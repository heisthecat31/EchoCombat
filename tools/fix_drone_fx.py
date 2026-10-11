"""DRONE: an explosion where it is shot down.

When a drone's health runs out, DroneFix.dll turns it off (dronefix.cpp, Shutdown), on the
server and on every client (VeilNet.dll's 'K'), and puts a "drone death token" on that
machine (DEATH_TOKEN_RVA, the veil tokens' layout: +00 count, +08 expiry, +10 shown here).
A dead drone's script runs nothing more, so the token alone never spawns it (tested). So
every node any drone runs, through the drone script's dispatcher (DISPATCH), also leaves its
node context (+20) and the spawn and sound stubs' addresses (+28, +30) there; DroneFix keeps the context of
each drone's release and, when that drone dies, calls the stub with it on the game thread:
the detonator's explosion smoke (DEATH_FX) and POINT's sound (DEATH_EVENT) on that drone. (A token still works as for the
translocator, fix_loc_fx.py, should one be set while a drone's nodes run.)

The spawn node class is transplanted from the detonator script as for UMBRAL VEIL
(veil_fx.py): its code, slots and strings go into a new section, its Bind runs after the
last plain Bind in setup_bindings (BIND_CALL).

    python tools/fix_drone_fx.py --src <dir with the stock scripts> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32                                          # noqa: E402
from veil_fx import (COLOR_B, COLOR_G, COLOR_R, ALPHA, DET_FX, EMISSION_RATE, LIFE, PARTICLE_SCALE,  # noqa: E402
                     PLAY_SOUND, SCALE, SPAWN_PARTICLE, VEIL, add_section, ring_offsets, sound_stub,
                     spawn_stub, transplant)
from veil_sound import POINT_SND_EVENT                                  # noqa: E402
from echocombat_config import section                                    # noqa: E402

SCRIPTS = "6eace9f64204fd0"
DRONE_SCRIPT = "221a0a3a2e56d247"         # mp_combat_ordnance_drone
DET_SCRIPT = "190ed14fe3da5ed1"
DRONE = section("grenade_properties", "drone")                           # config/mp_weapon_settings.json
DEATH_FX = DET_FX                         # the detonator's explosion smoke
DEATH_FX_TIME = DRONE.get("death_effect_time", 2.0)
DEATH_FX_SCALE = DRONE.get("death_effect_size", 1.0)
DEATH_FX_LIFE = DRONE.get("death_effect_lifetime", 1.0)
#: its sound: POINT's (an arc mine's explosion, in the veil bank every match loads, 3D)
DEATH_EVENT = DRONE.get("death_sound_event", POINT_SND_EVENT)
#: echovr.exe spare bytes (see veil_fx: past .data, unused by the game); dronefix.cpp's
DEATH_TOKEN_RVA = 0x2104D60               # +00 count, +08 expiry, +10 shown, +18 nodes run,
                                          # +20 last node ctx, +28 the spawn stub, +30 the sound stub
DISPATCH = 0x5D74                         # execute a node by its id (rcx = node ctx)
DISPATCH_OLD = bytes.fromhex("488b4110 ba48465cca")   # mov rax, [rcx+10h]; mov edx, 0ca5c4648h
BIND_CALL, BIND_TARGET = 0x3EE5, 0x2840   # setup_bindings: the last plain call to a node class's Bind


def patch(drone_pe: bytes, det_pe: bytes, fx: int = DEATH_FX, scale: float = DEATH_FX_SCALE,
          life: float = DEATH_FX_LIFE, time: float = DEATH_FX_TIME, sound: int = DEATH_EVENT) -> bytes:
    pe, det = PE(drone_pe), PE(det_pe)
    if any(s[1] == VEIL.rstrip(b"\0") for s in pe.sections()):
        raise ValueError("drone script already patched")
    if pe.read(DISPATCH, len(DISPATCH_OLD)) != DISPATCH_OLD \
            or pe.read(BIND_CALL, 5) != b"\xe8" + rel32(BIND_CALL + 5, BIND_TARGET):
        raise ValueError("unexpected drone script build")

    blob, fixups = bytearray(), []
    spn = transplant(det, SPAWN_PARTICLE, blob, fixups)
    snd = transplant(det, PLAY_SOUND, blob, fixups)
    blob += bytes(-len(blob) % 16)
    ring = len(blob)
    blob += ring_offsets(1, 0.0)
    sizes = {"bind": 64, "spawn": 512, "sound": 128, "dhook": 192, "dtramp": 32}
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

    # Bind: the original call's, then the transplanted class's (node pair [rdi], [rdi+10h]).
    b = bytearray(bytes.fromhex("4883ec28 e8") + rel32(at["bind"] + 9, BIND_TARGET))
    for cls in (spn, snd):
        b += bytes.fromhex("488b5710 488b0f e8") + rel32(at["bind"] + len(b) + 12, va + cls["bind"])
    b += bytes.fromhex("4883c428 c3")
    put("bind", bytes(b))

    floats = {EMISSION_RATE: 1.0, LIFE: life, ALPHA: 1.0, COLOR_R: 1.0, COLOR_G: 1.0, COLOR_B: 1.0}
    floats.update({o: scale for o in SCALE})
    floats.update({o: scale for o in PARTICLE_SCALE})
    put("spawn", spawn_stub(at["spawn"], va + spn["ctor"], va + spn["exec"], va + ring, 1, floats, asset=fx,
                            duration=time))
    put("sound", sound_stub(at["sound"], va + snd["ctor"], va + snd["exec"], sound))

    # the dispatcher's first two instructions, then on into it
    put("dtramp", DISPATCH_OLD + b"\xe9" + rel32(at["dtramp"] + len(DISPATCH_OLD) + 5, DISPATCH + len(DISPATCH_OLD)))
    # dispatcher hook (rcx = node ctx, kept): a drone death token here -> the explosion on
    # this node's drone, the node's own state (ctx+18h) kept round it
    d = bytearray(bytes.fromhex("53 56 57 4883ec20 4889cb"))
    d += bytes.fromhex("6548a16000000000000000 4c8b4010 4d8d98") + struct.pack("<I", DEATH_TOKEN_RVA)
    d += bytes.fromhex("f041ff4318 49895b20 488d05")               # +18: nodes run; +20: this ctx
    d += rel32(at["dhook"] + len(d) + 4, at["spawn"]) + bytes.fromhex("49894328 488d05")   # +28: the spawn stub
    d += rel32(at["dhook"] + len(d) + 4, at["sound"]) + bytes.fromhex("49894330")          # +30: the sound stub
    d += bytes.fromhex("49c7c10800fe7f 4d8b09 4d3b4b08 73")       # now >= expiry: no token
    j1 = len(d)
    d += b"\0"
    loop = len(d)
    d += bytes.fromhex("418b03 85c0 7e")                           # count <= 0: none left
    j2 = len(d)
    d += b"\0" + bytes.fromhex("8d48ff f0410fb10b 75")             # take one
    d += bytes([(loop - (len(d) + 1)) & 0xFF])
    d += bytes.fromhex("f041ff4310 488b7b18")                      # shown here; keep the node's state
    d += bytes.fromhex("48c7431800000000 4889d9 e8")
    d += rel32(at["dhook"] + len(d) + 4, at["spawn"])
    d += bytes.fromhex("48897b18")
    done = len(d)
    d[j1] = done - (j1 + 1)
    d[j2] = done - (j2 + 1)
    d += bytes.fromhex("4889d9 4883c420 5f 5e 5b e9")
    d += rel32(at["dhook"] + len(d) + 4, at["dtramp"])
    put("dhook", bytes(d))

    pe.write(va, bytes(blob))
    pe.write(DISPATCH, b"\xe9" + rel32(DISPATCH + 5, at["dhook"]) + b"\x90" * (len(DISPATCH_OLD) - 5))
    pe.write(BIND_CALL, b"\xe8" + rel32(BIND_CALL + 5, at["bind"]))
    return bytes(pe.d)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="dir with 6eace9f64204fd0/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    args = ap.parse_args(argv[1:])
    drone = open(os.path.join(args.src, SCRIPTS, DRONE_SCRIPT), "rb").read()
    det = open(os.path.join(args.src, SCRIPTS, DET_SCRIPT), "rb").read()
    mz, dmz = drone.find(b"MZ"), det.find(b"MZ")
    out = drone[:mz] + patch(drone[mz:], det[dmz:])
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, DRONE_SCRIPT), "wb").write(out)
    print(f"{SCRIPTS}/{DRONE_SCRIPT}: drone death -> effect {DEATH_FX:016x} (x{DEATH_FX_SCALE}, "
          f"life x{DEATH_FX_LIFE}, {DEATH_FX_TIME} s), sound {DEATH_EVENT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
