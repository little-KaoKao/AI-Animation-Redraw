from __future__ import annotations

import re
import logging
from pathlib import Path

from app.models import FrameHoldMap
from app.utils.ffmpeg import run_ffmpeg
from app.config import get_settings

logger = logging.getLogger(__name__)


async def extract_unique_frames(
    video_path: Path,
    output_dir: Path,
    fps: float,
) -> FrameHoldMap:
    """
    Extract unique (non-duplicate) frames using mpdecimate.
    Returns a FrameHoldMap with the number of video frames each unique frame holds.
    """
    settings = get_settings()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run mpdecimate with debug logging to capture keep/drop events
    _, stderr = await run_ffmpeg(
        "-i", str(video_path),
        "-vf", f"mpdecimate={settings.mpdecimate_params}",
        "-loglevel", "debug",
        "-vsync", "vfr",
        str(output_dir / "frame_%04d.png"),
    )

    # Parse keep event timestamps from debug output
    keep_times = []
    for line in stderr.splitlines():
        if "keep pts:" in line and "pts_time:" in line:
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                keep_times.append(float(m.group(1)))

    # Build hold map: how many original frames each unique frame occupies
    holds: dict[int, int] = {}
    frame_interval = 1.0 / fps if fps > 0 else 1.0 / 30

    for i in range(len(keep_times)):
        frame_idx = i + 1  # 1-based to match frame_%04d naming
        if i + 1 < len(keep_times):
            gap = keep_times[i + 1] - keep_times[i]
            hold_count = max(1, round(gap / frame_interval))
        else:
            # Last frame: default to the most common hold or 1
            hold_count = _guess_last_hold(holds)
        holds[frame_idx] = hold_count

    unique_count = len(keep_times)
    logger.info("Extracted %d unique frames from %s", unique_count, video_path.name)

    return FrameHoldMap(holds=holds, fps=fps)


def _guess_last_hold(holds: dict[int, int]) -> int:
    """Guess hold count for the last frame based on the most common value."""
    if not holds:
        return 1
    from collections import Counter
    counts = Counter(holds.values())
    return counts.most_common(1)[0][0]
