from fastapi import FastAPI

from app.api.routes_jobs import app


def create_app() -> FastAPI:
    return app
