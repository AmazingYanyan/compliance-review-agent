"""决策状态机与统计（P4）：人工确认（接受/拒绝）+ 统计口径。

- 每个 result 一条 decision（result_id 主键），不存在视同 unselected
- rejected 允许空原因（草稿），完成时校验非空
- 统计：N=U+A+R，M=rejected 且原因 strip 为空，can_complete = U=0 且 M=0
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Decision,
    DecisionEvent,
    DecisionValue,
    ProcessingRun,
    Result,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def _statistics_of(results: list[Result], dec_by_result: dict[uuid.UUID, Decision]) -> dict:
    total = len(results)
    unselected = 0
    accepted = 0
    rejected = 0
    missing_reason = 0
    for r in results:
        d = dec_by_result.get(r.id)
        value = d.decision if d else DecisionValue.unselected.value
        if value == DecisionValue.accepted.value:
            accepted += 1
        elif value == DecisionValue.rejected.value:
            rejected += 1
            if not (d.reject_reason or "").strip():
                missing_reason += 1
        else:
            unselected += 1

    accept_rate = (accepted / total) if total else None
    reject_rate = (rejected / total) if total else None
    can_complete = total > 0 and unselected == 0 and missing_reason == 0
    return {
        "total": total,
        "unselected": unselected,
        "accepted": accepted,
        "rejected": rejected,
        "missing_reason": missing_reason,
        "accept_rate": accept_rate,
        "reject_rate": reject_rate,
        "can_complete": can_complete,
    }


def compute_statistics(
    session: Session,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    check_meta: dict[str, dict],
) -> dict:
    """返回 {overall, materials}，按材料分组统计。"""
    results = session.exec(
        select(Result).where(Result.task_id == task_id, Result.run_id == run_id)
    ).all()
    result_ids = [r.id for r in results]
    dec_by_result: dict[uuid.UUID, Decision] = {}
    if result_ids:
        decisions = session.exec(
            select(Decision).where(
                Decision.task_id == task_id,
                Decision.result_id.in_(result_ids),  # type: ignore[attr-defined]
            )
        ).all()
        dec_by_result = {d.result_id: d for d in decisions}

    overall = _statistics_of(results, dec_by_result)

    # 按材料分组
    by_material: dict[str, list[Result]] = {}
    for r in results:
        material = check_meta.get(r.check_item_id, {}).get("material_type") or "unknown"
        by_material.setdefault(material, []).append(r)
    materials = [
        {
            "material_type": material,
            "statistics": _statistics_of(rs, dec_by_result),
        }
        for material, rs in sorted(by_material.items())
    ]
    return {"overall": overall, "materials": materials}


# ---------------------------------------------------------------------------
# 决策写入
# ---------------------------------------------------------------------------


def write_decision(
    session: Session,
    task_id: uuid.UUID,
    result_id: uuid.UUID,
    decision: str,
    reject_reason: str | None,
    actor_user_id: uuid.UUID | None,
) -> tuple[Decision, str | None]:
    """写入决策，返回 (decision, 错误消息或 None)。

    校验：decision 合法；非 rejected 时 reason 必须 null；rejected 允许空草稿。
    """
    if decision not in (
        DecisionValue.unselected.value,
        DecisionValue.accepted.value,
        DecisionValue.rejected.value,
    ):
        return None, "非法 decision 值"

    if decision != DecisionValue.rejected.value and reject_reason:
        return None, "仅拒绝时需要填写原因"
    if reject_reason and len(reject_reason) > 4000:
        return None, "拒绝原因超长（上限 4000 字符）"

    existing = session.get(Decision, result_id)
    if existing is None:
        existing = Decision(
            result_id=result_id,
            task_id=task_id,
            decision=decision,
            reject_reason=reject_reason if decision == DecisionValue.rejected.value else None,
            version=1,
            actor_user_id=actor_user_id,
            updated_at=_now(),
        )
        session.add(existing)
    else:
        before = {
            "decision": existing.decision,
            "reject_reason": existing.reject_reason,
            "version": existing.version,
        }
        existing.decision = decision
        existing.reject_reason = reject_reason if decision == DecisionValue.rejected.value else None
        existing.version = existing.version + 1
        existing.actor_user_id = actor_user_id
        existing.updated_at = _now()
        session.add(existing)
        session.add(
            DecisionEvent(
                task_id=task_id,
                result_id=result_id,
                actor_user_id=actor_user_id,
                event_type="update",
                before=before,
                after={
                    "decision": decision,
                    "reject_reason": existing.reject_reason,
                    "version": existing.version,
                },
            )
        )
    session.flush()
    return existing, None


def decision_to_view(d: Decision) -> dict:
    return {
        "result_id": str(d.result_id),
        "decision": d.decision,
        "reject_reason": d.reject_reason,
        "version": d.version,
        "updated_at": d.updated_at,
        "carried_from_result_id": str(d.carried_from_result_id)
        if d.carried_from_result_id
        else None,
    }
