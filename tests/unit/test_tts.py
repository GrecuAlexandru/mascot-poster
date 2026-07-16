from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models import TimedWord as DomainTimedWord
from app.providers.tts.base import TTSSettings, TTSResult, TimedWord
from app.services.alignment_service import AlignmentService
from app.services.audio_service import AudioService
from app.services.subtitle_service import SubtitleService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

NARRATION = (
    "Vanilla sugar and vanillin sugar. They look similar. "
    "The difference matters. Natural vanilla has two hundred compounds. "
    "So check the labels carefully. Choose wisely."
)


class TestTTSSettings:
    def test_defaults(self):
        s = TTSSettings()
        assert s.stability == 0.5
        assert s.similarity_boost == 0.75
        assert s.style_exaggeration == 0.0
        assert s.speed == 1.0
        assert s.model_id == "eleven_multilingual_v2"

    def test_stability_bounds(self):
        with pytest.raises(Exception):
            TTSSettings(stability=1.5)

    def test_speed_bounds(self):
        with pytest.raises(Exception):
            TTSSettings(speed=3.0)


class TestTTSResult:
    def test_creation(self):
        r = TTSResult(
            path=Path("/tmp/out.mp3"),
            duration_seconds=60.0,
            provider="elevenlabs",
            model="eleven_multilingual_v2",
            character_count=500,
            estimated_cost_usd=0.15,
        )
        assert r.provider == "elevenlabs"
        assert r.duration_seconds == 60.0
        assert r.timed_words is None

    def test_accepts_domain_timed_words(self):
        word = DomainTimedWord(word="Avem", start=0.0, end=0.43)

        result = TTSResult(
            path=Path("/tmp/out.mp3"),
            duration_seconds=0.43,
            provider="elevenlabs",
            model="eleven_multilingual_v2",
            character_count=4,
            estimated_cost_usd=0.0,
            timed_words=[word],
        )

        assert result.timed_words == [word]


class TestAlignmentService:
    def test_proportional_timing(self):
        svc = AlignmentService()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 10.0
        svc.ffmpeg = mock_ffmpeg

        words = svc._proportional_timing("hello world test", Path("/fake"))

        assert len(words) == 3
        assert words[0].word == "hello"
        assert words[0].start == 0.0
        assert words[-1].end == 10.0

    def test_proportional_timing_proportional(self):
        svc = AlignmentService()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 20.0
        svc.ffmpeg = mock_ffmpeg

        words = svc._proportional_timing("aa bbbb", Path("/fake"))

        assert len(words) == 2
        assert words[0].start < words[1].start
        assert words[0].end <= words[1].start

    def test_align_with_provider_timestamps(self):
        svc = AlignmentService()
        provider_words = [
            TimedWord(word="hello", start=0.0, end=0.5),
            TimedWord(word="world", start=0.5, end=1.0),
        ]
        result = svc.align("hello world", Path("/fake"), timed_words=provider_words)
        assert result == provider_words

    def test_align_fallback(self):
        svc = AlignmentService()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 10.0
        svc.ffmpeg = mock_ffmpeg

        result = svc.align("hello world", Path("/fake"), timed_words=None)
        assert len(result) == 2

    def test_group_into_phrases(self):
        words = [
            TimedWord(word="one", start=0.0, end=1.0),
            TimedWord(word="two", start=1.0, end=2.0),
            TimedWord(word="three", start=2.0, end=3.0),
            TimedWord(word="four", start=3.0, end=4.0),
            TimedWord(word="five", start=4.0, end=5.0),
            TimedWord(word="six", start=5.0, end=6.0),
        ]
        phrases = AlignmentService.group_into_phrases(words, max_phrase_words=3)
        assert len(phrases) == 2
        assert phrases[0].text == "one two three"
        assert phrases[1].text == "four five six"

    def test_find_phrase_timestamps(self):
        words = [
            TimedWord(word="check", start=5.0, end=5.5),
            TimedWord(word="the", start=5.5, end=5.8),
            TimedWord(word="labels", start=5.8, end=6.2),
            TimedWord(word="now", start=6.2, end=6.5),
        ]
        result = AlignmentService.find_phrase_timestamps("check the labels", words)
        assert result is not None
        assert result.start == 5.0
        assert result.end == 6.2

    def test_find_phrase_not_found(self):
        words = [TimedWord(word="hello", start=0.0, end=1.0)]
        result = AlignmentService.find_phrase_timestamps("goodbye", words)
        assert result is None


class TestSubtitleService:
    def test_select_phrases_basic(self):
        svc = SubtitleService()
        words = [
            TimedWord(word="The", start=0.0, end=0.3),
            TimedWord(word="difference", start=0.3, end=0.8),
            TimedWord(word="matters", start=0.8, end=1.2),
        ]
        phrases = svc.select_phrases("The difference matters.", words)
        assert len(phrases) >= 1
        assert any("difference" in p.text for p in phrases)

    def test_select_phrases_empty(self):
        svc = SubtitleService()
        phrases = svc.select_phrases("", [])
        assert phrases == []

    def test_split_sentences(self):
        svc = SubtitleService()
        sentences = svc._split_sentences("Hello world. Test sentence! Next?")
        assert len(sentences) == 3

    def test_deduplicate(self):
        svc = SubtitleService()
        from app.domain.models import TimedPhrase
        phrases = [
            TimedPhrase(text="hello", start=0.0, end=1.0),
            TimedPhrase(text="Hello", start=0.5, end=1.5),
            TimedPhrase(text="world", start=1.0, end=2.0),
        ]
        result = svc._deduplicate(phrases)
        assert len(result) == 2


class TestAudioService:
    def test_mix_narration_only(self, tmp_path):
        svc = AudioService()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 5.0
        svc.ffmpeg = mock_ffmpeg

        narration = tmp_path / "narration.mp3"
        narration.write_bytes(b"fake")
        output = tmp_path / "output.aac"

        svc.mix(
            narration_path=narration,
            output_path=output,
        )

        assert mock_ffmpeg._run.called

    def test_mix_with_music(self, tmp_path):
        svc = AudioService()
        captured_cmds: list[list[str]] = []

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 5.0
        mock_ffmpeg.ffmpeg_bin = "ffmpeg"
        mock_ffmpeg._run = lambda cmd: captured_cmds.append(cmd)
        svc.ffmpeg = mock_ffmpeg

        narration = tmp_path / "narration.mp3"
        narration.write_bytes(b"fake")
        music = tmp_path / "music.mp3"
        music.write_bytes(b"fake")
        output = tmp_path / "output.aac"

        svc.mix(
            narration_path=narration,
            output_path=output,
            music_path=music,
        )

        assert len(captured_cmds) == 1
        filter_str = " ".join(str(x) for x in captured_cmds[0])
        assert "sidechaincompress" in filter_str


class TestElevenLabsProvider:
    def test_estimate_cost(self):
        from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
        provider = ElevenLabsProvider(api_key="fake")
        cost = provider.estimate_cost(1000)
        assert cost > 0
        assert cost == 0.30

    def test_cache_key_deterministic(self):
        from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
        provider = ElevenLabsProvider(api_key="fake")
        settings = TTSSettings()
        key1 = provider._cache_key("hello", "voice1", settings)
        key2 = provider._cache_key("hello", "voice1", settings)
        key3 = provider._cache_key("hello", "voice2", settings)
        assert key1 == key2
        assert key1 != key3

    def test_cache_hit(self, tmp_path):
        from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
        import hashlib

        cache_dir = tmp_path / "tts_cache"
        provider = ElevenLabsProvider(api_key="fake", cache_dir=cache_dir)

        settings = TTSSettings()
        key = provider._cache_key("hello", "voice1", settings)

        audio_path = cache_dir / f"{key}.mp3"
        audio_path.write_bytes(b"fake_audio")
        meta_path = cache_dir / f"{key}.json"
        meta_path.write_text(json.dumps({
            "duration_seconds": 1.5,
            "timed_words": [{"word": "hello", "start": 0.0, "end": 1.5}],
        }))

        cached = provider._cache_path(key)
        assert cached is not None
        assert cached.exists()


class TestWordTimestampBuilder:
    def test_build_word_timestamps(self):
        from app.providers.tts.elevenlabs_provider import _build_word_timestamps
        chars = list("hello world")
        starts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        ends = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]

        words = _build_word_timestamps(chars, starts, ends)
        assert len(words) == 2
        assert words[0]["word"] == "hello"
        assert words[1]["word"] == "world"

    def test_empty_input(self):
        from app.providers.tts.elevenlabs_provider import _build_word_timestamps
        assert _build_word_timestamps([], [], []) == []
