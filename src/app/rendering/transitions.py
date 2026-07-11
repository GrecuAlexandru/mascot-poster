from __future__ import annotations

from app.domain.enums import ImageMotion, Transition


def _upscaled(width: int, height: int, factor: float) -> str:
    return f"scale={int(width * factor)}:{int(height * factor)}"


def zoompan_filter(
    motion: ImageMotion,
    duration_frames: int,
    width: int,
    height: int,
    fps: int,
) -> str:
    d = max(duration_frames, 1)
    s = f"d={d}:s={width}x{height}:fps={fps}"

    if motion == ImageMotion.SLOW_ZOOM_IN:
        step = 0.03 / d
        return f"{_upscaled(width, height, 1.04)},zoompan=z='1.0+{step:.8f}*on':{s}"

    if motion == ImageMotion.SLOW_ZOOM_OUT:
        step = -0.03 / d
        return f"{_upscaled(width, height, 1.04)},zoompan=z='1.03+{step:.8f}*on':{s}"

    if motion == ImageMotion.SLOW_PAN_LEFT:
        return (
            f"scale={int(width * 1.1)}:{height},"
            f"zoompan=z=1.0:x='iw-iw*on/{d}':y=0:{s}"
        )

    if motion == ImageMotion.SLOW_PAN_RIGHT:
        return (
            f"scale={int(width * 1.1)}:{height},"
            f"zoompan=z=1.0:x='iw*on/{d}-iw':y=0:{s}"
        )

    if motion == ImageMotion.PULSE:
        half = max(d // 2, 1)
        return (
            f"{_upscaled(width, height, 1.04)},"
            f"zoompan=z='1.0+0.02*sin(on/{half}*PI)':{s}"
        )

    return f"scale={width}:{height}"


def xfade_offset(prev_duration: float, transition: Transition) -> float | None:
    if transition == Transition.CUT:
        return None
    if transition == Transition.QUICK_FADE:
        return min(0.3, prev_duration * 0.3)
    if transition == Transition.CROSSFADE:
        return min(0.5, prev_duration * 0.4)
    if transition == Transition.FADE:
        return min(0.5, prev_duration * 0.4)
    if transition == Transition.SLIDE:
        return min(0.4, prev_duration * 0.3)
    return None
