from __future__ import annotations

import math
from pathlib import Path

import pytest
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
from app.rendering.text_layout import measure_text
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


def _caption_renderer(tmp_path: Path) -> ReferenceRenderer:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    return ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )


def test_reference_caption_layout_uses_compact_one_or_two_rows(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    region = renderer.template.region("caption")

    _, one_word_lines = renderer._caption_layout(["Natural"], region)
    _, two_word_lines = renderer._caption_layout(["Aromă", "pură"], region)
    _, three_word_lines = renderer._caption_layout(["Are", "aromă", "naturală"], region)
    _, four_word_lines = renderer._caption_layout(
        ["Avem", "zahăr", "vanilat", "natural"],
        region,
    )

    assert one_word_lines == [["Natural"]]
    assert two_word_lines == [["Aromă", "pură"]]
    assert three_word_lines == [["Are", "aromă"], ["naturală"]]
    assert four_word_lines == [["Avem", "zahăr"], ["vanilat", "natural"]]


def test_reference_caption_uses_one_fixed_highlight_color(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    assert getattr(renderer, "caption_word_gap_ratio", None) == 0.40
    assert getattr(renderer, "caption_line_height_ratio", None) == 1.38
    assert getattr(renderer, "caption_highlight_color", None) == (232, 117, 96)


def test_reference_renderer_reloads_an_overwritten_product_image(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    product_path = tmp_path / "left.png"
    Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(product_path)

    assert renderer._image(product_path).getpixel((0, 0)) == (255, 0, 0, 255)

    Image.new("RGBA", (20, 20), (0, 0, 255, 255)).save(product_path)

    assert renderer._image(product_path).getpixel((0, 0)) == (0, 0, 255, 255)


def test_reference_renderer_uses_bold_italic_font_for_object_labels(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    assert renderer._label_font_path == Path("C:/Windows/Fonts/arialbi.ttf")


def test_reference_renderer_draws_one_fixed_card_behind_only_the_active_caption_word(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    canvas = Image.new("RGBA", (1080, 1920), "white")
    region = renderer.template.region("caption")
    assert region.y == 780
    cue = CaptionCue(words=["Dar", "care"], active_word_index=0, start=0.0, end=0.5)
    font, _ = renderer._caption_layout(cue.words, region)
    widths = [measure_text(word, font)[0] for word in cue.words]
    gap = round(font.size * 0.40)
    line_width = sum(widths) + gap
    x = region.center[0] - line_width // 2
    y = region.center[1] - round(font.size * 1.38) // 2
    stroke = max(3, font.size // 14)
    padding_x = max(12, font.size // 7)
    padding_y = max(10, font.size // 9)
    text_bbox = ImageDraw.Draw(canvas).textbbox(
        (x, y),
        cue.words[0],
        font=font,
        stroke_width=stroke,
    )

    renderer._draw_caption(ImageDraw.Draw(canvas), cue)

    active_mask = Image.new("1", canvas.size)
    active_mask.putdata([
        pixel == (232, 117, 96, 255)
        for pixel in canvas.get_flattened_data()
    ])
    active_bbox = active_mask.getbbox()
    assert active_bbox is not None
    second_x = x + widths[0] + gap
    inactive_background = canvas.getpixel(
        (second_x + widths[1] // 2, text_bbox[1] - padding_y + 3),
    )
    expected_bbox = (
        text_bbox[0] - padding_x,
        text_bbox[1] - padding_y,
        text_bbox[2] + padding_x + 1,
        text_bbox[3] + padding_y + 1,
    )

    assert active_bbox == pytest.approx(expected_bbox, abs=1)
    assert inactive_background == (255, 255, 255, 255)


def test_reference_renderer_equalizes_product_extent_and_centers_each_half(tmp_path: Path) -> None:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    left_image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
    right_image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
    ImageDraw.Draw(left_image).rectangle((212, 162, 811, 861), fill=(240, 20, 20, 255))
    ImageDraw.Draw(right_image).rectangle((312, 212, 711, 811), fill=(20, 20, 240, 255))
    left_image.save(left)
    right_image.save(right)
    audio.write_bytes(b"audio")
    transcript = TimedTranscript(
        words=[TimedWord(word="Test", start=0.0, end=0.5)],
        beats=[TimedBeat(id="b0", start=0.0, end=0.5, pause_end=0.5)],
        duration_seconds=0.5,
    )
    spec = CompiledVideoSpec(
        left_label="Left",
        right_label="Right",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=transcript,
    )
    renderer = ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )

    frame = renderer.compose_frame(spec, 0.0).convert("RGB")

    def color_bbox(color: tuple[int, int, int]) -> tuple[int, int, int, int]:
        mask = Image.new("1", frame.size)
        mask.putdata([pixel == color for pixel in frame.get_flattened_data()])
        bbox = mask.getbbox()
        assert bbox is not None
        return bbox

    left_bbox = color_bbox((240, 20, 20))
    right_bbox = color_bbox((20, 20, 240))
    left_size = (left_bbox[2] - left_bbox[0], left_bbox[3] - left_bbox[1])
    right_size = (right_bbox[2] - right_bbox[0], right_bbox[3] - right_bbox[1])

    assert max(left_size) == pytest.approx(max(right_size), abs=1)
    assert ((left_bbox[0] + left_bbox[2]) / 2, (left_bbox[1] + left_bbox[3]) / 2) == pytest.approx((270, 325), abs=1)
    assert ((right_bbox[0] + right_bbox[2]) / 2, (right_bbox[1] + right_bbox[3]) / 2) == pytest.approx((810, 325), abs=1)


def test_reference_renderer_uses_a_tail_free_cta_card(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    card, anchor_y = renderer._build_speech_bubble("Like, share, follow")
    colors = set(card.get_flattened_data())
    _, lines = renderer._bubble_lines(renderer._cta_display_text("Like, share, follow"))

    assert renderer._cta_display_text("Like, share, follow") == "LIKE · SHARE · FOLLOW"
    assert lines == ["LIKE · SHARE · FOLLOW"]
    assert (24, 25, 30, 255) in colors
    assert (255, 196, 61, 255) in colors
    assert (255, 255, 255, 255) in colors
    assert anchor_y == card.height


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
    assert renderer.mascot_pivot_at(spec, 0.0) == (320.0, 1660.0)
    assert not renderer.cta_visible_at(spec, 0.499)
    assert not renderer.cta_visible_at(spec, 0.5)
    assert frame.crop((120, 700, 960, 920)).getbbox() is not None
    assert len(list(renderer.iter_frames(spec))) == math.ceil(0.5 * 30)


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

    assert ffmpeg.frames == 15
    assert result.video_path.read_bytes() == b"final-video"
    assert result.poster_path.exists()
    assert result.thumbnail_timestamp_ms == 467
    thumbnail_metadata = __import__("json").loads(
        (tmp_path / "output" / "thumbnail.json").read_text(encoding="utf-8")
    )
    assert thumbnail_metadata == {
        "thumbnail_offset_ms": 467,
    }

    assert result.contact_sheet_path.exists()
    assert result.timeline_path.exists()
    assert result.transcript_path is not None and result.transcript_path.exists()
