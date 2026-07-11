from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.domain.models import RenderResult
from app.rendering.ffmpeg import FFmpegRunner

logger = logging.getLogger(__name__)

EXPECTED_WIDTH = 1080
EXPECTED_HEIGHT = 1920
EXPECTED_FPS = 30
MIN_DURATION = 15.0
MAX_DURATION = 180.0
MAX_FILE_SIZE = 500 * 1024 * 1024
MIN_FILE_SIZE = 100 * 1024


class QualityService:
    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
    ):
        self.ffmpeg = FFmpegRunner(ffmpeg_bin, ffprobe_bin)

    def validate_video(self, video_path: Path) -> list[str]:
        problems: list[str] = []

        if not video_path.exists():
            problems.append(f"Video file does not exist: {video_path}")
            return problems

        file_size = video_path.stat().st_size
        if file_size < MIN_FILE_SIZE:
            problems.append(f"File size too small: {file_size} bytes")
        if file_size > MAX_FILE_SIZE:
            problems.append(f"File size too large: {file_size} bytes")

        try:
            info = self._probe_video(video_path)
        except Exception as e:
            problems.append(f"FFprobe failed: {e}")
            return problems

        streams = info.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not video_streams:
            problems.append("No video stream found")
        else:
            vs = video_streams[0]
            if vs.get("codec_name") != "h264":
                problems.append(f"Video codec is {vs.get('codec_name')}, expected h264")
            if vs.get("width") != EXPECTED_WIDTH:
                problems.append(f"Width is {vs.get('width')}, expected {EXPECTED_WIDTH}")
            if vs.get("height") != EXPECTED_HEIGHT:
                problems.append(f"Height is {vs.get('height')}, expected {EXPECTED_HEIGHT}")

            fps_str = vs.get("r_frame_rate", "0/1")
            try:
                num, den = fps_str.split("/")
                fps = int(num) / int(den) if int(den) != 0 else 0
                if abs(fps - EXPECTED_FPS) > 1:
                    problems.append(f"Frame rate is {fps:.0f}, expected {EXPECTED_FPS}")
            except Exception:
                problems.append(f"Could not parse frame rate: {fps_str}")

        if not audio_streams:
            problems.append("No audio stream found")
        else:
            as_codec = audio_streams[0].get("codec_name")
            if as_codec not in ("aac", "mp3"):
                problems.append(f"Audio codec is {as_codec}, expected aac")

        duration = float(info.get("format", {}).get("duration", 0))
        if duration < MIN_DURATION:
            problems.append(f"Duration {duration:.1f}s is below minimum {MIN_DURATION}s")
        if duration > MAX_DURATION:
            problems.append(f"Duration {duration:.1f}s exceeds maximum {MAX_DURATION}s")

        if problems:
            logger.warning(f"Quality check FAILED: {len(problems)} problems")
        else:
            logger.info("Quality check PASSED")

        return problems

    def validate_content(
        self,
        render_result: RenderResult,
        expected_scene_count: int = 0,
    ) -> list[str]:
        problems: list[str] = []

        if not render_result.poster_path.exists():
            problems.append("Poster frame not found")
        if not render_result.contact_sheet_path.exists():
            problems.append("Contact sheet not found")
        if not render_result.timeline_path.exists():
            problems.append("Timeline JSON not found")

        if expected_scene_count > 0 and render_result.scene_count != expected_scene_count:
            problems.append(
                f"Scene count {render_result.scene_count} != expected {expected_scene_count}"
            )

        if render_result.duration_seconds < MIN_DURATION:
            problems.append(
                f"Render duration {render_result.duration_seconds:.1f}s below minimum"
            )

        if render_result.resolution != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
            problems.append(
                f"Resolution {render_result.resolution} != expected "
                f"({EXPECTED_WIDTH}, {EXPECTED_HEIGHT})"
            )

        return problems

    def generate_preview(
        self,
        video_path: Path,
        output_path: Path,
        scale: int = 360,
    ) -> Path:
        import subprocess

        cmd = [
            self.ffmpeg.ffmpeg_bin,
            "-y",
            "-i", str(video_path),
            "-vf", f"scale={scale}:-1",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "28",
            "-an",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"Preview generation failed: {result.stderr[-300:]}")
        return output_path

    def _probe_video(self, path: Path) -> dict:
        import subprocess

        cmd = [
            self.ffmpeg.ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")
        return json.loads(result.stdout)
