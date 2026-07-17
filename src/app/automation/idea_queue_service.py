from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.automation.database import AutomationDatabase, AutomationIdeaRow, AutomationJobRow
from app.automation.models import (
    AutomationIdea,
    IdeaDraft,
    IdeaHistoryEntry,
    IdeaHistoryExport,
    IdeaImportResult,
    IdeaState,
    SkippedIdea,
)


class IdeaQueueService:
    def __init__(self, database: AutomationDatabase, legacy_history: Optional[object] = None):
        self.database = database
        self.legacy_history = legacy_history

    @staticmethod
    def normalize_item(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        return "".join(
            character
            for character in decomposed
            if character.isalnum() and not unicodedata.combining(character)
        )

    @classmethod
    def normalize_pair(cls, left: str, right: str) -> str:
        return "|".join(sorted((cls.normalize_item(left), cls.normalize_item(right))))

    @staticmethod
    def parse_pair(value: str) -> tuple[str, str] | None:
        parts = re.split(
            r"\s+(?:vs\.?|versus)\s+",
            value.strip(),
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        if len(parts) != 2 or not all(part.strip() for part in parts):
            return None
        return parts[0].strip(), parts[1].strip()

    def import_ideas(self, drafts: list[IdeaDraft]) -> IdeaImportResult:
        accepted: list[AutomationIdea] = []
        skipped: list[SkippedIdea] = []
        with self.database.session() as session:
            existing = set(session.scalars(select(AutomationIdeaRow.normalized_pair)).all())
            existing.update(self._job_pairs(session))
            existing.update(self._legacy_pairs())
            base_time = self._now()
            for index, draft in enumerate(drafts):
                key = self.normalize_pair(draft.left, draft.right)
                if not all(key.split("|")) or key in existing:
                    skipped.append(self._skipped(draft, "duplicate_pair"))
                    continue
                row = AutomationIdeaRow(
                    id=str(uuid4()),
                    external_id=draft.idea_id,
                    title=draft.title.strip(),
                    left_item=draft.left.strip(),
                    right_item=draft.right.strip(),
                    angle=draft.angle.strip(),
                    normalized_pair=key,
                    state=IdeaState.QUEUED.value,
                    created_at=base_time + timedelta(microseconds=index),
                )
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    skipped.append(self._skipped(draft, "duplicate_pair"))
                    continue
                existing.add(key)
                accepted.append(self._snapshot(row))
        return IdeaImportResult(accepted=accepted, skipped=skipped)

    def list_all(self) -> list[AutomationIdea]:
        with self.database.session() as session:
            rows = session.scalars(
                select(AutomationIdeaRow).order_by(
                    AutomationIdeaRow.created_at,
                    AutomationIdeaRow.id,
                )
            ).all()
            return [self._snapshot(row) for row in rows]

    def export_history(self) -> IdeaHistoryExport:
        with self.database.session() as session:
            jobs = session.scalars(
                select(AutomationJobRow).order_by(
                    AutomationJobRow.created_at,
                    AutomationJobRow.id,
                )
            ).all()
            ideas = session.scalars(
                select(AutomationIdeaRow).order_by(
                    AutomationIdeaRow.created_at,
                    AutomationIdeaRow.id,
                )
            ).all()
            used = self._used_entries(jobs, ideas)
            queued = [
                IdeaHistoryEntry(
                    title=row.title,
                    left=row.left_item,
                    right=row.right_item,
                    source="queue",
                )
                for row in ideas
                if row.state == IdeaState.QUEUED.value
            ]
        legacy = self._legacy_entries()
        return IdeaHistoryExport(
            used=used,
            queued=queued,
            legacy=legacy,
            markdown=self._markdown(used, queued, legacy),
        )

    def _job_pairs(self, session) -> set[str]:
        result: set[str] = set()
        rows = session.execute(
            select(AutomationJobRow.topic_override, AutomationJobRow.topic)
        ).all()
        for override, topic in rows:
            pair = self.parse_pair(override or "") or self.parse_pair(topic or "")
            if pair:
                result.add(self.normalize_pair(*pair))
        return result

    def _legacy_pairs(self) -> set[str]:
        return {
            self.normalize_pair(entry.left, entry.right)
            for entry in self._legacy_entries()
            if entry.left and entry.right
        }

    def _legacy_entries(self) -> list[IdeaHistoryEntry]:
        if self.legacy_history is None:
            return []
        getter = getattr(self.legacy_history, "get_all", None)
        if not callable(getter):
            return []
        entries: list[IdeaHistoryEntry] = []
        for value in getter():
            left = str(value.get("left", "")).strip()
            right = str(value.get("right", "")).strip()
            title = str(value.get("title", "")).strip() or f"{left} vs {right}"
            entries.append(
                IdeaHistoryEntry(
                    title=title,
                    left=left,
                    right=right,
                    source="legacy",
                )
            )
        return entries

    def _used_entries(self, jobs, ideas) -> list[IdeaHistoryEntry]:
        entries: list[IdeaHistoryEntry] = []
        seen: set[str] = set()
        for row in jobs:
            pair = self.parse_pair(row.topic_override or "") or self.parse_pair(row.topic or "")
            if not pair:
                continue
            key = self.normalize_pair(*pair)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                IdeaHistoryEntry(
                    title=f"{pair[0]} vs {pair[1]}",
                    left=pair[0],
                    right=pair[1],
                    source="automation_job",
                )
            )
        for row in ideas:
            if row.state != IdeaState.CONSUMED.value or row.normalized_pair in seen:
                continue
            seen.add(row.normalized_pair)
            entries.append(
                IdeaHistoryEntry(
                    title=row.title,
                    left=row.left_item,
                    right=row.right_item,
                    source="consumed_queue",
                )
            )
        return entries

    def _markdown(
        self,
        used: list[IdeaHistoryEntry],
        queued: list[IdeaHistoryEntry],
        legacy: list[IdeaHistoryEntry],
    ) -> str:
        seen: set[str] = set()

        def lines(entries: list[IdeaHistoryEntry]) -> list[str]:
            output: list[str] = []
            for entry in entries:
                key = (
                    self.normalize_pair(entry.left, entry.right)
                    if entry.left and entry.right
                    else self.normalize_item(entry.title)
                )
                if key in seen:
                    continue
                seen.add(key)
                output.append(f"- {entry.title}")
            return output or ["- (none)"]

        sections = [
            "# Mascot idea history",
            "",
            "## Used or attempted ideas",
            *lines(used),
            "",
            "## Ideas already queued",
            *lines(queued),
            "",
            "## Legacy topic history",
            *lines(legacy),
        ]
        return "\n".join(sections).strip() + "\n"

    @staticmethod
    def _snapshot(row: AutomationIdeaRow) -> AutomationIdea:
        return AutomationIdea(
            id=row.id,
            idea_id=row.external_id,
            title=row.title,
            left=row.left_item,
            right=row.right_item,
            angle=row.angle,
            state=IdeaState(row.state),
            created_at=row.created_at,
            consumed_at=row.consumed_at,
            automation_job_id=row.automation_job_id,
        )

    @staticmethod
    def _skipped(draft: IdeaDraft, reason: str) -> SkippedIdea:
        return SkippedIdea(idea_id=draft.idea_id, title=draft.title, reason=reason)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
