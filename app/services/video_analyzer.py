from __future__ import annotations

import re
import logging
from pathlib import Path
from fractions import Fraction
from collections import Counter

from app.models import VideoInfo
from app.utils.ffmpeg import probe_video, run_ffmpeg
from app.config import get_settings

logger = logging.getLogger(__name__)


async def analyze_video(video_path: Path) -> VideoInfo:
    """Analyze video metadata and frame hold pattern."""
    settings = get_settings()

    # Get basic metadata via ffmpeg probe
    probe = await probe_video(video_path)
    video_stream = next(
        (s for s in probe.get("streams", []) if s["codec_type"] == "video"),
        None,
    )
    if not video_stream:
        raise ValueError("No video stream found")

    width = int(video_stream["width"])
    height = int(video_stream["height"])
    fps_frac = Fraction(video_stream.get("r_frame_rate", "30/1"))
    fps = float(fps_frac)
    duration = float(probe.get("format", {}).get("duration", 0))
    total_frames = int(fps * duration)

    # Analyze frame hold pattern with mpdecimate
    unique_count, hold_pattern = await _analyze_hold_pattern(
        video_path, settings.mpdecimate_params
    )

    grid_count = (unique_count + 3) // 4  # ceil division

    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        total_frames=total_frames,
        unique_frames=unique_count,
        grid_count=grid_count,
        hold_pattern=hold_pattern,
    )


async def _analyze_hold_pattern(video_path: Path, mpdecimate_params: str) -> tuple[int, str]:
    """Run mpdecimate to detect unique frame count and hold pattern."""
    # Run mpdecimate with debug to get keep/drop info
    _, stderr = await run_ffmpeg(
        "-i", str(video_path),
        "-vf", f"mpdecimate={mpdecimate_params}",
        "-loglevel", "debug",
        "-vsync", "vfr",
        "-f", "null",
        "-",
    )

    # Parse keep events and count drops between them
    keep_times = []
    for line in stderr.splitlines():
        if "keep pts:" in line and "drop_count:" in line:
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                keep_times.append(float(m.group(1)))

    unique_count = len(keep_times)
    if unique_count == 0:
        return 0, "unknown"

    # Calculate hold durations (gaps between consecutive keeps)
    drop_counts = Counter()
    for i in range(len(keep_times) - 1):
        gap = keep_times[i + 1] - keep_times[i]
        # At 30fps, 1 frame = ~0.033s
        frames_held = max(1, round(gap * 30))  # approximate
        drop_counts[frames_held] += 1

    if not drop_counts:
        return unique_count, "1-on-1s"

    # Describe the dominant pattern
    most_common = drop_counts.most_common(3)
    parts = []
    for hold, count in most_common:
        parts.append(f"{hold}拍({count}次)")
    pattern = "混合: " + ", ".join(parts)

    return unique_count, pattern
