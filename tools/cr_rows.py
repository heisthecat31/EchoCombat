"""Generic walk of a single-table CR component file (port of EchoConstruct cr_ownership.cpp).

[56-byte RadTable descriptor][count x row], rows owned by the actor nodeid at row +8; then,
row by row, each row's nested tables (descriptors at fixed row offsets, per type), element-major,
recursively. Rows and nested tables are 8-aligned (or the descriptor's alignment).

    python tools/cr_rows.py <type name> <file>
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass

DESC = 56

LEAF = ()
COMPONENT_LOD_ROW = ((64, LEAF),)
NESTED = {   # type name (without Win10) -> ((row offset of a nested descriptor, its shape), ...)
    "CComponentLODCR": ((40, COMPONENT_LOD_ROW),),
    "CR15NetCustomizationCR": ((72, LEAF),),
    "CComponentRegionLODCR": ((32, LEAF),),
    "CR15NetBalanceSettingsCR": ((32, LEAF),),
    "CR15NetCaptureVolumeCR": ((32, LEAF),),
    "CR15NetGhostLODCR": ((32, LEAF),),
    "CR15UIPage2ElementCR": ((32, LEAF),),
    "CR15NetAIWaypointCR": ((40, LEAF),),
    "CR15UILayoutCR": ((40, LEAF),),
    "CParticleEffectCR": ((96, LEAF),),
    "CActorJugglerCR": ((32, LEAF), (88, LEAF)),
    "CComponentLODZoneCR": ((32, LEAF), (88, LEAF)),
    "CLODRegionCR": ((32, LEAF), (88, LEAF), (144, LEAF)),
    "CR15UIPageCR": ((32, LEAF), (88, LEAF), (152, LEAF), (208, LEAF)),
    "CR15UIPage2CR": ((32, LEAF), (88, LEAF), (144, LEAF), (200, LEAF), (272, LEAF)),
    "CR15DialoguePOICR": tuple((o, LEAF) for o in (176, 232, 296, 352, 408)),
    "CListCR": tuple((o, LEAF) for o in (48, 104, 160, 216, 272, 328, 384)),
    "CBlackboardCR": tuple((o, LEAF) for o in range(32, 537, 56)),
    "CScriptCR": tuple((o, LEAF) for o in range(48, 665, 56)),
    "CR15NetVoipBroadcasterCR": ((32, ((0, LEAF),)),),
    "CR15NetPunchCR": ((40, ((0, LEAF),)),),
}


def align_up(n: int, a: int) -> int:
    return n if a <= 1 else (n + a - 1) // a * a


@dataclass
class Desc:
    size: int
    align: int
    flags: int
    grow: int
    cap: int
    count: int

    @classmethod
    def read(cls, b, at):
        p, size, alloc, align, flags, grow, cap, count = struct.unpack_from("<QQQIIQQQ", b, at)
        if p or alloc or cap < count or (cap and size % cap):
            raise ValueError(f"no table descriptor at {at:#x}")
        return cls(size, align, flags, grow, cap, count)

    @property
    def stride(self):
        return self.size // self.cap if self.cap else 0


def skip_table(b, desc_at, shape, cursor):
    d = Desc.read(b, desc_at)
    if d.count == 0:
        return cursor
    cursor = align_up(cursor, max(d.align, 8))
    rows = cursor
    cursor += d.count * d.stride
    for i in range(d.count):
        for off, sub in shape:
            cursor = skip_table(b, rows + i * d.stride + off, sub, cursor)
    return cursor


@dataclass
class Spans:
    stride: int
    rows_at: int
    rows: list      # [(start, end)]
    nested: list    # [(start, end)]
    owners: list


def spans(type_name: str, b: bytes) -> Spans:
    shape = NESTED.get(type_name.removesuffix("Win10"), LEAF)
    d = Desc.read(b, 0)
    cursor = align_up(DESC, max(d.align, 8)) if d.count else DESC
    s = Spans(d.stride, cursor, [], [], [])
    cursor += d.count * d.stride
    for i in range(d.count):
        row = s.rows_at + i * d.stride
        s.rows.append((row, row + d.stride))
        s.owners.append(struct.unpack_from("<Q", b, row + 8)[0])
        start = cursor
        for off, sub in shape:
            cursor = skip_table(b, row + off, sub, cursor)
        s.nested.append((start, cursor))
    if cursor != len(b):
        raise ValueError(f"{type_name}: walk ends at {cursor:#x}, file is {len(b):#x}")
    return s


if __name__ == "__main__":
    s = spans(sys.argv[1], open(sys.argv[2], "rb").read())
    print(f"{len(s.rows)} rows of {s.stride}, rows at {s.rows_at:#x}")
