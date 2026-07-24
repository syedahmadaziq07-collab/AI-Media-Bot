"""Product-facing AI model catalog.

Prices are stored in sen. Provider prices can change, so verify the wholesale
costs and endpoint input schemas before enabling a model in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

InputType = Literal["text_only", "image_required", "image_optional"]
JobType = Literal["video", "image"]


@dataclass(frozen=True)
class AIModel:
    key: str
    display_name: str
    fal_endpoint: str
    job_type: JobType
    input_type: InputType
    duration_seconds: int | None
    resolution: str
    has_audio: bool
    wholesale_cost_sen: int
    sell_price_sen: int
    server_group: str

    @property
    def price_label(self) -> str:
        return f"RM {self.sell_price_sen / 100:.2f}"

    @property
    def spec_label(self) -> str:
        duration = f"{self.duration_seconds}s" if self.duration_seconds else ""
        audio = " + audio" if self.has_audio else ""
        return " · ".join(part for part in (duration, self.resolution, audio.strip()) if part)


MODELS: tuple[AIModel, ...] = (
    AIModel(
        key="veo3_text",
        display_name="Veo 3.1 Text-to-Video",
        fal_endpoint="fal-ai/veo3.1",
        job_type="video",
        input_type="text_only",
        duration_seconds=8,
        resolution="720p",
        has_audio=True,
        wholesale_cost_sen=650,
        sell_price_sen=1200,
        server_group="Server #1",
    ),
    AIModel(
        key="kling_i2v",
        display_name="Kling 2.6 Image-to-Video",
        fal_endpoint="fal-ai/kling-video/v2.6/standard/image-to-video",
        job_type="video",
        input_type="image_required",
        duration_seconds=5,
        resolution="720p",
        has_audio=False,
        wholesale_cost_sen=420,
        sell_price_sen=850,
        server_group="Server #2",
    ),
    AIModel(
        key="seedance_i2v",
        display_name="Seedance Image-to-Video",
        fal_endpoint="fal-ai/bytedance/seedance/v1/pro/image-to-video",
        job_type="video",
        input_type="image_optional",
        duration_seconds=5,
        resolution="720p",
        has_audio=False,
        wholesale_cost_sen=350,
        sell_price_sen=750,
        server_group="Server #2",
    ),
    AIModel(
        key="flux_image",
        display_name="FLUX Pro Image",
        fal_endpoint="fal-ai/flux-pro/v1.1",
        job_type="image",
        input_type="text_only",
        duration_seconds=None,
        resolution="1024px",
        has_audio=False,
        wholesale_cost_sen=90,
        sell_price_sen=250,
        server_group="Server #3",
    ),
    AIModel(
        key="nano_banana",
        display_name="Nano Banana Image",
        fal_endpoint="fal-ai/nano-banana",
        job_type="image",
        input_type="image_optional",
        duration_seconds=None,
        resolution="1024px",
        has_audio=False,
        wholesale_cost_sen=120,
        sell_price_sen=300,
        server_group="Server #3",
    ),
)

MODEL_BY_KEY = {model.key: model for model in MODELS}


def models_for(job_type: JobType) -> tuple[AIModel, ...]:
    return tuple(model for model in MODELS if model.job_type == job_type)