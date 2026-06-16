# Feature Specification: HAR Flow Reproducer

**Feature Branch**: `feature/har-reproducer`
**Created**: 2026-06-16
**Status**: Draft

**Input**: User description: "Desenvolver o HAR Flow Reproducer, uma ferramenta de linha de comando em Python que lê um arquivo .har capturado pelo browser e reproduz o fluxo HTTP completo contra o servidor real na internet, chegando ao mesmo estado final da sessão original."

## Clarifications

### Session 2026-06-16
- Q: How should step files (request/response) be stored on disk? → A: Plaintext (JSON)
- Q: How are success criteria provided to the tool? → A: Configuration file (JSON/YAML)

## Design Decisions

### Baseline & Dynamic Detection
- **Baseline Execution**: The first request (`req[0]`) is executed exactly as recorded in the HAR without any analysis or Token Tracker involvement. It serves as the session's state zero.
- **Baseline Comparison**: Every subsequent request (`req[N]`) is compared against `req[0]` (not `req[N-1]`) to determine if a value is static or dynamic.
- **Forced Dynamic Patterns**: Fields matching any of these patterns (case-insensitive) are ALWAYS treated as dynamic, regardless of whether their value matches the baseline: `.*token.*`, `.*csrf.*`, `.*jwt.*`, `.*auth.*`, `.*session.*`, `.*nonce.*`, `.*secret.*`, `.*key.*`.

### Token Tracking & Search
- **Grep Search**: Search is performed using `grep -Frn --include=res_*.json -m 1` via subprocess, targeting only files in the `real_responses/` directory.
- **Search Priority**: If a value appears in multiple response files, the one with the lowest index (closest to `req[0]`) is preferred.
- **Prefix Handling**: For values starting with "Bearer " or "Token ", the search is performed on the inner value. The extractor reconstructs the prefix during injection (e.g., `Authorization: Bearer {{jwt_main}}`).
- **Decoding Sequence**: If a literal search fails, the tool attempts search using the URL-decoded value, then the Base64-decoded value. If all fail, the token is marked as `unresolved`.

### Extractor Lifecycle & Format
- **Extractor Registry**: The engine maintains an in-memory registry. If a verified extractor exists for a `token_id` (derived from the field name), it is reused.
- **Extractor Signature**: Extractors are standalone Python functions in `extractors/extract_<token_id>.py` with the signature: `def extract_<token_id>(response: dict) -> str`.
- **Response Interface**: The `response` dictionary contains: `headers` (dict), `cookies` (dict), `body` (str), `body_mime` (str), and `redirect_url` (str | None).
- **Error Handling**: Extractors MUST raise an `ExtractorError` if the value is not found.

### Failure Recovery & Diagnostics
- **Unresolved Tokens**: These are treated as static (HAR value used) in the generated curl files, with an accompanying warning comment. They are flagged in diagnostic logs and prioritized by the Diagnostic Agent.
- **Diagnostic Agent**: A tool-based LLM agent (not a chatbot) with capabilities to: read steps, grep steps, view session state, propose extraction rules, propose direct value injections, and propose extractor replacements.
- **Diagnostic Flow**: Receives a `FailureContext` and returns a `Patch`. The engine applies the patch and retries the step. Limit: 1 LLM attempt per step.

### Success Validation
- **Criteria Types**:
    - `url_match`: Regex match against final URL.
    - `status_code`: Exact status code match.
    - `body_contains`: Substring search in response body.
    - `html_element_present`: CSS selector check via BeautifulSoup.
    - `composite`: Logical AND of multiple criteria.
- **Timing**: Validation runs only on the final step of the flow.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - HAR Parsing and Decomposition (Priority: P1)

The user provides a `.har` file captured in an anonymous browser window. The tool must break this down into manageable steps to facilitate analysis and reproduction.

**Why this priority**: This is the foundational step. Without decomposition, the reproduction engine cannot track state or identify dynamic tokens.

**Independent Test**: Provide a valid `.har` file and verify that the output directory contains a sequence of request and response files (e.g., `req_0000.json`, `res_0000.json`) with decoded bodies.

**Acceptance Scenarios**:
1. **Given** a `.har` file, **When** the `parse` command is run, **Then** each entry is saved as separate request/response JSON files with 4-digit padded indices.
2. **Given** a `.har` file with base64 encoded bodies, **When** parsed, **Then** the output files contain the decoded plain text/binary content.
3. **Given** a `.har` file containing `OPTIONS` requests, **When** parsed, **Then** these requests are marked as skippable during reproduction.

---

### User Story 2 - Interleaved Reproduction & Token Tracking (Priority: P1)

The tool reproduces the flow against a live server, automatically detecting and propagating dynamic values (JWTs, Cookies, CSRF tokens) that change between sessions.

**Why this priority**: This is the core value proposition of the tool.

**Independent Test**: Reproduce a flow requiring a login and a subsequent authenticated request. Verify that the second request uses the token returned by the server in the first response, not the one from the original HAR.

**Acceptance Scenarios**:
1. **Given** a set of parsed steps, **When** the `run` command is executed, **Then** the first request (`req[0]`) is sent exactly as recorded (baseline).
2. **Given** a request with values different from the baseline, **When** the tool analyzes it, **Then** it classifies these values as "dynamic".
3. **Given** a dynamic value, **When** the tool searches previous real responses, **Then** it identifies the exact source (header, JSON field, HTML attribute, or script tag).

---

### User Story 3 - Verified Extractor Generation (Priority: P2)

The tool automatically generates reliable extraction logic for dynamic tokens using a TDD-driven approach with LLM assistance.

**Why this priority**: Manual extractor writing is the primary pain point this tool aims to eliminate.

**Independent Test**: For a identified dynamic token in a JSON response, verify that a standalone Python extractor is generated and passes its associated test using the real response value.

**Acceptance Scenarios**:
1. **Given** a dynamic token and its source, **When** an extractor is generated, **Then** a test is written first using the real value as the expected outcome.
2. **Given** a failing extractor test, **When** the LLM agent is invoked, **Then** it iterates (up to 5 times) until the extractor correctly retrieves the value.
3. **Given** different source types, **When** extracting, **Then** specialized agents are used for Set-Cookie, other headers, JSONPath, CSS selectors, and Regex.

---

### User Story 4 - Failure Recovery & Diagnosis (Priority: P2)

When reproduction fails, the tool attempts deterministic recovery before escalating to an LLM-based diagnostic agent.

**Why this priority**: Live servers are unpredictable; robust recovery is needed for high success rates.

**Independent Test**: Simulate a 401 Unauthorized error during a run where a JWT is available in the session. Verify the tool injects the JWT and retries the request.

**Acceptance Scenarios**:
1. **Given** a 401/403 error, **When** a JWT is available in the current session, **Then** the tool injects it and retries.
2. **Given** an unexpected redirect, **When** the tool detects it, **Then** it follows the redirect automatically.
3. **Given** a 400 error mentioning "csrf", **When** a CSRF token is available, **Then** the tool injects it and retries.
4. **Given** a failure that deterministic rules cannot fix, **When** `diagnose` is run, **Then** an LLM agent proposes a patch (extractor fix or manual injection) based on the failure context.

---

### User Story 5 - Dry-Run Analysis (Priority: P3)

The user can analyze a HAR file without making actual network calls to understand the complexity of the flow.

**Why this priority**: Allows users to validate if a flow is reproducible before committing to live execution.

**Independent Test**: Run the `run --dry-run` command. Verify that no network requests are made and a report is generated showing detected dynamic candidates and their sources.

**Acceptance Scenarios**:
1. **Given** a parsed HAR, **When** `--dry-run` is used, **Then** the tool uses HAR responses to simulate the reproduction logic.
2. **Given** a dry-run execution, **When** finished, **Then** a report lists dynamic candidates per step, found sources, and unresolved tokens.

---

### Edge Cases

- **Empty/Malformed HAR**: Tool should provide a clear error message during the `parse` phase.
- **Token not found in any response**: The tool should mark the token as `unresolved` and report it in the dry-run/final report.
- **Extractor loop limit reached**: If the LLM fails to generate a working extractor after 5 attempts, the token should be marked as unresolved.
- **Very large response bodies**: The search mechanism must handle large files without crashing due to memory limits.
- **Dynamic values in encrypted/obfuscated bodies**: The tool should identify these as unresolved if no clear pattern is found.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST decompose a `.har` file into separate `req_NNNN.json` and `res_NNNN.json` files, stored as plaintext JSON for maximum debuggability.
- **FR-002**: The tool MUST decode base64 encoded request/response bodies during parsing.
- **FR-003**: The tool MUST identify dynamic tokens by comparing requests against the first request (`req[0]`) as a baseline.
- **FR-004**: The tool MUST locate the origin of dynamic tokens in previous real responses using efficient disk-based searching.
- **FR-005**: The tool MUST generate standalone Python extractor functions for identified tokens.
- **FR-006**: The tool MUST use a TDD loop (Test -> Implement -> Verify) for extractor generation, with a maximum of 5 LLM attempts.
- **FR-007**: The tool MUST implement deterministic recovery for 401/403 (JWT), 400 (CSRF), and unexpected redirects.
- **FR-008**: The tool MUST provide an LLM-based diagnostic mode that proposes patches for failed steps.
- **FR-009**: The tool MUST implement a `--dry-run` mode that simulates token tracking using the original HAR responses.
- **FR-010**: The tool MUST validate the final state of the reproduced flow against user-defined success criteria (URL, status code, body text, or HTML element) provided via a configuration file (JSON/YAML).

### Key Entities

- **HAR Entry**: A single request-response pair from the original capture.
- **Step**: A decomposed pair of request and response files used for reproduction.
- **Dynamic Token**: A value in a request that differs from the baseline and must be extracted from a response.
- **Extractor**: A verified Python function capable of retrieving a specific token from a response.
- **Session State**: The current set of extracted tokens available for injection into subsequent requests.
- **Success Criterion**: A measurable condition that defines if the flow reached its destination.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Successfully reproduce a multi-step authenticated flow to its final state without manual intervention in 90% of standard cases.
- **SC-002**: Zero manual extractor code written by the user for tokens found in standard JSON or HTML responses.
- **SC-003**: Dry-run analysis completes in under 30 seconds for HAR files with up to 100 entries.
- **SC-004**: Recovery rules resolve at least 50% of common session-related failures (401/403/400) automatically.

## Assumptions

- The user provides a `.har` file captured in an anonymous browser window to ensure a clean baseline.
- The server being targeted allows the reproduction of the flow and does not implement aggressive anti-bot measures that block non-browser clients.
- An LLM API (e.g., Anthropic) is available for extractor generation and diagnosis.
- The reproduction environment has the necessary permissions to read/write files in the specified output directories.
