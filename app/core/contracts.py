"""跨层共享的数据结构，以及各层之间的契约（Protocol）。

依赖方向只有一条：接口层 -> 编排层 -> 各能力层 -> core
core 不认识任何能力层，能力层之间互不 import。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ---- 数据 ----------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """一句转写结果。"""

    text: str
    begin_ms: int
    end_ms: int
    speaker: int = 0
    role: str = ""

    @property
    def speaker_label(self) -> str:
        """优先用语义角色，没有就退回声学编号。"""
        if self.role:
            return ROLE_LABELS.get(self.role, self.role)
        return SPEAKER_LABELS.get(self.speaker, f"说话人{self.speaker}")


# 声学分轨的中性称呼。角色由决策模型判定后填入 Segment.role
SPEAKER_LABELS = {0: "说话人0", 1: "说话人1", 2: "说话人2", 3: "说话人3"}
ROLE_LABELS = {"doctor": "医生", "patient": "患者", "other": "其他"}


@dataclass
class Transcript:
    """一次转写的完整结果。"""

    segments: list[Segment] = field(default_factory=list)
    backend: str = ""
    model: str = ""

    @property
    def text(self) -> str:
        """带说话人前缀的整段对话。"""
        return "\n".join(f"{s.speaker_label}：{s.text}" for s in self.segments)

    @classmethod
    def from_text(cls, text: str, *, backend: str = "text") -> "Transcript":
        """从「角色：内容」格式的纯文本构造。供直接粘贴对话时使用。"""
        segments: list[Segment] = []
        cursor = 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            speaker = 0
            role = ""
            head, sep, body = line.partition("：")
            if sep and len(head) <= 4:
                body = body.strip()
                if any(k in head for k in ("患者", "病人", "患方")):
                    speaker, role = 1, "patient"
                elif "家属" in head:
                    speaker, role = 2, "other"
                elif any(k in head for k in ("医生", "医师")):
                    speaker, role = 0, "doctor"
                line = body
            if not line:
                continue
            dur = max(1000, len(line) * 180)
            segments.append(
                Segment(
                    text=line,
                    begin_ms=cursor,
                    end_ms=cursor + dur,
                    speaker=speaker,
                    role=role,
                )
            )
            cursor += dur
        return cls(segments=segments, backend=backend, model="inline")


@dataclass(frozen=True)
class LLMReply:
    """大模型的一次文本回复。"""

    content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """决策模型对单个问题的完整判断。

    概率分布本身是信息：0.51 的「是」和 0.98 的「是」含义完全不同，
    所以三种题型都保留原始概率，不压缩成一个布尔或一个枚举。
    """

    name: str
    kind: str
    value: Any
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    legend: dict[str, str] = field(default_factory=dict)
    # 原始返回，兜底用，避免任何字段被解析逻辑吃掉
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- 派生视图 ---------------------------------------------

    @property
    def label(self) -> str:
        if self.kind == "score":
            try:
                return self.legend.get(
                    str(int(round(float(self.value)))), str(self.value)
                )
            except (TypeError, ValueError):
                return str(self.value)
        if self.kind == "noul":
            try:
                return "是" if float(self.value) >= 0.5 else "否"
            except (TypeError, ValueError):
                return str(self.value)
        return str(self.value)

    @property
    def certainty(self) -> float:
        """最可能选项的概率。0.5 表示接近抛硬币。"""
        if self.probabilities:
            return round(max(self.probabilities.values()), 4)
        if self.confidence is not None:
            return round(float(self.confidence), 4)
        try:
            p = float(self.value)
            # noul 的 value 本身就是概率
            return round(max(p, 1 - p), 4)
        except (TypeError, ValueError):
            return 0.0

    @property
    def is_uncertain(self) -> bool:
        """把握不足，适合在结果里标出来提示人工复核。"""
        return self.certainty < 0.7

    @property
    def ranked(self) -> list[tuple[str, float]]:
        """按概率降序的候选，带可读标签。

        noul 题往往只给一个概率值（表示「是」的概率），
        此时补出互补的「否」，让分布始终是完整的。
        """
        dist = dict(self.probabilities)
        if not dist and self.kind == "noul":
            try:
                p_yes = float(self.value)
            except (TypeError, ValueError):
                return []
            dist = {"是": round(p_yes, 4), "否": round(1 - p_yes, 4)}
            return sorted(dist.items(), key=lambda x: -x[1])

        def name_of(key: str) -> str:
            if key in self.legend:
                return self.legend[key]
            return {"0": "否", "1": "是"}.get(key, key)

        return sorted(
            ((name_of(k), round(v, 4)) for k, v in dist.items()),
            key=lambda x: -x[1],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "value": self.value,
            "label": self.label,
            "confidence": self.confidence,
            "certainty": self.certainty,
            "uncertain": self.is_uncertain,
            "probabilities": dict(self.probabilities),
            "ranked": self.ranked,
            "legend": dict(self.legend),
            "raw": dict(self.raw),
        }


@dataclass(frozen=True)
class DecisionSet:
    """一次决策调用的全部答案。"""

    decisions: dict[str, Decision]
    model: str
    usage: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, name: str) -> Decision:
        return self.decisions[name]

    def as_dict(self) -> dict[str, Any]:
        return {k: v.as_dict() for k, v in self.decisions.items()}


# ---- 契约 ----------------------------------------------------------


@runtime_checkable
class Transcriber(Protocol):
    """音频 -> Transcript。"""

    name: str

    def available(self) -> bool: ...

    def transcribe(self, audio_path: Path, *, speakers: int) -> Transcript: ...


@runtime_checkable
class ChatModel(Protocol):
    """提示词 -> 文本。实现方不需要知道提示词从哪来、内容是什么。"""

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> LLMReply: ...


@runtime_checkable
class Judger(Protocol):
    """state + 带类型的问题 -> 概率化判断。"""

    def decide(self, state: str, questions: dict[str, Any]) -> DecisionSet: ...


@runtime_checkable
class PromptSource(Protocol):
    """按名字取提示词正文。"""

    def get(self, name: str) -> str: ...


@runtime_checkable
class RecordWriter(Protocol):
    """把一份生成结果持久化，返回落盘路径。"""

    def write(self, payload: dict[str, Any], markdown: str) -> tuple[Path, Path]: ...
