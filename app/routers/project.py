from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.models import ProjectInfo, PipelineStage
from app.utils.file_manager import (
    get_project_dir, load_metadata, save_metadata, create_project,
)
from app.config import get_settings

router = APIRouter()


@router.post("/project/create")
async def create_new_project(name: str = ""):
    """Create a new empty project."""
    project_id, _ = create_project(name)
    return {"project_id": project_id}


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

    # Fix orphaned pending/retrying grids (e.g. after server restart)
    grids = metadata.get("grids", [])
    from app.routers.pipeline import _manager
    active_reroll_indices = set()
    for idx, t in _manager._reroll_tasks.get(project_id, {}).items():
        if not t.done():
            active_reroll_indices.add(idx)
    orphan_fixed = False
    for g in grids:
        if g.get("status") in ("pending", "retrying"):
            gi = g.get("grid_index")
            if gi not in active_reroll_indices:
                g["status"] = "failed"
                g["error_msg"] = g.get("error_msg") or "处理被中断"
                orphan_fixed = True
    if orphan_fixed:
        metadata["grids"] = grids
        save_metadata(project_dir, metadata)

    return ProjectInfo(
        project_id=project_id,
        name=metadata.get("name", ""),
        created_at=metadata.get("created_at", ""),
        has_video=has_video,
        has_character=has_character,
        video_filename=metadata.get("video_filename", ""),
        character_filename=metadata.get("character_filename", ""),
        video_asset_id=metadata.get("video_asset_id"),
        character_asset_id=metadata.get("character_asset_id"),
        grid_size=metadata.get("grid_size", 4),
        video_info=video_info,
        stage=PipelineStage(stage),
        progress=metadata.get("progress", 0),
        message=metadata.get("message", ""),
        output_ready=(project_dir / "output" / "final.mp4").exists(),
        grids=grids,
        grids_dirty=metadata.get("grids_dirty", False),
    )


@router.put("/project/{project_id}")
async def update_project(project_id: str, name: str = "", grid_size: int = 0):
    """Update project settings (name, grid_size)."""
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    meta = load_metadata(project_dir)
    if name:
        meta["name"] = name
    if grid_size in (1, 4, 9):
        meta["grid_size"] = grid_size
    save_metadata(project_dir, meta)
    return {"project_id": project_id, "updated": True}


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
                    "name": meta.get("name", ""),
                    "created_at": meta.get("created_at", ""),
                    "stage": meta.get("stage", "idle"),
                    "message": meta.get("message", ""),
                    "grid_size": meta.get("grid_size", 4),
                    "video_filename": meta.get("video_filename", ""),
                    "character_filename": meta.get("character_filename", ""),
                    "output_ready": (p / "output" / "final.mp4").exists(),
                })
    return result


@router.delete("/project/{project_id}")
async def delete_project(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")
    shutil.rmtree(project_dir)
    return {"deleted": project_id}
