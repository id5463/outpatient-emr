"""各层共用的测试替身。全部实现 core.contracts 里的 Protocol。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.contracts import Decision, DecisionSet, LLMReply, Segment, Transcript


@dataclass
class FakeTranscriber:
    name: str = "fake"
    segments: list[Segment] = field(
        default_factory=lambda: [
            Segment("肚子痛三天", 0, 1800, 1),
            Segment("先查血常规", 1800, 3000, 0),
        ]
    )
    calls: list[Path] = field(default_factory=list)

    def available(self) -> bool:
        return True

    def transcribe(self, audio_path: Path, *, speakers: int = 2) -> Transcript:
        self.calls.append(audio_path)
        return Transcript(segments=list(self.segments), backend=self.name, model="fake")


@dataclass
class FakeChat:
    """按提示词内容返回预置响应，模拟不同步骤。"""

    extract: dict[str, Any] = field(default_factory=dict)
    completion: dict[str, Any] = field(default_factory=dict)
    fail_on: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)
    model: str = "fake-llm"

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> LLMReply:
        self.calls.append((system[:20], user[:40]))
        blob = system + user
        if "complete" in self.fail_on and self.is_completion(system):
            raise RuntimeError("补全模拟失败")

        if self.is_completion(system):
            return LLMReply(json.dumps(self.completion, ensure_ascii=False), self.model)
        return LLMReply(json.dumps(self.extract, ensure_ascii=False), self.model)

    @staticmethod
    def is_completion(system: str) -> bool:
        return "补全" in system

    @staticmethod
    def is_completion(system: str) -> bool:
        return "补全" in system or "fill" in system.lower()
        return LLMReply("{}", self.model)


@dataclass
class FakeJudger:
    failing: bool = False
    calls: list[tuple[str, dict]] = field(default_factory=list)
    model: str = "fake-judge"

    def decide(self, state: str, questions: dict[str, Any]) -> DecisionSet:
        self.calls.append((state, questions))
        if self.failing:
            raise RuntimeError("决策模拟失败")

        decisions: dict[str, Decision] = {}
        for name, q in questions.items():
            kind = q["type"]
            if kind == "noul":
                value: Any = 0.8
            elif kind == "choice":
                criteria = q.get("criteria") or {}
                # 科室题固定给一个合法值，其余取第一个键
                value = "消化内科" if name == "department" else next(
                    iter(criteria), "unclear"
                )
            else:
                value = 0.0
            decisions[name] = Decision(name=name, kind=kind, value=value)
        return DecisionSet(decisions=decisions, model=self.model)


@dataclass
class InMemoryWriter:
    written: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    fail: bool = False

    def write(self, payload: dict[str, Any], markdown: str) -> tuple[Path, Path]:
        if self.fail:
            raise OSError("写盘模拟失败")
        self.written.append((payload, markdown))
        return Path("/tmp/fake.md"), Path("/tmp/fake.json")


@dataclass
class DictPrompts:
    prompts: dict[str, str] = field(
        default_factory=lambda: {
            "extract_open": "填写叙述性字段 chief_complaint 与 present_illness 输出 JSON",
            "complete": "补全缺失条目 fill / ask / reason，输出 JSON",
        }
    )

    def get(self, name: str) -> str:
        return self.prompts[name]
