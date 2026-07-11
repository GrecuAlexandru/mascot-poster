# Step 4 — Phase 4: Research and Verification

> Goal of this step: ground generated scripts in real evidence. Collect sources,
> build a research package, and run a separate verification pass on every claim.

Sections in this step:

- [Phase 4 milestone](#phase-4-research-and-verification)
- [10. Research Pipeline](#10-research-pipeline)
- [12. Fact Verification](#12-fact-verification)

---

## Phase 4: Research and verification

Add:

- Search provider
- Page extraction
- Research package
- Source storage
- Claim verification
- Risk rules

Deliverable:

- Script is grounded in stored sources

---

## 10. Research Pipeline

The research service must not allow the LLM to invent facts without evidence.

### Research stages

1. Build search queries
2. Call search provider
3. Retrieve relevant pages
4. Extract readable text
5. Score sources
6. Deduplicate information
7. Summarize supported facts
8. Store all sources
9. Generate a research package

### Source priority

Prefer:

1. Official product or manufacturer documentation
2. Government sources
3. Scientific or academic sources
4. Reputable reference sites
5. High-quality journalism
6. Retail product listings for visual or ingredient information

Avoid using:

- Random low-quality blogs
- Scraped AI-generated pages
- Unsourced social posts
- Other TikTok creators as factual sources

### Research package schema

```python
class ResearchPackage(BaseModel):
    topic: str
    left_item: str
    right_item: str
    facts: list["ResearchFact"]
    sources: list["SourceReference"]
    unresolved_questions: list[str]
    safety_notes: list[str]
```

```python
class ResearchFact(BaseModel):
    text: str
    source_ids: list[str]
    confidence: float
    applies_to: Literal["left", "right", "both", "general"]
```

If unresolved questions remain, the job should stop or request a safer topic angle.

---

## 12. Fact Verification

After script generation, run a separate verification pass.

The verifier receives:

- Final narration
- List of claims
- Research facts
- Sources
- Topic constraints

It returns:

```python
class VerificationResult(BaseModel):
    approved: bool
    claim_results: list["ClaimVerification"]
    required_changes: list[str]
```

```python
class ClaimVerification(BaseModel):
    claim_id: str
    supported: bool
    source_ids: list[str]
    explanation: str
    severity: Literal["none", "minor", "major"]
```

Rules:

- Any unsupported major claim fails the job
- Medical, financial, legal, or safety-sensitive claims require stricter thresholds
- If the script is edited, verification must run again
- Store verification results for auditability
