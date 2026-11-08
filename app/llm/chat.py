"""大语言模型层。

只做一件事：把 messages 发给模型并拿回文本。不认识病历，不读文件，
不持有「上次用了哪个模型」这类跨请求状态。
"""

from __future__ import annotations

from typing import Any

from ..core.contracts import LLMReply
from ..core.transport import JsonTransport, UpstreamError


class ModelChainError(RuntimeError):
    """候选链全部失败。"""


class QwenChat:
    """OpenAI 兼容 chat/completions。按候选链依次尝试。"""

    PATH = "chat/completions"

    def __init__(self, transport: JsonTransport, models: tuple[str, ...]) -> None:
        if not models:
            raise ValueError("models 不能为空")
        self.transport = transport
        self.models = models

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> LLMReply:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        errors: list[str] = []

        for model in self.models:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                data = self.transport.post(self.PATH, payload)
            except UpstreamError as exc:
                errors.append(f"{model}: {exc}")
                continue

            choice0 = (data.get("choices") or [{}])[0]
            content = _first_content(data)
            finish = choice0.get("finish_reason")
            if not content:
                # 思考 token 吃满 max_tokens 时正文会是空的
                reason = "内容被截断(finish_reason=length)" if finish == "length" else "响应缺少正文"
                errors.append(f"{model}: {reason}")
                continue

            return LLMReply(
                content=content, model=model, usage=data.get("usage") or {}
            )

        raise ModelChainError("候选模型全部不可用 -> " + " | ".join(errors))


def _first_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if not choices:
        return None
    content = (choices[0].get("message") or {}).get("content")
    return content if isinstance(content, str) else None
