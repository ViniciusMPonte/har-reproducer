---
description: "Task list template for feature implementation"
---

# Tasks: HAR Flow Reproducer

**Input**: Design documents from `/specs/001-har-reproducer/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: TDD approach requested for extractors and comprehensive test suites for all modules.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Initialize project with `uv init har-reproducer` (pyproject.toml, .python-version)
- [X] T002 Create package structure: `har_reproducer/` and `tests/` directories
- [X] T003 [P] Configure `pytest.ini` with `testpaths = tests` and `pythonpath = .`
- [X] T004 [P] Create `tests/conftest.py` with fixtures: `tmp_steps_dir`, `tmp_real_responses_dir`, `load_fixture`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

- [X] T005 [P] Implement Pydantic models in `har_reproducer/models.py` (Step, SessionState, DynamicToken, Extractor, StepAnalysis, SuccessCriterion, FailureContext, Patch)
- [X] T006 [P] Implement `SessionStore` in `har_reproducer/session.py` (set, get, render, render_dict)
- [X] T007 [P] Implement `grep_in_real_responses` and variant search in `har_reproducer/grep_utils.py`
- [X] T008 [P] Implement `SuccessCriteria` and `validate` logic in `har_reproducer/validator.py`
- [X] T009 Implement `HAR Parser` in `har_reproducer/parser.py` (split_har, load_har, parse_entry, decode_body)
- [X] T010 Implement `analyze_step` pipeline in `har_reproducer/tracker.py` (8 stages)
- [X] T011 Implement `run` and `execute_step` core logic in `har_reproducer/engine.py`
- [X] T012 Implement `cli.py` entry point with `argparse` subcommands (parse, run, diagnose)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - HAR Parsing and Decomposition (Priority: P1) 🎯 MVP

**Goal**: Decompose HAR into a sequence of request/response JSON files.
**Independent Test**: Verify `parse` command generates `req_NNNN.json` and `res_NNNN.json` with decoded bodies.

### Tests for User Story 1
- [X] T013 [P] [US1] Test `load_har` and `parse_entry` in `tests/parser/test_parse_entry.py`
- [X] T014 [P] [US1] Test `decode_body` with base64 content in `tests/parser/test_decode_body.py`
- [X] T015 [P] [US1] Test `split_har` output structure in `tests/parser/test_split_har.py`
- [X] T016 [P] [US1] Test `OPTIONS` request skipping in `tests/parser/test_options_skip.py`

### Implementation for User Story 1
- [X] T017 [US1] Implement `split_har` in `har_reproducer/parser.py`
- [X] T018 [US1] Implement `decode_body` in `har_reproducer/parser.py`
- [X] T019 [US1] Implement `parse` subcommand in `har_reproducer/cli.py`

---

## Phase 4: User Story 2 - Interleaved Reproduction & Token Tracking (Priority: P1)

**Goal**: Reproduce flow and automatically detect/propagate dynamic tokens.
**Independent Test**: Reproduce a login flow; verify second request uses token from live response.

### Tests for User Story 2
- [X] T020 [P] [US2] Test baseline comparison logic in `tests/tracker/test_compare_baseline.py`
- [X] T021 [P] [US2] Test `find_origin` using grep in `tests/tracker/test_find_origin.py`
- [X] T022 [P] [US2] Test `CurlTemplate` generation in `tests/tracker/test_curl_template.py`
- [X] T023 [P] [US2] Test `dry_run` simulation in `tests/tracker/test_dry_run.py`

### Implementation for User Story 2
- [X] T024 [US2] Implement baseline comparison in `har_reproducer/tracker.py`
- [X] T025 [US2] Implement dynamic token candidate detection in `har_reproducer/tracker.py`
- [X] T026 [US2] Implement `CurlTemplate` logic in `har_reproducer/tracker.py`
- [X] T027 [US2] Implement `run` loop in `har_reproducer/engine.py` (execute $\rightarrow$ save $\rightarrow$ analyze $\rightarrow$ repeat)
- [X] T028 [US2] Implement `--dry-run` mode in `har_reproducer/engine.py`

---

## Phase 5: User Story 3 - Verified Extractor Generation (Priority: P2)

**Goal**: Generate reliable Python extractors via TDD and LLM.
**Independent Test**: Verify a generated extractor passes its test and correctly retrieves a token from a live response.

### Tests for User Story 3
- [X] T029 [P] [US3] Test `BaseAgent` TDD loop in `tests/agents/test_base.py`
- [X] T030 [P] [US3] Test `CookieAgent` in `tests/agents/test_cookie_agent.py`
- [X] T031 [P] [US3] Test `JSONPathAgent` in `tests/agents/test_jsonpath_agent.py`
- [X] T032 [P] [US3] Test `CSSAgent` in `tests/agents/test_css_agent.py`
- [X] T033 [P] [US3] Test `RegexAgent` in `tests/agents/test_regex_agent.py`

### Implementation for User Story 3
- [X] T034 [US3] Implement `BaseAgent` and `run_tdd_loop` in `har_reproducer/agents/base.py`
- [X] T035 [P] [US3] Implement `CookieAgent` in `har_reproducer/agents/cookie_agent.py`
- [X] T036 [P] [US3] Implement `HeaderAgent` in `har_reproducer/agents/header_agent.py`
- [X] T037 [P] [US3] Implement `JSONPathAgent` in `har_reproducer/agents/jsonpath_agent.py`
- [X] T038 [P] [US3] Implement `CSSAgent` in `har_reproducer/agents/css_agent.py`
- [X] T039 [P] [US3] Implement `RegexAgent` in `har_reproducer/agents/regex_agent.py`
- [X] T040 [US3] Integrate extractor generation into `analyze_step` in `har_reproducer/tracker.py`
- [X] T041 [US3] Implement extractor registry and reuse logic in `har_reproducer/engine.py`

---

## Phase 6: User Story 4 - Failure Recovery & Diagnosis (Priority: P2)

**Goal**: Recover from failed requests using deterministic rules and a diagnostic agent.
**Independent Test**: Simulate a 401 error and verify the tool injects a session JWT and retries successfully.

### Tests for User Story 4
- [ ] T042 [P] [US4] Test deterministic recovery rules (401, 400) in `tests/engine/test_recovery.py`
- [ ] T043 [P] [US4] Test `diagnose` agent patch application in `tests/agent/test_apply_patch.py`
- [ ] T044 [P] [US4] Test diagnostic agent with `jwt_in_html.har` fixture in `tests/agent/test_diagnose_jwt_html.py`

### Implementation for User Story 4
- [ ] T045 [US4] Implement deterministic recovery logic in `har_reproducer/engine.py`
- [ ] T046 [US4] Implement `FailureContext` and `Patch` models in `har_reproducer/models.py`
- [ ] T047 [US4] Implement `diagnose` agent with tool-use in `har_reproducer/agents/diagnose_agent.py` (or within agents package)
- [ ] T048 [US4] Implement `diagnose` subcommand in `har_reproducer/cli.py`
- [ ] T049 [US4] Integrate recovery flow into `execute_step` in `har_reproducer/engine.py`

---

## Phase 7: User Story 5 - Dry-Run Analysis (Priority: P3)

**Goal**: Analyze HAR complexity without network calls.
**Independent Test**: Run `run --dry-run` and verify the generated report of dynamic candidates and origins.

### Implementation for User Story 5
- [ ] T050 [US5] Implement dry-run report generation in `har_reproducer/engine.py`
- [ ] T051 [US5] Implement simulation of `analyze_step` using HAR responses in `har_reproducer/tracker.py`

---

## Phase 8: Final Polish & Validation

**Purpose**: Cross-cutting concerns and final validation

- [ ] T052 [P] Implement success validation logic in `har_reproducer/validator.py`
- [ ] T053 [P] Implement final success check in `har_reproducer/engine.py`
- [ ] T054 [P] Implement final output of results to stdout in `har_reproducer/cli.py`
- [ ] T055 [P] Add docstrings to all public functions per constitution
- [ ] T056 [P] Run final linting and type checking

---

## Dependencies & Execution Order

### Phase Dependencies
- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories.
- **User Stories (Phase 3-7)**: Depend on Foundational.
  - US1 (Parsing) $\rightarrow$ US2 (Tracking) $\rightarrow$ US3 (Extractors) $\rightarrow$ US4 (Recovery) $\rightarrow$ US5 (Dry-Run)
- **Polish (Final Phase)**: Depends on all stories.

### Within Each User Story
- Tests $\rightarrow$ Models $\rightarrow$ Services $\rightarrow$ Integration.

### Parallel Opportunities
- All [P] tasks within a phase can be run in parallel.
- Independent agents in US3 can be implemented in parallel.

---

## Implementation Strategy

### MVP First (User Story 1 & 2)
1. Complete Setup and Foundational phases.
2. Implement US1 (Parsing) and US2 (Basic Tracking).
3. Validate basic reproduction of a non-authenticated flow.

### Incremental Delivery
1. Add US3 (LLM Extractors) $\rightarrow$ enable authenticated flows.
2. Add US4 (Recovery) $\rightarrow$ handle live server instability.
3. Add US5 (Dry-Run) $\rightarrow$ enable pre-flight analysis.
4. Add final validation $\rightarrow$ automate success check.
