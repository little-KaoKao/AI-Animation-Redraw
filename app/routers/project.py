from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.models import ProjectInfo, PipelineStage
from app.utils.file_manager import get_project_dir, load_metadata
from app.config import get_settings

router = APIRouter()


@router.get("/project/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    metadata = load_metadata(project_dir)
    input_dir = project_dir / "input"

    has_video = any(input_dir.glob("video.*"))
    has_character = any(input_dir.glob("character.*"))

    video_info = metadata.get("video_info")
    stage = metadata.get("stage", "idle")

    return ProjectInfo(
        project_id=project_id,
        has_video=has_video,
        has_character=has_character,
        video_info=video_info,
        stage=PipelineStage(stage),
        progress=metadata.get("progress", 0),
        message=metadata.get("message", ""),
        output_ready=(project_dir / "output" / "final.mp4").exists(),
    )


@router.get("/projects")
async def list_projects():
    settings = get_settings()
    projects_dir = settings.projects_path
    result = []
    if projects_dir.exists():
        for p in sorted(projects_dir.iterdir(), reverse=True):
            if p.is_dir():
                meta = load_metadata(p)
                result.append({
                    "project_id": p.name,
                    "stage": meta.get("stage", "idle"),
                    "message": meta.get("message", ""),
                })
    return result


@router.delete("/project/{project_id}")
async def delete_project(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")
    shutil.rmtree(project_dir)
    return {"deleted": project_id}
