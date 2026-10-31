"""Deterministic parser for one natural-language parking instruction.

The instruction is the *task*, not the target identity. This module therefore
extracts only attributes the system can reason about:

* ``occupancy`` - vacant / occupied / unspecified;
* ``side`` - LEFT / RIGHT / AHEAD / unspecified;
* ``landmark`` - ``near_exit`` when the instruction asks for a bay near an exit.

It never extracts a bay id, a bay number or a coordinate. An instruction that
names one is refused (:class:`ParkingInstructionError`): candidate generation
must come from scene geometry, never from a pre-written target id in the prompt.

The exit landmark is parsed but deliberately **not** marked verified. This
project has no calibrated exit anchor, so the binding layer must not use the
landmark to break a tie; it may only report it. Treating an unverified landmark
as a hard constraint would be the same class of fabrication the rest of this
package refuses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "OCCUPANCY_VACANT",
    "OCCUPANCY_OCCUPIED",
    "OCCUPANCY_UNSPECIFIED",
    "SIDE_LEFT",
    "SIDE_RIGHT",
    "SIDE_AHEAD",
    "SIDE_UNSPECIFIED",
    "LANDMARK_NEAR_EXIT",
    "TARGET_KIND_BAY",
    "ParkingInstruction",
    "ParkingInstructionError",
    "parse_parking_instruction",
]


OCCUPANCY_VACANT = "vacant"
OCCUPANCY_OCCUPIED = "occupied"
OCCUPANCY_UNSPECIFIED = "unspecified"
OCCUPANCY_VALUES = frozenset(
    {OCCUPANCY_VACANT, OCCUPANCY_OCCUPIED, OCCUPANCY_UNSPECIFIED}
)

SIDE_LEFT = "LEFT"
SIDE_RIGHT = "RIGHT"
SIDE_AHEAD = "AHEAD"
SIDE_UNSPECIFIED = "unspecified"
SIDE_VALUES = frozenset({SIDE_LEFT, SIDE_RIGHT, SIDE_AHEAD, SIDE_UNSPECIFIED})

LANDMARK_NEAR_EXIT = "near_exit"

TARGET_KIND_BAY = "车位"

_VACANT_TOKENS = ("空闲", "空位", "空车位", "没有车", "无车", "未被占用", "未占用")
_OCCUPIED_TOKENS = ("已占用", "被占用", "占用", "有车")
_EXIT_TOKENS = (
    "靠近出口",
    "临近出口",
    "近出口",
    "出口附近",
    "出口旁边",
    "出口旁",
    "靠出口",
)
_LEFT_TOKENS = ("左侧", "左边", "左方", "左手边", "向左", "靠左", "左前")
_RIGHT_TOKENS = ("右侧", "右边", "右方", "右手边", "向右", "靠右", "右前")
_AHEAD_TOKENS = ("正前方", "前方", "前面", "车头方向")

#: Bay ids appear in the scene, not in the task. ``B03``/``03号车位``/``车位03``
#: are all refused so a caller cannot smuggle a pre-written target through the
#: natural-language path.
_TARGET_ID_PATTERNS = (
    re.compile(r"车位\s*(?:编号|号)?\s*[:：]?\s*[A-Za-z]?\d+"),
    re.compile(r"\d+\s*号\s*车位"),
    re.compile(r"[A-Za-z]\d{1,3}\s*(?:号)?\s*车位"),
    re.compile(r"车位\s*[A-Za-z]\d{1,3}"),
)

_UNSUPPORTED_TARGET_TOKENS = ("充电", "残疾人", "货车位", "摩托车位", "女士车位")
_UNSUPPORTED_LANDMARK_TOKENS = (
    "电梯",
    "楼梯",
    "入口",
    "大门",
    "柱子",
    "充电桩",
    "广告牌",
)

_WS_RE = re.compile(r"[\s\u3000]+")


class ParkingInstructionError(ValueError):
    """The instruction is unsupported, contradictory, or names a target id."""


@dataclass(frozen=True)
class ParkingInstruction:
    """The attributes a parking task may carry, with no scene identity."""

    raw: str
    target_kind: str
    occupancy: str
    side: str
    landmark: str
    landmark_verified: bool = False
    notes: tuple[str, ...] = ()

    def to_metadata(self) -> dict:
        return {
            "raw": self.raw,
            "target_kind": self.target_kind,
            "occupancy": self.occupancy,
            "side": self.side,
            "landmark": self.landmark,
            "landmark_verified": self.landmark_verified,
            "notes": list(self.notes),
        }


def _compact(text: str) -> str:
    return _WS_RE.sub("", text)


def _find_landmark(text: str) -> str:
    if any(token in text for token in _EXIT_TOKENS):
        return LANDMARK_NEAR_EXIT
    for token in _UNSUPPORTED_LANDMARK_TOKENS:
        if token in text:
            raise ParkingInstructionError(
                f"unsupported landmark {token!r}: the scene has no verified "
                "anchor for it"
            )
    return ""


def _find_occupancy(text: str) -> str:
    vacant = any(token in text for token in _VACANT_TOKENS)
    occupied = any(token in text for token in _OCCUPIED_TOKENS)
    if vacant and occupied:
        raise ParkingInstructionError(
            "contradictory occupancy: the instruction asks for both a vacant "
            "and an occupied bay"
        )
    if occupied:
        raise ParkingInstructionError(
            "the instruction asks for an occupied bay; a parking task must "
            "name a vacant bay"
        )
    return OCCUPANCY_VACANT if vacant else OCCUPANCY_UNSPECIFIED


def _find_side(text: str) -> str:
    found = []
    if any(token in text for token in _LEFT_TOKENS):
        found.append(SIDE_LEFT)
    if any(token in text for token in _RIGHT_TOKENS):
        found.append(SIDE_RIGHT)
    # A compound 左前方/右前方 is a lateral instruction; the lateral component
    # is what the candidate filter can check, so it wins over the AHEAD token.
    if not found and any(token in text for token in _AHEAD_TOKENS):
        found.append(SIDE_AHEAD)
    if len(found) > 1:
        raise ParkingInstructionError(
            f"contradictory side: the instruction names {found}"
        )
    return found[0] if found else SIDE_UNSPECIFIED


def parse_parking_instruction(text: str) -> ParkingInstruction:
    """Parse one instruction, refusing anything the binding layer cannot check."""

    if type(text) is not str:
        raise ParkingInstructionError(
            f"instruction must be a string, got {type(text).__name__}"
        )
    raw = text.strip()
    if raw == "":
        raise ParkingInstructionError("instruction is blank")
    compact = _compact(raw)

    if "车位" not in compact:
        raise ParkingInstructionError(
            "unsupported target: the instruction must ask for a 车位"
        )
    for token in _UNSUPPORTED_TARGET_TOKENS:
        if token in compact:
            raise ParkingInstructionError(
                f"unsupported parking target {token!r}"
            )
    for pattern in _TARGET_ID_PATTERNS:
        match = pattern.search(compact)
        if match is not None:
            raise ParkingInstructionError(
                "instruction names an explicit target id "
                f"{match.group(0)!r}; candidates must come from scene geometry"
            )

    notes = []
    landmark = _find_landmark(compact)
    if landmark == LANDMARK_NEAR_EXIT:
        notes.append(
            "landmark near_exit is advisory only: no verified exit anchor exists"
        )

    return ParkingInstruction(
        raw=raw,
        target_kind=TARGET_KIND_BAY,
        occupancy=_find_occupancy(compact),
        side=_find_side(compact),
        landmark=landmark,
        landmark_verified=False,
        notes=tuple(notes),
    )
