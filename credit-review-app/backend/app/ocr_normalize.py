"""OCR 结果规范化：把 JSONL 解析为页面/块/裁剪图结构。

只做结构解析与字段映射，不写数据库（由流水线层负责）。
"""

import json

from bs4 import BeautifulSoup


def parse_jsonl(jsonl_bytes: bytes) -> list[dict]:
    """解析异步下载的 JSONL，返回 [{line_index, item_index, page}...]。

    每行形如 {"logId": ..., "result": {"layoutParsingResults": [page, ...]}}。
    """
    pages: list[dict] = []
    for line_no, line in enumerate(jsonl_bytes.decode("utf-8", errors="replace").split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = obj.get("result") or {}
        for item_idx, item in enumerate(result.get("layoutParsingResults") or []):
            pages.append({"line_index": line_no, "item_index": item_idx, "page": item})
    return pages


def _extract_text_and_images(block_content: str) -> tuple[str, list[str]]:
    soup = BeautifulSoup(block_content, "html.parser")
    imgs = [img.get("src", "") for img in soup.find_all("img")]
    text = soup.get_text("\n")
    return text.strip(), imgs


def _kind_from_label(label: str | None) -> str:
    if label == "seal":
        return "seal"
    if label == "signature":
        return "signature"
    if label == "image":
        return "image"
    return "unknown"


def parse_page(page: dict) -> tuple[dict, list[dict], list[dict]]:
    """解析一页，返回 (page_meta, blocks, crops)。"""
    pruned = page.get("prunedResult") or {}
    markdown = page.get("markdown") or {}
    images_map = markdown.get("images") or {}

    width = pruned.get("width")
    height = pruned.get("height")
    page_meta = {
        "width_px": width if isinstance(width, int) else None,
        "height_px": height if isinstance(height, int) else None,
        "coordinate_space": "ocr_input_image_pixels" if (width and height) else "unknown",
        "transform_metadata": pruned.get("doc_preprocessor_res"),
    }

    blocks: list[dict] = []
    crops: list[dict] = []
    parsing_list = pruned.get("parsing_res_list") or []
    for seq, b in enumerate(parsing_list):
        label = b.get("block_label")
        content = b.get("block_content") or ""
        text, img_srcs = _extract_text_and_images(content)
        is_table = label == "table" or "<table" in content.lower()
        block = {
            "provider_block_id": str(b.get("block_id")) if b.get("block_id") is not None else None,
            "group_id": str(b.get("group_id")) if b.get("group_id") is not None else None,
            "global_block_id": b.get("global_block_id"),
            "global_group_id": b.get("global_group_id"),
            "sequence_index": b.get("block_order") if b.get("block_order") is not None else seq,
            "label": label,
            "canonical_text": text,
            "table_html": content if is_table else None,
            "bbox": b.get("block_bbox"),
            "polygon": b.get("block_polygon_points"),
        }
        blocks.append(block)
        # 每个 img src 建立一个独立 crop，保留与块的关联
        for src in img_srcs:
            crops.append({
                "provider_label": label,
                "kind": _kind_from_label(label),
                "img_src": src,
                "image_url": images_map.get(src),
                "recognized_text": text or None,  # 印章文字来自块内可见文字
                "bbox": b.get("block_bbox"),
                "polygon": b.get("block_polygon_points"),
            })
    return page_meta, blocks, crops
