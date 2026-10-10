"""Read the buffer layouts dxc prints in a shader's header comments.

`dxc -dumpbin` lists every cbuffer and structured buffer with its fields and
byte offsets ("uint k_systemidx;  ; Offset: 264"). This turns that block into
{buffer name: [(field, type, offset)]} so the host can pack constant buffers by
field name instead of by hand.

    python tools/rm_preview/reflect.py <shader.ll>
"""

from __future__ import annotations

import re
import struct
import sys

FIELD = re.compile(r";\s+(row_major\s+)?(\w+)\s+([\w\[\]]+);\s+; Offset:\s+(\d+)")


def layouts(text: str) -> dict:
    out, cur, depth = {}, None, 0
    for line in text.splitlines():
        if line.startswith("; Resource Bindings"):
            break
        m = re.match(r"; (cbuffer|Resource bind info for) (\w+)", line)
        if m:
            cur = m.group(2)
            out[cur] = []
            continue
        m = FIELD.match(line)
        if m and cur:
            out[cur].append((m.group(3), m.group(2), int(m.group(4))))
    return out


SIZES = {"uint": 4, "int": 4, "float": 4, "uint2": 8, "int2": 8, "float2": 8, "uint3": 12, "float3": 12,
         "uint4": 16, "float4": 16, "float4x4": 64, "float3x4": 48}


def pack(fields, values: dict, size: int | None = None) -> bytes:
    """Pack {field: value} into a buffer laid out like `fields`; unknown fields stay 0."""
    end = max((o + SIZES.get(t, 4) for _, t, o in fields), default=0)
    b = bytearray(size or ((end + 15) & ~15))
    names = {n.split("[")[0]: (t, o) for n, t, o in fields}
    for k, v in values.items():
        t, o = names[k]
        base = t.rstrip("0123456789x")
        fmt = "f" if base == "float" else ("i" if base == "int" else "I")
        vals = v if isinstance(v, (list, tuple)) else [v]
        flat = []
        for x in vals:
            flat.extend(x if isinstance(x, (list, tuple)) else [x])
        for i, x in enumerate(flat):
            struct.pack_into("<" + fmt, b, o + 4 * i, x if fmt == "f" else int(x) & 0xFFFFFFFF)
    return bytes(b)


if __name__ == "__main__":
    for name, fields in layouts(open(sys.argv[1], encoding="latin1").read()).items():
        print(name)
        for n, t, o in fields:
            print(f"    {o:4d}  {t:10s} {n}")
