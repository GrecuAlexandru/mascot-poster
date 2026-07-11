from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, Field


class TTSSettings(BaseModel):
    stability: float = Field(default=0.5, ge=0.0, le=1.0)
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0)
    style_exaggeration: float = Field(default=0.0, ge=0.0, le=1.0)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    model_id: str = "eleven_multilingual_v2"
    format: Literal["mp3_44100_128", "mp3_44100_64", "wav_44100_16"] = "mp3_44100_128"


class TTSResult(BaseModel):
    path: Path
    duration_seconds: float
    provider: str
    model: str
    character_count: int
    estimated_cost_usd: float
    timed_words: Optional[list["TimedWord"]] = None
    cached: bool = False

    model_config = {"arbitrary_types_allowed": True}


class TimedWord(BaseModel):
    word: str
    start: float
    end: float


class TimedPhrase(BaseModel):
    text: str
    start: float
    end: float


class TTSProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language: str,
        output_path: Path,
        settings: TTSSettings,
        previous_text: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> TTSResult: ...

    def estimate_cost(self, character_count: int) -> float: ...
