"""fal.ai wrapper — submits jobs with a webhook_url (no polling)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import fal_client


def _ensure_key() -> None:
    os.environ.setdefault("FAL_KEY", os.environ.get("FAL_KEY", ""))


async def upload_image(path: Path) -> str:
    """Upload a local file to fal.ai storage and return the URL."""
    _ensure_key()
    return await asyncio.to_thread(fal_client.upload_file, str(path))


async def submit_job(endpoint: str, arguments: dict[str, Any], webhook_url: str) -> str:
    """Submit a job to fal.ai with a webhook callback. Returns the request_id."""
    _ensure_key()
    handle = await fal_client.submit_async(endpoint, arguments, webhook_url=webhook_url)
    return str(handle.request_id)


def extract_output_url(result: dict[str, Any], job_type: str) -> str | None:
    """Recursively walk the fal.ai result dict to find the output URL."""
    preferred = ("video", "video_url") if job_type == "video" else ("images", "image", "image_url")

    def walk(value: Any) -> str | None:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if isinstance(value, dict):
            for name in preferred:
                if name in value:
                    found = walk(value[name])
                    if found:
                        return found
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None

    return walk(result)
