"""提示词守卫测试。

两条硬约束：
  1. 提示词文件里不允许出现角色扮演式表述
  2. 生产代码里不允许内嵌提示词正文（只能从文件读）
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
APP_DIR = Path(__file__).resolve().parents[1] / "app"

# 角色扮演式的典型句式
FORBIDDEN_PATTERNS = [
    r"你是[一 ]?[个名位]",
    r"你是一[个名位]",
    r"扮演",
    r"假设你是",
    r"作为一[个名位]医生",
    r"你将作为",
    r"pretend you are",
    r"you are a doctor",
    r"act as an?",
    r"role[- ]playing",
    r"roleplay",
]

MIN_PROMPT_CHARS = 120


def _prompt_files() -> list[Path]:
    return sorted(PROMPTS_DIR.glob("*.md"))


def test_prompt_files_exist():
    names = {p.stem for p in _prompt_files()}
    assert {"extract_open", "complete"} <= names


@pytest.mark.parametrize("path", _prompt_files(), ids=lambda p: p.name)
def test_no_roleplay_phrasing(path: Path):
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    hits = [
        pat for pat in FORBIDDEN_PATTERNS if re.search(pat, lowered, re.IGNORECASE)
    ]
    assert not hits, f"{path.name} 含角色扮演句式: {hits}"


@pytest.mark.parametrize("path", _prompt_files(), ids=lambda p: p.name)
def test_prompts_are_substantive(path: Path):
    text = path.read_text(encoding="utf-8")
    assert len(text) >= MIN_PROMPT_CHARS, f"{path.name} 过短，可能没写清楚任务"


def test_structured_prompts_request_json():
    """要求结构化输出的提示词必须明确写出 JSON。"""
    for name in ("extract_open", "complete"):
        text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert "JSON" in text, f"{name}.md 应明确要求 JSON 输出"


def test_no_prompt_text_embedded_in_code():
    """app/ 下不应出现提示词文件的正文片段。

    判据：从每份提示词里取若干 120 字符的滑窗片段，
    若某个片段原样出现在 .py 源码中，说明提示词被抄进了代码。
    """
    sources = {
        p.name: p.read_text(encoding="utf-8") for p in APP_DIR.rglob("*.py")
    }
    window = 120
    hits: list[str] = []

    for prompt_path in _prompt_files():
        text = re.sub(r"\s+", " ", prompt_path.read_text(encoding="utf-8"))
        for i in range(0, max(0, len(text) - window), window // 2):
            chunk = text[i : i + window].strip()
            if len(chunk) < window - 10:
                continue
            for name, source in sources.items():
                if chunk in re.sub(r"\s+", " ", source):
                    hits.append(f"{prompt_path.name} -> {name}")

    assert not hits, "提示词正文不应内嵌在代码里：" + "; ".join(sorted(set(hits)))


def test_prompt_source_reads_only_from_files(tmp_path: Path):
    from app.llm.prompts import FilePromptSource, PromptNotFound

    (tmp_path / "a.md").write_text("内容", encoding="utf-8")
    src = FilePromptSource(tmp_path)
    assert src.get("a") == "内容"
    assert src.names() == ["a"]
    with pytest.raises(PromptNotFound):
        src.get("missing")
