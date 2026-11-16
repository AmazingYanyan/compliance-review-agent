#!/usr/bin/env python3
"""资产 1 自测：真实启动模拟服务、真实并发发请求、校验统计口径。

本脚本只验证「模拟服务本身可用」，**不是业务验收**：
* 不连数据库、不 import 业务代码、不调用真实模型；
* 所有数字来自服务端真实计时，落盘到 ``--out``；
* 用 ``--config mock_config.full_concurrency.json`` 可验证 barrier 收齐 + reverse 放行。

用法：
    python3 backend/tests/perf/selftest_mock_server.py \
        --config backend/tests/perf/mock_config.full_concurrency.json \
        --port 18099 --requests 12 \
        --out /tmp/qa_mock_selftest.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SERVER = HERE / "mock_llm_server.py"

CHECK_IDS = [
    "charter.business_scope",
    "charter.approval_body",
    "charter.voting_ratio",
    "charter.guarantee_restrictions",
    "charter.legal_representative_signature_authority",
    "charter.ownership_and_special_terms",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get(base: str, path: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(base + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wait_health(base: str, proc: subprocess.Popen, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"模拟服务提前退出，code={proc.returncode}")
        try:
            data = _get(base, "/__health", timeout=1.0)
            if data.get("ok"):
                return
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.1)
    raise RuntimeError("等待 /__health 超时")


def _build_body(check_id: str, window_index: int, seq: int) -> dict[str, Any]:
    # 用固定但合法的 UUID 充当窗口内 block_id（模拟服务只按字符串解析，不查库）
    block_ids = [
        str(uuid.UUID(int=0x1000 + window_index * 16 + i)) for i in range(4)
    ]
    window_text = "\n".join(
        f'block_id={bid} 文本="模拟窗口 {window_index} 的第 {i} 个块"' 
        for i, bid in enumerate(block_ids)
    )
    user = (
        f"检查项：模拟检查项（id={check_id}，结果模式=verbatim_quotes）\n"
        "请判断该检查项能否在下面的文本块里找到对应证据。\n" + window_text
    )
    return {
        "model": "qa-selftest-model",
        "messages": [
            {"role": "system", "content": "模拟 system 提示词"},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "text_search_output",
                "schema": {"type": "object"},
                "strict": True,
            },
        },
        "_qa_seq": seq,
    }


def _post(base: str, body: dict[str, Any], tag: str | None) -> dict[str, Any]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if tag:
        headers["X-QA-Tag"] = tag
    req = urllib.request.Request(
        base + "/v1/chat/completions", data=payload, headers=headers, method="POST"
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            raw = resp.read().decode("utf-8")
            return {
                "ok": True,
                "status": resp.status,
                "client_elapsed_ms": round((time.monotonic() - t0) * 1000, 3),
                "body": json.loads(raw),
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "client_elapsed_ms": round((time.monotonic() - t0) * 1000, 3),
            "body": exc.read().decode("utf-8")[:300],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="模拟服务自测")
    parser.add_argument("--config", default=str(HERE / "mock_config.example.json"))
    parser.add_argument("--port", type=int, default=18099)
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--out", default=None, help="自测证据 JSON 路径")
    parser.add_argument("--tag", default=None, help="给所有请求打同一个 tag")
    args = parser.parse_args()

    base = f"http://127.0.0.1:{args.port}"
    stats_out = f"/tmp/qa_mock_selftest_stats_{args.port}.json"
    cmd = [
        sys.executable, str(SERVER),
        "--config", str(Path(args.config).resolve()),
        "--port", str(args.port),
        "--stats-out", stats_out,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _wait_health(base, proc)
        bodies = [
            _build_body(CHECK_IDS[i % len(CHECK_IDS)], i // len(CHECK_IDS), i)
            for i in range(args.requests)
        ]
        t_start = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.requests) as pool:
            futures = [pool.submit(_post, base, b, args.tag) for b in bodies]
            client_results = [f.result() for f in as_completed(futures)]
        client_wall_ms = round((time.monotonic() - t_start) * 1000, 3)
        stats = _get(base, "/__stats", timeout=10.0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    check("服务返回所有请求", len(client_results) == args.requests,
          f"客户端收到 {len(client_results)}/{args.requests}")
    check("统计请求数与发出数一致", stats["request_count"] == args.requests,
          f"stats.request_count={stats['request_count']} 预期={args.requests}")
    check("每个请求都有真实到达时间",
          all(r["arrived_at"] for r in stats["requests"]),
          f"有 arrived_at 的请求数={sum(1 for r in stats['requests'] if r['arrived_at'])}")
    check("峰值在途 == 并发请求数", stats["peak_inflight"] == args.requests,
          f"实测 peak_inflight={stats['peak_inflight']} 预期={args.requests}")
    check("barrier 已收齐并放行" if stats["barrier"]["enabled"] else "barrier 未启用（跳过）",
          (not stats["barrier"]["enabled"]) or stats["barrier"]["ready"],
          f"enabled={stats['barrier']['enabled']} ready={stats['barrier']['ready']} "
          f"arrived={stats['barrier']['arrived_count']}")
    if stats["barrier"]["enabled"] and stats["barrier"]["ready"]:
        order = stats["barrier"]["release_order_actual_arrival_seqs"]
        check("barrier 放行顺序 == reverse",
              order == list(reversed(range(1, args.requests + 1))),
              f"实际放行 seq 顺序={order}")
    check("每个请求都识别到 check_item_id",
          all(r["check_item_id"] for r in stats["requests"]),
          f"识别到 check_item_id 的数量="
          f"{sum(1 for r in stats['requests'] if r['check_item_id'])}")
    check("首末到达时间差有真实测量值",
          isinstance(stats["first_last_arrival_gap_ms"], (int, float)),
          f"实测 first_last_arrival_gap_ms={stats['first_last_arrival_gap_ms']}")

    evidence: dict[str, Any] = {
        "schema_version": "qa-mock-selftest-1",
        "ran_at": _now_iso(),
        "scope": "仅验证模拟服务本身可用；不是业务验收，不是真实模型结果",
        "config": str(Path(args.config).resolve()),
        "port": args.port,
        "requests_sent": args.requests,
        "client_wall_ms": client_wall_ms,
        "client_status_codes": sorted({r["status"] for r in client_results}),
        "server_stats_path": stats_out,
        "server_stats": stats,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": sum(1 for c in checks if c["status"] == "PASS"),
            "failed": sum(1 for c in checks if c["status"] == "FAIL"),
        },
    }
    out_path = Path(args.out) if args.out else HERE / "evidence" / "selftest_mock_server.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for c in checks:
        print(f"{c['status'].ljust(4)} | {c['name']} | {c['detail']}")
    print(f"\n自测证据：{out_path}")
    print(f"服务端统计：{stats_out}")
    return 0 if evidence["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
