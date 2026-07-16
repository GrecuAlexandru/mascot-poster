from __future__ import annotations

import logging
from typing import Optional

from app.domain.models import Claim, ClaimVerification, ResearchPackage, VerificationResult
from app.providers.llm.base import LLMError, LLMProvider

logger = logging.getLogger(__name__)

_FACT_CHECK_SYSTEM_PROMPT = (
    "You are the fact checker for a Romanian short-form comparison video channel. You verify each "
    "spoken claim ONLY against the research facts and sources you are given; you cannot fetch new "
    "evidence, so your only remedies are to accept a claim, mark it minor, or (for a claim that "
    "reverses the evidence or makes an unsupported health, money, legal, or safety recommendation "
    "as certainty) mark it major and require one concrete wording edit. This is a casual explainer, "
    "not a scientific paper: rounded or approximate figures are fine as long as the direction of "
    "the comparison matches the research, and you never demand a number that is not already in the "
    "facts. You are a soft quality gate — when in doubt, approve and at most soften. You always "
    "respond with a single valid JSON object and no markdown fences."
)

RISK_THRESHOLDS = {
    "low": 0.5,
    "medium": 0.7,
    "high": 0.9,
}


class FactCheckService:
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm = llm_provider

    async def verify(
        self,
        narration: str,
        claims: list[Claim],
        research: ResearchPackage,
        left_item: str = "",
        right_item: str = "",
        angle: str = "",
    ) -> VerificationResult:
        if not claims:
            return VerificationResult(approved=True, claim_results=[])

        if self.llm:
            return await self._llm_verify(
                narration, claims, research, left_item, right_item, angle
            )
        return self._rule_based_verify(claims, research)

    async def _llm_verify(
        self,
        narration: str,
        claims: list[Claim],
        research: ResearchPackage,
        left_item: str,
        right_item: str,
        angle: str,
    ) -> VerificationResult:
        template = self._load_prompt("fact_check.md")
        claims_text = "\n".join(
            f"- [{c.id}] (risk={c.risk_level}, confidence={c.confidence}): {c.text}"
            for c in claims
        )
        facts_text = "\n".join(
            f"- [{i}] {f.text} (confidence={f.confidence}, applies_to={f.applies_to})"
            for i, f in enumerate(research.facts)
        )
        sources_text = "\n".join(
            f"- [{s.id}] {s.title} (trust={s.trust_score}, type={s.source_type})"
            for s in research.sources
        )

        user_prompt = template.format(
            narration=narration,
            claims=claims_text or "(none)",
            research_facts=facts_text or "(none)",
            sources=sources_text or "(none)",
            left_item=left_item,
            right_item=right_item,
            angle=angle,
        )

        data = await self.llm.complete_json(
            system_prompt=_FACT_CHECK_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=2048,
        )

        claim_results: list[ClaimVerification] = []
        for cr in data.get("claim_results", []):
            try:
                claim_results.append(ClaimVerification(**cr))
            except Exception as e:
                logger.warning(f"Skipping invalid claim verification: {e}")

        approved = data.get("approved", False)
        required_changes = data.get("required_changes", [])

        for c in claims:
            found = any(cr.claim_id == c.id for cr in claim_results)
            if not found:
                claim_results.append(ClaimVerification(
                    claim_id=c.id,
                    supported=False,
                    explanation="Claim not checked",
                    severity="minor",
                ))
                approved = False

        result = VerificationResult(
            approved=approved,
            claim_results=claim_results,
            required_changes=required_changes,
        )

        logger.info(
            f"Verification: approved={result.approved}, "
            f"{sum(1 for cr in result.claim_results if cr.supported)}/"
            f"{len(result.claim_results)} claims supported"
        )
        return result

    def _rule_based_verify(
        self,
        claims: list[Claim],
        research: ResearchPackage,
    ) -> VerificationResult:
        results: list[ClaimVerification] = []
        required_changes: list[str] = []
        all_supported = True

        for claim in claims:
            supported, source_ids, explanation = self._match_claim_to_facts(
                claim, research
            )
            threshold = RISK_THRESHOLDS.get(claim.risk_level, 0.5)
            severity: str = "none"

            if not supported:
                severity = "major" if claim.risk_level == "high" else "minor"
                all_supported = False
                required_changes.append(
                    f"Claim '{claim.id}' not supported by research: {claim.text}"
                )
            elif claim.confidence < threshold and claim.risk_level in ("medium", "high"):
                severity = "minor"
                required_changes.append(
                    f"Claim '{claim.id}' confidence {claim.confidence} "
                    f"below threshold {threshold} for risk level {claim.risk_level}"
                )

            results.append(ClaimVerification(
                claim_id=claim.id,
                supported=supported,
                source_ids=source_ids,
                explanation=explanation,
                severity=severity,
            ))

        any_major = any(cr.severity == "major" for cr in results)
        approved = all_supported and not any_major

        result = VerificationResult(
            approved=approved,
            claim_results=results,
            required_changes=required_changes,
        )

        logger.info(
            f"Rule-based verification: approved={result.approved}, "
            f"{sum(1 for cr in results if cr.supported)}/{len(results)} supported"
        )
        return result

    @staticmethod
    def _match_claim_to_facts(
        claim: Claim,
        research: ResearchPackage,
    ) -> tuple[bool, list[str], str]:
        claim_lower = claim.text.lower()
        claim_words = set(claim_lower.split())

        matched_sources: list[str] = []
        best_confidence = 0.0
        best_explanation = "No matching fact found"

        for fact in research.facts:
            fact_lower = fact.text.lower()
            fact_words = set(fact_lower.split())
            overlap = claim_words & fact_words
            overlap_ratio = len(overlap) / max(len(claim_words), 1) if claim_words else 0

            if overlap_ratio >= 0.3 or claim_lower in fact_lower:
                matched_sources.extend(fact.source_ids)
                if fact.confidence > best_confidence:
                    best_confidence = fact.confidence
                    best_explanation = (
                        f"Matched research fact (confidence={fact.confidence}, "
                        f"overlap={overlap_ratio:.0%}): {fact.text[:100]}"
                    )

        if matched_sources:
            threshold = RISK_THRESHOLDS.get(claim.risk_level, 0.5)
            if best_confidence >= threshold:
                return True, list(set(matched_sources)), best_explanation
            return True, list(set(matched_sources)), best_explanation

        return False, [], best_explanation

    def _load_prompt(self, name: str) -> str:
        from pathlib import Path

        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        path = prompt_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")
