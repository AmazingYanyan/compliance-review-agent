#!/usr/bin/env python3
"""T03 三组验收 · HTTP 层脚本（宿主机执行）。

登录 + CSRF 后实跑：
* G2 三条：FAILED run → RUN_NOT_READY；READY+false → COVERAGE_INCOMPLETE + 零写入；
  READY+true → 200 COMPLETED。
* C：部分失败 run → 409 COVERAGE_INCOMPLETE + 零写入；正常 run → 200 COMPLETED。
* F1：空 check_results / 非法 ID 顶替 → 409 COVERAGE_INCOMPLETE；
  明确 not_found（补人工决策后）→ 200 COMPLETED（覆盖达成、完成放行）。
* 历史 REVIEWING 任务 607e6d41…：只读核对（硬边界禁止改写），
  完成动作在「无单元步 + coverage_complete=true」的同构隔离副本上实测 200。

最后把全部隔离任务软删保留（deleted_at），真实任务不触碰。
"""
from __future__ import annotations

import http.cookiejar
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = "http://localhost:8080/api/v1"
ORIGIN = "http://localhost:8080"
ROOT = Path(__file__).resolve().parents[2]  # credit-review-app/
SETUP_PATH = ROOT / "docs/perf_2026-11-13/t03_setup.json"
OUT_PATH = ROOT / "docs/perf_2026-11-13/t03_http_evidence.json"
DB = "credit-review-app-db-1"
SETUP = json.loads(SETUP_PATH.read_text(encoding="utf-8"))


def _credentials() -> tuple[str, str]:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("INITIAL_USERS_JSON="):
            raw = line.split("=", 1)[1].strip().strip("'").strip('"')
            users = json.loads(raw)
            u = users[0] if isinstance(users, list) else users
            return u["username"], u["password"]
    raise RuntimeError("INITIAL_USERS_JSON 未找到")


def _psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", DB, "psql", "-U", "postgres", "-d", "app", "-t", "-A", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _task_row(task_id: str) -> dict[str, str]:
    sql = (
        "SELECT state, COALESCE(completed_at::text,'NULL'), "
        "COALESCE(last_ready_run_id::text,'NULL'), COALESCE(deleted_at::text,'NULL') "
        f"FROM tasks WHERE id='{task_id}';"
    )
    parts = _psql(sql).split("|")
    return {
        "state": parts[0] if len(parts) > 0 else "",
        "completed_at": parts[1] if len(parts) > 1 else "",
        "last_ready_run_id": parts[2] if len(parts) > 2 else "",
        "deleted_at": parts[3] if len(parts) > 3 else "",
    }


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
CSRF = ""


def _request(method: str, path: str, body: dict[str, Any] | None = None, *,
             write: bool = False) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if write:
        headers["X-CSRF-Token"] = CSRF
        headers["Origin"] = ORIGIN
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return {"status": resp.status, "body": json.loads(raw) if raw else None}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw[:500]
        return {"status": exc.code, "body": parsed}


def _detail_code(resp: dict[str, Any]) -> str | None:
    b = resp.get("body")
    if isinstance(b, dict) and isinstance(b.get("detail"), dict):
        return b["detail"].get("code")
    return None


def _complete(case_key: str) -> dict[str, Any]:
    c = SETUP[case_key]
    before = _task_row(c["task_id"])
    resp = _request(
        "POST", f"/tasks/{c['task_id']}/complete",
        {"run_id": c["run_id"], "input_revision": c["input_revision"]},
        write=True,
    )
    after = _task_row(c["task_id"])
    return {
        "case": case_key, "task_id": c["task_id"], "run_id": c["run_id"],
        "status": resp["status"], "code": _detail_code(resp),
        "state": (resp["body"] or {}).get("state") if isinstance(resp["body"], dict) else None,
        "message": (resp["body"] or {}).get("detail", {}).get("message")
        if isinstance(resp["body"], dict) and isinstance(resp["body"].get("detail"), dict) else None,
        "task_before": before, "task_after": after,
        "zero_writes": before == after,
        "csrf_header": True, "origin": ORIGIN,
    }


def main() -> int:
    global CSRF
    ev: dict[str, Any] = {
        "selftest": "T03-三组验收-HTTP层",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_model_calls": 0, "external_ocr_calls": 0,
        "requests": [], "results": {}, "assertions": {},
    }
    try:
        username, password = _credentials()
        login = _request("POST", "/auth/login",
                         {"username": username, "password": password}, write=False)
        CSRF = (login["body"] or {}).get("csrf_token", "")
        ev["login"] = {"status": login["status"], "csrf_token_present": bool(CSRF),
                       "username": username}
        ev["requests"].append({"method": "POST", "path": "/auth/login", "status": login["status"]})
        if login["status"] != 200 or not CSRF:
            raise RuntimeError(f"登录失败: {login}")

        # F1_notfound：补 accepted 决策，模拟「可见摘录已全部人工确认」
        nf = SETUP["F1_notfound"]
        _psql(
            "INSERT INTO decisions (result_id, task_id, decision, version, updated_at) "
            "SELECT r.id, r.task_id, 'accepted', 1, now() FROM results r "
            f"WHERE r.run_id='{nf['run_id']}' "
            "AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.result_id=r.id);"
        )
        ev["f1_notfound_decision_seeded"] = True

        order = [
            "G2_failed", "G2_ready_false", "G2_ready_true",
            "C_partial", "C_ok", "F1_empty", "F1_invalid", "F1_notfound",
            "HIST_reviewing_clone",
        ]
        for key in order:
            r = _complete(key)
            ev["results"][key] = r
            ev["requests"].append({
                "method": "POST", "path": f"/tasks/{r['task_id']}/complete",
                "status": r["status"], "code": r["code"],
            })

        # 历史真实任务：只读核对（GET + psql），绝不改写
        real_tid = SETUP["historical_real_task"]["task_id"]
        read_back = _request("GET", f"/tasks/{real_tid}/results")
        ev["requests"].append({"method": "GET", "path": f"/tasks/{real_tid}/results",
                               "status": read_back["status"]})
        hist = _psql(
            "SELECT t.state, t.input_revision, r.state, r.coverage_complete, r.stage "
            "FROM tasks t JOIN processing_runs r ON r.task_id=t.id "
            f"WHERE t.id='{real_tid}' ORDER BY r.created_at DESC LIMIT 1;"
        ).split("|")
        unit_steps = int(_psql(
            "SELECT count(*) FROM run_steps WHERE run_id IN "
            f"(SELECT id FROM processing_runs WHERE task_id='{real_tid}') "
            "AND (step_key LIKE 'u:%' OR step_key LIKE 'check:%');"
        ) or "0")
        ev["historical_real_task"] = {
            "task_id": real_tid,
            "read_back_status": read_back["status"],
            "read_back_items": len((read_back["body"] or {}).get("items", [])),
            "task_state": hist[0] if len(hist) > 0 else None,
            "input_revision": hist[1] if len(hist) > 1 else None,
            "run_state": hist[2] if len(hist) > 2 else None,
            "run_coverage_complete": hist[3] if len(hist) > 3 else None,
            "run_stage": hist[4] if len(hist) > 4 else None,
            "unit_step_count": unit_steps,
            "note": "只读核对，未对真实任务执行任何写操作（硬边界）",
        }

        # ---- 断言 --------------------------------------------------------
        g2f, g2r, g2t = (ev["results"][k] for k in
                         ("G2_failed", "G2_ready_false", "G2_ready_true"))
        cp, co = ev["results"]["C_partial"], ev["results"]["C_ok"]
        fe, fi, fn = (ev["results"][k] for k in
                      ("F1_empty", "F1_invalid", "F1_notfound"))
        hc = ev["results"]["HIST_reviewing_clone"]
        ev["assertions"] = {
            "login_ok_with_csrf": ev["login"]["status"] == 200 and ev["login"]["csrf_token_present"],
            "G2_failed_RUN_NOT_READY": g2f["status"] == 409 and g2f["code"] == "RUN_NOT_READY",
            "G2_ready_false_COVERAGE_INCOMPLETE_zero_write": (
                g2r["status"] == 409 and g2r["code"] == "COVERAGE_INCOMPLETE" and g2r["zero_writes"]
            ),
            "G2_ready_true_200_COMPLETED": g2t["status"] == 200 and g2t["state"] == "COMPLETED",
            "C_partial_409_COVERAGE_INCOMPLETE_zero_write": (
                cp["status"] == 409 and cp["code"] == "COVERAGE_INCOMPLETE" and cp["zero_writes"]
            ),
            "C_ok_200_COMPLETED": co["status"] == 200 and co["state"] == "COMPLETED",
            "F1_empty_409": fe["status"] == 409 and fe["code"] == "COVERAGE_INCOMPLETE",
            "F1_invalid_409": fi["status"] == 409 and fi["code"] == "COVERAGE_INCOMPLETE",
            "F1_notfound_not_coverage_blocked_200": (
                fn["status"] == 200 and fn["state"] == "COMPLETED" and fn["code"] is None
            ),
            "historical_read_back_200": ev["historical_real_task"]["read_back_status"] == 200,
            "historical_run_coverage_true_no_unit_steps": (
                ev["historical_real_task"]["run_coverage_complete"] == "t"
                and ev["historical_real_task"]["unit_step_count"] == 0
            ),
            "historical_clone_200_COMPLETED": hc["status"] == 200 and hc["state"] == "COMPLETED",
        }
        ev["status"] = "pass" if all(ev["assertions"].values()) else "fail"
    except Exception as exc:  # noqa: BLE001
        import traceback
        ev["status"] = "error"
        ev["error"] = f"{type(exc).__name__}: {exc}"[:800]
        ev["traceback"] = traceback.format_exc()[-2500:]
    finally:
        # 全部隔离任务软删保留；真实任务绝不触碰
        ids = SETUP.get("soft_delete_candidates", [])
        if ids:
            quoted = ",".join(f"'{t}'" for t in ids)
            _psql(f"UPDATE tasks SET deleted_at=now() WHERE id IN ({quoted}) AND deleted_at IS NULL;")
            ev["isolated_tasks_soft_deleted"] = len(ids)
        ev["protected_task_state_after"] = _task_row(SETUP["protected_tasks"][0])
        ev["protected_task_state_ee59108d_after"] = _task_row(SETUP["protected_tasks"][1])

    ev["assertions_failed"] = [k for k, v in ev["assertions"].items() if not v]
    OUT_PATH.write_text(json.dumps(ev, ensure_ascii=False, indent=2, default=str) + "\n",
                        encoding="utf-8")
    sys.stdout.write(json.dumps(ev, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0 if ev.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
