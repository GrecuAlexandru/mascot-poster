from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

from app.domain.models import TopicCandidate, TopicSelectionSignals


@dataclass(frozen=True)
class TopicSelectionDecision:
    eligible: bool
    score: float
    reasons: tuple[str, ...]


class TopicSelectionService:
    positive_weights = {
        "common_confusion": 25,
        "surprising_payoff": 20,
        "shareability": 20,
        "everyday_familiarity": 15,
        "cultural_debate": 10,
        "visual_feasibility": 10,
    }
    research_risk_penalty = 10

    def evaluate(
        self,
        candidate: TopicCandidate,
        allow_high_risk: bool = False,
    ) -> TopicSelectionDecision:
        signals = candidate.selection_signals
        if signals is None:
            return TopicSelectionDecision(
                eligible=False,
                score=0.0,
                reasons=("missing selection signals",),
            )
        reasons: list[str] = []
        if max(
            signals.common_confusion.score,
            signals.cultural_debate.score,
        ) < 3:
            reasons.append("weak confusion tension")
        if signals.surprising_payoff.score < 3:
            reasons.append("weak surprising payoff")
        if signals.visual_feasibility.score < 3:
            reasons.append("weak visual feasibility")
        if signals.research_risk.score > 3:
            reasons.append("excessive research risk")
        if candidate.risk_level == "high" and not allow_high_risk:
            reasons.append("high topic risk")
        return TopicSelectionDecision(
            eligible=not reasons,
            score=self._weighted_score(signals),
            reasons=tuple(reasons),
        )

    def select(
        self,
        candidates: Iterable[TopicCandidate],
        existing_pairs: Optional[Iterable[str]] = None,
        blacklist: Optional[Iterable[str]] = None,
        allow_high_risk: bool = False,
        limit: Optional[int] = None,
    ) -> list[TopicCandidate]:
        known_pairs = self._canonical_existing_pairs(existing_pairs or ())
        blocked_items = {self._normalize(item) for item in blacklist or ()}
        seen_pairs: set[str] = set()
        ranked: list[tuple[TopicCandidate, TopicSelectionDecision, int]] = []
        for index, candidate in enumerate(candidates):
            pair = self.pair_key(candidate.left, candidate.right)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if pair in known_pairs:
                continue
            if (
                self._normalize(candidate.left) in blocked_items
                or self._normalize(candidate.right) in blocked_items
            ):
                continue
            decision = self.evaluate(candidate, allow_high_risk=allow_high_risk)
            if decision.eligible:
                ranked.append((candidate, decision, index))
        ranked.sort(key=self._sort_key)
        selected = [candidate for candidate, _decision, _index in ranked]
        if limit is not None:
            return selected[:max(0, limit)]
        return selected

    @classmethod
    def pair_key(cls, left: str, right: str) -> str:
        return "|".join(sorted((cls._normalize(left), cls._normalize(right))))

    def _weighted_score(self, signals: TopicSelectionSignals) -> float:
        score = sum(
            getattr(signals, name).score / 5 * weight
            for name, weight in self.positive_weights.items()
        )
        score -= (
            signals.research_risk.score
            / 5
            * self.research_risk_penalty
        )
        return round(score, 2)

    @staticmethod
    def _sort_key(
        item: tuple[TopicCandidate, TopicSelectionDecision, int],
    ) -> tuple[float, int, int, int, int, int]:
        candidate, decision, index = item
        signals = candidate.selection_signals
        if signals is None:
            return (-decision.score, 0, 0, 0, 5, index)
        return (
            -decision.score,
            -signals.common_confusion.score,
            -signals.shareability.score,
            -signals.surprising_payoff.score,
            signals.research_risk.score,
            index,
        )

    @classmethod
    def _canonical_existing_pairs(cls, pairs: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for pair in pairs:
            parts = pair.split("|", 1)
            if len(parts) == 2:
                result.add(cls.pair_key(parts[0], parts[1]))
        return result

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(
            character
            for character in decomposed
            if character.isalnum() and not unicodedata.combining(character)
        )
