from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings
from app.services.runninghub_client import RunningHubClient

logger = logging.getLogger(__name__)


async def generate_threeview(
    character_path: Path,
    output_dir: Path,
) -> Path:
    """
    Generate a 3-view character reference sheet from the character image.
    Returns the path to the saved 3-view image.
    """
    settings = get_settings()
    client = RunningHubClient()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Upload character image
    logger.info("Uploading character image for 3-view generation...")
    char_url = await client.upload_image(character_path)

    # Submit image-to-image task with 3-view prompt
    task_id = await client.image_to_image(
        image_urls=[char_url],
        prompt=settings.threeview_prompt,
        resolution=settings.default_resolution,
        aspect_ratio="16:9",  # Wide format for side/front/back layout
    )

    # Poll until done
    logger.info("Waiting for 3-view generation (task: %s)...", task_id)
    results = await client.poll_until_done(task_id)

    if not results:
        raise RuntimeError("3-view generation returned no results")

    # Download the result
    result_url = results[0].get("fileUrl") or results[0].get("url", "")
    output_path = output_dir / "threeview.png"
    await client.download_file(result_url, output_path)

    logger.info("3-view saved to %s", output_path)
    return output_path
