from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException

from app.models import PipelineStatus, PipelineStage, GridInfo
from app.utils.file_manager import get_project_dir, load_metadata, save_metadata
from app.services.pipeline_manager import PipelineManager

router = APIRouter()

# Global pipeline manager instance
_manager = PipelineManager()


@router.post("/pipeline/start")
async def start_pipeline(project_id: str, grid_size: int = 4):
    if grid_size not in (1, 4, 9):
        raise HTTPException(400, "grid_size must be 1, 4, or 9")

    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    if not any((project_dir / "input").glob("video.*")):
        raise HTTPException(400, "No video uploaded")
    if not any((project_dir / "input").glob("character.*")):
        raise HTTPException(400, "No character image uploaded")

    await _manager.start(project_id, project_dir, grid_size=grid_size)
    return {"project_id": project_id, "status": "started", "grid_size": grid_size}


@router.get("/pipeline/{project_id}/status", response_model=PipelineStatus)
async def get_pipeline_status(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    return _manager.get_state_or_metadata(project_id, project_dir)


@router.post("/pipeline/{project_id}/cancel")
async def cancel_pipeline(project_id: str):
    cancelled = _manager.cancel(project_id)
    if not cancelled:
        raise HTTPException(400, "No running pipeline to cancel")
    return {"project_id": project_id, "status": "cancelled"}


@router.post("/pipeline/{project_id}/pause")
async def pause_pipeline(project_id: str):
    paused = _manager.pause(project_id)
    if not paused:
        raise HTTPException(400, "No running pipeline to pause")
    return {"project_id": project_id, "status": "paused"}


@router.post("/pipeline/{project_id}/resume")
async def resume_pipeline(project_id: str):
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    resumed = await _manager.resume(project_id, project_dir)
    if not resumed:
        raise HTTPException(400, "No paused/interrupted pipeline to resume")
    return {"project_id": project_id, "status": "resumed"}


@router.post("/pipeline/{project_id}/reroll")
async def reroll_grid(project_id: str, grid_index: int):
    """Re-generate a single grid (redraw only, no reassembly)."""
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    metadata = load_metadata(project_dir)
    grids = metadata.get("grids", [])
    if grid_index < 0 or grid_index >= len(grids):
        raise HTTPException(400, f"Invalid grid_index: {grid_index}")

    # Check main pipeline is not running (rerolls are allowed during complete/failed/paused)
    state = _manager.get_state(project_id)
    if state and state.stage not in (PipelineStage.COMPLETE, PipelineStage.FAILED,
                                      PipelineStage.IDLE, PipelineStage.PAUSED):
        raise HTTPException(400, "Pipeline is still running")

    await _manager.reroll_grid(project_id, project_dir, grid_index)
    return {"project_id": project_id, "grid_index": grid_index, "status": "rerolling"}


@router.post("/pipeline/{project_id}/reassemble")
async def reassemble_video(project_id: str):
    """Re-split grids and re-assemble video from current redrawn grids."""
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    # Don't reassemble while rerolls are still running
    if _manager.has_active_rerolls(project_id):
        raise HTTPException(400, "Rerolls still in progress")

    # Check main pipeline is not running
    state = _manager.get_state(project_id)
    if state and state.stage not in (PipelineStage.COMPLETE, PipelineStage.FAILED,
                                      PipelineStage.IDLE, PipelineStage.PAUSED):
        raise HTTPException(400, "Pipeline is still running")

    await _manager.reassemble(project_id, project_dir)
    return {"project_id": project_id, "status": "reassembling"}


@router.post("/pipeline/{project_id}/grid/{grid_index}/restore")
async def restore_grid_version(project_id: str, grid_index: int, version: int):
    """Restore a historical version of a grid as the active one."""
    import shutil
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    metadata = load_metadata(project_dir)
    grids = metadata.get("grids", [])
    if grid_index < 0 or grid_index >= len(grids):
        raise HTTPException(400, f"Invalid grid_index: {grid_index}")

    gi = grids[grid_index]
    versions = gi.get("versions", [])
    target = next((v for v in versions if v["version"] == version), None)
    if not target or target["status"] != "success":
        raise HTTPException(400, "Version not found or not successful")

    redrawn_dir = project_dir / "grids_redrawn"
    ver_path = redrawn_dir / target["filename"]
    if not ver_path.exists():
        raise HTTPException(404, "Version file not found on disk")

    # Copy versioned file over the main grid file
    main_path = redrawn_dir / gi["grid_name"]
    shutil.copy2(str(ver_path), str(main_path))

    gi["active_version"] = version
    metadata["grids"] = grids
    metadata["grids_dirty"] = True
    save_metadata(project_dir, metadata)

    # Update in-memory state
    state = _manager.get_state(project_id)
    if state and grid_index < len(state.grids):
        state.grids[grid_index].active_version = version

    return {"project_id": project_id, "grid_index": grid_index, "version": version}
