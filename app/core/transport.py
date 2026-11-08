"""无状态的 JSON 传输。重试与退避只在这里发生。"""

from __future__ import annotations

import json
import random
import time
from typing import Any

import httpx


class UpstreamError(RuntimeError):
    """上游不可用。retryable 表示「同一模型再试是否有意义」。"""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class JsonTransport:
    """薄封装。不持有业务状态，不认识模型名。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 120.0,
        max_retries: int = 4,
        retry_base_s: float = 1.5,
        proxy: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.retry_base_s = retry_base_s
        self.proxy = proxy or None
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout_s,
                proxy=self.proxy,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last: UpstreamError | None = None

        for attempt in range(self.max_retries):
            try:
                resp = self._get_client().post(url, json=payload)
            except httpx.HTTPError as exc:
                last = UpstreamError(f"网络错误: {exc}")
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except json.JSONDecodeError as exc:
                        raise UpstreamError(
                            f"响应不是 JSON: {exc}", retryable=False
                        ) from exc
                retryable = resp.status_code == 429 or resp.status_code >= 500
                last = UpstreamError(
                    _describe(resp), status=resp.status_code, retryable=retryable
                )
                if not retryable:
                    raise last

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_base_s * (2**attempt) + random.uniform(0, 0.4))

        raise last or UpstreamError("请求失败，原因未知")


def _describe(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return f"HTTP {resp.status_code}: {err.get('message', err)}"
    if isinstance(err, str):
        return f"HTTP {resp.status_code}: {err}"
    return f"HTTP {resp.status_code}: {json.dumps(body, ensure_ascii=False)[:300]}"
