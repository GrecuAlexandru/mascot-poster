"""Validate that all mascot poses exist and meet the required format.

Usage:
    python scripts/validate_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.config import get_settings
from app.services.mascot_service import MascotService
from app.rendering.coordinates import load_template
from app.rendering.safe_zones import check_all_regions


def main() -> int:
    settings = get_settings()
    ok = True

    print("Validating mascot assets...")
    mascot_svc = MascotService(settings.mascots_dir)
    print(f"  Set: {mascot_svc.set_name}")
    print(f"  Canvas: {mascot_svc.canvas_size}")
    print(f"  Available poses: {mascot_svc.available_poses}")

    required = [
        "neutral", "intro_hands_up", "present_both",
        "point_left", "point_right", "point_up", "point_down",
        "point_up_left", "point_up_right",
        "two_fingers_up", "idea", "thinking",
        "surprised", "explaining", "compare_left_right",
        "thumbs_up", "warning", "shrug",
        "celebrate", "outro_wave", "magnifying_glass",
        "phone_in_hand", "arms_crossed", "reading_note",
    ]
    missing = mascot_svc.validate_poses(required)
    if missing:
        print(f"  MISSING POSES: {missing}")
        ok = False
    else:
        print("  All required poses present.")

    image_problems = mascot_svc.validate_pose_images(required)
    if image_problems:
        print("  IMAGE PROBLEMS:")
        for p in image_problems:
            print(f"    - {p}")
        ok = False
    else:
        print("  All pose images valid (RGBA, correct size).")

    print()
    print("Validating template regions...")
    for template_name in ["comparison_v1", "reference_v1"]:
        try:
            template = load_template(template_name, settings.templates_dir)
            problems = check_all_regions(template)
            if problems:
                print(f"  {template_name}: ISSUES FOUND")
                for p in problems:
                    print(f"    - {p}")
                ok = False
            else:
                print(f"  {template_name}: OK ({len(template.regions)} regions)")
        except Exception as e:
            print(f"  {template_name}: ERROR - {e}")
            ok = False

    print()
    if ok:
        print("All validations passed.")
        return 0
    else:
        print("Validation FAILED - see issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
