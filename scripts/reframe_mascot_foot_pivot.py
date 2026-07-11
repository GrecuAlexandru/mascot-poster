import json
from pathlib import Path
from typing import Any

from PIL import Image


def with_padding(
    bounds: list[int], image: Image.Image, padding: int
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )


def reframe(pose: dict[str, Any], canvas: dict[str, Any], source: Image.Image) -> Image.Image:
    left, top, right, bottom = with_padding(pose["crop"], source, canvas["crop_padding"])
    crop = source.crop((left, top, right, bottom)).convert("RGBA")
    background = crop.getpixel((0, 0))
    scale = pose["scale"]
    if scale <= 0:
        raise ValueError("Pose scale must be greater than zero.")
    scaled_crop = crop.resize(
        (round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS
    )
    output = Image.new("RGBA", (canvas["width"], canvas["height"]), background)
    pivot_x = (pose["foot_pivot"][0] - left) * scale
    pivot_y = (pose["foot_pivot"][1] - top) * scale
    output.paste(
        scaled_crop,
        (
            round(canvas["foot_pivot"][0] + pose["offset"][0] - pivot_x),
            round(canvas["foot_pivot"][1] + pose["offset"][1] - pivot_y),
        ),
    )
    return output


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config_dir = root / "assets" / "mascot_poses_foot_pivot"
    output_dir = root / "assets" / "mascots" / "default"
    with (config_dir / "layout.json").open(encoding="utf-8") as config_file:
        layout = json.load(config_file)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources: dict[str, Image.Image] = {}
    try:
        for name, pose in layout["poses"].items():
            source_name = pose["source"]
            if source_name not in sources:
                sources[source_name] = Image.open(root / source_name)
            reframe(pose, layout["canvas"], sources[source_name]).save(
                output_dir / f"{name}.png", format="PNG"
            )
    finally:
        for source in sources.values():
            source.close()


if __name__ == "__main__":
    main()
