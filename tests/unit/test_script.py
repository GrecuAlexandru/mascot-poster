from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import Focus, ImageMotion, MascotPose, Transition
from app.domain.models import Claim, ScenePlan, ScriptPackage, TopicCandidate, TopicSpec
from app.services.script_helpers import create_sample_script
from app.services.scene_planner import ScenePlanner
from app.services.script_service import ScriptService
from app.services.topic_service import TopicService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


class TestTopicCandidate:
    def test_valid(self):
        tc = TopicCandidate(
            title="A vs B", left="A", right="B",
            angle="comparison", why_it_might_work="confusing",
        )
        assert tc.risk_level == "low"

    def test_invalid_risk(self):
        with pytest.raises(Exception):
            TopicCandidate(
                title="A vs B", left="A", right="B",
                angle="x", risk_level="extreme",
            )


class TestTopicSpec:
    def test_create(self):
        t = TopicSpec(title="X vs Y", comparison_left="X", comparison_right="Y")
        assert t.status == "IDEA"
        assert t.id is not None


class TestScriptPackage:
    def test_valid_script(self):
        s = create_sample_script()
        assert s.word_count > 80
        assert len(s.scenes) > 0

    def test_narration_empty_fails(self):
        with pytest.raises(Exception):
            ScriptPackage(
                title="Test", hook="hook", narration_text="",
                caption="cap", hashtags=[], scenes=[],
            )

    def test_scene_indices(self):
        s = create_sample_script()
        for i, scene in enumerate(s.scenes):
            assert scene.index == i

    def test_scene_index_mismatch(self):
        with pytest.raises(Exception):
            ScriptPackage(
                title="T", hook="h", narration_text="hello",
                caption="c", scenes=[
                    ScenePlan(index=1, narration="a"),
                    ScenePlan(index=0, narration="b"),
                ],
            )


class TestClaim:
    def test_valid(self):
        c = Claim(id="c1", text="fact")
        assert c.confidence == 1.0
        assert c.risk_level == "low"

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            Claim(id="c1", text="fact", confidence=1.5)


class TestTopicService:
    def test_manual_topic(self):
        svc = TopicService()
        t = svc.create_manual_topic(left="butter", right="margarine", angle="fats")
        assert t.title == "butter vs margarine"
        assert t.comparison_left == "butter"

    def test_manual_topic_empty_fails(self):
        svc = TopicService()
        with pytest.raises(ValueError):
            svc.create_manual_topic(left="", right="B")

    def test_deduplicate(self):
        svc = TopicService()
        candidates = [
            TopicCandidate(title="A vs B", left="a", right="b", angle="x"),
            TopicCandidate(title="A vs C", left="a", right="c", angle="x"),
            TopicCandidate(title="A vs B duplicate", left="A", right="B", angle="y"),
        ]
        result = svc.deduplicate(candidates)
        assert len(result) == 2

    def test_deduplicate_with_existing(self):
        svc = TopicService()
        existing = [TopicSpec(title="old", comparison_left="a", comparison_right="b")]
        candidates = [
            TopicCandidate(title="A vs B", left="a", right="b", angle="x"),
            TopicCandidate(title="A vs C", left="a", right="c", angle="x"),
        ]
        result = svc.deduplicate(candidates, existing=existing)
        assert len(result) == 1

    def test_filter_by_risk(self):
        svc = TopicService()
        candidates = [
            TopicCandidate(title="low", left="a", right="b", angle="x", risk_level="low"),
            TopicCandidate(title="high", left="c", right="d", angle="x", risk_level="high"),
        ]
        result = svc.filter_by_risk(candidates, allow_high_risk=False)
        assert len(result) == 1
        assert result[0].title == "low"

    def test_filter_blacklist(self):
        svc = TopicService()
        candidates = [
            TopicCandidate(title="A vs B", left="butter", right="margarine", angle="x"),
            TopicCandidate(title="C vs D", left="sugar", right="honey", angle="x"),
        ]
        result = svc.filter_blacklist(candidates, ["butter"])
        assert len(result) == 1
        assert result[0].left == "sugar"

    def test_style_guidance_en(self):
        svc = TopicService()
        g = svc.get_style_guidance("en")
        assert "Energetic" in g

    def test_style_guidance_ro(self):
        svc = TopicService()
        g = svc.get_style_guidance("ro")
        assert "Romanian" in g

    def test_generate_topics_mock(self):
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value={
            "topics": [
                {"title": "A vs B", "left": "A", "right": "B", "angle": "x", "risk_level": "low"},
                {"title": "C vs D", "left": "C", "right": "D", "angle": "y", "risk_level": "medium"},
            ]
        })
        svc = TopicService(llm_provider=mock_llm)
        result = asyncio.run(svc.generate_topics(niche="food", language="en", count=2))
        assert len(result) == 2
        assert result[0].title == "A vs B"
        prompt = mock_llm.complete_json.await_args.kwargs["user_prompt"]
        assert "concrete physical" in prompt
        assert "Never suggest abstract concepts" in prompt
        assert "readable paragraphs, URLs, warning labels" in prompt


class TestScriptService:
    def test_validate_script_valid(self):
        svc = ScriptService()
        s = create_sample_script()
        problems = svc.validate_script(s)
        assert problems == []

    def test_validate_short_script(self):
        svc = ScriptService()
        s = ScriptPackage(
            title="T", hook="h", narration_text="hello world",
            caption="c", scenes=[], estimated_duration_seconds=5.0,
        )
        problems = svc.validate_script(s)
        assert any("Word count" in p for p in problems)

    def test_generate_script_mock(self):
        sample = create_sample_script()
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value=json.loads(sample.model_dump_json()))
        svc = ScriptService(llm_provider=mock_llm)
        topic = TopicSpec(title="Vanilla sugar vs vanillin sugar",
                          comparison_left="Vanilla sugar",
                          comparison_right="Vanillin sugar")
        result = asyncio.run(svc.generate_script(topic))
        assert result.title == "Vanilla sugar vs vanillin sugar"
        assert result.word_count > 50

    def test_generate_script_repair_loop(self):
        sample = create_sample_script()
        valid_data = json.loads(sample.model_dump_json())
        broken_data = dict(valid_data)
        broken_data["narration_text"] = ""

        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(side_effect=[broken_data, valid_data])
        mock_llm.complete = AsyncMock(return_value=json.dumps(valid_data))

        svc = ScriptService(llm_provider=mock_llm)
        topic = TopicSpec(title="Vanilla sugar vs vanillin sugar",
                          comparison_left="Vanilla sugar",
                          comparison_right="Vanillin sugar")
        result = asyncio.run(svc.generate_script(topic, max_repair_attempts=1))
        assert result.word_count > 0


class TestScenePlanner:
    def test_auto_plan(self):
        planner = ScenePlanner()
        sample = create_sample_script()
        scenes = planner._auto_plan(sample)
        assert len(scenes) > 0
        assert scenes[0].mascot_pose == MascotPose.POINT_UP
        assert scenes[-1].mascot_pose == MascotPose.THUMBS_UP

    def test_plan_from_existing_scenes(self):
        planner = ScenePlanner()
        sample = create_sample_script()
        scenes = planner.plan_from_script(sample)
        assert len(scenes) == len(sample.scenes)

    def test_select_pose_first(self):
        planner = ScenePlanner()
        pose = planner._select_pose("hello world", 0, 10, "left", "right")
        assert pose == MascotPose.POINT_UP

    def test_select_pose_last(self):
        planner = ScenePlanner()
        pose = planner._select_pose("final thought", 9, 10, "left", "right")
        assert pose == MascotPose.THUMBS_UP

    def test_select_pose_left_item(self):
        planner = ScenePlanner()
        pose = planner._select_pose("Vanilla sugar is natural", 3, 10, "vanilla sugar", "vanillin sugar")
        assert pose == MascotPose.POINT_LEFT

    def test_select_pose_right_item(self):
        planner = ScenePlanner()
        pose = planner._select_pose("Vanillin sugar is cheap", 3, 10, "vanilla sugar", "vanillin sugar")
        assert pose == MascotPose.POINT_RIGHT

    def test_select_pose_both(self):
        planner = ScenePlanner()
        pose = planner._select_pose("Vanilla sugar vs vanillin sugar", 3, 10, "vanilla sugar", "vanillin sugar")
        assert pose == MascotPose.PRESENT_BOTH

    def test_select_pose_compare(self):
        planner = ScenePlanner()
        pose = planner._select_pose("But the difference is clear", 3, 10, "vanilla sugar", "vanillin sugar")
        assert pose == MascotPose.COMPARE_LEFT_RIGHT

    def test_select_focus_both(self):
        planner = ScenePlanner()
        focus = planner._select_focus("Vanilla and vanillin compared", "vanilla", "vanillin", 3, 10)
        assert focus == Focus.BOTH

    def test_select_focus_left(self):
        planner = ScenePlanner()
        focus = planner._select_focus("The vanilla is better", "vanilla", "vanillin", 3, 10)
        assert focus == Focus.LEFT

    def test_extract_phrases_short(self):
        planner = ScenePlanner()
        phrases = planner._extract_phrases("Hello world")
        assert len(phrases) == 1
        assert phrases[0] == "HELLO WORLD"

    def test_extract_phrases_long(self):
        planner = ScenePlanner()
        phrases = planner._extract_phrases("This is a longer sentence with many words")
        assert len(phrases) == 1
        assert len(phrases[0]) <= 42

    def test_min_pose_duration_enforced(self):
        planner = ScenePlanner(min_pose_duration=1.0)
        scenes = [
            ScenePlan(index=0, narration="a", duration_hint_seconds=0.5, mascot_pose=MascotPose.NEUTRAL),
            ScenePlan(index=1, narration="b", duration_hint_seconds=0.5, mascot_pose=MascotPose.POINT_LEFT),
        ]
        planner._enforce_min_pose_duration(scenes)
        assert scenes[0].duration_hint_seconds >= 1.0

    def test_split_sentences(self):
        sentences = ScenePlanner._split_sentences("Hello world. Test sentence! Next?")
        assert len(sentences) == 3


class TestScriptHelpers:
    def test_create_sample_script(self):
        s = create_sample_script()
        assert s.title == "Vanilla sugar vs vanillin sugar"
        assert s.word_count > 100
        assert len(s.scenes) == 12
        assert len(s.claims) == 3
        assert len(s.hashtags) == 5

    def test_script_fixture_loadable(self):
        path = FIXTURES_DIR / "script_package.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "narration_text" in data
        assert "scenes" in data


class TestTopicHistoryService:
    def test_add_and_exists(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        h.add(title="Coffee vs Tea", left="Coffee", right="Tea", angle="caffeine")
        assert h.count == 1
        assert h.exists("Coffee", "Tea")
        assert h.exists("coffee", "tea")
        assert not h.exists("Chocolate", "Tea")

    def test_add_from_topic(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        topic = TopicSpec(
            title="A vs B", comparison_left="A", comparison_right="B", angle="x",
        )
        h.add_from_topic(topic, job_id="job123")
        assert h.count == 1
        assert h.exists("A", "B")
        assert h.exists("a", "b")

    def test_reverse_order_detected(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        h.add(title="Tea vs Coffee", left="Tea", right="Coffee")
        assert h.exists("Coffee", "Tea")
        assert h.exists("TEA", "COFFEE")

    def test_no_duplicate_add(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        h.add(title="A vs B", left="A", right="B")
        h.add(title="A vs B", left="A", right="B")
        assert h.count == 1

    def test_get_normalized_pairs(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        h.add(title="A vs B", left="A", right="B")
        h.add(title="C vs D", left="C", right="D")
        pairs = h.get_normalized_pairs()
        assert "a|b" in pairs
        assert "b|a" in pairs
        assert "c|d" in pairs
        assert "d|c" in pairs

    def test_get_topic_titles(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        h.add(title="T1", left="X", right="Y")
        h.add(title="T2", left="P", right="Q")
        titles = h.get_topic_titles()
        assert "T1" in titles
        assert "T2" in titles

    def test_clear(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        h.add(title="A vs B", left="A", right="B")
        h.clear()
        assert h.count == 0
        assert not h.exists("A", "B")

    def test_persistence(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h1 = TopicHistoryService(tmp_path / "history.json")
        h1.add(title="A vs B", left="A", right="B")
        h2 = TopicHistoryService(tmp_path / "history.json")
        assert h2.count == 1
        assert h2.exists("A", "B")

    def test_empty_history(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        h = TopicHistoryService(tmp_path / "history.json")
        assert h.count == 0
        assert not h.exists("A", "B")
        assert h.get_normalized_pairs() == set()


class TestGenerateUniqueTopics:
    def test_filters_known_topics(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        history = TopicHistoryService(tmp_path / "history.json")
        history.add(title="Butter vs Margarine", left="Butter", right="Margarine")

        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value={
            "topics": [
                {"title": "Butter vs Margarine", "left": "Butter", "right": "Margarine",
                 "angle": "fats", "why_it_might_work": "d"},
                {"title": "Salt vs Sugar", "left": "Salt", "right": "Sugar",
                 "angle": "taste", "why_it_might_work": "d"},
            ]
        })

        svc = TopicService(llm_provider=llm)
        candidates = asyncio.run(svc.generate_unique_topics(
            history=history, count=5,
        ))

        assert len(candidates) == 1
        assert candidates[0].left == "Salt"

    def test_filters_reversed_order(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        history = TopicHistoryService(tmp_path / "history.json")
        history.add(title="Coffee vs Tea", left="Coffee", right="Tea")

        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value={
            "topics": [
                {"title": "Tea vs Coffee", "left": "Tea", "right": "Coffee",
                 "angle": "caffeine", "why_it_might_work": "d"},
                {"title": "X vs Y", "left": "X", "right": "Y",
                 "angle": "test", "why_it_might_work": "d"},
            ]
        })

        svc = TopicService(llm_provider=llm)
        candidates = asyncio.run(svc.generate_unique_topics(
            history=history, count=5,
        ))

        assert len(candidates) == 1
        assert candidates[0].title == "X vs Y"

    def test_empty_when_all_dups(self, tmp_path):
        from app.services.topic_history import TopicHistoryService

        history = TopicHistoryService(tmp_path / "history.json")
        history.add(title="A vs B", left="A", right="B")

        llm = AsyncMock()
        llm.complete_json = AsyncMock(return_value={
            "topics": [
                {"title": "A vs B", "left": "A", "right": "B",
                 "angle": "x", "why_it_might_work": "d"},
                {"title": "B vs A", "left": "B", "right": "A",
                 "angle": "x", "why_it_might_work": "d"},
            ]
        })

        svc = TopicService(llm_provider=llm)
        candidates = asyncio.run(svc.generate_unique_topics(
            history=history, count=5,
        ))

        assert len(candidates) == 0
