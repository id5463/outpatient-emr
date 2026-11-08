"""决策模型。独立端点，返回概率。不认识 LLM，也不做兜底。"""

from __future__ import annotations

from typing import Any

from ..core.contracts import Decision, DecisionSet
from ..core.transport import JsonTransport, UpstreamError


def noul(instructions: str, criteria: dict[str, str] | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    return q


def choice(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: str, criteria: list[str]) -> dict[str, Any]:
    if len(criteria) < 2:
        raise ValueError("score 至少需要两个等级")
    return {"type": "score", "instructions": instructions, "criteria": criteria}


class JevJudger:
    """typesafe/jev，POST /systemone。state 与 questions 共享一次调用。"""

    PATH = "systemone"
    MAX_QUESTIONS = 100

    def __init__(self, transport: JsonTransport, models: tuple[str, ...]) -> None:
        if not models:
            raise ValueError("models 不能为空")
        self.transport = transport
        self.models = models

    def decide(self, state: str, questions: dict[str, Any]) -> DecisionSet:
        if not questions:
            raise ValueError("至少需要一个 question")
        if len(questions) > self.MAX_QUESTIONS:
            raise ValueError(f"单次最多 {self.MAX_QUESTIONS} 个 question")

        errors: list[str] = []
        for model in self.models:
            payload = {"model": model, "state": state, "questions": questions}
            try:
                data = self.transport.post(self.PATH, payload)
            except UpstreamError as exc:
                errors.append(f"{model}: {exc}")
                continue
            answers = data.get("answers") or {}
            if not answers:
                errors.append(f"{model}: 响应缺少 answers")
                continue
            return DecisionSet(
                decisions=_parse(questions, answers),
                model=model,
                usage=data.get("usage") or {},
            )

        raise UpstreamError("决策模型全部不可用 -> " + " | ".join(errors))


def _parse(
    questions: dict[str, Any], answers: dict[str, Any]
) -> dict[str, Decision]:
    out: dict[str, Decision] = {}
    for name, q in questions.items():
        raw = answers.get(name) or {}
        kind = q["type"]
        if kind == "noul":
            value = _f(raw.get("noul"))
        elif kind == "choice":
            value = raw.get("choice")
        else:
            value = _f(raw.get("score"))
        out[name] = Decision(
            name=name,
            kind=kind,
            value=value,
            confidence=_f(raw.get("confidence")),
            probabilities={
                str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()
            },
            legend={str(k): str(v) for k, v in (raw.get("legend") or {}).items()},
            raw=dict(raw) if isinstance(raw, dict) else {},
        )
    return out


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
