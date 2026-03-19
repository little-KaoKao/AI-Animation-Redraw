from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def _grid_layout(grid_size: int) -> int:
    """Return number of columns/rows for the given grid_size (1, 4, or 9)."""
    return int(math.isqrt(grid_size))


def split_grids(
    grids_redrawn_dir: Path,
    frames_redrawn_dir: Path,
    total_unique_frames: int,
    grid_size: int = 4,
) -> list[Path]:
    """
    Split redrawn grid images back into individual frames.
    Supports grid_size 1, 4, or 9.
    Returns list of frame paths in order.
    """
    frames_redrawn_dir.mkdir(parents=True, exist_ok=True)
    n = _grid_layout(grid_size)

    frame_paths = []
    frame_num = 1

    grid_files = sorted(grids_redrawn_dir.glob("grid_*.png"))

    for grid_path in grid_files:
        grid_img = Image.open(grid_path)
        gw, gh = grid_img.size
        cell_w = gw // n
        cell_h = gh // n

        for idx in range(grid_size):
            if frame_num > total_unique_frames:
                break

            row = idx // n
            col = idx % n
            left = col * cell_w
            top = row * cell_h

            frame_img = grid_img.crop((left, top, left + cell_w, top + cell_h))
            frame_path = frames_redrawn_dir / f"frame_{frame_num:04d}.png"
            frame_img.save(frame_path)
            frame_paths.append(frame_path)
            frame_num += 1

    logger.info("Split %d frames from redrawn grids (grid_size=%d)", len(frame_paths), grid_size)
    return frame_paths
