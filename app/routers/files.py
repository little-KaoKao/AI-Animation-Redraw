from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from app.utils.file_manager import create_project, get_project_dir

router = APIRouter()


@router.post("/upload/video")
async def upload_video(file: UploadFile = File(...)):
    """Upload a video file and create a new project."""
    project_id, project_dir = create_project()
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    dest = project_dir / "input" / f"video{suffix}"

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"project_id": project_id, "filename": file.filename}


@router.post("/upload/character")
async def upload_character(project_id: str, file: UploadFile = File(...)):
    """Upload a character reference image to an existing project."""
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    suffix = Path(file.filename or "character.png").suffix or ".png"
    dest = project_dir / "input" / f"character{suffix}"

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"project_id": project_id, "filename": file.filename}


@router.get("/files/{project_id}/{subpath:path}")
async def serve_file(project_id: str, subpath: str):
    """Serve any file from a project directory."""
    project_dir = get_project_dir(project_id)
    file_path = project_dir / subpath

    # Prevent path traversal
    try:
        file_path.resolve().relative_to(project_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(file_path)
