from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.config import Settings
from app.services.mascot_calibration_service import MascotCalibrationService
from app.services.mascot_service import MascotService


def test_calibration_contains_every_pose_and_fixed_dot() -> None:
    settings = Settings(_env_file=None)
    calibration = MascotCalibrationService(settings.mascots_dir).load()

    assert set(calibration.poses) == set(MascotService(settings.mascots_dir).available_poses)
    assert (calibration.reference_dot.x, calibration.reference_dot.y) == (540, 1670)


def test_render_all_creates_full_size_images_with_identical_dot(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    service = MascotCalibrationService(settings.mascots_dir)

    outputs = service.render_all(tmp_path)

    assert len(outputs) == 24
    for path in outputs.values():
        image = Image.open(path).convert("RGBA")
        assert image.size == (1080, 1920)
        assert image.getpixel((540, 1670)) == (255, 0, 90, 255)


def test_pose_adjustment_moves_pivot_without_moving_reference_dot(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)
    service = MascotCalibrationService(settings.mascots_dir)
    calibration = service.load()
    neutral = calibration.poses["neutral"]
    adjusted = neutral.model_copy(update={"x": neutral.x + 40, "scale": 1.1})

    original = service.render_pose("neutral", show_reference_dot=True)
    changed = service.render_pose(
        "neutral",
        show_reference_dot=True,
        pose_calibration=adjusted,
    )

    assert original.getpixel((540, 1670)) == changed.getpixel((540, 1670))
    assert original.tobytes() != changed.tobytes()


def test_neutral_and_pointing_poses_share_target_pivot() -> None:
    settings = Settings(_env_file=None)
    calibration = MascotCalibrationService(settings.mascots_dir).load()

    pivots = [
        calibration.poses[name]
        for name in ("neutral", "point_left", "point_right")
    ]

    assert {(pose.x, pose.y) for pose in pivots} == {(540.0, 1670.0)}
