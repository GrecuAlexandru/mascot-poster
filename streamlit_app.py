from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.config import get_settings
from app.domain.enums import Focus, ImageMotion, MascotPose, Transition
from app.domain.models import (
    Claim,
    GenerationRequest,
    RenderSpec,
    RenderResult,
    ResearchPackage,
    ScenePlan,
    SceneSpec,
    ScriptPackage,
    TopicSpec,
    VerificationResult,
)
from app.rendering.coordinates import load_template
from app.rendering.compositor import Compositor
from app.services.pipeline import PipelineOrchestrator, PipelineState, Stage
from app.services.render_service import RenderService
from app.services.topic_service import TopicService
from app.services.topic_history import TopicHistoryService
from app.services.script_service import ScriptService
from app.services.research_service import ResearchService
from app.services.fact_check_service import FactCheckService
from app.services.image_service import ImageService
from app.services.quality_service import QualityService
from app.services.cost_tracker import CostTracker
from app.services.publishing_service import PublishingService, PublicationPayload
from app.services.analytics_service import AnalyticsService, AnalyticsSnapshot
from app.services.scene_planner import ScenePlanner
from app.services.mascot_service import MascotService
from app.services.reference_generation_factory import build_reference_generation_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

POSE_OPTIONS = [p.value for p in MascotPose]
FOCUS_OPTIONS = [f.value for f in Focus]
MOTION_OPTIONS = [m.value for m in ImageMotion]
TRANSITION_OPTIONS = [t.value for t in Transition]

PIPELINE_STAGES = [
    Stage.QUEUED,
    Stage.TOPIC_SELECTED,
    Stage.RESEARCH_COMPLETE,
    Stage.SCRIPT_COMPLETE,
    Stage.VERIFICATION_COMPLETE,
    Stage.ASSETS_COMPLETE,
    Stage.TTS_COMPLETE,
    Stage.TIMING_COMPLETE,
    Stage.RENDER_COMPLETE,
    Stage.QUALITY_COMPLETE,
    Stage.WAITING_FOR_APPROVAL,
    Stage.APPROVED,
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
    except RuntimeError:
        pass
    return asyncio.run(coro)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────────────────────

def init_state() -> None:
    ss = st.session_state
    if "jobs" not in ss:
        ss.jobs = {}
    if "current_job_id" not in ss:
        ss.current_job_id = None
    if "topic_candidates" not in ss:
        ss.topic_candidates = []
    if "render_spec" not in ss:
        ss.render_spec = None
    if "render_result" not in ss:
        ss.render_result = None
    if "quality_problems" not in ss:
        ss.quality_problems = None
    if "analytics" not in ss:
        ss.analytics = AnalyticsService()
    if "pipeline_running" not in ss:
        ss.pipeline_running = False
    if "pipeline_done" not in ss:
        ss.pipeline_done = False
    if "pipeline_step" not in ss:
        ss.pipeline_step = None
    if "pipeline_error" not in ss:
        ss.pipeline_error = None
    if "pipeline_topic" not in ss:
        ss.pipeline_topic = None
    if "pipeline_job_id" not in ss:
        ss.pipeline_job_id = None


def get_jobs() -> dict[str, dict]:
    return st.session_state.jobs


def get_current_job() -> Optional[dict]:
    jid = st.session_state.current_job_id
    if jid and jid in get_jobs():
        return get_jobs()[jid]
    return None


def set_current_job(jid: str) -> None:
    st.session_state.current_job_id = jid


def create_job(topic: Optional[TopicSpec] = None) -> PipelineState:
    settings = get_settings()
    orch = PipelineOrchestrator(
        templates_dir=settings.templates_dir,
        mascots_dir=settings.mascots_dir,
        output_base=PROJECT_ROOT / "output" / "jobs",
        font_path=settings.resolve_font(),
        ffmpeg_bin=settings.ffmpeg_bin,
        ffprobe_bin=settings.ffprobe_bin,
        fps=settings.video_fps,
        width=settings.video_width,
        height=settings.video_height,
        audio_sample_rate=settings.audio_sample_rate,
    )
    state = orch.create_job(topic=topic)
    get_jobs()[state.job_id] = {
        "status": "QUEUED",
        "stage": state.current_stage.value,
        "state": state,
        "created_at": _ts(),
    }
    set_current_job(state.job_id)
    return state


# ──────────────────────────────────────────────────────────────────────────────
# Provider factories
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def get_llm_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None
    skills_content = ""
    if settings.skills_file:
        skills_content = settings.skills_file.read_text(encoding="utf-8")
    from app.providers.llm.openai_provider import LLMProvider
    return LLMProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        skills_content=skills_content,
    )


@st.cache_resource
def get_topic_llm_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None
    skills_content = ""
    if settings.skills_file:
        skills_content = settings.skills_file.read_text(encoding="utf-8")
    from app.providers.llm.openai_provider import LLMProvider
    return LLMProvider(
        api_key=settings.llm_api_key,
        model=settings.topic_llm_model,
        base_url=settings.llm_base_url,
        skills_content=skills_content,
    )


@st.cache_resource
def get_topic_history() -> TopicHistoryService:
    settings = get_settings()
    return TopicHistoryService(settings.data_dir / "topic_history.json")


@st.cache_resource
def get_tts_provider() -> Optional[object]:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        return None
    from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
    cache_dir = PROJECT_ROOT / "cache" / "tts"
    return ElevenLabsProvider(api_key=api_key, cache_dir=cache_dir)


@st.cache_resource
def get_search_provider() -> Optional[object]:
    api_key = os.environ.get("SEARCH_API_KEY", "")
    if not api_key:
        return None
    provider_name = os.environ.get("SEARCH_PROVIDER", "tavily").lower()
    from app.providers.search.tavily_provider import TavilyProvider, SerperProvider
    if provider_name == "serper":
        return SerperProvider(api_key=api_key)
    return TavilyProvider(api_key=api_key)


@st.cache_resource
def get_image_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None
    from app.providers.images.openrouter_provider import OpenRouterImageProvider
    cache_dir = PROJECT_ROOT / "cache" / "images"
    return OpenRouterImageProvider(
        api_key=settings.llm_api_key,
        model=settings.image_model,
        cache_dir=cache_dir,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Service factories
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def make_render_service() -> RenderService:
    s = get_settings()
    return RenderService(
        templates_dir=s.templates_dir,
        mascots_dir=s.mascots_dir,
        font_path=s.resolve_font(),
        ffmpeg_bin=s.ffmpeg_bin,
        ffprobe_bin=s.ffprobe_bin,
        fps=s.video_fps,
        width=s.video_width,
        height=s.video_height,
        audio_sample_rate=s.audio_sample_rate,
        tts_provider=get_tts_provider(),
        cache_dir=PROJECT_ROOT / "cache" / "tts",
    )


@st.cache_resource
def make_topic_service() -> TopicService:
    return TopicService(llm_provider=get_llm_provider())


@st.cache_resource
def make_topic_idea_service() -> TopicService:
    return TopicService(llm_provider=get_topic_llm_provider() or get_llm_provider())


@st.cache_resource
def make_script_service() -> ScriptService:
    return ScriptService(llm_provider=get_llm_provider())


@st.cache_resource
def make_research_service() -> ResearchService:
    return ResearchService(
        search_provider=get_search_provider(),
        llm_provider=get_llm_provider(),
    )


@st.cache_resource
def make_fact_check_service() -> FactCheckService:
    return FactCheckService(llm_provider=get_llm_provider())


@st.cache_resource
def make_image_service() -> ImageService:
    return ImageService(
        provider=get_image_provider(),
        cache_dir=PROJECT_ROOT / "cache" / "images",
    )


@st.cache_resource
def make_quality_service() -> QualityService:
    s = get_settings()
    return QualityService(ffmpeg_bin=s.ffmpeg_bin, ffprobe_bin=s.ffprobe_bin)


@st.cache_resource
def make_publishing_service() -> PublishingService:
    return PublishingService()


@st.cache_resource
def make_scene_planner() -> ScenePlanner:
    return ScenePlanner()


@st.cache_resource
def make_mascot_service() -> MascotService:
    s = get_settings()
    return MascotService(s.mascots_dir)


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    s = get_settings()

    with st.sidebar:
        st.header("System")

        ffmpeg_ok = _check_binary(s.ffmpeg_bin)
        ffprobe_ok = _check_binary(s.ffprobe_bin)

        st.metric("FFmpeg", "OK" if ffmpeg_ok else "Missing", delta=None)
        st.metric("FFprobe", "OK" if ffprobe_ok else "Missing", delta=None)

        st.divider()
        st.subheader("Providers")

        llm = get_llm_provider()
        tts = get_tts_provider()
        search = get_search_provider()
        image = get_image_provider()

        pcol1, pcol2 = st.columns(2)
        pcol1.metric("LLM", "On" if llm else "Off")
        pcol2.metric("Search", "On" if search else "Off")
        pcol1.metric("TTS", "On" if tts else "Off")
        pcol2.metric("Images", "On" if image else "Off")

        st.divider()
        st.subheader("Assets")

        st.write(f"Templates: {'OK' if s.templates_dir.exists() else 'Missing'}")
        st.write(f"Mascots: {'OK' if s.mascots_dir.exists() else 'Missing'}")
        st.write(f"Model: `{s.llm_model}`")

        available_poses = make_mascot_service().available_poses
        st.write(f"Poses: {len(available_poses)} available")

        st.divider()
        st.subheader("Jobs")
        jobs = get_jobs()
        st.metric("Total Jobs", len(jobs))

        if jobs:
            options = {jid: f"{j['state'].topic.title[:40] if j['state'].topic else jid[:8]}"
                       for jid, j in jobs.items()}
            selected = st.selectbox(
                "Active job",
                options=list(options.keys()),
                format_func=lambda jid: options.get(jid, jid[:8]),
                index=0 if st.session_state.current_job_id is None else
                      list(jobs.keys()).index(st.session_state.current_job_id)
                      if st.session_state.current_job_id in jobs else 0,
            )
            if selected != st.session_state.current_job_id:
                set_current_job(selected)
                st.rerun()


def _check_binary(name: str) -> bool:
    import subprocess
    try:
        result = subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline progress widget
# ──────────────────────────────────────────────────────────────────────────────

def render_pipeline_progress(state: Optional[PipelineState]) -> None:
    if not state:
        st.info("No active job. Create or select a job to see pipeline progress.")
        return

    current_idx = 0
    try:
        current_idx = list(Stage).index(state.current_stage)
    except ValueError:
        pass

    cols = st.columns(len(PIPELINE_STAGES))
    for i, stage in enumerate(PIPELINE_STAGES):
        with cols[i]:
            if i < current_idx:
                st.markdown(f":white_check_mark: **{i+1}**")
            elif i == current_idx:
                st.markdown(f":dart: **{i+1}**")
            else:
                st.markdown(f":white_circle: ~~{i+1}~~")
            st.caption(stage.value.replace("_", " ").title()[:14])

    if state.error_message:
        st.error(f"Error: {state.error_message}")
    if state.retry_count:
        st.warning(f"Retries: {state.retry_count}")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Dashboard
# ──────────────────────────────────────────────────────────────────────────────

def tab_dashboard() -> None:
    st.header("Dashboard")

    state = get_current_job()
    render_pipeline_progress(state["state"] if state else None)

    jobs = get_jobs()
    if not jobs:
        st.info("No jobs yet. Go to the **Topic** tab to create one.")
        return

    st.subheader("Jobs")
    rows = []
    for jid, j in jobs.items():
        s = j["state"]
        rows.append({
            "Job ID": jid[:8] + "...",
            "Title": s.topic.title if s.topic else "(no topic)",
            "Stage": s.current_stage.value,
            "Status": j["status"],
            "Cost": f"${s.cost_tracker.total_cost:.4f}",
            "Created": j.get("created_at", "")[:19],
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    if state:
        st.subheader(f"Active Job: {state['state'].job_id[:8]}")
        s = state["state"]
        info_col, cost_col = st.columns(2)
        with info_col:
            st.write(f"**Stage:** {s.current_stage.value}")
            st.write(f"**Status:** {state['status']}")
            if s.topic:
                st.write(f"**Topic:** {s.topic.title}")
                st.write(f"**Compare:** {s.topic.comparison_left} vs {s.topic.comparison_right}")
        with cost_col:
            cost_data = s.cost_tracker.to_dict()
            st.write(f"**Total cost:** ${cost_data['by_category'].get('total', 0):.4f}")
            if cost_data["by_category"]:
                cat_data = {k: v for k, v in cost_data["by_category"].items() if k != "total"}
                if cat_data:
                    st.bar_chart(cat_data)

        st.subheader("Cost Records")
        if cost_data["records"]:
            st.dataframe(cost_data["records"], use_container_width=True, hide_index=True)
        else:
            st.caption("No cost records yet.")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Topic
# ──────────────────────────────────────────────────────────────────────────────

def tab_topic() -> None:
    st.header("Topic")

    idea_tab, manual_tab, ai_tab, load_tab, history_tab = st.tabs([
        "⚡ Generate Idea",
        "Manual",
        "Generate Candidates",
        "Load Fixture",
        "History",
    ])

    with idea_tab:
        _tab_topic_idea()

    with manual_tab:
        st.subheader("Create a topic manually")
        with st.form("manual_topic"):
            left = st.text_input("Left item", placeholder="Coffee")
            right = st.text_input("Right item", placeholder="Tea")
            title = st.text_input("Title (optional)", placeholder="Coffee vs Tea")
            angle = st.text_area("Comparison angle (optional)", placeholder="Energy, taste, and caffeine")
            submitted = st.form_submit_button("Create job from topic", type="primary")

        if submitted:
            if not left.strip() or not right.strip():
                st.error("Both left and right items are required.")
            else:
                svc = make_topic_service()
                topic = svc.create_manual_topic(
                    left=left.strip(),
                    right=right.strip(),
                    angle=angle.strip(),
                    title=title.strip() or None,
                )
                state = create_job(topic=topic)
                st.success(f"Job created: {state.job_id[:8]}")
                st.rerun()

    with ai_tab:
        st.subheader("Generate topic candidates with AI")
        llm = get_llm_provider()
        if not llm:
            st.warning("LLM provider not configured. Set `OPENROUTER_API_KEY` in `.env` to enable.")
        else:
            with st.form("ai_topic"):
                niche = st.text_input("Niche", value="food facts", key="ai_niche")
                language = st.selectbox("Language", ["en", "ro"], index=0, key="ai_lang")
                count = st.slider("Number of candidates", 1, 20, 10, key="ai_count")
                submitted = st.form_submit_button("Generate", type="primary")

            if submitted:
                svc = make_topic_service()
                try:
                    with st.spinner("Generating topics..."):
                        candidates = run_async(svc.generate_topics(
                            niche=niche,
                            language=language,
                            count=count,
                        ))
                    st.session_state.topic_candidates = candidates
                except Exception as e:
                    st.error(f"Failed: {e}")

            candidates = st.session_state.topic_candidates
            if candidates:
                st.write(f"**{len(candidates)} candidates generated**")
                for i, c in enumerate(candidates):
                    with st.expander(f"{i+1}. {c.title} (risk: {c.risk_level})"):
                        st.write(f"**Left:** {c.left}")
                        st.write(f"**Right:** {c.right}")
                        st.write(f"**Angle:** {c.angle}")
                        st.write(f"**Why:** {c.why_it_might_work}")
                        if st.button(f"Select this topic", key=f"pick_topic_{i}"):
                            topic = TopicSpec(
                                title=c.title,
                                comparison_left=c.left,
                                comparison_right=c.right,
                                angle=c.angle,
                            )
                            state = create_job(topic=topic)
                            get_topic_history().add_from_topic(topic, job_id=state.job_id)
                            st.success(f"Job created: {state.job_id[:8]}")
                            st.rerun()

    with load_tab:
        st.subheader("Load from fixture or JSON")
        fixture_dir = PROJECT_ROOT / "tests" / "fixtures"
        fixtures = list(fixture_dir.glob("*.json")) if fixture_dir.exists() else []
        fixture_names = {f.name: f for f in fixtures}

        fixture_col, json_col = st.columns(2)
        with fixture_col:
            if fixture_names:
                chosen = st.selectbox("Fixture file", list(fixture_names.keys()))
                if st.button("Load fixture"):
                    data = json.loads(fixture_names[chosen].read_text(encoding="utf-8"))
                    left = data.get("comparison_left") or data.get("left_label") or ""
                    right = data.get("comparison_right") or data.get("right_label") or ""
                    title = data.get("title", "")
                    angle = data.get("angle", "")
                    if left and right:
                        svc = make_topic_service()
                        topic = svc.create_manual_topic(
                            left=left, right=right, angle=angle, title=title,
                        )
                        state = create_job(topic=topic)
                        st.success(f"Job created: {state.job_id[:8]}")
                        st.rerun()
            else:
                st.info("No fixtures found. Run `python scripts/generate_fixtures.py`")

        with json_col:
            json_text = st.text_area("Paste topic JSON", height=150,
                                     placeholder='{"left": "Coffee", "right": "Tea", "title": "Coffee vs Tea", "angle": "..."}')
            if st.button("Create from JSON"):
                try:
                    data = json.loads(json_text)
                    left = data.get("left") or data.get("comparison_left") or ""
                    right = data.get("right") or data.get("comparison_right") or ""
                    if not left or not right:
                        st.error("JSON must contain 'left' and 'right' keys.")
                    else:
                        svc = make_topic_service()
                        topic = svc.create_manual_topic(
                            left=left, right=right,
                            angle=data.get("angle", ""),
                            title=data.get("title"),
                        )
                        state = create_job(topic=topic)
                        st.success(f"Job created: {state.job_id[:8]}")
                        st.rerun()
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")

    with history_tab:
        _tab_topic_history()


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Topic — Generate Idea
# ──────────────────────────────────────────────────────────────────────────────

def _tab_topic_idea() -> None:
    history = get_topic_history()
    settings = get_settings()

    if history.count:
        st.caption(f"{history.count} topics already in history")

    llm = get_topic_llm_provider() or get_llm_provider()
    if not llm:
        st.warning(
            "LLM provider not configured. Set `OPENROUTER_API_KEY` in `.env` to enable. "
            "You can still create topics manually in the other tabs."
        )
        return

    if not st.session_state.get("pipeline_running") and not st.session_state.get("pipeline_done"):
        if st.button("⚡ Generate Video", type="primary", use_container_width=True):
            st.session_state.pipeline_running = True
            st.session_state.pipeline_done = False
            st.session_state.pipeline_step = "topic"
            st.session_state.pipeline_error = None
            st.session_state.pipeline_topic = None
            st.session_state.pipeline_job_id = None
            st.rerun()

    if st.session_state.get("pipeline_running"):
        _run_pipeline_step(history, settings)

    if st.session_state.get("pipeline_done"):
        progress = {
            "status": "done",
            "topic": st.session_state.get("pipeline_topic"),
            "render_result": st.session_state.get("render_result"),
        }
        _display_pipeline_result(progress)

        if st.button("Generate another video", key="restart_pipeline"):
            st.session_state.pipeline_running = False
            st.session_state.pipeline_done = False
            st.session_state.pipeline_step = None
            st.session_state.pipeline_error = None
            st.session_state.pipeline_topic = None
            st.session_state.pipeline_job_id = None
            st.session_state.render_result = None
            st.session_state.render_spec = None
            st.session_state.quality_problems = None
            st.rerun()

    if st.session_state.get("pipeline_error"):
        st.error(st.session_state["pipeline_error"])
        if st.button("Try again", key="retry_pipeline"):
            st.session_state.pipeline_running = False
            st.session_state.pipeline_done = False
            st.session_state.pipeline_step = None
            st.session_state.pipeline_error = None
            st.session_state.render_result = None
            st.session_state.render_spec = None
            st.rerun()


def _display_pipeline_result(progress: dict) -> None:
    topic = progress.get("topic")
    result = progress.get("render_result")

    if topic:
        st.divider()
        st.subheader(topic.get("title", "Unknown"))
        c1, c2 = st.columns(2)
        c1.write(f"**Left:** {topic['left']}")
        c2.write(f"**Right:** {topic['right']}")
        c1.write(f"**Angle:** {topic.get('angle', '')}")
        c2.write(f"**Risk:** {topic.get('risk_level', '')}")

    if result and isinstance(result, RenderResult):
        st.success("Video ready!")

        res1, res2, res3 = st.columns(3)
        res1.metric("Duration", f"{result.duration_seconds:.1f}s")
        res2.metric("Resolution", f"{result.resolution[0]}x{result.resolution[1]}")
        res3.metric("Scenes", result.scene_count)

        vc, ac = st.columns([2, 1])
        with vc:
            if result.video_path.exists():
                st.video(str(result.video_path))
        with ac:
            if result.poster_path.exists():
                st.image(str(result.poster_path), caption="Poster", use_container_width=True)
            if result.contact_sheet_path.exists():
                st.image(str(result.contact_sheet_path), caption="Contact sheet", use_container_width=True)


_PIPELINE_STEPS_ORDER = [
    "topic",
    "research",
    "script",
    "fact_check",
    "images",
    "build_spec",
    "render",
    "quality",
    "done",
]


def _run_pipeline_step(history: "TopicHistoryService", settings: "Settings") -> None:
    step = st.session_state.get("pipeline_step", "topic")

    step_labels = {
        "topic": "Generating topic idea",
        "research": "Researching topic",
        "script": "Writing script",
        "fact_check": "Fact-checking claims",
        "images": "Acquiring images",
        "build_spec": "Building render spec",
        "render": "Rendering video",
        "quality": "Running quality check",
        "done": "Complete",
    }

    next_step = {
        "topic": "research",
        "research": "script",
        "script": "fact_check",
        "fact_check": "images",
        "images": "build_spec",
        "build_spec": "render",
        "render": "quality",
        "quality": "done",
    }

    current_idx = _PIPELINE_STEPS_ORDER.index(step) if step in _PIPELINE_STEPS_ORDER else 0
    total = len(_PIPELINE_STEPS_ORDER) - 1
    st.progress(current_idx / total, text=step_labels.get(step, step))

    try:
        if step == "topic":
            _pipeline_step_topic(history, settings)
        elif step == "research":
            _pipeline_step_research(settings)
        elif step == "script":
            _pipeline_step_script(settings)
        elif step == "fact_check":
            _pipeline_step_fact_check()
        elif step == "images":
            _pipeline_step_images()
        elif step == "build_spec":
            _pipeline_step_build_spec()
        elif step == "render":
            _pipeline_step_render()
        elif step == "quality":
            _pipeline_step_quality()

        st.session_state.pipeline_step = next_step.get(step, "done")

        if st.session_state.pipeline_step == "done":
            st.session_state.pipeline_running = False
            st.session_state.pipeline_done = True

        st.rerun()

    except Exception as e:
        logger.exception(f"Pipeline failed at step: {step}")
        st.session_state.pipeline_running = False
        st.session_state.pipeline_error = f"Failed at **{step_labels.get(step, step)}**: {e}"
        st.rerun()


def _get_pipeline_state() -> Optional[PipelineState]:
    jid = st.session_state.get("pipeline_job_id")
    if jid and jid in get_jobs():
        return get_jobs()[jid]["state"]
    return None


def _pipeline_step_topic(history: "TopicHistoryService", settings: "Settings") -> None:
    svc = make_topic_idea_service()
    candidates = run_async(svc.generate_unique_topics(
        history=history,
        count=10,
    ))
    if not candidates:
        raise RuntimeError("No unique topics found. Try clearing some history.")

    best = candidates[0]
    topic = TopicSpec(
        title=best.title,
        comparison_left=best.left,
        comparison_right=best.right,
        angle=best.angle,
    )
    st.session_state.pipeline_topic = {
        "title": best.title,
        "left": best.left,
        "right": best.right,
        "angle": best.angle,
        "risk_level": best.risk_level,
    }
    state = create_job(topic=topic)
    history.add_from_topic(topic, job_id=state.job_id)
    st.session_state.pipeline_job_id = state.job_id


def _pipeline_step_research(settings: "Settings") -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    svc = make_research_service()
    search_responses = []
    if svc.search:
        search_responses = run_async(svc.search_topic(pstate.topic))
    sources = svc.deduplicate_sources(search_responses)

    if svc.llm:
        research = run_async(svc.synthesize(pstate.topic, search_responses, sources))
    else:
        research = svc._fallback_synthesize(pstate.topic, sources)

    pstate.research = research
    pstate.checkpoint(Stage.RESEARCH_COMPLETE)


def _pipeline_step_script(settings: "Settings") -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    svc = make_script_service()
    research_facts = [f.text for f in pstate.research.facts] if pstate.research else []
    script = run_async(svc.generate_script(
        topic=pstate.topic,
        niche="",
        language="en",
        target_duration_seconds=60,
        research_facts=research_facts,
        canvas_width=settings.video_width,
        canvas_height=settings.video_height,
    ))
    pstate.script = script
    pstate.checkpoint(Stage.SCRIPT_COMPLETE)


def _pipeline_step_fact_check() -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    if not pstate.script.claims:
        pstate.verification = VerificationResult(approved=True, claim_results=[])
        pstate.checkpoint(Stage.VERIFICATION_COMPLETE)
        return

    svc = make_fact_check_service()
    research = pstate.research or ResearchPackage(
        topic=pstate.topic.title,
        left_item=pstate.topic.comparison_left,
        right_item=pstate.topic.comparison_right,
    )
    verification = run_async(svc.verify(
        narration=pstate.script.narration_text,
        claims=pstate.script.claims,
        research=research,
        left_item=pstate.topic.comparison_left,
        right_item=pstate.topic.comparison_right,
        angle=pstate.topic.angle,
    ))
    pstate.verification = verification
    pstate.checkpoint(Stage.VERIFICATION_COMPLETE)


def _pipeline_step_images() -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    try:
        img_svc = make_image_service()
        left_gen = pstate._work_dir / "left_image.png"
        right_gen = pstate._work_dir / "right_image.png"
        run_async(img_svc.generate_or_acquire(pstate.topic.comparison_left, left_gen))
        run_async(img_svc.generate_or_acquire(pstate.topic.comparison_right, right_gen))
    except Exception:
        pass

    pstate.checkpoint(Stage.ASSETS_COMPLETE)


def _pipeline_step_build_spec() -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    planner = make_scene_planner()
    plans = planner.plan_from_script(pstate.script)
    if not plans:
        raise RuntimeError("Scene planner produced no scenes")

    fixture_left = PROJECT_ROOT / "tests" / "fixtures" / "left.png"
    fixture_right = PROJECT_ROOT / "tests" / "fixtures" / "right.png"

    left_image = pstate._work_dir / "left_image.png"
    left_image = left_image if left_image.exists() else fixture_left
    right_image = pstate._work_dir / "right_image.png"
    right_image = right_image if right_image.exists() else fixture_right

    labels = pstate.topic.title.split(" vs ") if " vs " in pstate.topic.title else [
        pstate.topic.comparison_left, pstate.topic.comparison_right
    ]
    left_label = labels[0] if labels else "Left"
    right_label = labels[1] if len(labels) > 1 else "Right"

    fixture_audio = PROJECT_ROOT / "tests" / "fixtures" / "narration.mp3"

    spec = _build_spec_from_plans(
        title=pstate.script.title,
        left_label=left_label,
        right_label=right_label,
        left_image=left_image,
        right_image=right_image,
        audio=fixture_audio,
        plans=plans,
        narration=pstate.script.narration_text,
    )
    st.session_state.render_spec = spec

    pstate.checkpoint(Stage.TIMING_COMPLETE)


def _pipeline_step_render() -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    spec = st.session_state.get("render_spec")
    if not spec:
        raise RuntimeError("No render spec built")

    render_svc = make_render_service()
    output_dir = PROJECT_ROOT / "output" / pstate.job_id
    result = render_svc.render(spec, output_dir)

    st.session_state.render_result = result
    pstate.render_result = result
    pstate.checkpoint(Stage.RENDER_COMPLETE)


def _pipeline_step_quality() -> None:
    pstate = _get_pipeline_state()
    if not pstate:
        raise RuntimeError("No active job")

    result = st.session_state.get("render_result")
    if not result:
        raise RuntimeError("No render result")

    spec = st.session_state.get("render_spec")

    q_svc = make_quality_service()
    problems = q_svc.validate_video(result.video_path)
    if spec:
        problems.extend(q_svc.validate_content(result, expected_scene_count=len(spec.scenes)))
    st.session_state.quality_problems = problems

    if not problems:
        pstate.checkpoint(Stage.QUALITY_COMPLETE)
        pstate.checkpoint(Stage.WAITING_FOR_APPROVAL)


def _tab_topic_history() -> None:
    st.subheader("Topic History")

    history = get_topic_history()
    all_topics = history.get_all()

    st.metric("Total topics presented", history.count)

    if not all_topics:
        st.info(
            "No topics in history yet. Generate an idea or create a topic — "
            "selected topics will be saved here automatically."
        )
        return

    st.dataframe([
        {
            "Title": t.get("title", ""),
            "Left": t.get("left", ""),
            "Right": t.get("right", ""),
            "Angle": t.get("angle", ""),
            "Job ID": t.get("job_id", "")[:8] + "..." if t.get("job_id") else "",
            "Added": t.get("added_at", "")[:19],
        }
        for t in reversed(all_topics)
    ], use_container_width=True, hide_index=True)

    st.divider()
    export_col, clear_col = st.columns(2)
    with export_col:
        if st.button("Export history JSON"):
            st.download_button(
                "Download",
                data=json.dumps(all_topics, indent=2, ensure_ascii=False),
                file_name="topic_history.json",
                mime="application/json",
            )
    with clear_col:
        if st.button("Clear history", type="secondary"):
            history.clear()
            st.success("History cleared.")
            st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Research
# ──────────────────────────────────────────────────────────────────────────────

def tab_research() -> None:
    st.header("Research")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]
    if not pstate.topic:
        st.warning("This job has no topic. Set a topic in the Topic tab.")
        return

    st.write(f"**Topic:** {pstate.topic.title}")
    st.write(f"**Comparing:** {pstate.topic.comparison_left} vs {pstate.topic.comparison_right}")

    if pstate.research:
        st.success("Research already completed for this job.")
        _display_research(pstate.research)
        if st.button("Re-run research"):
            _run_research(pstate)
    else:
        search = get_search_provider()
        llm = get_llm_provider()
        if not search and not llm:
            st.warning("No search or LLM provider configured. Showing fixture data only.")

        fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "research_package.json"
        use_fixture = False
        if fixture_path.exists():
            use_fixture = st.checkbox("Load research from fixture instead", value=not search)

        if use_fixture:
            if st.button("Load fixture research"):
                data = json.loads(fixture_path.read_text(encoding="utf-8"))
                pstate.research = ResearchPackage(**data)
                pstate.checkpoint(Stage.RESEARCH_COMPLETE)
                state["stage"] = pstate.current_stage.value
                st.success("Research loaded from fixture.")
                st.rerun()
        else:
            if st.button("Run research", type="primary"):
                _run_research(pstate)


def _run_research(pstate: PipelineState) -> None:
    svc = make_research_service()
    try:
        with st.spinner("Searching and synthesizing..."):
            search_responses = []
            if svc.search:
                search_responses = run_async(svc.search_topic(pstate.topic))
                pstate.cost_tracker.add_search(
                    provider=svc.search.name,
                    queries=len(svc.build_queries(pstate.topic)),
                    cost=0.0,
                )
            sources = svc.deduplicate_sources(search_responses)
            research = run_async(svc.synthesize(pstate.topic, search_responses, sources))
            pstate.research = research
            pstate.checkpoint(Stage.RESEARCH_COMPLETE)
            st.success(f"Research: {len(research.facts)} facts, {len(research.sources)} sources")
            st.rerun()
    except Exception as e:
        st.error(f"Research failed: {e}")


def _display_research(research: ResearchPackage) -> None:
    facts_tab, sources_tab, notes_tab = st.tabs(["Facts", "Sources", "Notes"])
    with facts_tab:
        for f in research.facts:
            st.write(f"- [{f.applies_to}] (conf={f.confidence:.2f}) {f.text}")
            if f.source_ids:
                st.caption(f"  Sources: {', '.join(f.source_ids)}")
    with sources_tab:
        if research.sources:
            rows = [{"ID": s.id, "Title": s.title, "Publisher": s.publisher,
                     "Type": s.source_type, "Trust": f"{s.trust_score:.2f}", "URL": s.url}
                    for s in research.sources]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No sources.")
    with notes_tab:
        if research.unresolved_questions:
            st.write("**Unresolved questions:**")
            for q in research.unresolved_questions:
                st.write(f"- {q}")
        if research.safety_notes:
            st.warning("**Safety notes:**")
            for n in research.safety_notes:
                st.write(f"- {n}")
        if not research.unresolved_questions and not research.safety_notes:
            st.caption("No issues.")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Script
# ──────────────────────────────────────────────────────────────────────────────

def tab_script() -> None:
    st.header("Script")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]
    if not pstate.topic:
        st.warning("This job has no topic.")
        return

    st.write(f"**Topic:** {pstate.topic.title}")

    if pstate.script:
        _display_script(pstate.script)
        problems = make_script_service().validate_script(pstate.script)
        if problems:
            st.warning(f"{len(problems)} validation issues:")
            for p in problems:
                st.write(f"- {p}")
        else:
            st.success("Script passes validation.")
        planner = make_scene_planner()
        plans = planner.plan_from_script(pstate.script)
        if plans:
            st.subheader("Scene Plan")
            st.dataframe([
                {"#": p.index, "Pose": p.mascot_pose.value, "Focus": p.focus.value,
                 "Dur": f"{p.duration_hint_seconds:.1f}s", "Phrase": ", ".join(p.on_screen_phrases),
                 "Transition": p.transition.value, "Motion": p.image_motion.value}
                for p in plans
            ], use_container_width=True, hide_index=True)
        if st.button("Re-generate script"):
            _generate_script(pstate)
    else:
        llm = get_llm_provider()
        if not llm:
            st.warning("LLM provider not configured. You can load a script from fixture.")
        else:
            with st.form("script_opts"):
                niche = st.text_input("Niche", value="food facts")
                language = st.selectbox("Language", ["en", "ro"], index=0)
                target_dur = st.slider("Target duration (seconds)", 15, 120, 60)
                submitted = st.form_submit_button("Generate script", type="primary")
            if submitted:
                _generate_script(pstate, niche, language, target_dur)

        fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "script_package.json"
        if fixture_path.exists() and not pstate.script:
            st.divider()
            if st.button("Load script from fixture"):
                data = json.loads(fixture_path.read_text(encoding="utf-8"))
                pstate.script = ScriptPackage(**data)
                pstate.checkpoint(Stage.SCRIPT_COMPLETE)
                state["stage"] = pstate.current_stage.value
                st.rerun()


def _generate_script(pstate: PipelineState, niche: str = "food facts",
                     language: str = "en", target_dur: int = 60) -> None:
    svc = make_script_service()
    research_facts = []
    if pstate.research:
        research_facts = [f.text for f in pstate.research.facts]
    try:
        with st.spinner("Generating script..."):
            settings = get_settings()
            script = run_async(svc.generate_script(
                topic=pstate.topic,
                niche=niche,
                language=language,
                target_duration_seconds=target_dur,
                research_facts=research_facts,
                canvas_width=settings.video_width,
                canvas_height=settings.video_height,
            ))
        pstate.script = script
        pstate.checkpoint(Stage.SCRIPT_COMPLETE)
        st.success(f"Script generated: {script.word_count} words, {len(script.scenes)} scenes")
        st.rerun()
    except Exception as e:
        st.error(f"Script generation failed: {e}")


def _display_script(script: ScriptPackage) -> None:
    meta_col, dur_col, words_col = st.columns(3)
    meta_col.metric("Hook", script.hook[:40] + "..." if len(script.hook) > 40 else script.hook)
    dur_col.metric("Est. Duration", f"{script.estimated_duration_seconds:.0f}s")
    words_col.metric("Word Count", script.word_count)

    st.write(f"**Caption:** {script.caption}")
    if script.hashtags:
        st.write("**Hashtags:** " + " ".join(f"#{h}" for h in script.hashtags))

    if script.claims:
        st.subheader("Claims")
        st.dataframe([
            {"ID": c.id, "Text": c.text[:60], "Risk": c.risk_level,
             "Confidence": f"{c.confidence:.2f}", "Sources": len(c.supporting_source_ids)}
            for c in script.claims
        ], use_container_width=True, hide_index=True)

    st.subheader("Scenes")
    for scene in script.scenes:
        with st.expander(f"Scene {scene.index}: {scene.narration[:60]}..."):
            st.write(f"**Narration:** {scene.narration}")
            st.write(f"**Duration:** {scene.duration_hint_seconds:.1f}s")
            st.write(f"**Pose:** {scene.mascot_pose.value}")
            st.write(f"**Focus:** {scene.focus.value}")
            st.write(f"**Transition:** {scene.transition.value}")
            st.write(f"**Motion:** {scene.image_motion.value}")
            if scene.on_screen_phrases:
                st.write(f"**Phrases:** {', '.join(scene.on_screen_phrases)}")
            if scene.emphasis:
                st.write(f"**Emphasis:** {', '.join(scene.emphasis)}")

    st.subheader("Full Narration")
    st.text_area("Narration text", script.narration_text, height=150, key="full_narration_display")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Fact Check
# ──────────────────────────────────────────────────────────────────────────────

def tab_fact_check() -> None:
    st.header("Fact Check")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]
    if not pstate.script:
        st.warning("Generate or load a script first.")
        return
    if not pstate.script.claims:
        st.info("This script has no claims to verify.")
        if st.button("Mark verification complete"):
            pstate.verification = VerificationResult(approved=True, claim_results=[])
            pstate.checkpoint(Stage.VERIFICATION_COMPLETE)
            st.rerun()
        return

    if pstate.verification:
        _display_verification(pstate.verification)
        if st.button("Re-run verification"):
            _run_fact_check(pstate)
    else:
        if st.button("Run fact check", type="primary"):
            _run_fact_check(pstate)


def _run_fact_check(pstate: PipelineState) -> None:
    svc = make_fact_check_service()
    research = pstate.research or ResearchPackage(
        topic=pstate.topic.title,
        left_item=pstate.topic.comparison_left,
        right_item=pstate.topic.comparison_right,
    )
    try:
        with st.spinner("Verifying claims..."):
            result = run_async(svc.verify(
                narration=pstate.script.narration_text,
                claims=pstate.script.claims,
                research=research,
                left_item=pstate.topic.comparison_left,
                right_item=pstate.topic.comparison_right,
                angle=pstate.topic.angle,
            ))
        pstate.verification = result
        pstate.checkpoint(Stage.VERIFICATION_COMPLETE)
        if result.approved:
            st.success("All claims verified successfully.")
        else:
            st.warning(f"Verification found issues.")
        st.rerun()
    except Exception as e:
        st.error(f"Fact check failed: {e}")


def _display_verification(result: VerificationResult) -> None:
    verdict_col, claims_col = st.columns(2)
    verdict_col.metric("Approved", "Yes" if result.approved else "No")
    supported = sum(1 for cr in result.claim_results if cr.supported)
    claims_col.metric("Claims Supported", f"{supported}/{len(result.claim_results)}")

    st.subheader("Claim Results")
    for cr in result.claim_results:
        icon = ":white_check_mark:" if cr.supported else ":x:"
        sev = cr.severity
        with st.expander(f"{icon} {cr.claim_id} — {sev}"):
            st.write(f"**Supported:** {cr.supported}")
            st.write(f"**Severity:** {cr.severity}")
            st.write(f"**Explanation:** {cr.explanation}")
            if cr.source_ids:
                st.write(f"**Sources:** {', '.join(cr.source_ids)}")

    if result.required_changes:
        st.subheader("Required Changes")
        for change in result.required_changes:
            st.warning(f"- {change}")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Images
# ──────────────────────────────────────────────────────────────────────────────

def tab_images() -> None:
    st.header("Images")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]
    if not pstate.topic:
        st.warning("This job has no topic.")
        return

    st.write(f"**Left:** {pstate.topic.comparison_left}")
    st.write(f"**Right:** {pstate.topic.comparison_right}")

    img_svc = make_image_service()
    fixture_left = PROJECT_ROOT / "tests" / "fixtures" / "left.png"
    fixture_right = PROJECT_ROOT / "tests" / "fixtures" / "right.png"

    left_path = pstate._work_dir / "left_image.png" if hasattr(pstate, "_work_dir") else None
    right_path = pstate._work_dir / "right_image.png" if hasattr(pstate, "_work_dir") else None

    current_left = pstate._work_dir / "left_image.png" if hasattr(pstate, "_work_dir") else None

    left_col, right_col = st.columns(2)

    image_provider = get_image_provider()

    with left_col:
        st.subheader(pstate.topic.comparison_left)
        if fixture_left.exists():
            st.image(str(fixture_left), caption="Fixture", use_container_width=True)
        st.text_input("Left image URL", key="left_img_url",
                      placeholder="https://... (optional)")
        if st.button("Acquire left image", key="acquire_left"):
            _acquire_image(img_svc, pstate.topic.comparison_left,
                           pstate._work_dir / "left_image.png",
                           st.session_state.get("left_img_url", ""))

    with right_col:
        st.subheader(pstate.topic.comparison_right)
        if fixture_right.exists():
            st.image(str(fixture_right), caption="Fixture", use_container_width=True)
        st.text_input("Right image URL", key="right_img_url",
                      placeholder="https://... (optional)")
        if st.button("Acquire right image", key="acquire_right"):
            _acquire_image(img_svc, pstate.topic.comparison_right,
                           pstate._work_dir / "right_image.png",
                           st.session_state.get("right_img_url", ""))

    st.divider()
    st.subheader("Normalize images")
    norm_left = pstate._work_dir / "left_normalized.png"
    norm_right = pstate._work_dir / "right_normalized.png"
    if st.button("Normalize & create comparison canvas"):
        left_src = pstate._work_dir / "left_image.png"
        right_src = pstate._work_dir / "right_image.png"
        if not left_src.exists():
            left_src = fixture_left
        if not right_src.exists():
            right_src = fixture_right
        try:
            img_svc.normalize(left_src, right_src, norm_left, norm_right)
            canvas_path = pstate._work_dir / "comparison_canvas.png"
            img_svc.create_comparison_canvas(left_src, right_src, canvas_path)
            st.success("Images normalized.")
            st.image(str(canvas_path), caption="Comparison canvas", use_container_width=True)
            pstate.checkpoint(Stage.ASSETS_COMPLETE)
            st.rerun()
        except Exception as e:
            st.error(f"Normalization failed: {e}")


def _acquire_image(svc: ImageService, item: str, output: Path, url: str) -> None:
    try:
        run_async(svc.generate_or_acquire(item, output, url or None))
        st.success(f"Image for '{item}' saved.")
        st.image(str(output), use_container_width=True)
    except Exception as e:
        st.error(f"Failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Render
# ──────────────────────────────────────────────────────────────────────────────

def tab_render() -> None:
    st.header("Render Video")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]

    spec_tab, editor_tab, render_tab = st.tabs(["Auto-build from Script", "Scene Editor", "Render & Preview"])

    with spec_tab:
        _render_auto_spec(pstate)

    with editor_tab:
        _render_scene_editor(pstate)

    with render_tab:
        _render_execute(pstate)


def _render_auto_spec(pstate: PipelineState) -> None:
    st.subheader("Build spec from script scene plan")

    script = pstate.script
    if not script:
        st.info("Generate or load a script first.")
        return

    planner = make_scene_planner()
    plans = planner.plan_from_script(script)
    if not plans:
        st.warning("Scene planner produced no scenes.")
        return

    fixture_left = PROJECT_ROOT / "tests" / "fixtures" / "left.png"
    fixture_right = PROJECT_ROOT / "tests" / "fixtures" / "right.png"
    fixture_audio = PROJECT_ROOT / "tests" / "fixtures" / "narration.mp3"

    norm_left = pstate._work_dir / "left_image.png"
    norm_right = pstate._work_dir / "right_image.png"

    left_image = norm_left if norm_left.exists() else fixture_left
    right_image = norm_right if norm_right.exists() else fixture_right

    labels = pstate.topic.title.split(" vs ") if " vs " in pstate.topic.title else [
        pstate.topic.comparison_left, pstate.topic.comparison_right
    ]
    left_label = labels[0] if labels else "Left"
    right_label = labels[1] if len(labels) > 1 else "Right"

    spec = _build_spec_from_plans(
        title=script.title,
        left_label=left_label,
        right_label=right_label,
        left_image=left_image,
        right_image=right_image,
        audio=fixture_audio,
        plans=plans,
        narration=script.narration_text,
    )

    st.write(f"**Title:** {spec.title}")
    st.write(f"**Scenes:** {len(spec.scenes)}")
    st.write(f"**Duration:** {spec.total_duration:.1f}s")

    st.dataframe([
        {"#": i, "Start": f"{s.start:.1f}", "End": f"{s.end:.1f}",
         "Pose": s.pose.value, "Phrase": s.phrase, "Focus": s.focus.value}
        for i, s in enumerate(spec.scenes)
    ], use_container_width=True, hide_index=True)

    st.session_state.render_spec = spec
    st.success("Spec built. Go to the Render tab to render.")


def _build_spec_from_plans(
    title: str,
    left_label: str,
    right_label: str,
    left_image: Path,
    right_image: Path,
    audio: Path,
    plans: list[ScenePlan],
    narration: str = "",
) -> RenderSpec:
    scenes: list[SceneSpec] = []
    cumulative = 0.0
    for plan in plans:
        dur = plan.duration_hint_seconds
        scenes.append(SceneSpec(
            start=round(cumulative, 2),
            end=round(cumulative + dur, 2),
            pose=plan.mascot_pose,
            phrase=plan.on_screen_phrases[0] if plan.on_screen_phrases else "",
            focus=plan.focus,
            image_motion=plan.image_motion,
            transition=plan.transition,
        ))
        cumulative += dur

    if not narration:
        narration = " ".join(p.narration for p in plans)

    return RenderSpec(
        title=title,
        left_label=left_label,
        right_label=right_label,
        left_image=left_image,
        right_image=right_image,
        audio=audio,
        scenes=scenes,
        narration_text=narration,
    )


def _render_scene_editor(pstate: PipelineState) -> None:
    st.subheader("Scene Editor")

    if st.session_state.get("render_spec") is None:
        if pstate.script:
            if st.button("Auto-build spec from script"):
                _render_auto_spec(pstate)
                st.rerun()
        fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "render_sample.json"
        if fixture_path.exists():
            if st.button("Load default fixture spec"):
                data = json.loads(fixture_path.read_text(encoding="utf-8"))
                for key in ("left_image", "right_image", "audio"):
                    if key in data and not Path(data[key]).is_absolute():
                        data[key] = str(PROJECT_ROOT / data[key])
                st.session_state.render_spec = RenderSpec(**data)
                st.rerun()
        return

    spec: RenderSpec = st.session_state.render_spec

    with st.expander("Spec metadata", expanded=True):
        meta_col1, meta_col2 = st.columns(2)
        with meta_col1:
            spec.title = st.text_input("Title", value=spec.title, key="se_title")
            spec.left_label = st.text_input("Left label", value=spec.left_label, key="se_left_label")
        with meta_col2:
            spec.right_label = st.text_input("Right label", value=spec.right_label, key="se_right_label")
            template_name = st.text_input("Template", value=spec.template, key="se_template")
            spec.template = template_name

        img_col1, img_col2, aud_col = st.columns(3)
        with img_col1:
            left_path_str = st.text_input("Left image", value=str(spec.left_image), key="se_left_img")
            spec.left_image = Path(left_path_str)
        with img_col2:
            right_path_str = st.text_input("Right image", value=str(spec.right_image), key="se_right_img")
            spec.right_image = Path(right_path_str)
        with aud_col:
            audio_path_str = st.text_input("Audio", value=str(spec.audio), key="se_audio")
            spec.audio = Path(audio_path_str)

        narration = st.text_area("Narration text", value=spec.narration_text, height=100, key="se_narration")
        spec.narration_text = narration

    st.write(f"**{len(spec.scenes)} scenes** — Total: {spec.total_duration:.1f}s")

    for i, scene in enumerate(spec.scenes):
        with st.expander(f"Scene {i}: {scene.phrase or '(no phrase)'} — {scene.start:.1f}s to {scene.end:.1f}s"):
            sc_col1, sc_col2, sc_col3, sc_col4 = st.columns(4)
            with sc_col1:
                pose = st.selectbox("Pose", POSE_OPTIONS,
                                    index=POSE_OPTIONS.index(scene.pose.value),
                                    key=f"se_pose_{i}")
                scene.pose = MascotPose(pose)
            with sc_col2:
                focus = st.selectbox("Focus", FOCUS_OPTIONS,
                                     index=FOCUS_OPTIONS.index(scene.focus.value),
                                     key=f"se_focus_{i}")
                scene.focus = Focus(focus)
            with sc_col3:
                motion = st.selectbox("Motion", MOTION_OPTIONS,
                                      index=MOTION_OPTIONS.index(scene.image_motion.value),
                                      key=f"se_motion_{i}")
                scene.image_motion = ImageMotion(motion)
            with sc_col4:
                trans = st.selectbox("Transition", TRANSITION_OPTIONS,
                                    index=TRANSITION_OPTIONS.index(scene.transition.value),
                                    key=f"se_trans_{i}")
                scene.transition = Transition(trans)

            time_col1, time_col2, phrase_col = st.columns([1, 1, 3])
            with time_col1:
                start = st.number_input("Start", value=float(scene.start), min_value=0.0,
                                        step=0.5, key=f"se_start_{i}")
            with time_col2:
                end = st.number_input("End", value=float(scene.end), min_value=0.1,
                                      step=0.5, key=f"se_end_{i}")
            with phrase_col:
                phrase = st.text_input("On-screen phrase", value=scene.phrase, key=f"se_phrase_{i}")

            scene.start = float(start)
            scene.end = float(end)
            scene.phrase = phrase

            if st.button("Remove scene", key=f"se_remove_{i}"):
                spec.scenes.pop(i)
                st.rerun()

    add_col, preview_col = st.columns(2)
    with add_col:
        if st.button("+ Add scene"):
            last_end = spec.scenes[-1].end if spec.scenes else 0.0
            spec.scenes.append(SceneSpec(
                start=last_end,
                end=last_end + 4.0,
                pose=MascotPose.NEUTRAL,
                phrase="",
                focus=Focus.NEUTRAL,
                image_motion=ImageMotion.SLOW_ZOOM_IN,
                transition=Transition.QUICK_FADE,
            ))
            st.rerun()

    with preview_col:
        if st.button("Preview frame (first scene)"):
            _preview_frame(spec)

    st.divider()
    export_col1, export_col2 = st.columns(2)
    with export_col1:
        if st.button("Save spec to output"):
            out_dir = PROJECT_ROOT / "output" / "specs"
            out_dir.mkdir(parents=True, exist_ok=True)
            spec_path = out_dir / f"{pstate.job_id}_spec.json"
            spec_path.write_text(
                json.dumps(spec.model_dump(mode="json"), indent=2, default=str),
                encoding="utf-8",
            )
            st.success(f"Saved: {spec_path}")
    with export_col2:
        if st.button("Load spec from file"):
            st.session_state["_show_spec_loader"] = True

    if st.session_state.get("_show_spec_loader"):
        loader_path = st.text_input("Spec file path", value="", key="se_load_path")
        if st.button("Load", key="se_load_btn"):
            try:
                data = json.loads(Path(loader_path).read_text(encoding="utf-8"))
                for key in ("left_image", "right_image", "audio"):
                    if key in data and not Path(data[key]).is_absolute():
                        data[key] = str(PROJECT_ROOT / data[key])
                st.session_state.render_spec = RenderSpec(**data)
                st.session_state._show_spec_loader = False
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")


def _preview_frame(spec: RenderSpec) -> None:
    try:
        settings = get_settings()
        template = load_template(spec.template, settings.templates_dir)
        compositor = Compositor(template, settings.resolve_font())
        frame = compositor.compose_frame(spec, spec.scenes[0])
        st.image(frame, caption=f"Scene 0 preview — {spec.scenes[0].phrase}", use_container_width=True)
    except Exception as e:
        st.error(f"Preview failed: {e}")


def _render_execute(pstate: PipelineState) -> None:
    st.subheader("Render & Preview")

    spec = st.session_state.get("render_spec")
    if not spec:
        st.info("Build or load a spec first (Auto-build or Scene Editor tabs).")
        return

    st.write(f"**Title:** {spec.title}")
    st.write(f"**Scenes:** {len(spec.scenes)} | **Duration:** {spec.total_duration:.1f}s")

    output_col, tts_col = st.columns(2)
    with output_col:
        output_dir = st.text_input(
            "Output directory",
            value=str(PROJECT_ROOT / "output" / pstate.job_id),
            key="re_output_dir",
        )
    with tts_col:
        use_tts = st.checkbox("Use TTS narration", value=bool(spec.tts) or bool(spec.narration_text),
                               key="re_use_tts",
                               help="If narration_text is set and TTS provider is available")
        if use_tts:
            tts = get_tts_provider()
            if not tts:
                st.warning("TTS provider not configured. Will use audio file from spec.")
            else:
                voice_id = st.text_input(
                    "Voice ID",
                    value=os.environ.get("ELEVENLABS_VOICE_ID_EN", ""),
                    key="re_voice_id",
                )

    if st.button("Render video", type="primary"):
        svc = make_render_service()

        render_spec = spec.model_copy(deep=True)

        if use_tts and spec.narration_text:
            tts = get_tts_provider()
            if tts and voice_id:
                from app.domain.models import TTSSettingsSpec
                render_spec.tts = TTSSettingsSpec(
                    voice_id=voice_id,
                    language="en",
                )

        try:
            with st.spinner("Rendering video (this may take a while)..."):
                result = svc.render(render_spec, Path(output_dir))
            st.session_state.render_result = result
            pstate.render_result = result
            pstate.cost_tracker.add(
                provider="local",
                operation="render",
                units=spec.total_duration,
                unit_type="seconds",
                estimated_cost_usd=0.0,
            )
            pstate.checkpoint(Stage.RENDER_COMPLETE)
            st.success("Render complete!")
            st.rerun()
        except Exception as e:
            st.error(f"Render failed: {e}")
            logger.exception("Render error")

    result = st.session_state.get("render_result")
    if result and isinstance(result, RenderResult):
        st.divider()
        st.subheader("Results")

        res_col1, res_col2, res_col3 = st.columns(3)
        res_col1.metric("Duration", f"{result.duration_seconds:.1f}s")
        res_col2.metric("Resolution", f"{result.resolution[0]}x{result.resolution[1]}")
        res_col3.metric("Scenes", result.scene_count)

        video_col, artifacts_col = st.columns([2, 1])
        with video_col:
            if result.video_path.exists():
                st.video(str(result.video_path))
            else:
                st.warning(f"Video not found: {result.video_path}")

        with artifacts_col:
            if result.poster_path.exists():
                st.image(str(result.poster_path), caption="Poster", use_container_width=True)
            if result.contact_sheet_path.exists():
                st.image(str(result.contact_sheet_path), caption="Contact sheet", use_container_width=True)

        with st.expander("Timeline JSON"):
            if result.timeline_path.exists():
                tl_data = json.loads(result.timeline_path.read_text(encoding="utf-8"))
                st.json(tl_data)

        if pstate._work_dir.exists():
            alignment_path = pstate.output_dir / "alignment.json"
            if alignment_path.exists():
                with st.expander("Alignment data"):
                    st.json(json.loads(alignment_path.read_text(encoding="utf-8")))


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Quality
# ──────────────────────────────────────────────────────────────────────────────

def tab_quality() -> None:
    st.header("Quality Check")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]

    result = pstate.render_result or st.session_state.get("render_result")
    if not result:
        st.warning("Render a video first.")
        return

    st.write(f"**Video:** {result.video_path}")

    if st.button("Run quality check", type="primary"):
        svc = make_quality_service()
        try:
            problems = svc.validate_video(result.video_path)
            content_problems = svc.validate_content(result, expected_scene_count=len(st.session_state.render_spec.scenes) if st.session_state.get("render_spec") else 0)
            problems.extend(content_problems)
            st.session_state.quality_problems = problems
            if not problems:
                pstate.checkpoint(Stage.QUALITY_COMPLETE)
                pstate.checkpoint(Stage.WAITING_FOR_APPROVAL)
                st.success("All quality checks passed!")
                st.rerun()
        except Exception as e:
            st.error(f"Quality check failed: {e}")

    problems = st.session_state.get("quality_problems")
    if problems is not None:
        if problems:
            st.error(f"{len(problems)} issues found:")
            for p in problems:
                st.write(f"- {p}")
        else:
            st.success("No quality issues.")

    st.divider()
    st.subheader("Generate Preview")
    if st.button("Generate low-res preview"):
        svc = make_quality_service()
        preview_path = pstate.output_dir / "preview.mp4"
        try:
            svc.generate_preview(result.video_path, preview_path)
            if preview_path.exists():
                st.video(str(preview_path))
        except Exception as e:
            st.error(f"Preview generation failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Tab: Publish & Analytics
# ──────────────────────────────────────────────────────────────────────────────

def tab_publish() -> None:
    st.header("Publish & Analytics")

    state = get_current_job()
    if not state:
        st.info("Create or select a job first.")
        return
    pstate: PipelineState = state["state"]

    result = pstate.render_result or st.session_state.get("render_result")
    if not result:
        st.warning("Render a video first.")
        return

    approve_col, reject_col = st.columns(2)
    with approve_col:
        if st.button("Approve", type="primary"):
            state["status"] = "APPROVED"
            pstate.checkpoint(Stage.APPROVED)
            st.success("Job approved.")
            st.rerun()
    with reject_col:
        if st.button("Reject"):
            state["status"] = "REJECTED"
            pstate.checkpoint(Stage.REJECTED)
            st.warning("Job rejected.")
            st.rerun()

    st.divider()
    st.subheader("Publish")

    pub_svc = make_publishing_service()

    with st.form("publish_form"):
        platform = st.selectbox("Platform", ["tiktok", "youtube", "instagram"])
        video_url = st.text_input("Video URL", value=str(result.video_path))
        caption = st.text_area("Caption",
                                value=pstate.script.caption if pstate.script else "")
        scheduled = st.text_input("Scheduled at (ISO, optional)", value="")
        privacy = st.selectbox("Privacy", ["PUBLIC", "MUTUAL_FOLLOW", "SELF_ONLY"])
        disclose_ai = st.checkbox("Disclose AI-generated", value=True)
        disclose_brand = st.checkbox("Disclose branded content", value=False)
        submitted = st.form_submit_button("Publish")

    if submitted:
        payload = PublicationPayload(
            platform=platform,
            video_url=video_url,
            caption=caption[:2200],
            scheduled_at=scheduled or None,
            privacy_level=privacy,
            disclose_ai_generated=disclose_ai,
            disclose_branded_content=disclose_brand,
        )
        try:
            with st.spinner("Publishing..."):
                pub_result = run_async(pub_svc.publish_to_platform(platform, payload))
            if pub_result.status == "published":
                st.success(f"Published to {platform}: {pub_result.publication_id}")
                state["status"] = "UPLOADED"
                pstate.checkpoint(Stage.UPLOADED)
            elif pub_result.status == "skipped":
                st.info(f"Skipped: {pub_result.error}")
            else:
                st.error(f"Publish failed: {pub_result.error}")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

    st.divider()
    st.subheader("Analytics")

    with st.form("analytics_form"):
        a_views = st.number_input("Views", min_value=0, value=0)
        a_likes = st.number_input("Likes", min_value=0, value=0)
        a_comments = st.number_input("Comments", min_value=0, value=0)
        a_shares = st.number_input("Shares", min_value=0, value=0)
        a_saves = st.number_input("Saves", min_value=0, value=0)
        a_watch = st.number_input("Avg watch time (s)", min_value=0.0, value=0.0)
        a_completion = st.slider("Completion rate", 0.0, 1.0, 0.0, 0.01)
        a_followers = st.number_input("Follower increase", min_value=0, value=0)
        a_revenue = st.number_input("Revenue ($)", min_value=0.0, value=0.0, step=0.01)
        platform_a = st.selectbox("Platform", ["tiktok", "youtube", "instagram"], key="a_platform")
        submitted = st.form_submit_button("Record analytics")

    if submitted:
        snapshot = AnalyticsSnapshot(
            job_id=pstate.job_id,
            platform=platform_a,
            views=int(a_views),
            likes=int(a_likes),
            comments=int(a_comments),
            shares=int(a_shares),
            saves=int(a_saves),
            average_watch_time=float(a_watch) if a_watch else None,
            completion_rate=float(a_completion) if a_completion else None,
            follower_increase=int(a_followers),
            revenue=float(a_revenue) if a_revenue else None,
            captured_at=_ts(),
        )
        st.session_state.analytics.record(snapshot)
        st.success("Analytics recorded.")

    analytics_svc = st.session_state.analytics
    snapshots = analytics_svc.get_snapshots(pstate.job_id)
    if snapshots:
        st.subheader("Recorded Analytics")
        agg = analytics_svc.aggregate(pstate.job_id)
        st.json(agg)

        rows = [{"Platform": s.platform, "Views": s.views, "Likes": s.likes,
                 "Comments": s.comments, "Shares": s.shares, "Saves": s.saves,
                 "Captured": s.captured_at[:19]}
                for s in snapshots]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        if agg.get("platforms"):
            for p_name, p_data in agg["platforms"].items():
                st.write(f"**{p_name}**: {p_data['views']} views, {p_data['likes']} likes")

    daily = analytics_svc.get_daily_summary()
    st.divider()
    st.caption(f"Dashboard summary: {daily.get('total_jobs', 0)} jobs, "
               f"{daily.get('total_views', 0)} total views")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Short Video Platform",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🎬 Short Video Platform")
    st.caption("Self-contained dashboard — no separate API server required")

    init_state()
    render_sidebar()

    tabs = st.tabs([
        "📊 Dashboard",
        "💡 Topic",
        "🔍 Research",
        "📝 Script",
        "✅ Fact Check",
        "🖼️ Images",
        "🎬 Render",
        "✔️ Quality",
        "📤 Publish",
    ])

    with tabs[0]:
        tab_dashboard()
    with tabs[1]:
        tab_topic()
    with tabs[2]:
        tab_research()
    with tabs[3]:
        tab_script()
    with tabs[4]:
        tab_fact_check()
    with tabs[5]:
        tab_images()
    with tabs[6]:
        tab_render()
    with tabs[7]:
        tab_quality()
    with tabs[8]:
        tab_publish()


REFERENCE_STAGE_LABELS = {
    "preflight": "Checking configuration",
    "topic": "Choosing the comparison",
    "research_assets": "Finding sources and images",
    "script_verification": "Writing and verifying the script",
    "direction_tts": "Creating narration and direction",
    "compiled": "Synchronizing captions and sound effects",
    "render": "Rendering the video",
    "quality": "Running final checks",
}

REFERENCE_LANGUAGE_LABELS = {
    "ro": "Romanian",
    "en": "English",
}


@st.cache_resource
def make_reference_generation_service():
    return build_reference_generation_service(get_settings())


def _reference_preflight(settings, language: str) -> list[str]:
    problems: list[str] = []
    if not settings.llm_api_key:
        problems.append("Missing OPENROUTER_API_KEY")
    if not settings.elevenlabs_api_key:
        problems.append("Missing ELEVENLABS_API_KEY")
    if not settings.search_api_key:
        problems.append("Missing SEARCH_API_KEY")
    if language == "ro" and not settings.elevenlabs_voice_id_ro:
        problems.append("Missing ELEVENLABS_VOICE_ID_RO")
    if language == "en" and not settings.elevenlabs_voice_id_en:
        problems.append("Missing ELEVENLABS_VOICE_ID_EN")
    mascot = MascotService(settings.mascots_dir)
    if mascot.validate_pose_images(mascot.available_poses):
        problems.append("Mascot transparency preparation is required")
    return problems


def _run_reference_generation(request: GenerationRequest, job_id: Optional[str] = None) -> None:
    status = st.status("Starting generation", expanded=True)
    started = datetime.now(timezone.utc)

    def progress(stage: str) -> None:
        label = REFERENCE_STAGE_LABELS.get(stage, stage)
        status.update(label=label, state="running")
        st.write(f"• {label}")

    try:
        active_job_id = job_id or str(uuid4())
        service = make_reference_generation_service()
        result = run_async(service.generate(request, progress, job_id=active_job_id))
        st.session_state.reference_result = result
        st.session_state.reference_error = None
        st.session_state.reference_retry_job_id = None
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        status.update(label=f"Video ready in {elapsed:.0f}s", state="complete")
    except Exception as error:
        st.session_state.reference_result = None
        st.session_state.reference_error = str(error)
        st.session_state.reference_retry_job_id = job_id or active_job_id
        status.update(label="Generation stopped", state="error")


def render_reference_page() -> None:
    settings = get_settings()
    st.title("Video generator")
    st.caption("Automatically create a comparison video in the reference-video style.")

    with st.expander("Advanced settings", expanded=False):
        topic_override = st.text_input("Optional comparison", placeholder="Coffee vs Tea")
        language = st.selectbox(
            "Language",
            ["ro", "en"],
            index=0,
            format_func=REFERENCE_LANGUAGE_LABELS.__getitem__,
        )
        duration = st.slider("Target duration", min_value=20, max_value=60, value=25, step=1)
        default_voice = settings.elevenlabs_voice_id_ro if language == "ro" else settings.elevenlabs_voice_id_en
        voice_id = st.text_input("Voice ID", value=default_voice)
        diagnostics = _reference_preflight(settings, language)
        if diagnostics:
            st.warning(" • ".join(diagnostics))
        else:
            st.success("Configuration is ready")

    request = GenerationRequest(
        topic_override=topic_override.strip() or None,
        language=language,
        target_duration_seconds=duration,
        voice_id=voice_id.strip() or None,
    )
    if st.button(
        "⚡ Generate video",
        type="primary",
        use_container_width=True,
        disabled=bool(_reference_preflight(settings, language)),
    ):
        _run_reference_generation(request)

    if st.session_state.get("reference_error"):
        st.error(st.session_state.reference_error)
        retry_job = st.session_state.get("reference_retry_job_id")
        if retry_job and st.button("Retry failed stage", use_container_width=True):
            _run_reference_generation(request, retry_job)

    result = st.session_state.get("reference_result")
    if result is None:
        return
    render = result.render_result
    st.success("Video is ready")
    if render.video_path.exists():
        st.video(str(render.video_path))
        st.download_button(
            "Download video",
            data=render.video_path.read_bytes(),
            file_name="video.mp4",
            mime="video/mp4",
            use_container_width=True,
        )
    columns = st.columns(3)
    columns[0].metric("Duration", f"{render.duration_seconds:.1f}s")
    columns[1].metric("Resolution", f"{render.resolution[0]}×{render.resolution[1]}")
    columns[2].metric("Cues", render.scene_count)
    with st.expander("Diagnostic artifacts"):
        for label, path in (
            ("Transcript", render.transcript_path),
            ("Direction", render.direction_path),
            ("Image provenance", render.image_provenance_path),
            ("Quality report", render.quality_report_path),
        ):
            if path and path.exists():
                st.download_button(
                    label,
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=f"artifact_{label}",
                )
    if st.button("Generate another video", use_container_width=True):
        st.session_state.reference_result = None
        st.session_state.reference_error = None
        st.session_state.reference_retry_job_id = None
        st.rerun()


def reference_main() -> None:
    st.set_page_config(
        page_title="Video generator",
        page_icon="🎬",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    init_state()
    render_reference_page()


if __name__ == "__main__":
    reference_main()
