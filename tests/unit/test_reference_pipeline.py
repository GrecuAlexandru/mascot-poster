from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from app.domain.enums import Focus, MascotAnchor, MascotPose, SfxKind
from app.domain.models import (
    AbsoluteDirectionCue,
    CaptionCue,
    ClosingBeat,
    CompiledTimeline,
    CompiledVideoSpec,
    DirectionCue,
    DirectionPlan,
    GenerationRequest,
    GenerationResult,
    NarrationBeat,
    ReferenceScriptPackage,
    TimedBeat,
    TimedTranscript,
    TimedWord,
    RenderResult,
    SoundEffectCue,
)
from app.providers.llm.openai_provider import LLMProvider
from app.providers.tts.base import TTSResult, TTSSettings, TimedWord as ProviderTimedWord
from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
from app.services.beat_tts_service import BeatTTSService
from app.services.audio_service import AudioService
from app.config import Settings
from app.services.timeline_compiler import TimelineCompiler
from app.services.reference_quality_service import ReferenceQualityService
from app.services.reference_image_validator import ReferenceImageValidator
from app.services.video_generation_service import _CheckpointStore
import app.services.reference_generation_factory as reference_factory


def test_generation_request_defaults_to_romanian_reference_duration() -> None:
    request = GenerationRequest()

    assert request.language == "ro"
    assert request.target_duration_seconds == 25


@pytest.mark.parametrize("duration", [19, 61])
def test_generation_request_rejects_duration_outside_reference_range(duration: int) -> None:
    with pytest.raises(ValueError):
        GenerationRequest(target_duration_seconds=duration)


def test_generation_request_accepts_a_60_second_reference_video() -> None:
    request = GenerationRequest(target_duration_seconds=60)

    assert request.target_duration_seconds == 60


def test_narration_beat_accepts_only_supported_pause_lengths() -> None:
    beat = NarrationBeat(id="hook", text="Știi care este diferența?", pause_after_ms=300)

    assert beat.pause_after_ms == 300
    with pytest.raises(ValueError):
        NarrationBeat(id="bad", text="Text", pause_after_ms=275)


def test_reference_script_exposes_exact_spoken_text() -> None:
    script = ReferenceScriptPackage(
        title="Cafea vs ceai",
        left_item="Cafea",
        right_item="Ceai",
        hook="Diferența contează",
        beats=[
            NarrationBeat(id="b0", text="Cafeaua acționează rapid.", pause_after_ms=300),
            NarrationBeat(id="b1", text="Ceaiul este mai blând.", pause_after_ms=0),
        ],
        closing=ClosingBeat(
            id="closing",
            text="Așadar, alege băutura care se potrivește mai bine nevoilor tale.",
            pause_after_ms=500,
        ),
        caption="Cafea sau ceai?",
    )

    assert script.narration_text.endswith("mai bine nevoilor tale.")


def test_reference_script_rejects_fragmentary_closing() -> None:
    with pytest.raises(ValueError, match="closing"):
        ReferenceScriptPackage(
            title="Cafea vs ceai",
            left_item="Cafea",
            right_item="Ceai",
            hook="Diferența contează",
            beats=[NarrationBeat(id="b0", text="Cafeaua acționează rapid.")],
            closing=ClosingBeat(id="b8", text="Un fragment", pause_after_ms=0),
            caption="Cafea sau ceai?",
        )


def test_reference_script_accepts_short_signed_closing() -> None:
    script = ReferenceScriptPackage(
        title="Coffee vs tea",
        left_item="Coffee",
        right_item="Tea",
        hook="The difference matters",
        beats=[NarrationBeat(id="b0", text="Coffee acts quickly.")],
        closing=ClosingBeat(id="closing", text="Hugs from Pufăilă!", pause_after_ms=500),
        caption="Coffee or tea?",
    )

    assert script.all_beats[-1].text == "Hugs from Pufăilă!"


def test_reference_script_all_beats_ends_with_conclusive_closing() -> None:
    script = ReferenceScriptPackage(
        title="Cafea vs ceai",
        left_item="Cafea",
        right_item="Ceai",
        hook="Diferența contează",
        beats=[NarrationBeat(id="b0", text="Cafeaua acționează rapid.")],
        closing=ClosingBeat(
            id="closing",
            text="Așadar, alege varianta care se potrivește mai bine nevoilor tale.",
            pause_after_ms=500,
        ),
        caption="Cafea sau ceai?",
    )

    assert script.all_beats[-1].id == "closing"
    assert script.narration_text.endswith("nevoilor tale.")


def test_timed_transcript_rejects_overlapping_words() -> None:
    with pytest.raises(ValueError, match="overlap"):
        TimedTranscript(
            words=[
                TimedWord(word="unu", start=0.0, end=0.5),
                TimedWord(word="doi", start=0.4, end=0.9),
            ],
            beats=[TimedBeat(id="b0", start=0.0, end=0.9, pause_end=0.9)],
            duration_seconds=0.9,
        )


def test_direction_plan_uses_stable_word_anchors() -> None:
    plan = DirectionPlan(
        cues=[
            DirectionCue(
                beat_id="b0",
                word_index=1,
                mascot_pose=MascotPose.POINT_LEFT,
                mascot_anchor=MascotAnchor.LEFT,
                product_focus=Focus.LEFT,
                sfx_kind=SfxKind.WHOOSH,
            )
        ]
    )

    assert plan.cues[0].word_index == 1
    assert plan.cues[0].mascot_anchor == MascotAnchor.LEFT


def test_compiled_video_spec_requires_existing_media(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "narration.wav"
    for path in (left, right, audio):
        path.write_bytes(b"fixture")

    transcript = TimedTranscript(
        words=[TimedWord(word="test", start=0.0, end=0.5)],
        beats=[TimedBeat(id="b0", start=0.0, end=0.5, pause_end=0.5)],
        duration_seconds=0.5,
    )
    spec = CompiledVideoSpec(
        left_label="Cafea",
        right_label="Ceai",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=transcript,
        direction_cues=[
            AbsoluteDirectionCue(
                start=0.0,
                mascot_pose=MascotPose.NEUTRAL,
                mascot_anchor=MascotAnchor.CENTER,
            )
        ],
    )

    assert spec.template == "reference_v1"
    assert spec.fps == 30
    assert spec.narration_end_seconds == pytest.approx(0.5)
    assert spec.total_duration_seconds == pytest.approx(0.5)

    with pytest.raises(ValueError, match="left_image"):
        CompiledVideoSpec(
            left_label="Cafea",
            right_label="Ceai",
            left_image=tmp_path / "missing.png",
            right_image=right,
            narration_audio=audio,
            transcript=transcript,
            direction_cues=[],
        )


def test_compiled_video_spec_adds_outro_after_last_speech(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "narration.wav"
    for path in (left, right, audio):
        path.write_bytes(b"asset")
    transcript = TimedTranscript(
        words=[TimedWord(word="final", start=25.0, end=25.638)],
        beats=[TimedBeat(id="closing", start=24.0, end=25.178, pause_end=25.678)],
        duration_seconds=25.678,
    )

    spec = CompiledVideoSpec(
        left_label="Coffee",
        right_label="Tea",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=transcript,
        narration_end_seconds=25.678,
    )

    # The CTA bubble appears while the closing signoff is spoken (closing beat start),
    # while the video still runs a full outro after narration ends.
    assert spec.cta_start_seconds == pytest.approx(24.0)
    assert spec.narration_end == pytest.approx(25.678)
    assert spec.total_duration_seconds == pytest.approx(25.678)


def test_generation_result_exposes_reference_artifacts(tmp_path: Path) -> None:
    paths = {
        name: tmp_path / name
        for name in (
            "video.mp4",
            "poster.jpg",
            "contact.jpg",
            "timeline.json",
            "transcript.json",
            "direction.json",
            "provenance.json",
            "quality.json",
            "cost.json",
        )
    }
    for path in paths.values():
        path.write_bytes(b"artifact")
    render = RenderResult(
        video_path=paths["video.mp4"],
        poster_path=paths["poster.jpg"],
        contact_sheet_path=paths["contact.jpg"],
        timeline_path=paths["timeline.json"],
        transcript_path=paths["transcript.json"],
        direction_path=paths["direction.json"],
        image_provenance_path=paths["provenance.json"],
        quality_report_path=paths["quality.json"],
        cost_report_path=paths["cost.json"],
        duration_seconds=25.0,
        frame_count=750,
        resolution=(1080, 1920),
        scene_count=5,
    )
    result = GenerationResult(job_id="job-1", render_result=render)

    assert result.render_result.transcript_path == paths["transcript.json"]
    assert result.render_result.cost_report_path == paths["cost.json"]
    assert result.job_id == "job-1"


def test_openrouter_request_requires_strict_schema_and_fallbacks() -> None:
    provider = LLMProvider(
        api_key="test",
        model="deepseek/deepseek-v4-flash",
        fallback_models=["qwen/qwen3.5-flash-02-23"],
    )
    schema = GenerationRequest.model_json_schema()

    body = provider._build_request_body(
        system_prompt="system",
        user_prompt="user",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "generation_request", "strict": True, "schema": schema},
        },
        temperature=0.2,
        max_tokens=1000,
    )

    assert body["models"] == [
        "deepseek/deepseek-v4-flash",
        "qwen/qwen3.5-flash-02-23",
    ]
    assert body["route"] == "fallback"
    assert body["provider"]["require_parameters"] is True
    assert body["response_format"]["json_schema"]["strict"] is True


def test_complete_structured_validates_pydantic_result() -> None:
    provider = LLMProvider(api_key="test")
    provider.complete = AsyncMock(return_value='{"language":"ro","target_duration_seconds":25}')

    result = asyncio.run(
        provider.complete_structured(
            "system",
            "user",
            GenerationRequest,
            schema_name="generation_request",
        )
    )

    assert isinstance(result, GenerationRequest)
    assert result.language == "ro"


def test_settings_use_approved_low_cost_model_chain() -> None:
    settings = Settings(_env_file=None)

    assert settings.llm_model == "deepseek/deepseek-v4-flash"
    assert settings.topic_llm_model == "deepseek/deepseek-v4-flash"
    assert settings.script_llm_model == "deepseek/deepseek-v4-pro"
    assert settings.direction_llm_model == "deepseek/deepseek-v4-flash"
    assert settings.llm_fallback_model == "qwen/qwen3.5-flash-02-23"


def test_checkpoint_persists_exception_type_when_message_is_empty(tmp_path: Path) -> None:
    checkpoint = _CheckpointStore(tmp_path)

    checkpoint.fail("topic", TimeoutError())

    state = json.loads((tmp_path / "_pipeline" / "state.json").read_text(encoding="utf-8"))
    assert state["error"] == "TimeoutError: no details provided"


def test_production_pipeline_uses_vision_only_for_search_image_validation(monkeypatch) -> None:
    provider = object()
    monkeypatch.setattr(reference_factory, "get_topic_llm_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_script_llm_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_direction_llm_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_search_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_tts_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_image_provider", lambda: provider)
    monkeypatch.setattr(reference_factory, "get_topic_history_service", lambda: provider)

    monkeypatch.setattr(
        reference_factory,
        "get_vision_llm_provider",
        lambda: provider,
        raising=False,
    )

    service = reference_factory.build_reference_generation_service(Settings(_env_file=None))

    assert isinstance(service.image_service.validator, ReferenceImageValidator)
    assert service.image_service.validator.llm is provider
    assert service.image_service.max_candidates == 3
    assert service.image_validator is None


def test_beat_tts_offsets_words_and_inserts_exact_pauses(tmp_path: Path) -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def synthesize(self, text, voice_id, language, output_path, settings, **kwargs):
            self.calls.append({"text": text, "settings": settings, **kwargs})
            output_path.write_bytes(b"audio")
            words = text.rstrip(".").split()
            return TTSResult(
                path=output_path,
                duration_seconds=float(len(words)),
                provider="fake",
                model="fake",
                character_count=len(text),
                estimated_cost_usd=0.0,
                timed_words=[
                    ProviderTimedWord(word=word, start=float(i), end=float(i + 1))
                    for i, word in enumerate(words)
                ],
            )

    class FakeAudioService:
        def __init__(self) -> None:
            self.segments = []

        def concatenate_with_silence(self, segments, output_path):
            self.segments = list(segments)
            output_path.write_bytes(b"joined")
            return output_path

        def get_duration(self, audio_path):
            return 14.2

    provider = FakeProvider()
    audio_service = FakeAudioService()
    service = BeatTTSService(provider, audio_service)
    script = ReferenceScriptPackage(
        title="A vs B",
        left_item="A",
        right_item="B",
        hook="Hook",
        beats=[
            NarrationBeat(id="b0", text="unu doi.", pause_after_ms=300),
            NarrationBeat(id="b1", text="trei patru.", pause_after_ms=0),
        ],
        closing=ClosingBeat(
            id="closing",
            text="Vă pupă Pufăilă!",
            pause_after_ms=500,
        ),
        caption="Caption",
    )

    audio_path, transcript = asyncio.run(
        service.synthesize(
            script,
            voice_id="voice",
            language="ro",
            output_dir=tmp_path,
            settings=TTSSettings(speed=1.05),
        )
    )

    assert audio_path.read_bytes() == b"joined"
    assert [pause for _, pause in audio_service.segments] == [300, 0, 500]
    assert transcript.words[2].word == "trei"
    assert transcript.words[2].start == pytest.approx(2.3)
    assert transcript.beats[0].pause_end == pytest.approx(2.3)
    assert transcript.duration_seconds == pytest.approx(14.2)
    assert provider.calls[1]["previous_text"] == "unu doi."
    assert [call["settings"].speed for call in provider.calls] == [1.05, 1.05, 0.88]
    assert provider.calls[-1]["text"] == "Vă pupă Pufăilă!"


def test_elevenlabs_request_carries_context_and_seed() -> None:
    provider = ElevenLabsProvider(api_key="test")

    body = provider._build_request_body(
        text="Al doilea segment.",
        settings=TTSSettings(),
        previous_text="Primul segment.",
        seed=42,
    )

    assert body["previous_text"] == "Primul segment."
    assert body["seed"] == 42
    assert body["text"] == "Al doilea segment."


def test_audio_service_concatenates_segments_with_generated_silence(tmp_path: Path) -> None:
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    output = tmp_path / "narration.wav"
    service = AudioService()
    service.ffmpeg = MagicMock()
    service.ffmpeg.ffmpeg_bin = "ffmpeg"

    service.concatenate_with_silence([(first, 300), (second, 0)], output)

    command = service.ffmpeg._run.call_args.args[0]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "aevalsrc=0:d=0.300" in filter_graph
    assert "concat=n=3:v=0:a=1" in filter_graph
    assert command[-1] == str(output)


def test_audio_service_delays_sfx_to_compiled_cue_time(tmp_path: Path) -> None:
    narration = tmp_path / "narration.wav"
    whoosh = tmp_path / "whoosh.wav"
    narration.write_bytes(b"narration")
    whoosh.write_bytes(b"whoosh")
    output = tmp_path / "mixed.m4a"
    service = AudioService()
    service.ffmpeg = MagicMock()
    service.ffmpeg.ffmpeg_bin = "ffmpeg"
    service.ffmpeg.get_duration.return_value = 5.0

    service.mix_timed_sfx(
        narration_path=narration,
        cues=[SoundEffectCue(start=1.2, kind=SfxKind.WHOOSH, volume_db=-14.0)],
        library={SfxKind.WHOOSH: whoosh},
        output_path=output,
        total_duration_seconds=6.8,
    )

    command = service.ffmpeg._run.call_args.args[0]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "adelay=1200|1200" in filter_graph
    assert "volume=-14.0dB" in filter_graph
    assert "apad,atrim=duration=6.800" in filter_graph
    assert "loudnorm=I=-16" in filter_graph
    assert "alimiter=limit=0.841395" in filter_graph


def test_timeline_compiler_starts_cta_sound_with_the_closing_signoff() -> None:
    transcript = TimedTranscript(
        words=[TimedWord(word="Pa!", start=8.0, end=8.4)],
        beats=[TimedBeat(id="closing", start=8.0, end=8.4, pause_end=8.9)],
        duration_seconds=8.9,
    )

    timeline = TimelineCompiler().compile(DirectionPlan(), transcript)

    assert timeline.sound_cues[-1].kind is SfxKind.CTA_STING
    assert timeline.sound_cues[-1].start == pytest.approx(8.0)


def test_sound_effect_cues_are_four_decibels_louder() -> None:
    cue = SoundEffectCue(start=0.0, kind=SfxKind.POSE_POP)

    assert cue.volume_db == -14.0


def test_timeline_compiler_shows_full_phrase_and_highlights_active_word() -> None:
    transcript = TimedTranscript(
        words=[
            TimedWord(word="Știi", start=0.0, end=0.2),
            TimedWord(word="care", start=0.2, end=0.4),
            TimedWord(word="este", start=0.4, end=0.6),
            TimedWord(word="diferența?", start=0.6, end=0.9),
            TimedWord(word="Cafeaua", start=1.3, end=1.7),
        ],
        beats=[
            TimedBeat(id="hook", start=0.0, end=0.9, pause_end=1.2),
            TimedBeat(id="fact", start=1.3, end=1.7, pause_end=1.7),
        ],
        duration_seconds=1.7,
    )

    captions = TimelineCompiler().compile_captions(transcript)

    phrase = ["Știi", "care", "este", "diferența?"]
    assert [cue.words for cue in captions] == [
        phrase,
        phrase,
        phrase,
        phrase,
        ["Cafeaua"],
    ]
    assert [cue.active_word_index for cue in captions] == [0, 1, 2, 3, 0]
    # Each word's highlight window matches its spoken timing.
    assert captions[0].start == 0.0 and captions[0].end == 0.2
    assert captions[1].start == 0.2 and captions[1].end == 0.4
    assert captions[3].start == 0.6 and captions[3].end == 1.3


def test_timeline_compiler_resolves_cues_and_debounces_sfx() -> None:
    transcript = TimedTranscript(
        words=[
            TimedWord(word="Cafeaua", start=0.0, end=0.4),
            TimedWord(word="este", start=0.4, end=0.6),
            TimedWord(word="rapidă.", start=0.6, end=1.0),
        ],
        beats=[TimedBeat(id="b0", start=0.0, end=1.0, pause_end=1.0)],
        duration_seconds=1.0,
    )
    plan = DirectionPlan(cues=[
        DirectionCue(
            beat_id="b0", word_index=0, mascot_pose=MascotPose.POINT_LEFT,
            mascot_anchor=MascotAnchor.LEFT, product_focus=Focus.LEFT,
            sfx_kind=SfxKind.WHOOSH,
        ),
        DirectionCue(
            beat_id="b0", word_index=1, mascot_pose=MascotPose.POINT_RIGHT,
            mascot_anchor=MascotAnchor.RIGHT, product_focus=Focus.RIGHT,
            sfx_kind=SfxKind.WHOOSH,
        ),
        DirectionCue(
            beat_id="b0", word_index=2, mascot_pose=MascotPose.POINT_RIGHT,
            mascot_anchor=MascotAnchor.RIGHT, product_focus=Focus.RIGHT,
            sfx_kind=SfxKind.POSE_POP,
        ),
    ])

    compiled = TimelineCompiler().compile_direction(plan, transcript)

    assert isinstance(compiled, CompiledTimeline)
    assert [cue.start for cue in compiled.direction_cues] == [0.0, 0.4, 0.6]
    assert [cue.kind for cue in compiled.sound_cues] == [
        SfxKind.WHOOSH,
        SfxKind.POSE_POP,
        SfxKind.CTA_STING,
    ]
    assert compiled.sound_cues[-1].start == pytest.approx(1.0)


def test_timeline_compiler_rejects_director_word_anchor_outside_beat() -> None:
    transcript = TimedTranscript(
        words=[TimedWord(word="Unu", start=0.0, end=0.3)],
        beats=[TimedBeat(id="b0", start=0.0, end=0.3, pause_end=0.3)],
        duration_seconds=0.3,
    )
    plan = DirectionPlan(cues=[DirectionCue(beat_id="b0", word_index=1)])

    with pytest.raises(ValueError, match="word_index"):
        TimelineCompiler().compile_direction(plan, transcript)


def test_reference_quality_requires_exact_caption_words_and_white_poster(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "narration.m4a"
    video = tmp_path / "video.mp4"
    poster = tmp_path / "poster.jpg"
    contact = tmp_path / "contact.jpg"
    timeline = tmp_path / "timeline.json"
    for path in (left, right, audio, video, contact, timeline):
        path.write_bytes(b"asset")
    Image.new("RGB", (1080, 1920), "white").save(poster)
    transcript = TimedTranscript(
        words=[
            TimedWord(word="Cafeaua", start=0.0, end=0.4),
            TimedWord(word="ajută.", start=0.4, end=0.8),
        ],
        beats=[TimedBeat(id="b0", start=0.0, end=0.8, pause_end=25.0)],
        duration_seconds=25.0,
    )
    spec = CompiledVideoSpec(
        left_label="Cafea",
        right_label="Ceai",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=transcript,
        direction_cues=[AbsoluteDirectionCue(
            start=0.0,
            mascot_pose=MascotPose.POINT_LEFT,
            mascot_anchor=MascotAnchor.CENTER,
            product_focus=Focus.LEFT,
        )],
        captions=[
            CaptionCue(words=["Cafeaua"], active_word_index=0, start=0.0, end=0.4),
            CaptionCue(words=["Cafeaua", "ajută."], active_word_index=1, start=0.4, end=25.0),
        ],
    )
    result = RenderResult(
        video_path=video,
        poster_path=poster,
        contact_sheet_path=contact,
        timeline_path=timeline,
        duration_seconds=25.0,
        frame_count=750,
        resolution=(1080, 1920),
        scene_count=0,
    )

    class FakeMediaQuality:
        def validate_video(self, video_path: Path) -> list[str]:
            return []

        def validate_content(self, render_result: RenderResult, expected_scene_count: int) -> list[str]:
            return []

    quality = ReferenceQualityService(FakeMediaQuality())

    assert quality.validate(spec, result) == []
    moving_spec = spec.model_copy(update={
        "direction_cues": [spec.direction_cues[0].model_copy(update={
            "mascot_anchor": MascotAnchor.LEFT,
        })],
    })
    assert quality.validate(moving_spec, result) == [
        "Reference mascot direction changes its calibrated anchor"
    ]
    short_result = result.model_copy(update={"duration_seconds": 24.0})
    assert quality.validate(spec, short_result) == [
        "Final duration 24.000s does not match compiled duration 25.000s"
    ]
    spec.captions[1].words[1] = "greșit"
    assert quality.validate(spec, result) == ["Caption active-word sequence does not match narration"]
