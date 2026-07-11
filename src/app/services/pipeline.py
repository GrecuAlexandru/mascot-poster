from __future__ import annotations

import json
import logging
import shutil
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.domain.models import RenderResult, RenderSpec, ResearchPackage, ScriptPackage, TopicSpec, VerificationResult
from app.services.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class Stage(str, Enum):
    QUEUED = "QUEUED"
    TOPIC_SELECTED = "TOPIC_SELECTED"
    RESEARCH_COMPLETE = "RESEARCH_COMPLETE"
    SCRIPT_COMPLETE = "SCRIPT_COMPLETE"
    VERIFICATION_COMPLETE = "VERIFICATION_COMPLETE"
    ASSETS_COMPLETE = "ASSETS_COMPLETE"
    TTS_COMPLETE = "TTS_COMPLETE"
    TIMING_COMPLETE = "TIMING_COMPLETE"
    RENDER_COMPLETE = "RENDER_COMPLETE"
    QUALITY_COMPLETE = "QUALITY_COMPLETE"
    UPLOADED = "UPLOADED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


RETRYABLE_STAGES = {
    Stage.RESEARCH_COMPLETE,
    Stage.SCRIPT_COMPLETE,
    Stage.TTS_COMPLETE,
    Stage.RENDER_COMPLETE,
}


class PipelineState:
    def __init__(self, job_id: str, output_dir: Path):
        self.job_id = job_id
        self.output_dir = output_dir
        self.current_stage: Stage = Stage.QUEUED
        self.topic: Optional[TopicSpec] = None
        self.research: Optional[ResearchPackage] = None
        self.script: Optional[ScriptPackage] = None
        self.verification: Optional[VerificationResult] = None
        self.render_result: Optional[RenderResult] = None
        self.error_message: Optional[str] = None
        self.retry_count: int = 0
        self.cost_tracker = CostTracker(job_id)

        self._stage_outputs: dict[Stage, Path] = {}
        self._work_dir = output_dir / "_pipeline"
        self._work_dir.mkdir(parents=True, exist_ok=True)

    def checkpoint(self, stage: Stage) -> None:
        self.current_stage = stage
        logger.info(f"[{self.job_id}] Stage → {stage.value}")
        self._save_state()

    def get_resume_stage(self) -> Stage:
        return self.current_stage

    def should_skip(self, stage: Stage) -> bool:
        order = list(Stage)
        try:
            current_idx = order.index(self.current_stage)
            stage_idx = order.index(stage)
            return stage_idx < current_idx
        except ValueError:
            return False

    def save_artifact(self, stage: Stage, name: str, data: dict) -> Path:
        path = self._work_dir / f"{stage.value}_{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._stage_outputs[stage] = path
        return path

    def load_artifact(self, name: str) -> Optional[dict]:
        path = self._work_dir / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def create_debug_bundle(self, output_path: Path) -> Path:
        bundle_dir = output_path / f"debug_{self.job_id}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        state = {
            "job_id": self.job_id,
            "current_stage": self.current_stage.value,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }
        (bundle_dir / "job.json").write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )

        if self.topic:
            (bundle_dir / "topic.json").write_text(
                self.topic.model_dump_json(indent=2), encoding="utf-8"
            )
        if self.research:
            (bundle_dir / "research.json").write_text(
                self.research.model_dump_json(indent=2), encoding="utf-8"
            )
        if self.script:
            (bundle_dir / "script.json").write_text(
                self.script.model_dump_json(indent=2), encoding="utf-8"
            )
        if self.verification:
            (bundle_dir / "verification.json").write_text(
                self.verification.model_dump_json(indent=2), encoding="utf-8"
            )

        self.cost_tracker.save(bundle_dir / "cost.json")

        for path in self._stage_outputs.values():
            if path.exists():
                shutil.copy2(str(path), str(bundle_dir / path.name))

        logger.info(f"Debug bundle created: {bundle_dir}")
        return bundle_dir

    def fail(self, message: str) -> None:
        self.error_message = message
        self.current_stage = Stage.FAILED
        self._save_state()
        self.create_debug_bundle(self.output_dir)

    def _save_state(self) -> None:
        state = {
            "job_id": self.job_id,
            "current_stage": self.current_stage.value,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }
        path = self._work_dir / "state.json"
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")


class PipelineOrchestrator:
    def __init__(
        self,
        templates_dir: Path,
        mascots_dir: Path,
        output_base: Path,
        font_path: Optional[Path] = None,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        fps: int = 30,
        width: int = 1080,
        height: int = 1920,
        audio_sample_rate: int = 44100,
    ):
        self.templates_dir = templates_dir
        self.mascots_dir = mascots_dir
        self.output_base = output_base
        self.font_path = font_path
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.fps = fps
        self.width = width
        self.height = height
        self.audio_sample_rate = audio_sample_rate

    def create_job(self, topic: Optional[TopicSpec] = None) -> PipelineState:
        job_id = str(uuid4())
        output_dir = self.output_base / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        state = PipelineState(job_id, output_dir)
        if topic:
            state.topic = topic
            state.checkpoint(Stage.TOPIC_SELECTED)
        return state
