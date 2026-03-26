"""LLM adapter — OpenAI 兼容模式 + Langfuse @observe tracing.

和 memory 项目一致：通过 OpenAI SDK + base_url 对接 MiniMax API。
"""
from __future__ import annotations

import os
from typing import Any, AsyncIterator

import re

from langfuse import observe
from openai import AsyncOpenAI


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from model responses."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _create_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.minimaxi.com/v1"),
    )


def _get_model() -> str:
    return os.getenv("LLM_MODEL", "MiniMax-M2.7")


def _get_max_tokens() -> int:
    return int(os.getenv("LLM_MAX_TOKENS", "4096"))


def _get_temperature() -> float:
    return float(os.getenv("LLM_TEMPERATURE", "0.7"))


class LLMAdapter:
    """Thin wrapper around AsyncOpenAI — all calls traced by @observe."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        logger: Any | None = None,
    ):
        self.client = client or _create_client()
        self.model = model or _get_model()
        self.max_tokens = _get_max_tokens()
        self.temperature = _get_temperature()
        self._logger = logger

    @observe(name="LLM.generate")
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
        log_name: str = "",
    ) -> str:
        if json_mode:
            user_prompt = (
                user_prompt
                + "\n\n请严格以JSON格式返回结果，不要添加任何其他文字或markdown标记。"
            )

        # Optional structured logging
        log_ctx = None
        if self._logger and log_name:
            log_ctx = self._logger.llm_start(log_name, system_prompt, user_prompt)

        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature,
            )
            raw = resp.choices[0].message.content or ""
            result = _strip_thinking(raw)
            if not result.strip() and raw.strip():
                print(f"[LLM WARNING] _strip_thinking removed all content. Raw len={len(raw)}, first 200: {raw[:200]}")

            if log_ctx:
                self._logger.llm_end(log_ctx, result, self.model)  # type: ignore[union-attr]

            return result
        except Exception as e:
            if log_ctx and self._logger:
                self._logger.llm_error(log_ctx, e)
            raise

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[str]:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=True,
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


_instance: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _instance
    if _instance is None:
        _instance = LLMAdapter()
    return _instance
