from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def _grid_layout(grid_size: int) -> int:
    """Return number of columns/rows for the given grid_size (1, 4, or 9)."""
    return int(math.isqrt(grid_size))


def compose_grids(
    frames_dir: Path,
    grids_dir: Path,
    frame_count: int,
    frame_width: int,
    frame_height: int,
    grid_size: int = 4,
) -> list[Path]:
    """
    Compose frames into grid images.
    grid_size=1: 1x1 (single frame, no tiling)
    grid_size=4: 2x2
    grid_size=9: 3x3

    Returns list of grid file paths.
    """
    grids_dir.mkdir(parents=True, exist_ok=True)
    n = _grid_layout(grid_size)  # 1, 2, or 3

    cell_w = frame_width // n
    cell_h = frame_height // n
    grid_w = cell_w * n
    grid_h = cell_h * n

    grid_paths = []
    group = 1

    for start in range(1, frame_count + 1, grid_size):
        end = min(start + grid_size - 1, frame_count)
        grid_name = f"grid_{group:03d}_frames_{start:04d}-{end:04d}.png"
        grid_path = grids_dir / grid_name

        grid_img = Image.new("RGB", (grid_w, grid_h), (0, 0, 0))

        for idx in range(grid_size):
            frame_num = start + idx
            frame_path = frames_dir / f"frame_{frame_num:04d}.png"

            if frame_path.exists():
                frame_img = Image.open(frame_path)
                frame_img = frame_img.resize((cell_w, cell_h), Image.LANCZOS)
            else:
                frame_img = Image.new("RGB", (cell_w, cell_h), (0, 0, 0))

            row = idx // n
            col = idx % n
            grid_img.paste(frame_img, (col * cell_w, row * cell_h))

        grid_img.save(grid_path)
        grid_paths.append(grid_path)
        group += 1

    logger.info("Composed %d grids from %d frames (grid_size=%d)", len(grid_paths), frame_count, grid_size)
    return grid_paths
