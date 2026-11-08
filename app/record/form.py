"""门诊病历的字段体系。

字段分两类，因为它们的域性质完全不同：

ClosedField  取值是有限的、可穷举的（是否、三档紧急度、要不要用药）
             -> 交给决策模型，一次调用几百 token，1~2 秒返回

OpenField    取值是开放的自然语言（现病史、查体所见、科室、部位描述）
             -> 交给语言模型，不能被枚举

判断依据不是「方不方便」，而是「这个字段的值域是否真的有限」。
医学描述大部分是开放的：疼痛是「上腹偏右持续性钝痛向背部放射」，
任何枚举都装不下，硬塞只会丢信息。

扩展方式：往 CLOSED_FIELDS / OPEN_FIELDS 里加条目即可，
两者都不与科室绑定——科室只是开放字段里的一个值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Level = Literal["scale", "confirm"]


# ---- 封闭字段 ------------------------------------------------------


@dataclass(frozen=True)
class ClosedField:
    """值域有限的字段。

    scale   分级判断，levels 按由轻到重排列
    confirm 是否为真
    """

    name: str
    label: str
    kind: Level
    instructions: str
    levels: tuple[str, ...] | None = None
    # 该字段属于哪个症状域；空表示通用字段
    domain: str = ""

    def to_question(self) -> dict[str, Any]:
        if self.kind == "scale":
            if not self.levels or len(self.levels) < 2:
                raise ValueError(f"{self.name} 是 scale 但等级不足")
            return {
                "type": "score",
                "instructions": self.instructions,
                "criteria": list(self.levels),
            }
        return {"type": "noul", "instructions": self.instructions}


# ---- 开放字段 ------------------------------------------------------


@dataclass(frozen=True)
class OpenField:
    """值域开放、必须用自然语言表达的字段。

    hint 是写作指引，不是选项——它描述该写什么，不限定能写什么。
    """

    name: str
    label: str
    hint: str
    domain: str = ""
    required: bool = False


# ---- 症状域 --------------------------------------------------------
#
# 症状域只声明「哪些封闭字段用来筛查这个域」和「命中后展开哪些开放字段」，
# 域本身不代表科室。多个域可以同时命中。


@dataclass(frozen=True)
class Domain:
    key: str
    label: str
    screening: ClosedField
    open_details: tuple[OpenField, ...] = ()
    closed_details: tuple[ClosedField, ...] = ()


def _screen(key: str, label: str, question: str | None = None) -> ClosedField:
    return ClosedField(
        name=f"has_{key}",
        label=label,
        kind="confirm",
        instructions=question or f"对话中是否出现{label}的相关表现？",
    )


def _scale(name, label, instructions, levels) -> ClosedField:
    return ClosedField(name, label, "scale", instructions, levels=tuple(levels))


DOMAINS: tuple[Domain, ...] = (
    Domain(
        "fever",
        "发热",
        _screen("fever", "发热", "是否出现发热或体温升高？"),
        open_details=(
            OpenField(
                "fever_detail",
                "发热情况",
                "记录热型、最高体温、持续时间、伴随寒战或出汗。"
                "用对话原文的表述，不套用固定分类。",
                domain="fever",
            ),
        ),
        closed_details=(
            _scale("fever_level", "发热程度", "体温升高到什么程度？",
                   ("未达 38℃", "38~39℃", "39℃ 以上")),
        ),
    ),
    Domain(
        "pain",
        "疼痛",
        _screen("pain", "疼痛", "是否出现疼痛？"),
        open_details=(
            OpenField(
                "pain_detail",
                "疼痛特点",
                "记录部位、性质、程度、持续时间、放射、缓解与加重因素。"
                "按患者原话写，不用固定分类。",
                domain="pain",
            ),
        ),
        closed_details=(
            _scale("pain_impact", "疼痛影响", "疼痛对日常活动的影响程度？",
                   ("几乎不影响", "影响部分活动", "无法正常活动")),
        ),
    ),
    Domain(
        "gi",
        "消化道症状",
        _screen("gi", "消化道症状", "是否出现恶心、呕吐、腹泻、便秘或反酸等消化道表现？"),
        open_details=(
            OpenField(
                "gi_detail",
                "消化道表现",
                "记录各项消化道症状的起病、频率、与进食的关系、大便性状。",
                domain="gi",
            ),
        ),
    ),
    Domain(
        "bleeding",
        "出血",
        _screen("bleeding", "出血",
                "是否出现任何形式的出血，包括呕血、黑便、便血、咯血、鼻衄、皮下出血？"),
        open_details=(
            OpenField(
                "bleeding_detail",
                "出血情况",
                "记录出血部位、量、颜色、频次、诱因。",
                domain="bleeding",
            ),
        ),
        closed_details=(
            _scale("bleeding_amount", "出血量", "出血量大致多少？",
                   ("少量", "中等", "大量")),
        ),
    ),
    Domain(
        "respiratory",
        "呼吸道症状",
        _screen("respiratory", "呼吸道症状", "是否出现咳嗽、咳痰、气促或呼吸困难？"),
        open_details=(
            OpenField(
                "respiratory_detail",
                "呼吸道表现",
                "记录咳嗽性质、痰量痰色、气促程度与诱因、体位影响。",
                domain="respiratory",
            ),
        ),
    ),
    Domain(
        "cardiac",
        "循环系统症状",
        _screen("cardiac", "循环系统症状", "是否出现胸痛、心悸、气促或水肿？"),
        open_details=(
            OpenField(
                "cardiac_detail",
                "循环系统表现",
                "记录胸痛性质与诱因、心悸发作方式、水肿部位与时间规律。",
                domain="cardiac",
            ),
        ),
    ),
    Domain(
        "neuro",
        "神经系统症状",
        _screen("neuro", "神经系统症状",
                "是否出现头痛、眩晕、肢体无力麻木、言语不清或意识改变？"),
        open_details=(
            OpenField(
                "neuro_detail",
                "神经系统表现",
                "记录起病方式、部位、持续时间、进展过程、伴随症状。",
                domain="neuro",
            ),
        ),
    ),
    Domain(
        "skin",
        "皮肤表现",
        _screen("skin", "皮肤表现", "是否出现皮疹、瘙痒或其他皮肤损害？"),
        open_details=(
            OpenField(
                "skin_detail",
                "皮肤表现",
                "记录皮疹形态、分布、演变、瘙痒程度、可能的接触或用药诱因。",
                domain="skin",
            ),
        ),
    ),
    Domain(
        "constitutional",
        "全身情况",
        _screen("constitutional", "全身情况",
                "是否出现体重变化、明显乏力、盗汗或食欲改变？"),
        open_details=(
            OpenField(
                "constitutional_detail",
                "全身情况",
                "记录体重变化幅度与时间、乏力程度、盗汗与食欲情况。",
                domain="constitutional",
            ),
        ),
    ),
    Domain(
        "metabolic",
        "内分泌代谢表现",
        _screen("metabolic", "内分泌代谢表现",
                "是否出现多饮、多尿、怕热多汗或明显口渴？"),
        open_details=(
            OpenField(
                "metabolic_detail",
                "内分泌代谢表现",
                "记录饮水量尿量变化、怕热多汗、体重改变、食量变化。",
                domain="metabolic",
            ),
        ),
    ),
    Domain(
        "trauma",
        "外伤",
        _screen("trauma", "外伤", "是否有外伤或明确的受伤经过？"),
        open_details=(
            OpenField(
                "trauma_detail",
                "外伤经过",
                "记录受伤时间、机制、部位、现场处理、活动受限情况。",
                domain="trauma",
            ),
        ),
    ),
    Domain(
        "allergy",
        "过敏",
        _screen("allergy", "过敏", "是否提到过明确的药物、食物或接触物过敏？"),
        open_details=(
            OpenField(
                "allergy_detail",
                "过敏情况",
                "记录过敏原名称、反应形式、发生时间。",
                domain="allergy",
            ),
        ),
    ),
)

DOMAIN_BY_KEY: dict[str, Domain] = {d.key: d for d in DOMAINS}


# ---- 通用封闭字段：与症状域无关，每次就诊都问 ----------------------


URGENCY_LEVELS = ("可择期处理", "需尽快处理", "需立即处理")

UNIVERSAL_CLOSED: tuple[ClosedField, ...] = (
    _scale("urgency", "紧急程度", "按当前症状与体征，病情紧急程度如何？", URGENCY_LEVELS),
    ClosedField("needs_exam", "需进一步检查", "confirm",
                "本次是否需要安排化验或影像检查？"),
    ClosedField("needs_medication", "需用药", "confirm", "本次是否需要开具药物？"),
    ClosedField("needs_followup", "需随访", "confirm", "本次是否需要安排复诊或随访？"),
    ClosedField("needs_referral", "需转诊", "confirm",
                "本次是否需要转诊到其他科室或上级医院？"),
    ClosedField("needs_emergency", "需急诊处理", "confirm",
                "是否需要立即急诊或住院处理？"),
)


# ---- 通用开放字段：病历的固定叙述部分 ------------------------------


UNIVERSAL_OPEN: tuple[OpenField, ...] = (
    OpenField(
        "chief_complaint",
        "主诉",
        "主要症状或体征 + 持续时间，20 字以内，不含诊断名称。",
        required=True,
    ),
    OpenField(
        "department",
        "就诊科室",
        "根据全部症状判断最合适的接诊科室或专科。可以是任何临床科室名称，"
        "不限于常见列表。若跨专科，写出最相关的一个。",
        required=True,
    ),
    OpenField(
        "present_illness",
        "现病史",
        "按时间顺序写起病、症状特点与演变、伴随症状、诊治经过、"
        "发病以来一般情况。只写对话中出现的内容。",
        required=True,
    ),
    OpenField("past_history", "既往史", "既往疾病、手术、外伤、输血史。"),
    OpenField("allergy_history", "过敏史", "药物、食物或其他过敏，含反应形式。"),
    OpenField("personal_history", "个人史", "吸烟饮酒、职业、居住地、生活嗜好。"),
    OpenField("family_history", "家族史", "直系亲属同类疾病或遗传病。"),
    OpenField("physical_exam", "体格检查", "查体所见，含生命体征。只写对话中出现的。"),
    OpenField("auxiliary_exam", "辅助检查", "化验与影像结果及日期。"),
    OpenField("diagnosis", "诊断", "对话中提到的病名或印象。不做推断。"),
    OpenField("prescription", "处置", "用药（药名、剂量、用法）与医嘱。"),
    OpenField("follow_up", "随访", "复诊安排、注意事项、需警惕的症状。"),
)


# ---- 组装 ----------------------------------------------------------


def screening_fields() -> tuple[ClosedField, ...]:
    """阶段一：所有症状域的筛查字段。"""
    return tuple(d.screening for d in DOMAINS)


def closed_fields_for(hit_domains: tuple[str, ...]) -> tuple[ClosedField, ...]:
    """阶段二：通用封闭字段 + 命中症状域的封闭细节。"""
    ordered: list[ClosedField] = list(UNIVERSAL_CLOSED)
    seen = {f.name for f in ordered}
    for key in hit_domains:
        domain = DOMAIN_BY_KEY.get(key)
        if domain is None:
            continue
        for f in (domain.screening,) + domain.closed_details:
            if f.name in seen:
                continue
            ordered.append(f)
            seen.add(f.name)
    return tuple(ordered)


def open_fields_for(hit_domains: tuple[str, ...]) -> tuple[OpenField, ...]:
    """阶段三：通用开放字段 + 命中症状域的开放细节。"""
    ordered: list[OpenField] = list(UNIVERSAL_OPEN)
    seen = {f.name for f in ordered}
    for key in hit_domains:
        domain = DOMAIN_BY_KEY.get(key)
        if domain is None:
            continue
        for f in domain.open_details:
            if f.name in seen:
                continue
            ordered.append(f)
            seen.add(f.name)
    return tuple(ordered)


def closed_questions(fields: tuple[ClosedField, ...]) -> dict[str, Any]:
    return {f.name: f.to_question() for f in fields}


def open_schema(fields: tuple[OpenField, ...]) -> dict[str, str]:
    """把开放字段变成「字段名 -> 写作指引」，交给语言模型。"""
    return {f.name: f.hint for f in fields}
