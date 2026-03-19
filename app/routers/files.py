from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from app.utils.file_manager import (
    create_project, get_project_dir, load_metadata, save_metadata,
    create_asset, get_asset_path, list_assets, delete_asset,
)
from app.config import get_settings

router = APIRouter()


@router.post("/upload/video")
async def upload_video(file: UploadFile = File(...), project_id: str = ""):
    """Upload a video file. Creates a new project if project_id is not given."""
    if not project_id:
        project_id, project_dir = create_project()
    else:
        project_dir = get_project_dir(project_id)
        if not project_dir.exists():
            raise HTTPException(404, "Project not found")

    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    dest = project_dir / "input" / f"video{suffix}"

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Also store as reusable asset
    asset_id, _ = create_asset("video", dest, file.filename or "video.mp4")

    # Update metadata
    meta = load_metadata(project_dir)
    meta["video_filename"] = file.filename or ""
    meta["video_asset_id"] = asset_id
    save_metadata(project_dir, meta)

    return {"project_id": project_id, "filename": file.filename, "asset_id": asset_id}


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

    # Also store as reusable asset
    asset_id, _ = create_asset("character", dest, file.filename or "character.png")

    meta = load_metadata(project_dir)
    meta["character_filename"] = file.filename or ""
    meta["character_asset_id"] = asset_id
    save_metadata(project_dir, meta)

    return {"project_id": project_id, "filename": file.filename, "asset_id": asset_id}


@router.post("/project/{project_id}/use-asset")
async def use_asset(project_id: str, asset_type: str, asset_id: str):
    """Copy an existing asset into a project for reuse."""
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")

    src = get_asset_path(asset_type, asset_id)
    if src is None:
        raise HTTPException(404, "Asset not found")

    suffix = src.suffix
    if asset_type == "video":
        dest = project_dir / "input" / f"video{suffix}"
    elif asset_type == "character":
        dest = project_dir / "input" / f"character{suffix}"
    else:
        raise HTTPException(400, "Invalid asset_type")

    shutil.copy2(str(src), str(dest))

    # Read asset meta for filename
    asset_meta_path = src.parent / "meta.json"
    asset_filename = ""
    if asset_meta_path.exists():
        with open(asset_meta_path, "r", encoding="utf-8") as f:
            asset_meta = json.load(f)
            asset_filename = asset_meta.get("filename", "")

    meta = load_metadata(project_dir)
    meta[f"{asset_type}_asset_id"] = asset_id
    if asset_type == "video":
        meta["video_filename"] = asset_filename
    elif asset_type == "character":
        meta["character_filename"] = asset_filename
    save_metadata(project_dir, meta)

    return {"project_id": project_id, "asset_type": asset_type, "asset_id": asset_id}


@router.get("/assets/{asset_type}")
async def get_assets(asset_type: str):
    """List all assets of a given type (video/character)."""
    if asset_type not in ("video", "character"):
        raise HTTPException(400, "Invalid asset_type")
    return list_assets(asset_type)


@router.delete("/assets/{asset_type}/{asset_id}")
async def remove_asset(asset_type: str, asset_id: str):
    if not delete_asset(asset_type, asset_id):
        raise HTTPException(404, "Asset not found")
    return {"deleted": asset_id}


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


@router.get("/asset-file/{asset_type}/{asset_id}/original")
async def serve_asset_original(asset_type: str, asset_id: str):
    """Serve the original file for an asset (auto-detect extension)."""
    path = get_asset_path(asset_type, asset_id)
    if path is None:
        raise HTTPException(404, "Asset not found")
    return FileResponse(path)


@router.get("/asset-file/{asset_type}/{asset_id}/{subpath:path}")
async def serve_asset_file(asset_type: str, asset_id: str, subpath: str):
    """Serve a file from the asset directory."""
    settings = get_settings()
    asset_dir = settings.data_path / "assets" / asset_type / asset_id
    file_path = asset_dir / subpath

    try:
        file_path.resolve().relative_to(asset_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(file_path)


@router.get("/project-input/{project_id}/{file_type}")
async def serve_project_input(project_id: str, file_type: str):
    """Serve the video or character input file (auto-detect extension)."""
    if file_type not in ("video", "character"):
        raise HTTPException(400, "Invalid file_type")
    project_dir = get_project_dir(project_id)
    if not project_dir.exists():
        raise HTTPException(404, "Project not found")
    matches = list((project_dir / "input").glob(f"{file_type}.*"))
    if not matches:
        raise HTTPException(404, "File not found")
    return FileResponse(matches[0])
