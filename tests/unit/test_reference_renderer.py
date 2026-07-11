from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from app.domain.enums import Focus, MascotAnchor, MascotPose
from app.domain.models import (
    AbsoluteDirectionCue,
    CaptionCue,
    CompiledVideoSpec,
    TimedBeat,
    TimedTranscript,
    TimedWord,
)
from app.rendering.reference_renderer import ReferenceRenderer
from app.rendering.ffmpeg import FFmpegRunner
from app.services.reference_render_service import ReferenceRenderService


def _make_mascot_assets(directory: Path) -> None:
    directory.mkdir()
    (directory / "mascot_meta.json").write_text(
        '{"canvas_width":768,"canvas_height":768,"poses":{"neutral":"neutral.png","point_left":"point_left.png"}}',
        encoding="utf-8",
    )
    (directory / "pose_calibration.json").write_text(
        '{"canvas":{"width":1080,"height":1920},'
        '"reference_dot":{"x":540,"y":1670,"radius":9,"color":[255,0,90,255]},'
        '"source_pivot":{"x":384,"y":744},"base_render_height":533,'
        '"poses":{"neutral":{"x":540,"y":1670,"scale":1.0},'
        '"point_left":{"x":560,"y":1660,"scale":1.1}}}',
        encoding="utf-8",
    )
    for name in ("neutral.png", "point_left.png"):
        mascot = Image.new("RGBA", (768, 768), (255, 255, 255, 0))
        ImageDraw.Draw(mascot).ellipse((180, 120, 588, 700), fill=(230, 130, 30, 255))
        mascot.save(directory / name)


def test_reference_renderer_uses_white_canvas_and_local_product_focus(tmp_path: Path) -> None:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGBA", (800, 800), (255, 40, 40, 255)).save(left)
    Image.new("RGBA", (800, 800), (40, 40, 255, 255)).save(right)
    audio.write_bytes(b"audio")
    transcript = TimedTranscript(
        words=[TimedWord(word="Acum", start=0.0, end=0.5)],
        beats=[TimedBeat(id="b0", start=0.0, end=0.5, pause_end=0.5)],
        duration_seconds=0.5,
    )
    spec = CompiledVideoSpec(
        left_label="Cafea",
        right_label="Ceai",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=transcript,
        direction_cues=[
            AbsoluteDirectionCue(
                start=0.0,
                mascot_pose=MascotPose.POINT_LEFT,
                mascot_anchor=MascotAnchor.LEFT,
                product_focus=Focus.LEFT,
            )
        ],
        captions=[CaptionCue(words=["Acum"], active_word_index=0, start=0.0, end=0.5)],
    )
    renderer = ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )

    frame = renderer.compose_frame(spec, 0.18)

    assert frame.size == (1080, 1920)
    assert frame.getpixel((0, 0)) == (255, 255, 255)
    assert renderer.product_scale_at(spec, 0.18, Focus.LEFT) == 1.28
    assert renderer.product_scale_at(spec, 0.18, Focus.RIGHT) == 1.0
    assert renderer.mascot_x_at(spec, 0.09) < 540
    assert renderer.mascot_pivot_at(spec, 0.18) == (320.0, 1660.0)
    assert not renderer.cta_visible_at(spec, 0.499)
    assert renderer.cta_visible_at(spec, 0.5)
    assert frame.crop((120, 700, 960, 920)).getbbox() is not None
    assert len(list(renderer.iter_frames(spec))) == math.ceil(2.3 * 30)


def test_ffmpeg_raw_encoder_command_accepts_rgb_frame_pipe(tmp_path: Path) -> None:
    command = FFmpegRunner().raw_video_command(1080, 1920, 30, tmp_path / "video.mp4")

    assert command[:6] == ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24"]
    assert "pipe:0" in command
    assert "libx264" in command


def test_reference_render_service_streams_dynamic_frames_and_writes_artifacts(tmp_path: Path) -> None:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGBA", (800, 800), (255, 40, 40, 255)).save(left)
    Image.new("RGBA", (800, 800), (40, 40, 255, 255)).save(right)
    audio.write_bytes(b"audio")
    spec = CompiledVideoSpec(
        left_label="Cafea",
        right_label="Ceai",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=TimedTranscript(
            words=[TimedWord(word="Acum", start=0.0, end=0.5)],
            beats=[TimedBeat(id="b0", start=0.0, end=0.5, pause_end=0.5)],
            duration_seconds=0.5,
        ),
        captions=[CaptionCue(words=["Acum"], active_word_index=0, start=0.0, end=0.5)],
    )

    class FakeFFmpeg:
        def __init__(self) -> None:
            self.frames = 0

        def encode_raw_frames(self, frames, width, height, fps, output_path):
            self.frames = sum(1 for _ in frames)
            output_path.write_bytes(b"silent-video")
            return output_path

        def mux_audio(self, video_path, audio_path, output_path, sample_rate):
            output_path.write_bytes(b"final-video")
            return output_path

    renderer = ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )
    ffmpeg = FakeFFmpeg()
    result = ReferenceRenderService(renderer, ffmpeg).render(spec, tmp_path / "output")

    assert ffmpeg.frames == 69
    assert result.video_path.read_bytes() == b"final-video"
    assert result.poster_path.exists()
    assert result.contact_sheet_path.exists()
    assert result.timeline_path.exists()
    assert result.transcript_path is not None and result.transcript_path.exists()
