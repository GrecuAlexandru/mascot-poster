from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from app.providers.images.base import GeneratedImage, ImageProvider
from app.providers.storage.base import StorageObject
from app.providers.storage.local_provider import LocalStorageProvider
from app.services.image_service import ImageService, COMPARISON_CANVAS_W, COMPARISON_CANVAS_H
from app.services.cost_tracker import CostTracker
from app.services.quality_service import QualityService
from app.services.notification_service import NotificationService
from app.services.n8n_service import N8nWebhookService
from app.services.publishing_service import (
    PublicationPayload,
    PublicationResult,
    PublishingService,
    TikTokPublisher,
    YouTubePublisher,
)
from app.services.analytics_service import AnalyticsService, AnalyticsSnapshot
from app.services.pipeline import PipelineOrchestrator, PipelineState, Stage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


class TestImageService:
    def test_build_prompt(self, tmp_path):
        svc = ImageService(cache_dir=tmp_path)
        prompt = svc.build_prompt("vanilla sugar")
        assert "vanilla sugar" in prompt
        assert "centered" in prompt.lower()

    def test_validate_image_valid(self):
        svc = ImageService()
        svc.validate_image(FIXTURES_DIR / "left.png")

    def test_validate_image_missing(self):
        svc = ImageService()
        with pytest.raises(ValueError, match="not found"):
            svc.validate_image(Path("/nonexistent.png"))

    def test_validate_image_too_small(self, tmp_path):
        tiny = tmp_path / "tiny.png"
        img = Image.new("RGBA", (10, 10), (255, 0, 0))
        img.save(str(tiny))
        svc = ImageService()
        with pytest.raises(ValueError, match="too small"):
            svc.validate_image(tiny)

    def test_normalize(self, tmp_path):
        svc = ImageService()
        left_out = tmp_path / "norm_left.png"
        right_out = tmp_path / "norm_right.png"
        svc.normalize(
            FIXTURES_DIR / "left.png",
            FIXTURES_DIR / "right.png",
            left_out, right_out,
            target_w=430, target_h=480,
        )
        assert left_out.exists()
        assert right_out.exists()
        l = Image.open(left_out)
        assert l.size == (430, 480)

    def test_create_comparison_canvas(self, tmp_path):
        svc = ImageService()
        out = tmp_path / "comparison.png"
        svc.create_comparison_canvas(
            FIXTURES_DIR / "left.png",
            FIXTURES_DIR / "right.png",
            out,
        )
        assert out.exists()
        img = Image.open(out)
        assert img.size == (COMPARISON_CANVAS_W, COMPARISON_CANVAS_H)

    def test_hash_content(self):
        svc = ImageService()
        h = svc.hash_content(FIXTURES_DIR / "left.png")
        assert len(h) == 64


class TestLocalStorageProvider:
    def test_upload_download(self, tmp_path):
        source = tmp_path / "source.txt"
        source.write_text("test content")
        storage = LocalStorageProvider(base_dir=tmp_path / "storage")
        import asyncio
        result = asyncio.run(storage.upload(source, "test/key.txt"))
        assert result.size > 0
        assert "test" in result.url

        download_path = tmp_path / "downloaded.txt"
        asyncio.run(storage.download("test/key.txt", download_path))
        assert download_path.read_text() == "test content"

    def test_get_url(self, tmp_path):
        storage = LocalStorageProvider(
            base_dir=tmp_path, public_base_url="https://cdn.example.com"
        )
        url = storage.get_url("videos/test.mp4")
        assert "https://cdn.example.com" in url
        assert "videos/test.mp4" in url

    def test_download_missing(self, tmp_path):
        storage = LocalStorageProvider(base_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            import asyncio
            asyncio.run(storage.download("nonexistent", tmp_path / "out"))


class TestCostTracker:
    def test_add_and_total(self):
        t = CostTracker(job_id="test")
        t.add("openai", "llm_tokens", 1000, "tokens", 0.005)
        t.add("elevenlabs", "tts_characters", 500, "chars", 0.15)
        assert t.total_cost == 0.155

    def test_by_category(self):
        t = CostTracker()
        t.add("openai", "llm_tokens", 1000, "tokens", 0.01)
        t.add("openai", "llm_tokens", 500, "tokens", 0.005)
        t.add("tavily", "search_queries", 3, "queries", 0.03)
        d = t.to_dict()
        assert d["by_category"]["llm"] == 0.015
        assert d["by_category"]["search"] == 0.03
        assert d["by_category"]["total"] == 0.045

    def test_save(self, tmp_path):
        t = CostTracker(job_id="job1")
        t.add("test", "op", 1, "unit", 0.5)
        path = tmp_path / "cost.json"
        t.save(path)
        data = json.loads(path.read_text())
        assert data["job_id"] == "job1"

    def test_helper_methods(self):
        t = CostTracker()
        t.add_llm("openai", 100, 50, 0.01)
        t.add_tts("elevenlabs", 500, 0.15)
        t.add_search("tavily", 3, 0.03)
        t.add_images("openai", 2, 0.08)
        assert t.total_cost > 0


class TestQualityService:
    def test_validate_video_valid(self):
        svc = QualityService()
        video = PROJECT_ROOT / "output" / "video.mp4"
        if not video.exists():
            pytest.skip("No rendered video available")
        problems = svc.validate_video(video)
        assert problems == []

    def test_validate_video_missing(self):
        svc = QualityService()
        problems = svc.validate_video(Path("/nonexistent.mp4"))
        assert len(problems) == 1
        assert "does not exist" in problems[0]


class TestNotificationService:
    def test_format_approval_message(self):
        msg = NotificationService._format_approval_message(
            job_id="job123",
            topic="Vanilla vs Vanillin",
            preview_url="https://example.com/preview",
            video_url="https://example.com/video",
            caption="Test caption",
            cost=0.22,
            approve_url="https://api/approve",
            reject_url="https://api/reject",
            regenerate_url="https://api/regen",
        )
        assert "job123" in msg
        assert "Vanilla vs Vanillin" in msg
        assert "$0.2200" in msg

    def test_send_no_config(self):
        svc = NotificationService()
        asyncio.run(svc.send_failure_alert("job1", "test error"))


class TestN8nWebhookService:
    def test_init(self):
        svc = N8nWebhookService(
            n8n_webhook_url="https://n8n.example.com/webhook",
        )
        assert svc.webhook_url is not None

    def test_notify_no_config(self):
        svc = N8nWebhookService()
        asyncio.run(svc.notify_failure("job1", "test error", "RENDER"))


class TestPublishingService:
    def test_publication_payload(self):
        p = PublicationPayload(
            platform="tiktok",
            video_url="https://example.com/v.mp4",
            caption="Test",
        )
        assert p.disclose_ai_generated is True

    def test_tiktok_no_token(self):
        pub = TikTokPublisher()
        payload = PublicationPayload(
            platform="tiktok",
            video_url="https://example.com/v.mp4",
            caption="Test",
        )
        result = asyncio.run(pub.publish(payload))
        assert result.status == "skipped"

    def test_youtube_not_implemented(self):
        pub = YouTubePublisher()
        payload = PublicationPayload(
            platform="youtube",
            video_url="https://example.com/v.mp4",
            caption="Test",
        )
        result = asyncio.run(pub.publish(payload))
        assert result.status == "not_implemented"

    def test_publish_to_all_empty(self):
        svc = PublishingService()
        payload = PublicationPayload(
            platform="tiktok", video_url="https://x", caption="c"
        )
        results = asyncio.run(svc.publish_to_all(payload))
        assert results == []

    def test_publish_to_platform_unconfigured(self):
        svc = PublishingService()
        payload = PublicationPayload(
            platform="unknown", video_url="https://x", caption="c"
        )
        result = asyncio.run(svc.publish_to_platform("unknown", payload))
        assert result.status == "skipped"


class TestAnalyticsService:
    def test_record_and_get(self):
        svc = AnalyticsService()
        snap = AnalyticsSnapshot(
            job_id="job1", platform="tiktok",
            views=1000, likes=50, comments=10,
        )
        svc.record(snap)
        snapshots = svc.get_snapshots("job1")
        assert len(snapshots) == 1
        latest = svc.get_latest("job1")
        assert latest.views == 1000

    def test_aggregate(self):
        svc = AnalyticsService()
        svc.record(AnalyticsSnapshot(job_id="j1", platform="tiktok", views=500))
        svc.record(AnalyticsSnapshot(job_id="j1", platform="tiktok", views=1500))
        svc.record(AnalyticsSnapshot(job_id="j1", platform="youtube", views=300))
        agg = svc.aggregate("j1")
        assert agg["platforms"]["tiktok"]["views"] == 1500
        assert agg["platforms"]["youtube"]["views"] == 300

    def test_daily_summary(self):
        svc = AnalyticsService()
        svc.record(AnalyticsSnapshot(job_id="j1", platform="tiktok", views=500))
        summary = svc.get_daily_summary()
        assert summary["total_jobs"] == 1

    def test_performance_topics(self):
        svc = AnalyticsService()
        svc.record(AnalyticsSnapshot(job_id="good", platform="tiktok", views=5000))
        svc.record(AnalyticsSnapshot(job_id="bad", platform="tiktok", views=100))
        topics = svc.get_performance_topics(min_views=1000)
        assert "good" in topics
        assert "bad" not in topics

    def test_persist(self, tmp_path):
        svc = AnalyticsService(storage_dir=tmp_path)
        svc.record(AnalyticsSnapshot(job_id="j1", platform="tiktok", views=100))
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1


class TestPipelineState:
    def test_checkpoint(self, tmp_path):
        state = PipelineState("job1", tmp_path)
        state.checkpoint(Stage.TOPIC_SELECTED)
        assert state.current_stage == Stage.TOPIC_SELECTED

    def test_should_skip(self, tmp_path):
        state = PipelineState("job1", tmp_path)
        state.checkpoint(Stage.SCRIPT_COMPLETE)
        assert state.should_skip(Stage.TOPIC_SELECTED)

    def test_save_artifact(self, tmp_path):
        state = PipelineState("job1", tmp_path)
        path = state.save_artifact(Stage.SCRIPT_COMPLETE, "script", {"key": "val"})
        assert path.exists()

    def test_fail(self, tmp_path):
        state = PipelineState("job1", tmp_path)
        state.fail("Test error")
        assert state.current_stage == Stage.FAILED
        assert state.error_message == "Test error"

    def test_debug_bundle(self, tmp_path):
        state = PipelineState("job1", tmp_path)
        state.fail("Test error")
        bundle = tmp_path / f"debug_job1"
        assert bundle.exists()
        assert (bundle / "job.json").exists()

    def test_load_artifact(self, tmp_path):
        state = PipelineState("job1", tmp_path)
        state.save_artifact(Stage.SCRIPT_COMPLETE, "script", {"key": "val"})
        loaded = state.load_artifact("SCRIPT_COMPLETE_script.json")
        assert loaded == {"key": "val"}


class TestPipelineOrchestrator:
    def test_create_job(self, tmp_path):
        orch = PipelineOrchestrator(
            templates_dir=PROJECT_ROOT / "templates",
            mascots_dir=PROJECT_ROOT / "assets" / "mascots" / "default",
            output_base=tmp_path,
        )
        state = orch.create_job()
        assert state.job_id is not None
        assert state.current_stage == Stage.QUEUED

    def test_create_job_with_topic(self, tmp_path):
        from app.domain.models import TopicSpec
        orch = PipelineOrchestrator(
            templates_dir=PROJECT_ROOT / "templates",
            mascots_dir=PROJECT_ROOT / "assets" / "mascots" / "default",
            output_base=tmp_path,
        )
        topic = TopicSpec(title="A vs B", comparison_left="A", comparison_right="B")
        state = orch.create_job(topic=topic)
        assert state.current_stage == Stage.TOPIC_SELECTED
        assert state.topic is not None
