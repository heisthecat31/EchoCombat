"""rip-relative operands of a function in a script DLL, found by disassembling it.

transplant() (veil_fx.py) needs, per copied function, the offset of every
rip-relative disp32 so it can re-aim them. Those lists were written by hand
for the detonator's nodes; this finds them with llvm-objdump for any function.

    python tools/pe_reloc.py <dll> <rva> <size>
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys

OBJDUMP = next((t for t in ("llvm-objdump", "llvm-objdump-18", "llvm-objdump-17") if shutil.which(t)), None)


def rip_disps(dll_path: str, rva: int, size: int, image_base: int = 0x180000000) -> list[int]:
    """Offsets (from the function start) of each rip-relative disp32."""
    if not OBJDUMP:
        raise RuntimeError("llvm-objdump is needed to find relocations")
    out = subprocess.run([OBJDUMP, "-d", f"--start-address={image_base + rva:#x}",
                          f"--stop-address={image_base + rva + size:#x}", dll_path],
                         capture_output=True, text=True, check=True).stdout
    disps = []
    for line in out.splitlines():
        m = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)", line)
        if not m or "(%rip)" not in m.group(3):
            continue
        addr, raw = int(m.group(1), 16), bytes.fromhex(m.group(2).replace(" ", ""))
        t = re.search(r"#\s*0x([0-9a-f]+)", m.group(3))
        if not t:
            continue
        nxt = addr + len(raw)
        want = struct.pack("<i", int(t.group(1), 16) - nxt)
        i = raw.rfind(want)
        if i < 0:
            raise ValueError(f"disp not found at {addr:#x}: {m.group(3)}")
        disps.append(addr + i - (image_base + rva))
    return disps


if __name__ == "__main__":
    print([hex(x) for x in rip_disps(sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0))])
