# Confusion-Tension Topic Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a pool of comparison topics and deterministically select topics with strong confusion, surprise, and sharing tension while rejecting weak, unsafe, duplicate, or visually infeasible ideas.

**Architecture:** Extend topic candidates with structured editorial signals, then centralize eligibility, deduplication, filtering, and weighted ranking in a pure `TopicSelectionService`. Route both the multi-topic API service and the production reference generator through this selector, with one bounded repair attempt in production when the first pool has no eligible topic.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, existing async LLM provider interfaces.

## Global Constraints

- Preserve the existing public topic API response shape.
- Preserve manual topic overrides without automatic scoring.
- Do not alter research, scripting, rendering, publishing, or analytics behavior.
- Do not add another LLM judging call beyond the production generator's one bounded repair attempt.
- Use type hints throughout and add no source comments.
- Preserve unrelated working-tree changes.

---

### Task 1: Structured signals and deterministic selector

**Files:**
- Modify: `src/app/domain/models.py:20-27`
- Create: `src/app/services/topic_selection_service.py`
- Create: `tests/unit/test_topic_selection.py`

**Interfaces:**
- Produces: `TopicSignal(score: int, reason: str)`.
- Produces: `TopicSelectionSignals` with the seven approved signals.
- Produces: `TopicSelectionDecision(eligible: bool, score: float, reasons: tuple[str, ...])`.
- Produces: `TopicSelectionService.evaluate(candidate, allow_high_risk=False) -> TopicSelectionDecision`.
- Produces: `TopicSelectionService.select(candidates, existing_pairs=None, blacklist=None, allow_high_risk=False, limit=None) -> list[TopicCandidate]`.

- [ ] **Step 1: Write failing model and selector tests**

Add tests that construct complete signals, reject scores outside zero through five and blank reasons, confirm candidates without signals remain loadable but fail automatic eligibility, verify the exact weighted result, and cover every eligibility gate.

```python
def signals(**overrides: int) -> TopicSelectionSignals:
    values = {
        "common_confusion": 5,
        "everyday_familiarity": 4,
        "cultural_debate": 3,
        "surprising_payoff": 5,
        "shareability": 5,
        "visual_feasibility": 4,
        "research_risk": 1,
    }
    values.update(overrides)
    return TopicSelectionSignals(**{
        name: TopicSignal(score=score, reason=f"specific reason for {name}")
        for name, score in values.items()
    })


def test_selector_calculates_approved_weighted_score() -> None:
    candidate = TopicCandidate(
        title="Gem vs dulceață",
        left="Gem",
        right="Dulceață",
        angle="Textură și preparare",
        selection_signals=signals(),
    )
    decision = TopicSelectionService().evaluate(candidate)
    assert decision.eligible
    assert decision.score == 89.0
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest tests/unit/test_topic_selection.py -v`

Expected: collection failure because `TopicSignal`, `TopicSelectionSignals`, and `TopicSelectionService` do not exist.

- [ ] **Step 3: Implement the Pydantic signal models**

Add `TopicSignal` with `score: int = Field(ge=0, le=5)` and a stripped `reason` with minimum length one. Add the seven-field `TopicSelectionSignals` model. Add `selection_signals: Optional[TopicSelectionSignals] = None` to `TopicCandidate`.

- [ ] **Step 4: Implement the pure selection service**

Use the approved positive weights and ten-point research-risk penalty. Eligibility reasons must use stable strings for missing signals, weak confusion tension, weak payoff, weak visual feasibility, excessive research risk, and high topic risk. Normalize pair keys by Unicode-folding, removing diacritics and non-alphanumeric characters, sorting the two normalized item names, and joining them with `|`.

`select` must retain only the first occurrence of each unordered pair, exclude history and blacklisted items, evaluate candidates, sort eligible candidates by score and the approved tie breakers, preserve source order as the final tie breaker, and honor `limit`.

- [ ] **Step 5: Run selector tests and verify GREEN**

Run: `python -m pytest tests/unit/test_topic_selection.py -v`

Expected: all topic-selection tests pass.

---

### Task 2: Rank the general topic-service candidate pool

**Files:**
- Modify: `src/app/prompts/topic_generation.md`
- Modify: `src/app/services/topic_service.py:60-140`
- Modify: `tests/unit/test_script.py:146-162,396-466`

**Interfaces:**
- Consumes: `TopicSelectionService.select(...)` from Task 1.
- Preserves: `TopicService.generate_topics(...) -> list[TopicCandidate]`.
- Preserves: `TopicService.generate_unique_topics(...) -> list[TopicCandidate]`, now in ranked order.

- [ ] **Step 1: Update general-topic tests first**

Change mocked automatic candidates to include complete signal objects. Add an integration test where the LLM returns an obvious, low-tension topic first and a strong confusion topic second; assert the second topic becomes the first result. Add assertions that the prompt defines all seven signals, the zero-to-five scale, and pair-specific reasons.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/unit/test_script.py::TestTopicService::test_generate_topics_mock tests/unit/test_script.py::TestGenerateUniqueTopics -v`

Expected: ranking test fails because `generate_unique_topics` still preserves LLM order and prompt assertions fail because the scoring schema is absent.

- [ ] **Step 3: Update the general topic prompt**

Make confusion tension the first editorial requirement, explicitly reject obvious pairs, define all seven signals with calibrated zero/three/five meanings, require a pair-specific reason for each, and extend the JSON example with `selection_signals`.

- [ ] **Step 4: Integrate the selector into `TopicService`**

Construct a `TopicSelectionService` in `TopicService.__init__`, request `count * 2` candidates as before, and replace the manual history/deduplication loop with `select(candidates, existing_pairs=history.get_normalized_pairs(), blacklist=blacklist, limit=count)`. Keep standalone compatibility helpers such as `deduplicate`, `filter_by_risk`, and `filter_blacklist` unchanged for their existing callers and tests.

- [ ] **Step 5: Run general topic tests and verify GREEN**

Run: `python -m pytest tests/unit/test_script.py -v`

Expected: all script and topic-service tests pass.

---

### Task 3: Select from a production candidate pool with one repair attempt

**Files:**
- Modify: `src/app/services/reference_adapters.py:20-124,207-245`
- Modify: `tests/unit/test_reference_generation.py:47-70`
- Modify: `tests/unit/test_reference_proofreader.py:153-175`

**Interfaces:**
- Create: private `ReferenceTopicPool(BaseModel)` with `topics: list[TopicCandidate]` constrained to at most six entries.
- Consumes: `TopicSelectionService.select(...)` and `evaluate(...)`.
- Preserves: `ReferenceTopicGenerator.generate(request) -> TopicSpec`.

- [ ] **Step 1: Write failing production-pool tests**

Update the existing fake LLM to return a pool. Add tests proving that the generator selects the best of several candidates, supplies recent history to the selector, makes exactly one repair call when the initial pool is ineligible, raises a descriptive `RuntimeError` after two ineligible pools, and leaves `topic_override` on the existing no-LLM path.

- [ ] **Step 2: Run focused production tests and verify RED**

Run: `python -m pytest tests/unit/test_reference_generation.py -k "topic_generator" -v`

Expected: tests fail because the generator still requests one `TopicCandidate` and has no repair flow.

- [ ] **Step 3: Update the production prompt and response schema**

Require exactly six alternatives, add the confusion-tension rubric and signal schema, and replace the single-topic worked response with a `{"topics": [...]}` pool response. Preserve the Romanian-language and visual-production constraints.

- [ ] **Step 4: Implement selection and repair**

If `topic_override` exists, return `_parse_override` before any scoring or LLM call. Otherwise request `ReferenceTopicPool`, select against history, and return the first candidate. When none are eligible, build compact rejection notes from `evaluate`, make one temperature-zero repair request using schema name `reference_topic_repair`, select again, and raise `RuntimeError("No eligible confusion-tension topic after repair: ...")` if still empty.

- [ ] **Step 5: Preserve proofreading and history behavior**

Convert only the selected candidate to `TopicSpec`, proofread Romanian labels exactly once as before, and add only the final proofread topic to history.

- [ ] **Step 6: Run production-topic tests and verify GREEN**

Run: `python -m pytest tests/unit/test_reference_generation.py tests/unit/test_reference_proofreader.py -v`

Expected: all reference generation and proofreading tests pass.

---

### Task 4: Regression verification and handoff

**Files:**
- Verify all files modified in Tasks 1-3.

**Interfaces:**
- Produces no new interface; confirms repository compatibility.

- [ ] **Step 1: Run formatting and patch checks**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 2: Run all unit tests**

Run: `python -m pytest tests/ -v`

Expected: all tests pass with zero failures.

- [ ] **Step 3: Inspect the final diff scope**

Run: `git status --short` and `git diff --stat`

Expected: only topic-selection source, prompt, tests, and the implementation plan are new or modified in the isolated worktree.

- [ ] **Step 4: Report implementation details**

Summarize the new signals, gates, ranking behavior, production repair behavior, public API compatibility, and fresh verification results. Do not commit, push, or open a pull request unless the user requests it.
