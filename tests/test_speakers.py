from app.asr.speakers import (
    ROLE_DOCTOR,
    ROLE_PATIENT,
    apply_roles,
    build_role_questions,
    fallback_by_markers,
    separation_quality,
    speaker_texts,
)
from app.core.contracts import Decision, DecisionSet, Segment, Transcript


def tr(*items):
    """items: (text, speaker_id)"""
    return Transcript(
        segments=[
            Segment(t, i * 1000, (i + 1) * 1000, sid)
            for i, (t, sid) in enumerate(items)
        ],
        backend="bailian",
        model="fun-asr",
    )


def decisions(mapping: dict[str, str]) -> DecisionSet:
    return DecisionSet(
        decisions={
            f"speaker_{sid}": Decision(name=f"speaker_{sid}", kind="choice", value=role)
            for sid, role in mapping.items()
        },
        model="typesafe/jev",
    )


def test_speaker_texts_groups_by_id():
    t = tr(("问一", 0), ("答一", 1), ("问二", 0))
    texts = speaker_texts(t)
    assert set(texts) == {0, 1}
    assert "问一" in texts[0] and "问二" in texts[0]
    assert texts[1] == "答一"


def test_speaker_texts_limits_per_speaker():
    t = tr(*[(f"句{i}", 0) for i in range(10)])
    assert speaker_texts(t, per_speaker=3)[0].count("\n") == 2


def test_build_role_questions_one_per_speaker():
    q = build_role_questions([0, 1])
    assert set(q) == {"speaker_0", "speaker_1"}
    assert q["speaker_0"]["type"] == "choice"
    assert set(q["speaker_0"]["criteria"]) == {ROLE_DOCTOR, ROLE_PATIENT, "other"}


def test_role_question_text_has_no_roleplay():
    q = build_role_questions([0])
    text = q["speaker_0"]["instructions"]
    for banned in ("你是", "扮演", "假设你"):
        assert banned not in text


def test_apply_roles_writes_role_and_returns_mapping():
    t = tr(("问", 0), ("答", 1))
    out, mapping = apply_roles(t, decisions({"0": ROLE_DOCTOR, "1": ROLE_PATIENT}))
    assert [s.role for s in out.segments] == [ROLE_DOCTOR, ROLE_PATIENT]
    assert [s.speaker_label for s in out.segments] == ["医生", "患者"]
    assert mapping == {ROLE_DOCTOR: 0, ROLE_PATIENT: 1}


def test_apply_roles_refuses_when_only_one_role():
    t = tr(("问", 0), ("答", 1))
    out, mapping = apply_roles(t, decisions({"0": ROLE_DOCTOR, "1": ROLE_DOCTOR}))
    assert mapping == {}
    assert all(s.role == "" for s in out.segments)


def test_apply_roles_keeps_acoustic_id():
    t = tr(("问", 0), ("答", 1))
    out, _ = apply_roles(t, decisions({"0": ROLE_DOCTOR, "1": ROLE_PATIENT}))
    assert [s.speaker for s in out.segments] == [0, 1]


def test_separation_quality_detects_single_speaker():
    q = separation_quality(tr(("a", 0), ("b", 0), ("c", 0)))
    assert q["degraded"] is True
    assert q["speaker_count"] == 1


def test_separation_quality_ok_with_two():
    q = separation_quality(tr(("a", 0), ("b", 1), ("c", 0), ("d", 1)))
    assert q["degraded"] is False


def test_fallback_splits_by_marker():
    t = tr(("患者：我肚子痛", 0), ("医生：痛多久了", 0), ("大概一周", 0))
    out = fallback_by_markers(t)
    labels = [s.speaker_label for s in out.segments]
    assert labels[0] == "患者"
    assert labels[1] == "医生"


def test_fallback_keeps_current_role_for_unmarked_lines():
    t = tr(("医生：痛多久了", 0), ("大概一周", 0))
    out = fallback_by_markers(t)
    assert out.segments[-1].speaker_label == "医生"


def test_fallback_strips_leading_marker_only():
    """句首的角色词是标注，句中出现的不是。"""
    t = tr(("医生说要注意饮食", 0))
    out = fallback_by_markers(t)
    assert len(out.segments) == 1
    assert "要注意饮食" in out.segments[0].text
    assert out.segments[0].role == "doctor"


def test_fallback_drops_noise():
    t = tr(("%", 0), ("24", 0), ("我肚子痛", 0))
    out = fallback_by_markers(t)
    assert len(out.segments) == 1
