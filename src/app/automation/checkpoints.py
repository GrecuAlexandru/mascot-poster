from __future__ import annotations

import json
from pathlib import Path

from app.automation.models import RegenerationKind


INVALIDATED_STAGES = {
    RegenerationKind.SCRIPT: {
        "script_verification",
        "direction_tts",
        "social_description",
        "compiled",
        "render",
        "quality",
    },
    RegenerationKind.IMAGES: {
        "research_assets",
        "render",
        "quality",
    },
    RegenerationKind.FULL: {
        "topic",
        "research_assets",
        "script_verification",
        "direction_tts",
        "social_description",
        "compiled",
        "render",
        "quality",
    },
}


def invalidate_checkpoints(
    output_base: Path,
    job_id: str,
    kind: RegenerationKind | None,
) -> None:
    if kind is None:
        return
    pipeline_dir = Path(output_base) / job_id / "_pipeline"
    state_path = pipeline_dir / "state.json"
    stages = INVALIDATED_STAGES[kind]
    for stage in stages:
        (pipeline_dir / f"{stage}.json").unlink(missing_ok=True)
    if not state_path.is_file():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["completed"] = [
        stage for stage in state.get("completed", []) if stage not in stages
    ]
    if state.get("failed_stage") in stages:
        state["failed_stage"] = None
        state["error"] = None
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
