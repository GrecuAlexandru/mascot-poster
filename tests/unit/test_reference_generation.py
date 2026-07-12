from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from app.domain.enums import Focus, MascotAnchor, MascotPose
from app.domain.models import (
    ClosingBeat,
    DirectionCue,
    DirectionPlan,
    NarrationBeat,
    PairedImageBrief,
    ProductImageBrief,
    ReferenceScriptPackage,
    ResearchPackage,
    GenerationRequest,
    RenderResult,
    TimedBeat,
    TimedTranscript,
    TimedWord,
    TopicCandidate,
    TopicSpec,
)
from app.services.reference_direction_service import ReferenceDirectionService
from app.services.reference_direction_validator import ReferenceDirectionValidator
from app.services.reference_adapters import (
    ReferenceResearcher,
    ReferenceResearchSummary,
    ReferenceTopicGenerator,
)
from app.services.reference_script_service import ReferenceScriptService
from app.services.reference_image_validator import ImageValidationResult
from app.providers.search.base import SearchResponse, SearchResult
from app.services.timeline_compiler import TimelineCompiler
from app.services.video_generation_service import VideoGenerationService


def test_reference_duration_gate_accepts_60_seconds() -> None:
    assert VideoGenerationService._duration_is_acceptable(60.0)


def test_reference_topic_generator_requires_concrete_physical_items() -> None:
    class LLM:
        def __init__(self) -> None:
            self.user_prompt = ""

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.user_prompt = user
            return TopicCandidate(
                title="Cafea vs Ceai",
                left="Cafea",
                right="Ceai",
                angle="Aromă și cofeină",
            )

    llm = LLM()

    result = asyncio.run(ReferenceTopicGenerator(llm).generate(GenerationRequest()))

    assert result.comparison_left == "Cafea"
    assert "concrete physical" in llm.user_prompt
    assert "Do not generate abstract concepts" in llm.user_prompt
    assert "readable paragraphs, URLs, warning labels" in llm.user_prompt
    assert "product or concept" not in llm.user_prompt


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
                closing=ClosingBeat(
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

    assert result.beats[0].id == "hook"
    assert result.beats[1].id == "b0"
    assert result.beats[-1].text.startswith("Pe scurt,")
    assert result.beats[-1].pause_after_ms == 1000
    assert llm.calls[0][2] is ReferenceScriptPackage
    assert llm.calls[0][3]["schema_name"] == "reference_script"
    assert "același număr de caracteristici" in llm.calls[0][1]
    assert "Pe scurt," in llm.calls[0][1]
    assert "română" in llm.calls[0][1].casefold()
    prompt = llm.calls[0][1]
    assert "modern" in prompt.casefold()
    assert "ironie" in prompt.casefold()
    assert "4-12 cuvinte după prefix" in prompt
    assert "zahăr vanilat" in prompt
    assert "remake-ul" in prompt
    assert "nu reutiliza faptele" in prompt.casefold()


def test_reference_script_service_enforces_intro_and_signed_outro() -> None:
    class FakeLLM:
        async def complete_structured(self, system, user, model_type, **kwargs):
            return ReferenceScriptPackage(
                title="Coffee vs Tea",
                left_item="Coffee",
                right_item="Tea",
                hook="Alternative hook.",
                beats=[NarrationBeat(id="b0", text="Coffee has an intense flavor.")],
                closing=ClosingBeat(
                    id="closing",
                    text="Choose the drink that suits the moment. Hugs from Pufăilă!",
                    pause_after_ms=750,
                ),
                caption="Coffee or tea?",
            )

    result = asyncio.run(ReferenceScriptService(FakeLLM()).generate(
        TopicSpec(title="Coffee vs Tea", comparison_left="Coffee", comparison_right="Tea"),
        ResearchPackage(topic="Coffee vs Tea", left_item="Coffee", right_item="Tea"),
        target_duration_seconds=25,
        language="en",
    ))

    assert result.beats[0].text == "We have Coffee and we have Tea. But what's the difference?"
    assert result.beats[-1].text == "In short, Choose the drink that suits the moment."
    assert result.beats[-1].pause_after_ms == 1000
    assert result.closing.text == "Hugs from Pufăilă!"
    assert result.closing.pause_after_ms == 500


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
        closing=ClosingBeat(
            id="closing",
            text="Așadar, alege opțiunea care se potrivește mai bine nevoilor tale.",
            pause_after_ms=500,
        ),
        caption="Cafea sau ceai?",
    )

    result = asyncio.run(ReferenceDirectionService(FakeLLM()).generate(script, language="ro"))

    assert result.cues[0].beat_id == "b0"
    assert result.cues[0].word_index == 1


def test_direction_validator_choreographs_the_required_hook() -> None:
    script = ReferenceScriptPackage(
        title="Coffee vs Tea",
        left_item="Coffee",
        right_item="Tea",
        hook="We have Coffee and we have Tea. But what's the difference?",
        beats=[
            NarrationBeat(
                id="hook",
                text="We have Coffee and we have Tea. But what's the difference?",
            ),
            NarrationBeat(id="b0", text="Coffee is intense."),
        ],
        closing=ClosingBeat(id="closing", text="Hugs from Pufăilă!", pause_after_ms=500),
        caption="Coffee or tea?",
    )

    aligned = ReferenceDirectionValidator().align_with_script(
        DirectionPlan(cues=[DirectionCue(
            beat_id="b0",
            word_index=0,
            mascot_pose=MascotPose.POINT_UP_LEFT,
            product_focus=Focus.LEFT,
        )]),
        script,
    )

    hook_cues = [cue for cue in aligned.cues if cue.beat_id == "hook"]
    assert [(cue.word_index, cue.mascot_pose, cue.product_focus) for cue in hook_cues] == [
        (2, MascotPose.POINT_UP_LEFT, Focus.LEFT),
        (6, MascotPose.POINT_UP_RIGHT, Focus.RIGHT),
        (7, MascotPose.INTRO_HANDS_UP, Focus.BOTH),
    ]

    fallback_hook_cues = [
        cue
        for cue in ReferenceDirectionValidator().fallback(script).cues
        if cue.beat_id == "hook"
    ]
    assert [(cue.word_index, cue.mascot_pose, cue.product_focus) for cue in fallback_hook_cues] == [
        (2, MascotPose.POINT_UP_LEFT, Focus.LEFT),
        (6, MascotPose.POINT_UP_RIGHT, Focus.RIGHT),
        (7, MascotPose.INTRO_HANDS_UP, Focus.BOTH),
    ]


def test_direction_validator_balances_two_sided_beats_without_diacritics() -> None:
    script = ReferenceScriptPackage(
        title="Cacao praf vs Ciocolată topită",
        left_item="Cacao praf",
        right_item="Ciocolată topită",
        hook="Avem Cacao praf și avem Ciocolată topită. Dar care e diferența?",
        beats=[
            NarrationBeat(
                id="hook",
                text="Avem Cacao praf și avem Ciocolată topită. Dar care e diferența?",
            ),
            NarrationBeat(
                id="body",
                text="Cacao praf e amar. Ciocolata topita e dulce.",
            ),
        ],
        closing=ClosingBeat(id="closing", text="Vă pupă Pufăilă!", pause_after_ms=500),
        caption="Cacao sau ciocolată?",
    )
    plan = DirectionPlan(cues=[
        DirectionCue(
            beat_id="body",
            word_index=0,
            mascot_pose=MascotPose.POINT_UP_LEFT,
            product_focus=Focus.LEFT,
        ),
    ])

    aligned = ReferenceDirectionValidator().align_with_script(plan, script)
    body_cues = [cue for cue in aligned.cues if cue.beat_id == "body"]

    assert [cue.word_index for cue in body_cues] == [0, 4]
    assert [cue.mascot_pose for cue in body_cues] == [
        MascotPose.POINT_UP_LEFT,
        MascotPose.POINT_UP_RIGHT,
    ]
    assert [cue.product_focus for cue in body_cues] == [Focus.LEFT, Focus.RIGHT]


def test_direction_fallback_balances_every_two_sided_body_beat() -> None:
    script = ReferenceScriptPackage(
        title="Cacao praf vs Ciocolată topită",
        left_item="Cacao praf",
        right_item="Ciocolată topită",
        hook="Avem Cacao praf și avem Ciocolată topită. Dar care e diferența?",
        beats=[
            NarrationBeat(
                id="hook",
                text="Avem Cacao praf și avem Ciocolată topită. Dar care e diferența?",
            ),
            NarrationBeat(
                id="body_1",
                text="Cacao praf e intens. Ciocolata topita e dulce.",
            ),
            NarrationBeat(
                id="body_2",
                text="Cacao praf e ingredient. Ciocolata topita e desert.",
            ),
        ],
        closing=ClosingBeat(id="closing", text="Vă pupă Pufăilă!", pause_after_ms=500),
        caption="Cacao sau ciocolată?",
    )

    fallback = ReferenceDirectionValidator().fallback(script)

    for beat_id in ("body_1", "body_2"):
        cues = [cue for cue in fallback.cues if cue.beat_id == beat_id]
        assert [cue.product_focus for cue in cues] == [Focus.LEFT, Focus.RIGHT]


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
        closing=ClosingBeat(
            id="closing",
            text="Așadar, alege băutura potrivită pentru ritmul și nevoile tale.",
            pause_after_ms=750,
        ),
        caption="Cafea sau ceai?",
    )

    result = asyncio.run(ReferenceDirectionService(AllNeutralLLM()).generate(script, "ro"))

    assert all(cue.mascot_anchor == MascotAnchor.CENTER for cue in result.cues)
    assert any(cue.mascot_pose != MascotPose.NEUTRAL for cue in result.cues)
    assert any(cue.mascot_pose == MascotPose.POINT_UP_LEFT for cue in result.cues)
    assert any(cue.mascot_pose == MascotPose.POINT_UP_RIGHT for cue in result.cues)
    assert max(
        sum(candidate.beat_id == beat.id for candidate in result.cues)
        for beat in script.all_beats
    ) <= 2


def test_direction_alignment_mirrors_inverted_pointing() -> None:
    from app.domain.enums import SfxKind
    from app.services.reference_direction_validator import ReferenceDirectionValidator

    script = ReferenceScriptPackage(
        title="Cafea vs Ceai",
        left_item="Cafea",
        right_item="Ceai",
        hook="Comparația contează.",
        beats=[
            NarrationBeat(id="left", text="Cafeaua acționează rapid.", pause_after_ms=300),
            NarrationBeat(id="right", text="Ceaiul acționează mai blând.", pause_after_ms=300),
        ],
        closing=ClosingBeat(
            id="closing",
            text="Așadar, alege băutura potrivită pentru ritmul și nevoile tale.",
            pause_after_ms=750,
        ),
        caption="Cafea sau ceai?",
    )
    inverted = DirectionPlan(cues=[
        DirectionCue(
            beat_id="left",
            word_index=0,
            mascot_pose=MascotPose.POINT_RIGHT,
            mascot_anchor=MascotAnchor.CENTER,
            product_focus=Focus.RIGHT,
            sfx_kind=SfxKind.POSE_POP,
        ),
        DirectionCue(
            beat_id="right",
            word_index=0,
            mascot_pose=MascotPose.POINT_UP_LEFT,
            mascot_anchor=MascotAnchor.CENTER,
            product_focus=Focus.LEFT,
            sfx_kind=SfxKind.POSE_POP,
        ),
    ])

    aligned = ReferenceDirectionValidator().align_with_script(inverted, script)

    assert aligned.cues[0].mascot_pose == MascotPose.POINT_LEFT
    assert aligned.cues[0].product_focus == Focus.LEFT
    assert aligned.cues[1].mascot_pose == MascotPose.POINT_UP_RIGHT
    assert aligned.cues[1].product_focus == Focus.RIGHT


def test_direction_alignment_balances_inflected_two_sided_beats() -> None:
    from app.domain.enums import SfxKind
    from app.services.reference_direction_validator import ReferenceDirectionValidator

    script = ReferenceScriptPackage(
        title="Cafea vs Ceai",
        left_item="Cafea",
        right_item="Ceai",
        hook="Comparația contează.",
        beats=[
            NarrationBeat(
                id="both",
                text="Cafeaua și ceaiul au avantaje diferite.",
                pause_after_ms=300,
            ),
        ],
        closing=ClosingBeat(
            id="closing",
            text="Așadar, alege băutura potrivită pentru ritmul și nevoile tale.",
            pause_after_ms=750,
        ),
        caption="Cafea sau ceai?",
    )
    plan = DirectionPlan(cues=[
        DirectionCue(
            beat_id="both",
            word_index=0,
            mascot_pose=MascotPose.POINT_RIGHT,
            mascot_anchor=MascotAnchor.CENTER,
            product_focus=Focus.RIGHT,
            sfx_kind=SfxKind.POSE_POP,
        ),
    ])

    aligned = ReferenceDirectionValidator().align_with_script(plan, script)

    assert [cue.word_index for cue in aligned.cues] == [0, 2]
    assert [cue.mascot_pose for cue in aligned.cues] == [
        MascotPose.POINT_UP_LEFT,
        MascotPose.POINT_UP_RIGHT,
    ]
    assert [cue.product_focus for cue in aligned.cues] == [Focus.LEFT, Focus.RIGHT]


def test_pair_repair_regenerates_only_selected_side_once(tmp_path: Path) -> None:
    class Images:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def acquire(self, item, output_path, **kwargs):
            self.calls.append((item, kwargs))
            Image.new("RGBA", (400, 400), (255, 255, 255, 0)).save(output_path)
            return {"item": item, "path": str(output_path)}

    class Validator:
        async def validate_pair(self, left_path, right_path, brief):
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                pair_style_acceptable=False,
                composition_acceptable=False,
                warning_reasons=["Minor remaining lighting mismatch"],
                confidence=0.95,
            )

    brief = PairedImageBrief(
        shared_style="matching front cabin view on transparent background",
        left=ProductImageBrief(
            item="Manual car",
            exact_subject="complete manual-transmission car cockpit",
            distinguishing_attributes=["clutch pedal"],
        ),
        right=ProductImageBrief(
            item="Automatic car",
            exact_subject="complete automatic-transmission car cockpit",
            distinguishing_attributes=["no clutch pedal"],
        ),
    )
    images = Images()
    service = VideoGenerationService(
        output_base=tmp_path,
        topic_generator=None,
        researcher=None,
        script_writer=None,
        verifier=None,
        director=None,
        beat_tts=None,
        image_service=images,
        audio_service=None,
        sfx_service=None,
        timeline_compiler=None,
        renderer=None,
        quality_service=None,
        image_validator=Validator(),
    )
    topic = TopicSpec(
        title="Manual vs automatic", comparison_left="Manual car", comparison_right="Automatic car"
    )

    initial_validation = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=True,
        contains_prohibited_content=False,
        background_acceptable=True,
        repair_side="right",
        repair_instructions=["Remove all text", "Match the left image scale"],
        fatal_reasons=["Right image contains unrelated text"],
        confidence=0.95,
    )
    left_provenance = {"item": "Manual car", "selected": True}
    right_provenance = {"item": "Automatic car", "selected": False}

    left, right, validation, metadata = asyncio.run(service._repair_pair_once(
        topic,
        tmp_path / "left.png",
        tmp_path / "right.png",
        brief,
        initial_validation,
        left_provenance,
        right_provenance,
    ))

    assert [item for item, _ in images.calls] == ["Automatic car"]
    call = images.calls[0][1]
    assert call["force_generated"] is True
    assert call["generated_attempt_limit"] == 1
    assert call["input_references"] == [tmp_path / "left.png"]
    assert call["repair_instructions"] == ["Remove all text", "Match the left image scale"]
    assert left is left_provenance
    assert right["item"] == "Automatic car"
    assert not validation.has_fatal_issues
    assert metadata["repair_side"] == "right"
    assert metadata["generation_calls"] == 1


def test_pair_repair_both_sides_uses_one_paired_generation_call(tmp_path: Path) -> None:
    class Images:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_pair_repair(self, **kwargs):
            self.calls += 1
            return {"side": "left"}, {"side": "right"}

    class Validator:
        async def validate_pair(self, left_path, right_path, brief):
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.95,
            )

    images = Images()
    service = VideoGenerationService(
        output_base=tmp_path,
        topic_generator=None,
        researcher=None,
        script_writer=None,
        verifier=None,
        director=None,
        beat_tts=None,
        image_service=images,
        audio_service=None,
        sfx_service=None,
        timeline_compiler=None,
        renderer=None,
        quality_service=None,
        image_validator=Validator(),
    )
    topic = TopicSpec(title="Steak vs chicken", comparison_left="Steak", comparison_right="Chicken")
    brief = PairedImageBrief(
        shared_style="matching overhead studio product photographs",
        left=ProductImageBrief(
            item="Steak",
            exact_subject="single beef steak",
            distinguishing_attributes=["seared surface"],
        ),
        right=ProductImageBrief(
            item="Chicken",
            exact_subject="single chicken breast",
            distinguishing_attributes=["lightly seared surface"],
        ),
    )
    initial = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=False,
        contains_prohibited_content=False,
        background_acceptable=True,
        repair_side="both",
        repair_instructions=["Match both swatch sizes"],
        warning_reasons=["Both sides need composition repair"],
        confidence=0.95,
    )

    _, _, validation, metadata = asyncio.run(service._repair_pair_once(
        topic,
        tmp_path / "left.png",
        tmp_path / "right.png",
        brief,
        initial,
        {"old": "left"},
        {"old": "right"},
    ))

    assert images.calls == 1
    assert not validation.has_fatal_issues
    assert metadata["generation_calls"] == 1


def test_final_pair_policy_blocks_fatal_but_not_cosmetic_results() -> None:
    cosmetic = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=False,
        contains_prohibited_content=False,
        background_acceptable=True,
        pair_style_acceptable=False,
        composition_acceptable=False,
        warning_reasons=["Right image is slightly lower"],
        confidence=0.95,
    )
    fatal = cosmetic.model_copy(update={
        "contains_logo_or_prominent_text": True,
        "fatal_reasons": ["Right image still contains text"],
    })

    assert VideoGenerationService._pair_failure_reasons(cosmetic) == []
    assert VideoGenerationService._pair_failure_reasons(fatal) == [
        "Right image still contains text"
    ]


def test_reference_researcher_requests_a_bounded_summary_not_full_sources() -> None:
    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(
                query=query,
                results=[SearchResult(
                    title="Reading study",
                    url="https://example.com/reading",
                    snippet="Evidence about reading formats",
                )],
            )

    class LLM:
        def __init__(self) -> None:
            self.calls = []

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.calls.append((system, user, model_type, kwargs))
            return ReferenceResearchSummary(
                facts=[{
                    "text": "A source reports that both reading formats are used.",
                    "source_ids": ["src_0"],
                    "confidence": 0.8,
                    "applies_to": "both",
                }],
            )

    llm = LLM()
    researcher = ReferenceResearcher(Search(), llm)
    topic = TopicSpec(
        title="Physical books vs ebooks",
        comparison_left="Physical books",
        comparison_right="Ebooks",
    )

    result = asyncio.run(researcher.generate(topic))

    assert llm.calls[0][2] is ReferenceResearchSummary
    assert llm.calls[0][3]["max_tokens"] == 1200
    assert "at most 6 facts" in llm.calls[0][1]
    assert result.sources[0].id == "src_0"
    assert len(result.facts) == 1


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
                closing=ClosingBeat(
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
    assert tts.settings.speed == pytest.approx(1.05)
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
                closing=ClosingBeat(
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
        def __init__(self) -> None:
            self.mixed_durations: list[float | None] = []

        def mix_timed_sfx(
            self,
            narration_path,
            cues,
            library,
            output_path,
            total_duration_seconds=None,
        ):
            self.mixed_durations.append(total_duration_seconds)
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
    audio = Audio()
    service = VideoGenerationService(
        output_base=tmp_path / "jobs",
        topic_generator=TopicGenerator(),
        researcher=Researcher(),
        script_writer=script_writer,
        verifier=Verifier(),
        director=director,
        beat_tts=tts,
        image_service=Images(),
        audio_service=audio,
        sfx_service=Sfx(),
        timeline_compiler=TimelineCompiler(),
        renderer=renderer,
        quality_service=Quality(),
    )

    result = asyncio.run(service.generate(GenerationRequest(target_duration_seconds=25)))

    assert result.render_result.duration_seconds == 24.0
    assert tts.calls == 2
    assert director.hooks == ["short"]
    assert renderer.durations == [24.0]
    assert audio.mixed_durations == [24.0]
    assert "Measured narration duration was 61.0s" in script_writer.repair_notes[1][0]
