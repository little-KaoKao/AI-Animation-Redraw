from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

GRID_SIZE = 4  # frames per grid


def compose_grids(
    frames_dir: Path,
    grids_dir: Path,
    frame_count: int,
    frame_width: int,
    frame_height: int,
) -> list[Path]:
    """
    Compose every 4 frames into a 2x2 grid image.
    Portrait (H > W): 2 cols x 2 rows, each cell = W/2 x H/2 -> grid = W x H
    Landscape (W >= H): same 2x2 layout

    Returns list of grid file paths.
    """
    grids_dir.mkdir(parents=True, exist_ok=True)

    # Grid cell size: half of original dimensions
    cell_w = frame_width // 2
    cell_h = frame_height // 2
    grid_w = cell_w * 2
    grid_h = cell_h * 2

    grid_paths = []
    group = 1

    for start in range(1, frame_count + 1, GRID_SIZE):
        end = min(start + GRID_SIZE - 1, frame_count)
        grid_name = f"grid_{group:03d}_frames_{start:04d}-{end:04d}.png"
        grid_path = grids_dir / grid_name

        grid_img = Image.new("RGB", (grid_w, grid_h), (0, 0, 0))

        for idx in range(GRID_SIZE):
            frame_num = start + idx
            frame_path = frames_dir / f"frame_{frame_num:04d}.png"

            if frame_path.exists():
                frame_img = Image.open(frame_path)
                frame_img = frame_img.resize((cell_w, cell_h), Image.LANCZOS)
            else:
                # Pad with black for incomplete last group
                frame_img = Image.new("RGB", (cell_w, cell_h), (0, 0, 0))

            # 2x2 layout: top-left, top-right, bottom-left, bottom-right
            row = idx // 2
            col = idx % 2
            grid_img.paste(frame_img, (col * cell_w, row * cell_h))

        grid_img.save(grid_path)
        grid_paths.append(grid_path)
        group += 1

    logger.info("Composed %d grids from %d frames", len(grid_paths), frame_count)
    return grid_paths
