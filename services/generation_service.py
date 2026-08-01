"""Generation orchestration: debit, submit, poll, deliver, refund on failure."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from database import Database
from database.db import utc_now
from models_config import AIModel

from .credit_service import CreditService
from .fal_service import FalService

logger = logging.getLogger(__name__)
DeliveryCallback = Callable[[dict[str, Any]], Awaitable[None]]


def extract_output_url(result: dict[str, Any], job_type: str) -> str | None:
    preferred = ("video", "video_url") if job_type == "video" else ("images", "image", "image_url")

    def walk(value: Any, key: str = "") -> str | None:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if isinstance(value, dict):
            for name in preferred:
                if name in value:
                    found = walk(value[name], name)
                    if found:
                        return found
            for child_key, child in value.items():
                found = walk(child, child_key)
                if found:
                    return found
        if isinstance(value, list):
            for child in value:
                found = walk(child, key)
                if found:
                    return found
        return None

    return walk(result)


class GenerationService:
    def __init__(self, db: Database, fal: FalService):
        self.db = db
        self.credit = CreditService(db)
        self.fal = fal
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(
        self,
        user_id: int,
        model: AIModel,
        prompt: str,
        image_path: Path | None,
        deliver: DeliveryCallback,
        extra_args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Debit the user, upload image if any, submit to fal.ai, then poll in a background task.

        extra_args is merged into the fal.ai arguments dict after the base keys (prompt,
        image_url).  Use it to pass aspect_ratio or image_size from ratio_to_dimension_map.
        """
        job_id = uuid4().hex
        await self.credit.debit(user_id, model.sell_price_sen, job_id)
        uploaded_url: str | None = None
        try:
            if image_path:
                uploaded_url = await self.fal.upload_image(image_path)
            arguments: dict[str, Any] = {"prompt": prompt}
            if uploaded_url:
                arguments["image_url"] = uploaded_url
            if extra_args:
                arguments.update(extra_args)
            await self.db.create_job(
                job_id,
                user_id,
                model.key,
                model.job_type,
                prompt,
                model.sell_price_sen,
                uploaded_url,
            )
            request_id = await self.fal.submit(model.fal_endpoint, arguments)
            await self.db.update_job(job_id, status="processing", fal_request_id=request_id)
        except Exception:
            await self.credit.refund(user_id, model.sell_price_sen, f"refund:{job_id}")
            raise

        task = asyncio.create_task(self._poll(job_id, model, deliver))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return await self.db.get_job(job_id)

    async def _poll(
        self, job_id: str, model: AIModel, deliver: DeliveryCallback
    ) -> None:
        job = await self.db.get_job(job_id)
        try:
            result = await self.fal.wait_for_result(
                model.fal_endpoint, str(job["fal_request_id"])
            )
            output_url = extract_output_url(result, model.job_type)
            if not output_url:
                raise RuntimeError(
                    f"fal.ai completed without a {model.job_type} URL: {json.dumps(result)[:500]}"
                )
            await self.db.update_job(
                job_id, status="completed", output_url=output_url, completed_at=utc_now()
            )
            await deliver(await self.db.get_job(job_id))
        except Exception:
            logger.exception("Generation failed for job %s", job_id)
            try:
                await self.db.update_job(job_id, status="failed", completed_at=utc_now())
                await self.credit.refund(
                    int(job["user_id"]), int(job["cost"]), f"refund:{job_id}"
                )
            except Exception:
                logger.exception("Could not refund failed job %s", job_id)
            await deliver(await self.db.get_job(job_id))
