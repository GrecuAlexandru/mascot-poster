from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from app.domain.enums import ImageMotion, Transition
from app.domain.exceptions import FFmpegError
from app.rendering.transitions import zoompan_filter


class FFmpegRunner:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def _run(self, cmd: list[str]) -> str:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise FFmpegError(
                f"FFmpeg failed (code {result.returncode}):\n"
                f"cmd: {' '.join(cmd[:20])}...\n"
                f"stderr: {result.stderr[-500:]}"
            )
        return result.stdout

    def get_duration(self, media_path: Path) -> float:
        cmd = [
            self.ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(media_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed: {result.stderr}")
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])

    def create_segment(
        self,
        image_path: Path,
        output_path: Path,
        duration: float,
        fps: int,
        width: int,
        height: int,
        motion: ImageMotion = ImageMotion.SLOW_ZOOM_IN,
    ) -> Path:
        total_frames = max(1, int(duration * fps))
        vf = zoompan_filter(motion, total_frames, width, height, fps)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-t", f"{duration:.3f}",
            "-r", str(fps),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "medium",
            "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            "-frames:v", str(total_frames),
            str(output_path),
        ]
        self._run(cmd)
        return output_path

    def raw_video_command(
        self,
        width: int,
        height: int,
        fps: int,
        output_path: Path,
    ) -> list[str]:
        return [
            self.ffmpeg_bin,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s:v",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    def encode_raw_frames(
        self,
        frames: Iterable,
        width: int,
        height: int,
        fps: int,
        output_path: Path,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.raw_video_command(width, height, fps, output_path)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            if process.stdin is None:
                raise FFmpegError("FFmpeg raw-video stdin is unavailable")
            for frame in frames:
                image = frame.convert("RGB")
                if image.size != (width, height):
                    raise ValueError(
                        f"Raw frame size {image.size} != expected {(width, height)}"
                    )
                process.stdin.write(image.tobytes())
            process.stdin.close()
            process.stdin = None
            _, stderr = process.communicate(timeout=300)
        except Exception:
            process.kill()
            process.wait(timeout=10)
            raise
        if process.returncode != 0:
            raise FFmpegError(
                f"FFmpeg raw video encoding failed ({process.returncode}): "
                f"{stderr.decode(errors='replace')[-500:]}"
            )
        return output_path

    def concat_segments(
        self,
        segment_paths: list[Path],
        output_path: Path,
    ) -> Path:
        concat_input = "\n".join(
            f"file '{p.absolute()}'" for p in segment_paths
        )
        list_file = output_path.parent / "concat_list.txt"
        list_file.write_text(concat_input, encoding="utf-8")

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_path),
        ]
        self._run(cmd)
        list_file.unlink(missing_ok=True)
        return output_path

    def concat_with_xfade(
        self,
        segment_paths: list[Path],
        durations: list[float],
        transitions: list[Transition],
        output_path: Path,
    ) -> Path:
        if len(segment_paths) == 1:
            return segment_paths[0]

        inputs: list[str] = []
        for p in segment_paths:
            inputs.extend(["-i", str(p)])

        filter_parts: list[str] = []
        cumulative = durations[0]
        last_label = "[0:v]"

        for i in range(1, len(segment_paths)):
            transition = transitions[i] if i < len(transitions) else Transition.CUT
            from app.rendering.transitions import xfade_offset

            xfade_dur = xfade_offset(durations[i - 1], transition)
            if xfade_dur and xfade_dur >= 0.05:
                xfade_type = _xfade_type(transition)
                offset_val = max(0.0, cumulative - xfade_dur)
                filter_parts.append(
                    f"{last_label}[{i}:v]xfade=transition={xfade_type}:"
                    f"duration={xfade_dur:.3f}:offset={offset_val:.3f}[x{i}]"
                )
                last_label = f"[x{i}]"
                cumulative = cumulative + durations[i] - xfade_dur
            else:
                filter_parts.append(
                    f"{last_label}[{i}:v]concat=n=2:v=1:a=0[c{i}]"
                )
                last_label = f"[c{i}]"
                cumulative = cumulative + durations[i]

        filter_str = ";".join(filter_parts)
        cmd: list[str] = [self.ffmpeg_bin, "-y"]
        cmd.extend(inputs)
        cmd.extend(["-filter_complex", filter_str])
        cmd.extend(["-map", last_label])
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ])
        self._run(cmd)
        return output_path

    def mux_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        sample_rate: int = 44100,
    ) -> Path:
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", str(sample_rate),
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
        self._run(cmd)
        return output_path

    def create_poster(self, frame_path: Path, output_path: Path) -> Path:
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(frame_path),
            "-q:v", "2",
            str(output_path),
        ]
        self._run(cmd)
        return output_path


def _xfade_type(transition: Transition) -> str:
    mapping = {
        Transition.QUICK_FADE: "fade",
        Transition.CROSSFADE: "fadeblack",
        Transition.FADE: "fade",
        Transition.SLIDE: "slideleft",
        Transition.CUT: "fade",
    }
    return mapping.get(transition, "fade")
