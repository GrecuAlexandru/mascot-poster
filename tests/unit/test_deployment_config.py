from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_compose_keeps_api_database_and_search_private():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "ports" not in services["postgres"]
    assert "ports" not in services["api"]
    assert "ports" not in services["searxng"]
    assert services["worker"]["command"] == ["python", "-m", "app.automation.runtime"]
    assert services["bot"]["command"] == [
        "python",
        "-m",
        "app.automation.telegram_main",
    ]
    assert services["cleanup"]["command"] == [
        "python",
        "-m",
        "app.automation.cleanup_main",
    ]
    assert compose["networks"]["n8n-mascot"]["external"] is True
    assert "n8n-mascot" in services["api"]["networks"]


def test_internet_facing_services_have_egress_without_exposing_postgres():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert compose["networks"]["backend"]["internal"] is True
    assert compose["networks"]["egress"].get("internal", False) is False
    assert services["postgres"]["networks"] == ["backend"]
    for service_name in ("api", "worker", "bot", "cleanup", "searxng"):
        assert "egress" in services[service_name]["networks"]


def test_n8n_workflows_are_inactive_private_and_secret_free():
    workflows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "n8n" / "workflows").glob("*.json"))
    ]

    assert workflows
    assert all(workflow["active"] is False for workflow in workflows)
    encoded = json.dumps(workflows)
    assert "http://mascot-api:8000" in encoded
    assert "TELEGRAM_CHAT_ID" not in encoded
    assert "AUTOMATION_INTERNAL_API_TOKEN" not in encoded
    assert "Bearer " not in encoded
    assert "Mascot Internal API" in encoded
