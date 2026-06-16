# Data Model: HAR Flow Reproducer

## Core Entities

### 1. Step (Request/Response Pair)
Represents a single atomic interaction in the HTTP flow.
- **Request**:
    - `url`: str
    - `method`: str
    - `headers`: dict[str, str]
    - `cookies`: dict[str, str]
    - `body`: str | bytes
    - `is_skippable`: bool (True if OPTIONS request)
- **Response**:
    - `status_code`: int
    - `headers`: dict[str, str]
    - `cookies`: dict[str, str]
    - `body`: str | bytes
    - `body_mime`: str
    - `redirect_url`: str | None

### 2. SessionState
The current global state of the reproduction session.
- **tokens**: dict[token_id, current_value]
- **registry**: dict[token_id, ExtractorMetadata]

### 3. DynamicToken (Candidate)
A value identified as dynamic during the analysis of a step.
- **token_id**: str (derived from field name)
- **baseline_value**: str | None
- **current_value**: str
- **location**: `TokenLocation` (Header, Cookie, BodyJSON, BodyHTML, Script)
- **origin_step**: int (index of the response where the value was found)
- **status**: `Resolved` | `Unresolved`

### 4. Extractor
A verified piece of logic to retrieve a token.
- **token_id**: str
- **code**: str (the Python function source)
- **verified**: bool
- **agent_type**: `CookieAgent` | `HeaderAgent` | `JSONPathAgent` | `CSSAgent` | `RegexAgent`

### 5. StepAnalysis
The result of the `analyze_step` pipeline.
- **step_index**: int
- **static_values**: dict[field, value]
- **dynamic_tokens**: list[DynamicToken]
- **curl_template**: str (The final .curl.sh content)

### 6. SuccessCriterion
Defines if the reproduction reached the target state.
- **type**: `url_match` | `status_code` | `body_contains` | `html_element_present` | `composite`
- **value**: Any (regex, int, substring, CSS selector)
- **expected**: Any

### 7. FailureContext & Patch
Used by the Diagnostic Agent.
- **FailureContext**:
    - `failed_step`: int
    - `request_attempted`: StepRequest
    - `response_received`: StepResponse
    - `session_snapshot`: SessionState
    - `active_extractors`: list[Extractor]
- **Patch**:
    - `action`: `FIX_EXTRACTOR` | `INJECT_VALUE` | `REPLACE_EXTRACTOR`
    - `target_token_id`: str | None
    - `new_value`: str | None
    - `new_code`: str | None
    - `rationale`: str

## Validation Rules

- All entities MUST be Pydantic `BaseModel`s.
- `Extractor` code MUST strictly follow the signature: `def extract_<token_id>(response: dict) -> str`.
- `SessionState` MUST be the only way to pass dynamic values between the `tracker` and the `engine`.
