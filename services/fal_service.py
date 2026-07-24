"""Small wrapper around fal-client with retry-friendly async operations."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import fal_client


class FalService:
    def __init__(self, api_key: str):
        os.environ["FAL_KEY"] = api_key

    async def upload_image(self, path: Path) -> str:
        return await asyncio.to_thread(fal_client.upload_file, path)

    async def submit(self, endpoint: str, arguments: dict[str, Any]) -> str:
        handle = await fal_client.submit_async(endpoint, arguments)
        return str(handle.request_id)

    async def wait_for_result(
        self, endpoint: str, request_id: str, timeout_seconds: int = 900
    ) -> dict[str, Any]:
        handle = fal_client.AsyncRequestHandle.from_request_id(
            fal_client.AsyncClient(), endpoint, request_id
        )
        result = await asyncio.wait_for(handle.get(), timeout=timeout_seconds)
        if not isinstance(result, dict):
            raise RuntimeError("fal.ai returned an unexpected result.")
        return result