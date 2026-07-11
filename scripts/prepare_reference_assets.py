from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.services.mascot_asset_preparer import MascotAssetPreparer
from app.services.sfx_service import SfxLibraryService


def prepare_mascots(mascot_dir: Path) -> int:
    mascot_dir = mascot_dir.resolve()
    workspace = PROJECT_ROOT.resolve()
    if workspace not in mascot_dir.parents:
        raise ValueError(f"Mascot directory must be inside {workspace}")
    meta_path = mascot_dir / "mascot_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    staging = (mascot_dir.parent / f".{mascot_dir.name}_prepared").resolve()
    if mascot_dir.parent != staging.parent:
        raise ValueError("Invalid mascot staging directory")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    preparer = MascotAssetPreparer(
        canvas_size=(meta.get("canvas_width", 768), meta.get("canvas_height", 768)),
        padding=24,
    )
    for filename in meta.get("poses", {}).values():
        preparer.prepare(mascot_dir / filename, staging / filename)
    meta["alpha_prepared"] = True
    meta["foot_pivot_y"] = meta.get("canvas_height", 768) - 24
    (staging / "mascot_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    for filename in [*meta.get("poses", {}).values(), "mascot_meta.json"]:
        shutil.move(str(staging / filename), str(mascot_dir / filename))
    staging.rmdir()
    return len(meta.get("poses", {}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mascot-dir", type=Path, default=PROJECT_ROOT / "assets" / "mascots" / "default")
    parser.add_argument("--sfx-dir", type=Path, default=PROJECT_ROOT / "assets" / "sfx")
    args = parser.parse_args()
    mascot_count = prepare_mascots(args.mascot_dir)
    sfx_paths = SfxLibraryService().ensure_library(args.sfx_dir)
    print(f"Prepared {mascot_count} mascot poses")
    print(f"Generated {len(sfx_paths)} sound effects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
