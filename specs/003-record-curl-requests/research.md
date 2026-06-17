# Research: Record Curl Requests with Token Traceability

## Context
The goal is to capture actual HTTP requests during reproduction and output them as `curl` commands with comments tracing dynamic tokens to their source responses.

## Findings & Decisions

### 1. Request Interception
**Decision**: Intercept in `har_reproducer/engine.py` within the `execute_step` method.
**Rationale**: `execute_step` is the central point where token interpolation happens (rendering `StepRequest` into a final request) and where the network call is made via `httpx`. Capturing here ensures we have the "real" request sent and the resulting response.
**Alternatives**: `httpx` Event Hooks. Rejected because we need access to the `SessionStore` and `Step` context which are already available in `execute_step`.

### 2. Curl Formatting
**Decision**: Create a `CurlGenerator` service.
**Rationale**: Decouples the logic of translating an `httpx` request into a `curl` string from the execution engine. This allows for easy unit testing of the formatting logic.
**Approach**: 
- Convert headers and cookies to `-H` and `--cookie` flags.
- Convert the body to `-d` or `--data-binary`.
- Handle different HTTP methods.

### 3. Token Traceability
**Decision**: Use `DynamicToken.origin_step` from `har_reproducer/models.py`.
**Rationale**: The system already tracks which step produced a token via the `DynamicToken` model.
**Implementation**: 
- During `render` in `SessionStore`, we need a way to track which tokens were actually used.
- The `CurlGenerator` will cross-reference the final request values with the current session state and `DynamicToken` registry to identify interpolated values.
- For each identified token, add a comment: `# Token {{token_id}} comes from response of step {origin_step}`.

### 4. Runtime Artifacts
**Decision**: Follow the constitution's requirement for `curls/req_NNNN.curl.sh`.
**Rationale**: Maintains consistency with existing project standards.

## Resolved Clarifications
- **Sensitive Headers**: User requested to record everything exactly as sent (no masking). This will be implemented as a direct mapping of all headers.
