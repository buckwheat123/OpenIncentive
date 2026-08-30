from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import admin, auth, letters, views

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="奖金计算平台", docs_url="/docs")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(auth.router)
    app.include_router(views.router)
    app.include_router(admin.router)
    app.include_router(letters.router)
    return app


app = create_app()
