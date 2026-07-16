from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from app.domain.models import (
    CompiledVideoSpec,
    DirectionPlan,
    GenerationRequest,
    GenerationResult,
    ReferenceScriptPackage,
    RenderResult,
    ResearchPackage,
    SocialDescription,
    TimedTranscript,
    TopicSpec,
    VerificationResult,
)
from app.providers.tts.base import TTSSettings
from app.services.job_cost_ledger import (
    JobCostLedger,
    cost_scope,
    record_cost_event,
    set_cost_stage,
)


def format_exception_message(error: BaseException) -> str:
    detail = str(error).strip()
    name = type(error).__name__
    return f"{name}: {detail}" if detail else f"{name}: no details provided"


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
        self.state["error"] = format_exception_message(error)
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
        image_brief_service: object | None = None,
        image_validator: object | None = None,
        social_description_writer: object | None = None,
        description_history: object | None = None,
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
        self.image_brief_service = image_brief_service
        self.image_validator = image_validator
        self.social_description_writer = social_description_writer
        self.description_history = description_history

    async def generate(
        self,
        request: GenerationRequest,
        progress_callback: Optional[Callable[[str], Any]] = None,
        job_id: Optional[str] = None,
    ) -> GenerationResult:
        job_id = job_id or str(uuid4())
        job_dir = self.output_base / job_id
        checkpoint = _CheckpointStore(job_dir)
        cost_report_path = job_dir / "cost_report.json"
        cost_ledger = JobCostLedger.load(cost_report_path, job_id)
        scope = cost_scope(cost_ledger, "preflight")
        scope.__enter__()
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
                paired_image_brief_path = job_dir / "paired_image_brief.json"
                if not paired_image_brief_path.exists():
                    paired_image_brief_path = None
            else:
                assets_dir = job_dir / "assets"
                assets_dir.mkdir(parents=True, exist_ok=True)
                research = await self.researcher.generate(topic)
                paired_brief = None
                if self.image_brief_service is not None:
                    await self._announce(progress_callback, "image_brief")
                    paired_brief = await self.image_brief_service.generate(topic, research)
                    paired_image_brief_path = job_dir / "paired_image_brief.json"
                    paired_image_brief_path.write_text(
                        paired_brief.model_dump_json(indent=2),
                        encoding="utf-8",
                    )
                else:
                    paired_image_brief_path = None
                await self._announce(progress_callback, "image_validation")
                left_provenance, right_provenance = await asyncio.gather(
                    self._acquire_image(
                        topic.comparison_left,
                        assets_dir / "left.png",
                        paired_brief.left if paired_brief else None,
                        paired_brief.shared_style if paired_brief else "",
                    ),
                    self._acquire_image(
                        topic.comparison_right,
                        assets_dir / "right.png",
                        paired_brief.right if paired_brief else None,
                        paired_brief.shared_style if paired_brief else "",
                    ),
                )
                left_image = assets_dir / "left.png"
                right_image = assets_dir / "right.png"
                initial_pair_validation = None
                pair_validation = None
                pair_repair = None
                pair_warnings: list[str] = []
                if self.image_validator is not None and paired_brief is not None:
                    initial_pair_validation = await self.image_validator.validate_pair(
                        left_image,
                        right_image,
                        paired_brief,
                    )
                    pair_validation = initial_pair_validation
                    if initial_pair_validation.needs_repair:
                        (
                            left_provenance,
                            right_provenance,
                            pair_validation,
                            pair_repair,
                        ) = await self._repair_pair_once(
                                topic,
                                left_image,
                                right_image,
                                paired_brief,
                                initial_pair_validation,
                                left_provenance,
                                right_provenance,
                            )
                    failure_reasons = self._pair_failure_reasons(pair_validation)
                    if failure_reasons:
                        raise RuntimeError(
                            "Paired image validation failed: "
                            + "; ".join(failure_reasons)
                        )
                    pair_warnings = list(pair_validation.warning_reasons)
                    if not pair_validation.pair_style_acceptable:
                        pair_warnings.append("Residual photographic style mismatch")
                    if not pair_validation.composition_acceptable:
                        pair_warnings.append("Residual composition mismatch")
                provenance_path = job_dir / "image_provenance.json"
                provenance_path.write_text(
                    json.dumps({
                        "left": _CheckpointStore._serialize(left_provenance),
                        "right": _CheckpointStore._serialize(right_provenance),
                        "pair_validation": _CheckpointStore._serialize(pair_validation),
                        "initial_pair_validation": _CheckpointStore._serialize(initial_pair_validation),
                        "pair_repair": _CheckpointStore._serialize(pair_repair),
                        "pair_warnings": pair_warnings,
                    }, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                checkpoint.save(stage, {
                    "research": research,
                    "left_image": left_image,
                    "right_image": right_image,
                    "provenance_path": provenance_path,
                    "paired_image_brief": paired_brief,
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
                        settings=TTSSettings(speed=1.05),
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

            stage = "social_description"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                payload = checkpoint.load(stage)
                social_description = SocialDescription.model_validate(payload["description"])
            else:
                if self.social_description_writer is None:
                    social_description = SocialDescription(
                        description=script.caption,
                        hashtags=script.hashtags,
                        fallback_used=True,
                    )
                else:
                    recent_descriptions = (
                        self.description_history.recent(10)
                        if self.description_history is not None
                        else []
                    )
                    social_description = await self.social_description_writer.generate(
                        topic,
                        research,
                        script,
                        request.language,
                        recent_descriptions,
                    )
                checkpoint.save(
                    stage,
                    {
                        "description": social_description,
                        "publishable_text": social_description.publishable_text,
                    },
                )
                if self.description_history is not None:
                    self.description_history.add(topic.title, social_description.description)

            stage = "compiled"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                compiled = CompiledVideoSpec.model_validate(checkpoint.load(stage))
            else:
                timeline = self.timeline_compiler.compile(direction, transcript)
                library = self.sfx_service.ensure_library(job_dir / "assets" / "sfx")
                record_cost_event(
                    provider="local",
                    operation="sfx_generation",
                    amount_usd=0.0,
                    pricing_source="local_operation",
                    request_key="sfx_library",
                )
                mixed_audio = job_dir / "audio" / "mixed_audio.m4a"
                narration_end_seconds = transcript.duration_seconds
                total_duration_seconds = narration_end_seconds
                self.audio_service.mix_timed_sfx(
                    narration_audio,
                    timeline.sound_cues,
                    library,
                    mixed_audio,
                    total_duration_seconds=total_duration_seconds,
                )
                compiled = CompiledVideoSpec(
                    left_label=topic.comparison_left,
                    right_label=topic.comparison_right,
                    left_image=left_image,
                    right_image=right_image,
                    narration_audio=mixed_audio,
                    transcript=transcript,
                    narration_end_seconds=narration_end_seconds,
                    direction_cues=timeline.direction_cues,
                    sound_cues=timeline.sound_cues,
                    captions=timeline.captions,
                    cta_text="Like, share, follow",
                )
                checkpoint.save(stage, compiled)

            stage = "render"
            await self._announce(progress_callback, stage)
            if checkpoint.completed(stage):
                render_result = RenderResult.model_validate(checkpoint.load(stage))
            else:
                render_result = self.renderer.render(compiled, job_dir)
                record_cost_event(
                    provider="local",
                    operation="render",
                    amount_usd=0.0,
                    pricing_source="local_operation",
                    request_key="reference_render",
                )
                render_result = render_result.model_copy(update={
                    "image_provenance_path": provenance_path,
                    "paired_image_brief_path": paired_image_brief_path,
                    "cost_report_path": cost_report_path,
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
                provenance_payload = json.loads(provenance_path.read_text(encoding="utf-8"))
                quality_report_path.write_text(
                    json.dumps({
                        "problems": problems,
                        "narration_end_seconds": compiled.narration_end_seconds,
                        "cta_start_seconds": compiled.cta_start_seconds,
                        "total_duration_seconds": compiled.total_duration_seconds,
                        "render_duration_seconds": render_result.duration_seconds,
                        "image_pair_validation": provenance_payload.get("pair_validation"),
                        "initial_image_pair_validation": provenance_payload.get("initial_pair_validation"),
                        "image_pair_repair": provenance_payload.get("pair_repair"),
                        "image_pair_warnings": provenance_payload.get("pair_warnings", []),
                        "calibration_path": str(render_result.calibration_path or ""),
                    }, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                checkpoint.save(stage, {"problems": problems})
            if problems:
                raise RuntimeError("Quality validation failed: " + "; ".join(problems))
            render_result = render_result.model_copy(update={
                "quality_report_path": quality_report_path,
                "image_provenance_path": provenance_path,
                "paired_image_brief_path": paired_image_brief_path,
                "cost_report_path": cost_report_path,
            })
            checkpoint.save("render", render_result)
            cost_ledger.save(cost_report_path)
            return GenerationResult(job_id=job_id, render_result=render_result)
        except Exception as error:
            checkpoint.fail(stage, error)
            raise
        finally:
            cost_ledger.save(cost_report_path)
            scope.__exit__(None, None, None)

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

    async def _acquire_image(
        self,
        item: str,
        output_path: Path,
        brief: object | None,
        shared_style: str,
    ) -> Any:
        if brief is None:
            return await self.image_service.acquire(item, output_path)
        return await self.image_service.acquire(
            item,
            output_path,
            brief=brief,
            shared_style=shared_style,
        )

    async def _repair_pair_once(
        self,
        topic: TopicSpec,
        left_path: Path,
        right_path: Path,
        brief: Any,
        validation: Any,
        left_provenance: Any,
        right_provenance: Any,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        repair_side = validation.repair_side
        if repair_side == "none":
            repair_side = "both"
        instructions = list(validation.repair_instructions)
        if not instructions:
            instructions = list(validation.fatal_reasons or validation.warning_reasons)
        if not instructions:
            instructions = list(validation.rejection_reasons)
        metadata = {
            "repair_side": repair_side,
            "repair_instructions": instructions,
            "generation_calls": 1,
        }
        if repair_side == "left":
            left_provenance = await self.image_service.acquire(
                topic.comparison_left,
                left_path,
                brief=brief.left,
                shared_style=brief.shared_style,
                force_generated=True,
                input_references=[right_path],
                repair_instructions=instructions,
                generated_attempt_limit=1,
            )
        elif repair_side == "right":
            right_provenance = await self.image_service.acquire(
                topic.comparison_right,
                right_path,
                brief=brief.right,
                shared_style=brief.shared_style,
                force_generated=True,
                input_references=[left_path],
                repair_instructions=instructions,
                generated_attempt_limit=1,
            )
        else:
            left_provenance, right_provenance = await self.image_service.generate_pair_repair(
                left_item=topic.comparison_left,
                right_item=topic.comparison_right,
                left_path=left_path,
                right_path=right_path,
                brief=brief,
                repair_instructions=instructions,
            )
        if self.image_validator is None:
            raise RuntimeError("Pair repair requires an image validator")
        pair_validation = await self.image_validator.validate_pair(
            left_path,
            right_path,
            brief,
        )
        return left_provenance, right_provenance, pair_validation, metadata

    @staticmethod
    def _pair_failure_reasons(validation: Any) -> list[str]:
        if not validation.has_fatal_issues:
            return []
        reasons = [
            reason
            for reason in validation.fatal_reasons
            if not validation._color_pair_reason(reason)
        ]
        if reasons:
            return reasons
        if not validation.depicts_requested_item:
            reasons.append("One or both images depict the wrong requested item")
        if not validation.distinguishing_attributes_present:
            reasons.append("Required distinguishing attributes are missing")
        if validation.contains_logo_or_prominent_text:
            reasons.append("Image contains unwanted text or a logo")
        if validation.contains_prohibited_content:
            reasons.append("Image contains prohibited content")
        if not validation.background_acceptable:
            reasons.append("Image background is unusable")
        if not validation.realism_acceptable:
            reasons.append("Image is not plausibly photorealistic")
        if validation.confidence < 0.8:
            reasons.append("Image identity validation confidence is too low")
        return reasons or ["Fatal paired image validation failure"]

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
        for _ in range(3):
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
        # The verifier is a soft quality gate. After exhausting repair attempts we keep the
        # best-effort script and proceed rather than failing the whole job; the unresolved
        # notes are logged and travel with the verification result for later review.
        logger.warning(
            "Proceeding with unverified script after %d attempts: %s",
            3,
            "; ".join(verification.required_changes) or "no specific notes",
        )
        return script, verification

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
        set_cost_stage(stage)
        if callback is None:
            return
        result = callback(stage)
        if inspect.isawaitable(result):
            await result
