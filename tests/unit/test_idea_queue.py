from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.automation.database import AutomationDatabase
from app.automation.idea_queue_service import IdeaQueueService
from app.automation.job_service import JobService
from app.automation.models import IdeaDraft, IdeaState


def build_services(tmp_path: Path, legacy_history=None):
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    return JobService(database), IdeaQueueService(database, legacy_history)


def draft(
    idea_id: str,
    left: str,
    right: str,
    title: str | None = None,
) -> IdeaDraft:
    return IdeaDraft(
        idea_id=idea_id,
        title=title or f"{left} vs {right}",
        left=left,
        right=right,
        angle="Unghi editorial",
    )


def test_import_skips_reversed_duplicates_in_the_same_batch(tmp_path: Path) -> None:
    _, ideas = build_services(tmp_path)

    result = ideas.import_ideas([
        draft("IDEA-001", "Gem", "Dulceață"),
        draft("IDEA-002", "dulceata", "gem"),
    ])

    assert [item.idea_id for item in result.accepted] == ["IDEA-001"]
    assert [item.reason for item in result.skipped] == ["duplicate_pair"]
    assert result.accepted[0].state is IdeaState.QUEUED


def test_reimport_is_idempotent_and_checks_existing_jobs(tmp_path: Path) -> None:
    jobs, ideas = build_services(tmp_path)
    ideas.import_ideas([draft("IDEA-001", "Gem", "Dulceață")])
    jobs.create_job(
        target_at=datetime(2026, 7, 18, 9, tzinfo=timezone.utc),
        topic_override="Cafea vs Ceai",
    )

    result = ideas.import_ideas([
        draft("IDEA-001", "Gem", "Dulceață"),
        draft("IDEA-003", "ceai", "cafea"),
    ])

    assert result.accepted == []
    assert [item.reason for item in result.skipped] == [
        "duplicate_pair",
        "duplicate_pair",
    ]


def test_history_export_combines_used_queued_and_legacy_topics(tmp_path: Path) -> None:
    class LegacyHistory:
        def get_all(self):
            return [{
                "title": "Unt vs margarină",
                "left": "Unt",
                "right": "Margarină",
                "added_at": "2026-01-01T00:00:00+00:00",
            }]

    jobs, ideas = build_services(tmp_path, LegacyHistory())
    jobs.create_job(
        target_at=datetime(2026, 7, 18, 9, tzinfo=timezone.utc),
        topic_override="Cafea vs Ceai",
    )
    ideas.import_ideas([draft("IDEA-001", "Gem", "Dulceață")])

    history = ideas.export_history()

    assert [item.title for item in history.used] == ["Cafea vs Ceai"]
    assert [item.title for item in history.queued] == ["Gem vs Dulceață"]
    assert [item.title for item in history.legacy] == ["Unt vs margarină"]
    assert "## Used or attempted ideas" in history.markdown
    assert "- Cafea vs Ceai" in history.markdown
    assert "## Ideas already queued" in history.markdown
    assert "- Gem vs Dulceață" in history.markdown
    assert "- Unt vs margarină" in history.markdown


def test_job_creation_consumes_oldest_idea_once_and_links_records(tmp_path: Path) -> None:
    jobs, ideas = build_services(tmp_path)
    imported = ideas.import_ideas([
        draft("IDEA-001", "Gem", "Dulceață"),
        draft("IDEA-002", "Cafea", "Ceai"),
    ])
    target = datetime(2026, 7, 18, 9, tzinfo=timezone.utc)

    first = jobs.create_job_from_next_idea(target_at=target)
    second = jobs.create_job_from_next_idea(target_at=target)
    empty = jobs.create_job_from_next_idea(target_at=target)

    assert first is not None
    assert first.topic_override == "Gem vs Dulceață"
    assert first.idea_id == imported.accepted[0].id
    assert second is not None
    assert second.topic_override == "Cafea vs Ceai"
    assert second.idea_id == imported.accepted[1].id
    assert empty is None
    consumed = ideas.list_all()
    assert [item.state for item in consumed] == [
        IdeaState.CONSUMED,
        IdeaState.CONSUMED,
    ]
    assert [item.automation_job_id for item in consumed] == [first.id, second.id]
