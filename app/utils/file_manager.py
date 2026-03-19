from __future__ import annotations

import uuid
import json
import shutil
from datetime import datetime
from pathlib import Path

from app.config import get_settings


def create_project(name: str = "") -> tuple[str, Path]:
    """Create a new project directory and return (project_id, project_path)."""
    settings = get_settings()
    project_id = uuid.uuid4().hex[:12]
    project_dir = settings.projects_path / project_id

    for sub in ["input", "frames", "grids", "cha_3view", "grids_redrawn", "frames_redrawn", "output"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    metadata = {
        "project_id": project_id,
        "name": name or f"项目 {project_id[:6]}",
        "created_at": datetime.now().isoformat(),
        "stage": "idle",
        "grid_size": 4,
        "frame_hold_map": {},
        "grids": [],
    }
    save_metadata(project_dir, metadata)

    return project_id, project_dir


def get_project_dir(project_id: str) -> Path:
    settings = get_settings()
    return settings.projects_path / project_id


def load_metadata(project_dir: Path) -> dict:
    meta_path = project_dir / "metadata.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_metadata(project_dir: Path, metadata: dict):
    meta_path = project_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


# ── Asset management ──

def _assets_path() -> Path:
    settings = get_settings()
    p = settings.data_path / "assets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_asset(asset_type: str, src_path: Path, original_filename: str) -> tuple[str, Path]:
    """
    Copy a file into the asset library.
    asset_type: 'video' or 'character'
    Returns (asset_id, asset_path).
    """
    asset_id = uuid.uuid4().hex[:12]
    asset_dir = _assets_path() / asset_type / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    suffix = src_path.suffix
    dest = asset_dir / f"original{suffix}"
    shutil.copy2(str(src_path), str(dest))

    # Generate thumbnail for character images
    thumbnail = ""
    if asset_type == "character":
        try:
            from PIL import Image
            img = Image.open(dest)
            img.thumbnail((200, 200), Image.LANCZOS)
            thumb_path = asset_dir / "thumb.png"
            img.save(thumb_path)
            thumbnail = f"assets/{asset_type}/{asset_id}/thumb.png"
        except Exception:
            pass

    meta = {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "filename": original_filename,
        "created_at": datetime.now().isoformat(),
        "thumbnail": thumbnail,
    }
    with open(asset_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return asset_id, dest


def get_asset_path(asset_type: str, asset_id: str) -> Path | None:
    """Return the original file path for an asset, or None if not found."""
    asset_dir = _assets_path() / asset_type / asset_id
    if not asset_dir.exists():
        return None
    originals = list(asset_dir.glob("original.*"))
    return originals[0] if originals else None


def list_assets(asset_type: str) -> list[dict]:
    """List all assets of a given type, most recent first."""
    base = _assets_path() / asset_type
    results = []
    if base.exists():
        for d in sorted(base.iterdir(), reverse=True):
            meta_path = d / "meta.json"
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    results.append(json.load(f))
    return results


def delete_asset(asset_type: str, asset_id: str) -> bool:
    asset_dir = _assets_path() / asset_type / asset_id
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
        return True
    return False


# ── Asset cache helpers ──

def get_asset_cache_dir(asset_type: str, asset_id: str) -> Path | None:
    """Return the cache directory for an asset, creating it if the asset exists."""
    asset_dir = _assets_path() / asset_type / asset_id
    if not asset_dir.exists():
        return None
    cache_dir = asset_dir / "cache"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def has_video_cache(asset_id: str) -> bool:
    """Check if a video asset has cached analysis + frames."""
    cache_dir = get_asset_cache_dir("video", asset_id)
    if not cache_dir:
        return False
    return (
        (cache_dir / "video_info.json").exists()
        and (cache_dir / "frame_hold_map.json").exists()
        and (cache_dir / "frames").exists()
        and any((cache_dir / "frames").glob("*.png"))
    )


def has_character_cache(asset_id: str) -> bool:
    """Check if a character asset has a cached three-view."""
    cache_dir = get_asset_cache_dir("character", asset_id)
    if not cache_dir:
        return False
    return any((cache_dir).glob("threeview.*"))


def save_video_cache(asset_id: str, video_info: dict, frame_hold_map: dict, frames_dir: Path):
    """Write video analysis results to asset cache."""
    cache_dir = get_asset_cache_dir("video", asset_id)
    if not cache_dir:
        return
    with open(cache_dir / "video_info.json", "w", encoding="utf-8") as f:
        json.dump(video_info, f, ensure_ascii=False, indent=2)
    with open(cache_dir / "frame_hold_map.json", "w", encoding="utf-8") as f:
        json.dump(frame_hold_map, f, ensure_ascii=False, indent=2)
    # Copy frames
    cache_frames = cache_dir / "frames"
    if cache_frames.exists():
        shutil.rmtree(cache_frames)
    shutil.copytree(str(frames_dir), str(cache_frames))


def save_character_cache(asset_id: str, threeview_path: Path):
    """Write three-view image to character asset cache."""
    cache_dir = get_asset_cache_dir("character", asset_id)
    if not cache_dir:
        return
    dest = cache_dir / ("threeview" + threeview_path.suffix)
    shutil.copy2(str(threeview_path), str(dest))


def load_video_cache(asset_id: str, project_dir: Path) -> tuple[dict, dict] | None:
    """Load cached video results into project directory. Returns (video_info, frame_hold_map) or None."""
    cache_dir = get_asset_cache_dir("video", asset_id)
    if not cache_dir or not has_video_cache(asset_id):
        return None
    with open(cache_dir / "video_info.json", "r", encoding="utf-8") as f:
        video_info = json.load(f)
    with open(cache_dir / "frame_hold_map.json", "r", encoding="utf-8") as f:
        frame_hold_map = json.load(f)
    # Copy cached frames to project
    dest_frames = project_dir / "frames"
    if dest_frames.exists():
        shutil.rmtree(dest_frames)
    shutil.copytree(str(cache_dir / "frames"), str(dest_frames))
    return video_info, frame_hold_map


def load_character_cache(asset_id: str, project_dir: Path) -> Path | None:
    """Copy cached three-view into project. Returns the destination path or None."""
    cache_dir = get_asset_cache_dir("character", asset_id)
    if not cache_dir or not has_character_cache(asset_id):
        return None
    src = next(cache_dir.glob("threeview.*"))
    dest_dir = project_dir / "cha_3view"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(str(src), str(dest))
    return dest
