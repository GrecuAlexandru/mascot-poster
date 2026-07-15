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
    assert payload["state"] == "QUEUED"
    assert payload["topic_override"] == "Cafea vs ceai"
    fetched = client.get(
        f"/api/v1/automation/jobs/{payload['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]


def test_create_job_rejects_target_in_the_past(tmp_path: Path):
    client = build_client(tmp_path)
    response = client.post(
        "/api/v1/automation/jobs",
        headers={"Authorization": "Bearer test-secret"},
        json={"target_at": "2020-01-01T00:00:00Z"},
    )

    assert response.status_code == 422
