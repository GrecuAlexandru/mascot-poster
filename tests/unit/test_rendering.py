from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.rendering.compositor import Compositor
from app.rendering.coordinates import Region, TemplateConfig, load_template, SafeZones, FontConfig, FocusHighlight
from app.rendering.safe_zones import check_all_regions, content_safe_area, is_inside_safe_area
from app.rendering.text_layout import fit_text, measure_text, wrap_text
from app.rendering.timeline import Timeline
from app.rendering.transitions import zoompan_filter, xfade_offset
from app.domain.enums import Focus, ImageMotion, MascotPose, Transition
from app.domain.models import SceneSpec


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
MASCOTS_DIR = PROJECT_ROOT / "assets" / "mascots" / "default"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


def make_template() -> TemplateConfig:
    return TemplateConfig(
        name="test",
        description="test",
        canvas_width=1080,
        canvas_height=1920,
        background_color=(18, 18, 24),
        regions={
            "title": Region(x=80, y=80, width=920, height=180),
            "left_label": Region(x=80, y=250, width=430, height=60),
            "right_label": Region(x=570, y=250, width=430, height=60),
            "left_image": Region(x=80, y=330, width=430, height=480),
            "right_image": Region(x=570, y=330, width=430, height=480),
            "phrase": Region(x=80, y=860, width=920, height=160),
            "mascot": Region(x=180, y=1080, width=720, height=720),
        },
        safe_zones=SafeZones(top_margin=40, bottom_margin=120, side_margin=40, right_ui_width=80),
        fonts={
            "title": FontConfig(size=64, color=(255, 255, 255)),
            "label": FontConfig(size=36, color=(220, 220, 230)),
            "phrase": FontConfig(size=72, color=(255, 210, 80)),
        },
        focus_highlight=FocusHighlight(color=(255, 210, 80), border_width=6, alpha=180),
    )


class TestRegion:
    def test_from_list(self):
        r = Region.from_list([10, 20, 100, 200])
        assert r.x == 10
        assert r.y == 20
        assert r.width == 100
        assert r.height == 200

    def test_x2_y2(self):
        r = Region(x=10, y=20, width=100, height=200)
        assert r.x2 == 110
        assert r.y2 == 220

    def test_center(self):
        r = Region(x=0, y=0, width=100, height=200)
        assert r.center == (50, 100)

    def test_shrink(self):
        r = Region(x=0, y=0, width=100, height=100)
        s = r.shrink(10)
        assert s.x == 10 and s.y == 10
        assert s.width == 80 and s.height == 80

    def test_shrink_min_size(self):
        r = Region(x=0, y=0, width=10, height=10)
        s = r.shrink(100)
        assert s.width >= 1 and s.height >= 1


class TestTemplateConfig:
    def test_load_template_from_file(self):
        t = load_template("comparison_v1", TEMPLATES_DIR)
        assert t.name == "comparison_v1"
        assert t.canvas_width == 1080
        assert t.canvas_height == 1920
        assert "title" in t.regions
        assert "mascot" in t.regions

    def test_region_lookup(self):
        t = make_template()
        r = t.region("title")
        assert r.width == 920

    def test_region_lookup_missing(self):
        t = make_template()
        try:
            t.region("nonexistent")
            assert False, "Should have raised KeyError"
        except KeyError:
            pass


class TestSafeZones:
    def test_content_safe_area(self):
        t = make_template()
        safe = content_safe_area(t)
        assert safe.x == 40
        assert safe.y == 40
        assert safe.x2 <= 1080 - 80
        assert safe.y2 <= 1920 - 120

    def test_is_inside_safe_area(self):
        t = make_template()
        inner = Region(x=100, y=100, width=800, height=800)
        assert is_inside_safe_area(inner, t)

    def test_is_outside_safe_area(self):
        t = make_template()
        outer = Region(x=0, y=0, width=1080, height=1920)
        assert not is_inside_safe_area(outer, t)

    def test_check_all_regions_clean(self):
        t = make_template()
        problems = check_all_regions(t)
        assert problems == []

    def test_check_all_regions_with_problem(self):
        t = make_template()
        t2 = TemplateConfig(
            name=t.name, description=t.description,
            canvas_width=t.canvas_width, canvas_height=t.canvas_height,
            background_color=t.background_color,
            regions={"bad": Region(x=0, y=0, width=1080, height=1920)},
            safe_zones=t.safe_zones, fonts=t.fonts, focus_highlight=t.focus_highlight,
        )
        problems = check_all_regions(t2)
        assert len(problems) == 1


class TestTextLayout:
    def test_measure_text(self):
        from app.rendering.text_layout import load_font
        font = load_font(None, 36)
        w, h = measure_text("Hello", font)
        assert w > 0
        assert h > 0

    def test_wrap_text_short(self):
        from app.rendering.text_layout import load_font
        font = load_font(None, 36)
        lines = wrap_text("Hello", font, 1000, 2)
        assert lines == ["Hello"]

    def test_wrap_text_long(self):
        from app.rendering.text_layout import load_font
        font = load_font(None, 36)
        long_text = " ".join(["word"] * 30)
        lines = wrap_text(long_text, font, 200, 2)
        assert len(lines) <= 2

    def test_fit_text_reduces_size(self):
        region = Region(x=0, y=0, width=100, height=30)
        font, lines, size = fit_text("Very long text that won't fit", region, None, 72, 12, 2)
        assert size <= 72
        assert len(lines) <= 2


class TestTimeline:
    def _scenes(self) -> list[SceneSpec]:
        return [
            SceneSpec(start=0.0, end=4.0, pose=MascotPose.NEUTRAL, phrase="A"),
            SceneSpec(start=4.0, end=10.0, pose=MascotPose.POINT_LEFT, phrase="B"),
            SceneSpec(start=10.0, end=16.0, pose=MascotPose.THUMBS_UP, phrase="C"),
        ]

    def test_from_scenes(self):
        tl = Timeline.from_scenes(self._scenes(), fps=30)
        assert len(tl.entries) == 3
        assert tl.total_duration == 16.0
        assert tl.total_frames == 480

    def test_to_dict(self):
        tl = Timeline.from_scenes(self._scenes(), fps=30)
        d = tl.to_dict()
        assert d["total_duration_seconds"] == 16.0
        assert d["fps"] == 30
        assert len(d["scenes"]) == 3
        assert d["scenes"][0]["pose"] == "neutral"
        assert d["scenes"][2]["phrase"] == "C"

    def test_empty_scenes(self):
        tl = Timeline.from_scenes([], fps=30)
        assert tl.total_duration == 0.0
        assert tl.total_frames == 0


class TestTransitions:
    def test_zoompan_slow_zoom_in(self):
        f = zoompan_filter(ImageMotion.SLOW_ZOOM_IN, 120, 1080, 1920, 30)
        assert "zoompan" in f
        assert "z=" in f
        assert "1080x1920" in f

    def test_zoompan_none(self):
        f = zoompan_filter(ImageMotion.NONE, 120, 1080, 1920, 30)
        assert "scale=1080:1920" in f

    def test_zoompan_pulse(self):
        f = zoompan_filter(ImageMotion.PULSE, 120, 1080, 1920, 30)
        assert "sin" in f

    def test_xfade_offset_cut(self):
        assert xfade_offset(4.0, Transition.CUT) is None

    def test_xfade_offset_fade(self):
        d = xfade_offset(4.0, Transition.FADE)
        assert d is not None
        assert 0 < d <= 1.6

    def test_xfade_offset_quick_fade(self):
        d = xfade_offset(4.0, Transition.QUICK_FADE)
        assert d is not None
        assert d <= 1.2


class TestSceneSpec:
    def test_duration(self):
        s = SceneSpec(start=2.0, end=7.0, pose=MascotPose.NEUTRAL)
        assert s.duration == 5.0

    def test_end_before_start_fails(self):
        import pytest
        with pytest.raises(Exception):
            SceneSpec(start=5.0, end=3.0, pose=MascotPose.NEUTRAL)


class TestCompositor:
    def test_compose_frame(self):
        template = make_template()
        compositor = Compositor(template, font_path=None)
        from app.domain.models import RenderSpec
        spec = RenderSpec(
            title="Test Title",
            left_label="Left",
            right_label="Right",
            left_image=FIXTURES_DIR / "left.png",
            right_image=FIXTURES_DIR / "right.png",
            audio=FIXTURES_DIR / "narration.mp3",
            scenes=[
                SceneSpec(start=0.0, end=4.0, pose=MascotPose.POINT_UP, phrase="HELLO", focus=Focus.BOTH),
            ],
        )
        frame = compositor.compose_frame(spec, spec.scenes[0])
        assert frame.size == (1080, 1920)
        assert frame.mode == "RGB"

    def test_contact_sheet(self):
        template = make_template()
        compositor = Compositor(template, font_path=None)
        frames = [
            FIXTURES_DIR / "left.png",
            FIXTURES_DIR / "right.png",
        ]
        sheet = compositor.create_contact_sheet(frames, cols=2, thumb_width=360)
        assert sheet.mode == "RGB"
        assert sheet.width > 0
        assert sheet.height > 0


class TestMascotService:
    def test_load_and_validate(self):
        from app.services.mascot_service import MascotService
        svc = MascotService(MASCOTS_DIR)
        assert svc.set_name == "default_mascot"
        assert svc.canvas_size == (768, 768)
        required = ["neutral", "point_left", "point_right", "thumbs_up"]
        missing = svc.validate_poses(required)
        assert missing == []

    def test_pose_path(self):
        from app.services.mascot_service import MascotService
        svc = MascotService(MASCOTS_DIR)
        path = svc.pose_path("neutral")
        assert path is not None
        assert path.exists()

    def test_missing_pose(self):
        from app.services.mascot_service import MascotService
        svc = MascotService(MASCOTS_DIR)
        missing = svc.validate_poses(["nonexistent_pose"])
        assert len(missing) == 1
