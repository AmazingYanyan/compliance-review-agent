"""处理管线（P3）：材料分类 → 文本/表格查找 → 印章/签名匹配。

单一 Procrastinate 任务 processing.run 串行执行三个阶段，结果写入 results +
result_sources。每个阶段失败记录 error_code 并标记 run FAILED（可重试）。

本批（T03）改动：
* ``_search_stage`` 由「for leaf 串行调 search_check_item」改为「窗口 × 检查项批次」
  独立单元 + ``ThreadPoolExecutor(max_workers=LLM_MAX_IN_FLIGHT)`` 一次提交全部、
  ``as_completed`` 先回先收；模型线程只调用不写 DB，收集端用短事务归并落库。
* ``X=checks_per_request`` 按稳定清单顺序分组，X=1 视为批大小 1 的特例，
  与并发调度共用同一执行器；批量响应走 ``validate_batch_response`` 校验。
* 逐请求 JSONL 落 ``/data/perf_traces/{run_id}.jsonl``（t_submit / t_http_start），
  单元观测步 ``step_key=u:w{wi}:b{bi}``，七类批内短码写 ``last_error_code``。
* ``compute_coverage_summary``：coverage_affected_check_ids 纯读
  ``Result.not_found_reason``（不依赖 step_key 前缀）；无任何单元步时保守 False
  + 记错误码，不回退持久化值（F3/F4）。``_complete_run`` 仍是唯一写库事实源。

历史（T02）：覆盖状态事实源、三档 not_found_reason、LLM_FATAL 改 raise、
``model_snapshot.run_config`` 冻结 X / C / 分窗策略 / 版本 / 清单 hash。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.classification import classify_file
from app.core.config import settings
from app.core.db import engine
from app.llm_client import (
    LLMFatalError,
    LLMFormatError,
    LLMTransientError,
    RequestTrace,
    _ACTIVE_TAG,
    get_llm_client,
)
from app.llm_schemas import TEXT_SEARCH_SCHEMA, TextSearchOutput
from app.models import (
    ProcessingRun,
    Result,
    ResultSource,
    RunFile,
    RunState,
    RunStep,
    StepState,
    Task,
    TaskState,
)
from app.prompt_registry import (
    SEARCH_BATCH_SYSTEM_TEMPLATE,
    SEARCH_PROMPT_VERSION,
    prompt_versions,
    render_search_batch_user,
)
from app.queue import app
from app.text_search import (
    BatchCheckResult,
    BatchValidation,
    FoundEvidence,
    Window,
    _dedup_evidence,
    _window_text,
    chunk_source_blocks,
    load_source_blocks,
    search_check_item,  # 兼容 wrapper：保留为模块属性，供基线观测器 / 单测引用
    validate_batch_response,
)
from app.vision_match import CropEvidence, load_crops, match_by_text, match_by_vision


def _leaves_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    for material in snapshot.get("materials", []):
        for check in material.get("checks", []):
            leaves.append({**check, "material_type": material["material_type"]})
    return leaves


# ---------------------------------------------------------------------------
# 运行配置（写进 run.model_snapshot，JSONB 必须整体重新赋值）
# ---------------------------------------------------------------------------


def build_run_config(checklist_hash_value: str | None = None) -> dict[str, Any]:
    """构造静态 run_config：X / C / 分窗策略 / 批次状态 / 版本 / 清单 hash。"""
    return {
        "checks_per_request": settings.CHECKS_PER_REQUEST,  # X
        "llm_max_in_flight": settings.LLM_MAX_IN_FLIGHT,  # C：唯一在途上限
        "llm_max_concurrency_compat_alias": settings.LLM_MAX_CONCURRENCY,
        "pipeline_config_version": settings.PIPELINE_CONFIG_VERSION,
        **prompt_versions(),
        "window_strategy": {
            "max_chars": settings.LLM_WINDOW_CHARACTERS,
            "overlap_chars": settings.LLM_WINDOW_OVERLAP_CHARACTERS,
            "stable_sort_key": "(file_order, page_key, page_ordinal)",
            "bundle_id": "w{idx}",
            "content_hash": "sha256(file_key|page_key|page_ordinal|canonical_text)[:64]",
        },
        "batch": {
            "checks_per_request": settings.CHECKS_PER_REQUEST,
            # 固定文案（不随 X 变）：保证两次运行 run_config 静态部分除 X 外全等（QA B4）
            "status": "已启用：窗口×检查项批次并发调度（X=1 视为批大小 1）",
            # 实际批次清单 / 单元总数由 _search_stage 按分类后的 material+窗口补写
            "batches": [],
            "units_total": None,
        },
        "run_mode": "full_rerun",
        "run_mode_note": "补跑如实标注整次重跑（每次新建 run_id，跨 run 幂等键不成立）",
        "checklist_hash": checklist_hash_value,
        "text_model": settings.LLM_TEXT_MODEL,
        "vision_model": settings.LLM_VISION_MODEL,
    }


def _write_run_config(session: Session, run_id: uuid.UUID, patch: dict[str, Any]) -> None:
    """把运行配置合并进 ``run.model_snapshot['run_config']``。

    SQLModel 对 mutable JSONB dict 的原地修改不会触发 UPDATE，必须整体重新赋值。
    """
    run = session.get(ProcessingRun, run_id)
    if not run:
        return
    snapshot: dict[str, Any] = dict(run.model_snapshot or {})
    config: dict[str, Any] = dict(snapshot.get("run_config") or {})
    config.update(patch)
    snapshot["run_config"] = config
    run.model_snapshot = snapshot
    session.add(run)
    session.commit()


# ---------------------------------------------------------------------------
# 覆盖汇总（事实源：RunStep + Result.not_found_reason）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageSummary:
    """一次 run 的覆盖状态汇总（``_complete_run`` 的唯一写库事实源）。"""

    coverage_complete: bool
    coverage_affected_check_ids: list[str]
    check_count: int
    covered_check_count: int
    legacy_without_steps: bool = False
    reason: str = ""
    error_code: str | None = None


def compute_coverage_summary(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    snapshot: dict[str, Any],
) -> CoverageSummary:
    """按检查项聚合覆盖事实。

    * **F4/G3**：``coverage_affected_check_ids`` 直接读
      ``Result.not_found_reason == "coverage_incomplete"``（本查询已取出 results，
      零额外查询），彻底不依赖 ``step_key.startswith("check:")``；新引入的
      ``u:w{wi}:b{bi}`` 窗口/批次 step_key 不影响展示。
    * **F3**：本次 run 无任何单元步时保守 ``coverage_complete=False`` + 记错误码，
      **不再**回退持久化 ``run.coverage_complete`` —— worker ``_complete_run`` 读的
      正是本函数要写的字段，回退会形成循环依赖。历史 run 不回填、不加迁移。
    * ``PARTIAL_COVERAGE`` 是检查项级 ``failed_reason``，不是短码，不进任何
      ``last_error_code``；``complete_task`` 收敛后只信 ``run.coverage_complete``。
    """
    leaves = _leaves_from_snapshot(snapshot)
    # 印章/签名走视觉匹配，没有「应查窗口」，不纳入窗口覆盖判定
    window_check_ids = [
        leaf["id"]
        for leaf in leaves
        if leaf.get("result_mode") not in ("seal", "signature")
    ]
    results = session.exec(
        select(Result).where(Result.run_id == run_id, Result.task_id == task_id)
    ).all()
    affected: set[str] = {
        row.check_item_id
        for row in results
        if row.not_found_reason == "coverage_incomplete"
    }
    result_check_ids = {row.check_item_id for row in results}
    steps = session.exec(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.task_id == task_id)
    ).all()
    # 单元步：新的 u: 窗口批次步或旧的 check: 检查项步，二者都代表搜索已产生覆盖记录。
    unit_steps = [
        step
        for step in steps
        if step.step_key.startswith("u:") or step.step_key.startswith("check:")
    ]

    if not window_check_ids:
        return CoverageSummary(
            coverage_complete=bool(unit_steps),
            coverage_affected_check_ids=sorted(affected),
            check_count=0,
            covered_check_count=0,
            reason="无文本检查项（仅视觉匹配）",
        )

    if not unit_steps:
        return CoverageSummary(
            coverage_complete=False,
            coverage_affected_check_ids=sorted(set(window_check_ids) | affected),
            check_count=len(window_check_ids),
            covered_check_count=0,
            legacy_without_steps=True,
            reason="本次 run 无任何单元步，保守判定覆盖不完整（不回退持久化值）",
            error_code="COVERAGE_NO_UNIT_STEPS",
        )

    # 每个文本检查项：有结果行（候选 / 未找到 / 缺材料 / 覆盖不全）且不在 affected
    # 才算覆盖达成；缺结果行 = 未处理 = 未覆盖。判定与到达顺序、step_key 前缀无关。
    covered_ids = [
        cid
        for cid in window_check_ids
        if cid in result_check_ids and cid not in affected
    ]
    covered_set = set(covered_ids)
    incomplete = [cid for cid in window_check_ids if cid not in covered_set]
    complete = bool(window_check_ids) and not incomplete
    return CoverageSummary(
        coverage_complete=complete,
        coverage_affected_check_ids=sorted(set(incomplete) | affected),
        check_count=len(window_check_ids),
        covered_check_count=len(covered_ids),
        reason=(
            ""
            if complete
            else "存在未覆盖检查项：无结果行或 "
            "Result.not_found_reason=coverage_incomplete"
        ),
    )


# ---------------------------------------------------------------------------
# 耗时观测（Step 1）：RunStep 记录阶段/检查项/窗口的起止与状态
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _step_key_hash(step_key: str, extra: str = "") -> str:
    """input_hash 用 step_key + extra 的稳定短哈希，保证 (run_id, step_key, input_hash) 唯一。"""
    return hashlib.sha256(f"{step_key}|{extra}".encode("utf-8")).hexdigest()[:64]


def _stable_leaf_hash(leaf: dict[str, Any]) -> str:
    """检查项叶子的稳定内容 hash（无 UUID），用作 RunStep.input_hash_extra。"""
    payload = json.dumps(leaf, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:64]


def _record_step(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    step_key: str,
    input_hash: str,
    *,
    state: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    file_id: uuid.UUID | None = None,
    last_error_code: str | None = None,
    attempt: int = 0,
) -> None:
    """写/更新一条 RunStep（按 run_id+step_key+input_hash upsert）。"""
    existing = session.exec(
        select(RunStep).where(
            RunStep.run_id == run_id,
            RunStep.step_key == step_key,
            RunStep.input_hash == input_hash,
        )
    ).first()
    if existing:
        existing.state = state
        existing.started_at = started_at or existing.started_at
        existing.finished_at = finished_at or existing.finished_at
        existing.last_error_code = last_error_code
        existing.attempt = attempt
        session.add(existing)
    else:
        session.add(
            RunStep(
                task_id=task_id,
                run_id=run_id,
                file_id=file_id,
                step_key=step_key,
                input_hash=input_hash,
                state=state,
                attempt=attempt,
                last_error_code=last_error_code,
                started_at=started_at,
                finished_at=finished_at,
            )
        )


def _touch_step(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    step_key: str,
    state: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    last_error_code: str | None = None,
    input_hash_extra: str = "",
) -> None:
    """在独立 Session 里写/更新一条 RunStep（阶段/检查项级观测）。

    ``input_hash_extra`` 用稳定内容 hash（不含 UUID），为将来跨批次幂等键铺路。
    """
    input_hash = _step_key_hash(step_key, input_hash_extra)
    with Session(engine) as session:
        _record_step(
            session,
            task_id,
            run_id,
            step_key,
            input_hash,
            state=state,
            started_at=started_at,
            finished_at=finished_at,
            last_error_code=last_error_code,
        )
        session.commit()


# ---------------------------------------------------------------------------
# 结果写入
# ---------------------------------------------------------------------------


def _write_text_result(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_item: dict[str, Any],
    evidence: FoundEvidence,
    rank: int,
) -> None:
    result = Result(
        task_id=task_id,
        run_id=run_id,
        check_item_id=check_item["id"],
        kind=evidence.kind,
        text=evidence.text,
        table_html=evidence.table_html,
        relation_status=evidence.relation_status,
        rank=rank,
        fingerprint=evidence.fingerprint,  # 语义本轮改为 K2 内容 hash
    )
    session.add(result)
    session.flush()
    src = evidence.source
    session.add(
        ResultSource(
            task_id=task_id,
            result_id=result.id,
            file_id=src.file_id,
            page_id=src.page_id,
            block_id=src.block_id,
            start_char=evidence.start_char,
            end_char=evidence.end_char,
            source_page_number=src.source_page_number,
            bbox=src.bbox,
            polygon=src.polygon,
            location_precision=_location_precision(src),
        )
    )


def _location_precision(src: Any) -> str:
    if src.bbox or src.polygon:
        return "region"
    if src.page_id:
        return "page"
    return "none"


def _write_crop_result(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_item: dict[str, Any],
    evidence: CropEvidence,
    rank: int,
) -> None:
    kind = "seal" if check_item.get("result_mode") == "seal" else "signature"
    result = Result(
        task_id=task_id,
        run_id=run_id,
        check_item_id=check_item["id"],
        kind=kind,
        text=evidence.text,
        crop_id=evidence.crop_id,
        recognition_source=evidence.recognition_source,
        relation_status=evidence.relation_status,
        rank=rank,
    )
    session.add(result)
    session.flush()
    if evidence.file_id:
        session.add(
            ResultSource(
                task_id=task_id,
                result_id=result.id,
                file_id=evidence.file_id,
                page_id=evidence.page_id,
                block_id=evidence.block_id,
                bbox=evidence.bbox,
                polygon=evidence.polygon,
                location_precision="region" if (evidence.bbox or evidence.polygon) else "page",
            )
        )


def _write_not_found(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_item: dict[str, Any],
    reason: str,
) -> None:
    session.add(
        Result(
            task_id=task_id,
            run_id=run_id,
            check_item_id=check_item["id"],
            kind="not_found",
            not_found_reason=reason,
            rank=0,
        )
    )


# ---------------------------------------------------------------------------
# 阶段
# ---------------------------------------------------------------------------


def _classify_stage(task_id: uuid.UUID, run_id: uuid.UUID, client: Any) -> None:
    with Session(engine) as session:
        run_files = session.exec(
            select(RunFile).where(RunFile.run_id == run_id, RunFile.task_id == task_id)
        ).all()
        file_ids = [rf.file_id for rf in run_files]

    for file_id in file_ids:
        with Session(engine) as session:
            result = classify_file(
                task_id=task_id,
                file_id=file_id,
                client=client,
                max_chars=settings.LLM_WINDOW_CHARACTERS,
                overlap_chars=settings.LLM_WINDOW_OVERLAP_CHARACTERS,
            )
            rf = session.exec(
                select(RunFile).where(
                    RunFile.run_id == run_id,
                    RunFile.task_id == task_id,
                    RunFile.file_id == file_id,
                )
            ).first()
            if rf:
                rf.effective_material_type = (
                    None if result.material_type == "unknown" or result.mixed else result.material_type
                )
                rf.classification_source = "llm"
                rf.classification_reason = result.reason
                session.add(rf)
                session.commit()


# ---------------------------------------------------------------------------
# T03 并发调度：窗口 × 检查项批次 单元；模型线程只调用，收集端短事务归并
# ---------------------------------------------------------------------------


@dataclass
class SearchUnit:
    """一个「窗口 × 检查项批次」独立调用单元。"""

    run_id: uuid.UUID
    task_id: uuid.UUID
    request_id: str
    window: Window
    window_id: str
    window_index: int
    batch_index: int
    check_items: list[dict[str, Any]]
    t_submit: float = 0.0


@dataclass
class UnitCall:
    """模型线程执行结果（不含任何 DB 写入）。"""

    ok: bool = False
    data: dict[str, Any] | None = None
    traces: list[RequestTrace] = field(default_factory=list)
    finish_reason: str | None = None
    attempt: int = 0
    state: str = "ok"  # ok / timeout / format_failed / truncated / fatal
    error_code: str | None = None  # 短码（≤64），收集端再与批内短码合并


@dataclass
class CheckAgg:
    """收集端对单个检查项跨窗口的聚合（与到达顺序无关）。"""

    leaf: dict[str, Any]
    total_windows: int
    done_windows: int = 0
    failed: bool = False
    fatal: bool = False
    evidence: dict[str, FoundEvidence] = field(default_factory=dict)
    anomalies: set[str] = field(default_factory=set)
    flushed: bool = False


def _render_unit_user(unit: SearchUnit) -> str:
    return render_search_batch_user(unit.check_items, _window_text(unit.window.blocks))


def _execute_unit_inner(unit: SearchUnit, client: Any, user: str) -> UnitCall:
    """模型线程：只调用 LLM，不写 DB。重试计入同一在途额度（线程数 = C）。"""
    traces: list[RequestTrace] = []
    for attempt in range(settings.LLM_MAX_TRANSIENT_RETRIES + 1):
        trace = RequestTrace()
        trace.t_submit = unit.t_submit
        trace.window_text_sha256 = unit.window.window_text_sha256
        try:
            data = client.complete_json(
                system=SEARCH_BATCH_SYSTEM_TEMPLATE,
                user=user,
                schema_name="text_search_output",
                json_schema=TEXT_SEARCH_SCHEMA,
                validator=TextSearchOutput.model_validate,
                trace=trace,
            )
            traces.append(trace)
            return UnitCall(
                ok=True, data=data, traces=traces,
                finish_reason=trace.finish_reason, attempt=attempt, state="ok",
            )
        except LLMFatalError:
            trace.state = "error"
            trace.error_code = "LLM_FATAL"
            traces.append(trace)
            return UnitCall(traces=traces, attempt=attempt, state="fatal", error_code="LLM_FATAL")
        except LLMFormatError:
            truncated = trace.finish_reason == "length" or trace.error_code == "OUTPUT_TRUNCATED"
            code = "OUTPUT_TRUNCATED" if truncated else "FORMAT_FAILED"
            trace.state = "error"
            trace.error_code = code
            traces.append(trace)
            return UnitCall(
                traces=traces, attempt=attempt,
                state="truncated" if truncated else "format_failed", error_code=code,
            )
        except LLMTransientError:
            exhausted = attempt >= settings.LLM_MAX_TRANSIENT_RETRIES
            trace.state = "error"
            trace.error_code = "BATCH_TIMEOUT" if exhausted else "LLM_TRANSIENT_RETRY"
            traces.append(trace)
            if exhausted:
                return UnitCall(traces=traces, attempt=attempt, state="timeout", error_code="BATCH_TIMEOUT")
            continue
    return UnitCall(traces=traces, state="timeout", error_code="BATCH_TIMEOUT")


def _execute_unit(unit: SearchUnit, client: Any, user: str) -> UnitCall:
    """设置 X-QA-Tag(run_id) 后执行单元；tag 随真实 HTTP 下发供 QA A3 归属核对。"""
    tag_token = _ACTIVE_TAG.set(str(unit.run_id))
    try:
        return _execute_unit_inner(unit, client, user)
    finally:
        _ACTIVE_TAG.reset(tag_token)


def _append_traces(run_id: uuid.UUID, unit: SearchUnit, call: UnitCall) -> None:
    """逐请求 JSONL：只存 hash / 时间戳 / 状态 / 短码，不存窗口全文。"""
    try:
        trace_dir = Path(settings.DATA_DIR) / "perf_traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        path = trace_dir / f"{run_id}.jsonl"
        lines: list[str] = []
        for attempt, tr in enumerate(call.traces):
            rec = tr.to_dict()
            check_ids = [leaf["id"] for leaf in unit.check_items]
            rec.update(
                {
                    "run_id": str(run_id),
                    "request_id": unit.request_id,
                    "window_id": unit.window_id,
                    "window_index": unit.window_index,
                    # QA A3/A4 断言入口字段（与 request_id/batch_index/check_item_ids 并存）
                    "batch_id": f"b{unit.batch_index}",
                    "check_ids": check_ids,
                    "check_item_id": check_ids[0] if check_ids else None,
                    "batch_index": unit.batch_index,
                    "check_item_ids": check_ids,
                    "attempt": attempt,
                    "unit_state": call.state,
                    "unit_error_code": call.error_code,
                }
            )
            lines.append(json.dumps(rec, ensure_ascii=False, default=str))
        if lines:
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
    except OSError:
        # 观测落盘失败不影响业务结果落库
        pass


def _write_unit_step(
    task_id: uuid.UUID, run_id: uuid.UUID, unit: SearchUnit,
    state: str, error_code: str | None,
) -> None:
    """窗口×批次观测步：step_key=u:w{wi}:b{bi}，短码写 last_error_code。"""
    _touch_step(
        task_id, run_id, f"u:{unit.window_id}:b{unit.batch_index}",
        StepState.SUCCEEDED.value if state == "ok" else StepState.FAILED.value,
        started_at=_now(), finished_at=_now(),
        last_error_code=error_code,
        input_hash_extra=unit.request_id,
    )


def _direct_check_result(
    task_id: uuid.UUID, run_id: uuid.UUID, leaf: dict[str, Any], reason: str,
) -> None:
    """缺材料 / 无 OCR 块：无单元，直接写 not_found + check 步（沿用 T02 语义）。"""
    with Session(engine) as session:
        _write_not_found(session, task_id, run_id, leaf, reason)
        session.commit()
    _touch_step(
        task_id, run_id, f"check:{leaf['id']}", StepState.SUCCEEDED.value,
        started_at=_now(), finished_at=_now(),
        input_hash_extra=_stable_leaf_hash(leaf),
    )


def _flush_check(task_id: uuid.UUID, run_id: uuid.UUID, agg: CheckAgg) -> None:
    """收集端短事务：去重+稳定排序后落库该检查项全部结果与 check 步。"""
    cid = agg.leaf["id"]
    evidence = _dedup_evidence(list(agg.evidence.values()), cid)
    with Session(engine) as session:
        for rank, ev in enumerate(evidence):
            _write_text_result(session, task_id, run_id, agg.leaf, ev, rank)
        if agg.failed or agg.fatal:
            # 存在未覆盖窗口：保留已成功摘录 + 明确标记覆盖不全
            _write_not_found(session, task_id, run_id, agg.leaf, "coverage_incomplete")
        elif not evidence:
            _write_not_found(session, task_id, run_id, agg.leaf, "no_matching_evidence")
        session.commit()
    # PARTIAL_COVERAGE 是检查项级 failed_reason，不是短码；批次短码落 u: 步 / JSONL。
    _touch_step(
        task_id, run_id, f"check:{cid}",
        StepState.FAILED.value if agg.fatal else StepState.SUCCEEDED.value,
        started_at=_now(), finished_at=_now(),
        last_error_code="LLM_FATAL" if agg.fatal else None,
        input_hash_extra=_stable_leaf_hash(agg.leaf),
    )


def _search_stage(
    task_id: uuid.UUID, run_id: uuid.UUID,
    snapshot: dict[str, Any], client: Any,
) -> None:
    leaves = _leaves_from_snapshot(snapshot)
    with Session(engine) as session:
        run_files = session.exec(
            select(RunFile).where(RunFile.run_id == run_id, RunFile.task_id == task_id)
        ).all()
    material_files: dict[str, list[uuid.UUID]] = {}
    for rf in run_files:
        if rf.effective_material_type:
            material_files.setdefault(rf.effective_material_type, []).append(rf.file_id)

    max_chars = settings.LLM_WINDOW_CHARACTERS
    overlap_chars = settings.LLM_WINDOW_OVERLAP_CHARACTERS
    X = settings.CHECKS_PER_REQUEST

    # 按 material 分组：检查项按清单顺序；稳定窗口复用 load_source_blocks + chunk_source_blocks
    material_checks: dict[str, list[dict[str, Any]]] = {}
    material_windows: dict[str, list[Window]] = {}
    for leaf in leaves:
        if leaf.get("result_mode") in ("seal", "signature"):
            continue
        material = leaf["material_type"]
        file_ids = material_files.get(material, [])
        if not file_ids:
            _direct_check_result(task_id, run_id, leaf, "material_missing")
            continue
        material_checks.setdefault(material, []).append(leaf)
        if material not in material_windows:
            blocks = load_source_blocks(task_id, file_ids)
            material_windows[material] = chunk_source_blocks(blocks, max_chars, overlap_chars)

    units: list[SearchUnit] = []
    aggs: dict[str, CheckAgg] = {}
    batches_meta: list[dict[str, Any]] = []
    batch_index = 0
    for material, checks in material_checks.items():
        windows = material_windows[material]
        if not windows:
            for leaf in checks:
                _direct_check_result(task_id, run_id, leaf, "no_matching_evidence")
            continue
        for leaf in checks:
            aggs[leaf["id"]] = CheckAgg(leaf=leaf, total_windows=len(windows))
        for start in range(0, len(checks), X):
            batch = checks[start:start + X]
            bid = batch_index
            batch_index += 1
            batches_meta.append(
                {
                    "material_type": material,
                    "batch_index": bid,
                    "check_item_ids": [leaf["id"] for leaf in batch],
                    "window_count": len(windows),
                }
            )
            for wi, window in enumerate(windows):
                units.append(
                    SearchUnit(
                        run_id=run_id,
                        task_id=task_id,
                        request_id=f"{run_id}:w{wi}:b{bid}",
                        window=window,
                        window_id=f"w{wi}",
                        window_index=wi,
                        batch_index=bid,
                        check_items=batch,
                    )
                )

    # 把实际 X / C / 每批检查项 / 分窗策略 / 提示词版本 / 单元总数冻结进 run_config
    with Session(engine) as session:
        _write_run_config(
            session,
            run_id,
            {
                "batch": {
                    "checks_per_request": X,
                    "status": "已启用：窗口×检查项批次并发调度（X=1 视为批大小 1）",
                    "batches": batches_meta,
                    "units_total": len(units),
                },
                "units_total": len(units),
                "search_prompt_version": SEARCH_PROMPT_VERSION,
                "search_system": "SEARCH_BATCH_SYSTEM_TEMPLATE",
            },
        )

    # 一次提交全部单元：max_workers = C；额度内立即发出，先回先收、即时补位。
    # 不固定分波、不等同一批最慢；llm_client._IN_FLIGHT 由同一 C 驱动，无第二层限流。
    max_workers = settings.LLM_MAX_IN_FLIGHT
    pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="search")
    fatal_seen = False
    try:
        future_to_unit: dict[Any, SearchUnit] = {}
        for unit in units:
            unit.t_submit = time.perf_counter()
            future_to_unit[pool.submit(_execute_unit, unit, client, _render_unit_user(unit))] = unit

        for fut in as_completed(future_to_unit):
            unit = future_to_unit[fut]
            try:
                call = fut.result()
            except Exception:  # noqa: BLE001
                call = UnitCall(state="fatal", error_code="LLM_FATAL")

            unit_codes: list[str] = []
            if call.error_code and call.error_code not in unit_codes:
                unit_codes.append(call.error_code)
            if call.ok and call.data is not None:
                validation = validate_batch_response(
                    call.data, unit.check_items, unit.window,
                    finish_reason=call.finish_reason,
                )
                for code in validation.error_codes:
                    if code not in unit_codes:
                        unit_codes.append(code)
            else:
                # 单元整体失败（超时/格式/致命）：本批当前窗口所有检查项均未覆盖
                failed_code = call.error_code or "FORMAT_FAILED"
                validation = BatchValidation(
                    per_check={
                        leaf["id"]: BatchCheckResult(leaf["id"], False, [], [failed_code])
                        for leaf in unit.check_items
                    },
                    error_codes=list(unit_codes),
                )
            call.error_code = ",".join(unit_codes)[:64] or None
            _append_traces(run_id, unit, call)
            _write_unit_step(task_id, run_id, unit, call.state, call.error_code)
            if call.state == "fatal":
                fatal_seen = True

            for leaf in unit.check_items:
                cid = leaf["id"]
                agg = aggs[cid]
                res = validation.per_check[cid]
                if res.covered and not fatal_seen:
                    for ev in res.evidence:
                        agg.evidence.setdefault(ev.content_hash, ev)
                else:
                    agg.failed = True
                for code in res.anomalies:
                    agg.anomalies.add(code)
                if fatal_seen:
                    agg.fatal = True
                agg.done_windows += 1
                if agg.done_windows == agg.total_windows and not agg.flushed:
                    agg.flushed = True
                    _flush_check(task_id, run_id, agg)

            if fatal_seen:
                # 致命错误：本批检查项立即落 FAILED 步并停止派发，由 run_pipeline 标 FAILED
                for leaf in unit.check_items:
                    agg = aggs[leaf["id"]]
                    if not agg.flushed:
                        agg.fatal = True
                        agg.flushed = True
                        _flush_check(task_id, run_id, agg)
                raise RuntimeError("LLM_FATAL: 搜索阶段鉴权/参数等致命错误，整次 run 标记失败")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _vision_stage(task_id: uuid.UUID, run_id: uuid.UUID, snapshot: dict[str, Any], client: Any) -> None:
    leaves = _leaves_from_snapshot(snapshot)
    with Session(engine) as session:
        run_files = session.exec(
            select(RunFile).where(RunFile.run_id == run_id, RunFile.task_id == task_id)
        ).all()
    material_files: dict[str, list[uuid.UUID]] = {}
    for rf in run_files:
        if rf.effective_material_type:
            material_files.setdefault(rf.effective_material_type, []).append(rf.file_id)

    # 预取依赖项结果（如审计机构名）
    with Session(engine) as session:
        dep_texts: dict[str, str] = {}
        for leaf in leaves:
            for dep in leaf.get("dependencies", []):
                if dep not in dep_texts:
                    dep_texts[dep] = ""
        if dep_texts:
            rows = session.exec(
                select(Result).where(
                    Result.run_id == run_id,
                    Result.task_id == task_id,
                    Result.check_item_id.in_(list(dep_texts.keys())),  # type: ignore[attr-defined]
                )
            ).all()
            for row in rows:
                if row.text:
                    dep_texts[row.check_item_id] = row.text

    for leaf in leaves:
        if leaf.get("result_mode") not in ("seal", "signature"):
            continue
        material = leaf["material_type"]
        file_ids = material_files.get(material, [])
        if not file_ids:
            with Session(engine) as session:
                _write_not_found(session, task_id, run_id, leaf, "material_missing")
                session.commit()
            continue

        with Session(engine) as session:
            crops = load_crops(session, task_id, file_ids)

        target_text = None
        for dep in leaf.get("dependencies", []):
            if dep_texts.get(dep):
                target_text = dep_texts[dep]
                break

        # 先文字匹配
        evidence: list[CropEvidence] = match_by_text(crops, target_text)

        # 文字不足以确定（无依赖目标，或文字没匹配到）→ 视觉兜底
        if not evidence:
            evidence = match_by_vision(
                crops=crops,
                check_item=leaf,
                client=client,
                batch_size=settings.VISION_IMAGES_PER_BATCH,
                max_edge=settings.VISION_MAX_IMAGE_EDGE,
            )

        with Session(engine) as session:
            if not evidence:
                _write_not_found(session, task_id, run_id, leaf, "no_matching_evidence")
            else:
                for rank, ev in enumerate(evidence):
                    _write_crop_result(session, task_id, run_id, leaf, ev, rank)
            session.commit()


def _mark_run_failed(session: Session, run_id: uuid.UUID, code: str) -> None:
    run = session.get(ProcessingRun, run_id)
    if run:
        run.state = RunState.FAILED.value
        run.error_code = code
        run.finished_at = _now()
        session.add(run)


def _complete_run(run_id: uuid.UUID) -> None:
    with Session(engine) as session:
        run = session.get(ProcessingRun, run_id)
        if not run:
            return
        if run.state == RunState.FAILED.value:
            # 阶段已标记失败，不覆盖
            return
        summary = compute_coverage_summary(
            session, run.task_id, run_id, run.checklist_snapshot or {}
        )
        run.state = RunState.READY.value
        run.stage = "done"
        # 删除无条件 True：仅当全部应查窗口 SUCCEEDED 才置 true
        run.coverage_complete = summary.coverage_complete
        # F3：无任何单元步的保守分支记错误码（不覆盖已有阶段错误码）
        if summary.error_code and not run.error_code:
            run.error_code = summary.error_code
        run.finished_at = _now()
        session.add(run)
        # 任务状态 → 待核对
        task = session.get(Task, run.task_id)
        if task and task.state == TaskState.PROCESSING.value:
            task.state = TaskState.REVIEWING.value
            session.add(task)
        session.commit()


# ---------------------------------------------------------------------------
# 入口任务
# ---------------------------------------------------------------------------


@app.task(name="processing.run", queue="processing")
def run_pipeline(run_id: str) -> None:
    rid = uuid.UUID(run_id)
    with Session(engine) as session:
        run = session.get(ProcessingRun, rid)
        if not run or run.state not in (RunState.QUEUED.value, RunState.RUNNING.value):
            return
        task_id = run.task_id
        snapshot = run.checklist_snapshot or {}
        checklist_hash_value = run.checklist_hash
        run.state = RunState.RUNNING.value
        run.started_at = _now()
        session.add(run)
        session.commit()

    # 把 X / C / 分窗策略 / 版本 / 清单 hash 冻结进 model_snapshot.run_config
    with Session(engine) as session:
        _write_run_config(session, rid, build_run_config(checklist_hash_value))

    client = get_llm_client()

    # 阶段 1：材料分类
    _touch_step(task_id, rid, "stage:classify", StepState.RUNNING.value, started_at=_now())
    try:
        _classify_stage(task_id, rid, client)
        _touch_step(task_id, rid, "stage:classify", StepState.SUCCEEDED.value, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        _touch_step(
            task_id, rid, "stage:classify", StepState.FAILED.value,
            finished_at=_now(), last_error_code=f"CLASSIFY_FAILED:{type(exc).__name__}"[:64],
        )
        with Session(engine) as session:
            _mark_run_failed(session, rid, f"CLASSIFY_FAILED:{type(exc).__name__}"[:64])
            session.commit()
        return

    # 阶段 2：文本/表格查找
    _touch_step(task_id, rid, "stage:search", StepState.RUNNING.value, started_at=_now())
    try:
        _search_stage(task_id, rid, snapshot, client)
        _touch_step(task_id, rid, "stage:search", StepState.SUCCEEDED.value, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        _touch_step(
            task_id, rid, "stage:search", StepState.FAILED.value,
            finished_at=_now(), last_error_code=f"SEARCH_FAILED:{type(exc).__name__}"[:64],
        )
        with Session(engine) as session:
            _mark_run_failed(session, rid, f"SEARCH_FAILED:{type(exc).__name__}"[:64])
            session.commit()
        return

    # 阶段 3：印章/签名匹配
    _touch_step(task_id, rid, "stage:vision", StepState.RUNNING.value, started_at=_now())
    try:
        _vision_stage(task_id, rid, snapshot, client)
        _touch_step(task_id, rid, "stage:vision", StepState.SUCCEEDED.value, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        _touch_step(
            task_id, rid, "stage:vision", StepState.FAILED.value,
            finished_at=_now(), last_error_code=f"VISION_FAILED:{type(exc).__name__}"[:64],
        )
        with Session(engine) as session:
            _mark_run_failed(session, rid, f"VISION_FAILED:{type(exc).__name__}"[:64])
            session.commit()
        return

    _complete_run(rid)
