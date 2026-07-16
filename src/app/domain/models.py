from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import (
    Focus,
    ImageMotion,
    MascotAnchor,
    MascotPose,
    SfxKind,
    Transition,
)


class TopicCandidate(BaseModel):
    title: str
    left: str
    right: str
    angle: str
    why_it_might_work: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"


class TopicSpec(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel_id: Optional[UUID] = None
    title: str
    comparison_left: str
    comparison_right: str
    angle: str = ""
    status: str = "IDEA"
    priority: int = 0
    source_hint: Optional[str] = None


class GenerationRequest(BaseModel):
    topic_override: Optional[str] = None
    language: Literal["ro", "en"] = "ro"
    target_duration_seconds: int = Field(default=25, ge=20, le=60)
    voice_id: Optional[str] = None


class ProductImageBrief(BaseModel):
    item: str
    exact_subject: str = Field(min_length=3)
    search_query_en: str = Field(
        default="",
        description=(
            "Concise English image-search phrase of 3-8 words naming the exact "
            "physical object, e.g. 'single espresso shot white demitasse cup'"
        ),
    )
    distinguishing_attributes: list[str] = Field(min_length=1)
    required_elements: list[str] = Field(default_factory=list)
    prohibited_elements: list[str] = Field(default_factory=list)
    confusing_alternatives: list[str] = Field(default_factory=list)
    allow_packaging: bool = False
    allow_text: bool = False
    requires_real_reference: bool = False
    image_text_language: Literal["romanian", "english", "none"] = "none"


class PairedImageBrief(BaseModel):
    shared_style: str = Field(min_length=10)
    left: ProductImageBrief
    right: ProductImageBrief


class NarrationBeat(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    pause_after_ms: Literal[0, 150, 300, 500, 750, 1000] = 0
    claim_ids: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value.strip()


class Claim(BaseModel):
    id: str
    text: str
    supporting_source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    risk_level: Literal["low", "medium", "high"] = "low"


class ClosingBeat(NarrationBeat):
    id: Literal["closing"] = "closing"
    pause_after_ms: Literal[500, 750] = 750
    text: str = Field(
        min_length=1,
        description=(
            "Concluding verdict of 6-28 words, one or two complete sentences "
            "ending with '.', '!' or '?'"
        ),
    )


class ReferenceScriptPackage(BaseModel):
    title: str
    left_item: str
    right_item: str
    hook: str
    beats: list[NarrationBeat] = Field(min_length=1)
    closing: ClosingBeat
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_closing(self) -> "ReferenceScriptPackage":
        words = self.closing.text.split()
        if not 2 <= len(words) <= 28:
            raise ValueError("closing must contain 2-28 words")
        if not self.closing.text.endswith((".", "!", "?")):
            raise ValueError("closing must be a complete sentence")
        return self

    @property
    def all_beats(self) -> list[NarrationBeat]:
        return [*self.beats, self.closing]

    @property
    def narration_text(self) -> str:
        return " ".join(beat.text for beat in self.all_beats)

    @property
    def word_count(self) -> int:
        return len(self.narration_text.split())


class SocialDescription(BaseModel):
    description: str
    hashtags: list[str] = Field(default_factory=list)
    fallback_used: bool = False

    @model_validator(mode="after")
    def validate_description(self) -> "SocialDescription":
        self.description = self.description.strip()
        if not self.description:
            raise ValueError("description must not be blank")
        if not self.fallback_used:
            word_count = len(self.description.split())
            if not 25 <= word_count <= 45:
                raise ValueError("description must contain 25-45 words")
            question_index = self.description.rfind("?")
            trailing_decoration = self.description[question_index + 1 :]
            if question_index < 0 or any(
                character.isalnum() for character in trailing_decoration
            ):
                raise ValueError("description must end with a question")
        return self

    @property
    def normalized_hashtags(self) -> list[str]:
        normalized: list[str] = []
        for raw in ["pufaila", "stiaica", *self.hashtags]:
            folded = unicodedata.normalize("NFKD", str(raw).strip().lstrip("#"))
            token = "".join(
                character.lower()
                for character in folded
                if character.isascii() and character.isalnum()
            )
            if token and token not in normalized:
                normalized.append(token)
            if len(normalized) == 5:
                break
        return normalized

    @property
    def publishable_text(self) -> str:
        hashtags = " ".join(f"#{token}" for token in self.normalized_hashtags)
        return f"{self.description}\n\n{hashtags}" if hashtags else self.description


class DirectionCue(BaseModel):
    beat_id: str = Field(min_length=1)
    word_index: int = Field(ge=0)
    mascot_pose: MascotPose = MascotPose.NEUTRAL
    mascot_anchor: MascotAnchor = MascotAnchor.CENTER
    product_focus: Focus = Focus.NEUTRAL
    sfx_kind: SfxKind = SfxKind.NONE


class DirectionPlan(BaseModel):
    cues: list[DirectionCue] = Field(default_factory=list)


class ScenePlan(BaseModel):
    index: int
    narration: str
    duration_hint_seconds: float = Field(default=3.0, gt=0.0, le=10.0)
    mascot_pose: MascotPose = MascotPose.NEUTRAL
    focus: Focus = Focus.NEUTRAL
    on_screen_phrases: list[str] = Field(default_factory=list)
    transition: Transition = Transition.QUICK_FADE
    image_motion: ImageMotion = ImageMotion.SLOW_ZOOM_IN
    emphasis: list[str] = Field(default_factory=list)


class ScriptPackage(BaseModel):
    title: str
    hook: str
    narration_text: str
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    scenes: list[ScenePlan] = Field(default_factory=list)
    estimated_duration_seconds: float = 60.0

    @field_validator("narration_text")
    @classmethod
    def narration_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("narration_text must not be empty")
        return v

    @field_validator("scenes")
    @classmethod
    def scenes_sequential(cls, v: list[ScenePlan]) -> list[ScenePlan]:
        for i, scene in enumerate(v):
            if scene.index != i:
                raise ValueError(f"Scene index {scene.index} != expected {i}")
        return v

    @property
    def word_count(self) -> int:
        return len(self.narration_text.split())


class SceneSpec(BaseModel):
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    pose: MascotPose
    phrase: str = ""
    focus: Focus = Focus.NEUTRAL
    image_motion: ImageMotion = ImageMotion.SLOW_ZOOM_IN
    transition: Transition = Transition.QUICK_FADE

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError(f"end ({v}) must be greater than start ({start})")
        return v

    @property
    def duration(self) -> float:
        return self.end - self.start


class TTSSettingsSpec(BaseModel):
    voice_id: str
    language: str = "en"
    stability: float = 0.5
    similarity_boost: float = 0.75
    style_exaggeration: float = 0.0
    speed: float = 1.0
    model_id: str = "eleven_multilingual_v2"


class RenderSpec(BaseModel):
    title: str
    left_label: str
    right_label: str
    left_image: Path
    right_image: Path
    audio: Path
    scenes: list[SceneSpec] = Field(min_length=1)
    template: str = "comparison_v1"
    mascot_set: str = "default"
    narration_text: str = ""
    tts: Optional[TTSSettingsSpec] = None
    background_music: Optional[Path] = None
    sfx_paths: list[Path] = Field(default_factory=list)

    @field_validator("left_image")
    @classmethod
    def left_image_exists(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"left_image not found: {v}")
        return v

    @field_validator("right_image")
    @classmethod
    def right_image_exists(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"right_image not found: {v}")
        return v

    @field_validator("audio")
    @classmethod
    def audio_exists(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"audio not found: {v}")
        return v

    @field_validator("scenes")
    @classmethod
    def scenes_contiguous(cls, v: list[SceneSpec]) -> list[SceneSpec]:
        for i in range(1, len(v)):
            if v[i].start < v[i - 1].end - 0.001:
                raise ValueError(
                    f"Scene {i} starts at {v[i].start} "
                    f"but scene {i - 1} ends at {v[i - 1].end}"
                )
        return v

    @property
    def total_duration(self) -> float:
        return self.scenes[-1].end - self.scenes[0].start


class RenderResult(BaseModel):
    video_path: Path
    poster_path: Path
    contact_sheet_path: Path
    timeline_path: Path
    thumbnail_timestamp_ms: Optional[int] = Field(default=None, ge=0)
    transcript_path: Optional[Path] = None
    direction_path: Optional[Path] = None
    image_provenance_path: Optional[Path] = None
    paired_image_brief_path: Optional[Path] = None
    calibration_path: Optional[Path] = None
    quality_report_path: Optional[Path] = None
    cost_report_path: Optional[Path] = None
    duration_seconds: float
    frame_count: int
    resolution: tuple[int, int]
    scene_count: int


class GenerationResult(BaseModel):
    job_id: str
    render_result: RenderResult


class TimedWord(BaseModel):
    word: str
    start: float
    end: float


class TimedBeat(BaseModel):
    id: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    pause_end: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_timing(self) -> "TimedBeat":
        if self.end < self.start:
            raise ValueError("beat end must be after start")
        if self.pause_end < self.end:
            raise ValueError("beat pause_end must be after end")
        return self


class TimedTranscript(BaseModel):
    words: list[TimedWord] = Field(default_factory=list)
    beats: list[TimedBeat] = Field(default_factory=list)
    duration_seconds: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_timeline(self) -> "TimedTranscript":
        previous_end = 0.0
        for word in self.words:
            if word.end < word.start:
                raise ValueError("word end must be after start")
            if word.start < previous_end - 0.001:
                raise ValueError("word timings overlap")
            previous_end = word.end
        previous_pause_end = 0.0
        for beat in self.beats:
            if beat.start < previous_pause_end - 0.001:
                raise ValueError("beat timings overlap")
            previous_pause_end = beat.pause_end
        if previous_end > self.duration_seconds + 0.001:
            raise ValueError("word timings exceed transcript duration")
        if previous_pause_end > self.duration_seconds + 0.001:
            raise ValueError("beat timings exceed transcript duration")
        return self


class AbsoluteDirectionCue(BaseModel):
    start: float = Field(ge=0.0)
    mascot_pose: MascotPose = MascotPose.NEUTRAL
    mascot_anchor: MascotAnchor = MascotAnchor.CENTER
    product_focus: Focus = Focus.NEUTRAL
    sfx_kind: SfxKind = SfxKind.NONE


class SoundEffectCue(BaseModel):
    start: float = Field(ge=0.0)
    kind: SfxKind
    volume_db: float = -14.0


class CaptionCue(BaseModel):
    words: list[str] = Field(min_length=1)
    active_word_index: int = Field(ge=0)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_caption(self) -> "CaptionCue":
        if self.end <= self.start:
            raise ValueError("caption end must be after start")
        if self.active_word_index >= len(self.words):
            raise ValueError("active word index outside caption")
        return self


class CompiledTimeline(BaseModel):
    direction_cues: list[AbsoluteDirectionCue] = Field(default_factory=list)
    sound_cues: list[SoundEffectCue] = Field(default_factory=list)
    captions: list[CaptionCue] = Field(default_factory=list)


class CompiledVideoSpec(BaseModel):
    left_label: str
    right_label: str
    left_image: Path
    right_image: Path
    narration_audio: Path
    transcript: TimedTranscript
    direction_cues: list[AbsoluteDirectionCue] = Field(default_factory=list)
    sound_cues: list[SoundEffectCue] = Field(default_factory=list)
    captions: list[CaptionCue] = Field(default_factory=list)
    narration_end_seconds: Optional[float] = Field(default=None, ge=0.0)
    outro_duration_seconds: float = Field(default=0.0, ge=0.0)
    cta_text: str = "Like, share, follow"
    template: str = "reference_v1"
    mascot_set: str = "default"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    cta_duration_seconds: float = 1.8

    @model_validator(mode="after")
    def compile_end_times(self) -> "CompiledVideoSpec":
        if self.narration_end_seconds is None:
            self.narration_end_seconds = self.transcript.duration_seconds
        if self.narration_end_seconds < self.transcript.duration_seconds:
            raise ValueError("narration_end_seconds cannot precede transcript duration")
        return self

    @property
    def narration_end(self) -> float:
        return float(self.narration_end_seconds or self.transcript.duration_seconds)

    @property
    def cta_start_seconds(self) -> float:
        # The like/share/follow bubble appears while the closing signoff is spoken,
        # so it starts at the closing beat rather than after narration ends.
        for beat in self.transcript.beats:
            if beat.id == "closing":
                return float(beat.start)
        return self.narration_end

    @property
    def total_duration_seconds(self) -> float:
        return self.narration_end + self.outro_duration_seconds

    @property
    def thumbnail_timestamp_seconds(self) -> float:
        target = ("dar", "care", "e", "diferenta")
        words = self.transcript.words
        normalized = [self._normalize_thumbnail_word(word.word) for word in words]
        for index in range(len(normalized) - len(target) + 1):
            if tuple(normalized[index:index + len(target)]) == target:
                difference = words[index + len(target) - 1]
                return (difference.start + difference.end) / 2
        final_frame_time = max(0.0, self.total_duration_seconds - 1 / self.fps)
        return min(2.0, final_frame_time)

    @staticmethod
    def _normalize_thumbnail_word(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(
            character
            for character in decomposed
            if character.isalnum() and not unicodedata.combining(character)
        )

    @field_validator("left_image", "right_image", "narration_audio")
    @classmethod
    def media_exists(cls, value: Path, info) -> Path:
        if not value.exists():
            raise ValueError(f"{info.field_name} not found: {value}")
        return value


class TimedPhrase(BaseModel):
    text: str
    start: float
    end: float


class SourceReference(BaseModel):
    id: str
    url: str
    title: str
    publisher: str = ""
    retrieved_at: Optional[str] = None
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    source_type: Literal[
        "official", "government", "scientific", "reference",
        "journalism", "retail", "blog", "social", "unknown",
    ] = "unknown"


class ResearchFact(BaseModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    applies_to: Literal["left", "right", "both", "general"] = "general"


class ResearchPackage(BaseModel):
    topic: str
    left_item: str
    right_item: str
    facts: list[ResearchFact] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


class ClaimVerification(BaseModel):
    claim_id: str
    supported: bool
    source_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    severity: Literal["none", "minor", "major"] = "none"


class VerificationResult(BaseModel):
    approved: bool
    claim_results: list[ClaimVerification] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)


class CostRecord(BaseModel):
    job_id: Optional[str] = None
    provider: str
    operation: str
    units: float
    unit_type: str
    estimated_cost_usd: float


class CostEvent(BaseModel):
    event_id: str
    job_id: str
    timestamp_utc: str
    stage: str
    provider: str
    model: str = ""
    operation: str
    input_units: float = 0.0
    output_units: float = 0.0
    unit_type: str = "calls"
    amount_usd: float = Field(default=0.0, ge=0.0)
    amount_kind: Literal["actual", "estimated"] = "estimated"
    pricing_source: str = "estimate"
    attempt: int = Field(default=1, ge=1)
    status: Literal["success", "failed"] = "success"
    cached: bool = False
    error: Optional[str] = None
    request_key: str = ""


class CostReport(BaseModel):
    job_id: str
    events: list[CostEvent] = Field(default_factory=list)
    actual_total_usd: float = 0.0
    estimated_total_usd: float = 0.0
    projected_total_usd: float = 0.0
    by_provider: dict[str, float] = Field(default_factory=dict)
    by_stage: dict[str, float] = Field(default_factory=dict)
    by_operation: dict[str, float] = Field(default_factory=dict)
    by_model: dict[str, float] = Field(default_factory=dict)
    by_amount_kind: dict[str, float] = Field(default_factory=dict)
    billable_calls: int = 0
    failed_calls: int = 0
    cached_calls: int = 0
    retry_calls: int = 0
