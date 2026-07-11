from __future__ import annotations

from app.rendering.coordinates import Region, TemplateConfig


def content_safe_area(template: TemplateConfig) -> Region:
    sz = template.safe_zones
    return Region(
        x=sz.side_margin,
        y=sz.top_margin,
        width=max(1, template.canvas_width - sz.side_margin - sz.right_ui_width),
        height=max(
            1,
            template.canvas_height - sz.top_margin - sz.bottom_margin,
        ),
    )


def is_inside_safe_area(region: Region, template: TemplateConfig) -> bool:
    safe = content_safe_area(template)
    return (
        region.x >= safe.x
        and region.y >= safe.y
        and region.x2 <= safe.x2
        and region.y2 <= safe.y2
    )


def check_all_regions(template: TemplateConfig) -> list[str]:
    problems: list[str] = []
    for name, region in template.regions.items():
        if not is_inside_safe_area(region, template):
            problems.append(
                f"Region '{name}' ({region}) extends outside safe area"
                f" of template '{template.name}'"
            )
    return problems
