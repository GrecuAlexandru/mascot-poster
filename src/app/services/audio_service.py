from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.domain.models import SoundEffectCue
from app.rendering.ffmpeg import FFmpegRunner

logger = logging.getLogger(__name__)


class AudioService:
    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        sample_rate: int = 44100,
    ):
        self.ffmpeg = FFmpegRunner(ffmpeg_bin, ffprobe_bin)
        self.sample_rate = sample_rate

    def mix(
        self,
        narration_path: Path,
        output_path: Path,
        music_path: Optional[Path] = None,
        sfx_paths: Optional[list[Path]] = None,
        music_volume_db: float = -20.0,
        sfx_volume_db: float = -18.0,
        duck_amount_db: float = -8.0,
        fade_in_seconds: float = 0.5,
        fade_out_seconds: float = 0.5,
    ) -> Path:
        narration_duration = self.ffmpeg.get_duration(narration_path)
        if narration_duration <= 0:
            raise ValueError(f"Invalid narration duration: {narration_duration}")

        inputs: list[str] = ["-i", str(narration_path)]
        filter_inputs: list[str] = ["[0:a]"]

        if music_path and music_path.exists():
            inputs.extend(["-i", str(music_path)])
            music_idx = len(inputs) // 2 - 1
            music_input_idx = len(filter_inputs)
            filter_inputs.append(f"[{music_idx}:a]")

        if sfx_paths:
            for sfx in sfx_paths:
                if sfx.exists():
                    inputs.extend(["-i", str(sfx)])
                    sfx_idx = len(inputs) // 2 - 1
                    filter_inputs.append(f"[{sfx_idx}:a]")

        filter_parts: list[str] = []

        filter_parts.append(
            f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d={fade_in_seconds:.3f},"
            f"afade=t=out:st={narration_duration - fade_out_seconds:.3f}:d={fade_out_seconds:.3f}"
            f"[narration]"
        )

        last_label = "[narration]"

        if music_path and music_path.exists():
            music_input = f"[{music_input_idx}:a]" if f"[{music_input_idx}:a]" in filter_inputs else f"[1:a]"
            filter_parts.append(
                f"{music_input}volume={music_volume_db}dB,"
                f"atrim=duration={narration_duration:.3f},"
                f"aresample={self.sample_rate}[music_vol]"
            )
            filter_parts.append(
                f"[narration][music_vol]sidechaincompress="
                f"threshold=0.05:ratio=4:attack=5:release=300:makeup=1[mixed]"
            )
            last_label = "[mixed]"

        if sfx_paths:
            for i, sfx in enumerate(sfx_paths):
                if not sfx.exists():
                    continue
                sfx_idx = inputs.index("-i") + 1
                sfx_input_label = f"[{i + 2}:a]" if music_path else f"[{i + 1}:a]"
                current_mix = i
                mix_label = f"[sfx_mix{i}]" if i < len(sfx_paths) - 1 else "[final]"
                filter_parts.append(
                    f"{sfx_input_label}volume={sfx_volume_db}dB,"
                    f"aresample={self.sample_rate}[sfx{i}]"
                )
                filter_parts.append(
                    f"{last_label}[sfx{i}]amix=inputs=2:duration=first:dropout_transition=0{mix_label}"
                )
                last_label = mix_label

        filter_parts.append(
            f"{last_label}loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"aformat=sample_fmts=fltp:sample_rates={self.sample_rate}:channel_layouts=stereo[final]"
        )
        last_label = "[final]"

        filter_str = ";".join(filter_parts)

        cmd = [
            self.ffmpeg.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", last_label,
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", str(self.sample_rate),
            "-movflags", "+faststart",
            str(output_path),
        ]

        self.ffmpeg._run(cmd)
        logger.info(f"Audio mix complete: {output_path}")
        return output_path

    def trim_audio(
        self,
        audio_path: Path,
        output_path: Path,
        start: float = 0.0,
        duration: Optional[float] = None,
    ) -> Path:
        cmd = [
            self.ffmpeg.ffmpeg_bin, "-y",
            "-ss", f"{start:.3f}",
            "-i", str(audio_path),
        ]
        if duration:
            cmd.extend(["-t", f"{duration:.3f}"])
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", str(self.sample_rate),
            str(output_path),
        ])
        self.ffmpeg._run(cmd)
        return output_path

    def concatenate_with_silence(
        self,
        segments: list[tuple[Path, int]],
        output_path: Path,
    ) -> Path:
        if not segments:
            raise ValueError("At least one audio segment is required")

        inputs: list[str] = []
        filter_parts: list[str] = []
        concat_inputs: list[str] = []
        for index, (path, pause_ms) in enumerate(segments):
            if not path.exists():
                raise FileNotFoundError(path)
            inputs.extend(["-i", str(path)])
            segment_label = f"seg{index}"
            filter_parts.append(
                f"[{index}:a]aresample={self.sample_rate},"
                f"aformat=sample_fmts=fltp:channel_layouts=mono[{segment_label}]"
            )
            concat_inputs.append(f"[{segment_label}]")
            if pause_ms > 0:
                gap_label = f"gap{index}"
                filter_parts.append(
                    f"aevalsrc=0:d={pause_ms / 1000.0:.3f}:s={self.sample_rate},"
                    f"aformat=sample_fmts=fltp:channel_layouts=mono[{gap_label}]"
                )
                concat_inputs.append(f"[{gap_label}]")

        if len(concat_inputs) == 1:
            filter_parts.append(f"{concat_inputs[0]}anull[out]")
        else:
            filter_parts.append(
                f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}:v=0:a=1[out]"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg.ffmpeg_bin,
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            "-ar",
            str(self.sample_rate),
            str(output_path),
        ]
        self.ffmpeg._run(cmd)
        return output_path

    def mix_timed_sfx(
        self,
        narration_path: Path,
        cues: list[SoundEffectCue],
        library: dict,
        output_path: Path,
    ) -> Path:
        narration_duration = self.ffmpeg.get_duration(narration_path)
        if narration_duration <= 0:
            raise ValueError(f"Invalid narration duration: {narration_duration}")

        inputs: list[str] = ["-i", str(narration_path)]
        filters = [
            f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"aformat=sample_rates={self.sample_rate}:channel_layouts=stereo[narration]"
        ]
        mix_inputs = ["[narration]"]
        for index, cue in enumerate(cues):
            source = library.get(cue.kind)
            if source is None or not Path(source).exists():
                raise FileNotFoundError(f"Missing SFX asset for {cue.kind.value}")
            inputs.extend(["-i", str(source)])
            delay_ms = round(cue.start * 1000)
            label = f"sfx{index}"
            filters.append(
                f"[{index + 1}:a]aresample={self.sample_rate},"
                f"aformat=sample_rates={self.sample_rate}:channel_layouts=stereo,"
                f"volume={cue.volume_db:.1f}dB,adelay={delay_ms}|{delay_ms},"
                f"apad,atrim=duration={narration_duration:.3f}[{label}]"
            )
            mix_inputs.append(f"[{label}]")

        if len(mix_inputs) == 1:
            filters.append("[narration]alimiter=limit=0.841395[out]")
        else:
            filters.append(
                f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:"
                f"normalize=0,alimiter=limit=0.841395[out]"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg.ffmpeg_bin,
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            str(self.sample_rate),
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self.ffmpeg._run(cmd)
        return output_path
