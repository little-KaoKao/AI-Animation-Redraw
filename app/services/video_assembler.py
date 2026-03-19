from __future__ import annotations

import logging
from pathlib import Path

from app.models import FrameHoldMap
from app.utils.ffmpeg import run_ffmpeg
from app.config import get_settings

logger = logging.getLogger(__name__)


async def assemble_video(
    frames_dir: Path,
    original_video: Path,
    output_path: Path,
    hold_map: FrameHoldMap,
    width: int,
    height: int,
) -> Path:
    """
    Assemble redrawn frames into final video with original timing and audio.
    Uses ffmpeg concat demuxer for precise frame durations.
    """
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fps = hold_map.fps
    frame_interval = 1.0 / fps

    # Generate concat list file
    concat_path = frames_dir.parent / "concat_list.txt"
    with open(concat_path, "w", encoding="utf-8") as f:
        sorted_indices = sorted(hold_map.holds.keys())
        for i, idx in enumerate(sorted_indices):
            frame_path = frames_dir / f"frame_{idx:04d}.png"
            if not frame_path.exists():
                logger.warning("Missing frame %d, skipping", idx)
                continue

            hold_count = hold_map.holds[idx]
            duration = hold_count * frame_interval

            # ffmpeg concat demuxer requires forward slashes on all platforms
            f.write(f"file '{frame_path.as_posix()}'\n")
            f.write(f"duration {duration:.6f}\n")

        # Repeat last frame entry (required by concat demuxer)
        if sorted_indices:
            last_idx = sorted_indices[-1]
            last_path = frames_dir / f"frame_{last_idx:04d}.png"
            if last_path.exists():
                f.write(f"file '{last_path.as_posix()}'\n")

    # Step 1: Create video from frames (no audio)
    temp_video = output_path.parent / "temp_noaudio.mp4"
    await run_ffmpeg(
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path),
        "-vf", f"scale={width}:{height}",
        "-c:v", settings.processing.get("output_video_codec", "libx264"),
        "-crf", str(settings.video_crf),
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-y", str(temp_video),
    )

    # Step 2: Extract audio from original video
    temp_audio = output_path.parent / "temp_audio.aac"
    await run_ffmpeg(
        "-i", str(original_video),
        "-vn", "-acodec", "copy",
        "-y", str(temp_audio),
    )

    # Step 3: Merge video + audio
    if temp_audio.exists() and temp_audio.stat().st_size > 0:
        await run_ffmpeg(
            "-i", str(temp_video),
            "-i", str(temp_audio),
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-y", str(output_path),
        )
    else:
        # No audio track, just rename
        logger.info("No audio track found, output video without audio")
        temp_video.rename(output_path)

    # Cleanup temp files
    for tmp in [temp_video, temp_audio, concat_path]:
        if tmp.exists():
            tmp.unlink()

    logger.info("Video assembled: %s", output_path)
    return output_path
