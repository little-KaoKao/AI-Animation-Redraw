from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class PipelineStage(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    EXTRACTING = "extracting"
    COMPOSING_GRIDS = "composing_grids"
    GENERATING_3VIEW = "generating_3view"
    REDRAWING_GRIDS = "redrawing_grids"
    SPLITTING_GRIDS = "splitting_grids"
    ASSEMBLING_VIDEO = "assembling_video"
    COMPLETE = "complete"
    FAILED = "failed"
    PAUSED = "paused"


class VideoInfo(BaseModel):
    width: int = 0
    height: int = 0
    fps: float = 0
    duration: float = 0
    total_frames: int = 0
    unique_frames: int = 0
    grid_count: int = 0
    hold_pattern: str = ""  # e.g. "mixed 2-3 on"


class GridVersion(BaseModel):
    """A single historical version of a redrawn grid."""
    version: int  # 1-based
    filename: str  # e.g. grid_001_v1.png
    status: str = "success"  # success / failed
    created_at: str = ""


class GridInfo(BaseModel):
    """Info about a single grid for re-roll tracking."""
    grid_index: int  # 0-based
    grid_name: str
    status: str = "pending"  # pending / retrying / success / failed
    task_id: Optional[str] = None
    retry_count: int = 0
    error_msg: str = ""
    active_version: int = 0  # 0 = latest, else specific version number
    versions: list[GridVersion] = []


class ProjectInfo(BaseModel):
    project_id: str
    name: str = ""
    created_at: str = ""
    has_video: bool = False
    has_character: bool = False
    video_filename: str = ""
    character_filename: str = ""
    video_asset_id: Optional[str] = None
    character_asset_id: Optional[str] = None
    grid_size: int = 4
    video_info: Optional[VideoInfo] = None
    stage: PipelineStage = PipelineStage.IDLE
    progress: float = 0.0  # 0-100
    message: str = ""
    output_ready: bool = False
    grids: list[GridInfo] = []
    grids_dirty: bool = False


class PipelineStatus(BaseModel):
    project_id: str
    stage: PipelineStage
    progress: float = 0.0
    message: str = ""
    elapsed_seconds: float = 0.0
    video_info: Optional[VideoInfo] = None
    output_ready: bool = False
    grids: list[GridInfo] = []
    grids_dirty: bool = False
    rerolling: bool = False


class FrameHoldMap(BaseModel):
    """Maps unique frame index (1-based) to number of video frames it holds."""
    holds: dict[int, int] = {}
    fps: float = 30.0


class AssetInfo(BaseModel):
    """A reusable video or character asset."""
    asset_id: str
    asset_type: str  # "video" or "character"
    filename: str
    created_at: str = ""
    thumbnail: str = ""  # relative path to thumbnail
