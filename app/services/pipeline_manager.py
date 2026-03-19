from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from datetime import datetime, timezone

from app.models import PipelineStage, PipelineStatus, VideoInfo, GridInfo, GridVersion, FrameHoldMap
from app.utils.file_manager import (
    load_metadata, save_metadata,
    has_video_cache, has_character_cache,
    save_video_cache, save_character_cache,
    load_video_cache, load_character_cache,
)

from app.services.video_analyzer import analyze_video
from app.services.frame_extractor import extract_unique_frames
from app.services.grid_composer import compose_grids
from app.services.threeview_generator import generate_threeview
from app.services.grid_redrawer import redraw_all_grids, redraw_single_grid
from app.services.grid_splitter import split_grids
from app.services.video_assembler import assemble_video

logger = logging.getLogger(__name__)


class PipelineManager:
    """Manages pipeline execution and state for all projects."""

    def __init__(self):
        self._states: dict[str, PipelineStatus] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._project_dirs: dict[str, Path] = {}
        self._reroll_tasks: dict[str, dict[int, asyncio.Task]] = {}  # project_id -> {grid_index: task}

    def get_state(self, project_id: str) -> Optional[PipelineStatus]:
        return self._states.get(project_id)

    def cancel(self, project_id: str) -> bool:
        task = self._tasks.get(project_id)
        if task and not task.done():
            task.cancel()
            self._update(project_id, PipelineStage.FAILED, 0, "已取消")
            return True
        return False

    def pause(self, project_id: str) -> bool:
        """Pause a running pipeline by cancelling its task and marking PAUSED."""
        task = self._tasks.get(project_id)
        if task and not task.done():
            task.cancel()
            self._update(project_id, PipelineStage.PAUSED, 0, "已暂停")
            return True
        return False

    async def resume(self, project_id: str, project_dir: Path) -> bool:
        """Resume a paused/interrupted pipeline from the last completed stage."""
        meta = load_metadata(project_dir)
        stage = meta.get("stage", "idle")
        if stage not in ("paused", "analyzing", "extracting", "composing_grids",
                         "generating_3view", "redrawing_grids", "splitting_grids",
                         "assembling_video"):
            return False

        grid_size = meta.get("grid_size", 4)
        resume_from = self._detect_resume_stage(project_dir, meta)

        self._project_dirs[project_id] = project_dir
        self._states[project_id] = PipelineStatus(
            project_id=project_id,
            stage=PipelineStage.IDLE,
        )

        task = asyncio.create_task(
            self._run_pipeline(project_id, project_dir, grid_size, resume_from=resume_from)
        )
        self._tasks[project_id] = task
        return True

    def _detect_resume_stage(self, project_dir: Path, meta: dict) -> str:
        """Detect which stage to resume from based on files on disk."""
        # Check from latest to earliest
        if (project_dir / "output" / "final.mp4").exists():
            return "complete"
        if any((project_dir / "frames_redrawn").glob("*.png")) if (project_dir / "frames_redrawn").exists() else False:
            return "assembling_video"
        if any((project_dir / "grids_redrawn").glob("*.png")) if (project_dir / "grids_redrawn").exists() else False:
            return "splitting_grids"
        threeview_dir = project_dir / "cha_3view"
        if threeview_dir.exists() and any(threeview_dir.glob("threeview.*")):
            return "redrawing_grids"
        if any((project_dir / "grids").glob("grid_*.png")) if (project_dir / "grids").exists() else False:
            return "generating_3view"
        if any((project_dir / "frames").glob("*.png")) if (project_dir / "frames").exists() else False:
            return "composing_grids"
        if meta.get("video_info"):
            return "extracting"
        return "analyzing"

    async def start(self, project_id: str, project_dir: Path, grid_size: int = 4):
        # Cancel any existing pipeline for this project
        if project_id in self._tasks:
            self.cancel(project_id)

        self._project_dirs[project_id] = project_dir
        self._states[project_id] = PipelineStatus(
            project_id=project_id,
            stage=PipelineStage.IDLE,
        )

        task = asyncio.create_task(self._run_pipeline(project_id, project_dir, grid_size))
        self._tasks[project_id] = task

    async def reroll_grid(self, project_id: str, project_dir: Path, grid_index: int):
        """Re-generate a single grid (redraw only, no reassembly)."""
        self._project_dirs[project_id] = project_dir

        # Cancel existing reroll for same grid if running
        if project_id in self._reroll_tasks:
            existing = self._reroll_tasks[project_id].get(grid_index)
            if existing and not existing.done():
                existing.cancel()
        else:
            self._reroll_tasks[project_id] = {}

        task = asyncio.create_task(
            self._run_reroll(project_id, project_dir, grid_index)
        )
        self._reroll_tasks[project_id][grid_index] = task

    async def reassemble(self, project_id: str, project_dir: Path):
        """Re-split grids and re-assemble video from current redrawn grids."""
        self._project_dirs[project_id] = project_dir
        # Cancel existing main task if any
        if project_id in self._tasks:
            existing = self._tasks.get(project_id)
            if existing and not existing.done():
                existing.cancel()
        task = asyncio.create_task(
            self._run_reassemble(project_id, project_dir)
        )
        self._tasks[project_id] = task

    def _persist_grids(self, project_id: str, project_dir: Path, grid_infos: list[GridInfo]):
        """Persist grid statuses to metadata and in-memory state."""
        try:
            meta = load_metadata(project_dir)
            meta["grids"] = [g.model_dump() for g in grid_infos]
            save_metadata(project_dir, meta)
        except Exception:
            pass
        state = self._states.get(project_id)
        if state:
            state.grids = grid_infos

    def has_active_rerolls(self, project_id: str) -> bool:
        """Check if any reroll tasks are still running for a project."""
        tasks = self._reroll_tasks.get(project_id, {})
        return any(not t.done() for t in tasks.values())

    def _update(
        self,
        project_id: str,
        stage: PipelineStage,
        progress: float,
        message: str,
        video_info: Optional[VideoInfo] = None,
        grids: Optional[list[GridInfo]] = None,
    ):
        state = self._states.get(project_id)
        if state:
            state.stage = stage
            state.progress = progress
            state.message = message
            if video_info:
                state.video_info = video_info
            if grids is not None:
                state.grids = grids
            state.output_ready = stage == PipelineStage.COMPLETE

        # Persist to metadata on every stage change
        project_dir = self._project_dirs.get(project_id)
        if project_dir:
            try:
                meta = load_metadata(project_dir)
                meta["stage"] = stage.value
                meta["progress"] = progress
                meta["message"] = message
                if grids is not None:
                    meta["grids"] = [g.model_dump() for g in grids]
                if stage == PipelineStage.COMPLETE:
                    meta["output_ready"] = True
                save_metadata(project_dir, meta)
            except Exception:
                logger.debug("Failed to persist state for %s", project_id, exc_info=True)

    def get_state_or_metadata(self, project_id: str, project_dir: Path) -> PipelineStatus:
        """Get in-memory state, or fallback to metadata with zombie detection."""
        metadata = load_metadata(project_dir)
        grids_dirty = metadata.get("grids_dirty", False)
        rerolling = self.has_active_rerolls(project_id)

        # Refresh grid statuses from metadata (rerolls update metadata directly)
        fresh_grids_data = metadata.get("grids", [])
        fresh_grids = [GridInfo(**g) for g in fresh_grids_data] if fresh_grids_data else []

        # Orphan detection: reset "pending"/"retrying" grids with no active reroll task
        active_reroll_indices = set()
        for idx, t in self._reroll_tasks.get(project_id, {}).items():
            if not t.done():
                active_reroll_indices.add(idx)
        orphan_fixed = False
        for gi in fresh_grids:
            if gi.status in ("pending", "retrying") and gi.grid_index not in active_reroll_indices:
                gi.status = "failed"
                gi.error_msg = gi.error_msg or "处理被中断"
                orphan_fixed = True
        if orphan_fixed:
            try:
                metadata["grids"] = [g.model_dump() for g in fresh_grids]
                save_metadata(project_dir, metadata)
            except Exception:
                pass

        state = self._states.get(project_id)
        if state:
            state.grids_dirty = grids_dirty
            state.rerolling = rerolling
            state.grids = fresh_grids
            return state

        stage_str = metadata.get("stage", "idle")
        video_info_data = metadata.get("video_info")

        # Zombie detection: metadata shows active stage but no in-memory task
        active_stages = {"analyzing", "extracting", "composing_grids",
                         "generating_3view", "redrawing_grids", "splitting_grids",
                         "assembling_video"}
        if stage_str in active_stages:
            # Process was interrupted - mark as paused so user can resume
            stage = PipelineStage.PAUSED
            message = "处理被中断，可点击恢复继续"
        else:
            stage = PipelineStage(stage_str)
            message = metadata.get("message", "")

        return PipelineStatus(
            project_id=project_id,
            stage=stage,
            progress=metadata.get("progress", 0),
            message=message,
            output_ready=(project_dir / "output" / "final.mp4").exists(),
            grids=fresh_grids,
            video_info=VideoInfo(**video_info_data) if video_info_data else None,
            grids_dirty=grids_dirty,
            rerolling=rerolling,
        )

    async def _run_pipeline(
        self,
        project_id: str,
        project_dir: Path,
        grid_size: int,
        resume_from: str = "analyzing",
    ):
        start_time = time.time()

        # Stage order for resume logic
        stages = [
            "analyzing", "extracting", "composing_grids", "generating_3view",
            "redrawing_grids", "splitting_grids", "assembling_video",
        ]
        resume_idx = stages.index(resume_from) if resume_from in stages else 0

        def elapsed():
            s = self._states.get(project_id)
            if s:
                s.elapsed_seconds = time.time() - start_time

        try:
            input_dir = project_dir / "input"
            video_path = next(input_dir.glob("video.*"))
            character_path = next(input_dir.glob("character.*"))

            meta = load_metadata(project_dir)

            # Load existing data for resume
            video_info = None
            hold_map = None
            grid_infos = []
            grid_paths = []

            if resume_idx > 0:
                # Load video_info from metadata
                vi_data = meta.get("video_info")
                if vi_data:
                    video_info = VideoInfo(**vi_data)
                hm_data = meta.get("frame_hold_map")
                if hm_data:
                    hold_map = FrameHoldMap(**hm_data)
                grids_data = meta.get("grids", [])
                if grids_data:
                    grid_infos = [GridInfo(**g) for g in grids_data]
                # Reconstruct grid_paths
                grids_dir = project_dir / "grids"
                if grids_dir.exists():
                    grid_paths = sorted(grids_dir.glob("grid_*.png"))

            # Check for asset cache
            video_asset_id = meta.get("video_asset_id")
            char_asset_id = meta.get("character_asset_id")

            # Stage 1+2: Analyze video + Extract frames (may use cache)
            video_cache_used = False
            if resume_idx <= 1 and video_asset_id and has_video_cache(video_asset_id):
                # Reuse cached video analysis + frames
                self._update(project_id, PipelineStage.ANALYZING, 0, "正在从缓存加载视频分析结果...")
                elapsed()
                cached = load_video_cache(video_asset_id, project_dir)
                if cached:
                    vi_data, hm_data = cached
                    video_info = VideoInfo(**vi_data)
                    video_info.grid_count = (video_info.unique_frames + grid_size - 1) // grid_size
                    hold_map = FrameHoldMap(**hm_data)

                    meta = load_metadata(project_dir)
                    meta["video_info"] = video_info.model_dump()
                    meta["grid_size"] = grid_size
                    meta["frame_hold_map"] = hold_map.model_dump()
                    save_metadata(project_dir, meta)

                    self._update(project_id, PipelineStage.ANALYZING, 100, "视频分析完成(缓存)", video_info)
                    elapsed()
                    self._update(project_id, PipelineStage.EXTRACTING, 50,
                                 f"提取了 {len(hold_map.holds)} 帧(缓存)")
                    elapsed()
                    video_cache_used = True
                    logger.info("Used video cache for asset %s in project %s", video_asset_id, project_id)

            if not video_cache_used:
                # Stage 1: Analyze video
                if resume_idx <= 0:
                    self._update(project_id, PipelineStage.ANALYZING, 0, "正在分析视频...")
                    elapsed()
                    video_info = await analyze_video(video_path)
                    video_info.grid_count = (video_info.unique_frames + grid_size - 1) // grid_size
                    self._update(project_id, PipelineStage.ANALYZING, 100, "视频分析完成", video_info)
                    elapsed()

                    meta = load_metadata(project_dir)
                    meta["video_info"] = video_info.model_dump()
                    meta["grid_size"] = grid_size
                    save_metadata(project_dir, meta)
                else:
                    if video_info:
                        self._update(project_id, PipelineStage.ANALYZING, 100, "视频分析完成(已恢复)", video_info)

                # Stage 2: Extract unique frames
                if resume_idx <= 1:
                    self._update(project_id, PipelineStage.EXTRACTING, 0, "正在提取非重复帧...")
                    elapsed()
                    hold_map = await extract_unique_frames(
                        video_path, project_dir / "frames", video_info.fps
                    )
                    self._update(project_id, PipelineStage.EXTRACTING, 50,
                                 f"提取了 {len(hold_map.holds)} 帧")
                    elapsed()

                    meta = load_metadata(project_dir)
                    meta["frame_hold_map"] = hold_map.model_dump()
                    save_metadata(project_dir, meta)

                    # Write back to asset cache
                    if video_asset_id:
                        try:
                            save_video_cache(
                                video_asset_id,
                                video_info.model_dump(),
                                hold_map.model_dump(),
                                project_dir / "frames",
                            )
                            logger.info("Saved video cache for asset %s", video_asset_id)
                        except Exception:
                            logger.debug("Failed to save video cache", exc_info=True)

            # Stage 2b: Compose grids
            if resume_idx <= 2:
                self._update(project_id, PipelineStage.COMPOSING_GRIDS, 0, "正在合成宫格图...")
                elapsed()
                grid_paths = compose_grids(
                    project_dir / "frames",
                    project_dir / "grids",
                    len(hold_map.holds),
                    video_info.width,
                    video_info.height,
                    grid_size=grid_size,
                )
                grid_infos = [
                    GridInfo(grid_index=i, grid_name=p.name, status="pending")
                    for i, p in enumerate(grid_paths)
                ]
                self._update(project_id, PipelineStage.COMPOSING_GRIDS, 100,
                             f"合成了 {len(grid_paths)} 张宫格图", grids=grid_infos)
                elapsed()

            # Stage 3: Generate 3-view (may use cache)
            if resume_idx <= 3:
                char_cache_used = False
                if char_asset_id and has_character_cache(char_asset_id):
                    self._update(project_id, PipelineStage.GENERATING_3VIEW, 0, "正在从缓存加载三视图...")
                    elapsed()
                    cached_path = load_character_cache(char_asset_id, project_dir)
                    if cached_path:
                        threeview_path = cached_path
                        char_cache_used = True
                        self._update(project_id, PipelineStage.GENERATING_3VIEW, 100, "三视图加载完成(缓存)")
                        elapsed()
                        logger.info("Used character cache for asset %s in project %s", char_asset_id, project_id)

                if not char_cache_used:
                    self._update(project_id, PipelineStage.GENERATING_3VIEW, 0, "正在生成三视图...")
                    elapsed()
                    threeview_path = await generate_threeview(
                        character_path, project_dir / "cha_3view"
                    )
                    self._update(project_id, PipelineStage.GENERATING_3VIEW, 100, "三视图生成完成")
                    elapsed()

                    # Write back to asset cache
                    if char_asset_id:
                        try:
                            save_character_cache(char_asset_id, threeview_path)
                            logger.info("Saved character cache for asset %s", char_asset_id)
                        except Exception:
                            logger.debug("Failed to save character cache", exc_info=True)
            else:
                threeview_dir = project_dir / "cha_3view"
                threeview_path = next(threeview_dir.glob("threeview.*"))

            # Stage 4: Redraw grids
            if resume_idx <= 4:
                total_grids = len(grid_paths)
                self._update(project_id, PipelineStage.REDRAWING_GRIDS, 0,
                             f"正在重绘宫格图 (0/{total_grids})...")
                elapsed()

                if video_info.height > video_info.width:
                    aspect_ratio = "9:16"
                elif video_info.width > video_info.height:
                    aspect_ratio = "16:9"
                else:
                    aspect_ratio = "1:1"

                def on_grid_progress(done: int, total: int, index: int = -1,
                                     success: bool = True, retry_msg: str = ""):
                    pct = (done / total * 100) if total > 0 else 0
                    if 0 <= index < len(grid_infos):
                        if retry_msg:
                            grid_infos[index].status = "retrying"
                            # Extract retry count from message like "重试中 (2/3)"
                            import re
                            m = re.search(r'\((\d+)/', retry_msg)
                            if m:
                                grid_infos[index].retry_count = int(m.group(1))
                        elif success:
                            grid_infos[index].status = "success"
                            grid_infos[index].retry_count = 0
                            grid_infos[index].error_msg = ""
                        else:
                            grid_infos[index].status = "failed"
                    msg = retry_msg or f"正在重绘宫格图 ({done}/{total})..."
                    self._update(
                        project_id,
                        PipelineStage.REDRAWING_GRIDS,
                        pct,
                        msg,
                        grids=grid_infos,
                    )
                    elapsed()

                redrawn_paths = await redraw_all_grids(
                    grid_paths,
                    threeview_path,
                    project_dir / "grids_redrawn",
                    aspect_ratio=aspect_ratio,
                    on_progress=on_grid_progress,
                )
                self._update(project_id, PipelineStage.REDRAWING_GRIDS, 100,
                             f"重绘完成 ({len(redrawn_paths)}/{total_grids})",
                             grids=grid_infos)
                elapsed()

            # Stage 5: Split grids
            if resume_idx <= 5:
                self._update(project_id, PipelineStage.SPLITTING_GRIDS, 0, "正在拆分重绘图...")
                elapsed()
                split_grids(
                    project_dir / "grids_redrawn",
                    project_dir / "frames_redrawn",
                    len(hold_map.holds),
                    grid_size=grid_size,
                )
                self._update(project_id, PipelineStage.SPLITTING_GRIDS, 100, "拆分完成")
                elapsed()

            # Stage 6: Assemble video
            if resume_idx <= 6:
                self._update(project_id, PipelineStage.ASSEMBLING_VIDEO, 0, "正在合成视频...")
                elapsed()
                await assemble_video(
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
            self._update(project_id, PipelineStage.COMPLETE, 100, "全部完成!",
                         grids=grid_infos)
            elapsed()

            logger.info("Pipeline complete for project %s (%.1fs)", project_id, time.time() - start_time)

        except asyncio.CancelledError:
            logger.info("Pipeline cancelled/paused for project %s", project_id)
            # Stage already set by pause() or cancel(); don't overwrite
            state = self._states.get(project_id)
            if state and state.stage != PipelineStage.PAUSED:
                self._update(project_id, PipelineStage.FAILED, 0, "已取消")
        except Exception as e:
            logger.exception("Pipeline failed for project %s", project_id)
            err_msg = str(e) or repr(e)
            self._update(project_id, PipelineStage.FAILED, 0, f"错误: {err_msg}")

    def _persist_single_grid(self, project_id: str, project_dir: Path,
                             grid_index: int, gi: GridInfo, dirty: bool = False):
        """Persist only one grid's data to metadata (safe for concurrent rerolls)."""
        try:
            meta = load_metadata(project_dir)
            grids_data = meta.get("grids", [])
            if grid_index < len(grids_data):
                grids_data[grid_index] = gi.model_dump()
                meta["grids"] = grids_data
                if dirty:
                    meta["grids_dirty"] = True
                save_metadata(project_dir, meta)
            # Also update in-memory state for this specific grid
            state = self._states.get(project_id)
            if state and grid_index < len(state.grids):
                state.grids[grid_index] = gi.model_copy()
        except Exception:
            logger.debug("Failed to persist grid %d for %s", grid_index, project_id, exc_info=True)

    async def _run_reroll(self, project_id: str, project_dir: Path, grid_index: int):
        """Re-generate one grid only (no split/assemble). Marks grids_dirty."""
        try:
            meta = load_metadata(project_dir)
            video_info_data = meta.get("video_info", {})
            video_info = VideoInfo(**video_info_data) if video_info_data else None
            grids_data = meta.get("grids", [])

            if not video_info:
                raise RuntimeError("No video_info in metadata")

            if video_info.height > video_info.width:
                aspect_ratio = "9:16"
            elif video_info.width > video_info.height:
                aspect_ratio = "16:9"
            else:
                aspect_ratio = "1:1"

            grids_dir = project_dir / "grids"
            grid_files = sorted(grids_dir.glob("grid_*.png"))
            if grid_index >= len(grid_files):
                raise RuntimeError(f"Grid index {grid_index} out of range")

            grid_path = grid_files[grid_index]
            threeview_dir = project_dir / "cha_3view"
            threeview_path = next(threeview_dir.glob("threeview.*"))

            # Load only THIS grid's info
            gi = GridInfo(**grids_data[grid_index]) if grid_index < len(grids_data) else None
            next_ver = (max((v.version for v in gi.versions), default=0) + 1) if gi else 1

            # Mark as pending
            if gi:
                gi.status = "pending"
                gi.retry_count = 0
                gi.error_msg = ""
                self._persist_single_grid(project_id, project_dir, grid_index, gi)

            def on_retry(attempt, max_retries):
                if gi:
                    gi.status = "retrying"
                    gi.retry_count = attempt
                    self._persist_single_grid(project_id, project_dir, grid_index, gi)

            result_path, retry_count, error_msg = await redraw_single_grid(
                grid_path,
                threeview_path,
                project_dir / "grids_redrawn",
                aspect_ratio=aspect_ratio,
                on_retry=on_retry,
                version_num=next_ver,
            )

            now_str = datetime.now(timezone.utc).isoformat()

            if result_path and gi:
                gi.status = "success"
                gi.retry_count = retry_count
                gi.error_msg = ""
                ver_filename = f"{grid_path.stem}_v{next_ver}.png"
                gi.versions.append(GridVersion(
                    version=next_ver, filename=ver_filename,
                    status="success", created_at=now_str,
                ))
                gi.active_version = next_ver
            elif gi:
                gi.status = "failed"
                gi.retry_count = retry_count
                gi.error_msg = error_msg
                gi.versions.append(GridVersion(
                    version=next_ver,
                    filename=f"{grid_path.stem}_v{next_ver}.png",
                    status="failed", created_at=now_str,
                ))

            # Persist only this grid + mark dirty
            if gi:
                self._persist_single_grid(project_id, project_dir, grid_index, gi, dirty=True)

            logger.info("Reroll grid %d complete for project %s", grid_index, project_id)

        except asyncio.CancelledError:
            logger.info("Reroll grid %d cancelled for project %s", grid_index, project_id)
            try:
                meta = load_metadata(project_dir)
                grids_data = meta.get("grids", [])
                if grid_index < len(grids_data):
                    cancelled_gi = GridInfo(**grids_data[grid_index])
                    cancelled_gi.status = "failed"
                    cancelled_gi.error_msg = "已取消"
                    self._persist_single_grid(project_id, project_dir, grid_index, cancelled_gi)
            except Exception:
                pass
        except Exception as e:
            logger.exception("Reroll grid %d failed for project %s", grid_index, project_id)
            try:
                meta = load_metadata(project_dir)
                grids_data = meta.get("grids", [])
                if grid_index < len(grids_data):
                    failed_gi = GridInfo(**grids_data[grid_index])
                    failed_gi.status = "failed"
                    failed_gi.error_msg = str(e)
                    self._persist_single_grid(project_id, project_dir, grid_index, failed_gi)
            except Exception:
                pass

    async def _run_reassemble(self, project_id: str, project_dir: Path):
        """Re-split all grids and re-assemble video."""
        start_time = time.time()

        def elapsed():
            s = self._states.get(project_id)
            if s:
                s.elapsed_seconds = time.time() - start_time

        try:
            meta = load_metadata(project_dir)
            grid_size = meta.get("grid_size", 4)
            video_info_data = meta.get("video_info", {})
            video_info = VideoInfo(**video_info_data) if video_info_data else None
            hold_map_data = meta.get("frame_hold_map", {})
            grids_data = meta.get("grids", [])
            grid_infos = [GridInfo(**g) for g in grids_data]

            if not video_info:
                raise RuntimeError("No video_info in metadata")

            hold_map = FrameHoldMap(**hold_map_data) if hold_map_data else FrameHoldMap()

            # Ensure in-memory state exists
            if project_id not in self._states:
                self._states[project_id] = PipelineStatus(
                    project_id=project_id,
                    stage=PipelineStage.IDLE,
                    grids=grid_infos,
                )

            # Split grids
            self._update(project_id, PipelineStage.SPLITTING_GRIDS, 0, "正在重新拆分...",
                         grids=grid_infos)
            elapsed()

            split_grids(
                project_dir / "grids_redrawn",
                project_dir / "frames_redrawn",
                len(hold_map.holds),
                grid_size=grid_size,
            )
            self._update(project_id, PipelineStage.SPLITTING_GRIDS, 100, "拆分完成",
                         grids=grid_infos)
            elapsed()

            # Assemble video
            self._update(project_id, PipelineStage.ASSEMBLING_VIDEO, 0, "正在重新合成视频...",
                         grids=grid_infos)
            elapsed()

            input_dir = project_dir / "input"
            video_path = next(input_dir.glob("video.*"))

            await assemble_video(
                project_dir / "frames_redrawn",
                video_path,
                project_dir / "output" / "final.mp4",
                hold_map,
                video_info.width,
                video_info.height,
            )
            self._update(project_id, PipelineStage.ASSEMBLING_VIDEO, 100, "视频合成完成",
                         grids=grid_infos)
            elapsed()

            # Clear dirty flag
            meta = load_metadata(project_dir)
            meta["grids_dirty"] = False
            save_metadata(project_dir, meta)

            self._update(project_id, PipelineStage.COMPLETE, 100, "视频更新完成!",
                         grids=grid_infos)
            elapsed()

            logger.info("Reassemble complete for project %s (%.1fs)",
                        project_id, time.time() - start_time)

        except asyncio.CancelledError:
            logger.info("Reassemble cancelled for project %s", project_id)
            self._update(project_id, PipelineStage.FAILED, 0, "已取消")
        except Exception as e:
            logger.exception("Reassemble failed for project %s", project_id)
            self._update(project_id, PipelineStage.FAILED, 0, f"视频合成失败: {e}")
