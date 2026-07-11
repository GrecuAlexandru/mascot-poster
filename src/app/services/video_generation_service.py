from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from app.domain.models import (
    CompiledVideoSpec,
    DirectionPlan,
    GenerationRequest,
    GenerationResult,
    ReferenceScriptPackage,
    RenderResult,
    ResearchPackage,
    TimedTranscript,
    TopicSpec,
    VerificationResult,
)


class _CheckpointStore:
    def __init__(self, job_dir: Path):
        self.job_dir = job_dir
        self.directory = job_dir / "_pipeline"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path = self.directory / "state.json"
        self.state = self._load_state()

    def completed(self, stage: str) -> bool:
        return stage in self.state["completed"] and self.artifact_path(stage).exists()

    def artifact_path(self, stage: str) -> Path:
        return self.directory / f"{stage}.json"

    def save(self, stage: str, value: Any) -> None:
        self.artifact_path(stage).write_text(
            json.dumps(self._serialize(value), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if stage not in self.state["completed"]:
            self.state["completed"].append(stage)
        self.state["failed_stage"] = None
        self.state["error"] = None
        self._write_state()

    def load(self, stage: str) -> Any:
        return json.loads(self.artifact_path(stage).read_text(encoding="utf-8"))

    def fail(self, stage: str, error: Exception) -> None:
        self.state["failed_stage"] = stage
        self.state["error"] = str(error)
        self._write_state()

    def invalidate(self, stages: list[str]) -> None:
        invalid = set(stages)
        for stage in invalid:
            self.artifact_path(stage).unlink(missing_ok=True)
        self.state["completed"] = [
            stage for stage in self.state["completed"] if stage not in invalid
        ]
        if self.state["failed_stage"] in invalid:
            self.state["failed_stage"] = None
            self.state["error"] = None
        self._write_state()

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"completed": [], "failed_stage": None, "error": None}

    def _write_state(self) -> None:
        self.state_path.write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _serialize(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [_CheckpointStore._serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: _CheckpointStore._serialize(item) for key, item in value.items()}
        if isinstance(value, Path):
            return str(value)
        return value


class VideoGenerationService:
    def __init__(
        self,
        output_base: Path,
        topic_generator: object,
        researcher: object,
        script_writer: object,
        verifier: object,
        director: object,
        beat_tts: object,
        image_service: object,
        audio_service: object,
        sfx_service: object,
        timeline_compiler: object,
        renderer: object,
        quality_service: object,
    ):
        self.output_base = output_base
        self.topic_generator = topic_generator
        self.researcher = researcher
        self.script_writer = script_writer
        self.verifier = verifier
        self.director = director
        self.beat_tts = beat_tts
        self.image_service = image_service
        self.audio_service = audio_service
        self.sfx_service = sfx_service
        self.timeline_compiler = timeline_compiler
        self.renderer = renderer
        self.quality_service = quality_service

    async def generate(
        self,
        request: GenerationRequest,
        progress_callback: Optional[Callable[[str], Any]] = None,
        job_id: Optional[str] = None,
    ) -> GenerationResult:
        job_id = job_id or str(uuid4())
        job_dir = self.output_base / job_id
        checkpoint = _CheckpointStore(job_dir)
        stage = "preflight"
        try:
            await self._announce(progress_callback, stage)
            self._validate_dependencies()

            stage = "topic"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                topic = TopicSpec.model_validate(checkpoint.load(stage))
            else:
                topic = await self.topic_generator.generate(request)
                checkpoint.save(stage, topic)

            stage = "research_assets"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                payload = checkpoint.load(stage)
                research = ResearchPackage.model_validate(payload["research"])
                left_image = Path(payload["left_image"])
                right_image = Path(payload["right_image"])
                provenance_path = Path(payload["provenance_path"])
            else:
                assets_dir = job_dir / "assets"
                assets_dir.mkdir(parents=True, exist_ok=True)
                research, left_provenance, right_provenance = await asyncio.gather(
                    self.researcher.generate(topic),
                    self.image_service.acquire(topic.comparison_left, assets_dir / "left.png"),
                    self.image_service.acquire(topic.comparison_right, assets_dir / "right.png"),
                )
                left_image = assets_dir / "left.png"
                right_image = assets_dir / "right.png"
                provenance_path = job_dir / "image_provenance.json"
                provenance_path.write_text(
                    json.dumps({
                        "left": _CheckpointStore._serialize(left_provenance),
                        "right": _CheckpointStore._serialize(right_provenance),
                    }, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                checkpoint.save(stage, {
                    "research": research,
                    "left_image": left_image,
                    "right_image": right_image,
                    "provenance_path": provenance_path,
                })

            stage = "script_verification"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                payload = checkpoint.load(stage)
                script = ReferenceScriptPackage.model_validate(payload["script"])
                verification = VerificationResult.model_validate(payload["verification"])
            else:
                script, verification = await self._generate_verified_script(
                    topic,
                    research,
                    request,
                    [],
                )
                checkpoint.save(stage, {"script": script, "verification": verification})

            stage = "direction_tts"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                existing = checkpoint.load(stage)
                existing_transcript = TimedTranscript.model_validate(existing["transcript"])
                if not self._duration_is_acceptable(existing_transcript.duration_seconds):
                    checkpoint.invalidate(["direction_tts", "compiled", "render", "quality"])
            if checkpoint.completed(stage):
                payload = checkpoint.load(stage)
                direction = DirectionPlan.model_validate(payload["direction"])
                transcript = TimedTranscript.model_validate(payload["transcript"])
                narration_audio = Path(payload["narration_audio"])
            else:
                audio_dir = job_dir / "audio"
                narration_audio: Path | None = None
                transcript: TimedTranscript | None = None
                for attempt in range(3):
                    if script.word_count > self._word_budget(request):
                        script, verification = await self._generate_verified_script(
                            topic,
                            research,
                            request,
                            [
                                f"Narration has {script.word_count} spoken words. Reduce it to at most "
                                f"{self._word_budget(request)} spoken words.",
                            ],
                        )
                    narration_audio, transcript = await self.beat_tts.synthesize(
                        script,
                        request.voice_id or "",
                        request.language,
                        audio_dir,
                    )
                    if self._duration_is_acceptable(transcript.duration_seconds):
                        break
                    if attempt == 2:
                        break
                    script, verification = await self._generate_verified_script(
                        topic,
                        research,
                        request,
                        [self._duration_repair_note(transcript.duration_seconds, request)],
                    )
                if narration_audio is None or transcript is None:
                    raise RuntimeError("Narration synthesis did not return timing data")
                if not self._duration_is_acceptable(transcript.duration_seconds):
                    raise RuntimeError(
                        "Narration duration could not be repaired into the 20-60 second range: "
                        f"{transcript.duration_seconds:.1f}s"
                    )
                direction = await self.director.generate(script, request.language)
                checkpoint.save("script_verification", {"script": script, "verification": verification})
                checkpoint.save(stage, {
                    "direction": direction,
                    "transcript": transcript,
                    "narration_audio": narration_audio,
                })

            stage = "compiled"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                compiled = CompiledVideoSpec.model_validate(checkpoint.load(stage))
            else:
                timeline = self.timeline_compiler.compile(direction, transcript)
                library = self.sfx_service.ensure_library(job_dir / "assets" / "sfx")
                mixed_audio = job_dir / "audio" / "mixed_audio.m4a"
                self.audio_service.mix_timed_sfx(
                    narration_audio,
                    timeline.sound_cues,
                    library,
                    mixed_audio,
                )
                compiled = CompiledVideoSpec(
                    left_label=topic.comparison_left,
                    right_label=topic.comparison_right,
                    left_image=left_image,
                    right_image=right_image,
                    narration_audio=mixed_audio,
                    transcript=transcript,
                    direction_cues=timeline.direction_cues,
                    sound_cues=timeline.sound_cues,
                    captions=timeline.captions,
                )
                checkpoint.save(stage, compiled)

            stage = "render"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                render_result = RenderResult.model_validate(checkpoint.load(stage))
            else:
                render_result = self.renderer.render(compiled, job_dir)
                render_result = render_result.model_copy(update={
                    "image_provenance_path": provenance_path,
                })
                checkpoint.save(stage, render_result)

            stage = "quality"
            await self._announce(progress_callback, stage)
            quality_report_path = job_dir / "quality.json"
            if checkpoint.completed(stage):
                quality_payload = checkpoint.load(stage)
                problems = quality_payload["problems"]
                if problems:
                    checkpoint.invalidate([stage])
            if not checkpoint.completed(stage):
                problems = self.quality_service.validate(compiled, render_result)
                quality_report_path.write_text(
                    json.dumps({"problems": problems}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                checkpoint.save(stage, {"problems": problems})
            if problems:
                raise RuntimeError("Quality validation failed: " + "; ".join(problems))
            render_result = render_result.model_copy(update={
                "quality_report_path": quality_report_path,
                "image_provenance_path": provenance_path,
            })
            checkpoint.save("render", render_result)
            return GenerationResult(job_id=job_id, render_result=render_result)
        except Exception as error:
            checkpoint.fail(stage, error)
            raise

    def _validate_dependencies(self) -> None:
        dependencies = {
            "topic generator": self.topic_generator,
            "researcher": self.researcher,
            "script writer": self.script_writer,
            "verifier": self.verifier,
            "director": self.director,
            "beat TTS": self.beat_tts,
            "image service": self.image_service,
            "audio service": self.audio_service,
            "SFX service": self.sfx_service,
            "timeline compiler": self.timeline_compiler,
            "renderer": self.renderer,
            "quality service": self.quality_service,
        }
        missing = [name for name, dependency in dependencies.items() if dependency is None]
        if missing:
            raise RuntimeError("Missing generation dependencies: " + ", ".join(missing))

    async def _generate_verified_script(
        self,
        topic: TopicSpec,
        research: ResearchPackage,
        request: GenerationRequest,
        repair_notes: list[str],
    ) -> tuple[ReferenceScriptPackage, VerificationResult]:
        notes = list(repair_notes)
        verification = VerificationResult(approved=False)
        script: ReferenceScriptPackage | None = None
        for _ in range(2):
            script = await self.script_writer.generate(
                topic,
                research,
                request.target_duration_seconds,
                request.language,
                notes,
            )
            verification = await self.verifier.verify(script, research, topic)
            if verification.approved:
                return script, verification
            notes = [*repair_notes, *verification.required_changes]
        raise RuntimeError(
            "Script verification failed: " + "; ".join(verification.required_changes)
        )

    @staticmethod
    def _word_budget(request: GenerationRequest) -> int:
        return request.target_duration_seconds * 2

    @staticmethod
    def _duration_is_acceptable(duration_seconds: float) -> bool:
        return 20.0 <= duration_seconds <= 60.0

    @classmethod
    def _duration_repair_note(
        cls,
        duration_seconds: float,
        request: GenerationRequest,
    ) -> str:
        action = "Shorten" if duration_seconds > 30.0 else "Expand"
        return (
            f"Measured narration duration was {duration_seconds:.1f}s. {action} the spoken text "
            f"to target {request.target_duration_seconds}s and stay within 20-60 seconds. "
            f"Use at most {cls._word_budget(request)} spoken words."
        )

    @staticmethod
    async def _announce(callback: Optional[Callable[[str], Any]], stage: str) -> None:
        if callback is None:
            return
        result = callback(stage)
        if inspect.isawaitable(result):
            await result
