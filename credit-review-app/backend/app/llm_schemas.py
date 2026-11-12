"""LLM 结构化输出契约（Pydantic 模型 + response_format 用的 JSON Schema）。

三个输出结构对齐 contracts/ 下的 classification/text_search/vision_match 三个
output.schema.json。JSON Schema 用于传给模型做结构化输出（response_format），
Pydantic 模型用于结果严格校验（引用集合、字符范围、类别、任务归属与覆盖）。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

MATERIAL_TYPES = {
    "business_license",
    "articles_of_association",
    "audited_financials",
    "unknown",
}

RELATION_STATUSES = {"matched", "needs_review"}
OUTCOMES = {"found", "not_found"}


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 材料分类
# ---------------------------------------------------------------------------


class ClassificationOutput(BaseModel):
    bundle_id: str
    material_type: str
    mixed: bool
    confidence: float
    reason: str = Field(max_length=1000)
    source_block_ids: list[str] = Field(default_factory=list)

    @field_validator("material_type")
    @classmethod
    def _check_material_type(cls, v: str) -> str:
        if v not in MATERIAL_TYPES:
            raise ValueError(f"非法 material_type: {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence 越界: {v}")
        return v

    @field_validator("source_block_ids")
    @classmethod
    def _check_block_ids(cls, v: list[str]) -> list[str]:
        for bid in v:
            if not _is_uuid(bid):
                raise ValueError(f"非法 block_id: {bid}")
        return v


# ---------------------------------------------------------------------------
# 文本/表格查找
# ---------------------------------------------------------------------------


class SourceRef(BaseModel):
    block_id: str
    start_char: int | None = None
    end_char: int | None = None

    @field_validator("block_id")
    @classmethod
    def _check_block_id(cls, v: str) -> str:
        if not _is_uuid(v):
            raise ValueError(f"非法 block_id: {v}")
        return v

    @field_validator("start_char", "end_char")
    @classmethod
    def _check_char(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError(f"字符偏移为负: {v}")
        return v


class TextEvidence(BaseModel):
    source_refs: list[SourceRef] = Field(min_length=1)
    relation_status: str
    relevance_reason: str = Field(max_length=1000)

    @field_validator("relation_status")
    @classmethod
    def _check_relation(cls, v: str) -> str:
        if v not in RELATION_STATUSES:
            raise ValueError(f"非法 relation_status: {v}")
        return v


class CheckSearch(BaseModel):
    check_item_id: str
    outcome: str
    evidence: list[TextEvidence] = Field(default_factory=list)

    @field_validator("outcome")
    @classmethod
    def _check_outcome(cls, v: str) -> str:
        if v not in OUTCOMES:
            raise ValueError(f"非法 outcome: {v}")
        return v


class TextSearchOutput(BaseModel):
    bundle_id: str
    check_results: list[CheckSearch]


# ---------------------------------------------------------------------------
# 视觉匹配（印章/签名）
# ---------------------------------------------------------------------------


class ImageMatch(BaseModel):
    crop_id: str
    recognized_text: str | None = None
    relation_status: str
    relevance_reason: str = Field(max_length=1000)

    @field_validator("crop_id")
    @classmethod
    def _check_crop_id(cls, v: str) -> str:
        if not _is_uuid(v):
            raise ValueError(f"非法 crop_id: {v}")
        return v

    @field_validator("relation_status")
    @classmethod
    def _check_relation(cls, v: str) -> str:
        if v not in RELATION_STATUSES:
            raise ValueError(f"非法 relation_status: {v}")
        return v


class VisionMatchOutput(BaseModel):
    bundle_id: str
    check_item_id: str
    matches: list[ImageMatch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# response_format 用的 JSON Schema（去 format，保证严格模式兼容）
# ---------------------------------------------------------------------------


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _uuid_prop() -> dict[str, Any]:
    return {"type": "string"}


def _string_prop(max_length: int | None = None) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "string"}
    if max_length:
        prop["maxLength"] = max_length
    return prop


def _enum_prop(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


def _nullable_int_prop() -> dict[str, Any]:
    return {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]}


CLASSIFICATION_SCHEMA = _schema(
    {
        "bundle_id": _string_prop(),
        "material_type": _enum_prop(sorted(MATERIAL_TYPES)),
        "mixed": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": _string_prop(1000),
        "source_block_ids": {"type": "array", "items": _uuid_prop()},
    },
    ["bundle_id", "material_type", "mixed", "confidence", "reason", "source_block_ids"],
)

TEXT_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "bundle_id": _string_prop(),
        "check_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check_item_id": _string_prop(),
                    "outcome": _enum_prop(["found", "not_found"]),
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_refs": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "block_id": _uuid_prop(),
                                            "start_char": _nullable_int_prop(),
                                            "end_char": _nullable_int_prop(),
                                        },
                                        "required": ["block_id", "start_char", "end_char"],
                                        "additionalProperties": False,
                                    },
                                },
                                "relation_status": _enum_prop(["matched", "needs_review"]),
                                "relevance_reason": _string_prop(1000),
                            },
                            "required": ["source_refs", "relation_status", "relevance_reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["check_item_id", "outcome", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["bundle_id", "check_results"],
    "additionalProperties": False,
}

VISION_MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "bundle_id": _string_prop(),
        "check_item_id": _string_prop(),
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "crop_id": _uuid_prop(),
                    "recognized_text": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "relation_status": _enum_prop(["matched", "needs_review"]),
                    "relevance_reason": _string_prop(1000),
                },
                "required": ["crop_id", "recognized_text", "relation_status", "relevance_reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["bundle_id", "check_item_id", "matches"],
    "additionalProperties": False,
}
