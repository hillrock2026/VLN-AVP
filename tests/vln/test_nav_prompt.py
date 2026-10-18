"""Offline tests for the navigation prompt variants.

The subject is prompt *text*: what it must contain, and - more important after
06A - what it must never contain, because a placeholder in the prompt is what the
model copied. No model, no network and no image is involved here.
"""

from __future__ import annotations

import pytest

from vln.vlm.nav_prompt import (
    BASELINE_PROMPT,
    DEFAULT_INTENT_ID,
    DEFAULT_TARGET_KIND,
    DEFAULT_TARGET_LABEL,
    DIRECTION_ANSWERS,
    EVIDENCE_UNCERTAINTY_ANSWERS,
    GROUNDING_QUESTION,
    IDENTITY_FIELD,
    POSITION_ANSWERS,
    UNKNOWN_ANSWER,
    VARIANTS,
    VISIBLE_ANSWERS,
    Variant,
    build_grounding_prompt,
    build_nav_prompt,
)

#: The tokens that 06A's baseline put in the prompt and that the model echoed.
_FORBIDDEN_PLACEHOLDERS = ("<字符串>", "<数值>", "<", ">")

#: Phrasings that would re-introduce a copyable sampled object.
_SAMPLED_VALUE_MARKERS = ("{", "}", '"x":0', "(0,0,0)", "0,0,0")

_DETEMPLATED_VARIANTS = (Variant.DETEMPLATED, Variant.ABSTENTION, Variant.STRICT)


def test_the_variant_set_is_the_planned_ones() -> None:
    # 07A's four plus 07B's target-direction prompt.
    assert VARIANTS == (
        "baseline",
        "detemplated",
        "abstention",
        "strict",
        "target-direction",
    )


def test_baseline_is_reproduced_verbatim_for_a_controlled_comparison() -> None:
    assert build_nav_prompt(Variant.BASELINE) == BASELINE_PROMPT
    assert "<字符串>" in BASELINE_PROMPT  # the fault being corrected, kept as control


@pytest.mark.parametrize("variant", _DETEMPLATED_VARIANTS)
def test_no_placeholder_token_survives_in_any_rebuilt_variant(variant: str) -> None:
    text = build_nav_prompt(variant)
    for token in _FORBIDDEN_PLACEHOLDERS:
        assert token not in text, f"{variant} still contains {token!r}"


@pytest.mark.parametrize("variant", _DETEMPLATED_VARIANTS)
def test_no_sampled_json_value_can_be_copied(variant: str) -> None:
    text = build_nav_prompt(variant)
    for marker in _SAMPLED_VALUE_MARKERS:
        assert marker not in text, f"{variant} still contains a copyable {marker!r}"


@pytest.mark.parametrize(
    "variant", (Variant.DETEMPLATED, Variant.STRICT)
)
def test_contract_variants_forbid_copying_and_fabrication(variant: str) -> None:
    text = build_nav_prompt(variant)
    assert "不得复制" in text or "禁止照抄" in text
    assert "不要编造" in text
    # The abstention wording must not name a token the model can echo instead of
    # abstaining: the 07A pilot saw the literal phrase 空字符串 come back.
    assert "不要输出任何字符" in text
    assert "空字符串" not in text


@pytest.mark.parametrize("variant", _DETEMPLATED_VARIANTS)
def test_variants_demand_visual_evidence_before_answering(variant: str) -> None:
    text = build_nav_prompt(variant)
    assert "车位编号" in text
    assert "立柱" in text
    assert "观察" in text


@pytest.mark.parametrize("variant", _DETEMPLATED_VARIANTS)
def test_the_target_may_only_be_claimed_when_it_is_visible(variant: str) -> None:
    text = build_nav_prompt(variant)
    assert DEFAULT_TARGET_LABEL in text
    assert "确实出现" in text or "是否出现" in text


def test_the_strict_variant_bans_all_zero_coordinates() -> None:
    text = build_nav_prompt(Variant.STRICT)
    assert "全为零的坐标" in text


def test_the_abstention_variant_is_not_a_contract_prompt() -> None:
    """It asks for a judgement in prose, so it cannot satisfy the v1 contract."""

    text = build_nav_prompt(Variant.ABSTENTION)
    assert "不要输出 JSON" in text
    assert "无法确定" in text


@pytest.mark.parametrize("variant", (Variant.DETEMPLATED, Variant.STRICT))
def test_the_literal_intent_id_is_the_only_identifier_offered(variant: str) -> None:
    text = build_nav_prompt(variant)
    assert DEFAULT_INTENT_ID in text
    assert text.count(DEFAULT_INTENT_ID) == 1


@pytest.mark.parametrize("variant", (Variant.DETEMPLATED, Variant.STRICT))
def test_the_message_keeps_the_image_first_and_the_prompt_last(variant: str) -> None:
    """The image path must not regress: the prompt is still the text part."""

    from vln.vlm.image_input import load_image_part
    from vln.vlm.server_client import build_image_messages
    from pathlib import Path

    image = sorted((Path(__file__).resolve().parents[2] / "images").glob("*.png"))[0]
    part = load_image_part(image)
    text = build_nav_prompt(variant)

    (message,) = build_image_messages(part, text)
    assert message["content"][0]["type"] == "image_url"
    assert message["content"][1] == {"type": "text", "text": text}
    assert "<字符串>" not in message["content"][1]["text"]


def test_the_grounding_probe_is_unchanged_from_06a() -> None:
    assert build_grounding_prompt() == GROUNDING_QUESTION
    assert "立柱" in GROUNDING_QUESTION


@pytest.mark.parametrize("variant", _DETEMPLATED_VARIANTS)
def test_a_custom_target_and_intent_id_are_carried_through(variant: str) -> None:
    text = build_nav_prompt(variant, target="A12", intent_id="custom-id-1")
    assert "A12" in text
    if variant != Variant.ABSTENTION:
        assert "custom-id-1" in text


def test_an_unknown_variant_is_refused_not_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown prompt variant"):
        build_nav_prompt("basline")  # a typo must not silently re-run the baseline


@pytest.mark.parametrize("kwargs", [{"target": ""}, {"target": "  "}, {"intent_id": ""}])
def test_blank_parameters_are_refused(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        build_nav_prompt(Variant.STRICT, **kwargs)


def test_the_module_imports_no_model_stack() -> None:
    import subprocess
    import sys

    code = (
        "import sys, vln.vlm.nav_prompt as m;"
        "bad=[x for x in ('torch','transformers') if x in sys.modules];"
        "assert not bad, bad;"
        "assert 'vln.client' not in sys.modules;"
        "assert callable(m.build_nav_prompt)"
    )
    root = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2] / "src"),
    )
    assert root.returncode == 0, root.stderr


# ----------------------------------------------------------------------
# 07B: the target-direction prompt (identify a visible bay, answer discretely)
# ----------------------------------------------------------------------


def _target_prompt(target: str = "D50") -> str:
    return build_nav_prompt(Variant.TARGET_DIRECTION, target=target)


def test_target_prompt_names_the_target_but_never_assumes_it_exists() -> None:
    text = _target_prompt("D50")
    assert "D50" in text
    assert "不得因为本指令提到它就假定它存在" in text


def test_target_prompt_asks_for_no_coordinate_and_no_json() -> None:
    """07B has no metric ground truth, so demanding numbers would invite invention."""

    text = _target_prompt()
    assert "不要输出任何坐标数值" in text
    assert "不要输出 JSON" in text
    # No field in the answer block asks for a number: every field name is followed
    # by a closed vocabulary or by prose.
    for numeric_field in ("x:", "y:", "heading:", "x =", "heading ="):
        assert numeric_field not in text


@pytest.mark.parametrize("marker", ["{", "}", "(0,0,0)", "0,0,0", "<", ">", "示例值"])
def test_target_prompt_carries_nothing_copyable(marker: str) -> None:
    """No braces, no placeholder brackets, no zero triple, no sample value."""

    assert marker not in _target_prompt()


def test_target_prompt_offers_unknown_alongside_every_real_answer() -> None:
    text = _target_prompt()
    assert UNKNOWN_ANSWER in text
    for answer in POSITION_ANSWERS[:-1]:
        assert answer in text
    for answer in DIRECTION_ANSWERS[:-1]:
        assert answer in text


def test_target_prompt_requires_evidence_for_a_positive_claim() -> None:
    assert "Evidence:" in _target_prompt()
    assert "视觉证据" in _target_prompt()


def test_target_prompt_orders_observation_before_the_decision() -> None:
    text = _target_prompt()
    assert text.index("第一步 观察") < text.index("第二步 查找目标")
    assert text.index("第二步 查找目标") < text.index("第三步 判断相对方位")
    assert text.index("第三步 判断相对方位") < text.index("第四步 给出下一步离散导航方向")


def test_target_prompt_block_lists_exactly_the_five_fields() -> None:
    text = _target_prompt()
    for field in ("Target:", "Visible:", "Relative position:", "Next direction:", "Evidence:"):
        assert field in text


def test_the_answer_vocabularies_are_closed_and_include_unknown() -> None:
    assert VISIBLE_ANSWERS == ("是", "否")
    assert POSITION_ANSWERS == ("LEFT", "RIGHT", "AHEAD", UNKNOWN_ANSWER)
    assert DIRECTION_ANSWERS == ("LEFT", "RIGHT", "STRAIGHT", UNKNOWN_ANSWER)


def test_target_prompt_is_offered_to_the_image_message_unchanged() -> None:
    from pathlib import Path

    from vln.vlm.image_input import load_image_part
    from vln.vlm.server_client import build_image_messages

    image = sorted((Path(__file__).resolve().parents[2] / "images").glob("*.png"))[0]
    text = _target_prompt("D50")
    (message,) = build_image_messages(load_image_part(image), text)
    assert message["content"][0]["type"] == "image_url"
    assert message["content"][1] == {"type": "text", "text": text}


# ----------------------------------------------------------------------
# 07C: the target *kind* and the optional extra note
# ----------------------------------------------------------------------


def test_the_bay_number_wording_is_still_the_default() -> None:
    """07B's prompt must stay byte-identical, or its recorded run stops matching."""

    default = _target_prompt("D50")
    explicit = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="D50", target_kind=DEFAULT_TARGET_KIND
    )
    assert default == explicit
    assert "本次要找的车位编号是 D50" in default
    assert "Target: 目标车位编号（照抄第二步给出的标识本身）" in default
    assert len(default) == 811


def test_a_custom_target_kind_replaces_the_noun_everywhere_it_matters() -> None:
    """07C found the model rejecting a visible sign as "not a bay number"."""

    text = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="出口", target_kind="目标标识"
    )
    assert "本次要找的目标标识是 出口" in text
    assert "Target: 目标目标标识（照抄第二步给出的标识本身）" in text
    assert "不得凭猜测补出目标标识" in text
    assert "本次要找的车位编号" not in text
    assert "目标车位编号" not in text


def test_the_target_note_is_absent_by_default_and_appended_when_given() -> None:
    default = _target_prompt("D50")
    note = "注意：地面上的车位编号在画面里是倒置的。"
    with_note = build_nav_prompt(Variant.TARGET_DIRECTION, target="D50", target_note=note)

    assert note not in default
    assert note in with_note
    assert with_note.startswith(default.split("第三步")[0])
    assert "第三步" in with_note  # the note goes after the target step, not instead of it


@pytest.mark.parametrize("kwargs", [{"target_kind": ""}, {"target_kind": "  "}, {"target_note": 3}])
def test_blank_or_non_string_new_parameters_are_refused(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        build_nav_prompt(Variant.TARGET_DIRECTION, target="D50", **kwargs)


def test_the_new_parameters_do_not_leak_into_the_other_variants() -> None:
    """Only TARGET_DIRECTION takes a target kind; the others ignore it harmlessly."""

    for variant in (Variant.DETEMPLATED, Variant.ABSTENTION, Variant.STRICT):
        assert build_nav_prompt(variant, target="A12", target_kind="目标标识") == (
            build_nav_prompt(variant, target="A12")
        )


# ----------------------------------------------------------------------
# 08A: the explicit identity field (identity scored apart from direction)
# ----------------------------------------------------------------------


def test_the_identity_field_is_absent_unless_it_is_asked_for() -> None:
    """07B's and 07C's recorded runs must still match the text they were sent."""

    default = _target_prompt("D50")
    explicit_off = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="D50", require_identity=False
    )
    assert default == explicit_off
    assert len(default) == 811
    assert IDENTITY_FIELD not in default
    assert "下面五个字段" in default


def test_the_identity_field_is_added_to_the_block_and_the_rules() -> None:
    text = build_nav_prompt(Variant.TARGET_DIRECTION, target="D50", require_identity=True)
    assert "下面六个字段" in text
    assert "下面五个字段" not in text
    # Once in the block, once in the rule that stops it echoing the target name.
    assert text.count(IDENTITY_FIELD) == 2
    assert "不得直接照抄 Target 行给出的目标名称" in text
    # The six block fields keep their order, with the identity directly after the
    # requested target so the two cannot be confused in the parsed output.
    order = [
        text.index(f"{field}:")
        for field in (
            "Target",
            IDENTITY_FIELD,
            "Visible",
            "Relative position",
            "Next direction",
            "Evidence",
        )
    ]
    assert order == sorted(order)


def test_the_identity_field_offers_cannot_determine_and_nothing_copyable() -> None:
    text = build_nav_prompt(Variant.TARGET_DIRECTION, target="D50", require_identity=True)
    identity_line = next(
        line for line in text.splitlines() if line.startswith(f"{IDENTITY_FIELD}:")
    )
    assert UNKNOWN_ANSWER in identity_line
    for token in _FORBIDDEN_PLACEHOLDERS + _SAMPLED_VALUE_MARKERS:
        assert token not in identity_line


def test_require_identity_must_be_a_bool() -> None:
    for bad in ("yes", 1, None):
        with pytest.raises(ValueError):
            build_nav_prompt(Variant.TARGET_DIRECTION, target="D50", require_identity=bad)


def test_require_identity_does_not_leak_into_the_other_variants() -> None:
    for variant in (Variant.DETEMPLATED, Variant.ABSTENTION, Variant.STRICT):
        assert build_nav_prompt(variant, target="A12", require_identity=True) == (
            build_nav_prompt(variant, target="A12")
        )


# ----------------------------------------------------------------------
# NAV-12B: the opt-in evidence-insufficiency rule
# ----------------------------------------------------------------------


def test_the_evidence_rule_is_absent_by_default_and_keeps_the_old_prompt() -> None:
    """Historical 07B/07C/08A/11C prompts must remain byte-identical."""

    default = _target_prompt("D50")
    assert len(default) == 811
    assert "证据不足、无法辨认或无法确定时写" not in default
    assert "Target 只回显本次要找的目标" not in default
    assert "Evidence: 你据以判断的可见证据（一句话）" in default


def test_the_evidence_rule_is_added_when_requested() -> None:
    text = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target="D50",
        require_identity=True,
        require_evidence=True,
    )
    assert "证据不足、无法辨认或无法确定时写 无法确定" in text
    assert "Target 只回显本次要找的目标，不代表画面中已经看到它" in text
    assert "Evidence 必须写「无法确定」" in text
    assert "Relative position 和 Next direction 也必须写「无法确定」" in text
    assert "下面六个字段" in text
    assert "Evidence: 你据以判断的可见证据（一句话）" not in text


def test_the_evidence_prompt_keeps_the_block_order_and_stays_copyable_free() -> None:
    text = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target="D50",
        require_identity=True,
        require_evidence=True,
    )
    order = [
        text.index(f"{field}:")
        for field in (
            "Target",
            IDENTITY_FIELD,
            "Visible",
            "Relative position",
            "Next direction",
            "Evidence",
        )
    ]
    assert order == sorted(order)
    for marker in _FORBIDDEN_PLACEHOLDERS + _SAMPLED_VALUE_MARKERS:
        assert marker not in text, f"the evidence prompt contains {marker!r}"


def test_the_evidence_rule_can_be_used_without_the_identity_field() -> None:
    text = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="D50", require_evidence=True
    )
    assert "下面五个字段" in text
    assert IDENTITY_FIELD not in text
    assert "6. Target 只回显本次要找的目标" in text
    assert "证据不足、无法辨认或无法确定时写 无法确定" in text


def test_require_evidence_must_be_a_bool() -> None:
    for bad in ("yes", 1, None):
        with pytest.raises(ValueError):
            build_nav_prompt(
                Variant.TARGET_DIRECTION, target="D50", require_evidence=bad
            )


def test_require_evidence_does_not_leak_into_the_other_variants() -> None:
    for variant in (Variant.DETEMPLATED, Variant.ABSTENTION, Variant.STRICT):
        assert build_nav_prompt(variant, target="A12", require_evidence=True) == (
            build_nav_prompt(variant, target="A12")
        )


def test_the_evidence_uncertainty_vocabulary_starts_with_the_prompt_answer() -> None:
    assert EVIDENCE_UNCERTAINTY_ANSWERS[0] == UNKNOWN_ANSWER
    assert "证据不足" in EVIDENCE_UNCERTAINTY_ANSWERS
    assert len(set(EVIDENCE_UNCERTAINTY_ANSWERS)) == len(
        EVIDENCE_UNCERTAINTY_ANSWERS
    )
    assert all(isinstance(token, str) and token for token in EVIDENCE_UNCERTAINTY_ANSWERS)
