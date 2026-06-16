# Research: HAR Flow Reproducer

## 1. HTTP Reproduction with `httpx`
- **Decision**: Use `httpx` as the sole HTTP client.
- **Rationale**: Support for HTTP/2 is critical for modern web flows. `httpx` provides a cleaner API than `urllib3` and is more modern than `requests`. It allows fine-grained control over headers and cookies, which is essential for session reproduction.
- **Alternatives Considered**: `requests` (no HTTP/2), `urllib` (too low-level).

## 2. Data Modeling with `pydantic`
- **Decision**: Use `pydantic.BaseModel` for all public data structures.
- **Rationale**: Ensures strict type validation and consistent JSON serialization. This is critical for the `SessionStore` and `StepAnalysis` where data integrity across the pipeline is paramount.
- **Alternatives Considered**: `dataclasses` (lack of built-in validation/serialization).

## 3. HTML & JSON Extraction
- **Decision**: Use `beautifulsoup4` for CSS selectors and `jsonpath-ng` for JSONPath.
- **Rationale**: These are industry-standard libraries for parsing structured content. `jsonpath-ng` allows for complex queries in JSON bodies, and `BeautifulSoup` provides robust HTML navigation even with malformed markup.
- **Alternatives Considered**: `lxml` (more complex setup), `json` module with manual traversal (too brittle for dynamic paths).

## 4. LLM-Driven TDD Loop for Extractors
- **Decision**: Implementation of a `run_tdd_loop` that generates a test first, then an extractor, and iterates based on pytest results.
- **Rationale**: LLMs can produce syntactically correct but logically flawed code. A TDD loop ensures the extractor is verified against the *real* response value before being marked as `verified = True`.
- **Verification Strategy**: Execute the generated extractor function using `exec()` or a dedicated subprocess within a controlled environment, passing the real response dict and asserting the result.

## 5. Disk-Based Token Search
- **Decision**: Use `grep -Frn` via `subprocess` for searching tokens in `real_responses/`.
- **Rationale**: Searching through potentially large JSON/HTML files in memory would lead to high RAM usage. `grep` is highly optimized for this task. Using `-m 1` ensures we find the first occurrence (closest to the baseline).
- **Decoding Strategy**: Search sequence: Literal $\rightarrow$ URL-decoded $\rightarrow$ Base64-decoded. This covers the most common ways tokens are encoded in HTTP traffic.

## 6. Diagnostic Agent Architecture
- **Decision**: Tool-use based LLM agent for failure recovery.
- **Rationale**: A chatbot is insufficient. The agent needs to "see" the state of the filesystem and session. Providing tools like `read_step` and `grep_responses` allows the LLM to perform root-cause analysis and propose a precise `Patch`.
- **Constraint**: Limit to 1 attempt per step to prevent infinite loops and reduce API cost.
