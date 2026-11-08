"""持久化。只管写盘，不含任何业务判断。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class FileRecordWriter:
    """把一次结果写成 .md + .json 一对文件。"""

    def __init__(self, directory: Path, *, prefix: str = "门诊病历") -> None:
        self.directory = Path(directory)
        self.prefix = prefix

    def write(self, payload: dict[str, Any], markdown: str) -> tuple[Path, Path]:
        self.directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self.prefix}-{_stamp()}"
        md_path = self.directory / f"{stem}.md"
        json_path = self.directory / f"{stem}.json"
        md_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return md_path, json_path


class NullRecordWriter:
    """不落盘。用于 Web 请求内只想返回结果时。"""

    def write(self, payload: dict[str, Any], markdown: str) -> tuple[Path, Path]:
        return Path(""), Path("")


def _stamp() -> str:
    now = datetime.now()
    base = now.strftime("%Y%m%d-%H%M%S")
    return base


def safe_filename(name: str) -> str:
    return re.sub(r"[^\w.\-]", "_", name)[:80]
