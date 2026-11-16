#!/usr/bin/env python3
"""QA 性能试验 · 模拟 LLM 服务（资产 1）。

用途
----
一个 **纯标准库、独立进程** 的 OpenAI 兼容 Chat Completions 模拟服务，
用于在「不调用任何真实模型」的前提下验证：

* 请求确实被发出（记录每个请求到达服务端的真实时间）；
* 峰值在途数（已到达但尚未返回响应的最大并发数）；
* 「先收齐 N 个请求，再按预设顺序放行」（barrier 模式）；
* 可控短延迟，用于「一快一慢、快结束立即补发下一条」；
* 注入 401 / 429 / 500 / 格式失败 / 输出截断 / 超时；
* 输出机器可读 JSON 统计，供后续断言消费。

设计约束
--------
* 只依赖 Python 标准库，不 import 任何业务代码、不连数据库、不触发外部服务。
* 所有时间来自 ``time.time()`` / ``time.monotonic()``，逐请求落盘，不填推算值。
* 「在途」定义为：请求已到达本服务 handler，且尚未写出完整响应。
  barrier 等待期间同样算在途 —— 这正是需要证明的「请求已经发出」。
* 服务端只能观测「实际 HTTP 到达时间」；「任务提交时间」由客户端脚本另记，
  两者相减才是排队/调度开销（见 README）。

端点
----
* ``POST * /chat/completions``   —— 兼容任意 base_url 前缀，OpenAI SDK 直接可打
* ``GET  /__health``             —— 存活探针
* ``GET  /__stats``              —— 返回当前完整统计（机器可读 JSON）
* ``GET  /__dump``               —— 把统计写到 ``--stats-out`` 并返回路径
* ``POST /__reset``              —— 清空统计（保留配置），便于同一进程跑多组用例

用法
----
    python3 backend/tests/perf/mock_llm_server.py \
        --config backend/tests/perf/mock_config.example.json \
        --stats-out /tmp/qa_mock_stats.json

进程收到 SIGINT / SIGTERM 时会自动把统计落盘。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量与工具
# ---------------------------------------------------------------------------

SCHEMA_TEXT_SEARCH = "text_search_output"
SCHEMA_CLASSIFICATION = "classification_output"
SCHEMA_VISION = "vision_match_output"

BLOCK_ID_RE = re.compile(r"block_id=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
CHECK_ID_RE = re.compile(r"检查项：.*?（id=([A-Za-z0-9_.\-]+)")
BATCH_CHECK_RE = re.compile(r"check_item_id\s*[=:]\s*[\"']?([A-Za-z0-9_.\-]+)")
INVALID_BLOCK_ID = "00000000-0000-4000-8000-000000000000"

DEFAULT_RESPONSES: dict[str, dict[str, Any]] = {
    SCHEMA_CLASSIFICATION: {
        "bundle_id": "merged",
        "material_type": "articles_of_association",
        "mixed": False,
        "confidence": 0.9,
        "reason": "模拟服务默认分类响应",
        "source_block_ids": [],
    },
    SCHEMA_TEXT_SEARCH: {
        "bundle_id": "window-0",
        "check_results": [],
    },
    SCHEMA_VISION: {
        "bundle_id": "window-0",
        "check_item_id": "unknown",
        "matches": [],
    },
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_str(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _round_ms(value: float) -> float:
    return round(value, 3)


def _walk_render(obj: Any, ctx: dict[str, Any]) -> Any:
    """递归渲染模板里的 ``{{...}}`` 占位符。"""
    if isinstance(obj, str):
        out = obj
        for token, value in ctx.items():
            out = out.replace("{{" + token + "}}", str(value))
        return out
    if isinstance(obj, list):
        return [_walk_render(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk_render(v, ctx) for k, v in obj.items()}
    return obj


def _resolve_ref(root: dict[str, Any], path: list[Any]) -> Any:
    """按 ``path``（字符串键 / 整数下标）从 JSON 根里取一个子对象。"""
    cur: Any = root
    for part in path:
        if isinstance(cur, list) and isinstance(part, int):
            cur = cur[part]
        elif isinstance(cur, dict):
            cur = cur[str(part)]
        else:
            raise KeyError(f"response_ref 路径无法解析：{path!r} 在 {part!r} 处中断")
    return cur


# ---------------------------------------------------------------------------
# 请求分类：把 OpenAI 请求体解析成可匹配的字段
# ---------------------------------------------------------------------------


@dataclass
class RequestInfo:
    arrival_seq: int
    arrived_at: str
    arrived_monotonic_ms: float
    schema_name: str
    check_item_id: str | None
    batch_check_ids: list[str]
    block_ids: list[str]
    window_index: int
    attempt: int
    tag: str | None
    response_format_type: str | None
    model: str | None
    user_chars: int
    raw_body_sha256: str


class Classifier:
    """从请求体提取匹配字段；window_index 按窗口文本中的 block_id 序列稳定编号。"""

    def __init__(self, batch_regex: str | None = None) -> None:
        self._batch_re = re.compile(batch_regex) if batch_regex else BATCH_CHECK_RE
        # window_index 必须按 (schema_name, check_item_id) 分组从 0 编号：
        # 分类窗口与搜索窗口的块序列不同，若全局编号会让搜索窗口 1 变成 2/3，
        # 导致「只注入窗口 1」的规则永远匹配不上。
        self._window_index_by_key: dict[str, int] = {}
        self._group_window_count: dict[str, int] = {}
        self._attempt_counter: dict[str, int] = {}
        self._lock = threading.Lock()

    def classify(self, body: dict[str, Any], seq: int, arrived_at: str,
                 arrived_monotonic_ms: float, tag: str | None) -> RequestInfo:
        messages = body.get("messages") or []
        system = ""
        user = ""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, list):
                content = " ".join(
                    str(p.get("text", "")) for p in content if isinstance(p, dict)
                )
            text = content if isinstance(content, str) else ""
            if msg.get("role") == "system":
                system = text
            elif msg.get("role") == "user":
                user = text

        response_format = body.get("response_format") or {}
        rf_type = response_format.get("type") if isinstance(response_format, dict) else None
        schema_name = "unknown"
        if isinstance(response_format, dict):
            js = response_format.get("json_schema")
            if isinstance(js, dict) and js.get("name"):
                schema_name = str(js["name"])
            elif rf_type:
                schema_name = str(rf_type)

        block_ids = BLOCK_ID_RE.findall(user) or BLOCK_ID_RE.findall(system)
        window_hash = _sha256_str("\n".join(block_ids))
        single = CHECK_ID_RE.search(user)
        check_item_id = single.group(1) if single else None
        batch_ids = list(dict.fromkeys(self._batch_re.findall(user)))
        if not batch_ids and check_item_id:
            batch_ids = [check_item_id]

        group_key = (
            f"{schema_name}|{check_item_id or (batch_ids[0] if batch_ids else '-')}"
        )
        window_key = f"{group_key}|{window_hash}"
        with self._lock:
            if window_key not in self._window_index_by_key:
                idx = self._group_window_count.get(group_key, 0)
                self._window_index_by_key[window_key] = idx
                self._group_window_count[group_key] = idx + 1
            window_index = self._window_index_by_key[window_key]

            attempt_key = f"{group_key}|{window_index}|{','.join(batch_ids)}"
            attempt = self._attempt_counter.get(attempt_key, 0)
            self._attempt_counter[attempt_key] = attempt + 1

        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
        return RequestInfo(
            arrival_seq=seq,
            arrived_at=arrived_at,
            arrived_monotonic_ms=arrived_monotonic_ms,
            schema_name=schema_name,
            check_item_id=check_item_id,
            batch_check_ids=batch_ids,
            block_ids=block_ids,
            window_index=window_index,
            attempt=attempt,
            tag=tag,
            response_format_type=rf_type,
            model=body.get("model"),
            user_chars=len(user),
            raw_body_sha256=_sha256_str(raw),
        )

    def reset(self) -> None:
        with self._lock:
            self._window_index_by_key.clear()
            self._group_window_count.clear()
            self._attempt_counter.clear()


# ---------------------------------------------------------------------------
# 屏障：先收齐 N 个请求，再按预设顺序放行
# ---------------------------------------------------------------------------


@dataclass
class BarrierConfig:
    enabled: bool = False
    size: int = 0
    release_order: Any = "as_arrived"
    release_gap_ms: float = 0.0
    wait_timeout_seconds: float = 30.0
    check_item_order: list[str] = field(default_factory=list)


class Barrier:
    def __init__(self, cfg: BarrierConfig) -> None:
        self.cfg = cfg
        self._cond = threading.Condition()
        self._arrivals: dict[int, RequestInfo] = {}
        self._ready = False
        self._timed_out = False
        self._reached_at: str | None = None
        self._rank: dict[int, int] = {}
        self._order_actual: list[int] = []

    def _compute_order(self) -> list[int]:
        seqs = sorted(self._arrivals)
        order = self.cfg.release_order
        if isinstance(order, list):
            explicit = [int(x) for x in order]
            missing = [s for s in seqs if s not in explicit]
            return explicit + missing
        if order == "reverse":
            return list(reversed(seqs))
        if order == "by_check_item":
            rank_map = {cid: i for i, cid in enumerate(self.cfg.check_item_order)}

            def key(seq: int) -> tuple[int, int]:
                info = self._arrivals[seq]
                cid = info.check_item_id or (
                    info.batch_check_ids[0] if info.batch_check_ids else ""
                )
                return (rank_map.get(cid, len(rank_map) + 1), seq)

            return sorted(seqs, key=key)
        return seqs  # as_arrived

    def arrive(self, info: RequestInfo) -> tuple[float, bool]:
        """返回 ``(额外等待秒数, 是否属于本轮屏障)``。

        未启用屏障、或本请求序号已超出 ``size`` 时，直接返回 ``(0, False)``。
        """
        if not self.cfg.enabled or self.cfg.size <= 0:
            return 0.0, False
        with self._cond:
            if info.arrival_seq > self.cfg.size:
                return 0.0, False
            self._arrivals[info.arrival_seq] = info
            deadline = time.monotonic() + self.cfg.wait_timeout_seconds
            while not self._ready and time.monotonic() < deadline:
                if len(self._arrivals) >= self.cfg.size:
                    self._ready = True
                    self._reached_at = _now_iso()
                    self._order_actual = self._compute_order()
                    self._rank = {seq: i for i, seq in enumerate(self._order_actual)}
                    self._cond.notify_all()
                    break
                self._cond.wait(timeout=0.05)
            if not self._ready:
                self._timed_out = True
                self._ready = True
                self._order_actual = sorted(self._arrivals)
                self._rank = {seq: i for i, seq in enumerate(self._order_actual)}
                self._cond.notify_all()
            rank = self._rank.get(info.arrival_seq, 0)
            return rank * self.cfg.release_gap_ms / 1000.0, True

    def snapshot(self) -> dict[str, Any]:
        with self._cond:
            return {
                "enabled": self.cfg.enabled,
                "size": self.cfg.size,
                "release_order_config": self.cfg.release_order,
                "release_gap_ms": self.cfg.release_gap_ms,
                "arrived_count": len(self._arrivals),
                "ready": self._ready,
                "timed_out": self._timed_out,
                "reached_at": self._reached_at,
                "release_order_actual_arrival_seqs": self._order_actual,
                "release_order_actual_check_item_ids": [
                    (self._arrivals[s].check_item_id
                     or (self._arrivals[s].batch_check_ids[0]
                         if self._arrivals[s].batch_check_ids else None))
                    for s in self._order_actual
                ],
            }

    def reset(self) -> None:
        with self._cond:
            self._arrivals.clear()
            self._ready = False
            self._timed_out = False
            self._reached_at = None
            self._rank.clear()
            self._order_actual.clear()


# ---------------------------------------------------------------------------
# 服务端状态与统计
# ---------------------------------------------------------------------------


class ServerState:
    def __init__(self, cfg: dict[str, Any], config_path: str | None,
                 stats_out: str | None, tag_header: str) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.stats_out = stats_out
        self.tag_header = tag_header
        self.started_at = _now_iso()
        self.started_monotonic_ms = time.monotonic() * 1000.0
        self.classifier = Classifier(cfg.get("batch_check_ids_regex"))
        barrier_raw = cfg.get("barrier") or {}
        self.barrier = Barrier(BarrierConfig(
            enabled=bool(barrier_raw.get("enabled", False)),
            size=int(barrier_raw.get("size", 0)),
            release_order=barrier_raw.get("release_order", "as_arrived"),
            release_gap_ms=float(barrier_raw.get("release_gap_ms", 0)),
            wait_timeout_seconds=float(barrier_raw.get("wait_timeout_seconds", 30)),
            check_item_order=list(barrier_raw.get("check_item_order") or []),
        ))
        self._lock = threading.Lock()
        self._seq = 0
        self._inflight = 0
        self._peak_inflight = 0
        self._requests: list[dict[str, Any]] = []
        self._fixture_cache: dict[str, dict[str, Any]] = {}

    # -- 计数 ---------------------------------------------------------------

    def enter_request(self, info: RequestInfo) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            self._inflight += 1
            self._peak_inflight = max(self._peak_inflight, self._inflight)
            rec: dict[str, Any] = {
                "arrival_seq": info.arrival_seq,
                "arrived_at": info.arrived_at,
                "arrived_monotonic_ms": info.arrived_monotonic_ms,
                "inflight_at_arrival": self._inflight,
                "schema_name": info.schema_name,
                "check_item_id": info.check_item_id,
                "batch_check_ids": info.batch_check_ids,
                "batch_size": len(info.batch_check_ids),
                "window_index": info.window_index,
                "attempt": info.attempt,
                "tag": info.tag,
                "response_format_type": info.response_format_type,
                "model": info.model,
                "user_chars": info.user_chars,
                "block_id_count": len(info.block_ids),
                "raw_body_sha256": info.raw_body_sha256,
                "matched_rule": None,
                "inject": None,
                "released_at": None,
                "responded_at": None,
                "status_code": None,
                "elapsed_ms": None,
                "error": None,
            }
            self._requests.append(rec)
            return rec

    def leave_request(self, rec: dict[str, Any]) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)
            rec["responded_at"] = _now_iso()
            rec["elapsed_ms"] = _round_ms(
                time.monotonic() * 1000.0 - rec["arrived_monotonic_ms"]
            )

    def next_seq(self) -> int:
        with self._lock:
            return self._seq + 1

    def peak(self) -> int:
        with self._lock:
            return self._peak_inflight

    # -- fixture ------------------------------------------------------------

    def load_fixture(self, path: str) -> dict[str, Any]:
        abs_path = path
        if not Path(abs_path).is_absolute():
            base = Path(self.config_path).parent if self.config_path else Path.cwd()
            abs_path = str((base / path).resolve())
        if abs_path not in self._fixture_cache:
            self._fixture_cache[abs_path] = json.loads(
                Path(abs_path).read_text(encoding="utf-8")
            )
        return self._fixture_cache[abs_path]

    # -- 统计 ---------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            requests = [dict(r) for r in self._requests]
            peak = self._peak_inflight
            seq = self._seq
            inflight = self._inflight
        arrivals = [r["arrived_monotonic_ms"] for r in requests]
        first_gap = (
            _round_ms(max(arrivals) - min(arrivals)) if len(arrivals) >= 2 else 0.0
        )
        expected = self.cfg.get("expected_request_count")
        by_schema: dict[str, int] = {}
        by_check: dict[str, int] = {}
        by_inject: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        for r in requests:
            by_schema[r["schema_name"]] = by_schema.get(r["schema_name"], 0) + 1
            key = r["check_item_id"] or "(none)"
            by_check[key] = by_check.get(key, 0) + 1
            inj = r["inject"] or "(none)"
            by_inject[inj] = by_inject.get(inj, 0) + 1
            tag = r["tag"] or "(untagged)"
            by_tag[tag] = by_tag.get(tag, 0) + 1
        return {
            "schema_version": "qa-mock-llm-stats-1",
            "service": "mock_llm_server.py",
            "started_at": self.started_at,
            "snapshot_at": _now_iso(),
            "config_path": self.config_path,
            "config_sha256": (
                _sha256_str(Path(self.config_path).read_text(encoding="utf-8"))
                if self.config_path and Path(self.config_path).is_file() else None
            ),
            "request_count": seq,
            "current_inflight": inflight,
            "peak_inflight": peak,
            "first_arrival_at": requests[0]["arrived_at"] if requests else None,
            "last_arrival_at": requests[-1]["arrived_at"] if requests else None,
            "first_last_arrival_gap_ms": first_gap,
            "expected_request_count": expected,
            "arrival_count_matches_expected": (
                None if expected is None else seq == int(expected)
            ),
            "proves_requests_actually_sent": seq > 0 and all(
                r["arrived_at"] for r in requests
            ),
            "by_schema": by_schema,
            "by_check_item": by_check,
            "by_inject": by_inject,
            "by_tag": by_tag,
            "barrier": self.barrier.snapshot(),
            "requests": requests,
        }

    def dump(self) -> str | None:
        if not self.stats_out:
            return None
        target = Path(self.stats_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return str(target)

    def reset(self) -> None:
        with self._lock:
            self._seq = 0
            self._inflight = 0
            self._peak_inflight = 0
            self._requests.clear()
        self.classifier.reset()
        self.barrier.reset()


# ---------------------------------------------------------------------------
# 规则匹配与响应渲染
# ---------------------------------------------------------------------------


def _match_rule(rule: dict[str, Any], info: RequestInfo) -> bool:
    when = rule.get("when") or {}
    checks = (
        ("schema_name", info.schema_name),
        ("check_item_id", info.check_item_id),
        ("window_index", info.window_index),
        ("attempt", info.attempt),
        ("tag", info.tag),
        ("batch_size", len(info.batch_check_ids)),
    )
    for key, actual in checks:
        if key in when and when[key] != actual:
            return False
    if "check_item_id_in" in when:
        if info.check_item_id not in when["check_item_id_in"]:
            return False
    if "any_of_check_item_ids" in when:
        wanted = set(when["any_of_check_item_ids"])
        if not (wanted & set(info.batch_check_ids)):
            return False
    return True


def _build_context(info: RequestInfo) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        # T01/T02 后 Window.bundle_id 稳定为 w{idx}（不再是 window-{idx}）
        "BUNDLE": f"w{info.window_index}",
        "CHECK_ID": info.check_item_id or "unknown",
        "WINDOW_INDEX": info.window_index,
        "SEQ": info.arrival_seq,
        "ATTEMPT": info.attempt,
        "INVALID_BLOCK": INVALID_BLOCK_ID,
        "BLOCK:LAST": info.block_ids[-1] if info.block_ids else INVALID_BLOCK_ID,
        "BLOCK_COUNT": len(info.block_ids),
    }
    for i, bid in enumerate(info.block_ids):
        ctx[f"BLOCK:{i}"] = bid
    return ctx


def _pick_response(state: ServerState, rule: dict[str, Any] | None,
                   info: RequestInfo) -> tuple[dict[str, Any], str | None]:
    """返回 (响应模板, 命中的规则名)。模板稍后统一渲染占位符。"""
    if rule:
        if "response" in rule:
            return rule["response"], rule.get("name")
        ref = rule.get("response_ref")
        if isinstance(ref, dict) and ref.get("file") and ref.get("path"):
            root = state.load_fixture(str(ref["file"]))
            return _resolve_ref(root, list(ref["path"])), rule.get("name")
    base = DEFAULT_RESPONSES.get(info.schema_name, DEFAULT_RESPONSES[SCHEMA_TEXT_SEARCH])
    out = json.loads(json.dumps(base, ensure_ascii=False))
    if info.schema_name == SCHEMA_TEXT_SEARCH:
        ids = info.batch_check_ids or ([info.check_item_id] if info.check_item_id else [])
        out["check_results"] = [
            {"check_item_id": cid, "outcome": "not_found", "evidence": []}
            for cid in ids
        ]
    return out, None


def _inject_error_response(inject: str, cfg: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """返回故障注入用的 (HTTP 状态码, body)。"""
    if inject == "401":
        return 401, {
            "error": {
                "message": "QA 注入：invalid api key",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }
    if inject == "429":
        return 429, {
            "error": {
                "message": "QA 注入：rate limit exceeded",
                "type": "rate_limit_error",
                "code": "rate_limit_exceeded",
            }
        }
    if inject == "500":
        return 500, {
            "error": {
                "message": "QA 注入：internal server error",
                "type": "server_error",
                "code": "internal_error",
            }
        }
    raise ValueError(f"未知故障注入类型：{inject}")


def _make_chat_completion(content: str, model: str | None,
                          finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": f"chatcmpl-qa-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "qa-mock-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "QAMockLLM/1.0"

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # 诊断走 stderr，不污染 stdout（stdout 只留启动信息）
        sys.stderr.write("[mock] " + (fmt % args) + "\n")

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # -- 控制端点 -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/__health":
            self._send_json(200, {"ok": True, "service": "qa-mock-llm"})
            return
        if path == "/__stats":
            self._send_json(200, self.state.snapshot())
            return
        if path == "/__dump":
            out = self.state.dump()
            self._send_json(200, {"ok": True, "stats_out": out})
            return
        self._send_json(404, {"error": "unknown control endpoint", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/__reset":
            self._read_body()
            self.state.reset()
            self._send_json(200, {"ok": True, "reset": True})
            return
        if not path.endswith("/chat/completions"):
            self._read_body()
            self._send_json(404, {"error": "only /chat/completions is supported", "path": path})
            return
        self._handle_chat()

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    # -- 主逻辑 -------------------------------------------------------------

    def _handle_chat(self) -> None:
        raw = self._read_body()
        arrived_at = _now_iso()
        arrived_monotonic_ms = time.monotonic() * 1000.0
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {}

        tag = self.headers.get(self.state.tag_header)
        seq = self.state.next_seq()
        info = self.state.classifier.classify(
            body, seq, arrived_at, arrived_monotonic_ms, tag
        )
        rec = self.state.enter_request(info)

        # 选规则（第一条匹配者胜）
        rule: dict[str, Any] | None = None
        for candidate in (self.state.cfg.get("rules") or []):
            if _match_rule(candidate, info):
                rule = candidate
                break
        rec["matched_rule"] = rule.get("name") if rule else None
        inject = (rule or {}).get("inject") or self.state.cfg.get("default_inject")
        rec["inject"] = inject

        try:
            # 1) 屏障：先收齐 N 个再按预设顺序放行
            wait_seconds, in_barrier = self.state.barrier.arrive(info)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            rec["released_at"] = _now_iso() if in_barrier else arrived_at

            # 2) 可控短延迟
            delay_ms = float(
                (rule or {}).get("delay_ms", self.state.cfg.get("default_delay_ms", 0))
            )
            if inject == "timeout":
                hang = float(self.state.cfg.get("timeout_hang_seconds", 3.0))
                time.sleep(hang)
            elif delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

            # 3) 构造并写出响应
            if inject in ("401", "429", "500"):
                status, payload = _inject_error_response(inject, self.state.cfg)
            elif inject == "format_error":
                status = 200
                payload = _make_chat_completion(
                    "QA 注入：这不是合法 JSON {{{", info.model
                )
            elif inject == "truncated":
                template, _ = _pick_response(self.state, rule, info)
                rendered = _walk_render(template, _build_context(info))
                full = json.dumps(rendered, ensure_ascii=False)
                cut = max(1, int(len(full) * float(
                    self.state.cfg.get("truncate_ratio", 0.6)
                )))
                status = 200
                payload = _make_chat_completion(
                    full[:cut], info.model, finish_reason="length"
                )
                payload["qa_truncation_signal"] = {
                    "injected": True,
                    "original_chars": len(full),
                    "returned_chars": cut,
                }
            else:
                template, _ = _pick_response(self.state, rule, info)
                rendered = _walk_render(template, _build_context(info))
                status = 200
                payload = _make_chat_completion(
                    json.dumps(rendered, ensure_ascii=False), info.model
                )
            rec["status_code"] = status
            self._send_json(status, payload)
        except BrokenPipeError:
            # 客户端（如超时）先断开：仍算「请求确实发出」
            rec["error"] = "client_disconnected_before_response"
            rec["status_code"] = rec["status_code"] or 499
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
            rec["status_code"] = rec["status_code"] or 500
            try:
                self._send_json(500, {"error": {"message": rec["error"]}})
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.state.leave_request(rec)


class QAServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], state: ServerState) -> None:
        self.state = state
        super().__init__(addr, Handler)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="QA 性能试验模拟 LLM 服务")
    parser.add_argument("--config", default=None, help="JSON 配置路径")
    parser.add_argument("--host", default=None, help="覆盖配置里的 host")
    parser.add_argument("--port", type=int, default=None, help="覆盖配置里的 port")
    parser.add_argument("--stats-out", default=None, help="统计 JSON 落盘路径")
    parser.add_argument(
        "--tag-header", default=None,
        help="读取该请求头作为 tag（用于两个 run 隔离验证）",
    )
    args = parser.parse_args()

    cfg = _load_config(args.config)
    host = args.host or cfg.get("host") or "127.0.0.1"
    port = args.port or int(cfg.get("port") or 8099)
    stats_out = args.stats_out or cfg.get("stats_out")
    tag_header = args.tag_header or cfg.get("tag_header") or "X-QA-Tag"

    state = ServerState(cfg, args.config, stats_out, tag_header)
    server = QAServer((host, port), state)

    def _shutdown(signum: int, _frame: Any) -> None:
        sys.stderr.write(f"[mock] 收到信号 {signum}，落盘统计后退出\n")
        out = state.dump()
        if out:
            sys.stderr.write(f"[mock] 统计已写入 {out}\n")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    sys.stderr.write(
        f"[mock] 监听 http://{host}:{port}/chat/completions  "
        f"barrier={state.barrier.cfg.enabled}/{state.barrier.cfg.size}  "
        f"stats_out={stats_out}\n"
    )
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        out = state.dump()
        if out:
            sys.stderr.write(f"[mock] 最终统计已写入 {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
