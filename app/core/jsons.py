"""从模型输出里抠出 JSON。纯函数，无依赖。"""

from __future__ import annotations

import json
import re
from typing import Any


class JsonParseError(ValueError):
    pass


def parse_json(text: str) -> Any:
    """处理模型常见的三种脏输出：围栏包裹、前缀说明、首尾空行。"""
    if not text or not text.strip():
        raise JsonParseError("模型返回空内容")

    s = text.strip()

    fence = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", s, re.S)
    if fence:
        s = fence.group(1).strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = s.find(open_ch), s.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise JsonParseError(f"无法解析为 JSON：{text[:200]}")


def parse_object(text: str) -> dict[str, Any]:
    """要求顶层必须是对象。"""
    data = parse_json(text)
    if not isinstance(data, dict):
        raise JsonParseError(f"期望 JSON 对象，实际是 {type(data).__name__}")
    return data
