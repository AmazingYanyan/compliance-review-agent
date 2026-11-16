#!/usr/bin/env python3
"""qa-perf 三组快速验收 · C 组完成接口 HTTP 层独立实跑（宿主机执行）。

登录 + CSRF 后，对容器内实跑脚本造的**隔离任务**直接打真实 8080：
* C_partial（run READY / coverage_complete=false）→ POST /complete 期望
  409 COVERAGE_INCOMPLETE + 零写入；
* C_ok（run READY / coverage_complete=true / 已补 accepted 决策）→ 期望 200 COMPLETED；
* 顺带 GET /tasks/{id}/results 记录 coverage_complete / coverage_affected_check_ids /
  editable（覆盖不全 ≠ 整体只读，也是 Chrome banner 的数据前提）。

零写入判定：用 psql 只读目标任务 ID 的 tasks 行前后快照（天然带目标任务 ID 过滤，
避免 5s 轮询的其他任务写请求串扰），不依赖前端拦截。

输出：
  backend/tests/perf/evidence/quick_acceptance_run/c_complete.json（COMPLETE_SPEC）
  backend/tests/perf/evidence/quick_acceptance_run/c_http_raw.json（原始请求/响应）

用法：
  python3 backend/tests/perf/run_complete_http.py \
      --setup backend/tests/perf/evidence/quick_acceptance_run/setup.json
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # credit-review-app/
BASE = "http://localhost:8080/api/v1"
ORIGIN = "http://localhost:8080"
DB = "credit-review-app-db-1"


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
        ["docker", "exec", DB, "psql", "-U", "postgres", "-d", "app",
         "-t", "-A", "-c", sql],
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
            return {"status": resp.status,
                    "body": json.loads(raw) if raw else None}
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


def _complete(task_id: str, run_id: str, input_revision: int) -> dict[str, Any]:
    before = _task_row(task_id)
    resp = _request("POST", f"/tasks/{task_id}/complete",
                    {"run_id": run_id, "input_revision": input_revision},
                    write=True)
    after = _task_row(task_id)
    return {
        "task_id": task_id, "run_id": run_id,
        "status": resp["status"], "code": _detail_code(resp),
        "state": (resp["body"] or {}).get("state")
        if isinstance(resp["body"], dict) else None,
        "message": (resp["body"] or {}).get("detail", {}).get("message")
        if isinstance(resp["body"], dict)
        and isinstance(resp["body"].get("detail"), dict) else None,
        "task_before": before, "task_after": after,
        "zero_write": before == after,
        "task_id_filtered": True,
        "csrf_header": True, "origin": ORIGIN,
    }


def main() -> int:
    global CSRF
    p = argparse.ArgumentParser()
    p.add_argument("--setup", default=str(
        HERE / "evidence" / "quick_acceptance_run" / "setup.json"))
    p.add_argument("--out-dir", default=str(
        HERE / "evidence" / "quick_acceptance_run"))
    args = p.parse_args()
    out = Path(args.out_dir)
    setup = json.loads(Path(args.setup).read_text(encoding="utf-8"))
    partial = setup["C_partial"]
    ok = setup["C_ok"]
    ev: dict[str, Any] = {
        "schema_version": "qa-quick-acceptance-http-1",
        "ran_at": datetime.now(UTC).isoformat(),
        "scope": "C 组完成接口 + list_results 覆盖字段，真实 8080 HTTP，隔离任务未软删",
        "real_model_calls": 0, "external_ocr_calls": 0,
        "requests": [], "results": {}, "assertions": {},
    }
    try:
        username, password = _credentials()
        login = _request("POST", "/auth/login",
                         {"username": username, "password": password})
        CSRF = (login["body"] or {}).get("csrf_token", "")
        ev["login"] = {"status": login["status"],
                       "csrf_token_present": bool(CSRF), "username": username}
        ev["requests"].append({"method": "POST", "path": "/auth/login",
                               "status": login["status"]})
        if login["status"] != 200 or not CSRF:
            raise RuntimeError(f"登录失败: {login}")

        # list_results 覆盖字段（部分失败任务）
        lr = _request("GET", f"/tasks/{partial['task_id']}/results")
        body = lr.get("body") if isinstance(lr.get("body"), dict) else {}
        ev["list_results_partial"] = {
            "status": lr["status"],
            "coverage_complete": body.get("coverage_complete"),
            "coverage_affected_check_ids": body.get("coverage_affected_check_ids"),
            "editable": body.get("editable"),
            "item_count": len(body.get("items") or []),
        }
        ev["requests"].append({"method": "GET",
                               "path": f"/tasks/{partial['task_id']}/results",
                               "status": lr["status"]})

        ev["results"]["partial"] = _complete(
            partial["task_id"], partial["run_id"], partial["input_revision"])
        ev["requests"].append({"method": "POST",
                               "path": f"/tasks/{partial['task_id']}/complete",
                               "status": ev["results"]["partial"]["status"],
                               "code": ev["results"]["partial"]["code"]})
        ev["results"]["ok"] = _complete(
            ok["task_id"], ok["run_id"], ok["input_revision"])
        ev["requests"].append({"method": "POST",
                               "path": f"/tasks/{ok['task_id']}/complete",
                               "status": ev["results"]["ok"]["status"],
                               "code": ev["results"]["ok"]["code"]})

        p_res, o_res = ev["results"]["partial"], ev["results"]["ok"]
        lrp = ev["list_results_partial"]
        ev["assertions"] = {
            "login_ok_with_csrf": ev["login"]["status"] == 200
            and ev["login"]["csrf_token_present"],
            "partial_409_COVERAGE_INCOMPLETE": (
                p_res["status"] == 409 and p_res["code"] == "COVERAGE_INCOMPLETE"),
            "partial_zero_write": p_res["zero_write"] and p_res["task_id_filtered"],
            "ok_200_COMPLETED": (
                o_res["status"] == 200 and o_res["state"] == "COMPLETED"),
            "list_results_coverage_false": lrp["coverage_complete"] is False,
            "list_results_editable_true": lrp["editable"] is True,
            "list_results_affected_check_ids": bool(
                lrp["coverage_affected_check_ids"]),
        }
        ev["status"] = "pass" if all(ev["assertions"].values()) else "fail"
    except Exception as exc:  # noqa: BLE001
        import traceback
        ev["status"] = "error"
        ev["error"] = f"{type(exc).__name__}: {exc}"[:800]
        ev["traceback"] = traceback.format_exc()[-2000:]
    finally:
        ev["assertions_failed"] = [k for k, v in ev["assertions"].items() if not v]
        ev["protected_task_state_after"] = _task_row(setup["protected_tasks"][0])
        ev["protected_task_state_ee59108d_after"] = _task_row(
            setup["protected_tasks"][1])

    # ---- 组装 COMPLETE_SPEC（供 verify_quick_acceptance.py C 组断言） ----
    cp = json.loads((out / "c_partial_results.json").read_text(encoding="utf-8"))
    co = json.loads((out / "c_ok_results.json").read_text(encoding="utf-8"))
    text_rows = [r for r in cp["rows"] if r["kind"] == "text"]
    reasons = sorted({r["not_found_reason"] for r in cp["rows"]
                      if r["not_found_reason"]})
    ok_reasons = sorted({r["not_found_reason"] for r in co["rows"]
                         if r["not_found_reason"]})
    p_res = ev["results"].get("partial", {})
    o_res = ev["results"].get("ok", {})
    spec = {
        "schema_version": "qa-complete-spec-1",
        "status": ev["status"],
        "source": "run_complete_http.py 真实 8080 HTTP + 落库导出 c_*_results.json",
        "partial_failure": {
            "status": p_res.get("status"),
            "detail_code": p_res.get("code"),
            "zero_write": p_res.get("zero_write"),
            "task_id_filtered": p_res.get("task_id_filtered"),
            "kept_candidates": len(text_rows),
            "not_found_reason": reasons[0] if reasons else None,
            "run_coverage_complete": cp["coverage_complete"],
            "task_state": cp["task_state"],
            "unit_short_codes": sorted({s["last_error_code"] for s in cp["steps"]
                                        if s["step_key"].startswith("u:")
                                        and s["last_error_code"]}),
        },
        "normal_complete": {
            "status": o_res.get("status"),
            "state": o_res.get("state"),
            "run_coverage_complete": co["coverage_complete"],
            "not_found_reason": ok_reasons[0] if ok_reasons else None,
            "text_rows": len([r for r in co["rows"] if r["kind"] == "text"]),
        },
        "list_results_partial": ev.get("list_results_partial"),
        "http_assertions": ev["assertions"],
        "note": "所有字段来自真实 HTTP 响应 / 真实落库行；未跑的字段保持缺失，不填推算值。",
    }
    (out / "c_complete.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "c_http_raw.json").write_text(
        json.dumps(ev, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8")
    sys.stdout.write(json.dumps({
        "status": ev["status"],
        "assertions": ev["assertions"],
        "assertions_failed": ev["assertions_failed"],
    }, ensure_ascii=False, indent=2) + "\n")
    return 0 if ev["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
