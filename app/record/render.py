"""Markdown 渲染。纯函数，不调模型也不读文件。"""

from __future__ import annotations

from .form import OpenField
from .formfill import describe
from .model import OPEN_LABELS, VITAL_LABELS, OutpatientRecord

FOOTER = "> 本文由门诊病历填写系统根据问诊对话生成，需经接诊医师核对。"

# 病历正文的小节顺序；domain 小节按命中顺序插在体格检查之前
SECTION_ORDER = (
    "chief_complaint",
    "present_illness",
    "past_history",
    "allergy_history",
    "personal_history",
    "family_history",
    "physical_exam",
    "auxiliary_exam",
    "diagnosis",
    "prescription",
    "follow_up",
)


def render_markdown(
    record: OutpatientRecord,
    *,
    department: str | None = None,
    visited_at: str | None = None,
    closed: dict | None = None,
    closed_fields: tuple = (),
    open_fields: tuple[OpenField, ...] = (),
    footer: str = FOOTER,
) -> str:
    """排成 Markdown。缺失小节写「未记录」，不省略标题。"""
    lines: list[str] = ["# 门诊病历", "", "## 一般项目"]
    lines.append(f"- 就诊科室：{department or '未记录'}")
    lines.append(f"- 就诊时间：{visited_at or '未记录'}")
    lines.append(f"- 主诉：{_text(record.texts.get('chief_complaint'))}")
    lines.append("")

    for key in SECTION_ORDER:
        if key == "chief_complaint":
            continue
        lines.append(f"## {OPEN_LABELS[key]}")
        if key == "physical_exam":
            lines.extend(_vitals(record))
            lines.append("")
            lines.append(_text(record.texts.get(key)))
        elif key == "diagnosis" and record.negatives:
            lines.append(_text(record.texts.get(key)))
            lines.append("")
            lines.append("有鉴别意义的阴性所见：" + "；".join(record.negatives))
        elif key == "present_illness":
            lines.append(_text(record.texts.get(key)))
            extras = _domain_texts(record, open_fields)
            if extras:
                lines.append("")
                lines.extend(f"- {label}：{value}" for label, value in extras)
        else:
            lines.append(_text(record.texts.get(key)))
        lines.append("")

    closed_bits = describe(closed or {}, closed_fields) if closed_fields else {}
    if closed_bits:
        lines.append("## 结构化字段")
        lines.extend(f"- {k}：{v}" for k, v in closed_bits.items())
        lines.append("")

    lines.append("## 信息缺口")
    lines.extend(f"- {x}" for x in record.unclear_points) if record.unclear_points else None
    if not record.unclear_points:
        lines.append("未发现")
    lines.append("")
    lines.append(footer)
    return "\n".join(lines)


def _domain_texts(
    record: OutpatientRecord, open_fields: tuple[OpenField, ...]
) -> list[tuple[str, str]]:
    labels = {f.name: f.label for f in open_fields}
    return [
        (labels.get(name, name), value)
        for name, value in record.domain_texts.items()
        if value
    ]


def _vitals(record: OutpatientRecord) -> list[str]:
    if not record.vitals:
        return ["生命体征：未记录"]
    parts = [
        f"{VITAL_LABELS[k]} {record.vitals[k]}"
        for k in VITAL_LABELS
        if k in record.vitals
    ]
    return ["生命体征：" + "，".join(parts)]


def _text(value: str | None) -> str:
    if value is None:
        return "未记录"
    text = str(value).strip()
    return text or "未记录"
