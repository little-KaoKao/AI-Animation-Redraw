from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


async def run_ffmpeg(*args: str, timeout: int = 600) -> tuple[str, str]:
    settings = get_settings()
    cmd = [settings.ffmpeg_path, *args]
    logger.debug("ffmpeg: %s", " ".join(cmd))

    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

    stdout_str = proc.stdout.decode("utf-8", errors="replace")
    stderr_str = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        logger.error("ffmpeg failed (rc=%d): %s", proc.returncode, stderr_str[-500:])
    return stdout_str, stderr_str


async def probe_video(video_path: str | Path) -> dict:
    """Parse video metadata from ffmpeg -i stderr output (no ffprobe needed)."""
    settings = get_settings()
    cmd = [settings.ffmpeg_path, "-i", str(video_path)]
    logger.debug("probe: %s", " ".join(cmd))

    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

    stderr_str = proc.stderr.decode("utf-8", errors="replace")

    result: dict = {"streams": [], "format": {}}

    # Parse duration from "Duration: HH:MM:SS.ss"
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr_str)
    if dur_match:
        h, m, s = dur_match.groups()
        result["format"]["duration"] = str(int(h) * 3600 + int(m) * 60 + float(s))

    # Parse video stream: "Stream #...: Video: codec, ..., WxH, ..., fps_val fps"
    vid_match = re.search(
        r"Stream\s+#\S+.*?Video:\s+\S+.*?,\s*(\d+)x(\d+).*?,\s*([\d.]+)\s+fps",
        stderr_str,
    )
    if vid_match:
        w, h, fps = vid_match.groups()
        result["streams"].append({
            "codec_type": "video",
            "width": w,
            "height": h,
            "r_frame_rate": f"{fps}/1",
        })

    # Parse audio stream
    if re.search(r"Stream\s+#\S+.*?Audio:", stderr_str):
        result["streams"].append({"codec_type": "audio"})

    return result
