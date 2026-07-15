from fastapi import FastAPI

from app.api.routes_jobs import app as legacy_app
from app.automation.api import create_automation_router
from app.automation.runtime import build_job_service
from app.automation.settings import get_automation_settings


def create_app() -> FastAPI:
    settings = get_automation_settings()
    token = (
        settings.internal_api_token.get_secret_value()
        if settings.internal_api_token is not None
        else ""
    )
    legacy_app.include_router(create_automation_router(build_job_service(), token))
    return legacy_app


app = create_app()
