from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.services.mascot_calibration_service import MascotCalibrationService


def create_contact_sheet(outputs: dict[str, Path], output_path: Path) -> Path:
    thumb_width = 216
    thumb_height = 384
    columns = 6
    rows = (len(outputs) + columns - 1) // columns
    padding = 12
    sheet = Image.new(
        "RGB",
        (
            columns * thumb_width + (columns + 1) * padding,
            rows * thumb_height + (rows + 1) * padding,
        ),
        "white",
    )
    for index, (pose, path) in enumerate(outputs.items()):
        image = Image.open(path).convert("RGB").resize(
            (thumb_width, thumb_height),
            Image.Resampling.LANCZOS,
        )
        x = padding + index % columns * (thumb_width + padding)
        y = padding + index // columns * (thumb_height + padding)
        sheet.paste(image, (x, y))
        ImageDraw.Draw(sheet).text((x + 8, y + 8), pose, fill=(10, 10, 10))
    sheet.save(output_path, quality=92)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mascot-dir",
        type=Path,
        default=PROJECT_ROOT / "assets" / "mascots" / "default",
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "mascot_calibration",
    )
    args = parser.parse_args()
    service = MascotCalibrationService(args.mascot_dir, args.config)
    calibration = service.load()
    outputs = service.render_all(args.output)
    create_contact_sheet(outputs, args.output / "contact-sheet.jpg")
    index = {
        "canvas": calibration.canvas.model_dump(),
        "reference_dot": calibration.reference_dot.model_dump(),
        "source_pivot": calibration.source_pivot.model_dump(),
        "base_render_height": calibration.base_render_height,
        "poses": {
            pose: {
                **calibration.poses[pose].model_dump(),
                "output": str(path),
            }
            for pose, path in outputs.items()
        },
    }
    (args.output / "calibration-index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Generated {len(outputs)} calibration images in {args.output}")
    print(f"Reference dot: ({calibration.reference_dot.x:.0f}, {calibration.reference_dot.y:.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
