from fastapi import FastAPI

from app.api.routes_jobs import app as legacy_app
from app.automation.api import create_automation_router
from app.automation.runtime import build_job_service, build_publication_service
from app.automation.settings import get_automation_settings


def create_app() -> FastAPI:
    settings = get_automation_settings()
    token = (
        settings.internal_api_token.get_secret_value()
        if settings.internal_api_token is not None
        else ""
    )
    job_service = build_job_service()
    legacy_app.include_router(
        create_automation_router(
            job_service,
            token,
            publisher=build_publication_service(job_service),
        )
    )
    return legacy_app


app = create_app()
