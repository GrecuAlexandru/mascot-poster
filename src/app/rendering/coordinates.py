from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.exceptions import TemplateNotFoundError


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def shrink(self, margin: int) -> "Region":
        return Region(
            x=self.x + margin,
            y=self.y + margin,
            width=max(1, self.width - 2 * margin),
            height=max(1, self.height - 2 * margin),
        )

    @classmethod
    def from_list(cls, data: list[int]) -> "Region":
        return cls(x=data[0], y=data[1], width=data[2], height=data[3])


@dataclass(frozen=True)
class SafeZones:
    top_margin: int
    bottom_margin: int
    side_margin: int
    right_ui_width: int


@dataclass(frozen=True)
class FontConfig:
    size: int
    color: tuple[int, int, int]


@dataclass(frozen=True)
class FocusHighlight:
    color: tuple[int, int, int]
    border_width: int
    alpha: int


@dataclass(frozen=True)
class TemplateConfig:
    name: str
    description: str
    canvas_width: int
    canvas_height: int
    background_color: tuple[int, int, int]
    regions: dict[str, Region]
    safe_zones: SafeZones
    fonts: dict[str, FontConfig]
    focus_highlight: FocusHighlight

    def region(self, name: str) -> Region:
        if name not in self.regions:
            raise KeyError(f"Region '{name}' not found in template '{self.name}'")
        return self.regions[name]

    @classmethod
    def from_file(cls, path: Path) -> "TemplateConfig":
        if not path.exists():
            raise TemplateNotFoundError(f"Template file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateConfig":
        bg = data.get("background", {})
        bg_color = tuple(bg.get("color", [18, 18, 24]))

        regions_data = data.get("regions", {})
        regions = {
            name: Region.from_list(coords) for name, coords in regions_data.items()
        }

        sz = data.get("safe_zones", {})
        safe_zones = SafeZones(
            top_margin=sz.get("top_margin", 80),
            bottom_margin=sz.get("bottom_margin", 220),
            side_margin=sz.get("side_margin", 60),
            right_ui_width=sz.get("right_ui_width", 120),
        )

        fonts_data = data.get("fonts", {})
        fonts: dict[str, FontConfig] = {}
        for name, cfg in fonts_data.items():
            color = tuple(cfg.get("color", [255, 255, 255]))
            fonts[name] = FontConfig(size=cfg.get("size", 36), color=color)

        fh = data.get("focus_highlight", {})
        fh_color = tuple(fh.get("color", [255, 210, 80]))
        focus_highlight = FocusHighlight(
            color=fh_color,
            border_width=fh.get("border_width", 6),
            alpha=fh.get("alpha", 180),
        )

        canvas = data.get("canvas", {})
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            canvas_width=canvas.get("width", 1080),
            canvas_height=canvas.get("height", 1920),
            background_color=bg_color,
            regions=regions,
            safe_zones=safe_zones,
            fonts=fonts,
            focus_highlight=focus_highlight,
        )


def load_template(name: str, templates_dir: Path) -> TemplateConfig:
    path = templates_dir / f"{name}.json"
    return TemplateConfig.from_file(path)
