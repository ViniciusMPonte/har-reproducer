# Feature Specification: Record Curl Requests with Token Traceability

**Feature Branch**: `003-record-curl-requests`

**Created**: 2026-06-16

**Status**: Draft

**Input**: User description: "Grave as requests reais no formato de comando curl, com comentários falando quais foram os tokens dinamicos inseridos e de quais responses eles vieram."

## Clarifications

### Session 2026-06-16
- Q: How should sensitive headers be handled? → A: Record everything exactly as sent

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Record Basic Requests (Priority: P1)

As a developer, I want to see the actual HTTP requests made by the system in a format I can easily reuse, so that I can debug the communication between the system and the API.

**Why this priority**: This is the core requirement. Without capturing the requests in curl format, the feature provides no value.

**Independent Test**: Run a simple flow that makes one API request and verify that a corresponding `curl` command is output.

**Acceptance Scenarios**:

1. **Given** a flow is executed, **When** an HTTP request is sent, **Then** the system outputs a valid `curl` command representing that request.
2. **Given** a request with headers and a body, **When** it is recorded, **Then** the `curl` command includes all relevant headers and the request body.

---

### User Story 2 - Trace Dynamic Tokens (Priority: P1)

As a developer, I want to know where the dynamic values in a request came from, so that I can understand the dependency chain between different API calls.

**Why this priority**: This is the "special sauce" of the feature. Simply recording curls is easy; tracing the tokens is the main goal.

**Independent Test**: Run a flow where Request B uses a token extracted from Request A's response. Verify that the `curl` command for Request B contains a comment tracing the token back to Request A.

**Acceptance Scenarios**:

1. **Given** a request contains a value that was dynamically extracted from a previous response, **When** the request is recorded as a `curl` command, **Then** a comment is added above or beside the value indicating its source response.
2. **Given** multiple dynamic tokens in a single request, **When** recorded, **Then** each token is individually traced to its respective source.

---

### Edge Cases

- What happens when a token is used across multiple requests? (Each request should still show the trace to the original source response).
- How does the system handle tokens that are modified after extraction? (The comment should indicate the original source).
- What happens if the source response is no longer available in memory? (The system should still record the source identifier if possible).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST capture real HTTP requests sent during execution.
- **FR-002**: System MUST format captured requests as valid `curl` commands.
- **FR-003**: System MUST identify dynamic tokens inserted into requests.
- **FR-004**: System MUST track the source (previous response) of each dynamic token.
- **FR-005**: System MUST add comments to the `curl` output indicating which tokens were dynamic and their origin response.
- **FR-006**: System MUST record all headers exactly as sent without masking.

### Key Entities *(include if feature involves data)*

- **RecordedRequest**: Represents a captured HTTP request, including its method, URL, headers, body, and associated token traces.
- **TokenTrace**: Represents the mapping between a value in a request and the response from which it was extracted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of recorded requests are valid `curl` commands that can be executed manually.
- **SC-002**: 100% of dynamic tokens used in requests are accompanied by a comment tracing them back to their source response.
- **SC-003**: The traceability comments clearly identify the source response (e.g., by request index or a unique identifier).

## Assumptions

- The system already has a mechanism for identifying and tracking dynamic tokens.
- "Real requests" refers to the actual network traffic generated during the execution of a reproduction flow.
- The primary output target is the console or a log file for developer review.
- The format of the comments will be standard shell comments (`#`).
- No masking or scrubbing of sensitive headers (e.g., Authorization) will be performed.
