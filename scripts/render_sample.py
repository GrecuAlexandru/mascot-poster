"""Phase 1/2 deliverable: render a complete vertical comparison video from a JSON spec.

Phase 1: Fixed audio + scene JSON → video
Phase 2: Optional TTS narration + audio mixing + alignment

Usage:
    python scripts/render_sample.py
    python scripts/render_sample.py --spec path/to/spec.json
    python scripts/render_sample.py --output path/to/output_dir
    python scripts/render_sample.py --tts --voice-id <id>  (requires ELEVENLABS_API_KEY)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.config import get_settings
from app.domain.models import RenderSpec
from app.services.render_service import RenderService


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a comparison video from a JSON spec")
    parser.add_argument(
        "--spec",
        type=Path,
        default=PROJECT_ROOT / "tests" / "fixtures" / "render_sample.json",
        help="Path to the render spec JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output",
        help="Output directory for rendered video and artifacts",
    )
    parser.add_argument(
        "--tts",
        action="store_true",
        help="Generate narration via TTS (requires ELEVENLABS_API_KEY env var)",
    )
    parser.add_argument(
        "--voice-id",
        type=str,
        default=None,
        help="ElevenLabs voice ID for TTS narration",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        help="Narration language code (en, ro, etc.)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("render_sample")

    if not args.spec.exists():
        logger.error(f"Spec file not found: {args.spec}")
        logger.info("Run 'python scripts/generate_fixtures.py' to create test fixtures first.")
        return 1

    logger.info(f"Loading spec: {args.spec}")
    spec_data = json.loads(args.spec.read_text(encoding="utf-8"))

    for key in ("left_image", "right_image", "audio"):
        if key in spec_data and not Path(spec_data[key]).is_absolute():
            spec_data[key] = str(PROJECT_ROOT / spec_data[key])
    if "background_music" in spec_data and spec_data["background_music"] and not Path(spec_data["background_music"]).is_absolute():
        spec_data["background_music"] = str(PROJECT_ROOT / spec_data["background_music"])
    if "sfx_paths" in spec_data:
        spec_data["sfx_paths"] = [
            str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
            for p in spec_data["sfx_paths"]
        ]

    if args.tts:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            logger.error("ELEVENLABS_API_KEY not set. Cannot use --tts.")
            return 1
        voice_id = args.voice_id or os.environ.get("ELEVENLABS_VOICE_ID_EN", "")
        if not voice_id:
            logger.error("No voice ID provided. Use --voice-id or set ELEVENLABS_VOICE_ID_EN.")
            return 1

        spec_data["tts"] = {
            "voice_id": voice_id,
            "language": args.language,
        }
        if not spec_data.get("narration_text"):
            script_path = PROJECT_ROOT / "tests" / "fixtures" / "narration_script.json"
            if script_path.exists():
                spec_data["narration_text"] = json.loads(
                    script_path.read_text(encoding="utf-8")
                ).get("narration_text", "")
            else:
                logger.error("No narration_text in spec and no narration_script.json found.")
                return 1
        logger.info(f"TTS mode: voice={voice_id}, lang={args.language}")

    spec = RenderSpec(**spec_data)

    settings = get_settings()

    tts_provider = None
    cache_dir = None
    if args.tts:
        from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
        cache_dir = PROJECT_ROOT / "cache" / "tts"
        tts_provider = ElevenLabsProvider(
            api_key=os.environ["ELEVENLABS_API_KEY"],
            cache_dir=cache_dir,
        )

    render_service = RenderService(
        templates_dir=settings.templates_dir,
        mascots_dir=settings.mascots_dir,
        font_path=settings.resolve_font(),
        ffmpeg_bin=settings.ffmpeg_bin,
        ffprobe_bin=settings.ffprobe_bin,
        fps=settings.video_fps,
        width=settings.video_width,
        height=settings.video_height,
        audio_sample_rate=settings.audio_sample_rate,
        tts_provider=tts_provider,
        cache_dir=cache_dir,
    )

    logger.info(
        f"Rendering: '{spec.title}' "
        f"({len(spec.scenes)} scenes, {spec.total_duration:.1f}s)"
    )

    result = render_service.render(spec, args.output)

    print()
    print("=" * 60)
    print("RENDER COMPLETE")
    print("=" * 60)
    print(f"  Video:        {result.video_path}")
    print(f"  Poster:       {result.poster_path}")
    print(f"  Contact sheet:{result.contact_sheet_path}")
    print(f"  Timeline:     {result.timeline_path}")
    print(f"  Duration:     {result.duration_seconds:.2f}s")
    print(f"  Resolution:   {result.resolution[0]}x{result.resolution[1]}")
    print(f"  Scenes:       {result.scene_count}")
    alignment_path = args.output / "alignment.json"
    if alignment_path.exists():
        print(f"  Alignment:    {alignment_path}")
    tts_cost_path = args.output / "tts_cost.json"
    if tts_cost_path.exists():
        print(f"  TTS cost:     {tts_cost_path}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
