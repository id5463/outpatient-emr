"""说话人角色判定。

分工：
  ASR      负责「把声音分成几路」（speaker_id），这是声学问题
  决策模型  负责「每一路是医生还是患者」，这是语义问题

只有在声学分离不可用（所有句子都落在同一个 speaker_id）时，
才退回按对话里的「医生：」「患者：」标注做兜底切分。
"""

from __future__ import annotations

import re
from typing import Any

from ..core.contracts import DecisionSet, Segment, Transcript

ROLE_DOCTOR = "doctor"
ROLE_PATIENT = "patient"
ROLE_OTHER = "other"

ROLE_LABELS = {ROLE_DOCTOR: "医生", ROLE_PATIENT: "患者", ROLE_OTHER: "其他"}

_MARKER_RE = re.compile(r"^(患者|病人|患方|家属|医生|医师)\s*[:：]?\s*")
_MARKER_ROLE = {"患者": 1, "病人": 1, "患方": 1, "家属": 2, "医生": 0, "医师": 0}
_NOISE_RE = re.compile(r"^[\d%．.\s]+|[%％]+$")
# 只剩角色词和标点的片段，没有信息量
_BARE_MARKER_RE = re.compile(
    r"^(患者|病人|患方|家属|医生|医师)[\s。．.、,，:：]*$"
)


def speaker_texts(transcript: Transcript, *, per_speaker: int = 6) -> dict[int, str]:
    """每个 speaker 抽取若干代表性句子，作为判断角色的材料。"""
    buckets: dict[int, list[str]] = {}
    for seg in transcript.segments:
        buckets.setdefault(seg.speaker, []).append(seg.text)
    return {
        sid: "\n".join(texts[:per_speaker]) for sid, texts in sorted(buckets.items())
    }


def build_role_questions(speaker_ids: list[int]) -> dict[str, Any]:
    """为每个 speaker 生成一个 choice 题。选项文字只描述话语特征，不描述身份设定。"""
    questions: dict[str, Any] = {}
    for sid in speaker_ids:
        questions[f"speaker_{sid}"] = {
            "type": "choice",
            "instructions": (
                f"对话中标记为「说话人{sid}」的这一方，"
                "其话语更符合下面哪一种？"
            ),
            "criteria": {
                ROLE_DOCTOR: "询问症状、追问病史、给出检查或处置、解释病情",
                ROLE_PATIENT: "陈述自身不适、回答提问、描述感受与经历",
                ROLE_OTHER: "陪同者插话，或无法判断",
            },
        }
    return questions


def apply_roles(
    transcript: Transcript, decisions: DecisionSet
) -> tuple[Transcript, dict[str, int]]:
    """把 speaker_id 映射成医生/患者，写回片段。

    返回 (新转写, {角色: speaker_id})。
    判断失败时保留原 speaker，不臆造。
    """
    mapping: dict[int, str] = {}
    for name, decision in decisions.decisions.items():
        if not name.startswith("speaker_"):
            continue
        sid = int(name.split("_", 1)[1])
        role = str(decision.value or ROLE_OTHER)
        if role in ROLE_LABELS:
            mapping[sid] = role

    # 至少要有医生和患者各一方，否则说明分离没起作用
    if ROLE_DOCTOR not in mapping.values() or ROLE_PATIENT not in mapping.values():
        return transcript, {}

    segments = [
        Segment(
            text=seg.text,
            begin_ms=seg.begin_ms,
            end_ms=seg.end_ms,
            speaker=seg.speaker,
            role=mapping.get(seg.speaker, ROLE_OTHER),
        )
        for seg in transcript.segments
    ]
    role_to_speaker = {role: sid for sid, role in mapping.items()}
    return (
        Transcript(segments=segments, backend=transcript.backend, model=transcript.model),
        role_to_speaker,
    )


def fallback_by_markers(transcript: Transcript) -> Transcript:
    """声学分离失效时，按对话里的角色标注切分。

    只在同一人配音这类场景使用，且必须保留原始标注信息。
    """
    segments: list[Segment] = []
    current: str | None = None

    for seg in transcript.segments:
        text = _NOISE_RE.sub("", seg.text or "").strip()
        if not text:
            continue

        marker = _MARKER_RE.match(text)
        if marker:
            current = _role_name(marker.group(1))
            text = text[marker.end() :].strip()
        if not text or _BARE_MARKER_RE.match(text):
            continue

        # 一句话里可能夹着下一方的标注
        pieces = _split_inline(text)
        for role, chunk in pieces:
            chunk = chunk.strip()
            if role:
                current = role
            if not chunk or _BARE_MARKER_RE.match(chunk):
                continue
            segments.append(
                Segment(
                    text=chunk,
                    begin_ms=seg.begin_ms,
                    end_ms=seg.end_ms,
                    speaker=seg.speaker,
                    role=role or current or ROLE_OTHER,
                )
            )

    return Transcript(
        segments=segments, backend=transcript.backend, model=transcript.model
    )


def _role_name(marker: str) -> str:
    if marker in ("医生", "医师"):
        return ROLE_DOCTOR
    if marker == "家属":
        return ROLE_OTHER
    return ROLE_PATIENT


def _split_inline(text: str) -> list[tuple[str | None, str]]:
    """按句中出现的「患者：」「医生：」切分。只认带冒号的写法，避免误伤正文。"""
    pattern = re.compile(r"(患者|病人|患方|家属|医生|医师)\s*[:：]")
    matches = list(pattern.finditer(text))
    if not matches:
        return [(None, text)]

    out: list[tuple[str | None, str]] = []
    head = text[: matches[0].start()].strip()
    if head:
        out.append((None, head))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((_role_name(m.group(1)), text[m.end() : end]))
    return out


def separation_quality(transcript: Transcript) -> dict[str, Any]:
    """判断声学分离是否真的生效。"""
    counts: dict[int, int] = {}
    for seg in transcript.segments:
        counts[seg.speaker] = counts.get(seg.speaker, 0) + 1
    total = sum(counts.values()) or 1
    dominant = max(counts.values()) if counts else 0
    return {
        "speaker_count": len(counts),
        "counts": counts,
        "dominant_ratio": round(dominant / total, 3),
        "degraded": len(counts) < 2 or dominant / total > 0.9,
    }
