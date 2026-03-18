from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.routers import files, project, pipeline


def create_app() -> FastAPI:
    app = FastAPI(title="AI手书复刻", version="0.1.0")

    app.include_router(files.router, prefix="/api")
    app.include_router(project.router, prefix="/api")
    app.include_router(pipeline.router, prefix="/api")

    static_dir = Path(__file__).parent.parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
