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
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[Path]:
    """
    Redraw all grid images using the 3-view as character reference.
    Uses asyncio.Semaphore for concurrency control.
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

    async def redraw_one(index: int, grid_path: Path):
        nonlocal completed
        async with semaphore:
            try:
                # Upload grid image
                grid_url = await client.upload_image(grid_path)

                # Submit redraw task
                task_id = await client.image_to_image(
                    image_urls=[threeview_url, grid_url],
                    prompt=settings.redraw_prompt,
                    resolution=settings.default_resolution,
                    aspect_ratio=aspect_ratio,
                )

                # Poll until done
                logger.info("Redrawing grid %d/%d (task: %s)...", index + 1, total, task_id)
                task_results = await client.poll_until_done(task_id)

                if not task_results:
                    raise RuntimeError(f"Grid {index + 1} redraw returned no results")

                # Download result
                result_url = task_results[0].get("fileUrl") or task_results[0].get("url", "")
                out_name = grid_path.name  # Keep same naming
                out_path = output_dir / out_name
                await client.download_file(result_url, out_path)

                results[index] = out_path
                completed += 1
                logger.info("Grid %d/%d complete", completed, total)

                if on_progress:
                    on_progress(completed, total)

            except Exception as e:
                logger.error("Failed to redraw grid %d: %s", index + 1, e)
                completed += 1
                if on_progress:
                    on_progress(completed, total)
                raise

    # Launch all tasks (semaphore controls actual concurrency)
    tasks = [redraw_one(i, p) for i, p in enumerate(grid_paths)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Collect successful results
    successful = [p for p in results if p is not None]
    if len(successful) < total:
        failed = total - len(successful)
        logger.warning("%d/%d grids failed to redraw", failed, total)

    return successful
