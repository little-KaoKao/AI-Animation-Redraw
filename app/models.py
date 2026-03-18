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


class VideoInfo(BaseModel):
    width: int = 0
    height: int = 0
    fps: float = 0
    duration: float = 0
    total_frames: int = 0
    unique_frames: int = 0
    grid_count: int = 0
    hold_pattern: str = ""  # e.g. "mixed 2-3 on"


class ProjectInfo(BaseModel):
    project_id: str
    has_video: bool = False
    has_character: bool = False
    video_info: Optional[VideoInfo] = None
    stage: PipelineStage = PipelineStage.IDLE
    progress: float = 0.0  # 0-100
    message: str = ""
    output_ready: bool = False


class PipelineStatus(BaseModel):
    project_id: str
    stage: PipelineStage
    progress: float = 0.0
    message: str = ""
    elapsed_seconds: float = 0.0
    video_info: Optional[VideoInfo] = None
    output_ready: bool = False


class FrameHoldMap(BaseModel):
    """Maps unique frame index (1-based) to number of video frames it holds."""
    holds: dict[int, int] = {}
    fps: float = 30.0
