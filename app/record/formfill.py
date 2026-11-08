"""把决策模型的答案落成表单值，并保留概率信息。纯函数。"""

from __future__ import annotations

from typing import Any

from ..core.contracts import Decision, DecisionSet
from .form import ClosedField


def to_closed(
    decisions: DecisionSet, fields: tuple[ClosedField, ...]
) -> dict[str, Any]:
    """封闭字段 -> 值 + 概率分布 + 把握程度。"""
    out: dict[str, Any] = {}
    for field in fields:
        decision = decisions.decisions.get(field.name)
        out[field.name] = _entry(field, decision)
    return out


def _entry(field: ClosedField, decision: Decision | None) -> Any:
    if decision is None or decision.value is None:
        return None

    if field.kind == "confirm":
        try:
            p_yes = float(decision.value)
        except (TypeError, ValueError):
            return None
        return {
            "value": p_yes >= 0.5,
            "p": round(p_yes, 4),
            "certainty": decision.certainty,
            "uncertain": decision.is_uncertain,
            "ranked": decision.ranked,
        }

    try:
        idx = int(round(float(decision.value)))
    except (TypeError, ValueError):
        return None
    label = (
        field.levels[idx]
        if field.levels and 0 <= idx < len(field.levels)
        else None
    )
    return {
        "index": idx,
        "label": label,
        "certainty": decision.certainty,
        "uncertain": decision.is_uncertain,
        "ranked": decision.ranked,
        "probabilities": dict(decision.probabilities),
    }


def confirmed(slot: Any) -> bool:
    """把 confirm 槽位化成布尔。未记录视为否。"""
    if isinstance(slot, dict):
        return bool(slot.get("value"))
    return bool(slot)


def describe(
    closed: dict[str, Any], fields: tuple[ClosedField, ...]
) -> dict[str, str]:
    """转成「标签 -> 可读值」，并在把握不足时加标记。"""
    out: dict[str, str] = {}
    for field in fields:
        slot = closed.get(field.name)
        if slot is None:
            continue
        if field.kind == "confirm":
            text = "是" if confirmed(slot) else "否"
        else:
            label = slot.get("label") if isinstance(slot, dict) else None
            text = label or "未记录"
        if isinstance(slot, dict) and slot.get("uncertain"):
            text += f"（把握 {slot.get('certainty', 0):.2f}）"
        out[field.label] = text
    return out


def uncertain_fields(
    closed: dict[str, Any], fields: tuple[ClosedField, ...]
) -> list[str]:
    """挑出把握不足的字段名，供人工复核。"""
    lookup = {f.name: f for f in fields}
    return [
        lookup[name].label
        for name, slot in closed.items()
        if name in lookup
        and isinstance(slot, dict)
        and slot.get("uncertain")
    ]


def hit_domains_from_closed(
    closed: dict[str, Any], screening_names: dict[str, str]
) -> list[str]:
    """从筛查字段的结果得出命中的症状域。

    screening_names: 字段名 -> 症状域 key
    """
    hits: list[str] = []
    for field_name, domain_key in screening_names.items():
        if confirmed(closed.get(field_name)):
            hits.append(domain_key)
    return hits
