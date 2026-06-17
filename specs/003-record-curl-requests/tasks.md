# Tasks: Record Curl Requests with Token Traceability

**Input**: Design documents from `/specs/003-record-curl-requests/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, quickstart.md

**Tests**: Tests are not explicitly requested in the feature specification; focusing on implementation and verification via independent tests described in the spec.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create directory structure for the feature if missing (src/models, src/services, src/cli)
- [ ] T002 [P] Verify `httpx` and `pydantic` versions in pyproject.toml

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

- [ ] T003 Create `RecordedRequest` and `TokenTrace` models in src/models/request_record.py (based on data-model.md)
- [ ] T004 Create `CurlGenerator` class in src/services/curl_generator.py with basic structure
- [ ] T005 [P] Implement basic HTTP to curl conversion in src/services/curl_generator.py (method, URL, basic headers)

**Checkpoint**: Foundation ready - user story implementation can begin

---

## Phase 3: User Story 1 - Record Basic Requests (Priority: P1) 🎯 MVP

**Goal**: Capture real HTTP requests as valid `curl` commands.

**Independent Test**: Run a flow with one API request and verify a valid `curl` command is output to the console/file.

### Implementation for User Story 1

- [ ] T006 [US1] Implement full header and cookie conversion in src/services/curl_generator.py
- [ ] T007 [US1] Implement request body conversion (JSON/Form) in src/services/curl_generator.py
- [ ] T008 [US1] Integrate `CurlGenerator` into `har_reproducer/engine.py` in the `execute_step` method
- [ ] T009 [US1] Implement output logic to save curls to `curls/req_NNNN.curl.sh` (as per constitution)
- [ ] T010 [US1] Verify a simple flow generates valid, executable `curl` commands

**Checkpoint**: User Story 1 is fully functional and testable independently

---

## Phase 4: User Story 2 - Trace Dynamic Tokens (Priority: P1)

**Goal**: Add traceability comments to `curl` commands for dynamic tokens.

**Independent Test**: Run a flow where Request B uses a token from Request A; verify the `curl` for Request B contains a comment tracing the token back to Request A.

### Implementation for User Story 2

- [ ] T011 [US2] Implement token detection logic in src/services/curl_generator.py (comparing final request values vs session state)
- [ ] T012 [US2] Implement token trace resolution in src/services/curl_generator.py (mapping tokens to `DynamicToken.origin_step`)
- [ ] T013 [US2] Implement comment generation for tokens in src/services/curl_generator.py (formatting as `# Token {id} comes from response of step {index}`)
- [ ] T014 [US2] Integrate trace comments into the final `curl` output in src/services/curl_generator.py
- [ ] T015 [US2] Verify traceability comments are correctly added for multiple dynamic tokens in a single request

**Checkpoint**: User Story 2 is fully functional and testable independently

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T016 [P] Run `quickstart.md` validation and ensure documentation matches implementation
- [ ] T017 [P] Refactor `curl_generator.py` for better maintainability if needed
- [ ] T018 [P] Ensure no secrets are leaked in the `curl` output beyond what is explicitly recorded (per FR-006)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 and US2 can proceed sequentially (US1 first)
- **Polish (Final Phase)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2)
- **User Story 2 (P1)**: Can start after User Story 1 (needs basic curl formatting to be ready)

### Within Each User Story

- Models before services
- Services before integration
- Core implementation before verification

### Parallel Opportunities

- Setup tasks T001, T002 can run in parallel.
- Foundational task T005 can run in parallel with T003/T004 if the interface is defined.
- T016, T017, T018 (Polish) can run in parallel.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Verify basic `curl` output.

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Verifybasic curls → Deliver MVP
3. Add User Story 2 → Verify token traces → Deliver full feature

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify curls are valid shell scripts
- Commit after each task or logical group
