from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from app.automation.database import AutomationDatabase, AutomationIdeaRow, AutomationJobRow, Base


class RecordingConnection:
    def __init__(self, events):
        self.events = events

    def execute(self, statement, parameters):
        self.events.append(("execute", str(statement), parameters))


class RecordingPostgresEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, events):
        self.events = events
        self.connection = RecordingConnection(events)

    @contextmanager
    def begin(self):
        self.events.append(("begin",))
        yield self.connection
        self.events.append(("commit",))


def test_postgres_schema_creation_is_serialized_with_an_advisory_lock(monkeypatch):
    events = []
    engine = RecordingPostgresEngine(events)
    database = AutomationDatabase.__new__(AutomationDatabase)
    database.engine = engine

    monkeypatch.setattr(
        Base.metadata,
        "create_all",
        lambda bind: events.append(("create_all", bind)),
    )

    database.create_schema()

    assert events[0] == ("begin",)
    assert events[1][0] == "execute"
    assert "pg_advisory_xact_lock" in events[1][1]
    assert events[2] == ("create_all", engine.connection)
    assert events[3][0] == "execute"
    assert "ADD COLUMN IF NOT EXISTS idea_id" in events[3][1]
    assert events[4] == ("commit",)


def test_idea_queue_schema_has_unique_pairs_and_job_link() -> None:
    assert AutomationIdeaRow.__table__.c.normalized_pair.unique is True
    assert "idea_id" in AutomationJobRow.__table__.c
