"""Pull DXBC shaders out of shader assets and disassemble them.

A particle effect (3ae7c41914252baa) names one shader asset per emitter. Each is a
pair: 1173fb0c062915d3/<id> (768 B header) and 77fc096173af254c/<id> (the code).
The code asset holds a small table at +0xE0 (one 0x20-byte row per shader:
symbol, offset, size, kind) and then the shaders back to back, uncompressed,
starting at the first 'DXBC'. They are DXIL (shader model 6) compute shaders,
generated per effect from its particle graph ("SG"): typically emit + update
(+ init). Field names survive in the reflection data (gPSysTable, gEmitterTable,
k_curve_tex_idx, ...), so `dxc -dumpbin` gives readable IR.

The engine's own (global) shaders live in 635f6220ae85fd46 in the same way.
Anything that is not DXIL falls back to d3dcompiler_47's D3DDisassemble.

    python tools/rm_preview/particle_shaders.py --src <dir of a type folder> --out <dir>
        [--only id,id] [--dxc J:/dxc/bin/x64/dxc.exe]
"""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import subprocess


def blobs(data: bytes):
    """(offset from first DXBC, bytes) for every shader in a code asset."""
    base = i = data.find(b"DXBC")
    while 0 <= i < len(data):
        size = struct.unpack_from("<I", data, i + 24)[0]
        if size < 32 or i + size > len(data):
            break
        yield i - base, data[i:i + size]
        i = data.find(b"DXBC", i + size)


def chunks(code: bytes):
    n = struct.unpack_from("<I", code, 28)[0]
    return [code[o:o + 4] for o in struct.unpack_from(f"<{n}I", code, 32)]


def d3d_disasm(code: bytes) -> str:
    d3d = ctypes.WinDLL("d3dcompiler_47.dll")
    p = ctypes.c_void_p()
    if d3d.D3DDisassemble(code, len(code), 0, None, ctypes.byref(p)):
        return "; D3DDisassemble failed"
    vt = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vt[3])(p)
    n = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vt[4])(p)
    return ctypes.string_at(ptr, n).decode("latin1")


def kind_of(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("; ") and s.endswith(" Shader"):
            return s[2:]
        if s[:6] in ("cs_5_0", "vs_5_0", "ps_5_0", "gs_5_0", "hs_5_0", "ds_5_0"):
            return s[:6]
    return "?"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="a type folder, e.g. <extract>/77fc096173af254c")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="", help="comma-separated asset ids")
    ap.add_argument("--dxc", default="J:/dxc/bin/x64/dxc.exe")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    only = set(x for x in a.only.split(",") if x)
    for name in sorted(os.listdir(a.src)):
        if only and name not in only:
            continue
        data = open(os.path.join(a.src, name), "rb").read()
        for off, code in blobs(data):
            stem = os.path.join(a.out, f"{name}_{off:05x}")
            open(stem + ".dxbc", "wb").write(code)
            if b"DXIL" in chunks(code):
                subprocess.run([a.dxc, "-dumpbin", stem + ".dxbc", "-Fc", stem + ".ll"], capture_output=True)
                path = stem + ".ll"
            else:
                path = stem + ".asm"
                open(path, "w", encoding="latin1").write(d3d_disasm(code))
            text = open(path, encoding="latin1").read() if os.path.exists(path) else ""
            print(f"{name} +{off:#07x} {len(code):6d} B  {kind_of(text)}")


if __name__ == "__main__":
    main()
