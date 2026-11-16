#!/usr/bin/env python3
"""补测：list_results 覆盖字段（F4 展示面 / 前端持久 banner 的数据源）。

C_partial run（窗口0 成功、窗口1 超时）已被软删，先临时恢复 deleted_at，
打 GET /results 断言 coverage_complete / coverage_affected_check_ids，再软删回去。
零真实模型 / 零外部 OCR；真实任务不触碰。
"""
from __future__ import annotations

import http.cookiejar
import json
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://localhost:8080/api/v1"
ORIGIN = "http://localhost:8080"
DB = "credit-review-app-db-1"
SETUP = json.loads((ROOT / "docs/perf_2026-11-13/t03_setup.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs/perf_2026-11-13/t03_list_results_evidence.json"
C = SETUP["C_partial"]


def _psql(sql: str) -> str:
    return subprocess.run(
        ["docker", "exec", DB, "psql", "-U", "postgres", "-d", "app", "-t", "-A", "-c", sql],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _credentials() -> tuple[str, str]:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("INITIAL_USERS_JSON="):
            u = json.loads(line.split("=", 1)[1].strip().strip("'").strip('"'))[0]
            return u["username"], u["password"]
    raise RuntimeError("无 INITIAL_USERS_JSON")


def main() -> int:
    ev: dict[str, Any] = {
        "selftest": "T03-补测-list_results覆盖字段",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_model_calls": 0, "external_ocr_calls": 0,
        "assertions": {},
    }
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        _psql(f"UPDATE tasks SET deleted_at=NULL WHERE id='{C['task_id']}' AND deleted_at IS NOT NULL;")
        username, password = _credentials()
        req = urllib.request.Request(
            BASE + "/auth/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with opener.open(req, timeout=20) as resp:
            csrf = json.loads(resp.read().decode())["csrf_token"]
        ev["login_csrf_present"] = bool(csrf)
        get = urllib.request.Request(BASE + f"/tasks/{C['task_id']}/results",
                                     headers={"Accept": "application/json"}, method="GET")
        with opener.open(get, timeout=20) as resp:
            body = json.loads(resp.read().decode())
            status = resp.status
        ev["response"] = {
            "status": status,
            "run_id": body.get("run_id"),
            "editable": body.get("editable"),
            "coverage_complete": body.get("coverage_complete"),
            "coverage_affected_check_ids": body.get("coverage_affected_check_ids"),
            "items": len(body.get("items", [])),
            "not_found_reasons": sorted({i.get("not_found_reason") for i in body.get("items", [])
                                         if i.get("not_found_reason")}),
        }
        ev["assertions"] = {
            "status_200": status == 200,
            "run_id_matches": body.get("run_id") == C["run_id"],
            "coverage_complete_false": body.get("coverage_complete") is False,
            "affected_check_ids_hit": "charter.business_scope" in (body.get("coverage_affected_check_ids") or []),
            "coverage_incomplete_reason_present": "coverage_incomplete" in ev["response"]["not_found_reasons"],
            "hit_excerpts_still_visible": any(i.get("kind") == "text" for i in body.get("items", [])),
        }
        ev["status"] = "pass" if all(ev["assertions"].values()) else "fail"
    except Exception as exc:  # noqa: BLE001
        import traceback
        ev["status"] = "error"
        ev["error"] = f"{type(exc).__name__}: {exc}"[:800]
        ev["traceback"] = traceback.format_exc()[-2000:]
    finally:
        _psql(f"UPDATE tasks SET deleted_at=now() WHERE id='{C['task_id']}' AND deleted_at IS NULL;")
        ev["task_soft_deleted_back"] = True
    OUT.write_text(json.dumps(ev, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(ev, ensure_ascii=False, indent=2, default=str) + "\n")
    return 0 if ev.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
