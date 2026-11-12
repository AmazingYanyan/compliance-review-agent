"""材料分类（P3-6）：读取文件 OCR 块按窗口分组，LLM 分类为四类材料。

分类只判断材料类别（business_license / articles_of_association / audited_financials /
unknown），不推断企业是否合规。mixed 只在多窗口证据不一致时提出。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.core.db import engine
from app.llm_client import LLMClient
from app.llm_schemas import CLASSIFICATION_SCHEMA, ClassificationOutput
from app.models import OcrBlock

CLASSIFY_SYSTEM = (
    "你是银行信贷资料核对的材料分类助手。你只根据给定文本块判断该文件属于哪类材料，"
    "绝不推断企业是否合规、是否满足审计要求。类别只能是以下之一："
    "business_license（营业执照）、articles_of_association（公司章程）、"
    "audited_financials（最近一年已审计财报）、unknown（无法判断）。"
    "source_block_ids 引用支撑你判断的文本块 ID，必须来自给定块，不得凭空生成。"
)


@dataclass
class BlockRef:
    block_id: uuid.UUID
    text: str
    table_html: str | None = None


@dataclass
class Window:
    bundle_id: str
    blocks: list[BlockRef] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks)


def _window_text(blocks: list[BlockRef]) -> str:
    """把窗口内块组装成给模型的文本（带 block_id 标注）。"""
    parts: list[str] = []
    for b in blocks:
        text = b.text.strip()
        if not text and b.table_html:
            text = f"[表格]{b.table_html[:2000]}"
        if text:
            parts.append(f'block_id={b.block_id} 文本="{text}"')
    return "\n".join(parts)


def chunk_blocks(
    blocks: list[BlockRef],
    max_chars: int,
    overlap_chars: int,
) -> list[Window]:
    """按字符预算分窗，块边界对齐，窗口间重叠 overlap_chars 字符。"""
    windows: list[Window] = []
    current: list[BlockRef] = []
    current_chars = 0
    for block in blocks:
        text = block.text
        block_chars = len(text)
        if current and current_chars + block_chars > max_chars:
            windows.append(Window(bundle_id=f"window-{len(windows)}", blocks=list(current)))
            # 回退 overlap_chars 字符，作为新窗口起点（重叠）
            current, current_chars = _recede(current, overlap_chars)
        current.append(block)
        current_chars += block_chars
    if current:
        windows.append(Window(bundle_id=f"window-{len(windows)}", blocks=list(current)))
    return windows


def _recede(blocks: list[BlockRef], overlap_chars: int) -> tuple[list[BlockRef], int]:
    """从窗口末尾回退，保留覆盖 overlap_chars 字符的块。"""
    keep: list[BlockRef] = []
    chars = 0
    for block in reversed(blocks):
        keep.insert(0, block)
        chars += len(block.text)
        if chars >= overlap_chars:
            break
    return keep, chars


def load_file_blocks(task_id: uuid.UUID, file_id: uuid.UUID) -> list[BlockRef]:
    """读取文件的 OCR 文本块（按顺序），跳过无文本的纯图块。"""
    with Session(engine) as session:
        rows = session.exec(
            select(OcrBlock)
            .where(OcrBlock.task_id == task_id, OcrBlock.file_id == file_id)
            .order_by(OcrBlock.sequence_index)
        ).all()
        blocks: list[BlockRef] = []
        for row in rows:
            text = (row.canonical_text or "").strip()
            if not text and not row.table_html:
                continue  # 纯图块（印章/签名等）不参与文字分类
            blocks.append(BlockRef(block_id=row.id, text=text, table_html=row.table_html))
        return blocks


def _merge_results(results: list[ClassificationOutput]) -> ClassificationOutput:
    """合并多窗口分类结果：一致取该类别，不一致标 mixed。"""
    if not results:
        return ClassificationOutput(
            bundle_id="merged",
            material_type="unknown",
            mixed=False,
            confidence=0.0,
            reason="无可用文本块",
            source_block_ids=[],
        )
    if len(results) == 1:
        return results[0]
    types = {r.material_type for r in results if r.material_type != "unknown"}
    if len(types) == 1:
        merged_type = types.pop()
        confidence = min(r.confidence for r in results if r.material_type == merged_type)
        block_ids: list[str] = []
        for r in results:
            block_ids.extend(r.source_block_ids)
        return ClassificationOutput(
            bundle_id="merged",
            material_type=merged_type,
            mixed=False,
            confidence=confidence,
            reason="多窗口一致：" + results[0].reason,
            source_block_ids=list(dict.fromkeys(block_ids)),
        )
    # 窗口间不一致 → mixed（有证据）
    return ClassificationOutput(
        bundle_id="merged",
        material_type="unknown",
        mixed=True,
        confidence=0.0,
        reason="多窗口类别不一致：" + "、".join(sorted(types)),
        source_block_ids=[],
    )


def classify_file(
    task_id: uuid.UUID,
    file_id: uuid.UUID,
    client: LLMClient,
    max_chars: int,
    overlap_chars: int,
) -> ClassificationOutput:
    """对一个文件的 OCR 块做分类，返回合并结果。"""
    blocks = load_file_blocks(task_id, file_id)
    if not blocks:
        return ClassificationOutput(
            bundle_id="merged",
            material_type="unknown",
            mixed=False,
            confidence=0.0,
            reason="该文件无可用 OCR 文本块",
            source_block_ids=[],
        )
    windows = chunk_blocks(blocks, max_chars, overlap_chars)
    results: list[ClassificationOutput] = []
    for window in windows:
        user = "请判断下面文本属于哪类材料。\n" + _window_text(window.blocks)
        data = client.complete_json(
            system=CLASSIFY_SYSTEM,
            user=user,
            schema_name="classification_output",
            json_schema=CLASSIFICATION_SCHEMA,
            validator=ClassificationOutput.model_validate,
        )
        out = ClassificationOutput.model_validate(data)
        # 校验 source_block_ids 属于当前窗口
        valid_ids = {str(b.block_id) for b in window.blocks}
        out.source_block_ids = [bid for bid in out.source_block_ids if bid in valid_ids]
        results.append(out)
    return _merge_results(results)
