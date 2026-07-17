from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.automation.api import create_automation_router
from app.automation.database import AutomationDatabase
from app.automation.job_service import JobService


def build_client(tmp_path: Path) -> TestClient:
    database = AutomationDatabase(f"sqlite:///{tmp_path / 'automation.db'}")
    database.create_schema()
    service = JobService(database)
    app = FastAPI()
    app.include_router(create_automation_router(service, "test-secret"))
    return TestClient(app)


def test_private_api_rejects_missing_or_wrong_bearer_token(tmp_path: Path):
    client = build_client(tmp_path)

    assert client.get("/api/v1/automation/jobs/missing").status_code == 401
    response = client.get(
        "/api/v1/automation/jobs/missing",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


def test_n8n_can_create_and_read_a_durable_job(tmp_path: Path):
    client = build_client(tmp_path)
    target_at = datetime.now(timezone.utc) + timedelta(hours=2)
    headers = {"Authorization": "Bearer test-secret"}

    created = client.post(
        "/api/v1/automation/jobs",
        headers=headers,
        json={
            "target_at": target_at.isoformat(),
            "topic_override": "Cafea vs ceai",
            "language": "ro",
            "target_duration_seconds": 25,
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "CREATED"
    assert payload["job"]["state"] == "QUEUED"
    assert payload["job"]["topic_override"] == "Cafea vs ceai"
    fetched = client.get(
        f"/api/v1/automation/jobs/{payload['job']['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["job"]["id"]


def test_create_job_rejects_target_in_the_past(tmp_path: Path):
    client = build_client(tmp_path)
    response = client.post(
        "/api/v1/automation/jobs",
        headers={"Authorization": "Bearer test-secret"},
        json={"target_at": "2020-01-01T00:00:00Z"},
    )

    assert response.status_code == 422


def test_n8n_can_import_and_export_idea_history(tmp_path: Path):
    client = build_client(tmp_path)
    headers = {"Authorization": "Bearer test-secret"}

    imported = client.post(
        "/api/v1/automation/ideas/import",
        headers=headers,
        json={
            "ideas": [{
                "idea_id": "IDEA-001",
                "title": "Gem vs dulceață",
                "left": "Gem",
                "right": "Dulceață",
                "angle": "Textură și preparare",
            }]
        },
    )
    history = client.get(
        "/api/v1/automation/ideas/history",
        headers=headers,
    )

    assert imported.status_code == 200
    assert imported.json()["accepted"][0]["idea_id"] == "IDEA-001"
    assert history.status_code == 200
    assert history.json()["queued"][0]["title"] == "Gem vs dulceață"
    assert "Gem vs dulceață" in history.json()["markdown"]


def test_queue_job_request_consumes_an_idea_or_returns_empty(tmp_path: Path):
    client = build_client(tmp_path)
    headers = {"Authorization": "Bearer test-secret"}
    target_at = datetime.now(timezone.utc) + timedelta(hours=2)
    client.post(
        "/api/v1/automation/ideas/import",
        headers=headers,
        json={
            "ideas": [{
                "idea_id": "IDEA-001",
                "title": "Gem vs dulceață",
                "left": "Gem",
                "right": "Dulceață",
                "angle": "",
            }]
        },
    )

    created = client.post(
        "/api/v1/automation/jobs",
        headers=headers,
        json={"target_at": target_at.isoformat(), "use_next_idea": True},
    )
    empty = client.post(
        "/api/v1/automation/jobs",
        headers=headers,
        json={"target_at": target_at.isoformat(), "use_next_idea": True},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "CREATED"
    assert created.json()["job"]["topic_override"] == "Gem vs Dulceață"
    assert empty.status_code == 200
    assert empty.json() == {"status": "NO_IDEA_AVAILABLE", "job": None}


def test_queue_request_rejects_an_explicit_override(tmp_path: Path):
    client = build_client(tmp_path)
    response = client.post(
        "/api/v1/automation/jobs",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "target_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "topic_override": "Gem vs Dulceață",
            "use_next_idea": True,
        },
    )

    assert response.status_code == 422


def test_idea_endpoints_require_the_internal_token(tmp_path: Path):
    client = build_client(tmp_path)

    assert client.get("/api/v1/automation/ideas/history").status_code == 401
    assert client.post(
        "/api/v1/automation/ideas/import",
        json={"ideas": []},
    ).status_code == 401
