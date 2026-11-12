"""LLM 客户端封装（OpenAI 兼容 Chat Completions）。

- 结构化输出：优先 response_format=json_schema（严格模式），不支持时降级 json_object
- 结果严格校验：Pydantic 模型校验，最多一次格式修复（不循环让模型编合法答案）
- SDK 层 max_retries=0，重试由步骤层管理（避免 SDK 与业务重试相乘）
- 并发：模块级信号量限制同时进行的 LLM 调用数
"""

from __future__ import annotations

import json
import threading
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


class LLMClient:
    def __init__(self) -> None:
        self._client = OpenAI(
            base_url=settings.LLM_API_BASE,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self._semaphore = threading.Semaphore(settings.LLM_MAX_CONCURRENCY)

    # -- 内部：一次原始调用 -------------------------------------------------

    def _chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        response_format: dict[str, Any] | None,
        temperature: float,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            raise LLMFormatError("模型返回空内容")
        return content

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
    ) -> dict[str, Any]:
        """调用模型并返回通过校验的 JSON（dict）。

        images 为视觉模型的 base64 data URL 列表（可选）；提供时 user 消息变为
        多模态 content 数组。validator 为 Pydantic 模型类，用于校验返回结构。
        """
        model = model or settings.LLM_TEXT_MODEL
        messages = self._build_messages(system, user, images)

        with self._semaphore:
            # 首选 json_schema 严格模式
            try:
                raw = self._chat(
                    messages,
                    model,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "schema": json_schema,
                            "strict": True,
                        },
                    },
                    temperature=temperature,
                )
            except LLMFatalError as exc:
                # 模型不支持 json_schema 时降级 json_object
                raw = self._chat(
                    messages,
                    model,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                )
            data = self._parse(raw)

        # 首次校验
        first_error: Exception | None = None
        try:
            validator(data)
            return data
        except Exception as exc:  # noqa: BLE001
            first_error = exc

        # 最多一次格式修复：把校验错误反馈给模型重试
        repaired = self._repair(messages, model, json_schema, schema_name, data, first_error)
        try:
            validator(repaired)
            return repaired
        except Exception as second_err:  # noqa: BLE001
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
        with self._semaphore:
            raw = self._chat(messages, model, {"type": "json_object"}, 0.0)
        return self._parse(raw)


# 模块级单例
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
