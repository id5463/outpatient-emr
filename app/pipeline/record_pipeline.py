"""编排层。只串联，不实现能力，也不落盘。

三个阶段的依据是字段的域性质，不是科室：

  1. 症状筛查   jev 判断哪些症状域出现（可多个，跨专科）
  2. 封闭字段   jev 填值域有限的字段，保留概率
  3. 开放字段   语言模型写值域开放的内容

依赖全部通过构造函数注入，且都是 Protocol。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..asr.speakers import (
    apply_roles,
    build_role_questions,
    fallback_by_markers,
    separation_quality,
    speaker_texts,
)
from ..core.contracts import (
    ChatModel,
    Judger,
    PromptSource,
    RecordWriter,
    Transcriber,
    Transcript,
)
from ..core.jsons import JsonParseError, parse_object
from ..record.form import (
    DOMAIN_BY_KEY,
    DOMAINS,
    closed_fields_for,
    closed_questions,
    open_fields_for,
    open_schema,
    screening_fields,
)
from ..record.formfill import (
    confirmed,
    hit_domains_from_closed,
    to_closed,
    uncertain_fields,
)
from ..record.model import OutpatientRecord, build_state
from ..record.render import render_markdown


class BudgetExceeded(RuntimeError):
    pass


def _require_budget(started: float, budget_s: float, step: str) -> None:
    used = time.monotonic() - started
    if used >= budget_s:
        raise BudgetExceeded(f"{step} 前已用 {used:.1f}s，超出 {budget_s:.0f}s 预算")


@dataclass
class PipelineResult:
    transcript: Transcript
    record: OutpatientRecord
    closed: dict[str, Any]
    markdown: str
    hit_domains: tuple[str, ...] = ()
    department: str = ""
    decisions: dict[str, Any] = field(default_factory=dict)
    models_used: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    files: dict[str, str] = field(default_factory=dict)
    markdown_path: Path | None = None
    json_path: Path | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "transcript": {
                "backend": self.transcript.backend,
                "model": self.transcript.model,
                "text": self.transcript.text,
                "segments": [
                    {
                        "text": s.text,
                        "begin_ms": s.begin_ms,
                        "end_ms": s.end_ms,
                        "speaker": s.speaker_label,
                        "role": s.role,
                    }
                    for s in self.transcript.segments
                ],
            },
            "record": self.record.to_payload(),
            "closed": self.closed,
            "department": self.department,
            "hit_domains": list(self.hit_domains),
            "decisions": self.decisions,
            "markdown": self.markdown,
            "models_used": self.models_used,
            "warnings": self.warnings,
            "elapsed_s": round(self.elapsed_s, 2),
            "files": dict(self.files),
        }


class RecordPipeline:
    def __init__(
        self,
        *,
        transcriber: Transcriber,
        chat: ChatModel,
        judger: Judger,
        prompts: PromptSource,
        writer: RecordWriter,
        speakers: int = 2,
        llm_temperature: float = 0.0,
        llm_max_tokens: int = 8192,
        budget_s: float = 300.0,
    ) -> None:
        self.transcriber = transcriber
        self.chat = chat
        self.judger = judger
        self.prompts = prompts
        self.writer = writer
        self.speakers = speakers
        self.llm_temperature = llm_temperature
        self.llm_max_tokens = llm_max_tokens
        self.budget_s = budget_s

    # ---- 步骤 ---------------------------------------------------

    def transcribe(self, audio_path: Path) -> Transcript:
        return self.transcriber.transcribe(audio_path, speakers=self.speakers)

    def assign_roles(self, transcript: Transcript) -> tuple[Transcript, dict[str, str]]:
        """ASR 分音轨，决策模型判角色；分离失效时退回标注。"""
        if separation_quality(transcript)["degraded"]:
            fallback = fallback_by_markers(transcript)
            has_roles = len({s.role for s in fallback.segments if s.role}) >= 2
            return fallback, {
                "model": "marker-fallback" if has_roles else "",
                "warning": (
                    "声学分轨未分开（可能同一人配音），已按对话中的角色标注切分，需人工核对。"
                    if has_roles
                    else "声学分轨未分开，且对话无角色标注，说话人标签可能不准。"
                ),
            }

        texts = speaker_texts(transcript)
        try:
            decisions = self.judger.decide(
                "\n\n".join(f"说话人{sid}：\n{t}" for sid, t in texts.items()),
                build_role_questions(sorted(texts)),
            )
        except Exception as exc:  # noqa: BLE001
            return transcript, {
                "model": "unavailable",
                "warning": f"说话人角色判定失败：{exc}",
            }

        transcript, mapping = apply_roles(transcript, decisions)
        if mapping:
            return transcript, {"model": decisions.model, "warning": ""}

        fallback = fallback_by_markers(transcript)
        if len({s.role for s in fallback.segments if s.role}) >= 2:
            return fallback, {
                "model": f"{decisions.model}+marker",
                "warning": "决策模型未能区分医患双方，已按对话中的角色标注切分。",
            }
        return transcript, {
            "model": decisions.model,
            "warning": "未能区分医患双方，保留声学标签。",
        }

    def screen(self, transcript: Transcript) -> tuple[list[str], dict[str, Any], str]:
        """阶段一：哪些症状域出现了。可多个同时命中。"""
        fields = screening_fields()
        decisions = self.judger.decide(transcript.text, closed_questions(fields))
        closed = to_closed(decisions, fields)
        mapping = {f.name: d.key for f, d in zip(fields, DOMAINS)}
        return hit_domains_from_closed(closed, mapping), closed, decisions.model

    def fill_closed(
        self,
        transcript: Transcript,
        hit_domains: list[str],
        known: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple, str]:
        """阶段二：值域有限的字段。保留完整概率分布。"""
        fields = closed_fields_for(tuple(hit_domains))
        state = _state(transcript.text, known)
        decisions = self.judger.decide(state, closed_questions(fields))
        merged = dict(known)
        merged.update(to_closed(decisions, fields))
        return merged, fields, decisions.model

    def fill_open(
        self, transcript: Transcript, hit_domains: list[str]
    ) -> tuple[OutpatientRecord, tuple, str]:
        """阶段三：值域开放的字段，交给语言模型自由书写。"""
        fields = open_fields_for(tuple(hit_domains))
        schema = open_schema(fields)
        system = (
            self.prompts.get("extract_open")
            + "\n\n本次需要填写的字段与写作要求：\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
        )
        reply = self.chat.chat(
            system,
            transcript.text,
            json_mode=True,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
        )
        payload = parse_object(reply.content)
        record = OutpatientRecord.from_payload(
            payload, known_domain_names=tuple(schema)
        )
        return record, fields, reply.model

    def complete(
        self, record: OutpatientRecord, transcript: Transcript
    ) -> tuple[dict[str, Any], str]:
        user = (
            "已填写内容：\n"
            + json.dumps(record.filled(), ensure_ascii=False, indent=2)
            + "\n\n问诊对话：\n"
            + transcript.text
        )
        reply = self.chat.chat(
            self.prompts.get("complete"),
            user,
            json_mode=True,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
        )
        try:
            return parse_object(reply.content), reply.model
        except JsonParseError:
            return {}, reply.model

    # ---- 全流程 -------------------------------------------------

    def run(
        self,
        *,
        audio_path: Path | None = None,
        transcript_text: str | None = None,
        visited_at: str | None = None,
        persist: bool = True,
    ) -> PipelineResult:
        if not audio_path and not transcript_text:
            raise ValueError("audio_path 与 transcript_text 至少提供一个")

        started = time.monotonic()
        warnings: list[str] = []
        models: dict[str, str] = {}

        if transcript_text:
            transcript = Transcript.from_text(transcript_text)
            models["asr"] = f"{transcript.backend}:{transcript.model}"
        else:
            transcript = self.transcribe(audio_path)  # type: ignore[arg-type]
            models["asr"] = f"{transcript.backend}:{transcript.model}"
            transcript, note = self.assign_roles(transcript)
            models["role"] = note.get("model", "")
            if note.get("warning"):
                warnings.append(note["warning"])

        # 阶段一
        closed: dict[str, Any] = {}
        hit_domains: list[str] = []
        closed_fields: tuple = ()
        try:
            _require_budget(started, self.budget_s, "症状筛查")
            hit_domains, closed, model = self.screen(transcript)
            models["screening"] = model
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"症状筛查失败，改用全部症状域：{exc}")
            hit_domains = [d.key for d in DOMAINS]
            models["screening"] = "unavailable"

        # 阶段二
        try:
            _require_budget(started, self.budget_s, "封闭字段")
            closed, closed_fields, model = self.fill_closed(
                transcript, hit_domains, closed
            )
            models["closed"] = model
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"封闭字段填写失败：{exc}")
            closed_fields = closed_fields_for(tuple(hit_domains))
            models["closed"] = "unavailable"

        # 阶段三
        open_fields: tuple = ()
        try:
            _require_budget(started, self.budget_s, "开放字段")
            record, open_fields, model = self.fill_open(transcript, hit_domains)
            models["open"] = model
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"开放字段抽取失败：{exc}")
            record = OutpatientRecord()
            open_fields = open_fields_for(tuple(hit_domains))
            models["open"] = "unavailable"

        # 补全空缺
        try:
            _require_budget(started, self.budget_s, "字段补全")
            completion, model = self.complete(record, transcript)
            models["complete"] = model
            changed = record.merge_fill(completion.get("fill") or {})
            record.add_questions(completion.get("ask") or [])
            if changed:
                warnings.append("以下字段由补全步骤填充：" + "、".join(changed))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"补全步骤失败：{exc}")
            models["complete"] = "unavailable"

        weak = uncertain_fields(closed, closed_fields)
        if weak:
            warnings.append("以下字段把握不足，建议人工确认：" + "、".join(weak))

        department = record.texts.get("department") or ""
        markdown = render_markdown(
            record,
            department=department,
            visited_at=visited_at,
            closed=closed,
            closed_fields=closed_fields,
            open_fields=open_fields,
        )
        models["render"] = "local"

        elapsed = time.monotonic() - started
        if elapsed > self.budget_s:
            warnings.append(f"总耗时 {elapsed:.1f}s 超出 {self.budget_s:.0f}s 预算")

        result = PipelineResult(
            transcript=transcript,
            record=record,
            closed=closed,
            markdown=markdown,
            hit_domains=tuple(hit_domains),
            department=department,
            decisions={
                k: v
                for k, v in closed.items()
                if isinstance(v, dict) and "certainty" in v
            },
            models_used=models,
            warnings=warnings,
            elapsed_s=elapsed,
        )

        if persist:
            md_path, json_path = self.writer.write(result.to_payload(), result.markdown)
            result.markdown_path = md_path if str(md_path) else None
            result.json_path = json_path if str(json_path) else None
            result.files = {
                "markdown": str(md_path) if str(md_path) else "",
                "json": str(json_path) if str(json_path) else "",
            }
        return result


def _state(transcript_text: str, known: dict[str, Any]) -> str:
    parts = []
    if known:
        parts.append("已判定的封闭字段：\n" + json.dumps(known, ensure_ascii=False, indent=2))
    parts.append("问诊对话：\n" + transcript_text)
    return "\n\n".join(parts)
