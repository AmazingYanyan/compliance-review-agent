"""本地持久化文件存储。

文件按 UUID 路径保存，不信任用户提供的文件名。原文件、OCR JSONL、页面图、
裁剪图统一由本模块流式读写，业务行只保存 storage_key。
"""

from pathlib import Path

from app.core.config import settings

ROOT = Path(settings.DATA_DIR)


def resolve(key: str) -> Path:
    """把 storage_key 解析到磁盘路径，确保不越出 DATA_DIR。"""
    p = (ROOT / key).resolve()
    if not str(p).startswith(str(ROOT.resolve()) + "/"):
        raise ValueError(f"非法 storage_key: {key}")
    return p


def write_bytes(key: str, data: bytes) -> Path:
    p = resolve(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def read_bytes(key: str) -> bytes:
    return resolve(key).read_bytes()


def exists(key: str) -> bool:
    return resolve(key).exists()


def delete(key: str) -> None:
    p = resolve(key)
    if p.exists():
        p.unlink()
