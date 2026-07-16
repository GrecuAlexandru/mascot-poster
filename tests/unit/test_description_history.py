from __future__ import annotations

import json
from pathlib import Path

from app.services.description_history import DescriptionHistoryService


def test_description_history_starts_empty_and_persists_utf8(tmp_path: Path) -> None:
    path = tmp_path / "description_history.json"
    history = DescriptionHistoryService(path)

    assert history.recent() == []

    history.add("Pâine vs lipie", "Pâine vs lipie 🥖 Tu ce alegi?")

    assert DescriptionHistoryService(path).recent() == [
        "Pâine vs lipie 🥖 Tu ce alegi?"
    ]
    assert "Pâine" in path.read_text(encoding="utf-8")


def test_description_history_suppresses_duplicates_and_returns_newest_first(
    tmp_path: Path,
) -> None:
    history = DescriptionHistoryService(tmp_path / "history.json")
    for index in range(12):
        history.add(f"Topic {index}", f"Description {index}")
    history.add("Topic 11", "Description 11")

    assert history.recent(10) == [f"Description {index}" for index in range(11, 1, -1)]
    assert len(json.loads(history.path.read_text(encoding="utf-8"))) == 12


def test_description_history_recovers_from_malformed_json_and_caps_entries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.json"
    path.write_text("not json", encoding="utf-8")
    history = DescriptionHistoryService(path, max_entries=3)

    assert history.recent() == []

    for index in range(5):
        history.add(f"Topic {index}", f"Description {index}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["description"] for entry in payload] == [
        "Description 2",
        "Description 3",
        "Description 4",
    ]
    assert all(set(entry) == {"topic", "description", "created_at"} for entry in payload)
