import httpx
from typing import Tuple
from .models import Step, StepRequest, StepResponse
from src.models.request_record import RecordedRequest
from src.services.curl_generator import CurlGenerator
import json
from pathlib import Path
from typing import List, Optional, Tuple
from .models import Step, StepRequest, StepResponse, SessionState, Extractor, Patch, StepAnalysis
from .session import SessionStore
from .tracker import TokenTracker
from .parser import HARParser
from .validator import Validator

class Engine:
    """
    The Execution Engine: Performs the HTTP requests and manages the loop.
    """
    def __init__(self, har_path: Path, output_dir: Path, config_path: Optional[Path] = None):
        self.har_path = har_path
        self.output_dir = output_dir
        self.real_responses_dir = output_dir / "real_responses"
        self.real_responses_dir.mkdir(parents=True, exist_ok=True)
        self.real_requests_dir = output_dir / "real_requests"
        self.real_requests_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_store = SessionStore()
        self.tracker = TokenTracker(self.real_responses_dir, self.session_store)
        self.validator = Validator()
        
        self.success_criteria = []
        if config_path and config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    from .models import SuccessCriterion
                    self.success_criteria = [SuccessCriterion(**c) for c in config.get("success_criteria", [])]
            except Exception as e:
                print(f"Error loading config: {e}")

    def run(self, dry_run: bool = False):
        """
        Main loop to reproduce the HAR flow.
        """
        har_data = HARParser.load_har(self.har_path)
        entries = har_data.get("log", {}).get("entries", [])
        
        # We need a baseline. Usually req[0].
        first_entry = HARParser.parse_entry(entries[0], 0)
        
        analyses = []
        last_response = None
        for i, entry in enumerate(entries):
            step = HARParser.parse_entry(entry, i)
            
            # Update tokens using verified extractors before execution
            self.update_session_tokens()
            
            if dry_run:
                print(f"Dry-run: Analyzing step {i}...")
                analysis = self.tracker.analyze_step(step, first_entry, is_dry_run=True)
                analyses.append(analysis)
                continue
                
            # Execute the step
            final_request, response = self.execute_step(step)
            step.response = response
            last_response = response
            
            # Save real request and response
            req_file = self.real_requests_dir / f"req_{i:04d}.json"
            req_file.write_text(final_request.model_dump_json(indent=2), encoding="utf-8")
            
            res_file = self.real_responses_dir / f"res_{i:04d}.json"
            res_file.write_text(response.model_dump_json(indent=2), encoding="utf-8")
            
            # Analyze and track tokens
            analysis = self.tracker.analyze_step(step, first_entry, is_dry_run=False)
            analyses.append(analysis)
            
            print(f"Step {i} completed with status {response.status_code}")
        
        if dry_run:
            self._generate_dry_run_report(analyses)
            return

        # Final Validation
        if last_response and self.success_criteria:
            is_success = self.validator.validate(last_response, self.success_criteria)
            print(f"\nFinal Validation Result: {'✓ SUCCESS' if is_success else '✗ FAILURE'}")
            return is_success
        
        return True

    def _generate_dry_run_report(self, analyses: List[StepAnalysis]):
        """
        Generates a report of dynamic tokens and their resolution status.
        """
        print("\n--- Dry-Run Analysis Report ---")
        print(f"Analyzed {len(analyses)} steps.")
        
        all_tokens = {}
        for analysis in analyses:
            for token in analysis.dynamic_tokens:
                all_tokens[token.token_id] = token
        
        print(f"Detected {len(all_tokens)} dynamic token candidates:")
        for tid, token in all_tokens.items():
            status = "✓ Resolved" if token.status == "Resolved" else "✗ Unresolved"
            origin = f" at step {token.origin_step}" if token.origin_step != -1 else ""
            print(f"- {tid}: {status}{origin} (Location: {token.location})")
        print("------------------------------\n")

    def update_session_tokens(self):
        """
        Runs all verified extractors and updates the session store.
        """
        for token_id, extractor in self.session_store.state.registry.items():
            if not extractor.verified or extractor.origin_step is None:
                continue
            
            # Load the actual response from our reproduction
            res_file = self.real_responses_dir / f"res_{extractor.origin_step:04d}.json"
            if res_file.exists():
                try:
                    response = json.loads(res_file.read_text(encoding="utf-8"))
                    value = self._run_extractor(extractor, response)
                    if value:
                        self.session_store.set_token(token_id, value)
                except Exception:
                    continue

    def _run_extractor(self, extractor: Extractor, response: dict) -> Optional[str]:
        """Executes the extractor code against a response and returns the result."""
        import sys
        import subprocess
        from pathlib import Path
        
        temp_file = Path(f"run_extractor_{extractor.token_id}.py")
        safe_token_id = extractor.token_id.replace("-", "_").replace(".", "_").replace(" ", "_")
        
        wrapped_code = f"""
import sys
import json
from typing import Dict

{extractor.code}

if __name__ == "__main__":
    response = {response}
    try:
        result = extract_{safe_token_id}(response)
        print(result)
    except Exception:
        sys.exit(1)
"""
        temp_file.write_text(wrapped_code)
        
        try:
            result = subprocess.run(
                [sys.executable, str(temp_file)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        finally:
            if temp_file.exists():
                temp_file.unlink()
        return None

    def handle_recovery(self, response: StepResponse) -> bool:
        """
        Attempts deterministic recovery for common failure codes.
        Returns True if a recovery action was taken that warrants a retry.
        """
        if response.status_code == 401:
            # 401 Unauthorized: Try to refresh all tokens from their origin responses
            print("Detected 401 Unauthorized. Attempting deterministic recovery (token refresh)...")
            self.update_session_tokens()
            return True
            
        if response.status_code == 400:
            # 400 Bad Request: Often means a token is malformed or missing.
            # We try token refresh as well, although it's less likely to work.
            print("Detected 400 Bad Request. Attempting deterministic recovery (token refresh)...")
            self.update_session_tokens()
            return True
            
        return False

    def apply_patch(self, patch: Patch):
        """
        Applies a patch provided by the Diagnostic Agent to the session or registry.
        """
        if patch.action == "INJECT_VALUE":
            if patch.target_token_id and patch.new_value:
                self.session_store.set_token(patch.target_token_id, patch.new_value)
                
        elif patch.action == "FIX_EXTRACTOR":
            if patch.target_token_id and patch.new_code:
                # Create a new extractor with updated code and mark as unverified
                from .models import Extractor
                current_extractor = self.session_store.state.registry.get(patch.target_token_id)
                agent_type = current_extractor.agent_type if current_extractor else "RegexAgent"
                
                self.session_store.state.registry[patch.target_token_id] = Extractor(
                    token_id=patch.target_token_id,
                    code=patch.new_code,
                    verified=False,
                    agent_type=agent_type,
                    origin_step=current_extractor.origin_step if current_extractor else None
                )
                
        elif patch.action == "REPLACE_EXTRACTOR":
            # Similar to FIX_EXTRACTOR but might change agent_type
            if patch.target_token_id and patch.new_code:
                from .models import Extractor
                self.session_store.state.registry[patch.target_token_id] = Extractor(
                    token_id=patch.target_token_id,
                    code=patch.new_code,
                    verified=False,
                    agent_type="RegexAgent", # Default or from a suggested agent_type
                    origin_step=None
                )

    def diagnose(self, step_index: int) -> Optional[Patch]:
        """
        Launches the Diagnostic Agent to find a fix for a failed step.
        """
        from .agents.diagnose_agent import DiagnoseAgent
        from .models import FailureContext
        
        # Construct failure context
        # In a real scenario, we'd use the actual failed response
        ctx = FailureContext(
            failed_step=step_index,
            request_attempted=StepRequest(url="dummy", method="GET"),
            response_received=StepResponse(status_code=401, headers={}, cookies={}, body="Unauthorized"),
            session_snapshot=self.session_store.state,
            active_extractors=list(self.session_store.state.registry.values())
        )
        
        agent = DiagnoseAgent(self, ctx)
        return agent.diagnose()

    def execute_step(self, step: Step) -> Tuple[StepRequest, StepResponse]:
        """
        Executes a single HTTP request using httpx with deterministic recovery.
        """
        max_attempts = 2
        for attempt in range(max_attempts):
            req = step.request
            
            # Interpolate tokens from session store
            headers = self.session_store.render_dict(req.headers)
            # Filter out HTTP/2 pseudo-headers (those starting with ':')
            headers = {k: v for k, v in headers.items() if not k.startswith(':')}
            cookies = self.session_store.render_dict(req.cookies)
            body = self.session_store.render(req.body) if req.body else None
            
            # Create the final request object that was actually sent
            final_request = StepRequest(
                url=req.url,
                method=req.method,
                headers=headers,
                cookies=cookies,
                body=body,
                is_skippable=req.is_skippable
            )
            
            # --- Recording Start ---
            # Create a RecordedRequest for the current interaction
            recorded_req = RecordedRequest(
                step_index=step.index,
                url=final_request.url,
                method=final_request.method,
                headers=final_request.headers,
                cookies=final_request.cookies,
                body=final_request.body
            )
            # Generate the curl command with session context for token tracing
            curl_cmd = CurlGenerator().generate(recorded_req, session_store=self.session_store)
            
            # Save to file as per constitution: curls/req_NNNN.curl.sh
            import os
            os.makedirs("curls", exist_ok=True)
            filename = f"curls/req_{step.index:04d}.curl.sh"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"#!/bin/bash\n{curl_cmd}\n")
            # --- Recording End ---

            
            with httpx.Client(follow_redirects=False) as client:
                resp = client.request(
                    method=final_request.method,
                    url=final_request.url,
                    headers=final_request.headers,
                    cookies=final_request.cookies,
                    content=final_request.body.encode("utf-8") if final_request.body else None
                )

                
                # Force status_code to be int in case of weird mock behavior
                status_code = resp.status_code
                if not isinstance(status_code, int):
                    try:
                        status_code = int(status_code)
                    except (TypeError, ValueError):
                        if hasattr(status_code, 'status_code'):
                            status_code = status_code.status_code
                        else:
                            status_code = 500
                
                response = StepResponse(
                    status_code=status_code,
                    headers=dict(resp.headers),
                    cookies=dict(client.cookies),
                    body=resp.text,
                    body_mime=resp.headers.get("Content-Type"),
                    redirect_url=resp.headers.get("Location")
                )
            
            # If it's the first attempt and we fail, try deterministic recovery
            if attempt == 0 and self.handle_recovery(response):
                print(f"Deterministic recovery successful for step {step.index}. Retrying request...")
                continue
                
            return final_request, response
