<!--
Sync Impact Report:
- Version change: None → 1.0.0
- Modified principles: Initial creation of 7 core principles
- Added sections: Core Principles, Governance
- Removed sections: None
- Templates requiring updates:
  - .specify/templates/plan-template.md ✅ (Constitution Check now references these principles)
  - .specify/templates/spec-template.md ✅ (No structural changes, but requirements must align)
  - .specify/templates/tasks-template.md ✅ (No structural changes, but tasks must align)
- Follow-up TODOs: None
-->
# HAR Flow Reproducer Constitution

## Core Principles

### I. Code Quality
- Every new code MUST have unit tests covering the happy path and explicit error cases defined in the plan.
- Functions MUST be decomposed if they exceed 30 lines, unless the complexity is an unbreakable domain logic (e.g., the Token Tracker 8-step pipeline).
- Circular dependencies are FORBIDDEN. Dependency hierarchy: `models.py` ← `session.py`, `grep_utils.py` ← `tracker.py`, `agents/` ← `engine.py` ← `cli.py`.
- All public functions MUST have a docstring specifying: inputs, return value, and non-obvious preconditions.

### II. Testing Patterns
- Test fixtures MUST replicate the exact runtime structure (`steps/` and `real_responses/` within each fixture folder). Test code MUST use the same paths as in production.
- Disk-dependent tests MUST use `pytest`'s `tmp_path`. No writing to fixed paths outside `tmp_path`.
- Token Tracker tests MUST NOT make network calls. "Real" responses MUST be pre-recorded files in fixtures.
- The agent TDD loop (`run_tdd_loop`) MUST be tested using Anthropic API mocks—never calling the real API.
- `pytest-httpx` is the ONLY allowed way to mock the HTTP server in engine tests.

### III. Dependency Management
- Package manager: `uv` exclusively. Direct `pip install` is FORBIDDEN.
- Production dependencies: `httpx`, `pydantic`, `beautifulsoup4`, `jsonpath-ng`.
- Development dependencies: `pytest`, `pytest-httpx`.
- Dependencies MUST be added via `uv add <dep>` or `uv add --dev <dep>`.

### IV. Data Models
- All public data models MUST be Pydantic `BaseModel` (not `dataclass`), unless explicitly justified. This ensures automatic validation and consistent JSON serialization.
- Generic `dict`s MUST NOT cross module boundaries. Modules MUST exchange Pydantic models.

### V. Error Handling
- Expected errors (e.g., token not found, extractor failing a test) are part of the normal flow and MUST NOT raise unhandled exceptions. They MUST be represented in model fields (e.g., `verified = False`, `unresolved: list[Candidate]`).
- Unexpected errors (e.g., file not found, invalid JSON) MUST raise specific exceptions with descriptive messages indicating the file path and current step.
- The LLM Agent is the last resort—it MUST only be activated after deterministic recovery rules fail.

### VI. CLI
- Subcommands: `parse`, `run`, `diagnose`. No default behavior without a subcommand.
- Flags MUST use the `--` prefix. Ambiguous positional flags are FORBIDDEN.
- Progress output MUST go to `stdout`. Errors MUST go to `stderr`.
- The `--dry-run` mode MUST NOT make network calls or modify files outside the specified output directory.

### VII. Runtime Artifacts
- `curls/req_NNNN.curl.sh`: One file per step, 4-digit padded index.
- `extractors/extract_<token_id>.py`: Fixed signature `extract_<token_id>(response: dict) -> str`, never modified by the agent.
- `extractor_tests/`: TDD tests generated before the code, running independently via `pytest extractor_tests/`.
- `real_responses/res_NNNN.json`: MUST NOT overwrite a file already saved in the same execution.

## Governance

The project constitution is the supreme guidance for all development. Amendments require a documented proposal and approval. Compliance is verified during every code review and PR.

**Version**: 1.0.0 | **Ratified**: 2026-06-16 | **Last Amended**: 2026-06-16
