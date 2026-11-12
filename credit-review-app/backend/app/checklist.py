"""检查清单装载与校验。

清单存于版本化配置文件（backend/app/data/），processing_run 保存完整快照。
本模块只负责只读装载、展平叶子与内容 hash，不负责生成结果。
"""

import hashlib
import json
from pathlib import Path
from typing import Any

CHECKLIST_DIR = Path(__file__).parent / "data"

# 版本 → 文件名映射（冻结版本）
_CHECKLIST_FILES: dict[str, str] = {
    "borrower-wcl-v1": "checklist_borrower_wcl_v1.json",
}

_cache: dict[str, dict[str, Any]] = {}


def _load(version: str) -> dict[str, Any]:
    if version in _cache:
        return _cache[version]
    filename = _CHECKLIST_FILES.get(version)
    if not filename:
        raise ValueError(f"未知清单版本: {version}")
    path = CHECKLIST_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != version:
        raise ValueError(f"清单版本不匹配: {data.get('version')} != {version}")
    if not data.get("enabled", False):
        raise ValueError(f"清单已禁用: {version}")
    _cache[version] = data
    return data


def get_checklist(version: str = "borrower-wcl-v1") -> dict[str, Any]:
    """返回完整清单（含 3 类材料、18 叶子）。"""
    return _load(version)


def get_leaves(version: str = "borrower-wcl-v1") -> list[dict[str, Any]]:
    """展平返回全部检查叶子项，附带所属材料类型与标签。"""
    data = _load(version)
    leaves: list[dict[str, Any]] = []
    for material in data["materials"]:
        for check in material["checks"]:
            leaves.append(
                {
                    **check,
                    "material_type": material["material_type"],
                    "material_label": material["label"],
                }
            )
    return leaves


def get_check_item_ids(version: str = "borrower-wcl-v1") -> set[str]:
    return {leaf["id"] for leaf in get_leaves(version)}


def leaf_count(version: str = "borrower-wcl-v1") -> int:
    return len(get_leaves(version))


def checklist_hash(version: str = "borrower-wcl-v1") -> str:
    """清单内容的稳定 hash，用于 run 快照冻结。"""
    data = _load(version)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
