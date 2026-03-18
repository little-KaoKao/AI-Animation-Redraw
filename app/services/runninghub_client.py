from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class RunningHubClient:
    """Async client for RunningHub API."""

    def __init__(self):
        self._settings = get_settings()
        self._base = self._settings.rh_base_url

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._settings.runninghub_api_key}"}

    async def upload_image(self, file_path: Path) -> str:
        """Upload an image file. Returns the download_url."""
        url = f"{self._base}{self._settings.runninghub.get('upload_endpoint', '/openapi/v2/media/upload/binary')}"

        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "image/png")}
                for attempt in range(self._settings.rh_max_retries + 1):
                    try:
                        resp = await client.post(url, headers=self._headers(), files=files)
                        resp.raise_for_status()
                        data = resp.json()
                        if data.get("code") != 0:
                            raise RuntimeError(f"Upload failed: {data.get('message', 'unknown error')}")
                        download_url = data["data"]["download_url"]
                        logger.info("Uploaded %s -> %s", file_path.name, download_url[:80])
                        return download_url
                    except (httpx.HTTPError, KeyError) as e:
                        if attempt < self._settings.rh_max_retries:
                            wait = self._settings.runninghub.get("retry_backoff_base", 2) ** attempt
                            logger.warning("Upload attempt %d failed, retrying in %ds: %s", attempt + 1, wait, e)
                            f.seek(0)
                            await asyncio.sleep(wait)
                        else:
                            raise

    async def image_to_image(
        self,
        image_urls: list[str],
        prompt: str,
        resolution: str = "2k",
        aspect_ratio: str = "9:16",
    ) -> str:
        """Submit an image-to-image generation task. Returns taskId."""
        endpoint = self._settings.runninghub.get(
            "image_to_image_endpoint",
            "/openapi/v2/rhart-image-n-g31-flash-official/image-to-image",
        )
        url = f"{self._base}{endpoint}"
        body = {
            "imageUrls": image_urls,
            "prompt": prompt,
            "resolution": resolution,
            "aspectRatio": aspect_ratio,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()

        task_id = data.get("taskId")
        if not task_id:
            raise RuntimeError(f"No taskId in response: {data}")

        logger.info("Submitted image-to-image task: %s", task_id)
        return task_id

    async def poll_task_status(self, task_id: str) -> str:
        """Check task status. Returns QUEUED/RUNNING/SUCCESS/FAILED."""
        endpoint = self._settings.runninghub.get(
            "task_status_endpoint", "/task/openapi/status"
        )
        url = f"{self._base}{endpoint}"
        body = {
            "apiKey": self._settings.runninghub_api_key,
            "taskId": task_id,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", "UNKNOWN")

    async def get_task_results(self, task_id: str) -> list[dict]:
        """Get task output files. Returns list of {fileUrl, fileType}."""
        endpoint = self._settings.runninghub.get(
            "task_outputs_endpoint", "/task/openapi/outputs"
        )
        url = f"{self._base}{endpoint}"
        body = {
            "apiKey": self._settings.runninghub_api_key,
            "taskId": task_id,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", [])

    async def poll_until_done(self, task_id: str) -> list[dict]:
        """Poll task until SUCCESS or FAILED. Returns task results."""
        for attempt in range(self._settings.rh_max_poll_attempts):
            status = await self.poll_task_status(task_id)
            logger.debug("Task %s status: %s (poll %d)", task_id, status, attempt + 1)

            if status == "SUCCESS":
                return await self.get_task_results(task_id)
            elif status == "FAILED":
                raise RuntimeError(f"Task {task_id} failed")

            await asyncio.sleep(self._settings.rh_poll_interval)

        raise TimeoutError(f"Task {task_id} timed out after {self._settings.rh_max_poll_attempts} polls")

    async def download_file(self, url: str, save_path: Path):
        """Download a file from URL to local path."""
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
        logger.info("Downloaded %s -> %s", url[:60], save_path.name)
