from __future__ import annotations

import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.domain.enums import Focus, MascotAnchor, MascotPose, VisualEventKind
from app.domain.models import (
    AbsoluteDirectionCue,
    CaptionCue,
    CompiledVideoSpec,
    TimedBeat,
    TimedTranscript,
    TimedWord,
    VisualEvent,
)
from app.rendering.reference_renderer import ReferenceRenderer
from app.rendering.ffmpeg import FFmpegRunner
from app.rendering.text_layout import load_font, measure_text
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

    one_word_font, one_word_lines = renderer._caption_layout(["Natural"], region)
    two_word_font, two_word_lines = renderer._caption_layout(["Aromă", "pură"], region)
    three_word_font, three_word_lines = renderer._caption_layout(
        ["Are", "aromă", "naturală"],
        region,
    )
    _, four_word_lines = renderer._caption_layout(
        ["Avem", "zahăr", "vanilat", "natural"],
        region,
    )

    assert one_word_font.size == 76
    assert two_word_font.size == 76
    assert three_word_font.size == 76
    assert one_word_lines == [["Natural"]]
    assert two_word_lines == [["Aromă", "pură"]]
    assert three_word_lines == [["Are", "aromă"], ["naturală"]]
    assert four_word_lines == [["Avem", "zahăr"], ["vanilat", "natural"]]


def test_reference_caption_layout_never_places_more_than_two_words_on_a_row(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    font = load_font(renderer.font_path, 88)

    for word_count in range(1, 5):
        words = ["A", "B", "C", "D"][:word_count]
        lines = renderer._caption_lines(words, font, 10_000)

        assert len(lines) <= 2
        assert all(len(line) <= 2 for line in lines)
        assert [word for line in lines for word in line] == words


def test_reference_caption_uses_editorial_tile_brand_system(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    assert renderer.caption_card_colors == (
        (232, 117, 96),
        (242, 193, 78),
        (120, 198, 163),
    )
    assert renderer.caption_text_color == (36, 31, 26)
    assert renderer.caption_active_scale == 1.0
    assert renderer.caption_active_lift == 0


def test_reference_caption_region_is_centered_and_uses_sixty_five_percent_width(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    region = renderer.template.region("caption")

    assert region.width == round(renderer.template.canvas_width * 0.65)
    assert region.center[0] == renderer.template.canvas_width // 2


def test_reference_caption_cards_have_equal_height_for_every_word(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    font = load_font(renderer.font_path, 88)
    cards = [
        renderer._build_caption_card(
            word,
            font,
            renderer.caption_card_style(word, index),
            active=False,
        )
        for index, word in enumerate(["e", "până", "Țară,"])
    ]

    def fill_height(card: Image.Image, color: tuple[int, int, int]) -> int:
        mask = Image.new("1", card.size)
        mask.putdata([pixel[:3] == color for pixel in card.get_flattened_data()])
        bbox = mask.getbbox()
        assert bbox is not None
        return bbox[3] - bbox[1]

    assert len({card.height for card in cards}) == 1
    assert len({
        fill_height(card, renderer.caption_card_colors[index])
        for index, card in enumerate(cards)
    }) == 1


def test_reference_renderer_reloads_an_overwritten_product_image(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    product_path = tmp_path / "left.png"
    Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(product_path)

    assert renderer._image(product_path).getpixel((0, 0)) == (255, 0, 0, 255)

    Image.new("RGBA", (20, 20), (0, 0, 255, 255)).save(product_path)

    assert renderer._image(product_path).getpixel((0, 0)) == (0, 0, 255, 255)


def test_reference_renderer_keeps_a_transparent_product_safety_margin(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    product_path = tmp_path / "left.png"
    image = Image.new("RGBA", (100, 100), (248, 249, 247, 255))
    ImageDraw.Draw(image).rectangle((20, 10, 79, 89), fill=(30, 30, 30, 255))
    image.save(product_path)

    normalized = renderer._image(product_path)

    assert normalized.size == (68, 88)
    assert normalized.getpixel((0, 0))[3] == 0


def test_reference_renderer_uses_bold_italic_font_for_object_labels(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    assert renderer._label_font_path == Path("C:/Windows/Fonts/arialbi.ttf")


def test_reference_caption_card_geometry_is_clean_and_unrotated(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    first = renderer.caption_card_style("Diferența", 1)
    second = renderer.caption_card_style("Diferența", 1)

    assert first == second
    assert first.rotation_degrees == 0
    assert first.corner_offsets == ((0, 0), (0, 0), (0, 0), (0, 0))
    assert first.fill == renderer.caption_card_colors[1]


def test_reference_caption_does_not_visually_highlight_the_active_word(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    font = load_font(renderer.font_path, 118)
    style = renderer.caption_card_style("câteva", 1)

    inactive = renderer._build_caption_card("câteva", font, style, active=False)
    active = renderer._build_caption_card("câteva", font, style, active=True)

    assert active.size == inactive.size
    assert list(active.get_flattened_data()) == list(inactive.get_flattened_data())


def test_reference_caption_words_reveal_in_predefined_slot_positions(
    tmp_path: Path,
) -> None:
    renderer = _caption_renderer(tmp_path)
    slot_words = ["Avem", "zahăr", "vanilat", "și"]
    frames = [Image.new("RGBA", (1080, 1920), "white") for _ in slot_words]
    for index, frame in enumerate(frames):
        renderer._draw_caption(
            frame,
            CaptionCue(
                words=slot_words[:index + 1],
                slot_words=slot_words,
                active_word_index=index,
                start=float(index),
                end=float(index + 1),
            ),
        )

    region = renderer.template.region("caption")

    def top_row_bbox(image: Image.Image, color: tuple[int, int, int]):
        mask = Image.new("1", image.size)
        mask.putdata([
            pixel[:3] == color and index // image.width < region.center[1]
            for index, pixel in enumerate(image.get_flattened_data())
        ])
        bbox = mask.getbbox()
        assert bbox is not None
        return bbox

    first_word_positions = [top_row_bbox(frame, renderer.caption_card_colors[0]) for frame in frames]
    assert first_word_positions == [first_word_positions[0]] * len(frames)
    assert renderer.caption_card_colors[1] not in {
        pixel[:3] for pixel in frames[0].get_flattened_data()
    }
    assert renderer.caption_card_colors[2] not in {
        pixel[:3] for pixel in frames[1].get_flattened_data()
    }


def test_reference_renderer_draws_a_card_behind_every_caption_word(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    canvas = Image.new("RGBA", (1080, 1920), "white")
    cue = CaptionCue(words=["Dar", "care", "diferența"], active_word_index=1, start=0.0, end=0.5)

    renderer._draw_caption(canvas, cue)

    colors = set(canvas.get_flattened_data())
    assert {(232, 117, 96, 255), (242, 193, 78, 255), (120, 198, 163, 255)} <= colors
    assert (36, 31, 26, 255) in colors


def test_reference_caption_card_has_dark_flat_text_without_white_outline(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    font = load_font(renderer.font_path, 118)
    style = renderer.caption_card_style("Diferența", 0)

    card = renderer._build_caption_card("Diferența", font, style, active=False)

    opaque_colors = {
        pixel[:3]
        for pixel in card.get_flattened_data()
        if pixel[3] == 255
    }
    assert renderer.caption_text_color in opaque_colors
    assert (255, 255, 255) not in opaque_colors


def test_reference_caption_long_romanian_words_stay_inside_region(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    canvas = Image.new("RGBA", (1080, 1920), "white")
    region = renderer.template.region("caption")
    cue = CaptionCue(
        words=["electrocasnicelor", "neconfundabile", "surprinzătoare"],
        active_word_index=1,
        start=0.0,
        end=0.5,
    )

    renderer._draw_caption(canvas, cue)

    mask = Image.new("1", canvas.size)
    mask.putdata([pixel != (255, 255, 255, 255) for pixel in canvas.get_flattened_data()])
    bbox = mask.getbbox()
    assert bbox is not None
    assert bbox[0] >= region.x
    assert bbox[1] >= region.y
    assert bbox[2] <= region.x2
    assert bbox[3] <= region.y2


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

    assert left_size[1] == pytest.approx(right_size[1], abs=1)
    assert left_size[1] == pytest.approx(519, abs=4)
    assert ((left_bbox[0] + left_bbox[2]) / 2, (left_bbox[1] + left_bbox[3]) / 2) == pytest.approx((277.5, 365), abs=1)
    assert ((right_bbox[0] + right_bbox[2]) / 2, (right_bbox[1] + right_bbox[3]) / 2) == pytest.approx((802.5, 365), abs=1)


def test_reference_renderer_stages_products_and_labels_from_visual_events(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGBA", (300, 400), (240, 20, 20, 255)).save(left)
    Image.new("RGBA", (300, 400), (20, 20, 240, 255)).save(right)
    audio.write_bytes(b"audio")
    spec = CompiledVideoSpec(
        left_label="StÃ¢nga",
        right_label="Dreapta",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=TimedTranscript(duration_seconds=3.0),
        visual_events=[
            VisualEvent(kind=VisualEventKind.REVEAL_LEFT, start=0.0),
            VisualEvent(kind=VisualEventKind.REVEAL_RIGHT, start=1.2),
            VisualEvent(kind=VisualEventKind.SHOW_BOTH, start=2.0),
        ],
    )

    opening = renderer.compose_frame(spec, 0.0)
    left_only = renderer.compose_frame(spec, 0.3)
    both = renderer.compose_frame(spec, 1.5)

    assert (240, 20, 20) not in set(opening.get_flattened_data())
    assert (20, 20, 240) not in set(opening.get_flattened_data())
    assert (240, 20, 20) in set(left_only.get_flattened_data())
    assert (20, 20, 240) not in set(left_only.get_flattened_data())
    assert (20, 20, 240) in set(both.get_flattened_data())
    assert left_only.crop((35, 650, 520, 750)).getbbox() is not None
    assert left_only.crop((560, 650, 1045, 750)).getextrema() == ((255, 255),) * 3
    assert both.crop((560, 650, 1045, 750)).getextrema() != ((255, 255),) * 3


def test_reference_renderer_keeps_legacy_products_visible_without_events(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGBA", (300, 400), (240, 20, 20, 255)).save(left)
    Image.new("RGBA", (300, 400), (20, 20, 240, 255)).save(right)
    audio.write_bytes(b"audio")
    spec = CompiledVideoSpec(
        left_label="Left",
        right_label="Right",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=TimedTranscript(duration_seconds=1.0),
    )

    frame = renderer.compose_frame(spec, 0.0)

    colors = set(frame.get_flattened_data())
    assert (240, 20, 20) in colors
    assert (20, 20, 240) in colors


def test_reference_renderer_uses_cubic_scale_and_fade_entrance(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    event = VisualEvent(kind=VisualEventKind.REVEAL_LEFT, start=1.0, duration_seconds=0.22)

    assert renderer.visual_event_progress(event, 0.99) == 0.0
    assert renderer.visual_event_progress(event, 1.0) == 0.0
    assert renderer.visual_event_progress(event, 1.11) == pytest.approx(0.875)
    assert renderer.visual_event_progress(event, 1.22) == 1.0
    assert renderer.entrance_scale(0.0) == 0.86
    assert renderer.entrance_scale(1.0) == 1.0


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
    alpha = card.getchannel("A")
    assert max(alpha.crop((0, card.height - 1, card.width, card.height)).get_flattened_data()) == 0
    assert card.height - alpha.getbbox()[3] >= 14


def test_production_cta_shrinks_instead_of_wrapping(monkeypatch, tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    class WideFont:
        def __init__(self, size: int):
            self.size = size

        def getbbox(self, text: str):
            return (0, 0, round(len(text) * self.size * 0.75), self.size)

    monkeypatch.setattr(
        "app.rendering.reference_renderer.load_font",
        lambda _path, size: WideFont(size),
    )
    text = renderer._cta_display_text("Like, share, follow")

    font, lines = renderer._bubble_lines(text)

    assert lines == ["LIKE · SHARE · FOLLOW"]
    assert measure_text(lines[0], font)[0] <= 760
    assert font.size < 60


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
    assert renderer.product_scale_at(spec, 0.18, Focus.LEFT) == 1.12
    assert renderer.product_scale_at(spec, 0.18, Focus.RIGHT) == 1.0
    assert renderer.mascot_x_at(spec, 0.09) < 540
    assert renderer.mascot_pivot_at(spec, 0.18) == (320.0, 1660.0)
    assert renderer.mascot_pivot_at(spec, 0.0) == (320.0, 1660.0)
    assert not renderer.cta_visible_at(spec, 0.499)
    assert not renderer.cta_visible_at(spec, 0.5)
    assert frame.crop((120, 700, 960, 920)).getbbox() is not None
    assert len(list(renderer.iter_frames(spec))) == math.ceil(0.5 * 30)


def test_reference_renderer_uses_a_dedicated_title_and_mascot_thumbnail(tmp_path: Path) -> None:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGBA", (800, 800), (255, 40, 40, 255)).save(left)
    Image.new("RGBA", (800, 800), (40, 40, 255, 255)).save(right)
    audio.write_bytes(b"audio")
    spec = CompiledVideoSpec(
        left_label="Ligament",
        right_label="Tendon",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=TimedTranscript(
            words=[TimedWord(word="Acum", start=0.0, end=0.5)],
            beats=[TimedBeat(id="b0", start=0.0, end=0.5, pause_end=0.5)],
            duration_seconds=0.5,
        ),
    )
    renderer = ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )

    frame = renderer.compose_thumbnail(spec)
    colors = set(frame.get_flattened_data())

    assert frame.size == (1080, 1920)
    assert (255, 40, 40) not in colors
    assert (40, 40, 255) not in colors
    assert (230, 130, 30) in colors
    assert frame.crop((80, 120, 1000, 500)).getbbox() is not None


def test_reference_video_never_injects_the_designed_thumbnail(tmp_path: Path) -> None:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    audio = tmp_path / "audio.wav"
    Image.new("RGBA", (800, 800), (255, 40, 40, 255)).save(left)
    Image.new("RGBA", (800, 800), (40, 40, 255, 255)).save(right)
    audio.write_bytes(b"audio")
    spec = CompiledVideoSpec(
        left_label="Ligament",
        right_label="Tendon",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=TimedTranscript(
            words=[TimedWord(word="Acum", start=0.0, end=0.5)],
            beats=[TimedBeat(id="b0", start=0.0, end=0.5, pause_end=0.5)],
            duration_seconds=0.5,
        ),
    )
    renderer = ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )

    final_frame = renderer.compose_frame(spec, spec.total_duration_seconds - 1 / spec.fps)

    assert (255, 40, 40) in set(final_frame.get_flattened_data())
    assert (40, 40, 255) in set(final_frame.get_flattened_data())


def test_thumbnail_uses_coiny_and_colored_layered_title(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)

    assert renderer._thumbnail_font_path.name == "Coiny-Regular.ttf"
    assert renderer._thumbnail_vs_font_path == renderer._cta_font_path
    assert renderer.thumbnail_left_color == (255, 196, 61)
    assert renderer.thumbnail_right_color == (104, 211, 176)
    assert renderer.thumbnail_shadow_color == (232, 117, 96)
    assert renderer.thumbnail_outline_color == (48, 36, 24)


def test_thumbnail_font_contains_every_romanian_letter(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    font = load_font(renderer._thumbnail_font_path, 100)

    for letter in "ĂăÂâÎîȘșȚț":
        assert font.getmask(letter).getbbox() is not None, letter


def test_thumbnail_long_romanian_object_names_fit_separate_regions(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    left = "Zarzără turcească extra coaptă"
    right = "Corcodușă românească tradițională"

    left_font, left_lines = renderer._thumbnail_label_layout(
        left.upper(),
        renderer.thumbnail_left_region,
    )
    right_font, right_lines = renderer._thumbnail_label_layout(
        right.upper(),
        renderer.thumbnail_right_region,
    )

    assert " ".join(left_lines) == left.upper()
    assert " ".join(right_lines) == right.upper()
    assert 1 <= len(left_lines) <= 2
    assert 1 <= len(right_lines) <= 2
    assert all(
        measure_text(line, left_font)[0] <= renderer.thumbnail_left_region.width
        for line in left_lines
    )
    assert all(
        measure_text(line, right_font)[0] <= renderer.thumbnail_right_region.width
        for line in right_lines
    )
    assert renderer.thumbnail_left_region.y2 < renderer.thumbnail_vs_region.y
    assert renderer.thumbnail_vs_region.y2 < renderer.thumbnail_right_region.y
    assert renderer.thumbnail_right_region.y2 < renderer.thumbnail_mascot_top


def test_ffmpeg_raw_encoder_command_accepts_rgb_frame_pipe(tmp_path: Path) -> None:
    command = FFmpegRunner().raw_video_command(1080, 1920, 30, tmp_path / "video.mp4")

    assert command[:6] == ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24"]
    assert "pipe:0" in command
    assert "libx264" in command


def test_ffmpeg_audio_mux_does_not_pad_a_thumbnail_tail(tmp_path: Path) -> None:
    runner = FFmpegRunner()
    commands: list[list[str]] = []
    runner._run = commands.append

    runner.mux_audio(
        tmp_path / "video.mp4",
        tmp_path / "audio.wav",
        tmp_path / "output.mp4",
    )

    assert "-shortest" in commands[0]
    assert "apad" not in commands[0]


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
    assert result.thumbnail_path is not None and result.thumbnail_path.exists()
    assert result.thumbnail_timestamp_ms == 467
    thumbnail_metadata = __import__("json").loads(
        (tmp_path / "output" / "thumbnail.json").read_text(encoding="utf-8")
    )
    assert thumbnail_metadata == {
        "thumbnail_path": "thumbnail.png",
        "thumbnail_offset_ms": 467,
    }
    assert result.contact_sheet_path.exists()
    assert result.timeline_path.exists()
    assert result.transcript_path is not None and result.transcript_path.exists()
