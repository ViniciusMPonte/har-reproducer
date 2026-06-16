# Implementation Plan: HAR Flow Reproducer

**Branch**: `feature/har-reproducer` | **Date**: 2026-06-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-har-reproducer/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

The HAR Flow Reproducer is a Python CLI tool that reproduces HTTP flows from a `.har` file against a live server. It automatically detects dynamic tokens (JWTs, cookies, CSRF), finds their origins in previous real responses using `grep`, and generates verified Python extractors via a TDD loop with LLM assistance. It includes deterministic and LLM-based recovery for failed requests and validates the final state against user-defined criteria (URL, status code, body, or HTML element).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `httpx` (HTTP client), `pydantic` (data models), `beautifulsoup4` (HTML parsing), `jsonpath-ng` (JSON extraction)

**Storage**: Local filesystem for runtime artifacts: `steps/`, `real_responses/`, `curls/`, `extractors/`, `extractor_tests/`

**Testing**: `pytest`, `pytest-httpx` (for HTTP mocking)

**Target Platform**: Linux (utilizes `grep` via subprocess)

**Project Type**: CLI

**Performance Goals**: Dry-run analysis completes in under 30 seconds for HAR files with up to 100 entries.

**Constraints**:
- Token Tracker tests MUST NOT make network calls.
- LLM API calls MUST be mocked in tests.
- `uv` exclusively as package manager.

**Scale/Scope**: Reproduces one execution at a time; does not support WebSockets or OAuth browser popups.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Status | Note |
|-----------|-------------|--------|------|
| Code Quality | Unit tests for happy/error paths, <30 lines per func, no circular deps, docstrings | ✅ | Planned |
| Testing Patterns | Mirror runtime fixtures, `tmp_path` for disk, no network in Tracker tests, mock LLM API, `pytest-httpx` | ✅ | Planned |
| Dep Management | `uv` only, `httpx`, `pydantic`, `bs4`, `jsonpath-ng` | ✅ | Planned |
| Data Models | Pydantic `BaseModel`, no generic dicts across boundaries | ✅ | Planned |
| Error Handling | Expected errors in models, specific exceptions for unexpected, LLM as last resort | ✅ | Planned |
| CLI | `parse`, `run`, `diagnose`, `--` flags, stdout/stderr, `--dry-run` | ✅ | Planned |
| Runtime Artifacts | `req_NNNN.curl.sh`, `extract_<token_id>.py`, `res_NNNN.json` | ✅ | Planned |

## Project Structure

### Documentation (this feature)

```text
specs/001-har-reproducer/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
har_reproducer/
├── __init__.py
├── cli.py              # entry point
├── models.py           # Pydantic models
├── parser.py           # HAR Parser
├── session.py          # SessionStore
├── grep_utils.py       # Grep search logic
├── tracker.py          # Analysis pipeline (8 steps)
├── engine.py           # Execution & recovery
├── validator.py        # Success criteria validation
└── agents/
    ├── __init__.py
    ├── base.py         # BaseAgent & TDD loop
    ├── cookie_agent.py
    ├── header_agent.py
    ├── jsonpath_agent.py
    ├── css_agent.py
    └── regex_agent.py

tests/
├── __init__.py
├── conftest.py
├── fixtures/
│   ├── simple_flow.har
│   ├── complex_flow.har
│   ├── jwt_in_html.har
│   └── tracker/
│       ├── tracker_jwt_body/
│       ├── tracker_set_cookie/
│       ├── tracker_csrf_html/
│       ├── tracker_redirect_param/
│       ├── tracker_script_token/
│       ├── tracker_static_headers/
│       ├── tracker_unknown_origin/
│       ├── tracker_ambiguous/
│       └── tracker_complex_flow/
├── test_models.py
├── test_session.py
├── test_grep_utils.py
├── test_validator.py
├── parser/
│   ├── test_load_har.py
│   ├── test_decode_body.py
│   ├── test_parse_entry.py
│   ├── test_options_skip.py
│   ├── test_split_har.py
│   └── test_complex_flow.py
├── tracker/
│   ├── test_compare_baseline.py
│   ├── test_find_origin.py
│   ├── test_curl_template.py
│   ├── test_jwt_body.py
│   ├── test_set_cookie.py
│   ├── test_csrf_html.py
│   ├── test_redirect_param.py
│   ├── test_script_token.py
│   ├── test_static_headers.py
│   ├── test_unknown_origin.py
│   ├── test_ambiguous.py
│   ├── test_complex_flow.py
│   └── test_dry_run.py
├── agents/
│   ├── test_base.py
│   ├── test_cookie_agent.py
│   ├── test_jsonpath_agent.py
│   ├── test_css_agent.py
│   └── test_regex_agent.py
├── engine/
│   ├── test_build_request.py
│   ├── test_apply_extractors.py
│   ├── test_recovery.py
│   └── test_run_simple_flow.py
└── agent/
    ├── test_diagnose_jwt_html.py
    └── test_apply_patch.py
```

**Structure Decision**: Single project layout using the `har_reproducer` package. This follows the user's explicit implementation structure and separates core logic from the CLI and agent implementations.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Token Tracker pipeline (8 steps) | Domain logic is a linear pipeline of analysis, search, and generation that must be atomic for each step. | Splitting would complicate state management of the `extractor_registry` and `CurlTemplate`. |
