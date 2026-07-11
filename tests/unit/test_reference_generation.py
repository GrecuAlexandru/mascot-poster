from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from app.domain.enums import Focus, MascotAnchor, MascotPose
from app.domain.models import (
    DirectionCue,
    DirectionPlan,
    NarrationBeat,
    ReferenceScriptPackage,
    ResearchPackage,
    GenerationRequest,
    RenderResult,
    TimedBeat,
    TimedTranscript,
    TimedWord,
    TopicSpec,
)
from app.services.reference_direction_service import ReferenceDirectionService
from app.services.reference_script_service import ReferenceScriptService
from app.services.timeline_compiler import TimelineCompiler
from app.services.video_generation_service import VideoGenerationService


def test_reference_duration_gate_accepts_60_seconds() -> None:
    assert VideoGenerationService._duration_is_acceptable(60.0)


def test_reference_script_service_requests_romanian_beat_schema() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.calls = []

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.calls.append((system, user, model_type, kwargs))
            return ReferenceScriptPackage(
                title="Cafea vs Ceai",
                left_item="Cafea",
                right_item="Ceai",
                hook="Diferența începe aici.",
                beats=[NarrationBeat(id="b0", text="Cafeaua acționează rapid.")],
                closing=NarrationBeat(
                    id="closing",
                    text="Așadar, alege opțiunea care se potrivește mai bine nevoilor tale.",
                    pause_after_ms=500,
                ),
                caption="Cafea sau ceai?",
            )

    llm = FakeLLM()
    service = ReferenceScriptService(llm)
    topic = TopicSpec(title="Cafea vs Ceai", comparison_left="Cafea", comparison_right="Ceai")
    research = ResearchPackage(topic="Cafea vs Ceai", left_item="Cafea", right_item="Ceai")

    result = asyncio.run(service.generate(topic, research, target_duration_seconds=25, language="ro"))

    assert result.beats[0].id == "b0"
    assert llm.calls[0][2] is ReferenceScriptPackage
    assert llm.calls[0][3]["schema_name"] == "reference_script"
    assert "română" in llm.calls[0][1].casefold()


def test_reference_direction_service_returns_word_anchored_cues() -> None:
    class FakeLLM:
        async def complete_structured(self, system, user, model_type, **kwargs):
            return DirectionPlan(cues=[DirectionCue(
                beat_id="b0",
                word_index=1,
                mascot_pose=MascotPose.POINT_LEFT,
                mascot_anchor=MascotAnchor.LEFT,
                product_focus=Focus.LEFT,
            )])

    script = ReferenceScriptPackage(
        title="Cafea vs Ceai",
        left_item="Cafea",
        right_item="Ceai",
        hook="Hook",
        beats=[NarrationBeat(id="b0", text="Cafeaua acționează rapid.")],
        closing=NarrationBeat(
            id="closing",
            text="Așadar, alege opțiunea care se potrivește mai bine nevoilor tale.",
            pause_after_ms=500,
        ),
        caption="Cafea sau ceai?",
    )

    result = asyncio.run(ReferenceDirectionService(FakeLLM()).generate(script, language="ro"))

    assert result.cues[0].beat_id == "b0"
    assert result.cues[0].word_index == 1


def test_direction_service_replaces_all_neutral_anchor_travel() -> None:
    class AllNeutralLLM:
        async def complete_structured(self, system, user, model_type, **kwargs):
            return DirectionPlan(cues=[
                DirectionCue(
                    beat_id="left",
                    word_index=0,
                    mascot_pose=MascotPose.NEUTRAL,
                    mascot_anchor=MascotAnchor.LEFT,
                    product_focus=Focus.LEFT,
                ),
                DirectionCue(
                    beat_id="right",
                    word_index=0,
                    mascot_pose=MascotPose.NEUTRAL,
                    mascot_anchor=MascotAnchor.RIGHT,
                    product_focus=Focus.RIGHT,
                ),
            ])

    script = ReferenceScriptPackage(
        title="Cafea vs Ceai",
        left_item="Cafea",
        right_item="Ceai",
        hook="Comparația contează.",
        beats=[
            NarrationBeat(id="left", text="Cafeaua acționează rapid.", pause_after_ms=300),
            NarrationBeat(id="right", text="Ceaiul acționează mai blând.", pause_after_ms=300),
        ],
        closing=NarrationBeat(
            id="closing",
            text="Așadar, alege băutura potrivită pentru ritmul și nevoile tale.",
            pause_after_ms=750,
        ),
        caption="Cafea sau ceai?",
    )

    result = asyncio.run(ReferenceDirectionService(AllNeutralLLM()).generate(script, "ro"))

    assert all(cue.mascot_anchor == MascotAnchor.CENTER for cue in result.cues)
    assert any(cue.mascot_pose != MascotPose.NEUTRAL for cue in result.cues)
    assert any(cue.mascot_pose == MascotPose.POINT_LEFT for cue in result.cues)
    assert any(cue.mascot_pose == MascotPose.POINT_RIGHT for cue in result.cues)
    assert max(
        sum(candidate.beat_id == beat.id for candidate in result.cues)
        for beat in script.all_beats
    ) <= 2


def test_video_generation_service_checkpoints_and_resumes(tmp_path: Path) -> None:
    class TopicGenerator:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, request):
            self.calls += 1
            return TopicSpec(title="Cafea vs Ceai", comparison_left="Cafea", comparison_right="Ceai")

    class Researcher:
        async def generate(self, topic):
            return ResearchPackage(topic=topic.title, left_item=topic.comparison_left, right_item=topic.comparison_right)

    class ScriptWriter:
        async def generate(self, topic, research, target_duration_seconds, language, repair_notes=None):
            return ReferenceScriptPackage(
                title=topic.title,
                left_item=topic.comparison_left,
                right_item=topic.comparison_right,
                hook="Hook",
                beats=[NarrationBeat(id="b0", text="Cafeaua acționează rapid.")],
                closing=NarrationBeat(
                    id="closing",
                    text="Așadar, alege opțiunea care se potrivește mai bine nevoilor tale.",
                    pause_after_ms=500,
                ),
                caption="Cafea sau ceai?",
            )

    class Verifier:
        async def verify(self, script, research, topic):
            from app.domain.models import VerificationResult
            return VerificationResult(approved=True)

    class Director:
        async def generate(self, script, language):
            return DirectionPlan(cues=[DirectionCue(
                beat_id="b0", word_index=0, mascot_pose=MascotPose.POINT_LEFT,
                mascot_anchor=MascotAnchor.LEFT, product_focus=Focus.LEFT,
            )])

    class TTS:
        def __init__(self) -> None:
            self.settings = None

        async def synthesize(self, script, voice_id, language, output_dir, settings=None):
            self.settings = settings
            output_dir.mkdir(parents=True, exist_ok=True)
            audio = output_dir / "narration.wav"
            audio.write_bytes(b"audio")
            transcript = TimedTranscript(
                words=[
                    TimedWord(word="Cafeaua", start=0.0, end=0.3),
                    TimedWord(word="acționează", start=0.3, end=0.6),
                    TimedWord(word="rapid.", start=0.6, end=0.9),
                ],
                    beats=[TimedBeat(id="b0", start=0.0, end=0.9, pause_end=25.0)],
                    duration_seconds=25.0,
            )
            return audio, transcript

    class Images:
        async def acquire(self, item, output_path, provenance_path=None):
            Image.new("RGBA", (400, 400), (255, 255, 255, 0)).save(output_path)
            return {"item": item, "path": str(output_path), "source_type": "generated"}

    class Audio:
        def mix_timed_sfx(
            self,
            narration_path,
            cues,
            library,
            output_path,
            total_duration_seconds=None,
        ):
            output_path.write_bytes(narration_path.read_bytes())
            return output_path

    class Sfx:
        def ensure_library(self, output_dir):
            return {}

    class Renderer:
        def __init__(self) -> None:
            self.calls = 0

        def render(self, spec, output_dir):
            self.calls += 1
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = {name: output_dir / name for name in ("video.mp4", "poster.jpg", "sheet.jpg", "timeline.json", "transcript.json", "direction.json")}
            for path in paths.values():
                path.write_bytes(b"artifact")
            return RenderResult(
                video_path=paths["video.mp4"], poster_path=paths["poster.jpg"],
                contact_sheet_path=paths["sheet.jpg"], timeline_path=paths["timeline.json"],
                transcript_path=paths["transcript.json"], direction_path=paths["direction.json"],
                        duration_seconds=spec.total_duration_seconds,
                        frame_count=round(spec.total_duration_seconds * 30),
                        resolution=(1080, 1920), scene_count=1,
            )

    class Quality:
        def validate(self, spec, result):
            return []

    topic = TopicGenerator()
    renderer = Renderer()
    tts = TTS()
    service = VideoGenerationService(
        output_base=tmp_path / "jobs",
        topic_generator=topic,
        researcher=Researcher(),
        script_writer=ScriptWriter(),
        verifier=Verifier(),
        director=Director(),
        beat_tts=tts,
        image_service=Images(),
        audio_service=Audio(),
        sfx_service=Sfx(),
        timeline_compiler=TimelineCompiler(),
        renderer=renderer,
        quality_service=Quality(),
    )
    stages = []

    first = asyncio.run(service.generate(GenerationRequest(), stages.append, job_id="job-1"))
    second = asyncio.run(service.generate(GenerationRequest(), stages.append, job_id="job-1"))

    state = json.loads((tmp_path / "jobs" / "job-1" / "_pipeline" / "state.json").read_text())
    assert first.job_id == "job-1"
    assert second.render_result.video_path == first.render_result.video_path
    assert topic.calls == 1
    assert renderer.calls == 1
    assert tts.settings.speed == pytest.approx(0.8)
    assert "quality" in state["completed"]
    assert stages[0] == "preflight"
    assert first.render_result.cost_report_path == tmp_path / "jobs" / "job-1" / "cost_report.json"
    report = json.loads(first.render_result.cost_report_path.read_text(encoding="utf-8"))
    assert report["job_id"] == "job-1"
    assert report["by_stage"]["render"] == 0.0
    assert len(report["events"]) == len({event["event_id"] for event in report["events"]})


def test_video_generation_repairs_tts_that_exceeds_the_60_second_maximum(tmp_path: Path) -> None:
    class TopicGenerator:
        async def generate(self, request):
            return TopicSpec(title="Coffee vs Tea", comparison_left="Coffee", comparison_right="Tea")

    class Researcher:
        async def generate(self, topic):
            return ResearchPackage(topic=topic.title, left_item=topic.comparison_left, right_item=topic.comparison_right)

    class ScriptWriter:
        def __init__(self) -> None:
            self.repair_notes: list[list[str]] = []

        async def generate(self, topic, research, target_duration_seconds, language, repair_notes=None):
            self.repair_notes.append(list(repair_notes or []))
            long_script = not repair_notes
            return ReferenceScriptPackage(
                title=topic.title,
                left_item=topic.comparison_left,
                right_item=topic.comparison_right,
                hook="long" if long_script else "short",
                beats=[NarrationBeat(
                    id="b0",
                    text=" ".join(["word"] * (40 if long_script else 30)),
                )],
                closing=NarrationBeat(
                    id="closing",
                    text="Therefore, choose the option that best fits your current needs.",
                    pause_after_ms=500,
                ),
                caption="Coffee or tea?",
            )

    class Verifier:
        async def verify(self, script, research, topic):
            from app.domain.models import VerificationResult
            return VerificationResult(approved=True)

    class Director:
        def __init__(self) -> None:
            self.hooks: list[str] = []

        async def generate(self, script, language):
            self.hooks.append(script.hook)
            return DirectionPlan(cues=[DirectionCue(
                beat_id="b0", word_index=0, mascot_pose=MascotPose.POINT_LEFT,
                mascot_anchor=MascotAnchor.LEFT, product_focus=Focus.LEFT,
            )])

    class TTS:
        def __init__(self) -> None:
            self.calls = 0

        async def synthesize(self, script, voice_id, language, output_dir, settings=None):
            self.calls += 1
            output_dir.mkdir(parents=True, exist_ok=True)
            duration = 61.0 if script.hook == "long" else 24.0
            audio = output_dir / f"narration_{self.calls}.wav"
            audio.write_bytes(b"audio")
            return audio, TimedTranscript(
                words=[TimedWord(word="word", start=0.0, end=0.1)],
                beats=[TimedBeat(id="b0", start=0.0, end=0.1, pause_end=duration)],
                duration_seconds=duration,
            )

    class Images:
        async def acquire(self, item, output_path, provenance_path=None):
            Image.new("RGBA", (400, 400), (255, 255, 255, 0)).save(output_path)
            return {"item": item, "path": str(output_path), "source_type": "generated"}

    class Audio:
        def mix_timed_sfx(
            self,
            narration_path,
            cues,
            library,
            output_path,
            total_duration_seconds=None,
        ):
            output_path.write_bytes(narration_path.read_bytes())
            return output_path

    class Sfx:
        def ensure_library(self, output_dir):
            return {}

    class Renderer:
        def __init__(self) -> None:
            self.durations: list[float] = []

        def render(self, spec, output_dir):
            self.durations.append(spec.total_duration_seconds)
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = {name: output_dir / name for name in ("video.mp4", "poster.jpg", "sheet.jpg", "timeline.json")}
            for path in paths.values():
                path.write_bytes(b"artifact")
            return RenderResult(
                video_path=paths["video.mp4"], poster_path=paths["poster.jpg"],
                contact_sheet_path=paths["sheet.jpg"], timeline_path=paths["timeline.json"],
                duration_seconds=spec.total_duration_seconds,
                frame_count=round(spec.total_duration_seconds * 30),
                resolution=(1080, 1920), scene_count=1,
            )

    class Quality:
        def validate(self, spec, result):
            return []

    script_writer = ScriptWriter()
    director = Director()
    tts = TTS()
    renderer = Renderer()
    service = VideoGenerationService(
        output_base=tmp_path / "jobs",
        topic_generator=TopicGenerator(),
        researcher=Researcher(),
        script_writer=script_writer,
        verifier=Verifier(),
        director=director,
        beat_tts=tts,
        image_service=Images(),
        audio_service=Audio(),
        sfx_service=Sfx(),
        timeline_compiler=TimelineCompiler(),
        renderer=renderer,
        quality_service=Quality(),
    )

    result = asyncio.run(service.generate(GenerationRequest(target_duration_seconds=25)))

    assert result.render_result.duration_seconds == 25.8
    assert tts.calls == 2
    assert director.hooks == ["short"]
    assert renderer.durations == [25.8]
    assert "Measured narration duration was 61.0s" in script_writer.repair_notes[1][0]
