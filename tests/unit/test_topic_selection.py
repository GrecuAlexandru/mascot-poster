from __future__ import annotations

import pytest

from app.domain.models import (
    TopicCandidate,
    TopicSelectionSignals,
    TopicSignal,
)
from app.services.topic_selection_service import TopicSelectionService


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


def candidate(
    title: str = "Gem vs dulceață",
    left: str = "Gem",
    right: str = "Dulceață",
    selection_signals: TopicSelectionSignals | None = None,
    risk_level: str = "low",
) -> TopicCandidate:
    return TopicCandidate(
        title=title,
        left=left,
        right=right,
        angle="Diferența reală",
        selection_signals=selection_signals or signals(),
        risk_level=risk_level,
    )


def test_topic_signal_rejects_scores_outside_zero_through_five() -> None:
    with pytest.raises(ValueError):
        TopicSignal(score=6, reason="specific")


def test_topic_signal_strips_and_rejects_blank_reasons() -> None:
    assert TopicSignal(score=3, reason="  specific  ").reason == "specific"
    with pytest.raises(ValueError):
        TopicSignal(score=3, reason="   ")


def test_legacy_candidate_without_signals_remains_loadable_but_ineligible() -> None:
    legacy = TopicCandidate(title="A vs B", left="A", right="B", angle="x")

    decision = TopicSelectionService().evaluate(legacy)

    assert not decision.eligible
    assert decision.score == 0.0
    assert decision.reasons == ("missing selection signals",)


def test_selector_calculates_approved_weighted_score() -> None:
    decision = TopicSelectionService().evaluate(candidate())

    assert decision.eligible
    assert decision.score == 89.0
    assert decision.reasons == ()


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"common_confusion": 2, "cultural_debate": 2}, "weak confusion tension"),
        ({"surprising_payoff": 2}, "weak surprising payoff"),
        ({"visual_feasibility": 2}, "weak visual feasibility"),
        ({"research_risk": 4}, "excessive research risk"),
    ],
)
def test_selector_applies_each_signal_gate(
    overrides: dict[str, int],
    expected_reason: str,
) -> None:
    decision = TopicSelectionService().evaluate(
        candidate(selection_signals=signals(**overrides))
    )

    assert not decision.eligible
    assert expected_reason in decision.reasons


def test_selector_excludes_high_risk_topics_by_default() -> None:
    risky = candidate(risk_level="high")

    assert not TopicSelectionService().evaluate(risky).eligible
    assert TopicSelectionService().evaluate(risky, allow_high_risk=True).eligible


def test_selector_ranks_by_weighted_score_instead_of_input_order() -> None:
    weaker = candidate(
        title="Weak",
        left="Weak left",
        right="Weak right",
        selection_signals=signals(
            common_confusion=3,
            everyday_familiarity=3,
            cultural_debate=0,
            surprising_payoff=3,
            shareability=2,
            visual_feasibility=3,
            research_risk=2,
        ),
    )
    stronger = candidate(title="Strong", left="Strong left", right="Strong right")

    selected = TopicSelectionService().select([weaker, stronger])

    assert [item.title for item in selected] == ["Strong", "Weak"]


def test_selector_keeps_first_unordered_pair_and_filters_history_and_blacklist() -> None:
    first = candidate(title="First", left="Corb", right="Cioară")
    reversed_duplicate = candidate(title="Duplicate", left="Cioară", right="Corb")
    historical = candidate(title="Historical", left="Gem", right="Dulceață")
    blacklisted = candidate(title="Blacklisted", left="Taur", right="Bou")
    valid = candidate(title="Valid", left="Fulger", right="Trăsnet")

    selected = TopicSelectionService().select(
        [first, reversed_duplicate, historical, blacklisted, valid],
        existing_pairs={"dulceata|gem"},
        blacklist=["Taur"],
    )

    assert [item.title for item in selected] == ["First", "Valid"]


def test_selector_uses_approved_tie_breakers_and_limit() -> None:
    higher_shareability = candidate(
        title="Higher shareability",
        left="A",
        right="B",
        selection_signals=signals(
            common_confusion=4,
            cultural_debate=4,
            shareability=5,
            visual_feasibility=3,
        ),
    )
    higher_debate_same_total = candidate(
        title="Higher debate",
        left="C",
        right="D",
        selection_signals=signals(
            common_confusion=4,
            cultural_debate=5,
            shareability=4,
            visual_feasibility=4,
        ),
    )

    selected = TopicSelectionService().select(
        [higher_debate_same_total, higher_shareability],
        limit=1,
    )

    assert [item.title for item in selected] == ["Higher shareability"]
