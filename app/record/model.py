"""门诊病历的开放字段模型。纯数据与纯函数。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 通用开放字段的中文名
OPEN_LABELS: dict[str, str] = {
    "chief_complaint": "主诉",
    "department": "就诊科室",
    "present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "family_history": "家族史",
    "physical_exam": "体格检查",
    "auxiliary_exam": "辅助检查",
    "diagnosis": "诊断",
    "prescription": "处置",
    "follow_up": "随访",
}
VITAL_LABELS = {
    "temperature": "体温",
    "pulse": "脉搏",
    "respiration": "呼吸",
    "blood_pressure": "血压",
}
LIST_FIELDS = ("unclear_points", "negatives")


@dataclass
class OutpatientRecord:
    """开放字段的容器。未写的内容一律视为空洞，不补造。"""

    texts: dict[str, str] = field(default_factory=dict)
    vitals: dict[str, str] = field(default_factory=dict)
    unclear_points: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    # 症状域展开出来的开放细节，如 pain_detail / fever_detail
    domain_texts: dict[str, str] = field(default_factory=dict)

    # ---- 构造 ---------------------------------------------------

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        known_domain_names: tuple[str, ...] = (),
    ) -> "OutpatientRecord":
        texts: dict[str, str] = {}
        domain_texts: dict[str, str] = {}

        for key, value in payload.items():
            if key in ("vitals", "unclear_points", "negatives"):
                continue
            if value in (None, "", [], {}):
                continue
            text = value if isinstance(value, str) else str(value)
            if key in OPEN_LABELS:
                texts[key] = text
            elif key in known_domain_names:
                domain_texts[key] = text
            # 其余未知键丢弃，避免污染病历

        vitals_raw = payload.get("vitals") or {}
        vitals = (
            {k: str(v) for k, v in vitals_raw.items() if k in VITAL_LABELS and v}
            if isinstance(vitals_raw, dict)
            else {}
        )

        return cls(
            texts=texts,
            vitals=vitals,
            unclear_points=_str_list(payload.get("unclear_points")),
            negatives=_str_list(payload.get("negatives")),
            domain_texts=domain_texts,
        )

    # ---- 访问 ---------------------------------------------------

    def get(self, name: str) -> str | None:
        if name in OPEN_LABELS:
            return self.texts.get(name)
        return self.domain_texts.get(name)

    def set(self, name: str, value: str) -> None:
        if name in OPEN_LABELS:
            self.texts[name] = value
        else:
            self.domain_texts[name] = value

    @property
    def chief_complaint(self) -> str | None:
        return self.texts.get("chief_complaint")

    @property
    def present_illness(self) -> str | None:
        return self.texts.get("present_illness")

    def missing_required(self, required: tuple[str, ...]) -> list[str]:
        return [k for k in required if not self.get(k)]

    def filled(self) -> dict[str, str]:
        out = {k: v for k, v in self.texts.items() if v}
        out.update({k: v for k, v in self.domain_texts.items() if v})
        return out

    def to_payload(self) -> dict[str, Any]:
        return {
            "texts": dict(self.texts),
            "domain_texts": dict(self.domain_texts),
            "vitals": dict(self.vitals),
            "unclear_points": list(self.unclear_points),
            "negatives": list(self.negatives),
        }

    # ---- 变更 ---------------------------------------------------

    def merge_fill(self, fill: dict[str, Any]) -> list[str]:
        """只补空字段，绝不覆盖已有内容。"""
        changed: list[str] = []
        for key, value in fill.items():
            if not value:
                continue
            if self.get(key):
                continue
            if key in OPEN_LABELS or key in self.domain_texts or key.endswith("_detail"):
                self.set(key, str(value))
                changed.append(key)
        return changed

    def add_questions(self, questions: list[str]) -> None:
        for q in questions:
            q = str(q).strip()
            if q and q not in self.unclear_points:
                self.unclear_points.append(q)


def _str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def build_state(record: OutpatientRecord, transcript: str) -> str:
    import json

    return (
        "已填写内容：\n"
        + json.dumps(record.filled(), ensure_ascii=False, indent=2)
        + "\n\n问诊对话：\n"
        + transcript
    )
