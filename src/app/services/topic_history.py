from __future__ import annotations

import json
import logging
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.domain.models import TopicSpec

logger = logging.getLogger(__name__)

class TopicHistoryService:
    def __init__(self, history_path: Path):
        self.history_path = history_path
        self._history: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.history_path.exists():
            try:
                self._history = json.loads(
                    self.history_path.read_text(encoding="utf-8")
                )
            except Exception as e:
                logger.warning(f"Could not load topic history: {e}")
                self._history = []

    def _save(self) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(
            json.dumps(self._history, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.casefold())
        return "".join(
            character
            for character in decomposed
            if character.isalnum() and not unicodedata.combining(character)
        )

    def _pair_key(self, left: str, right: str) -> str:
        return f"{self._normalize(left)}|{self._normalize(right)}"

    def exists(self, left: str, right: str) -> bool:
        target = self._pair_key(left, right)
        target_rev = self._pair_key(right, left)
        for entry in self._history:
            existing = self._pair_key(
                entry.get("left", ""), entry.get("right", "")
            )
            if existing == target or existing == target_rev:
                return True
        return False

    def add(
        self,
        title: str,
        left: str,
        right: str,
        angle: str = "",
        job_id: str = "",
    ) -> dict:
        if self.exists(left, right):
            logger.info(f"Topic already in history: {left} vs {right}")
            existing = self._find(left, right)
            if existing:
                return existing
        entry = {
            "title": title,
            "left": left,
            "right": right,
            "angle": angle,
            "job_id": job_id,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        self._history.append(entry)
        self._save()
        logger.info(f"Topic added to history: {left} vs {right} (total: {len(self._history)})")
        return entry

    def add_from_topic(self, topic: TopicSpec, job_id: str = "") -> dict:
        return self.add(
            title=topic.title,
            left=topic.comparison_left,
            right=topic.comparison_right,
            angle=topic.angle,
            job_id=job_id,
        )

    def _find(self, left: str, right: str) -> Optional[dict]:
        target = self._pair_key(left, right)
        target_rev = self._pair_key(right, left)
        for entry in self._history:
            existing = self._pair_key(
                entry.get("left", ""), entry.get("right", "")
            )
            if existing == target or existing == target_rev:
                return entry
        return None

    def get_all(self) -> list[dict]:
        return list(self._history)

    def get_normalized_pairs(self) -> set[str]:
        pairs: set[str] = set()
        for entry in self._history:
            pairs.add(self._pair_key(
                entry.get("left", ""), entry.get("right", "")
            ))
            pairs.add(self._pair_key(
                entry.get("right", ""), entry.get("left", "")
            ))
        return pairs

    def get_topic_titles(self) -> list[str]:
        return [e.get("title", "") for e in self._history]

    @property
    def count(self) -> int:
        return len(self._history)

    def clear(self) -> None:
        self._history = []
        self._save()
        logger.info("Topic history cleared")
