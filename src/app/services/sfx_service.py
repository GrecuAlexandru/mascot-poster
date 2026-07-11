from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable

from app.domain.enums import SfxKind


class SfxLibraryService:
    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate

    def ensure_library(self, output_dir: Path) -> dict[SfxKind, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        definitions: dict[SfxKind, tuple[str, float, Callable[[float, random.Random], float]]] = {
            SfxKind.WHOOSH: ("whoosh.wav", 0.22, self._whoosh),
            SfxKind.POSE_POP: ("pose_pop.wav", 0.12, self._pose_pop),
            SfxKind.FOCUS_TICK: ("focus_tick.wav", 0.08, self._focus_tick),
            SfxKind.CTA_STING: ("cta_sting.wav", 0.42, self._cta_sting),
        }
        paths: dict[SfxKind, Path] = {}
        for kind, (filename, duration, generator) in definitions.items():
            path = output_dir / filename
            if not path.exists():
                self._write(path, duration, generator)
            paths[kind] = path
        return paths

    def _write(
        self,
        path: Path,
        duration: float,
        generator: Callable[[float, random.Random], float],
    ) -> None:
        frames = round(duration * self.sample_rate)
        rng = random.Random(20260710)
        samples = bytearray()
        for index in range(frames):
            time = index / self.sample_rate
            value = max(-1.0, min(1.0, generator(time / duration, rng)))
            samples.extend(struct.pack("<h", round(value * 32767)))
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(self.sample_rate)
            audio.writeframes(bytes(samples))

    @staticmethod
    def _whoosh(progress: float, rng: random.Random) -> float:
        envelope = math.sin(math.pi * progress) ** 1.4
        sweep = math.sin(2 * math.pi * (180 * progress + 1500 * progress * progress))
        noise = rng.uniform(-1.0, 1.0)
        return envelope * (0.24 * sweep + 0.28 * noise)

    @staticmethod
    def _pose_pop(progress: float, rng: random.Random) -> float:
        envelope = (1.0 - progress) ** 3
        phase = 2 * math.pi * (260 * progress - 90 * progress * progress)
        return envelope * (0.62 * math.sin(phase) + 0.05 * rng.uniform(-1.0, 1.0))

    @staticmethod
    def _focus_tick(progress: float, rng: random.Random) -> float:
        envelope = (1.0 - progress) ** 6
        return envelope * (
            0.48 * math.sin(2 * math.pi * 1900 * progress)
            + 0.08 * rng.uniform(-1.0, 1.0)
        )

    @staticmethod
    def _cta_sting(progress: float, rng: random.Random) -> float:
        attack = min(progress / 0.08, 1.0)
        release = max(0.0, (1.0 - progress) ** 1.4)
        frequency = 330 + 440 * progress
        tone = math.sin(2 * math.pi * frequency * progress)
        harmony = math.sin(2 * math.pi * frequency * 1.5 * progress)
        return attack * release * (0.38 * tone + 0.18 * harmony)
