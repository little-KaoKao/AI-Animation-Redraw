from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

from app.config import get_settings
from app.services.runninghub_client import RunningHubClient

logger = logging.getLogger(__name__)


async def redraw_all_grids(
    grid_paths: list[Path],
    threeview_path: Path,
    output_dir: Path,
    aspect_ratio: str = "9:16",
    on_progress: Optional[Callable[..., None]] = None,
) -> list[Path]:
    """
    Redraw all grid images using the 3-view as character reference.
    Uses asyncio.Semaphore for concurrency control.
    on_progress(done, total, grid_index, success)
    Returns list of redrawn grid paths.
    """
    settings = get_settings()
    client = RunningHubClient()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Upload 3-view once (reuse URL for all grids)
    logger.info("Uploading 3-view for grid redraw...")
    threeview_url = await client.upload_image(threeview_path)

    semaphore = asyncio.Semaphore(settings.max_concurrent_redraws)
    completed = 0
    total = len(grid_paths)
    results: list[Optional[Path]] = [None] * total

    max_retries = settings.rh_max_retries

    async def redraw_one(index: int, grid_path: Path):
        nonlocal completed
        async with semaphore:
            last_err = None
            for attempt in range(max_retries + 1):
                try:
                    grid_url = await client.upload_image(grid_path)

                    task_id = await client.image_to_image(
                        image_urls=[threeview_url, grid_url],
                        prompt=settings.redraw_prompt,
                        resolution=settings.default_resolution,
                        aspect_ratio=aspect_ratio,
                    )

                    logger.info("Redrawing grid %d/%d (task: %s)...", index + 1, total, task_id)
                    task_results = await client.poll_until_done(task_id)

                    if not task_results:
                        raise RuntimeError(f"Grid {index + 1} redraw returned no results")

                    result_url = task_results[0].get("fileUrl") or task_results[0].get("url", "")
                    out_name = grid_path.name
                    out_path = output_dir / out_name
                    await client.download_file(result_url, out_path)

                    results[index] = out_path
                    completed += 1
                    logger.info("Grid %d/%d complete", completed, total)

                    if on_progress:
                        on_progress(completed, total, index, True)
                    return  # success

                except Exception as e:
                    last_err = e
                    if attempt < max_retries:
                        wait = 2 ** attempt
                        logger.warning("Grid %d attempt %d failed, retrying in %ds: %s",
                                       index + 1, attempt + 1, wait, e)
                        if on_progress:
                            on_progress(completed, total, index, False,
                                        f"重试中 ({attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait)
                    else:
                        logger.error("Grid %d failed after %d retries: %s",
                                     index + 1, max_retries + 1, e)
                        completed += 1
                        if on_progress:
                            on_progress(completed, total, index, False)
                        raise last_err

    tasks = [redraw_one(i, p) for i, p in enumerate(grid_paths)]
    await asyncio.gather(*tasks, return_exceptions=True)

    successful = [p for p in results if p is not None]
    if len(successful) < total:
        failed = total - len(successful)
        logger.warning("%d/%d grids failed to redraw", failed, total)

    return successful


async def redraw_single_grid(
    grid_path: Path,
    threeview_path: Path,
    output_dir: Path,
    aspect_ratio: str = "9:16",
    on_retry: Optional[Callable[[int, int], None]] = None,
    version_num: int = 0,
) -> tuple[Optional[Path], int, str]:
    """Redraw a single grid image with auto-retry.

    Returns (output_path, retry_count, error_msg).
    If version_num > 0, saves as grid_NNN_vN.png in addition to grid_NNN.png.
    """
    settings = get_settings()
    client = RunningHubClient()
    output_dir.mkdir(parents=True, exist_ok=True)
    max_retries = settings.rh_max_retries
    retry_count = 0

    threeview_url = await client.upload_image(threeview_path)

    for attempt in range(max_retries + 1):
        try:
            grid_url = await client.upload_image(grid_path)

            task_id = await client.image_to_image(
                image_urls=[threeview_url, grid_url],
                prompt=settings.redraw_prompt,
                resolution=settings.default_resolution,
                aspect_ratio=aspect_ratio,
            )

            logger.info("Redrawing single grid %s attempt %d (task: %s)...",
                        grid_path.name, attempt + 1, task_id)
            task_results = await client.poll_until_done(task_id)

            if not task_results:
                raise RuntimeError(f"Grid redraw returned no results: {grid_path.name}")

            result_url = task_results[0].get("fileUrl") or task_results[0].get("url", "")
            out_path = output_dir / grid_path.name
            await client.download_file(result_url, out_path)

            # Save versioned copy for history
            if version_num > 0:
                stem = grid_path.stem  # e.g. grid_001
                ver_name = f"{stem}_v{version_num}.png"
                ver_path = output_dir / ver_name
                import shutil
                shutil.copy2(str(out_path), str(ver_path))

            logger.info("Single grid redraw complete: %s", out_path.name)
            return out_path, retry_count, ""

        except Exception as e:
            retry_count = attempt + 1
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("Single grid %s attempt %d failed, retrying in %ds: %s",
                               grid_path.name, attempt + 1, wait, e)
                if on_retry:
                    on_retry(attempt + 1, max_retries)
                await asyncio.sleep(wait)
            else:
                logger.error("Single grid %s failed after %d retries: %s",
                             grid_path.name, max_retries + 1, e)
                return None, retry_count, str(e)
