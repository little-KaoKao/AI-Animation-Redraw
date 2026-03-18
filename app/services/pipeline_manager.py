from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from app.models import PipelineStage, PipelineStatus, VideoInfo
from app.utils.file_manager import load_metadata, save_metadata

from app.services.video_analyzer import analyze_video
from app.services.frame_extractor import extract_unique_frames
from app.services.grid_composer import compose_grids
from app.services.threeview_generator import generate_threeview
from app.services.grid_redrawer import redraw_all_grids
from app.services.grid_splitter import split_grids
from app.services.video_assembler import assemble_video

logger = logging.getLogger(__name__)


class PipelineManager:
    """Manages pipeline execution and state for all projects."""

    def __init__(self):
        self._states: dict[str, PipelineStatus] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def get_state(self, project_id: str) -> Optional[PipelineStatus]:
        return self._states.get(project_id)

    def cancel(self, project_id: str) -> bool:
        task = self._tasks.get(project_id)
        if task and not task.done():
            task.cancel()
            self._update(project_id, PipelineStage.FAILED, 0, "Cancelled by user")
            return True
        return False

    async def start(self, project_id: str, project_dir: Path):
        # Cancel any existing pipeline for this project
        if project_id in self._tasks:
            self.cancel(project_id)

        self._states[project_id] = PipelineStatus(
            project_id=project_id,
            stage=PipelineStage.IDLE,
        )

        task = asyncio.create_task(self._run_pipeline(project_id, project_dir))
        self._tasks[project_id] = task

    def _update(
        self,
        project_id: str,
        stage: PipelineStage,
        progress: float,
        message: str,
        video_info: Optional[VideoInfo] = None,
    ):
        state = self._states.get(project_id)
        if state:
            state.stage = stage
            state.progress = progress
            state.message = message
            if video_info:
                state.video_info = video_info
            state.output_ready = stage == PipelineStage.COMPLETE

    async def _run_pipeline(self, project_id: str, project_dir: Path):
        start_time = time.time()

        def elapsed():
            s = self._states.get(project_id)
            if s:
                s.elapsed_seconds = time.time() - start_time

        try:
            input_dir = project_dir / "input"
            video_path = next(input_dir.glob("video.*"))
            character_path = next(input_dir.glob("character.*"))

            # Stage 1: Analyze video
            self._update(project_id, PipelineStage.ANALYZING, 0, "正在分析视频...")
            elapsed()
            video_info = await analyze_video(video_path)
            self._update(project_id, PipelineStage.ANALYZING, 100, "视频分析完成", video_info)
            elapsed()

            # Save video info to metadata
            meta = load_metadata(project_dir)
            meta["video_info"] = video_info.model_dump()
            meta["stage"] = PipelineStage.ANALYZING.value
            save_metadata(project_dir, meta)

            # Stage 2: Extract unique frames
            self._update(project_id, PipelineStage.EXTRACTING, 0, "正在提取非重复帧...")
            elapsed()
            hold_map = await extract_unique_frames(
                video_path, project_dir / "frames", video_info.fps
            )
            self._update(project_id, PipelineStage.EXTRACTING, 50, f"提取了 {len(hold_map.holds)} 帧，正在合成宫格图...")
            elapsed()

            # Save hold map
            meta["frame_hold_map"] = hold_map.model_dump()
            save_metadata(project_dir, meta)

            # Stage 2b: Compose grids
            self._update(project_id, PipelineStage.COMPOSING_GRIDS, 0, "正在合成宫格图...")
            elapsed()
            grid_paths = compose_grids(
                project_dir / "frames",
                project_dir / "grids",
                len(hold_map.holds),
                video_info.width,
                video_info.height,
            )
            self._update(project_id, PipelineStage.COMPOSING_GRIDS, 100, f"合成了 {len(grid_paths)} 张宫格图")
            elapsed()

            # Stage 3: Generate 3-view
            self._update(project_id, PipelineStage.GENERATING_3VIEW, 0, "正在生成三视图...")
            elapsed()
            threeview_path = await generate_threeview(
                character_path, project_dir / "cha_3view"
            )
            self._update(project_id, PipelineStage.GENERATING_3VIEW, 100, "三视图生成完成")
            elapsed()

            # Stage 4: Redraw grids
            total_grids = len(grid_paths)
            self._update(project_id, PipelineStage.REDRAWING_GRIDS, 0, f"正在重绘宫格图 (0/{total_grids})...")
            elapsed()

            # Determine aspect ratio from video
            if video_info.height > video_info.width:
                aspect_ratio = "9:16"
            elif video_info.width > video_info.height:
                aspect_ratio = "16:9"
            else:
                aspect_ratio = "1:1"

            def on_grid_progress(done: int, total: int):
                pct = (done / total * 100) if total > 0 else 0
                self._update(
                    project_id,
                    PipelineStage.REDRAWING_GRIDS,
                    pct,
                    f"正在重绘宫格图 ({done}/{total})...",
                )
                elapsed()

            redrawn_paths = await redraw_all_grids(
                grid_paths,
                threeview_path,
                project_dir / "grids_redrawn",
                aspect_ratio=aspect_ratio,
                on_progress=on_grid_progress,
            )
            self._update(project_id, PipelineStage.REDRAWING_GRIDS, 100, f"重绘完成 ({len(redrawn_paths)}/{total_grids})")
            elapsed()

            # Stage 5: Split grids
            self._update(project_id, PipelineStage.SPLITTING_GRIDS, 0, "正在拆分重绘图...")
            elapsed()
            split_grids(
                project_dir / "grids_redrawn",
                project_dir / "frames_redrawn",
                len(hold_map.holds),
            )
            self._update(project_id, PipelineStage.SPLITTING_GRIDS, 100, "拆分完成")
            elapsed()

            # Stage 6: Assemble video
            self._update(project_id, PipelineStage.ASSEMBLING_VIDEO, 0, "正在合成视频...")
            elapsed()
            output_path = await assemble_video(
                project_dir / "frames_redrawn",
                video_path,
                project_dir / "output" / "final.mp4",
                hold_map,
                video_info.width,
                video_info.height,
            )
            self._update(project_id, PipelineStage.ASSEMBLING_VIDEO, 100, "视频合成完成")
            elapsed()

            # Done!
            self._update(project_id, PipelineStage.COMPLETE, 100, "全部完成！")
            elapsed()

            meta["stage"] = PipelineStage.COMPLETE.value
            meta["message"] = "全部完成！"
            save_metadata(project_dir, meta)

            logger.info("Pipeline complete for project %s (%.1fs)", project_id, time.time() - start_time)

        except asyncio.CancelledError:
            logger.info("Pipeline cancelled for project %s", project_id)
            self._update(project_id, PipelineStage.FAILED, 0, "已取消")
        except Exception as e:
            logger.exception("Pipeline failed for project %s", project_id)
            err_msg = str(e) or repr(e)
            self._update(project_id, PipelineStage.FAILED, 0, f"错误: {err_msg}")
            meta = load_metadata(project_dir)
            meta["stage"] = PipelineStage.FAILED.value
            meta["message"] = str(e) or repr(e)
            save_metadata(project_dir, meta)
