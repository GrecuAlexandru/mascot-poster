from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image

from app.domain.models import CompiledVideoSpec, RenderResult
from app.rendering.ffmpeg import FFmpegRunner
from app.rendering.reference_renderer import ReferenceRenderer


class ReferenceRenderService:
    def __init__(self, renderer: ReferenceRenderer, ffmpeg: FFmpegRunner | object):
        self.renderer = renderer
        self.ffmpeg = ffmpeg

    def render(self, spec: CompiledVideoSpec, output_dir: Path) -> RenderResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = output_dir / "_reference_work"
        work_dir.mkdir(exist_ok=True)
        frame_count = max(1, math.ceil(spec.total_duration_seconds * spec.fps))
        capture_indexes = self._capture_indexes(spec, frame_count)
        captures: list[Image.Image] = []

        def frames():
            for index, frame in enumerate(self.renderer.iter_frames(spec)):
                if index in capture_indexes:
                    captures.append(frame.copy())
                yield frame

        silent_video = work_dir / "video_silent.mp4"
        self.ffmpeg.encode_raw_frames(
            frames(),
            spec.width,
            spec.height,
            spec.fps,
            silent_video,
        )
        if not captures:
            captures.append(self.renderer.compose_frame(spec, 0.0))

        video_path = output_dir / "video.mp4"
        self.ffmpeg.mux_audio(
            silent_video,
            spec.narration_audio,
            video_path,
            44100,
        )
        poster_path = output_dir / "poster.jpg"
        captures[0].save(poster_path, quality=92)
        contact_sheet_path = output_dir / "contact-sheet.jpg"
        self._contact_sheet(captures).save(contact_sheet_path, quality=90)
        timeline_path = output_dir / "timeline.json"
        timeline_path.write_text(
            json.dumps(spec.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        transcript_path = output_dir / "transcript.json"
        transcript_path.write_text(
            spec.transcript.model_dump_json(indent=2),
            encoding="utf-8",
        )
        direction_path = output_dir / "direction.json"
        direction_path.write_text(
            json.dumps({
                "direction_cues": [cue.model_dump(mode="json") for cue in spec.direction_cues],
                "sound_cues": [cue.model_dump(mode="json") for cue in spec.sound_cues],
                "captions": [cue.model_dump(mode="json") for cue in spec.captions],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return RenderResult(
            video_path=video_path,
            poster_path=poster_path,
            contact_sheet_path=contact_sheet_path,
            timeline_path=timeline_path,
            transcript_path=transcript_path,
            direction_path=direction_path,
            calibration_path=self.renderer.calibration_path,
            duration_seconds=spec.total_duration_seconds,
            frame_count=frame_count,
            resolution=(spec.width, spec.height),
            scene_count=len(spec.direction_cues),
        )

    @staticmethod
    def _capture_indexes(spec: CompiledVideoSpec, frame_count: int) -> set[int]:
        indexes = {0, frame_count - 1}
        for cue in spec.direction_cues:
            indexes.add(min(frame_count - 1, max(0, round(cue.start * spec.fps))))
        return indexes

    @staticmethod
    def _contact_sheet(images: list[Image.Image]) -> Image.Image:
        thumb_width = 270
        thumbs = [
            image.resize(
                (thumb_width, round(thumb_width * image.height / image.width)),
                Image.Resampling.LANCZOS,
            )
            for image in images
        ]
        thumb_height = thumbs[0].height
        columns = min(3, len(thumbs))
        rows = math.ceil(len(thumbs) / columns)
        padding = 12
        sheet = Image.new(
            "RGB",
            (
                columns * thumb_width + (columns + 1) * padding,
                rows * thumb_height + (rows + 1) * padding,
            ),
            (255, 255, 255),
        )
        for index, thumb in enumerate(thumbs):
            x = padding + (index % columns) * (thumb_width + padding)
            y = padding + (index // columns) * (thumb_height + padding)
            sheet.paste(thumb, (x, y))
        return sheet
