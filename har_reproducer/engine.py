import httpx
import json
from pathlib import Path
from typing import List, Optional
from .models import Step, StepRequest, StepResponse, SessionState
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
        
        self.session_store = SessionStore()
        self.tracker = TokenTracker(self.real_responses_dir, self.session_store)
        self.validator = Validator()

    def run(self, dry_run: bool = False):
        """
        Main loop to reproduce the HAR flow.
        """
        har_data = HARParser.load_har(self.har_path)
        entries = har_data.get("log", {}).get("entries", [])
        
        # We need a baseline. Usually req[0].
        first_entry = HARParser.parse_entry(entries[0], 0)
        
        for i, entry in enumerate(entries):
            step = HARParser.parse_entry(entry, i)
            
            # Update tokens using verified extractors before execution
            self.update_session_tokens()
            
            if dry_run:
                print(f"Dry-run: Analyzing step {i}...")
                self.tracker.analyze_step(step, first_entry)
                continue
                
            # Execute the step
            response = self.execute_step(step)
            step.response = response
            
            # Save real response
            res_file = self.real_responses_dir / f"res_{i:04d}.json"
            res_file.write_text(response.model_dump_json(indent=2), encoding="utf-8")
            
            # Analyze and track tokens
            self.tracker.analyze_step(step, first_entry)
            
            print(f"Step {i} completed with status {response.status_code}")

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

    def execute_step(self, step: Step) -> StepResponse:
        """
        Executes a single HTTP request using httpx.
        """
        req = step.request
        
        # Interpolate tokens from session store
        headers = self.session_store.render_dict(req.headers)
        cookies = self.session_store.render_dict(req.cookies)
        body = self.session_store.render(req.body) if req.body else None
        
        with httpx.Client(follow_redirects=False) as client:
            resp = client.request(
                method=req.method,
                url=req.url,
                headers=headers,
                cookies=cookies,
                content=body.encode("utf-8") if body else None
            )
            
            return StepResponse(
                status_code=resp.status_code,
                headers=dict(resp.headers),
                cookies=client.cookies.get_dict(),
                body=resp.text,
                body_mime=resp.headers.get("Content-Type"),
                redirect_url=resp.headers.get("Location")
            )
