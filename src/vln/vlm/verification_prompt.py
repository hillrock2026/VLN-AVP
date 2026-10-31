"""Prompt for one close-range bound-target verification observation.

The frame already carries only the bound bay's projected region, labelled
``A``. The model is asked for the closed-vocabulary facts the deterministic
verifier needs: occupancy, boundary clarity, occlusion and evidence
sufficiency, plus one ``Selected`` letter. It is never asked for a bay id, a
world coordinate, a confidence probability or free-form reasoning.

The task instruction is deliberately not repeated: the target is already bound
by CAP-07A, and repeating "vacant" would bias the occupancy answer.
"""

from __future__ import annotations

__all__ = [
    "BOUNDARY_CLEAR",
    "BOUNDARY_UNCLEAR",
    "OCCLUSION_NONE",
    "OCCLUSION_PRESENT",
    "EVIDENCE_SUFFICIENT",
    "EVIDENCE_INSUFFICIENT",
    "UNKNOWN_ANSWER",
    "BOUNDARY_ANSWERS",
    "OCCLUSION_ANSWERS",
    "EVIDENCE_ANSWERS",
    "build_target_verification_prompt",
]

UNKNOWN_ANSWER = "无法确定"

BOUNDARY_CLEAR = "清晰"
BOUNDARY_UNCLEAR = "不清晰"
BOUNDARY_ANSWERS = (BOUNDARY_CLEAR, BOUNDARY_UNCLEAR, UNKNOWN_ANSWER)

OCCLUSION_NONE = "无"
OCCLUSION_PRESENT = "有"
OCCLUSION_ANSWERS = (OCCLUSION_NONE, OCCLUSION_PRESENT, UNKNOWN_ANSWER)

EVIDENCE_SUFFICIENT = "充分"
EVIDENCE_INSUFFICIENT = "不足"
EVIDENCE_ANSWERS = (EVIDENCE_SUFFICIENT, EVIDENCE_INSUFFICIENT, UNKNOWN_ANSWER)


def build_target_verification_prompt(label: str = "A") -> str:
    """Build the closed-vocabulary prompt for one close-range observation."""

    if type(label) is not str or label.strip() == "":
        raise ValueError("label must be a non-blank str")
    if label not in "ABCDEFGH" or len(label) != 1:
        raise ValueError(f"unsupported label {label!r}")

    return (
        "请只依据这张刚刚采集的近距离停车场图像作答，不要使用历史图像或文字描述猜测。\n"
        "车辆已经停稳在目标车位的安全接近区域。图中用彩色线框标出了本次要复核的"
        f"目标车位，并标有字母 {label}。\n"
        f"请只判断高亮区域 {label}：\n"
        "1. 只有高亮区域内确实停放车辆时，才写「占用」；立柱、护栏、黄色防撞栏、"
        "挡车器、地面标线不是车辆，不能算占用。\n"
        "2. 只有高亮区域地面可见且没有车辆时，才写「空闲」。\n"
        "3. 高亮区域边界被画面裁断、被遮挡或看不全时，边界写「不清晰」。\n"
        "4. 看不清、有歧义或无法确认时写「无法确定」，不得猜测，也不得把无法确定"
        "当作空闲。\n"
        "5. 不要输出坐标、车位编号、x/y 数值、JSON 或长篇解释；不要照抄本说明。\n"
        "\n"
        "请严格按以下字段逐行输出，不要输出其他内容：\n"
        f"{label}: 判断结果，只能从 空闲、占用、无法确定 中选择\n"
        "边界: 判断结果，只能从 清晰、不清晰、无法确定 中选择\n"
        "遮挡: 判断结果，只能从 无、有、无法确定 中选择\n"
        "证据: 判断结果，只能从 充分、不足、无法确定 中选择\n"
        f"Selected: 只能写 {label} 或 无法确定\n"
    )
