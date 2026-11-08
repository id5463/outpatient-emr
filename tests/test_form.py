from app.record.form import (
    DOMAINS,
    DOMAIN_BY_KEY,
    UNIVERSAL_CLOSED,
    UNIVERSAL_OPEN,
    closed_fields_for,
    closed_questions,
    open_fields_for,
    open_schema,
    screening_fields,
)


def names(items):
    return [x.name for x in items]


def test_screening_covers_every_domain():
    screening = screening_fields()
    assert len(screening) == len(DOMAINS)
    assert all(f.kind == "confirm" for f in screening)
    assert all(f.name.startswith("has_") for f in screening)


def test_universal_closed_always_present():
    for hits in ((), ("fever",), ("pain", "fever", "skin")):
        got = names(closed_fields_for(hits))
        for required in (
            "urgency",
            "needs_exam",
            "needs_medication",
            "needs_followup",
            "needs_referral",
            "needs_emergency",
        ):
            assert required in got


def test_hit_domains_expand_their_fields():
    only = closed_fields_for(("fever",))
    assert "fever_level" in names(only)
    assert "pain_impact" not in names(only)


def test_multiple_domains_stack_cross_specialty():
    """发热 + 疼痛 + 皮肤：跨三个专科，字段全部展开。"""
    closed = names(closed_fields_for(("fever", "pain", "skin")))
    opened = names(open_fields_for(("fever", "pain", "skin")))
    assert "fever_level" in closed and "pain_impact" in closed
    assert "fever_detail" in opened
    assert "pain_detail" in opened
    assert "skin_detail" in opened


def test_department_is_open_field_not_closed():
    """科室值域开放：任何临床科室名都可以，不进封闭字段。"""
    assert "department" in names(UNIVERSAL_OPEN)
    assert "department" not in names(UNIVERSAL_CLOSED)
    assert "department" not in [d.screening.name for d in DOMAINS]


def test_open_schema_is_hints_not_options():
    """开放字段给的是写作指引，不是可选值列表。"""
    schema = open_schema(open_fields_for(()))
    assert isinstance(schema["pain_detail"] if "pain_detail" in schema else "", str)
    assert "现病史" in schema["present_illness"] or "起病" in schema["present_illness"]


def test_no_choice_type_anywhere_in_closed():
    """封闭字段只允许 scale 和 confirm，不再有硬编码的 choice 枚举。"""
    for f in UNIVERSAL_CLOSED:
        assert f.kind in ("scale", "confirm"), f.name
    for d in DOMAINS:
        for f in (d.screening,) + d.closed_details:
            assert f.kind in ("scale", "confirm"), f.name


def test_scale_fields_have_levels():
    for f in UNIVERSAL_CLOSED:
        if f.kind == "scale":
            assert f.levels and len(f.levels) >= 2, f.name


def test_unknown_domain_ignored():
    assert "fever_level" in names(closed_fields_for(("fever", "不存在")))


def test_no_duplicate_names():
    got = names(closed_fields_for(tuple(DOMAIN_BY_KEY))) + names(
        open_fields_for(tuple(DOMAIN_BY_KEY))
    )
    assert len(got) == len(set(got))


def test_questions_are_typed():
    q = closed_questions(closed_fields_for(("fever",)))
    assert q["has_fever"]["type"] == "noul"
    assert q["urgency"]["type"] == "score"
    assert "criteria" in q["urgency"]


def test_open_fields_have_hints():
    for f in UNIVERSAL_OPEN:
        assert f.hint.strip(), f.name
    for d in DOMAINS:
        for f in d.open_details:
            assert f.hint.strip(), f.name
