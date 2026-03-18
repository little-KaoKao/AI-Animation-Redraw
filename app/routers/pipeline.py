from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException

from app.models import PipelineStatus, PipelineStage
from app.utils.file_manager import get_project_dir, load_metadata
from app.services.pipeline_manager import PipelineManager

router = APIRouter()

# Global pipeline manager instance
_manager = PipelineManager()


@router.post("/pipeline/start")
async def start_pipeline(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    if not any((project_dir / "input").glob("video.*")):
        raise HTTPException(400, "No video uploaded")
    if not any((project_dir / "input").glob("character.*")):
        raise HTTPException(400, "No character image uploaded")

    await _manager.start(project_id, project_dir)
    return {"project_id": project_id, "status": "started"}


@router.get("/pipeline/{project_id}/status", response_model=PipelineStatus)
async def get_pipeline_status(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    state = _manager.get_state(project_id)
    if state:
        return state

    # Fallback to metadata file
    metadata = load_metadata(project_dir)
    return PipelineStatus(
        project_id=project_id,
        stage=PipelineStage(metadata.get("stage", "idle")),
        progress=metadata.get("progress", 0),
        message=metadata.get("message", ""),
        output_ready=(project_dir / "output" / "final.mp4").exists(),
    )


@router.post("/pipeline/{project_id}/cancel")
async def cancel_pipeline(project_id: str):
    cancelled = _manager.cancel(project_id)
    if not cancelled:
        raise HTTPException(400, "No running pipeline to cancel")
    return {"project_id": project_id, "status": "cancelled"}
