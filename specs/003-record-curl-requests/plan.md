# Implementation Plan: Record Curl Requests with Token Traceability

**Branch**: `003-record-curl-requests` | **Date**: 2026-06-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-record-curl-requests/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Implement a mechanism to capture actual HTTP requests sent during reproduction flows and output them as valid `curl` commands. Each `curl` command must include shell comments indicating which values were dynamic tokens and the index/ID of the response they originated from.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `httpx` (for request interception/logging), `pydantic` (for data models).

**Storage**: Filesystem (`curls/req_NNNN.curl.sh` as per constitution).

**Testing**: `pytest`, `pytest-httpx`.

**Target Platform**: Linux.

**Project Type**: CLI.

**Performance Goals**: Minimal overhead on request execution.

**Constraints**: No network calls allowed in Token Tracker tests; must use pre-recorded fixtures.

**Scale/Scope**: Developer-focused reproduction tool.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Code Quality**: Use unit tests for curl formatting; decompose long functions; avoid circular deps.
- [x] **II. Testing Patterns**: Use `pytest-httpx` for mocking; no real network calls in tracker tests.
- [x] **III. Dependency Management**: Use `uv` exclusively.
- [x] **IV. Data Models**: `RecordedRequest` and `TokenTrace` MUST be Pydantic `BaseModel`.
- [x] **V. Error Handling**: Capture recording failures as non-fatal states.
- [x] **VI. CLI**: Output curls to `stdout` (or specified files), errors to `stderr`.
- [x] **VII. Runtime Artifacts**: Follow naming convention `curls/req_NNNN.curl.sh`.

## Project Structure

### Documentation (this feature)

```text
specs/003-record-curl-requests/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/
├── models/
│   └── request_record.py   # Pydantic models for RecordedRequest, TokenTrace
├── services/
│   └── curl_generator.py   # Logic to convert HTTP request to curl string with comments
└── cli/
    └── recorder.py         # Integration with CLI to output recorded requests
```

**Structure Decision**: Single project structure. The logic is split between data models for the record and a service for the curl formatting.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**
