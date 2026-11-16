"""提示词版本注册（K6）。

集中管理提示词版本与模板常量，供 ``run.model_snapshot.run_config`` 冻结版本标识，
以及批量搜索 / 并发调度统一引用。

强监管约束（必须随模板一起下发）：系统只输出「证据 / 未找到」与覆盖状态，
不做合规判断；人工「接受」只是确认动作，不等于合规通过。

本批（T03）：搜索阶段切换到本模块的批量模板。``X=1`` 是「批大小为 1」的特例，
与 ``X>1`` 共用同一套 ``render_search_batch_user`` / ``SEARCH_BATCH_SYSTEM_TEMPLATE``，
不按 X 分支写两套提示词；``text_search.SEARCH_SYSTEM`` 与 ``SEARCH_USER_TEMPLATE``
仅保留给兼容 wrapper / 基线观测器，不再是运行时实际下发文本。
"""

from __future__ import annotations

# --- 版本标识（写入 run.model_snapshot.run_config） ---------------------------
SEARCH_PROMPT_VERSION = "text-search-batch-v2"
CLASSIFY_PROMPT_VERSION = "classify-v1"
VISION_PROMPT_VERSION = "vision-match-v1"

# --- 强监管约束 -------------------------------------------------------------
STRONG_REGULATORY_CONSTRAINT = (
    "强监管约束：你只输出「证据 / 未找到」以及识别覆盖状态，不做任何合规判断、"
    "不推断企业是否满足监管或审计要求；系统给出「接受」只是人工确认动作，"
    "不等于合规通过。找不到证据就如实输出未找到，严禁编造或补全原文。"
)

# --- 模板常量 ---------------------------------------------------------------
SEARCH_SYSTEM_TEMPLATE = (
    "你是银行信贷资料核对的证据摘录助手。你只根据给定文本块判断某个检查项能否在原文中"
    "找到对应证据。你绝不生成新的原文段落，只返回 source_refs 引用（block_id，以及可选的 "
    "start_char/end_char 表示引用范围）。找不到就 outcome=not_found。"
    "block_id 必须原样复制给定文本块里的 block_id 字符串（形如 8-4-4-4-12 的 UUID），"
    "严禁编造不存在的 block_id。\n"
    + STRONG_REGULATORY_CONSTRAINT
)

CLASSIFY_SYSTEM_TEMPLATE = (
    "你是银行信贷资料核对的材料分类助手。你只根据给定文本块判断该文件属于哪类材料，"
    "绝不推断企业是否合规、是否满足审计要求。类别只能是以下之一："
    "business_license（营业执照）、articles_of_association（公司章程）、"
    "audited_financials（最近一年已审计财报）、unknown（无法判断）。"
    "source_block_ids 引用支撑你判断的文本块 ID，必须来自给定块，不得凭空生成。\n"
    + STRONG_REGULATORY_CONSTRAINT
)

VISION_SYSTEM_TEMPLATE = (
    "你是银行信贷资料核对的印章/签名匹配助手。你只判断裁剪图是否为目标检查项要求的"
    "印章或签名，只返回 crop_id 引用与识别文字，不做任何合规判断。\n"
    + STRONG_REGULATORY_CONSTRAINT
)

# 兼容 wrapper / 基线观测器保留；运行时搜索阶段改用下面的批量模板。
SEARCH_USER_TEMPLATE = (
    "检查项：{label}（id={check_id}，结果模式={result_mode}）\n"
    "请判断该检查项能否在下面的文本块里找到对应证据，找到就返回引用。\n"
    "{window_text}"
)

# --- T03 批量搜索模板（X=1 与 X>1 共用，批大小 1 即单检查项） ----------------
SEARCH_BATCH_SYSTEM_TEMPLATE = (
    "你是银行信贷资料核对的证据摘录助手。你会收到一个 OCR 窗口文本和一组检查项。"
    "你只根据该窗口文本块逐个判断每个检查项能否找到对应证据；绝不生成新的原文段落，"
    "只返回 source_refs 引用（block_id，以及可选的 start_char/end_char）。"
    "对每个检查项，check_results 里必须有且仅有一项："
    "找到证据用 outcome=found 并给出引用，该窗口确无候选用 outcome=not_found 且 evidence 为空数组。"
    "block_id 必须原样复制给定文本块里的 block_id 字符串，严禁编造不存在的 block_id；"
    "严禁返回不在本批清单里的 check_item_id，也严禁漏返或重复返回检查项。\n"
    + STRONG_REGULATORY_CONSTRAINT
)


def render_search_batch_user(check_items: list[dict], window_text: str) -> str:
    """构造「窗口 × 检查项批次」的 user 提示词。

    每个检查项给出 ID / 名称 / 取证范围 / 误引边界；额外输出一组
    ``check_item_id=<id>`` 显式清单，供后端与模拟服务稳定识别本批检查项，
    也让「每个检查项恰好一项响应」的契约可被机器校验。窗口文本只附一次。
    """
    lines = [
        f"本批共 {len(check_items)} 个检查项。请对下面的 OCR 窗口文本逐个判断，"
        "并在 check_results 中按检查项分别返回：每个检查项恰好一项，"
        "不多、不少、不重复、不用其他 ID 顶替。"
    ]
    for leaf in check_items:
        check_id = leaf["id"]
        label = leaf.get("label", check_id)
        mode = leaf.get("result_mode", "verbatim_quotes")
        scope = leaf.get("evidence_scope") or "本窗口内与检查项直接对应的条款原文"
        boundary = (
            leaf.get("misquote_boundary")
            or "不得把相邻条款、其他字段或其他检查项的原文误引为该项证据"
        )
        lines.append(
            f"检查项：{label}（id={check_id}，结果模式={mode}，"
            f"取证范围={scope}，误引边界={boundary}）"
        )
    lines.append("本批检查项 id 清单（check_results 必须严格按此清单逐项返回）：")
    for leaf in check_items:
        lines.append(f"check_item_id={leaf['id']}")
    lines.append("下面是当前 OCR 窗口的文本块（block_id 必须来自这些块）：")
    lines.append(window_text)
    return "\n".join(lines)


CLASSIFY_USER_TEMPLATE = "请判断下面文本属于哪类材料。\n{window_text}"

# 三档 not_found_reason 的口径说明（供提示词与交接文档共用，非模型输出）
NOT_FOUND_REASON_POLICY: dict[str, str] = {
    "material_missing": "缺材料：该检查项无对应材料文件 / 无可查 OCR 文本块",
    "no_matching_evidence": "应查窗口全部 SUCCEEDED 且无候选证据",
    "coverage_incomplete": "存在未覆盖窗口；保留已成功摘录，覆盖状态为不完整",
}


def prompt_versions() -> dict[str, str]:
    """返回当前全部提示词版本，供 run_config 冻结。"""
    return {
        "search_prompt_version": SEARCH_PROMPT_VERSION,
        "classify_prompt_version": CLASSIFY_PROMPT_VERSION,
        "vision_prompt_version": VISION_PROMPT_VERSION,
    }
