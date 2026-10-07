"""Pull the PE image out of a `StreamingScriptWin10` asset and look inside it.

Each streaming script is a 20-byte resource header followed by a complete DLL:

    0x00  u64   unknown (two hashes, stable per build)
    0x10  u32   unknown
    0x14  ...   `MZ` -- start of the PE image, runs to EOF

The DLL exports only `setup_bindings`, so nothing useful comes from the export
table.  What does work is chasing CSymbol64 constants: the script asks the
engine for a tuning value by the hash of the full JSON path, e.g.
`CSymbol64("grenade_properties|dot|stick_to_geo")`, and those 8-byte constants
sit in `.rdata` where they can be found and cross-referenced back into code.

    python tools/script_pe.py extract <asset> <out.dll>
    python tools/script_pe.py info    <asset>
    python tools/script_pe.py find    <asset> <name>     # locate a CSymbol64
    python tools/script_pe.py xref    <asset> <name>     # disassemble around it
"""

from __future__ import annotations

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYMBOL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)), "lone_echo_blender", "scripts")
for _p in (_HERE, _SYMBOL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from le_symbol_names import symbol64

SCRIPTS = r"H:\pcvr-extracted\6eace9f64204fd0"


def resolve(asset: str) -> str:
    """Accept a bare hash or a full path."""
    return asset if os.path.sep in asset or os.path.exists(asset) else \
        os.path.join(SCRIPTS, asset)


def image(asset: str) -> bytes:
    blob = open(resolve(asset), "rb").read()
    mz = blob.find(b"MZ")
    if mz < 0:
        raise ValueError("no PE image in this asset")
    return blob[mz:]


def sections(pe: bytes):
    """`[(name, virtual_address, raw_offset, raw_size, virtual_size)]`."""
    e = struct.unpack_from("<I", pe, 0x3C)[0]
    nsec = struct.unpack_from("<H", pe, e + 6)[0]
    opt = struct.unpack_from("<H", pe, e + 20)[0]
    out = []
    for i in range(nsec):
        so = e + 24 + opt + i * 40
        name = pe[so:so + 8].rstrip(b"\0").decode("ascii", "replace")
        vsz, va, rsz, ra = struct.unpack_from("<IIII", pe, so + 8)
        out.append((name, va, ra, rsz, vsz))
    return out


def image_base(pe: bytes) -> int:
    e = struct.unpack_from("<I", pe, 0x3C)[0]
    opt = e + 24
    magic = struct.unpack_from("<H", pe, opt)[0]
    return struct.unpack_from("<Q", pe, opt + 24)[0] if magic == 0x20B else \
        struct.unpack_from("<I", pe, opt + 28)[0]


def off_to_rva(pe: bytes, off: int):
    for _n, va, ra, rsz, _vsz in sections(pe):
        if ra <= off < ra + rsz:
            return va + (off - ra)
    return None


def rva_to_off(pe: bytes, rva: int):
    for _n, va, ra, rsz, vsz in sections(pe):
        if va <= rva < va + max(rsz, vsz):
            return ra + (rva - va)
    return None


def section_of(pe: bytes, off: int) -> str:
    for n, _va, ra, rsz, _vsz in sections(pe):
        if ra <= off < ra + rsz:
            return n
    return "?"


def find_const(pe: bytes, value: int):
    """Every file offset holding `value` as a little-endian u64."""
    needle = value.to_bytes(8, "little")
    out, i = [], pe.find(needle)
    while i >= 0:
        out.append(i)
        i = pe.find(needle, i + 1)
    return out


def code_refs(pe: bytes, target_rva: int):
    """RIP-relative references to `target_rva` from executable sections."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    base = image_base(pe)
    hits = []
    for name, va, ra, rsz, _vsz in sections(pe):
        if name not in (".text",):
            continue
        code = pe[ra:ra + rsz]
        for ins in md.disasm(code, base + va):
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_MEM and \
                        op.mem.base == capstone.x86.X86_REG_RIP:
                    if ins.address + ins.size + op.mem.disp == base + target_rva:
                        hits.append(ins.address)
    return hits


def disasm_at(pe: bytes, addr: int, before: int = 40, after: int = 90):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    base = image_base(pe)
    rva = addr - base
    off = rva_to_off(pe, rva)
    start = max(0, off - before)
    out = []
    for ins in md.disasm(pe[start:off + after], base + off_to_rva(pe, start)):
        out.append((ins.address, ins.mnemonic, ins.op_str))
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, asset = argv[1], argv[2]
    pe = image(asset)

    if cmd == "extract":
        open(argv[3], "wb").write(pe)
        print(f"wrote {argv[3]}  ({len(pe):,} B)")
        return 0

    if cmd == "info":
        print(f"image size {len(pe):,}  base 0x{image_base(pe):x}")
        for n, va, ra, rsz, vsz in sections(pe):
            print(f"  {n:<9} rva 0x{va:08x}  raw 0x{ra:08x}  "
                  f"raw_size {rsz:>9,}  virt_size {vsz:>9,}")
        return 0

    if cmd in ("find", "xref"):
        name = argv[3]
        value = int(symbol64(name), 16)
        offs = find_const(pe, value)
        print(f'CSymbol64("{name}") = 0x{value:016x}')
        if not offs:
            print("  not present in this script")
            return 1
        for off in offs:
            rva = off_to_rva(pe, off)
            print(f"  offset 0x{off:x}  section {section_of(pe, off)}  "
                  f"rva 0x{rva:x}")
            if cmd == "xref":
                refs = code_refs(pe, rva)
                print(f"    {len(refs)} code reference(s)")
                for r in refs:
                    print(f"    --- 0x{r:x} ---")
                    for a, m, o in disasm_at(pe, r):
                        mark = ">>" if a == r else "  "
                        print(f"      {mark} 0x{a:x}  {m:<8} {o}")
        return 0

    print(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
