"""Product-facing AI model catalog.

Prices are stored in sen. Provider prices can change, so verify the wholesale
costs and endpoint input schemas before enabling a model in production.

ratio_to_dimension_map converts the user-visible aspect ratio label (e.g. "16:9")
to the exact parameter dict that the fal.ai endpoint expects. Different endpoints
use different schemas (some take aspect_ratio string, some take width/height).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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
    # ── New fields ──────────────────────────────────────────────────────────────
    description: str = ""
    max_prompt_chars: int = 2500
    prompt_tips: tuple[str, ...] = ()
    supported_ratios: tuple[str, ...] = ("16:9", "9:16", "1:1")
    # Maps user-visible ratio label → fal.ai parameter dict merged into arguments
    ratio_to_dimension_map: dict[str, dict[str, Any]] = field(default_factory=dict)

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
        description=(
            "Google Veo 3.1 di server ini — 8s pada 720p dengan audio tersedia. "
            "Text-to-video generasi terkini daripada Google DeepMind."
        ),
        max_prompt_chars=2500,
        prompt_tips=(
            "Terangkan scene, subjek & pergerakan dengan terperinci",
            "Sebut pergerakan kamera (pan, zoom, close-up, tracking shot)",
            "Tetapkan mood (sinematik, mesra, dramatik, dokumentari)",
            "Tambah cue audio untuk bunyi yang segerak dengan visual",
        ),
        supported_ratios=("16:9", "9:16", "1:1"),
        ratio_to_dimension_map={
            "16:9": {"aspect_ratio": "16:9"},
            "9:16": {"aspect_ratio": "9:16"},
            "1:1":  {"aspect_ratio": "1:1"},
        },
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
        description=(
            "Kling 2.6 Standard Image-to-Video — 5s pada 720p. "
            "Hantar gambar dan biarkan AI animasikan ia dengan pergerakan natural."
        ),
        max_prompt_chars=2000,
        prompt_tips=(
            "Terangkan bagaimana gambar patut bergerak (perlahan, pantas, halus)",
            "Sebut elemen mana yang perlu bergerak (rambut, pakaian, awan, air)",
            "Tetapkan gaya — sinematik, slow-motion, dynamic",
            "Elak minta transformasi drastik yang terlalu jauh dari gambar asal",
        ),
        supported_ratios=("16:9", "9:16", "1:1"),
        ratio_to_dimension_map={
            "16:9": {"aspect_ratio": "16:9"},
            "9:16": {"aspect_ratio": "9:16"},
            "1:1":  {"aspect_ratio": "1:1"},
        },
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
        description=(
            "ByteDance Seedance Pro Image-to-Video — 5s pada 720p. "
            "Boleh guna gambar sebagai rujukan atau buat dari teks sahaja."
        ),
        max_prompt_chars=2000,
        prompt_tips=(
            "Gambar sebagai rujukan visual — prompt tetap penting untuk menentukan pergerakan",
            "Terangkan pergerakan yang diingini dengan jelas dan spesifik",
            "Sertakan jenis pencahayaan yang dikehendaki (natural, studio, dramatic)",
            "Guna /skip untuk skip gambar dan buat dari teks sahaja",
        ),
        supported_ratios=("16:9", "9:16", "1:1"),
        ratio_to_dimension_map={
            "16:9": {"aspect_ratio": "16:9"},
            "9:16": {"aspect_ratio": "9:16"},
            "1:1":  {"aspect_ratio": "1:1"},
        },
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
        description=(
            "FLUX Pro v1.1 — model text-to-image resolusi tinggi terbaik. "
            "Menghasilkan gambar fotorealistik, seni, ilustrasi dan konsep visual."
        ),
        max_prompt_chars=2000,
        prompt_tips=(
            "Terangkan subjek utama, latar belakang dan pencahayaan",
            "Sebut gaya (fotorealistik, lukisan minyak, ilustrasi digital, anime)",
            "Tambah perincian teknikal (DSLR, 4K, cinematic, bokeh)",
            "Elak percanggahan — pilih satu gaya dan kekalkan konsisten",
        ),
        supported_ratios=("1:1", "16:9", "9:16", "4:3", "3:4"),
        ratio_to_dimension_map={
            "1:1":  {"image_size": {"width": 1024, "height": 1024}},
            "16:9": {"image_size": {"width": 1360, "height": 768}},
            "9:16": {"image_size": {"width": 768,  "height": 1360}},
            "4:3":  {"image_size": {"width": 1024, "height": 768}},
            "3:4":  {"image_size": {"width": 768,  "height": 1024}},
        },
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
        description=(
            "Nano Banana — model kreatif untuk gambar dengan atau tanpa gambar rujukan. "
            "Sesuai untuk variasi, edit dan eksplorasi visual."
        ),
        max_prompt_chars=1500,
        prompt_tips=(
            "Gambar rujukan membantu hasilkan variasi yang lebih tepat",
            "Terangkan perubahan atau gaya yang dikehendaki secara jelas",
            "Sertakan warna utama dan suasana yang diingini",
            "Guna /skip untuk buat dari teks sahaja tanpa gambar",
        ),
        supported_ratios=("1:1", "16:9", "9:16"),
        ratio_to_dimension_map={
            "1:1":  {"image_size": {"width": 1024, "height": 1024}},
            "16:9": {"image_size": {"width": 1360, "height": 768}},
            "9:16": {"image_size": {"width": 768,  "height": 1360}},
        },
    ),
)

MODEL_BY_KEY = {model.key: model for model in MODELS}


def models_for(job_type: JobType) -> tuple[AIModel, ...]:
    return tuple(model for model in MODELS if model.job_type == job_type)
