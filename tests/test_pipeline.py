from pathlib import Path

import pytest

from app.pipeline.record_pipeline import RecordPipeline
from tests.fakes import (
    DictPrompts,
    FakeChat,
    FakeJudger,
    FakeTranscriber,
    InMemoryWriter,
)

OPEN_EXTRACT = {
    "chief_complaint": "上腹痛一周",
    "present_illness": "饭后加重，伴恶心",
    "department": "消化内科",
    "vitals": {"temperature": "36.8℃"},
    "unclear_points": ["过敏史缺失"],
}


def build(
    *,
    chat: FakeChat | None = None,
    judger: FakeJudger | None = None,
    transcriber: FakeTranscriber | None = None,
    writer: InMemoryWriter | None = None,
    budget_s: float = 300.0,
) -> tuple[RecordPipeline, dict]:
    parts = {
        "chat": chat or FakeChat(extract=OPEN_EXTRACT),
        "judger": judger or FakeJudger(),
        "transcriber": transcriber or FakeTranscriber(),
        "writer": writer or InMemoryWriter(),
    }
    pipeline = RecordPipeline(
        transcriber=parts["transcriber"],
        chat=parts["chat"],
        judger=parts["judger"],
        prompts=DictPrompts(),
        writer=parts["writer"],
        budget_s=budget_s,
    )
    return pipeline, parts


def test_run_from_text_produces_markdown():
    pipeline, parts = build()
    result = pipeline.run(transcript_text="医生：哪里不舒服？\n患者：上腹痛一周")
    assert "# 门诊病历" in result.markdown
    assert result.record.texts["chief_complaint"] == "上腹痛一周"
    assert parts["writer"].written


def test_run_from_audio_uses_transcriber():
    pipeline, parts = build()
    result = pipeline.run(audio_path=Path("/tmp/nonexistent.wav"))
    assert parts["transcriber"].calls == [Path("/tmp/nonexistent.wav")]
    assert result.transcript.backend == "fake"


def test_run_requires_input():
    pipeline, _ = build()
    with pytest.raises(ValueError):
        pipeline.run()


def test_closed_fields_keep_probability():
    pipeline, _ = build()
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    slot = result.closed.get("has_fever")
    assert slot is not None
    assert set(slot) >= {"value", "p", "certainty", "uncertain", "ranked"}
    # FakeJudger 的 noul 返回 0.8
    assert slot["p"] == pytest.approx(0.8, abs=1e-6)


def test_uncertain_fields_surface_as_warning():
    class ShakyJudger(FakeJudger):
        def decide(self, state, questions):
            from app.core.contracts import Decision, DecisionSet

            self.calls.append((state, questions))
            out = {}
            for name, q in questions.items():
                value = 0.55 if q["type"] == "noul" else (
                    "消化内科" if name == "department" else (
                        next(iter(q.get("criteria") or {}), 0) if q["type"] == "choice" else 0.0
                    )
                )
                out[name] = Decision(name=name, kind=q["type"], value=value)
            return DecisionSet(decisions=out, model=self.model)

    pipeline, _ = build(judger=ShakyJudger())
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    assert any("把握不足" in w for w in result.warnings)


def test_screening_hits_multiple_domains():
    pipeline, _ = build()
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    # FakeJudger 所有 noul 都是 0.8，故全部症状域命中
    assert len(result.hit_domains) > 3
    assert set(result.closed) >= {"urgency", "needs_exam"}


def test_open_fields_extracted_by_chat():
    pipeline, _ = build()
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    assert result.models_used["open"] == "fake-llm"
    assert result.record.texts["present_illness"]


def test_judge_receives_typed_questions():
    judger = FakeJudger()
    pipeline, _ = build(judger=judger)
    pipeline.run(transcript_text="患者：上腹痛", persist=False)
    batches = [q for _, q in judger.calls]
    screening = next(q for q in batches if "has_fever" in q)
    assert screening["has_fever"]["type"] == "noul"
    closed = next(q for q in batches if "urgency" in q and "needs_exam" in q)
    assert closed["urgency"]["type"] == "score"
    assert "criteria" in closed["urgency"]


def test_decision_failure_degrades_without_aborting():
    pipeline, _ = build(judger=FakeJudger(failing=True))
    result = pipeline.run(transcript_text="患者：上腹痛")
    assert result.models_used["screening"] == "unavailable"
    assert result.models_used["closed"] == "unavailable"
    assert any("症状筛查失败" in w for w in result.warnings)
    assert result.markdown


def test_completion_fills_empty_fields_only():
    chat = FakeChat(
        extract=OPEN_EXTRACT,
        completion={
            "fill": {"chief_complaint": "不该覆盖", "allergy_history": "青霉素"},
            "ask": ["最近体重有变化吗？"],
        },
    )
    pipeline, _ = build(chat=chat)
    result = pipeline.run(transcript_text="患者：上腹痛")
    assert result.record.texts["chief_complaint"] == "上腹痛一周"
    assert result.record.texts["allergy_history"] == "青霉素"
    assert "最近体重有变化吗？" in result.record.unclear_points


def test_open_extract_failure_degrades():
    class BrokenChat(FakeChat):
        def chat(self, system, user, **kw):
            if "chief_complaint" in system and "补全" not in system:
                raise RuntimeError("模型挂了")
            return super().chat(system, user, **kw)

    pipeline, _ = build(chat=BrokenChat(extract=OPEN_EXTRACT))
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    assert result.models_used["open"] == "unavailable"
    assert result.markdown


def test_persist_false_skips_writer():
    writer = InMemoryWriter()
    pipeline, parts = build(writer=writer)
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    assert not parts["writer"].written
    assert result.markdown_path is None


def test_payload_shape():
    pipeline, _ = build()
    result = pipeline.run(transcript_text="医生：问题\n患者：回答", persist=False)
    payload = result.to_payload()
    assert set(payload) >= {
        "transcript", "record", "closed", "markdown",
        "models_used", "hit_domains", "department", "elapsed_s",
    }
    assert payload["department"] == "消化内科"


def test_department_comes_from_open_field():
    pipeline, _ = build()
    result = pipeline.run(
        transcript_text="患者：上腹痛", visited_at="2026-11-08 09:00"
    )
    assert result.department == "消化内科"
    assert "就诊科室：消化内科" in result.markdown


def test_budget_exceeded_still_produces_markdown():
    pipeline, _ = build(budget_s=0.0)
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    assert result.markdown


def test_elapsed_recorded():
    pipeline, _ = build()
    result = pipeline.run(transcript_text="患者：上腹痛", persist=False)
    assert result.elapsed_s >= 0
    assert "elapsed_s" in result.to_payload()
