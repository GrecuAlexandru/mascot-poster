from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from app.domain.exceptions import RenderError
from app.domain.models import RenderResult, RenderSpec, SceneSpec
from app.providers.tts.base import TTSSettings
from app.rendering.compositor import Compositor
from app.rendering.coordinates import load_template
from app.rendering.ffmpeg import FFmpegRunner
from app.rendering.timeline import Timeline
from app.services.alignment_service import AlignmentService
from app.services.audio_service import AudioService
from app.services.mascot_service import MascotService
from app.services.subtitle_service import SubtitleService

logger = logging.getLogger(__name__)


class RenderService:
    def __init__(
        self,
        templates_dir: Path,
        mascots_dir: Path,
        font_path: Optional[Path] = None,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        fps: int = 30,
        width: int = 1080,
        height: int = 1920,
        audio_sample_rate: int = 44100,
        tts_provider: Optional[object] = None,
        cache_dir: Optional[Path] = None,
    ):
        self.templates_dir = templates_dir
        self.mascots_dir = mascots_dir
        self.font_path = font_path
        self.fps = fps
        self.width = width
        self.height = height
        self.audio_sample_rate = audio_sample_rate
        self.ffmpeg = FFmpegRunner(ffmpeg_bin, ffprobe_bin)
        self.tts_provider = tts_provider
        self.alignment_svc = AlignmentService(ffmpeg_bin, ffprobe_bin)
        self.audio_svc = AudioService(ffmpeg_bin, ffprobe_bin, audio_sample_rate)
        self.subtitle_svc = SubtitleService()
        self.cache_dir = cache_dir

    def render(
        self,
        spec: RenderSpec,
        output_dir: Path,
    ) -> RenderResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = output_dir / "_work"
        work_dir.mkdir(exist_ok=True)

        audio_path = spec.audio

        if spec.tts and spec.narration_text:
            audio_path = self._generate_tts(spec, work_dir)

        if spec.background_music or spec.sfx_paths:
            mixed_path = work_dir / "mixed_audio.aac"
            self.audio_svc.mix(
                narration_path=audio_path,
                output_path=mixed_path,
                music_path=spec.background_music,
                sfx_paths=spec.sfx_paths if spec.sfx_paths else None,
            )
            audio_path = mixed_path

        if spec.narration_text:
            self._generate_alignment_and_subtitles(spec, audio_path, work_dir, output_dir)

        template = load_template(spec.template, self.templates_dir)
        compositor = Compositor(template, self.font_path)

        mascot_svc = MascotService(self.mascots_dir)
        required_poses = list({s.pose.value for s in spec.scenes})
        missing = mascot_svc.validate_poses(required_poses)
        if missing:
            logger.warning(f"Missing mascot poses: {missing}")

        timeline = Timeline.from_scenes(spec.scenes, self.fps)

        logger.info(
            f"Rendering {len(spec.scenes)} scenes, "
            f"total duration {timeline.total_duration:.1f}s"
        )

        frames = self._render_frames(spec, compositor, work_dir)
        for i, entry in enumerate(timeline.entries):
            entry.frame_path = frames[i]

        segments = self._create_segments(spec.scenes, frames, work_dir)
        for i, entry in enumerate(timeline.entries):
            entry.segment_path = segments[i]
            entry.segment_duration = spec.scenes[i].duration

        video_no_audio = work_dir / "video_no_audio.mp4"
        transitions = [s.transition for s in spec.scenes]
        durations = [s.duration for s in spec.scenes]
        self.ffmpeg.concat_with_xfade(segments, durations, transitions, video_no_audio)

        final_video = output_dir / "video.mp4"
        self.ffmpeg.mux_audio(
            video_no_audio, audio_path, final_video, self.audio_sample_rate
        )

        poster_path = output_dir / "poster.jpg"
        self.ffmpeg.create_poster(frames[0], poster_path)

        contact_sheet_path = output_dir / "contact-sheet.jpg"
        sheet = compositor.create_contact_sheet(frames)
        sheet.save(str(contact_sheet_path), quality=90)

        timeline_path = output_dir / "timeline.json"
        timeline_path.write_text(
            json.dumps(timeline.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        video_duration = self.ffmpeg.get_duration(final_video)

        self._cleanup(work_dir)

        logger.info(f"Render complete: {final_video}")
        return RenderResult(
            video_path=final_video,
            poster_path=poster_path,
            contact_sheet_path=contact_sheet_path,
            timeline_path=timeline_path,
            duration_seconds=video_duration,
            frame_count=timeline.total_frames,
            resolution=(self.width, self.height),
            scene_count=len(spec.scenes),
        )

    def _generate_tts(self, spec: RenderSpec, work_dir: Path) -> Path:
        if not self.tts_provider:
            raise RenderError("TTS requested but no provider configured")

        tts_spec = spec.tts
        output_path = work_dir / "tts_narration.mp3"

        settings = TTSSettings(
            stability=tts_spec.stability,
            similarity_boost=tts_spec.similarity_boost,
            style_exaggeration=tts_spec.style_exaggeration,
            speed=tts_spec.speed,
            model_id=tts_spec.model_id,
        )

        logger.info(
            f"Generating TTS: voice={tts_spec.voice_id}, "
            f"lang={tts_spec.language}, chars={len(spec.narration_text)}"
        )

        result = asyncio.run(self.tts_provider.synthesize(
            text=spec.narration_text,
            voice_id=tts_spec.voice_id,
            language=tts_spec.language,
            output_path=output_path,
            settings=settings,
        ))

        logger.info(
            f"TTS complete: duration={result.duration_seconds:.1f}s, "
            f"cost=${result.estimated_cost_usd:.4f}"
        )

        cost_path = work_dir.parent / "tts_cost.json"
        cost_path.write_text(
            json.dumps({
                "provider": result.provider,
                "model": result.model,
                "character_count": result.character_count,
                "duration_seconds": result.duration_seconds,
                "estimated_cost_usd": result.estimated_cost_usd,
            }, indent=2),
            encoding="utf-8",
        )

        return output_path

    def _generate_alignment_and_subtitles(
        self,
        spec: RenderSpec,
        audio_path: Path,
        work_dir: Path,
        output_dir: Path,
    ) -> None:
        provider_words = None
        if hasattr(self.tts_provider, "_last_result"):
            provider_words = self.tts_provider._last_result

        timed_words = self.alignment_svc.align(
            text=spec.narration_text,
            audio_path=audio_path,
            timed_words=provider_words,
        )

        phrases = self.subtitle_svc.select_phrases(
            narration=spec.narration_text,
            words=timed_words,
        )

        alignment_path = output_dir / "alignment.json"
        alignment_path.write_text(
            json.dumps({
                "timed_words": [w.model_dump() for w in timed_words],
                "phrases": [p.model_dump() for p in phrases],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            f"Alignment: {len(timed_words)} words, {len(phrases)} subtitle phrases"
        )

    def _render_frames(
        self,
        spec: RenderSpec,
        compositor: Compositor,
        work_dir: Path,
    ) -> list[Path]:
        frames: list[Path] = []
        for i, scene in enumerate(spec.scenes):
            frame = compositor.compose_frame(spec, scene)
            path = work_dir / f"scene_{i:03d}.png"
            frame.save(str(path))
            frames.append(path)
            logger.info(f"Scene {i}: frame saved ({path.name})")
        return frames

    def _create_segments(
        self,
        scenes: list[SceneSpec],
        frames: list[Path],
        work_dir: Path,
    ) -> list[Path]:
        segments: list[Path] = []
        for i, scene in enumerate(scenes):
            path = work_dir / f"seg_{i:03d}.mp4"
            self.ffmpeg.create_segment(
                image_path=frames[i],
                output_path=path,
                duration=scene.duration,
                fps=self.fps,
                width=self.width,
                height=self.height,
                motion=scene.image_motion,
            )
            segments.append(path)
            logger.info(f"Segment {i}: created ({path.name})")
        return segments

    def _cleanup(self, work_dir: Path) -> None:
        import shutil
        try:
            shutil.rmtree(work_dir)
        except Exception as e:
            logger.warning(f"Could not clean up work dir: {e}")
