"""Give the DOT FIELD a working remote trigger: throw it, then pull the trigger to activate.

The DOT script (`mp_combat_grenade_dot`, 97d0806e6ea89130) already contains the
activation code. Its one exported function (`2fc48a8b48754599`) checks
`use_remote_trigger`, that it runs on the owner's client and that the field
has been thrown (Unstable), then stops it and sets the magazine state that its
server side reacts to by starting the field. Nothing ever calls that function.
When grabbed, released or deposited, the DOT script also calls four external
functions (a150b1c25e86ac18, 048bcc7d19348703, 048bcc7d19398c03,
4cc1130866b48fc1) that were meant to come from a companion trigger script.
No script among the 567 in the PC extract defines them or calls the DOT
export, so that companion script was never shipped.

The detonator's own script (`190ed14fe3da5ed1`) has the same trigger plumbing:

* onspawnedlocal -> EnableComponent(R15Trigger)
* attachhand     -> on the owner's client, R15SetTriggerHand(R15Trigger, holding hand)
* OnTriggered    -> on the owner's client, if its flags are clear and it is not
                    held, SetState(e32dc7dfd49f50a9), the state both the
                    detonator's and the DOT's server side react to

This tool makes a trimmed copy of that script, `mp_combat_grenade_dot_trigger`
(CSymbol64 4e8af51fe7d6af8c), plus the `CScriptResourceWin10` entry every script
also has (4 zero bytes, identical for all of them), and attaches it to the DOT magazine as a third
script after the shared magazine script and its own. In the copy:

* the onstatechanged handlers (both: the server one that fires the detonator's
  explosion and sets Exploded, and the client one with its visuals) never match,
  so the DOT's own field logic is the only reaction to the state change
* the ondeposited, ontypechanged and onspawnedremote handlers never match
* the onspawnedlocal chain stops after enabling the trigger, so the detonator's
  spawn sound is not played

Each patch site is checked against the expected original bytes first.

Use it with the `trigger` preset of `fix_dot.py` (`use_remote_trigger` on,
`activate_on_collision` off). With `stick_to_geo` on, the DOT script's own
impact handling stops the field where it hits; the native weld stays off via
`fix_dot_stick.py` / `fix_dot_constraints.py`.

    python tools/fix_dot_trigger.py --src <extract root> --out <dir>

`CScriptCRWin10` is also edited by `fix_drone_script.py`. If `<out>` already
holds a level's script table, that copy is patched instead of the pristine one,
so the two stack in either order.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
SCRIPT_RESOURCE = "991421b41de58370"   # CSymbol64("CScriptResourceWin10")
#: Every script's CScriptResourceWin10 entry is these 4 bytes; the level resolves
#: the script through it before loading the DLL, so the new script needs one too.
SCRIPT_RESOURCE_BODY = bytes(4)
SCRIPT_CR = "d99f6bbd8009c92c"         # CSymbol64("CScriptCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DET_SCRIPT = 0x190ED14FE3DA5ED1
DOT_SCRIPT = 0x97D0806E6EA89130
TRIGGER_SCRIPT = 0x4E8AF51FE7D6AF8C     # CSymbol64("mp_combat_grenade_dot_trigger")
DOT_ACTOR = 0x0C00C9AC34BD2832

#: (rva, original bytes, patched bytes) in the detonator script's PE image.
#: The event constants are `movabs reg, imm64`; only the immediate changes.
_DEAD = b"\x01\xd0\x7d\x0d\xde\xad\x7d\x0d"


def _imm(rva, original):
    return rva + 2, struct.pack("<Q", original), _DEAD[:-1] + bytes([rva & 0xFF])


PATCHES = [
    _imm(0xB8EF, 0xD15AF7A86BF42202),   # delegate_onstatechanged (server + client)
    _imm(0xBA9A, 0x0360CE7DFC51DD43),   # delegate_onspawnedremote
    _imm(0xBB22, 0x088725A83299F252),   # delegate_ondeposited
    _imm(0xBBAA, 0x71B428190A37733E),   # delegate_ontypechanged
    # next_node, node 75014b69 -> 70415af5 (client check, then spawn sound):
    # `mov eax, 0x70415af5; ret` becomes `or rax, -1; ret`, the end-of-thread value.
    (0xC3C1, bytes.fromhex("b8f55a4170c3"), bytes.fromhex("4883c8ffc3c3")),
]

HDR = 0x38
STRIDE = 720


def u64(blob, offset):
    return struct.unpack_from("<Q", blob, offset)[0]


def rva_to_raw(pe: bytes, rva: int) -> int:
    e = struct.unpack_from("<I", pe, 0x3C)[0]
    nsec = struct.unpack_from("<H", pe, e + 6)[0]
    opt = struct.unpack_from("<H", pe, e + 20)[0]
    for i in range(nsec):
        so = e + 24 + opt + i * 40
        vsize, va, rsize, raw = struct.unpack_from("<IIII", pe, so + 8)
        if va <= rva < va + max(vsize, rsize):
            return raw + rva - va
    raise ValueError(f"rva {rva:#x} not in any section")


def build_script(det_asset: bytes) -> bytes:
    mz = det_asset.find(b"MZ")
    if mz < 0:
        raise ValueError("no PE image in the detonator script asset")
    out = bytearray(det_asset)
    for rva, old, new in PATCHES:
        at = mz + rva_to_raw(det_asset[mz:], rva)
        if out[at:at + len(old)] != old:
            raise ValueError(f"unexpected bytes at rva {rva:#x}: wrong detonator script build")
        out[at:at + len(new)] = new
    return bytes(out)


def attach(blob: bytes) -> bytes:
    count = u64(blob, 0x28)
    if u64(blob, 0x08) != count * STRIDE or u64(blob, 0x30) != count:
        raise ValueError("unexpected CScriptCR framing")
    entries = [blob[HDR + STRIDE * i:HDR + STRIDE * (i + 1)] for i in range(count)]
    pool = blob[HDR + STRIDE * count:]
    if any(u64(e, 8) == DOT_ACTOR and u64(e, 32) == TRIGGER_SCRIPT for e in entries):
        return blob                                   # already attached
    own = [i for i, e in enumerate(entries) if u64(e, 8) == DOT_ACTOR and u64(e, 32) == DOT_SCRIPT]
    donors = [e for e in entries if u64(e, 0) == DET_SCRIPT and u64(e, 32) == DET_SCRIPT]
    if len(own) != 1 or not donors:
        raise ValueError("DOT entry or detonator-script donor not found")
    entry = bytearray(donors[0])
    for offset in (48, 104, 160, 216, 272, 328, 384, 440, 496, 552, 608, 664):
        if u64(entry, offset + 8):
            raise ValueError("detonator script entry carries pool data; a plain copy is not enough")
    struct.pack_into("<Q", entry, 0, TRIGGER_SCRIPT)
    struct.pack_into("<Q", entry, 8, DOT_ACTOR)
    struct.pack_into("<Q", entry, 32, TRIGGER_SCRIPT)
    entries.insert(own[0] + 1, bytes(entry))

    head = bytearray(blob[:HDR])
    struct.pack_into("<Q", head, 0x08, len(entries) * STRIDE)
    struct.pack_into("<Q", head, 0x28, len(entries))
    struct.pack_into("<Q", head, 0x30, len(entries))
    return bytes(head) + b"".join(entries) + pool


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])

    det = open(os.path.join(args.src, SCRIPTS, f"{DET_SCRIPT:x}"), "rb").read()
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, f"{TRIGGER_SCRIPT:x}"), "wb").write(build_script(det))
    print(f"{SCRIPTS}/{TRIGGER_SCRIPT:x}: mp_combat_grenade_dot_trigger "
          f"(detonator script, {len(PATCHES)} patches)")
    os.makedirs(os.path.join(args.out, SCRIPT_RESOURCE), exist_ok=True)
    open(os.path.join(args.out, SCRIPT_RESOURCE, f"{TRIGGER_SCRIPT:x}"), "wb").write(SCRIPT_RESOURCE_BODY)
    print(f"{SCRIPT_RESOURCE}/{TRIGGER_SCRIPT:x}: its CScriptResourceWin10 entry")

    os.makedirs(os.path.join(args.out, SCRIPT_CR), exist_ok=True)
    for level, name in LEVELS.items():
        staged = os.path.join(args.out, SCRIPT_CR, level)
        src = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPT_CR, level)
        blob = open(src, "rb").read()
        fixed = attach(blob)
        open(staged, "wb").write(fixed)
        print(f"{name}: {u64(blob, 0x28)} -> {u64(fixed, 0x28)} script entries"
              f"{' (on top of staged copy)' if src == staged else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
