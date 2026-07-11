from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.config import Settings
from app.domain.enums import Focus, MascotAnchor, MascotPose, SfxKind
from app.domain.models import (
    AbsoluteDirectionCue,
    CompiledVideoSpec,
    SoundEffectCue,
    TimedBeat,
    TimedTranscript,
    TimedWord,
)
from app.rendering.ffmpeg import FFmpegRunner
from app.rendering.reference_renderer import ReferenceRenderer
from app.services.quality_service import QualityService
from app.services.reference_quality_service import ReferenceQualityService
from app.services.reference_render_service import ReferenceRenderService
from app.services.timeline_compiler import TimelineCompiler


def product(path: Path, color: tuple[int, int, int], shape: str) -> None:
    image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    if shape == "circle":
        draw.ellipse((170, 160, 854, 844), fill=(*color, 255))
    else:
        draw.rounded_rectangle((170, 220, 854, 804), radius=100, fill=(*color, 255))
    image.save(path)


def main() -> None:
    settings = Settings(_env_file=None)
    output = PROJECT_ROOT / "output" / "reference_acceptance"
    output.mkdir(parents=True, exist_ok=True)
    left = output / "left.png"
    right = output / "right.png"
    audio = output / "narration.wav"
    product(left, (238, 187, 67), "circle")
    product(right, (94, 165, 89), "rectangle")
    subprocess.run([
        settings.ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        "23.8",
        str(audio),
    ], check=True, capture_output=True)
    transcript = TimedTranscript(
        words=[TimedWord(word="Concluzie.", start=0.0, end=21.5)],
        beats=[TimedBeat(id="closing", start=0.0, end=21.5, pause_end=22.0)],
        duration_seconds=22.0,
    )
    spec = CompiledVideoSpec(
        left_label="Left",
        right_label="Right",
        left_image=left,
        right_image=right,
        narration_audio=audio,
        transcript=transcript,
        narration_end_seconds=22.0,
        direction_cues=[
            AbsoluteDirectionCue(
                start=0.0,
                mascot_pose=MascotPose.NEUTRAL,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=Focus.NEUTRAL,
            ),
            AbsoluteDirectionCue(
                start=7.0,
                mascot_pose=MascotPose.POINT_LEFT,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=Focus.LEFT,
            ),
            AbsoluteDirectionCue(
                start=14.0,
                mascot_pose=MascotPose.POINT_RIGHT,
                mascot_anchor=MascotAnchor.CENTER,
                product_focus=Focus.RIGHT,
            ),
        ],
        sound_cues=[SoundEffectCue(start=22.0, kind=SfxKind.CTA_STING)],
        captions=TimelineCompiler().compile_captions(transcript),
    )
    renderer = ReferenceRenderer(
        settings.templates_dir,
        settings.mascots_dir,
        settings.resolve_font(),
    )
    result = ReferenceRenderService(
        renderer,
        FFmpegRunner(settings.ffmpeg_bin, settings.ffprobe_bin),
    ).render(spec, output)
    problems = ReferenceQualityService(
        QualityService(settings.ffmpeg_bin, settings.ffprobe_bin)
    ).validate(spec, result)
    if problems:
        raise RuntimeError("; ".join(problems))
    print(result.video_path)
    print(f"duration={result.duration_seconds:.3f}s frames={result.frame_count}")


if __name__ == "__main__":
    main()
