"""Prompt for one scene-entity parking-target binding round.

The image already carries the candidate regions and their temporary letters;
this prompt asks only for observations the model can make on that image:

* per candidate, is the bay vacant, occupied or unknown;
* one candidate letter (or ``无法确定``).

It never asks for a coordinate, a bay id or a JSON object. The letters are
temporary per-frame tokens painted by
:mod:`vln.carla.image_annotate`; the system maps the chosen letter back to the
real bay through :mod:`vln.carla.parking_entities`. A model that invents a
letter, returns an off-vocabulary occupancy, or copies the prompt is refused by
:func:`vln.nav.target_binding.parse_binding_decision`.
"""

from __future__ import annotations

__all__ = [
    "OCCUPANCY_VACANT_ANSWER",
    "OCCUPANCY_OCCUPIED_ANSWER",
    "OCCUPANCY_UNKNOWN_ANSWER",
    "OCCUPANCY_ANSWERS",
    "SELECTED_FIELD",
    "build_binding_prompt",
]


OCCUPANCY_VACANT_ANSWER = "空闲"
OCCUPANCY_OCCUPIED_ANSWER = "占用"
OCCUPANCY_UNKNOWN_ANSWER = "无法确定"

#: Closed vocabulary. Unknown is first class and is never a synonym of vacant.
OCCUPANCY_ANSWERS = (
    OCCUPANCY_VACANT_ANSWER,
    OCCUPANCY_OCCUPIED_ANSWER,
    OCCUPANCY_UNKNOWN_ANSWER,
)

SELECTED_FIELD = "Selected"

_LABEL_ALPHABET = "ABCDEFGH"


def build_binding_prompt(labels: tuple[str, ...], instruction: str) -> str:
    """Build the binding prompt for the candidate letters visible in the frame."""

    if not isinstance(labels, tuple) or not labels:
        raise ValueError("labels must be a non-empty tuple")
    if len(set(labels)) != len(labels):
        raise ValueError("labels must be unique")
    for label in labels:
        if label not in _LABEL_ALPHABET:
            raise ValueError(f"unsupported candidate label {label!r}")
    if not isinstance(instruction, str) or instruction.strip() == "":
        raise ValueError("instruction must be a non-blank str")

    label_text = "、".join(labels)
    return (
        "请只依据这张停车场图像作答，不要推测画面之外的信息。\n"
        "图像中已经用彩色线框圈出候选车位，并在每个候选区域上标有一个大写字母。\n"
        f"本次任务：{instruction.strip()}\n"
        "\n"
        "请逐个判断每个候选车位的占用情况。判断规则：\n"
        "1. 只有车位区域内确实能看到停放车辆时，才写「占用」。\n"
        "2. 只有车位区域内没有车辆、地面确实可见时，才写「空闲」。\n"
        "3. 车位被遮挡、看不清或无法确认时，写「无法确定」；"
        "不得把无法确定当作空闲。\n"
        "4. 只能使用图像中的候选字母，不要输出坐标、车位编号、x/y 数值或 JSON。\n"
        "5. 不要照抄本指令中的句子作为答案，不要因为任务里提到「空闲」就假定车位空闲。\n"
        "\n"
        f"候选字母为：{label_text}。\n"
        "请按下面两段输出，每行一个字段，不要输出其他内容：\n"
        "第一段：对每个候选字母各写一行，格式为「候选字母: 判断结果」；"
        "判断结果只能从 空闲、占用、无法确定 中选择。\n"
        f"第二段：写一行 {SELECTED_FIELD}: 你选择的候选字母；"
        "如果无法确定，写「无法确定」。不得选择候选字母之外的任何内容。\n"
    )
