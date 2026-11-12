"""印章/签名视觉匹配（P3-8）：先文字匹配，不足再视觉模型多图分批。

- 文字匹配：用 OCR 裁剪图的 recognized_text 与依赖目标（如审计机构名）匹配，
  足以对应时直接采用，不对本项再调视觉模型
- 视觉兜底：候选裁剪图分批（每批 VISION_IMAGES_PER_BATCH 张）给视觉模型，
  每张带稳定 crop_id 防按图序认错；应用从本地工件取图
"""

from __future__ import annotations

import base64
import io
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.llm_client import LLMClient
from app.llm_schemas import VISION_MATCH_SCHEMA, VisionMatchOutput
from app.models import Asset, Crop
from app.storage import read_bytes

VISION_SYSTEM = (
    "你是银行信贷资料核对的印章/签名识别助手。根据给定裁剪图判断是否为检查项所要求的"
    "印章或签名。你只返回被选中的 crop_id、可可靠辨认的文字及对应关系，不判断真伪，"
    "不生成不可靠的机构名或姓名。无法可靠辨认时返回空 matches。"
)


@dataclass
class CropEvidence:
    crop_id: uuid.UUID
    file_id: uuid.UUID | None
    page_id: uuid.UUID | None
    block_id: uuid.UUID | None
    text: str | None
    relation_status: str
    recognition_source: str  # ocr / vision
    bbox: Any | None
    polygon: Any | None


def _normalize(text: str | None) -> str:
    """机构名规范化：去空白与常见排版差异（保留原文，不强行等同相近机构）。"""
    if not text:
        return ""
    return re.sub(r"\s+", "", text)


def load_crops(
    session: Session, task_id: uuid.UUID, file_ids: list[uuid.UUID]
) -> list[Crop]:
    if not file_ids:
        return []
    return session.exec(
        select(Crop).where(
            Crop.task_id == task_id,
            Crop.file_id.in_(file_ids),  # type: ignore[attr-defined]
        )
    ).all()


def match_by_text(crops: list[Crop], target_text: str | None) -> list[CropEvidence]:
    """用裁剪图已识别文字匹配目标机构名。"""
    if not target_text:
        return []
    target_norm = _normalize(target_text)
    if not target_norm:
        return []
    evidence: list[CropEvidence] = []
    for crop in crops:
        if not crop.recognized_text:
            continue
        if target_norm in _normalize(crop.recognized_text):
            evidence.append(
                CropEvidence(
                    crop_id=crop.id,
                    file_id=crop.file_id,
                    page_id=crop.page_id,
                    block_id=crop.block_id,
                    text=crop.recognized_text,
                    relation_status="matched",
                    recognition_source="ocr",
                    bbox=crop.bbox,
                    polygon=crop.polygon,
                )
            )
    return evidence


def _crop_image_base64(crop: Crop, max_edge: int) -> str | None:
    """读取裁剪图，缩放到长边 max_edge 后返回 base64 data URL。"""
    if not crop.image_asset_id or crop.image_status != "downloaded":
        return None
    with Session(engine) as session:
        asset = session.get(Asset, crop.image_asset_id)
        storage_key = asset.storage_key if asset else None
    if not storage_key:
        return None
    try:
        raw = read_bytes(storage_key)
    except Exception:  # noqa: BLE001
        return None
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        img.thumbnail((max_edge, max_edge))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:  # noqa: BLE001
        return None


def match_by_vision(
    crops: list[Crop],
    check_item: dict[str, Any],
    client: LLMClient,
    batch_size: int,
    max_edge: int,
) -> list[CropEvidence]:
    """视觉模型多图分批识别印章/签名。"""
    check_id = check_item["id"]
    label = check_item.get("label", check_id)
    evidence: list[CropEvidence] = []

    # 只取有图且已下载的裁剪图
    usable = [c for c in crops if c.image_asset_id and c.image_status == "downloaded"]
    if not usable:
        return evidence

    for start in range(0, len(usable), batch_size):
        batch = usable[start : start + batch_size]
        images: list[str] = []
        labels: list[str] = []
        for crop in batch:
            b64 = _crop_image_base64(crop, max_edge)
            if b64 is None:
                continue
            images.append(b64)
            labels.append(f"图{len(images)} = crop_id={crop.id}")

        if not images:
            continue

        user = (
            f"检查项：{label}（id={check_id}）\n"
            "下面每张裁剪图按顺序对应一个 crop_id：\n"
            + "\n".join(labels)
            + "\n请判断哪些裁剪图是该项要求的印章或签名，返回 matches。"
        )
        try:
            data = client.complete_json(
                system=VISION_SYSTEM,
                user=user,
                schema_name="vision_match_output",
                json_schema=VISION_MATCH_SCHEMA,
                validator=VisionMatchOutput.model_validate,
                images=images,
                model=settings.LLM_VISION_MODEL,
            )
            output = VisionMatchOutput.model_validate(data)
        except Exception:  # noqa: BLE001
            # 视觉识别失败不阻止其他项，本批跳过
            continue

        crop_by_id = {str(c.id): c for c in batch}
        for match in output.matches:
            crop = crop_by_id.get(match.crop_id)
            if crop is None:
                continue
            evidence.append(
                CropEvidence(
                    crop_id=crop.id,
                    file_id=crop.file_id,
                    page_id=crop.page_id,
                    block_id=crop.block_id,
                    text=match.recognized_text or crop.recognized_text,
                    relation_status=match.relation_status,
                    recognition_source="vision",
                    bbox=crop.bbox,
                    polygon=crop.polygon,
                )
            )
    return evidence
