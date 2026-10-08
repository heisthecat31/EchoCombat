"""TRANSLOCATOR: an effect and a sound when the player teleports.

The translocator's script (9398a165c004a9c0) teleports the player with its
R15TELEPORTPLAYERNODE (execute_node_3c80a3d4) and shows / plays nothing. This makes
that node, once the teleport is done, also

* spawn the stun field's burst (particle effect LOC_FX, the stun mine script's
  (190ed14ff6dc4ad8) execute_node_8ff76ff9 effect) where the player lands, killed after
  LOC_FX_TIME s, with the detonator script's SPAWNPARTICLEEFFECTNODE, and
* play sound event LOC_EVENT there with the detonator script's PLAYSOUNDNODE: an event
  veil_sound.py adds, playing media 279761503 on its own.

(The stun mine's other effect, de22b615c9c69cdd, is its lingering field: it loops
until killed, and is not the bubble.)

Both node classes are transplanted into the script as for UMBRAL VEIL (veil_fx.py):
their code, slots and strings go into a new section, and their Binds run after the
explosion node's Bind in setup_bindings. Each runs on the teleport node's own context
with the context's state reset to 0 first, so neither inherits the other's state (see
veil_fx: two node classes on one context otherwise clash).

    python tools/fix_loc_fx.py --src <dir with the stock scripts> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32                                          # noqa: E402
from veil_sound import LOC_EVENT                                          # noqa: E402
from veil_fx import (COLOR_B, COLOR_G, COLOR_R, ALPHA, EMISSION_RATE, LIFE, PARTICLE_SCALE,  # noqa: E402
                     PLAY_SOUND, SCALE, SPAWN_PARTICLE, VEIL, add_section, ring_offsets, sound_stub,
                     spawn_stub, transplant)

SCRIPTS = "6eace9f64204fd0"
LOC_SCRIPT = "9398a165c004a9c0"
DET_SCRIPT = "190ed14fe3da5ed1"
#: the stun field's burst (stun script, execute_node_8ff76ff9)
LOC_FX = 0x4CE12AE42C1B6269
LOC_FX_TIME = 2.5
LOC_FX_SCALE = 2.0          # the emitter's size and each particle's size
LOC_FX_LIFE = 2.5           # particle lifetime multiplier: how slowly it fades

TELEPORT_NODE = 0x7040                    # execute_node_3c80a3d4: R15TELEPORTPLAYERNODE
TELEPORT_OLD = bytes.fromhex("4c8bdc 49895b08 57")   # mov r11,rsp; mov [r11+8],rbx; push rdi
BIND_CALL, BIND_TARGET = 0x3725, 0x17E0   # setup_bindings: call R15NETACTIVATEEXPLOSIONNODE::Bind

# --- networked, as UMBRAL VEIL (plugin/veilnet.cpp) ------------------------------------
# The teleport node runs only on the teleporting player's machine (its thread starts
# from their trigger), so the effect and sound were theirs alone. Now the teleport also
# bumps LOC_COUNTER; VeilNet.dll sends that as a 'T' packet to the server, which relays
# it to every other client, and each of them gets a "translocator token" (LOC_TOKEN_RVA,
# the veil tokens' layout, 1.5 s). Every node any translocator puck runs goes through
# the script's dispatcher (DISPATCH); on a machine holding a token, the next one to run
# takes it and shows the effect and plays the sound on its own puck -- where the player
# lands. The teleporting machine holds no token, the server only relays.
#: echovr.exe spare bytes (see veil_fx: past .data, unused by the game)
LOC_TOKEN_RVA = 0x2104D20                 # +00 count, +08 expiry, +10 shown here
LOC_COUNTER_RVA = 0x2104D40               # u32, bumped by each teleport on this machine
DISPATCH = 0x5910                         # execute a node by its id (rcx = node ctx)
DISPATCH_OLD = bytes.fromhex("488b4110 ba35ee39e0")   # mov rax, [rcx+10h]; mov edx, 0e039ee35h


def patch(loc_pe: bytes, det_pe: bytes, fx: int = LOC_FX, sound: int = LOC_EVENT, scale: float = LOC_FX_SCALE,
          life: float = LOC_FX_LIFE, time: float = LOC_FX_TIME) -> bytes:
    pe, det = PE(loc_pe), PE(det_pe)
    if any(s[1] == VEIL.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("translocator script already patched")
    if pe.read(TELEPORT_NODE, len(TELEPORT_OLD)) != TELEPORT_OLD \
            or pe.read(DISPATCH, len(DISPATCH_OLD)) != DISPATCH_OLD \
            or pe.read(BIND_CALL, 5) != b"\xe8" + rel32(BIND_CALL + 5, BIND_TARGET):
        raise ValueError("unexpected translocator script build")

    blob, fixups = bytearray(), []
    spn = transplant(det, SPAWN_PARTICLE, blob, fixups)
    snd = transplant(det, PLAY_SOUND, blob, fixups)
    blob += bytes(-len(blob) % 16)
    ring = len(blob)
    blob += ring_offsets(1, 0.0)
    sizes = {"bind": 64, "spawn": 512, "sound": 128, "hook": 128, "tramp": 32, "dhook": 192, "dtramp": 32}
    parts = {}
    for name, size in sizes.items():
        blob += bytes(-len(blob) % 16)
        parts[name] = len(blob)
        blob += bytes(size)
    va = add_section(pe, VEIL, len(blob))
    for d, t in fixups:
        blob[d:d + 4] = rel32(va + d + 4, va + t)
    at = {k: va + o for k, o in parts.items()}

    def put(name, code):
        if len(code) > sizes[name]:
            raise ValueError(f"{name} stub too long")
        blob[parts[name]:parts[name] + len(code)] = code

    # Bind: the explosion node's, then the two transplanted classes' (node pair [rdi], [rdi+10h]).
    b = bytearray(bytes.fromhex("4883ec28 e8") + rel32(at["bind"] + 9, BIND_TARGET))
    for bind in (va + spn["bind"], va + snd["bind"]):
        b += bytes.fromhex("488b5710 488b0f e8") + rel32(at["bind"] + len(b) + 12, bind)
    b += bytes.fromhex("4883c428 c3")
    put("bind", bytes(b))

    floats = {EMISSION_RATE: 1.0, LIFE: life, ALPHA: 1.0, COLOR_R: 1.0, COLOR_G: 1.0, COLOR_B: 1.0}
    floats.update({o: scale for o in SCALE})
    floats.update({o: scale for o in PARTICLE_SCALE})
    put("spawn", spawn_stub(at["spawn"], va + spn["ctor"], va + spn["exec"], va + ring, 1, floats, asset=fx,
                                duration=time))
    put("sound", sound_stub(at["sound"], va + snd["ctor"], va + snd["exec"], sound))

    # the teleport node's first instructions, then on into it
    t = bytearray(TELEPORT_OLD + b"\xe9")
    t += rel32(at["tramp"] + len(t) + 4, TELEPORT_NODE + len(TELEPORT_OLD))
    put("tramp", bytes(t))
    # hook: the teleport node; once it is done (rax >= 0), the effect and the sound
    h = bytearray(bytes.fromhex("53 4883ec20 4889cb e8"))
    h += rel32(at["hook"] + len(h) + 4, at["tramp"])
    h += bytes.fromhex("4885c0 78")                                 # test rax,rax; js done
    js = len(h)
    h += b"\0"
    h += bytes.fromhex("6548a16000000000000000 488b4010 f0ff80") + struct.pack("<I", LOC_COUNTER_RVA)  # a teleport
    for stub in ("spawn", "sound"):
        h += bytes.fromhex("48c7431800000000 4889d9 e8")           # state 0; rcx = ctx; call
        h += rel32(at["hook"] + len(h) + 4, at[stub])
    h += bytes.fromhex("48c7431800000000 31c0")                     # state 0; done
    h[js] = len(h) - (js + 1)
    h += bytes.fromhex("4883c420 5b c3")
    put("hook", bytes(h))

    # the dispatcher's first two instructions, then on into it
    put("dtramp", DISPATCH_OLD + b"\xe9" + rel32(at["dtramp"] + len(DISPATCH_OLD) + 5, DISPATCH + len(DISPATCH_OLD)))
    # dispatcher hook (rcx = node ctx, kept): a translocator token here -> the effect and
    # the sound on this node's puck, the node's own state (ctx+18h) kept round them
    d = bytearray(bytes.fromhex("53 56 57 4883ec20 4889cb"))
    d += bytes.fromhex("6548a16000000000000000 4c8b4010 4d8d98") + struct.pack("<I", LOC_TOKEN_RVA)
    d += bytes.fromhex("49c7c10800fe7f 4d8b09 4d3b4b08 73")       # now >= expiry: no token
    j1 = len(d)
    d += b"\0"
    loop = len(d)
    d += bytes.fromhex("418b03 85c0 7e")                           # count <= 0: none left
    j2 = len(d)
    d += b"\0" + bytes.fromhex("8d48ff f0410fb10b 75")             # take one
    d += bytes([(loop - (len(d) + 1)) & 0xFF])
    d += bytes.fromhex("f041ff4310 488b7b18")                      # shown here; keep the node's state
    for stub in ("spawn", "sound"):
        d += bytes.fromhex("48c7431800000000 4889d9 e8")
        d += rel32(at["dhook"] + len(d) + 4, at[stub])
    d += bytes.fromhex("48897b18")
    d[j1] = d[j2] = 0                                              # patched below
    done = len(d)
    d[j1] = done - (j1 + 1)
    d[j2] = done - (j2 + 1)
    d += bytes.fromhex("4889d9 4883c420 5f 5e 5b e9")
    d += rel32(at["dhook"] + len(d) + 4, at["dtramp"])
    put("dhook", bytes(d))

    pe.write(va, bytes(blob))
    pe.write(DISPATCH, b"\xe9" + rel32(DISPATCH + 5, at["dhook"]) + b"\x90" * (len(DISPATCH_OLD) - 5))
    pe.write(BIND_CALL, b"\xe8" + rel32(BIND_CALL + 5, at["bind"]))
    pe.write(TELEPORT_NODE, b"\xe9" + rel32(TELEPORT_NODE + 5, at["hook"]) + b"\x90" * (len(TELEPORT_OLD) - 5))
    return bytes(pe.d)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="dir with 6eace9f64204fd0/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    ap.add_argument("--fx", type=lambda v: int(v, 16), default=LOC_FX, help="particle effect (hex)")
    ap.add_argument("--sound", type=int, default=LOC_EVENT, help="sound event id")
    ap.add_argument("--scale", type=float, default=LOC_FX_SCALE, help="effect size")
    ap.add_argument("--life", type=float, default=LOC_FX_LIFE, help="effect lifetime multiplier")
    ap.add_argument("--time", type=float, default=LOC_FX_TIME, help="effect killed after this many s (0: never)")
    args = ap.parse_args(argv[1:])
    loc = open(os.path.join(args.src, SCRIPTS, LOC_SCRIPT), "rb").read()
    det = open(os.path.join(args.src, SCRIPTS, DET_SCRIPT), "rb").read()
    mz, dmz = loc.find(b"MZ"), det.find(b"MZ")
    out = loc[:mz] + patch(loc[mz:], det[dmz:], args.fx, args.sound, args.scale, args.life, args.time)
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, LOC_SCRIPT), "wb").write(out)
    print(f"{SCRIPTS}/{LOC_SCRIPT}: translocator teleport -> effect {args.fx:016x} (x{args.scale}, "
          f"life x{args.life}, {args.time} s) and sound event {args.sound}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
