from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class DescriptionHistoryService:
    def __init__(self, path: Path, max_entries: int = 50):
        self.path = path
        self.max_entries = max_entries
        self._entries = self._load()

    def recent(self, limit: int = 10) -> list[str]:
        return [
            str(entry["description"])
            for entry in reversed(self._entries[-max(0, limit) :])
            if entry.get("description")
        ]

    def add(self, topic_title: str, description: str) -> None:
        topic_title = topic_title.strip()
        description = description.strip()
        if not description:
            return
        if any(
            entry.get("topic") == topic_title
            and entry.get("description") == description
            for entry in self._entries
        ):
            return
        self._entries.append(
            {
                "topic": topic_title,
                "description": description,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._entries = self._entries[-self.max_entries :]
        self._save()

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [entry for entry in payload if isinstance(entry, dict)]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self._entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)
