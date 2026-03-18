from __future__ import annotations

import uuid
import json
from pathlib import Path

from app.config import get_settings


def create_project() -> tuple[str, Path]:
    """Create a new project directory and return (project_id, project_path)."""
    settings = get_settings()
    project_id = uuid.uuid4().hex[:12]
    project_dir = settings.projects_path / project_id

    for sub in ["input", "frames", "grids", "cha_3view", "grids_redrawn", "frames_redrawn", "output"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    # Init metadata
    metadata = {"project_id": project_id, "stage": "idle", "frame_hold_map": {}}
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
