"""提示词来源。生产实现只认磁盘上的文件。

提示词属于可编辑的运营内容，放代码里会让改一句提示词变成一次发版，
也会让不同环境没法用不同提示词。所以这里只提供文件实现。
"""

from __future__ import annotations

from pathlib import Path


class PromptNotFound(FileNotFoundError):
    pass


class FilePromptSource:
    """从目录读取 <name>.md，按 mtime 缓存。"""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._cache: dict[str, tuple[float, str]] = {}

    def get(self, name: str) -> str:
        path = self.directory / f"{name}.md"
        if not path.is_file():
            raise PromptNotFound(f"提示词不存在: {path}")
        mtime = path.stat().st_mtime
        cached = self._cache.get(name)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        text = path.read_text(encoding="utf-8")
        self._cache[name] = (mtime, text)
        return text

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.md"))
