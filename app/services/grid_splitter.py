from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

GRID_SIZE = 4


def split_grids(
    grids_redrawn_dir: Path,
    frames_redrawn_dir: Path,
    total_unique_frames: int,
) -> list[Path]:
    """
    Split redrawn 2x2 grid images back into individual frames.
    Returns list of frame paths in order.
    """
    frames_redrawn_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = []
    frame_num = 1

    grid_files = sorted(grids_redrawn_dir.glob("grid_*.png"))

    for grid_path in grid_files:
        grid_img = Image.open(grid_path)
        gw, gh = grid_img.size
        cell_w = gw // 2
        cell_h = gh // 2

        for idx in range(GRID_SIZE):
            if frame_num > total_unique_frames:
                break

            row = idx // 2
            col = idx % 2
            left = col * cell_w
            top = row * cell_h

            frame_img = grid_img.crop((left, top, left + cell_w, top + cell_h))
            frame_path = frames_redrawn_dir / f"frame_{frame_num:04d}.png"
            frame_img.save(frame_path)
            frame_paths.append(frame_path)
            frame_num += 1

    logger.info("Split %d frames from redrawn grids", len(frame_paths))
    return frame_paths
