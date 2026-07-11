from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.tts.base import TTSSettings, TTSResult, TimedWord

logger = logging.getLogger(__name__)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
ELEVENLABS_COST_PER_1K_CHARS = 0.30


class ElevenLabsError(Exception):
    pass


class ElevenLabsTransientError(ElevenLabsError):
    pass


class ElevenLabsProvider:
    name = "elevenlabs"

    def __init__(
        self,
        api_key: str,
        cache_dir: Optional[Path] = None,
        timeout: float = 60.0,
    ):
        self._api_key = api_key
        self._cache_dir = cache_dir
        self._timeout = timeout
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def estimate_cost(self, character_count: int) -> float:
        return round((character_count / 1000) * ELEVENLABS_COST_PER_1K_CHARS, 4)

    def _cache_key(
        self,
        text: str,
        voice_id: str,
        settings: TTSSettings,
        previous_text: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> str:
        parts = (
            f"{text}|{voice_id}|{settings.model_dump_json()}|"
            f"{previous_text or ''}|{seed if seed is not None else ''}"
        )
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_request_body(
        text: str,
        settings: TTSSettings,
        previous_text: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "text": text,
            "model_id": settings.model_id,
            "voice_settings": {
                "stability": settings.stability,
                "similarity_boost": settings.similarity_boost,
                "style": settings.style_exaggeration,
                "use_speaker_boost": True,
                "speed": settings.speed,
            },
        }
        if previous_text:
            body["previous_text"] = previous_text
        if seed is not None:
            body["seed"] = seed
        return body

    def _cache_path(self, key: str) -> Optional[Path]:
        if not self._cache_dir:
            return None
        meta_path = self._cache_dir / f"{key}.json"
        audio_path = self._cache_dir / f"{key}.mp3"
        if meta_path.exists() and audio_path.exists():
            return audio_path
        return None

    def _load_cache_meta(self, key: str) -> Optional[dict]:
        if not self._cache_dir:
            return None
        meta_path = self._cache_dir / f"{key}.json"
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        return None

    def _save_cache(
        self,
        key: str,
        audio_data: bytes,
        meta: dict,
        extension: str = "mp3",
    ) -> Path:
        if not self._cache_dir:
            return Path("")
        audio_path = self._cache_dir / f"{key}.{extension}"
        audio_path.write_bytes(audio_data)
        meta_path = self._cache_dir / f"{key}.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return audio_path

    @retry(
        retry=retry_if_exception_type(ElevenLabsTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_api(
        self,
        text: str,
        voice_id: str,
        settings: TTSSettings,
        with_timestamps: bool = True,
        previous_text: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> tuple[bytes, Optional[list[dict]]]:
        url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}"
        params = {
            "model_id": settings.model_id,
            "voice_settings": {
                "stability": settings.stability,
                "similarity_boost": settings.similarity_boost,
                "style": settings.style_exaggeration,
                "use_speaker_boost": True,
            },
        }
        if with_timestamps:
            params["with_timestamps"] = True
            url = f"{url}/with-timestamps"

        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = self._build_request_body(text, settings, previous_text, seed)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, headers=headers, json=body)

        if response.status_code == 429:
            raise ElevenLabsTransientError("Rate limited")
        if response.status_code >= 500:
            raise ElevenLabsTransientError(f"Server error: {response.status_code}")
        if response.status_code != 200:
            raise ElevenLabsError(
                f"ElevenLabs API error {response.status_code}: {response.text[:500]}"
            )

        data = response.json()

        if with_timestamps and "audio_base64" in data:
            import base64
            audio_bytes = base64.b64decode(data["audio_base64"])
            chars = data.get("alignment", {}).get("characters", [])
            starts = data.get("alignment", {}).get("character_start_times_seconds", [])
            ends = data.get("alignment", {}).get("character_end_times_seconds", [])
            timestamps = _build_word_timestamps(chars, starts, ends)
            return audio_bytes, timestamps
        elif "audio_base64" in data:
            import base64
            audio_bytes = base64.b64decode(data["audio_base64"])
            return audio_bytes, None
        elif "audio" in data:
            import base64
            audio_bytes = base64.b64decode(data["audio"])
            return audio_bytes, data.get("alignment")

        audio_bytes = response.content
        return audio_bytes, None

    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language: str,
        output_path: Path,
        settings: TTSSettings,
        previous_text: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> TTSResult:
        character_count = len(text)
        cost = self.estimate_cost(character_count)
        ext = "mp3" if "mp3" in settings.format else "wav"

        key = self._cache_key(text, voice_id, settings, previous_text, seed)
        cached_audio = self._cache_path(key)
        if cached_audio:
            logger.info(f"TTS cache hit: {key[:12]}...")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(cached_audio.read_bytes())
            meta = self._load_cache_meta(key) or {}
            timed_words = None
            if meta.get("timed_words"):
                timed_words = [TimedWord(**w) for w in meta["timed_words"]]
            return TTSResult(
                path=output_path,
                duration_seconds=meta.get("duration_seconds", 0.0),
                provider=self.name,
                model=settings.model_id,
                character_count=character_count,
                estimated_cost_usd=cost,
                timed_words=timed_words,
                cached=True,
            )

        logger.info(
            f"Calling ElevenLabs: voice={voice_id}, chars={character_count}, "
            f"model={settings.model_id}"
        )
        audio_bytes, timestamps = await self._call_api(
            text,
            voice_id,
            settings,
            previous_text=previous_text,
            seed=seed,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

        duration = _get_duration_ffprobe(output_path)

        timed_words: list[TimedWord] | None = None
        if timestamps:
            timed_words = [TimedWord(**tw) for tw in timestamps]

        if self._cache_dir:
            meta = {
                "duration_seconds": duration,
                "timed_words": [tw.model_dump() for tw in timed_words] if timed_words else None,
                "voice_id": voice_id,
                "model_id": settings.model_id,
            }
            self._save_cache(key, audio_path=output_path, audio_data=audio_bytes, meta=meta)

        return TTSResult(
            path=output_path,
            duration_seconds=duration,
            provider=self.name,
            model=settings.model_id,
            character_count=character_count,
            estimated_cost_usd=cost,
            timed_words=timed_words,
        )

    def _save_cache(self, key: str, audio_data: bytes, meta: dict, audio_path: Path = None, extension: str = "mp3") -> Path:
        if not self._cache_dir:
            return Path("")
        cache_audio = self._cache_dir / f"{key}.{extension}"
        cache_audio.write_bytes(audio_data)
        cache_meta = self._cache_dir / f"{key}.json"
        cache_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return cache_audio


def _build_word_timestamps(
    chars: list[str],
    starts: list[float],
    ends: list[float],
) -> list[dict]:
    if not chars or not starts or not ends:
        return []

    words: list[dict] = []
    current_word = ""
    word_start: float | None = None
    word_end: float | None = None

    for i, ch in enumerate(chars):
        if i >= len(starts) or i >= len(ends):
            break
        if ch.isspace():
            if current_word and word_start is not None:
                words.append({
                    "word": current_word,
                    "start": word_start,
                    "end": word_end or word_start,
                })
                current_word = ""
                word_start = None
                word_end = None
        else:
            if word_start is None:
                word_start = starts[i]
            word_end = ends[i]
            current_word += ch

    if current_word and word_start is not None:
        words.append({
            "word": current_word,
            "start": word_start,
            "end": word_end or word_start,
        })

    return words


def _get_duration_ffprobe(path: Path) -> float:
    import subprocess
    import json as json_mod
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data = json_mod.loads(result.stdout)
            return float(data["format"]["duration"])
    except Exception:
        pass
    return 0.0
