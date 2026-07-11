"""Generate placeholder test fixtures: mascot PNGs, sample comparison images, narration audio.

Run after a fresh clone to populate assets/ and tests/fixtures/.
"""
from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASCOT_DIR = PROJECT_ROOT / "assets" / "mascots" / "default"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"

CANVAS_W = 1080
CANVAS_H = 1920
MASCOT_W = 1024
MASCOT_H = 1024


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ["C:\\Windows\\Fonts\\arialbd.ttf", "C:\\Windows\\Fonts\\arial.ttf"]:
        p = Path(candidate)
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def generate_mascot_pose(name: str, output_path: Path) -> None:
    img = Image.new("RGBA", (MASCOT_W, MASCOT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = MASCOT_W // 2, MASCOT_H // 2 + 100
    body_color = (100, 180, 255, 255)
    accent_color = (255, 210, 80, 255)
    outline = (40, 40, 60, 255)

    body_w = 400
    body_h = 480

    draw.ellipse(
        [cx - body_w // 2, cy - body_h // 2, cx + body_w // 2, cy + body_h // 2],
        fill=body_color, outline=outline, width=6
    )

    head_r = 160
    head_y = cy - body_h // 2 - head_r + 60
    draw.ellipse(
        [cx - head_r, head_y - head_r, cx + head_r, head_y + head_r],
        fill=body_color, outline=outline, width=6
    )

    eye_y = head_y - 20
    draw.ellipse([cx - 55, eye_y - 25, cx - 15, eye_y + 25], fill=(255, 255, 255, 255))
    draw.ellipse([cx + 15, eye_y - 25, cx + 55, eye_y + 25], fill=(255, 255, 255, 255))
    draw.ellipse([cx - 45, eye_y - 15, cx - 25, eye_y + 15], fill=(20, 20, 40, 255))
    draw.ellipse([cx + 25, eye_y - 15, cx + 45, eye_y + 15], fill=(20, 20, 40, 255))

    if name == "point_left":
        for sy in range(eye_y - 15, eye_y + 15):
            draw.line([(cx - 35, sy), (cx - 25, sy)], fill=(20, 20, 40, 255), width=1)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="left")
    elif name == "point_right":
        for sy in range(eye_y - 15, eye_y + 15):
            draw.line([(cx + 25, sy), (cx + 35, sy)], fill=(20, 20, 40, 255), width=1)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="right")
    elif name == "point_up":
        draw.line([(cx - 35, eye_y), (cx - 20, eye_y - 15)], fill=(20, 20, 40, 255), width=3)
        draw.line([(cx + 20, eye_y - 15), (cx + 35, eye_y)], fill=(20, 20, 40, 255), width=3)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="up")
    elif name == "point_down":
        draw.arc([cx - 40, eye_y - 20, cx + 40, eye_y + 40], 0, 180, fill=(20, 20, 40, 255), width=5)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="down")
    elif name == "thinking":
        draw.line([(cx - 35, eye_y + 5), (cx - 20, eye_y - 10)], fill=(20, 20, 40, 255), width=3)
        draw.line([(cx + 20, eye_y - 10), (cx + 35, eye_y + 5)], fill=(20, 20, 40, 255), width=3)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="thinking")
    elif name == "surprised":
        draw.ellipse([cx - 40, eye_y - 15, cx - 15, eye_y + 20], fill=(20, 20, 40, 255))
        draw.ellipse([cx + 15, eye_y - 15, cx + 40, eye_y + 20], fill=(20, 20, 40, 255))
        draw.ellipse([cx - 25, head_y + 20, cx + 25, head_y + 60], fill=(40, 20, 40, 255), outline=outline, width=3)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="up")
    elif name == "warning":
        for i in range(0, 360, 45):
            rad = math.radians(i)
            x1 = cx + int(40 * math.cos(rad))
            y1 = eye_y + int(20 * math.sin(rad))
            x2 = cx + int(15 * math.cos(rad))
            y2 = eye_y + int(8 * math.sin(rad))
            draw.line([(x1, y1), (x2, y2)], fill=(255, 60, 60, 255), width=4)
        draw.rectangle([cx - 20, head_y + 15, cx + 20, head_y + 45], fill=(40, 20, 40, 255))
        _draw_arms(draw, cx, cy, body_w, body_h, direction="crossed")
    elif name == "thumbs_up":
        draw.arc([cx - 30, eye_y - 15, cx + 30, eye_y + 20], 0, 180, fill=(20, 20, 40, 255), width=4)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="thumbs_up")
    elif name == "arms_open":
        draw.arc([cx - 40, eye_y - 10, cx + 40, eye_y + 30], 0, 180, fill=(20, 20, 40, 255), width=5)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="open")
    elif name == "hands_up":
        draw.arc([cx - 35, eye_y - 10, cx + 35, eye_y + 25], 0, 180, fill=(20, 20, 40, 255), width=4)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="up")
    else:  # neutral
        draw.line([(cx - 35, eye_y), (cx - 15, eye_y)], fill=(20, 20, 40, 255), width=3)
        draw.line([(cx + 15, eye_y), (cx + 35, eye_y)], fill=(20, 20, 40, 255), width=3)
        draw.arc([cx - 30, head_y + 10, cx + 30, head_y + 50], 0, 180, fill=(20, 20, 40, 255), width=4)
        _draw_arms(draw, cx, cy, body_w, body_h, direction="down")

    color = _pose_label_color(name)
    label_font = _get_font(32)
    bbox = label_font.getbbox(name)
    lw = bbox[2] - bbox[0]
    draw.rounded_rectangle(
        [cx - lw // 2 - 20, MASCOT_H - 80, cx + lw // 2 + 20, MASCOT_H - 20],
        radius=12, fill=(20, 20, 30, 200)
    )
    draw.text(
        (cx - lw // 2, MASCOT_H - 75),
        name, font=label_font, fill=(*color, 255),
    )

    img.save(str(output_path))


def _pose_label_color(name: str) -> tuple[int, int, int]:
    if name in ("warning",):
        return (255, 80, 80)
    if name in ("surprised",):
        return (255, 180, 60)
    if name in ("thumbs_up", "point_up"):
        return (100, 255, 100)
    return (200, 200, 220)


def _draw_arms(draw, cx, cy, body_w, body_h, direction="down") -> None:
    outline = (40, 40, 60, 255)
    arm_color = (100, 180, 255, 255)
    aw = 50
    sh_y = cy - body_h // 2 + 80
    sh_x = body_w // 2 - 30

    if direction == "down":
        draw.ellipse([cx - sh_x - aw, sh_y, cx - sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw, sh_y, cx + sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
    elif direction == "up":
        draw.ellipse([cx - sh_x - aw, sh_y - 200, cx - sh_x + aw, sh_y + 50], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw, sh_y - 200, cx + sh_x + aw, sh_y + 50], fill=arm_color, outline=outline, width=4)
    elif direction == "left":
        draw.ellipse([cx - sh_x - aw - 120, sh_y - 50, cx - sh_x + aw - 120, sh_y + 200], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw, sh_y, cx + sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
    elif direction == "right":
        draw.ellipse([cx - sh_x - aw, sh_y, cx - sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw + 120, sh_y - 50, cx + sh_x + aw + 120, sh_y + 200], fill=arm_color, outline=outline, width=4)
    elif direction == "open":
        draw.ellipse([cx - sh_x - aw - 150, sh_y + 50, cx - sh_x + aw - 150, sh_y + 300], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw + 150, sh_y + 50, cx + sh_x + aw + 150, sh_y + 300], fill=arm_color, outline=outline, width=4)
    elif direction == "thinking":
        draw.ellipse([cx - sh_x - aw, sh_y, cx - sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw, sh_y - 100, cx + sh_x + aw, sh_y - 10], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - 60, sh_y - 180, cx + sh_x + 60, sh_y - 60], fill=arm_color, outline=outline, width=4)
    elif direction == "crossed":
        draw.line([(cx - sh_x, sh_y), (cx + 40, sh_y + 200)], fill=arm_color, width=aw)
        draw.line([(cx + sh_x, sh_y), (cx - 40, sh_y + 200)], fill=arm_color, width=aw)
    elif direction == "thumbs_up":
        draw.ellipse([cx - sh_x - aw, sh_y, cx - sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw + 80, sh_y + 50, cx + sh_x + aw + 80, sh_y + 150], fill=arm_color, outline=outline, width=4)
        x0 = cx + sh_x + aw + 80
        y0 = sh_y + 150
        draw.ellipse([x0 - 30, y0 - 120, x0 + 30, y0 - 10], fill=accent_color if False else arm_color, outline=outline, width=4)
    else:
        draw.ellipse([cx - sh_x - aw, sh_y, cx - sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)
        draw.ellipse([cx + sh_x - aw, sh_y, cx + sh_x + aw, sh_y + 250], fill=arm_color, outline=outline, width=4)


def generate_mascots() -> None:
    MASCOT_DIR.mkdir(parents=True, exist_ok=True)
    poses = [
        "neutral", "point_left", "point_right", "point_up", "point_down",
        "arms_open", "hands_up", "thinking", "surprised", "warning", "thumbs_up",
    ]
    for pose in poses:
        path = MASCOT_DIR / f"{pose}.png"
        generate_mascot_pose(pose, path)
        print(f"  mascot: {path.name}")

    meta = {
        "set_name": "default_mascot",
        "canvas_width": MASCOT_W,
        "canvas_height": MASCOT_H,
        "poses": {p: f"{p}.png" for p in poses},
    }
    meta_path = MASCOT_DIR / "mascot_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  mascot meta: {meta_path.name}")


def generate_sample_image(
    filename: str,
    label: str,
    bg_color: tuple[int, int, int],
    accent_color: tuple[int, int, int],
) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (600, 600), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([20, 20, 580, 580], radius=30, fill=(*bg_color, 255))

    draw.rounded_rectangle([60, 60, 540, 300], radius=20, fill=(*accent_color, 255))

    draw.ellipse([180, 330, 420, 540], fill=(*accent_color, 200), outline=(*bg_color, 255), width=5)

    font = _get_font(42)
    bbox = font.getbbox(label)
    lw = bbox[2] - bbox[0]
    draw.text(
        ((600 - lw) // 2, 425),
        label, font=font, fill=(255, 255, 255, 255),
    )

    path = FIXTURES_DIR / filename
    img.save(str(path))
    print(f"  fixture: {path.name}")


def generate_narration_audio(duration_seconds: float = 60.0) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    output_path = FIXTURES_DIR / "narration.mp3"

    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", f"{duration_seconds:.1f}",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sample_rate = 44100
        num_samples = int(duration_seconds * sample_rate)
        wav_path = FIXTURES_DIR / "narration.wav"
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for i in range(num_samples):
                t = i / sample_rate
                freq = 220 + 110 * math.sin(2 * math.pi * 0.1 * t)
                val = int(8000 * math.sin(2 * math.pi * freq * t) *
                          (0.5 + 0.5 * math.sin(2 * math.pi * 0.05 * t)))
                wav.writeframes(struct.pack("<h", val))
        cmd2 = ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(output_path)]
        subprocess.run(cmd2, capture_output=True)
        wav_path.unlink(missing_ok=True)

    print(f"  fixture: {output_path.name}")


def generate_sample_scene_json() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    scenes = [
        {"start": 0.0, "end": 4.0, "pose": "intro_hands_up", "phrase": "THEY LOOK SIMILAR", "focus": "both",
         "image_motion": "slow_zoom_in", "transition": "fade"},
        {"start": 4.0, "end": 10.0, "pose": "point_left", "phrase": "NATURAL VANILLA", "focus": "left",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 10.0, "end": 14.0, "pose": "thinking", "phrase": "", "focus": "both",
         "image_motion": "slow_pan_right", "transition": "quick_fade"},
        {"start": 14.0, "end": 22.0, "pose": "point_right", "phrase": "ARTIFICIAL VANILLIN", "focus": "right",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 22.0, "end": 28.0, "pose": "compare_left_right", "phrase": "KEY DIFFERENCE", "focus": "both",
         "image_motion": "slow_zoom_out", "transition": "crossfade"},
        {"start": 28.0, "end": 36.0, "pose": "point_left", "phrase": "REAL BEANS", "focus": "left",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 36.0, "end": 42.0, "pose": "warning", "phrase": "CHECK LABELS", "focus": "both",
         "image_motion": "slow_pan_left", "transition": "quick_fade"},
        {"start": 42.0, "end": 50.0, "pose": "point_right", "phrase": "CHEAPER OPTION", "focus": "right",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 50.0, "end": 56.0, "pose": "surprised", "phrase": "NOT THE SAME!", "focus": "both",
         "image_motion": "pulse", "transition": "crossfade"},
        {"start": 56.0, "end": 60.0, "pose": "thumbs_up", "phrase": "CHOOSE WISELY", "focus": "both",
         "image_motion": "slow_zoom_in", "transition": "fade"},
    ]

    spec = {
        "title": "Vanilla sugar vs vanillin sugar",
        "left_label": "Vanilla sugar",
        "right_label": "Vanillin sugar",
        "left_image": "tests/fixtures/left.png",
        "right_image": "tests/fixtures/right.png",
        "audio": "tests/fixtures/narration.mp3",
        "template": "comparison_v1",
        "mascot_set": "default",
        "scenes": scenes,
    }

    path = FIXTURES_DIR / "render_sample.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"  fixture: {path.name}")


def NARRATION_TEXT() -> str:
    return (
        "Vanilla sugar and vanillin sugar. They look almost identical, "
        "but they are not the same thing. "
        "Vanilla sugar is made with real vanilla beans, "
        "which contain natural vanillin extracted from the orchid pod. "
        "Vanillin sugar, on the other hand, uses artificial vanillin, "
        "a synthetic compound that mimics the flavor of real vanilla. "
        "The difference matters. Natural vanilla has over two hundred flavor compounds, "
        "while artificial vanillin only provides one. "
        "That is why vanilla sugar tastes richer and more complex. "
        "Vanillin sugar is cheaper, but the flavor is simpler. "
        "So check the labels carefully. "
        "If it says vanilla, you are getting the real thing. "
        "If it says vanillin, it is artificial. "
        "They may look similar, but choose wisely."
    )


def generate_narration_script() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / "narration_script.json"
    script = {
        "narration_text": NARRATION_TEXT(),
        "estimated_words": len(NARRATION_TEXT().split()),
        "estimated_duration_seconds": 60.0,
        "language": "en",
    }
    path.write_text(json.dumps(script, indent=2), encoding="utf-8")
    print(f"  fixture: {path.name}")


def generate_tts_render_spec() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    scenes = [
        {"start": 0.0, "end": 4.0, "pose": "intro_hands_up", "phrase": "THEY LOOK SIMILAR", "focus": "both",
         "image_motion": "slow_zoom_in", "transition": "fade"},
        {"start": 4.0, "end": 10.0, "pose": "point_left", "phrase": "NATURAL VANILLA", "focus": "left",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 10.0, "end": 14.0, "pose": "thinking", "phrase": "", "focus": "both",
         "image_motion": "slow_pan_right", "transition": "quick_fade"},
        {"start": 14.0, "end": 22.0, "pose": "point_right", "phrase": "ARTIFICIAL VANILLIN", "focus": "right",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 22.0, "end": 28.0, "pose": "compare_left_right", "phrase": "KEY DIFFERENCE", "focus": "both",
         "image_motion": "slow_zoom_out", "transition": "crossfade"},
        {"start": 28.0, "end": 36.0, "pose": "point_left", "phrase": "REAL BEANS", "focus": "left",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 36.0, "end": 42.0, "pose": "warning", "phrase": "CHECK LABELS", "focus": "both",
         "image_motion": "slow_pan_left", "transition": "quick_fade"},
        {"start": 42.0, "end": 50.0, "pose": "point_right", "phrase": "CHEAPER OPTION", "focus": "right",
         "image_motion": "slow_zoom_in", "transition": "quick_fade"},
        {"start": 50.0, "end": 56.0, "pose": "surprised", "phrase": "NOT THE SAME!", "focus": "both",
         "image_motion": "pulse", "transition": "crossfade"},
        {"start": 56.0, "end": 60.0, "pose": "thumbs_up", "phrase": "CHOOSE WISELY", "focus": "both",
         "image_motion": "slow_zoom_in", "transition": "fade"},
    ]

    spec = {
        "title": "Vanilla sugar vs vanillin sugar",
        "left_label": "Vanilla sugar",
        "right_label": "Vanillin sugar",
        "left_image": "tests/fixtures/left.png",
        "right_image": "tests/fixtures/right.png",
        "audio": "tests/fixtures/narration.mp3",
        "template": "comparison_v1",
        "mascot_set": "default",
        "narration_text": NARRATION_TEXT(),
        "scenes": scenes,
    }

    path = FIXTURES_DIR / "render_tts_sample.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"  fixture: {path.name}")


def main() -> None:
    print("Generating fixtures...")
    if not (MASCOT_DIR / "neutral.png").exists():
        print("  Mascot PNGs not found, generating placeholders...")
        generate_mascots()
    else:
        print("  Mascot PNGs already exist, skipping generation.")
    generate_sample_image("left.png", "VANILLA", (80, 120, 60), (180, 220, 100))
    generate_sample_image("right.png", "VANILLIN", (120, 80, 60), (255, 180, 80))
    generate_narration_audio(60.0)
    generate_sample_scene_json()
    generate_narration_script()
    generate_tts_render_spec()
    print("Done.")


if __name__ == "__main__":
    main()
