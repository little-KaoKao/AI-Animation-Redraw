from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic_settings import BaseSettings


def _default_ffmpeg_path() -> str:
    """Return a sensible default ffmpeg path based on the current OS."""
    if platform.system() == "Windows":
        return "bin\\ffmpeg.exe"
    # macOS / Linux: expect ffmpeg on PATH
    return "ffmpeg"


class Settings(BaseSettings):
    # .env fields
    runninghub_api_key: str = ""
    ffmpeg_path: str = _default_ffmpeg_path()
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: str = "./data"

    # Loaded from config.yaml at runtime
    runninghub: dict = {}
    processing: dict = {}
    prompts: dict = {}
    output: dict = {}

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    _project_root: Path = Path(__file__).parent.parent

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._load_yaml()
        # Resolve ffmpeg_path
        fp = Path(self.ffmpeg_path)
        if not fp.is_absolute():
            # If it looks like a relative path to a bundled binary, resolve it
            resolved = self._project_root / fp
            if resolved.exists():
                self.ffmpeg_path = str(resolved)
            else:
                # Try to find ffmpeg on system PATH
                found = shutil.which(self.ffmpeg_path)
                if found:
                    self.ffmpeg_path = found

    def _load_yaml(self):
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.runninghub = data.get("runninghub", {})
            self.processing = data.get("processing", {})
            self.prompts = data.get("prompts", {})
            self.output = data.get("output", {})

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def projects_path(self) -> Path:
        p = self.data_path / "projects"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # RunningHub helpers
    @property
    def rh_base_url(self) -> str:
        return self.runninghub.get("base_url", "https://www.runninghub.cn")

    @property
    def rh_poll_interval(self) -> int:
        return self.runninghub.get("poll_interval_seconds", 5)

    @property
    def rh_max_poll_attempts(self) -> int:
        return self.runninghub.get("max_poll_attempts", 120)

    @property
    def rh_max_retries(self) -> int:
        return self.runninghub.get("max_retries", 3)

    @property
    def max_concurrent_redraws(self) -> int:
        return self.processing.get("max_concurrent_redraws", 4)

    @property
    def mpdecimate_params(self) -> str:
        return self.processing.get("mpdecimate_params", "hi=64*12:lo=64*5:frac=0.33")

    @property
    def threeview_prompt(self) -> str:
        return self.prompts.get("threeview_generation", "")

    @property
    def redraw_prompt(self) -> str:
        return self.prompts.get("grid_redraw", "")

    @property
    def default_resolution(self) -> str:
        return self.output.get("default_resolution", "2k")

    @property
    def video_crf(self) -> int:
        return self.processing.get("output_video_crf", 18)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
