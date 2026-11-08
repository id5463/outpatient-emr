import pytest

from app.core.contracts import Transcript
from app.record.model import OutpatientRecord, build_state
from app.record.render import FOOTER, render_markdown


def test_from_payload_keeps_known_fields():
    rec = OutpatientRecord.from_payload(
        {
            "chief_complaint": "腹痛三天",
            "present_illness": "上腹痛，饭后加重",
            "bogus_field": "应被丢弃",
            "vitals": {"temperature": "36.5℃", "unknown": "x"},
            "unclear_points": ["过敏史缺失"],
        }
    )
    assert rec.texts["chief_complaint"] == "腹痛三天"
    assert "bogus_field" not in rec.texts
    assert rec.vitals == {"temperature": "36.5℃"}
    assert rec.unclear_points == ["过敏史缺失"]


def test_from_payload_keeps_domain_texts():
    rec = OutpatientRecord.from_payload(
        {"pain_detail": "上腹偏右持续性钝痛，向背部放射"}, known_domain_names=("pain_detail",)
    )
    assert rec.domain_texts["pain_detail"].startswith("上腹偏右")


def test_from_payload_drops_unknown_domain_texts():
    rec = OutpatientRecord.from_payload(
        {"something_else": "x"}, known_domain_names=("pain_detail",)
    )
    assert rec.domain_texts == {}


def test_from_payload_coerces_non_string():
    rec = OutpatientRecord.from_payload({"chief_complaint": 123})
    assert rec.texts["chief_complaint"] == "123"


def test_missing_required():
    rec = OutpatientRecord.from_payload({"chief_complaint": "腹痛三天"})
    assert rec.missing_required(("chief_complaint",)) == []
    assert rec.missing_required(("chief_complaint", "present_illness")) == [
        "present_illness"
    ]


def test_merge_fill_never_overwrites_existing():
    rec = OutpatientRecord.from_payload({"chief_complaint": "腹痛三天"})
    changed = rec.merge_fill(
        {"chief_complaint": "应被忽略", "allergy_history": "青霉素过敏"}
    )
    assert changed == ["allergy_history"]
    assert rec.texts["chief_complaint"] == "腹痛三天"
    assert rec.texts["allergy_history"] == "青霉素过敏"


def test_merge_fill_fills_domain_detail():
    rec = OutpatientRecord()
    changed = rec.merge_fill({"pain_detail": "上腹钝痛"})
    assert changed == ["pain_detail"]
    assert rec.domain_texts["pain_detail"] == "上腹钝痛"


def test_merge_fill_ignores_empty():
    rec = OutpatientRecord()
    assert rec.merge_fill({"allergy_history": "", "family_history": None}) == []


def test_add_questions_dedupes():
    rec = OutpatientRecord()
    rec.add_questions(["问题一", "问题二", "问题一", "  "])
    assert rec.unclear_points == ["问题一", "问题二"]


def test_filled_merges_texts_and_domains():
    rec = OutpatientRecord(
        texts={"chief_complaint": "腹痛"},
        domain_texts={"pain_detail": "上腹钝痛"},
    )
    filled = rec.filled()
    assert filled["chief_complaint"] == "腹痛"
    assert filled["pain_detail"] == "上腹钝痛"


def test_render_contains_all_sections_in_order():
    rec = OutpatientRecord.from_payload(
        {
            "chief_complaint": "上腹痛一周",
            "physical_exam": "上腹压痛",
            "vitals": {"temperature": "36.8℃", "blood_pressure": "120/80mmHg"},
            "diagnosis": "慢性胃炎",
            "negatives": ["无反跳痛"],
        }
    )
    md = render_markdown(rec, department="消化内科", visited_at="2026-11-08 10:00")
    heads = [line for line in md.splitlines() if line.startswith("## ")]
    assert heads[:4] == ["## 一般项目", "## 现病史", "## 既往史", "## 过敏史"]
    assert "## 随访" in heads
    assert "## 信息缺口" in heads
    assert md.startswith("# 门诊病历")
    assert "生命体征：体温 36.8℃，血压 120/80mmHg" in md
    assert "有鉴别意义的阴性所见：无反跳痛" in md
    assert md.rstrip().endswith(FOOTER)


def test_render_includes_domain_texts_under_present_illness():
    rec = OutpatientRecord.from_payload(
        {
            "chief_complaint": "腹痛",
            "present_illness": "上腹痛三天",
            "pain_detail": "上腹偏右持续性钝痛，向背部放射",
        },
        known_domain_names=("pain_detail",),
    )
    md = render_markdown(rec, department="消化内科")
    assert "上腹偏右持续性钝痛，向背部放射" in md


def test_render_marks_absent_fields():
    md = render_markdown(OutpatientRecord())
    assert md.count("未记录") >= 8
    assert "## 信息缺口\n未发现" in md


def test_render_shows_certainty_when_uncertain():
    closed = {"has_fever": {"value": True, "p": 0.55, "certainty": 0.55,
                            "uncertain": True, "ranked": []}}
    from app.record.form import ClosedField

    fields = (ClosedField("has_fever", "发热", "confirm", "是否发热"),)
    md = render_markdown(OutpatientRecord(), closed=closed, closed_fields=fields)
    assert "把握" in md


def test_transcript_from_text_assigns_roles():
    tr = Transcript.from_text("医生：问题\n患者：回答\n家属：补充")
    labels = [s.speaker_label for s in tr.segments]
    assert labels == ["医生", "患者", "其他"]
    assert "医生：问题" in tr.text


def test_transcript_from_text_skips_blank_lines():
    tr = Transcript.from_text("\n医生：一\n\n\n患者：二\n")
    assert len(tr.segments) == 2


def test_build_state_includes_filled_and_transcript():
    rec = OutpatientRecord(texts={"chief_complaint": "腹痛"})
    state = build_state(rec, "医生：哪里不舒服？")
    assert "腹痛" in state and "问诊对话" in state
