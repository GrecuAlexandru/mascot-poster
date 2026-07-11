from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models import (
    Claim,
    ClaimVerification,
    ResearchFact,
    ResearchPackage,
    SourceReference,
    TopicSpec,
    VerificationResult,
)
from app.providers.search.base import SearchResponse, SearchResult
from app.services.fact_check_service import FactCheckService, RISK_THRESHOLDS
from app.services.research_service import ResearchService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


def make_research_package() -> ResearchPackage:
    return ResearchPackage(
        topic="Vanilla sugar vs vanillin sugar",
        left_item="Vanilla sugar",
        right_item="Vanillin sugar",
        facts=[
            ResearchFact(
                text="Vanilla sugar is made with real vanilla beans.",
                source_ids=["src_0"],
                confidence=0.95,
                applies_to="left",
            ),
            ResearchFact(
                text="Vanillin sugar uses artificial vanillin.",
                source_ids=["src_1"],
                confidence=0.9,
                applies_to="right",
            ),
            ResearchFact(
                text="Natural vanilla has over 200 flavor compounds.",
                source_ids=["src_0"],
                confidence=0.85,
                applies_to="left",
            ),
        ],
        sources=[
            SourceReference(id="src_0", url="https://en.wikipedia.org/wiki/Vanilla",
                           title="Vanilla", publisher="wikipedia.org",
                           trust_score=0.8, source_type="reference"),
            SourceReference(id="src_1", url="https://www.sciencedirect.com/vanillin",
                           title="Vanillin", publisher="sciencedirect.com",
                           trust_score=0.85, source_type="scientific"),
        ],
    )


class TestSourceReference:
    def test_valid(self):
        s = SourceReference(id="s1", url="https://example.com", title="Test")
        assert s.trust_score == 0.5
        assert s.source_type == "unknown"

    def test_trust_bounds(self):
        with pytest.raises(Exception):
            SourceReference(id="s1", url="https://example.com", title="T", trust_score=1.5)


class TestResearchFact:
    def test_valid(self):
        f = ResearchFact(text="Fact", source_ids=["s1"])
        assert f.confidence == 0.5
        assert f.applies_to == "general"

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ResearchFact(text="f", confidence=-0.1)


class TestResearchPackage:
    def test_valid(self):
        pkg = make_research_package()
        assert len(pkg.facts) == 3
        assert len(pkg.sources) == 2

    def test_fixture_loadable(self):
        path = FIXTURES_DIR / "research_package.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        pkg = ResearchPackage(**data)
        assert len(pkg.facts) == 5
        assert len(pkg.sources) == 4


class TestClaimVerification:
    def test_valid(self):
        cv = ClaimVerification(claim_id="c1", supported=True)
        assert cv.severity == "none"

    def test_invalid_severity(self):
        with pytest.raises(Exception):
            ClaimVerification(claim_id="c1", supported=True, severity="critical")


class TestVerificationResult:
    def test_approved(self):
        r = VerificationResult(approved=True, claim_results=[], required_changes=[])
        assert r.approved

    def test_with_changes(self):
        r = VerificationResult(
            approved=False,
            required_changes=["Fix claim 1"],
        )
        assert not r.approved
        assert len(r.required_changes) == 1


class TestResearchService:
    def test_build_queries(self):
        svc = ResearchService()
        topic = TopicSpec(
            title="Vanilla sugar vs vanillin sugar",
            comparison_left="Vanilla sugar",
            comparison_right="Vanillin sugar",
            angle="ingredients",
        )
        queries = svc.build_queries(topic)
        assert len(queries) >= 4
        assert any("vanilla sugar" in q.lower() for q in queries)

    def test_score_source_government(self):
        svc = ResearchService()
        trust, stype = svc.score_source(
            "https://www.fda.gov/food",
            "FDA Food Labeling",
            "",
        )
        assert stype == "government"
        assert trust >= 0.9

    def test_score_source_scientific(self):
        svc = ResearchService()
        trust, stype = svc.score_source(
            "https://www.sciencedirect.com/topics/chemistry",
            "Vanillin synthesis",
            "",
        )
        assert stype == "scientific"
        assert trust >= 0.8

    def test_score_source_social(self):
        svc = ResearchService()
        trust, stype = svc.score_source(
            "https://www.tiktok.com/@user/video",
            "My vanilla video",
            "",
        )
        assert stype == "social"
        assert trust < 0.2

    def test_score_source_blog(self):
        svc = ResearchService()
        trust, stype = svc.score_source(
            "https://medium.com/@author/post",
            "Vanilla vs vanillin blog",
            "",
        )
        assert stype == "blog"
        assert trust <= 0.3

    def test_deduplicate_sources(self):
        svc = ResearchService()
        responses = [
            SearchResponse(
                query="test",
                results=[
                    SearchResult(title="A", url="https://a.com", snippet="", score=0.9),
                    SearchResult(title="B", url="https://b.com", snippet="", score=0.8),
                ],
            ),
            SearchResponse(
                query="test2",
                results=[
                    SearchResult(title="A dup", url="https://a.com", snippet="", score=0.9),
                    SearchResult(title="C", url="https://c.com", snippet="", score=0.7),
                ],
            ),
        ]
        sources = svc.deduplicate_sources(responses)
        assert len(sources) == 3
        urls = [s.url for s in sources]
        assert "https://a.com" in urls
        assert "https://b.com" in urls
        assert "https://c.com" in urls

    def test_deduplicate_sorted_by_trust(self):
        svc = ResearchService()
        responses = [
            SearchResponse(
                query="test",
                results=[
                    SearchResult(title="Blog", url="https://medium.com/post", snippet="", score=0.9),
                    SearchResult(title="Gov", url="https://fda.gov/food", snippet="", score=0.8),
                ],
            ),
        ]
        sources = svc.deduplicate_sources(responses)
        assert sources[0].trust_score >= sources[1].trust_score

    def test_has_blocking_issues_safety(self):
        svc = ResearchService()
        pkg = ResearchPackage(
            topic="t", left_item="a", right_item="b",
            safety_notes=["May cause allergic reaction"],
        )
        issue = ResearchService.has_blocking_issues(pkg)
        assert issue is not None
        assert "Safety" in issue

    def test_has_blocking_issues_unresolved(self):
        svc = ResearchService()
        pkg = ResearchPackage(
            topic="t", left_item="a", right_item="b",
            unresolved_questions=["q1", "q2", "q3"],
        )
        issue = ResearchService.has_blocking_issues(pkg)
        assert issue is not None

    def test_has_blocking_issues_ok(self):
        svc = ResearchService()
        pkg = make_research_package()
        assert ResearchService.has_blocking_issues(pkg) is None

    def test_fallback_synthesize(self):
        svc = ResearchService()
        topic = TopicSpec(title="Test vs Other", comparison_left="Test", comparison_right="Other")
        sources = [SourceReference(id="s0", url="https://example.com", title="Test", trust_score=0.8)]
        pkg = svc._fallback_synthesize(topic, sources)
        assert len(pkg.facts) == 1
        assert pkg.facts[0].source_ids == ["s0"]

    def test_search_topic_mock(self):
        mock_search = MagicMock()
        mock_search.search = AsyncMock(return_value=SearchResponse(
            query="test query",
            results=[SearchResult(title="Result", url="https://example.com", snippet="snip")],
            provider="tavily",
        ))
        svc = ResearchService(search_provider=mock_search)
        topic = TopicSpec(title="A vs B", comparison_left="A", comparison_right="B")
        results = asyncio.run(svc.search_topic(topic, max_results_per_query=3))
        assert len(results) > 0
        assert len(results[0].results) == 1


class TestFactCheckService:
    def test_rule_based_verify_all_supported(self):
        svc = FactCheckService()
        pkg = make_research_package()
        claims = [
            Claim(id="c1", text="Vanilla sugar is made with real vanilla beans", confidence=0.9, risk_level="low"),
            Claim(id="c2", text="Vanillin sugar uses artificial vanillin", confidence=0.9, risk_level="low"),
        ]
        result = svc._rule_based_verify(claims, pkg)
        assert result.approved
        assert len(result.claim_results) == 2
        assert all(cr.supported for cr in result.claim_results)

    def test_rule_based_verify_unsupported(self):
        svc = FactCheckService()
        pkg = make_research_package()
        claims = [
            Claim(id="c1", text="Dinosaurs could fly at supersonic speeds", confidence=0.5, risk_level="low"),
        ]
        result = svc._rule_based_verify(claims, pkg)
        assert not result.approved
        assert not result.claim_results[0].supported

    def test_rule_based_verify_high_risk_unsupported(self):
        svc = FactCheckService()
        pkg = make_research_package()
        claims = [
            Claim(id="c1", text="Unrelated medical claim", confidence=0.3, risk_level="high"),
        ]
        result = svc._rule_based_verify(claims, pkg)
        assert not result.approved
        assert result.claim_results[0].severity == "major"

    def test_rule_based_verify_no_claims(self):
        svc = FactCheckService()
        pkg = make_research_package()
        result = asyncio.run(svc.verify("narration", [], pkg))
        assert result.approved

    def test_match_claim_exact_words(self):
        svc = FactCheckService()
        pkg = make_research_package()
        supported, sources, expl = FactCheckService._match_claim_to_facts(
            Claim(id="c1", text="Vanilla sugar is made with real vanilla beans"),
            pkg,
        )
        assert supported
        assert "src_0" in sources

    def test_match_claim_no_overlap(self):
        pkg = make_research_package()
        supported, sources, expl = FactCheckService._match_claim_to_facts(
            Claim(id="c1", text="The sky is blue"),
            pkg,
        )
        assert not supported
        assert sources == []

    def test_risk_thresholds(self):
        assert RISK_THRESHOLDS["low"] == 0.5
        assert RISK_THRESHOLDS["medium"] == 0.7
        assert RISK_THRESHOLDS["high"] == 0.9

    def test_llm_verify_mock(self):
        svc = FactCheckService()
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "approved": True,
            "claim_results": [
                {"claim_id": "c1", "supported": True, "source_ids": ["src_0"], "explanation": "ok", "severity": "none"},
            ],
            "required_changes": [],
        })
        svc.llm = mock_llm

        pkg = make_research_package()
        claims = [Claim(id="c1", text="Vanilla sugar is natural", confidence=0.9)]
        result = asyncio.run(svc.verify(
            narration="Vanilla sugar is natural",
            claims=claims,
            research=pkg,
            left_item="Vanilla sugar",
            right_item="Vanillin sugar",
        ))
        assert result.approved

    def test_llm_verify_missing_claim(self):
        svc = FactCheckService()
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "approved": True,
            "claim_results": [],
            "required_changes": [],
        })
        svc.llm = mock_llm

        pkg = make_research_package()
        claims = [Claim(id="c1", text="test", confidence=0.9)]
        result = asyncio.run(svc.verify("test", claims, pkg))
        assert not result.approved

    def test_verify_with_fixture(self):
        path = FIXTURES_DIR / "research_package.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        pkg = ResearchPackage(**data)

        svc = FactCheckService()
        claims = [
            Claim(id="c1", text="Vanilla sugar is made with real vanilla beans", confidence=0.9, risk_level="low"),
            Claim(id="c2", text="Vanillin sugar uses artificial vanillin synthetic compound", confidence=0.9, risk_level="low"),
        ]
        result = svc._rule_based_verify(claims, pkg)
        assert len(result.claim_results) == 2
