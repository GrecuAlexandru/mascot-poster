from __future__ import annotations

from app.config import (
    Settings,
    get_direction_llm_provider,
    get_description_history_service,
    get_image_provider,
    get_llm_provider,
    get_proofread_llm_provider,
    get_script_llm_provider,
    get_search_provider,
    get_topic_history_service,
    get_topic_llm_provider,
    get_tts_provider,
    get_vision_llm_provider,
)
from app.rendering.ffmpeg import FFmpegRunner
from app.rendering.reference_renderer import ReferenceRenderer
from app.services.audio_service import AudioService
from app.services.beat_tts_service import BeatTTSService
from app.services.fact_check_service import FactCheckService
from app.services.reference_adapters import (
    ReferenceResearcher,
    ReferenceTopicGenerator,
    ReferenceVerifier,
)
from app.services.reference_direction_service import ReferenceDirectionService
from app.services.reference_image_service import ReferenceImageService
from app.services.reference_image_brief_service import ReferenceImageBriefService
from app.services.reference_image_validator import ReferenceImageValidator
from app.services.reference_proofreader import ReferenceProofreader
from app.services.reference_quality_service import ReferenceQualityService
from app.services.reference_render_service import ReferenceRenderService
from app.services.reference_script_service import ReferenceScriptService
from app.services.sfx_service import SfxLibraryService
from app.services.social_description_service import SocialDescriptionService
from app.services.timeline_compiler import TimelineCompiler
from app.services.video_generation_service import VideoGenerationService
from app.services.quality_service import QualityService


def build_reference_generation_service(settings: Settings) -> VideoGenerationService:
    topic_llm = get_topic_llm_provider()
    research_llm = get_llm_provider()
    script_llm = get_script_llm_provider()
    direction_llm = get_direction_llm_provider()
    search = get_search_provider()
    tts = get_tts_provider()
    image_provider = get_image_provider()
    vision_llm = get_vision_llm_provider()
    if (
        topic_llm is None
        or research_llm is None
        or script_llm is None
        or direction_llm is None
    ):
        raise RuntimeError("Text model configuration is incomplete")
    if search is None:
        raise RuntimeError("Search provider configuration is incomplete")
    if tts is None:
        raise RuntimeError("ElevenLabs configuration is incomplete")
    if image_provider is None:
        raise RuntimeError("OpenRouter image configuration is incomplete")
    if vision_llm is None:
        raise RuntimeError("Search-image validation configuration is incomplete")

    proofread_llm = get_proofread_llm_provider()
    proofreader = ReferenceProofreader(proofread_llm) if proofread_llm is not None else None

    audio_service = AudioService(
        settings.ffmpeg_bin,
        settings.ffprobe_bin,
        settings.audio_sample_rate,
    )
    renderer = ReferenceRenderer(
        templates_dir=settings.templates_dir,
        mascots_dir=settings.mascots_dir,
        font_path=settings.resolve_font(),
    )
    render_service = ReferenceRenderService(
        renderer,
        FFmpegRunner(settings.ffmpeg_bin, settings.ffprobe_bin),
    )
    return VideoGenerationService(
        output_base=settings.project_root / "output" / "jobs",
        topic_generator=ReferenceTopicGenerator(
            topic_llm, get_topic_history_service(), proofreader
        ),
        researcher=ReferenceResearcher(search, research_llm),
        script_writer=ReferenceScriptService(script_llm, proofreader),
        verifier=ReferenceVerifier(FactCheckService(research_llm)),
        director=ReferenceDirectionService(direction_llm),
        beat_tts=BeatTTSService(tts, audio_service),
        image_service=ReferenceImageService(
            search_provider=search,
            generated_provider=image_provider,
            validator=ReferenceImageValidator(vision_llm),
            max_candidates=3,
        ),
        audio_service=audio_service,
        sfx_service=SfxLibraryService(settings.audio_sample_rate),
        timeline_compiler=TimelineCompiler(),
        renderer=render_service,
        quality_service=ReferenceQualityService(
            QualityService(settings.ffmpeg_bin, settings.ffprobe_bin),
        ),
        image_brief_service=ReferenceImageBriefService(direction_llm),
        image_validator=None,
        social_description_writer=SocialDescriptionService(script_llm),
        description_history=get_description_history_service(),
    )
