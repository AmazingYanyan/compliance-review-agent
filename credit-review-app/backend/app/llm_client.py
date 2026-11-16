"""LLM 客户端封装（OpenAI 兼容 Chat Completions）。

- 结构化输出：优先 response_format=json_schema（严格模式），不支持时降级 json_object
- 结果严格校验：Pydantic 模型校验，最多一次格式修复（不循环让模型编合法答案）
- SDK 层 max_retries=0，重试由步骤层管理（避免 SDK 与业务重试相乘）
- 并发：**模块级** ``_IN_FLIGHT = BoundedSemaphore(LLM_MAX_IN_FLIGHT)`` 是唯一在途上限；
  实例级 semaphore 已删除。调度器不得再建第二层信号量，否则形成双重限流。
  ``LLM_MAX_CONCURRENCY`` 降级为兼容别名，不参与限流。
- 观测：可选 ``RequestTrace`` 记录逐请求 hash / 时间戳 / 状态 / 错误码（K10：不存窗口全文）。
  请求 hash（user_sha256 / messages_sha256 / window_text_sha256）只进 trace 与证据，
  绝不写进 ``RunStep.input_hash``。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

import openai
from openai import OpenAI

from app.core.config import settings


class LLMError(Exception):
    """LLM 调用错误基类。"""


class LLMTransientError(LLMError):
    """连接/超时/429/5xx 等可重试错误。"""


class LLMFatalError(LLMError):
    """鉴权/无权限/参数错误等不可重试错误。"""


class LLMFormatError(LLMError):
    """返回内容无法解析为合法 JSON 或未通过 schema 校验。"""


_TRANSIENT = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)

_FATAL = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.BadRequestError,
    openai.UnprocessableEntityError,
)


def _classify(exc: Exception) -> LLMError:
    if isinstance(exc, _FATAL):
        return LLMFatalError(str(exc))
    if isinstance(exc, _TRANSIENT):
        return LLMTransientError(str(exc))
    # openai.APIStatusError 兜底
    if isinstance(exc, openai.APIStatusError):
        code = getattr(exc, "status_code", None)
        if code is not None and code >= 500:
            return LLMTransientError(str(exc))
        return LLMFatalError(str(exc))
    return LLMTransientError(str(exc))


@dataclass
class RequestTrace:
    """单次结构化调用的时序与状态记录（K10：只存 hash / 时间戳 / 状态 / 错误码）。

    请求侧 hash 含 ``block_id=<UUID>``，属于「实际发给模型的请求 hash」，
    只允许出现在 JSONL trace 与证据里，不得写入 ``RunStep.input_hash``。
    """

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    t_submit: float | None = None
    t_http_start: float | None = None
    t_http_end: float | None = None
    t_persist: float | None = None
    finish_reason: str | None = None
    state: str = "pending"
    error_code: str | None = None
    messages_sha256: str | None = None
    user_sha256: str | None = None
    window_text_sha256: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """导出为可写 JSONL 的扁平 dict（无窗口全文、无密钥）。"""
        return {
            "trace_id": self.trace_id,
            "t_submit": self.t_submit,
            "t_http_start": self.t_http_start,
            "t_http_end": self.t_http_end,
            "t_persist": self.t_persist,
            "finish_reason": self.finish_reason,
            "state": self.state,
            "error_code": self.error_code,
            "messages_sha256": self.messages_sha256,
            "user_sha256": self.user_sha256,
            "window_text_sha256": self.window_text_sha256,
            "model": self.model,
        }


# 模块级唯一在途上限：settings.LLM_MAX_IN_FLIGHT 在 import 时固化，改值必须重启容器。
_IN_FLIGHT = threading.BoundedSemaphore(settings.LLM_MAX_IN_FLIGHT)

# _chat 的调用签名需与既有 monkeypatch 包装器保持兼容（5 个位置参数），
# 因此 trace 通过 ContextVar 传递，而不是新增必传/可选 kwargs。
_ACTIVE_TRACE: ContextVar[RequestTrace | None] = ContextVar("llm_active_trace", default=None)

# T03 / QA A3 归属：可选 run 标识，以 X-QA-Tag 请求头随真实 HTTP 下发。
# 由并发调度器在模型线程里 set（线程本地），classification / vision 不 set 即不带该头；
# 不改 complete_json 签名。离线 monkeypatch Completions.create 时该 kwarg 被忽略。
_ACTIVE_TAG: ContextVar[str | None] = ContextVar("llm_active_tag", default=None)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _split_chat_result(result: Any) -> tuple[str, str | None]:
    """兼容返回 ``(content, finish_reason)`` 与旧式只返回 content 的包装器。"""
    if isinstance(result, tuple) and len(result) == 2:
        content, finish_reason = result
        return str(content), (str(finish_reason) if finish_reason is not None else None)
    return str(result), None


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            base_url=settings.LLM_API_BASE,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    # -- 内部：一次原始调用 -------------------------------------------------

    def _chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        response_format: dict[str, Any] | None,
        temperature: float,
        trace: RequestTrace | None = None,
    ) -> tuple[str, str | None]:
        """发起一次 Chat Completions 请求，返回 ``(content, finish_reason)``。

        ``finish_reason == "length"`` 是输出被截断的信号；写入 trace 供后续判读。
        trace 优先取显式参数，其次取 ``complete_json`` 设置的 ContextVar。
        """
        active = trace or _ACTIVE_TRACE.get()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
        }
        tag = _ACTIVE_TAG.get()
        if tag:
            kwargs["extra_headers"] = {
                **(kwargs.get("extra_headers") or {}),
                "X-QA-Tag": tag,
            }
        if response_format is not None:
            kwargs["response_format"] = response_format
        if active is not None and active.t_http_start is None:
            active.t_http_start = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            if active is not None:
                active.t_http_end = time.perf_counter()
                active.state = "error"
                active.error_code = type(exc).__name__
            raise _classify(exc) from exc
        if active is not None:
            active.t_http_end = time.perf_counter()

        choice = resp.choices[0] if resp.choices else None
        finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
        message = getattr(choice, "message", None) if choice is not None else None
        content = getattr(message, "content", None) if message is not None else None
        if active is not None:
            active.finish_reason = str(finish_reason) if finish_reason is not None else None
            if finish_reason == "length" and not active.error_code:
                active.error_code = "OUTPUT_TRUNCATED"
        if not content:
            raise LLMFormatError("模型返回空内容")
        return content, finish_reason

    # -- 结构化输出主入口 ---------------------------------------------------

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any],
        validator: Callable[[dict[str, Any]], Any],
        images: list[str] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        trace: RequestTrace | None = None,
    ) -> dict[str, Any]:
        """调用模型并返回通过校验的 JSON（dict）。

        images 为视觉模型的 base64 data URL 列表（可选）；提供时 user 消息变为
        多模态 content 数组。validator 为 Pydantic 模型类，用于校验返回结构。
        ``trace`` 可选，向后兼容：classification / vision 等调用方不传。
        """
        model = model or settings.LLM_TEXT_MODEL
        messages = self._build_messages(system, user, images)
        active = trace if trace is not None else RequestTrace()
        if active.t_submit is None:
            active.t_submit = time.perf_counter()
        active.state = "running"
        active.model = model
        active.user_sha256 = _sha256_text(user)
        active.messages_sha256 = _sha256_text(
            json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)
        )

        token = _ACTIVE_TRACE.set(active)
        try:
            return self._complete_json_inner(
                messages, model, schema_name, json_schema, validator, temperature, active
            )
        finally:
            _ACTIVE_TRACE.reset(token)
            active.t_persist = time.perf_counter()

    def _complete_json_inner(
        self,
        messages: list[dict[str, Any]],
        model: str,
        schema_name: str,
        json_schema: dict[str, Any],
        validator: Callable[[dict[str, Any]], Any],
        temperature: float,
        trace: RequestTrace,
    ) -> dict[str, Any]:
        """首次请求与格式修复分别 acquire 信号量（BoundedSemaphore 非可重入，不可嵌套）。"""

        def _request(msgs: list[dict[str, Any]], response_format: dict[str, Any], temp: float) -> str:
            with _IN_FLIGHT:
                if trace.t_http_start is None:
                    trace.t_http_start = time.perf_counter()
                finish_reason: str | None = None
                try:
                    content, finish_reason = _split_chat_result(
                        self._chat(msgs, model, response_format, temp)
                    )
                finally:
                    trace.t_http_end = time.perf_counter()
                if finish_reason is not None and trace.finish_reason is None:
                    trace.finish_reason = finish_reason
                if finish_reason == "length" and not trace.error_code:
                    trace.error_code = "OUTPUT_TRUNCATED"
                return content

        strict_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
                "strict": True,
            },
        }
        try:
            raw = _request(messages, strict_format, temperature)
        except LLMFatalError:
            # 模型不支持 json_schema 时降级 json_object（单独一次 acquire）
            raw = _request(messages, {"type": "json_object"}, temperature)
        data = self._parse(raw)

        # 首次校验（在信号量之外执行，避免持锁做 CPU 校验）
        first_error: Exception
        try:
            validator(data)
            trace.state = "ok"
            return data
        except Exception as exc:  # noqa: BLE001
            first_error = exc

        # 最多一次格式修复：把校验错误反馈给模型重试（_repair 内部单独 acquire）
        repaired = self._repair(messages, model, json_schema, schema_name, data, first_error)
        try:
            validator(repaired)
            trace.state = "ok"
            return repaired
        except Exception as second_err:  # noqa: BLE001
            trace.state = "error"
            trace.error_code = "LLM_FORMAT_ERROR"
            raise LLMFormatError(f"两次校验失败: {second_err}") from second_err

    # -- 辅助 ---------------------------------------------------------------

    def _build_messages(
        self, system: str, user: str, images: list[str] | None
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if images:
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            for img in images:
                content.append(
                    {"type": "image_url", "image_url": {"url": img}}
                )
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user})
        return messages

    def _parse(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        # 去掉可能的 markdown 代码块包裹
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMFormatError(f"JSON 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMFormatError("返回不是 JSON 对象")
        return data

    def _repair(
        self,
        messages: list[dict[str, Any]],
        model: str,
        json_schema: dict[str, Any],
        schema_name: str,
        original: dict[str, Any],
        error: Exception,
    ) -> dict[str, Any]:
        feedback = (
            "你上一次返回的 JSON 未通过校验，请严格按给定 schema 修正后重新输出，"
            "只输出合法 JSON，不要输出任何解释。\n"
            f"上次返回：{json.dumps(original, ensure_ascii=False)}\n"
            f"校验错误：{error}\n"
            f"目标 schema：{json.dumps(json_schema, ensure_ascii=False)}"
        )
        messages = messages + [{"role": "assistant", "content": json.dumps(original, ensure_ascii=False)},
                               {"role": "user", "content": feedback}]
        # 格式修复单独 acquire，不与首次请求共用同一个 with（BoundedSemaphore 非可重入）
        with _IN_FLIGHT:
            raw, _finish_reason = _split_chat_result(
                self._chat(messages, model, {"type": "json_object"}, 0.0)
            )
        return self._parse(raw)


# 模块级单例
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
