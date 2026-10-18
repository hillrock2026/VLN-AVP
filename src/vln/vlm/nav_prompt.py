"""Navigation prompt variants for the ZDTaichu5.0-9B image round.

Why this exists: in ``M1-VLN-REAL-MODEL-06A`` the navigation prompt lived only
inside an integration test (``tests/integration/test_taichu_image_smoke.py``) and
it contained a fully sampled JSON template with ``<字符串>`` / ``<数值>``
placeholders. Against the real model that produced template echo - one round
returned the placeholder token verbatim as ``intent_id`` - and a degenerate
``target {x:0,y:0,heading:0}`` for two visually different frames, while a plain
visual question on the same images was answered correctly. The prompt, not the
image path, was the fault, so the variants belong in one reviewable place rather
than in a test string.

What this module does **not** do: it does not parse model output, build an
``AgentIntent``, call a host, or change any contract. ``AgentIntent`` v1 has no
abstention field, so a variant that expects the model to decline cannot express
that through the contract - :data:`Variant.ABSTENTION` therefore asks for a
supporting plain-text judgement and is explicitly *not* a contract prompt.

Every variant obeys two house rules, asserted by the unit tests:

* no placeholder token and no sampled JSON value appears in the text, so the
  model has nothing to copy;
* the requested target must really be visible before it may be claimed, and an
  unverifiable target must not be turned into a coordinate.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_TARGET_LABEL",
    "DEFAULT_INTENT_ID",
    "DEFAULT_TARGET_KIND",
    "VISUAL_EVIDENCE_KINDS",
    "GROUNDING_QUESTION",
    "VISIBLE_ANSWERS",
    "POSITION_ANSWERS",
    "DIRECTION_ANSWERS",
    "UNKNOWN_ANSWER",
    "EVIDENCE_UNCERTAINTY_ANSWERS",
    "IDENTITY_FIELD",
    "Variant",
    "VARIANTS",
    "BASELINE_PROMPT",
    "build_nav_prompt",
    "build_grounding_prompt",
]

#: The parking slot the task asks for. Only IMG-02/IMG-03/IMG-04 carry legible bay
#: identifiers (``D65``, ``D0x``, ``316``) and none of the four carries ``P07``,
#: so every variant is a genuine "target not visible" case.
DEFAULT_TARGET_LABEL = "P07"

#: A literal the caller owns, so the model never has to invent an identifier and
#: an echoed placeholder can never be mistaken for a real one.
DEFAULT_INTENT_ID = "p07-visual-nav"

#: What the requested target *is* in the default wording: a bay number. See
#: :func:`_target_direction` for why 07C had to make this a parameter.
DEFAULT_TARGET_KIND = "车位编号"

#: What the prompt asks the model to look at. These are the evidence kinds that
#: actually appear in the four frames: column area letters (C/A/B/C), bay numbers
#: (D65/D0x/316), the 出口/EXIT sign, deck arrows, wheel stops and pillars.
VISUAL_EVIDENCE_KINDS = (
    "立柱上的区域标识（字母或数字）",
    "地面上可见的车位编号",
    "出口(EXIT/出口)标识",
    "地面方向箭头",
    "障碍物（护栏、挡车器、闸门）",
    "通道结构与可通行区域",
)

#: The visual probe verified in 06A (IMG-01 -> C, IMG-02 -> A). It shares no
#: wording with the JSON contract, so a correct answer cannot be a template echo.
GROUNDING_QUESTION = "这张图中的立柱上重复出现了什么字母标识？只回答该字母，不要解释。"


class Variant:
    """The prompt variants, by name. Plain strings, mirroring ``LoopStopReason``."""

    #: 06A's prompt, reproduced verbatim as the control for every comparison.
    BASELINE = "baseline"
    #: Smallest correction: same contract shape, template and placeholders removed,
    #: anti-copy and anti-fabrication rules added.
    DETEMPLATED = "detemplated"
    #: Staged observation -> target check -> decision -> conclusion, as plain text.
    #: Deliberately not a contract prompt (see the module docstring).
    ABSTENTION = "abstention"
    #: Strictest form: fixed literal ``intent_id``, minimal format definition with
    #: no sampled values, explicit bans on placeholders and on all-zero coordinates.
    STRICT = "strict"
    #: 07B: find a *visible* target bay and give a discrete direction. No JSON, no
    #: coordinates - only fields whose values are drawn from a closed vocabulary.
    TARGET_DIRECTION = "target-direction"


VARIANTS = (
    Variant.BASELINE,
    Variant.DETEMPLATED,
    Variant.ABSTENTION,
    Variant.STRICT,
    Variant.TARGET_DIRECTION,
)

#: The discrete values the 07B prompt allows. ``UNKNOWN`` is a first-class answer
#: on purpose: the whole point of the negative controls is that "cannot determine"
#: must be reachable without inventing a position.
VISIBLE_ANSWERS = ("是", "否")
POSITION_ANSWERS = ("LEFT", "RIGHT", "AHEAD", "无法确定")
DIRECTION_ANSWERS = ("LEFT", "RIGHT", "STRAIGHT", "无法确定")
UNKNOWN_ANSWER = "无法确定"

#: Explicit evidence-insufficiency answers. The prompt asks the model to write
#: :data:`UNKNOWN_ANSWER` when the visual evidence cannot support the judgement;
#: the verifier accepts the other exact forms as robustness. An Evidence value
#: is classified as insufficient only when the *whole* value is composed of
#: these tokens (see :func:`vln.nav.visual_decision.evidence_is_insufficient`),
#: never by keyword search inside an otherwise substantive sentence.
EVIDENCE_UNCERTAINTY_ANSWERS = (
    UNKNOWN_ANSWER,
    "证据不足",
    "无法判断",
    "无法确认",
    "不确定",
    "不能确定",
    "无法识别",
    "无法辨认",
    "看不清",
    "不可见",
)

#: 08A's extra conclusion-block field. 07B and 07C scored ``Visible`` and the
#: direction, but never asked **what the model actually read**: the ``Target``
#: field is defined as a copy of the requested label, so a correct-looking answer
#: could not be separated from target-name anchoring. This field asks for the
#: characters found in the pixels, which is what makes identity and direction
#: separately scorable.
IDENTITY_FIELD = "Identified as"

#: 06A's instruction, byte-for-byte, so a comparison against it is controlled.
#: It is kept only as the baseline and is never returned by a default.
BASELINE_PROMPT = (
    "请观察这张停车场图像，判断可见的车位标识、道路结构、通行区域及可能的障碍物。"
    "导航目标为 P07。只输出一个 JSON 对象，不要输出任何其他文字、解释或代码块标记，"
    '键必须恰好是 contract_version、intent_id、action、target：{"contract_version":"1",'
    '"intent_id":"<字符串>","action":"parking.move","target":{"x":<数值>,"y":<数值>,'
    '"heading":<数值>}}。'
    "如果图像中没有可见的车位编号标识、目标标识不是 P07、或无法判断通道是否畅通，"
    "请直接返回空字符串，不要编造坐标。"
)

_EVIDENCE_BLOCK = "观察要点：" + "、".join(VISUAL_EVIDENCE_KINDS) + "。"

#: How the two contract variants express abstention. The contract has no
#: abstention field, so the only representation left is an empty answer - and the
#: wording avoids naming a token the model could copy: the text-only control in
#: the 07A pilot returned the literal phrase ``空字符串`` when the prompt asked for
#: one, which is a phrase echo rather than an abstention.
_ABSTENTION_FORM = "直接返回一个空的回答（不要输出任何字符）。"

#: Shared by the two de-templated contract variants. No example object, no
#: placeholder, no numeric value: the field semantics are described in prose only.
_CONTRACT_RULES = (
    "输出格式（只有在你确实从图像中确定了目标时才输出）：\n"
    "只输出一个 JSON 对象，不要输出其他任何文字、解释或代码块标记。\n"
    "该对象只含四个键：\n"
    "- contract_version：字符串常量 1\n"
    "- intent_id：字符串常量 {intent_id}\n"
    "- action：字符串常量 parking.move\n"
    "- target：对象，只含 x、y、heading 三个数值字段\n"
    "不要输出任何示例值、示意值或尖括号包裹的说明文字；"
    "每个字段值必须是固定常量或你根据图像得出的真实内容。"
)


def _detemplated(target: str, intent_id: str) -> str:
    return (
        "请先仔细观察这张停车场图像，再作答。\n"
        + _EVIDENCE_BLOCK
        + "\n"
        + f"导航任务：寻找车位 {target}。\n"
        "硬性规则：\n"
        f"1. 只能依据图像中真实可见的内容判断，不得推测图像里看不到的信息。\n"
        f"2. 不得声称看到了 {target}，除非图像中确实出现了「{target}」这样的车位编号标识。\n"
        "3. 不得复制本指令中的任何文字作为字段值，不得输出占位符或示意值。\n"
        f"4. 如果无法从图像中确认 {target} 的位置，不要编造坐标，"
        f"{_ABSTENTION_FORM}\n"
        + _CONTRACT_RULES.format(intent_id=intent_id)
    )


def _abstention(target: str, intent_id: str) -> str:
    return (
        "请仔细观察这张停车场图像，然后按顺序给出你的判断，不要跳步。\n"
        + _EVIDENCE_BLOCK
        + "\n"
        + f"第一步 观察：说明图像中真实可见的内容（立柱区域标识、车位编号、出口标识、"
        "地面箭头、障碍物、通道结构）。\n"
        f"第二步 核对目标：导航目标为车位 {target}。图像中是否出现了「{target}」"
        "或与之等价的车位编号标识？请指出你据此判断的具体可见证据。\n"
        "第三步 决策：根据当前可见信息给出下一步导航判断；"
        "如果无法从当前图像确认目标位置，明确说明无法确定，不要编造位置或坐标。\n"
        "第四步 结论：用一句话总结你的判断。\n"
        "不要推测图像中看不到的信息，不要编造任何数值。\n"
        "请用简体中文回答，不要输出 JSON。"
    )


def _strict(target: str, intent_id: str) -> str:
    return (
        "请先仔细观察这张停车场图像，只依据图像中真实可见的内容作答。\n"
        + _EVIDENCE_BLOCK
        + "\n"
        + f"导航任务：寻找车位 {target}。\n"
        "判断规则：\n"
        f"- 只有当图像中确实出现「{target}」这样的车位编号标识时，才能声称找到了目标。\n"
        "- 不得输出占位符、示意值或尖括号包裹的说明文字，不得把字段名当作字段值。\n"
        "- 不得为图像中看不到的目标编造位置，不得输出 x、y、heading 全为零的坐标。\n"
        f"- 无法从图像中确认 {target} 位置时，不要编造坐标，{_ABSTENTION_FORM}\n"
        "禁止照抄本指令中的任何文字作为答案。\n"
        + _CONTRACT_RULES.format(intent_id=intent_id)
    )


def _target_direction(
    target: str,
    _intent_id: str,
    target_kind: str = "车位编号",
    target_note: str = "",
    require_identity: bool = False,
    require_evidence: bool = False,
) -> str:
    """The 07B prompt: identify a visible target and answer discretely.

    Deliberately asks for **no** coordinate: with no calibration, map or vehicle
    pose in this project, a metric target would have no ground truth to compare
    against. The answer vocabulary is closed (see :data:`VISIBLE_ANSWERS`,
    :data:`POSITION_ANSWERS`, :data:`DIRECTION_ANSWERS`), so "cannot determine" is
    always available next to the real answers and never has to be faked as a
    position.

    ``target_kind`` is what the target *is* - a bay number by default. In 07C the
    model denied a plainly visible 出口/EXIT sign with the evidence "仅可见蓝色
    『出口』指示牌，无对应车位编号", i.e. it read the sign and then rejected it for
    not being a bay number, so a caller testing a sign target must say so. The
    default keeps the 07B prompt byte-identical.

    ``target_note`` appends one caller-supplied sentence after the target step (for
    example that the deck paint is inverted). It is empty by default, so the 07B
    prompt text is untouched; 07C used it for one labelled supplementary probe.

    ``require_identity`` adds 08A's :data:`IDENTITY_FIELD` line to the conclusion
    block plus the rule that keeps it from being a copy of the requested label.
    False by default, so the 07B and 07C prompts stay byte-identical.

    ``require_evidence`` adds the explicit evidence-insufficiency instruction:
    the model must write :data:`UNKNOWN_ANSWER` in ``Evidence`` when it cannot
    support the judgement, and ``Target`` is stated to be only the request echo,
    not proof that the target was seen. False by default, so every historical
    prompt (07B/07C/08A/11C) remains byte-identical.
    """

    note = f"{target_note}\n" if target_note else ""
    if require_identity:
        identity_line = (
            f"{IDENTITY_FIELD}: 你从画面像素中实际辨认出的标识文字"
            f"（原样照抄画面里出现的字符）；无法辨认或目标不可见时写 {UNKNOWN_ANSWER}\n"
        )
        identity_rule = (
            f"6. {IDENTITY_FIELD} 必须来自画面像素，不得直接照抄 Target 行给出的目标名称，"
            "不得因为本指令提到目标就照填。\n"
        )
        field_count = "六"
    else:
        identity_line = ""
        identity_rule = ""
        field_count = "五"

    if require_evidence:
        evidence_line = (
            "Evidence: 支持你判断的可见证据（一句话）；不得只重复目标名称或指令；"
            f"证据不足、无法辨认或无法确定时写 {UNKNOWN_ANSWER}\n"
        )
        rule_number = "7" if require_identity else "6"
        evidence_rule = (
            f"{rule_number}. Target 只回显本次要找的目标，不代表画面中已经看到它；"
            "Evidence 必须描述画面中实际可见的依据。如果证据不足或无法确定，"
            f"Evidence 必须写「{UNKNOWN_ANSWER}」，Relative position 和 "
            f"Next direction 也必须写「{UNKNOWN_ANSWER}」。\n"
        )
    else:
        evidence_line = "Evidence: 你据以判断的可见证据（一句话）\n"
        evidence_rule = ""

    return (
        "请仔细观察这张停车场图像，只依据画面中真实可见的内容作答。\n"
        + _EVIDENCE_BLOCK
        + "\n"
        "第一步 观察：说明画面中真实可见的内容（立柱区域标识、地面车位编号、出口标识、"
        "地面箭头、障碍物、通道结构）。\n"
        f"第二步 查找目标：本次要找的{target_kind}是 {target}。画面中是否真的出现了"
        f"「{target}」这个标识？如果出现，请说明它在画面中的大致位置和你能看到的视觉证据。\n"
        + note
        + f"第三步 判断相对方位（仅当 {target} 确实可见时）：以当前视角看，{target} "
        "位于画面的左侧、右侧还是前方？\n"
        "第四步 给出下一步离散导航方向：从 LEFT、RIGHT、STRAIGHT 三个方向中选择一个；"
        f"如果 {target} 不可见或无法确定，这里写 {UNKNOWN_ANSWER}。\n"
        f"第五步 输出结论块：逐行写出下面{field_count}个字段，每行采用「字段名: 值」的形式，"
        "不要输出其他内容：\n"
        f"Target: 目标{target_kind}（照抄第二步给出的标识本身）\n"
        + identity_line
        + f"Visible: {' 或 '.join(VISIBLE_ANSWERS)}\n"
        f"Relative position: {' 或 '.join(POSITION_ANSWERS)}\n"
        f"Next direction: {' 或 '.join(DIRECTION_ANSWERS)}\n"
        + evidence_line
        + "硬性规则：\n"
        f"1. 不得推测画面中看不到的信息，不得凭猜测补出{target_kind}。\n"
        f"2. 不得声称看到了 {target}，除非画面中确实出现了这个标识；"
        "不得因为本指令提到它就假定它存在。\n"
        f"3. 如果 {target} 在画面中不可见，Visible 必须写「{VISIBLE_ANSWERS[1]}」，"
        f"Relative position 和 Next direction 必须写「{UNKNOWN_ANSWER}」，不要编造位置。\n"
        "4. 不得把本指令中的整句文字当作答案抄回。\n"
        "5. 不要输出任何坐标数值，不要输出 x、y、heading，不要输出 JSON。\n"
        + identity_rule
        + evidence_rule
    )


_BUILDERS = {
    Variant.DETEMPLATED: _detemplated,
    Variant.ABSTENTION: _abstention,
    Variant.STRICT: _strict,
    Variant.TARGET_DIRECTION: _target_direction,
}


def build_nav_prompt(
    variant: str = Variant.STRICT,
    *,
    target: str = DEFAULT_TARGET_LABEL,
    intent_id: str = DEFAULT_INTENT_ID,
    target_kind: str = DEFAULT_TARGET_KIND,
    target_note: str = "",
    require_identity: bool = False,
    require_evidence: bool = False,
) -> str:
    """Return the navigation prompt for ``variant``.

    ``BASELINE`` returns 06A's text unchanged; the other variants are built from
    ``target``, ``intent_id`` and ``target_kind``. An unknown variant is refused
    rather than silently defaulted, so a typo in an experiment cannot quietly re-run
    the baseline and look like a result. ``target_kind`` only affects
    :data:`Variant.TARGET_DIRECTION` and defaults to the bay-number wording, so the
    prompt 07B was run with is reproduced byte-for-byte.

    ``require_identity`` also only affects :data:`Variant.TARGET_DIRECTION`, and is
    ``False`` by default, so the 07B and 07C prompts are reproduced byte-for-byte
    and their recorded runs still match the text they were sent.

    ``require_evidence`` only affects :data:`Variant.TARGET_DIRECTION` and is
    ``False`` by default. When true it adds the evidence-insufficiency rule that
    pairs with :func:`vln.nav.visual_decision.evidence_is_insufficient`; the
    historical prompts remain byte-identical.
    """

    if variant == Variant.BASELINE:
        return BASELINE_PROMPT
    builder = _BUILDERS.get(variant)
    if builder is None:
        raise ValueError(
            f"unknown prompt variant {variant!r}; expected one of {list(VARIANTS)}"
        )
    if type(target) is not str or target.strip() == "":
        raise ValueError("target must be a non-blank str")
    if type(intent_id) is not str or intent_id.strip() == "":
        raise ValueError("intent_id must be a non-blank str")
    if type(target_kind) is not str or target_kind.strip() == "":
        raise ValueError("target_kind must be a non-blank str")
    if type(target_note) is not str:
        raise ValueError("target_note must be a str")
    if type(require_identity) is not bool:
        raise ValueError("require_identity must be a bool")
    if type(require_evidence) is not bool:
        raise ValueError("require_evidence must be a bool")
    if builder is _target_direction:
        return builder(
            target,
            intent_id,
            target_kind,
            target_note,
            require_identity,
            require_evidence,
        )
    return builder(target, intent_id)


def build_grounding_prompt() -> str:
    """Return the 06A visual probe, unchanged, as the non-regression control."""

    return GROUNDING_QUESTION
