"""Party guns' shot: party-aware steps in the Pulsar's own weapon script.

Party guns hold the Pulsar (PowerBoost.dll reads them as "assault"), whose weapon script
(`mpl_cbt_wpn_integrated_custom_assault` cff4557b7d2ce426) runs on the 15 pooled gun actors of
each Combat level. Two of its steps ask PowerBoost.dll about the gun (instance +3B0h, the gun
actor):

* the muzzle flash (execute_node_160b3927, `movabs rax, pfx_wpn_cbt_assault_muzzle_flash` at
  MUZZLE_LOAD): rax = PartyEffect(gun, stock flash, instance data) (RULES mailbox +38h): the stock
  flash for everyone else, the team's confetti burst for a party gun's shot, fx_party_empty (no
  particles) on its other trigger frames: this machine's gun runs the node every trigger frame and
  only the let-through shot gets confetti. (Leaving the node by its early exit instead, -1, kept it
  re-running and the gun firing by itself, tested 2026-11-05: every node must finish normally.)
* the flame (pfx_wpn_cbt_assault_breaker, four nodes) -> fx_party_empty, and the muzzle light
  (muzzle_flash_light_0, three nodes) -> a light name no gun has, when PartyGunActor(gun) (mailbox
  +40h) says it is a party gun;
* the shot sound (play_assault_shot, imm32 in its PlaySound node at SHOT_SOUND): an event id with
  no sound, likewise.
No PowerBoost: the Pulsar as it was.

A separate party gun script beside the Pulsar's could not work (tested 2026-11-05): as its own
component it never hears the trigger, which reaches the Pulsar's `ncaScript`; and the Pulsar
handing a party gun's nodes to that script's dispatcher stopped the gun firing, even with an
unchanged copy.

The confetti (tools/rm_preview/party_fx.py): our own piece sheet per team (a BC7 texture) and our
own burst numbers in a billboard effect container, staged as new resources; fx_party_empty is the
same container with no particles.

    python tools/fix_party_fx.py --src <extract root> --out <stage dir> --mailbox <rules mailbox rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "rm_preview"))

from fix_smoke import PE, rel32, SCRIPTS  # noqa: E402
from le_symbol_names import symbol64  # noqa: E402
from veil_fx import add_section  # noqa: E402
import party_fx  # noqa: E402
from fix_rules_netsettings import ARCHIVE, read, read_archive, write, write_archive  # noqa: E402
from fix_party_guns import LEVELS  # noqa: E402
from fix_drone_model import TEXTURE_DESC as TEX_DESC, TEXTURE_GPU as TEX_GPU, DESC_TEMPLATE, build_dds, descriptor  # noqa: E402

PULSAR_SCRIPT = "cff4557b7d2ce426"
EFFECT, COMPANION = "3ae7c41914252baa", "be45c22fa8c2d3f"
MUZZLE = 0xA8CD797F5E8693FE                      # pfx_wpn_cbt_assault_muzzle_flash
MUZZLE_LOAD = 0x32384                            # execute_node_160b3927: movabs rax, MUZZLE (10 bytes)
MUZZLE_BACK = MUZZLE_LOAD + 10
MUZZLE_EXIT = 0x3246B                            # the node's own exit: mov rbx, [rsp+2E0h]; add rsp, 2D0h; pop rbp; ret
#: the shot sound: its PlaySound node's event (the gun actor is at [rbp-29h] there)
SHOT_SOUND = (0x24624, bytes.fromhex("c745ef76299304"))   # mov dword [rbp-11h], play_assault_shot
SILENT_EVENT = 0x00000001                        # no Wwise event has this id
BREAKER = 0x5859D9F1DEBA8F62                     # pfx_wpn_cbt_assault_breaker (the shot's flame)
LIGHT = 0x2AE9184EABCDB17A                       # muzzle_flash_light_0 (the light component's name)
EMPTY = int(symbol64("fx_party_empty"), 16)      # a burst of no particles
NO_LIGHT = int(symbol64("echocombat_party_no_light"), 16)
#: the flame nodes: `mov r9, [rbx]` at +21h, `movabs rax, BREAKER` at +24h (the instance: [r9+68h])
BREAKER_NODES = (0x21AA0, 0x29D00, 0x29E90, 0x30380)
#: the light nodes: `mov rdx, rcx` (the node) at +5Ah, `movabs rax, LIGHT` at +73h
LIGHT_NODES = (0x1C970, 0x24490, 0x2B670)
PARTY_EFFECT_FN = 0x38                           # RULES mailbox +38h: PowerBoost's PartyEffect
PARTY_GUN_FN = 0x40                              # RULES mailbox +40h: PowerBoost's PartyGunActor
EFFECTS = {team: int(symbol64(f"fx_party_confetti_{team}"), 16) for team in party_fx.TEAMS}
SHEETS = {team: int(symbol64(f"fx_party_confetti_pieces_{team}"), 16) for team in party_fx.TEAMS}

PUSH = bytes.fromhex("51 52 4150 4151 4152 4153")    # push rcx rdx r8 r9 r10 r11
POP = bytes.fromhex("415b 415a 4159 4158 5a 59")     # pop r11 r10 r9 r8 rdx rcx


def exe_fn(mailbox: int, slot: int) -> bytes:
    """mov rax, [echovr.exe + mailbox + slot] (the exe base through the PEB)."""
    return (bytes.fromhex("65488b042560000000")           # mov rax, gs:[60h] (PEB)
            + bytes.fromhex("488b4010")                   # mov rax, [rax+10h]: echovr.exe
            + bytes.fromhex("488b80") + struct.pack("<I", mailbox + slot))


def muzzle_cave(mailbox: int, at: int) -> bytes:
    """The muzzle node: rax = PartyEffect(gun actor, stock flash, instance data) (no PowerBoost: the
    stock flash); 0 = spawn nothing, the node returns 0 (a new effect from the node replaces its
    last one, so an empty burst on the frames after a shot killed the confetti at once, tested
    2026-11-05; returning -1, its own early exit, kept it re-running and the gun firing). The gun actor is instance +3B0h (the node copies +3A8h..+3B8h, space id / actor /
    prefab, as the effect's attach actor)."""
    c = bytearray(PUSH)
    c += bytes.fromhex("4883ec20")                       # sub rsp, 20h (the body's rsp is 16-aligned)
    c += exe_fn(mailbox, PARTY_EFFECT_FN)
    c += bytes.fromhex("4885c0")                         # test rax, rax
    j_none = len(c); c += bytes.fromhex("7400")          # jz none
    c += bytes.fromhex("4d8b4168")                       # mov r8, [r9+68h]: the instance data (r9 = [rbx])
    c += bytes.fromhex("498b88b0030000")                 # mov rcx, [r8+3B0h]: the gun actor
    c += bytes.fromhex("48ba") + struct.pack("<Q", MUZZLE)   # mov rdx, MUZZLE
    c += bytes.fromhex("ffd0")                           # call rax
    j_done = len(c); c += bytes.fromhex("eb00")          # jmp done
    c[j_none + 1] = len(c) - (j_none + 2)
    c += bytes.fromhex("48b8") + struct.pack("<Q", MUZZLE)   # none: mov rax, MUZZLE
    c[j_done + 1] = len(c) - (j_done + 2)
    c += bytes.fromhex("4883c420")                       # done: add rsp, 20h
    c += POP
    c += bytes.fromhex("4885c0")                         # test rax, rax
    j_skip = len(c); c += bytes.fromhex("7400")          # jz skip
    c += b"\xe9" + rel32(at + len(c) + 5, MUZZLE_BACK)   # back to the node with the effect in rax
    c[j_skip + 1] = len(c) - (j_skip + 2)
    c += bytes.fromhex("31c0")                           # skip: xor eax, eax (finished, nothing spawned)
    c += b"\xe9" + rel32(at + len(c) + 5, MUZZLE_EXIT)   # ... by the node's own exit
    c += bytes(-len(c) % 8)
    for x in list(EFFECTS.values()) + [EMPTY]:           # the party effects, named in the script
        c += struct.pack("<Q", x)
    return bytes(c)


#: how a swap cave finds the gun actor (into rcx; r8 is free)
GUN_FROM_R9 = bytes.fromhex("4d8b4168 498b88b0030000")            # mov r8, [r9+68h]; mov rcx, [r8+3B0h]
GUN_FROM_RDX = bytes.fromhex("4c8b02 4d8b4068 498b88b0030000")    # mov r8, [rdx]; mov r8, [r8+68h]; mov rcx, [r8+3B0h]


def swap_cave(mailbox: int, at: int, site: int, old: int, new: int, gun: bytes) -> bytes:
    """A `movabs rax, old` at site: rax = PartyGunActor(gun) ? new : old, then on."""
    c = bytearray(PUSH)
    c += bytes.fromhex("4883ec20")                       # sub rsp, 20h (the body's rsp is 16-aligned)
    c += exe_fn(mailbox, PARTY_GUN_FN)
    c += bytes.fromhex("4885c0")                         # test rax, rax
    j_none = len(c); c += bytes.fromhex("7400")          # jz none
    c += gun
    c += bytes.fromhex("ffd0")                           # call rax
    j_done = len(c); c += bytes.fromhex("eb00")          # jmp done
    c[j_none + 1] = len(c) - (j_none + 2)
    c += bytes.fromhex("31c0")                           # none: xor eax, eax
    c[j_done + 1] = len(c) - (j_done + 2)
    c += bytes.fromhex("4883c420")                       # done: add rsp, 20h
    c += POP
    c += bytes.fromhex("85c0")                           # test eax, eax
    c += bytes.fromhex("48b8") + struct.pack("<Q", old)  # mov rax, old (flags kept)
    j_back = len(c); c += bytes.fromhex("7400")          # jz back
    c += bytes.fromhex("48b8") + struct.pack("<Q", new)  # mov rax, new
    c[j_back + 1] = len(c) - (j_back + 2)
    c += b"\xe9" + rel32(at + len(c) + 5, site + 10)    # back after the movabs
    return bytes(c)


def sound_cave(mailbox: int, at: int) -> bytes:
    """The shot sound node: its event, or SILENT_EVENT when PartyGun([rbp-29h], the gun actor)."""
    c = bytearray(PUSH)
    c += bytes.fromhex("4883ec20")                       # sub rsp, 20h (the body's rsp is 16-aligned)
    c += exe_fn(mailbox, PARTY_GUN_FN)
    c += bytes.fromhex("4885c0")                         # test rax, rax
    j_none = len(c); c += bytes.fromhex("7400")          # jz none
    c += bytes.fromhex("488b4dd7")                       # mov rcx, [rbp-29h]: the gun actor
    c += bytes.fromhex("ffd0")                           # call rax
    j_done = len(c); c += bytes.fromhex("eb00")          # jmp done
    c[j_none + 1] = len(c) - (j_none + 2)
    c += bytes.fromhex("31c0")                           # none: xor eax, eax
    c[j_done + 1] = len(c) - (j_done + 2)
    c += bytes.fromhex("4883c420")                       # done: add rsp, 20h
    c += POP
    c += SHOT_SOUND[1]                                   # mov dword [rbp-11h], play_assault_shot
    c += bytes.fromhex("85c0")                           # test eax, eax
    j_back = len(c); c += bytes.fromhex("7400")          # jz back
    c += bytes.fromhex("c745ef") + struct.pack("<I", SILENT_EVENT)   # mov dword [rbp-11h], silent
    c[j_back + 1] = len(c) - (j_back + 2)
    c += b"\xe9" + rel32(at + len(c) + 5, SHOT_SOUND[0] + len(SHOT_SOUND[1]))   # back: the PlaySound call
    return bytes(c)


def pulsar_script(pe_bytes: bytes, mailbox: int) -> bytes:
    pe = PE(pe_bytes)
    if pe.read(MUZZLE_LOAD, 10) != b"\x48\xb8" + struct.pack("<Q", MUZZLE):
        raise ValueError(f"{PULSAR_SCRIPT}: unexpected muzzle node at {MUZZLE_LOAD:#x}: wrong build")
    if pe.read(MUZZLE_EXIT, 8) != bytes.fromhex("488b9c24e0020000"):
        raise ValueError(f"{PULSAR_SCRIPT}: unexpected muzzle node exit at {MUZZLE_EXIT:#x}")
    at, ins = SHOT_SOUND
    if pe.read(at, len(ins)) != ins:
        raise ValueError(f"{PULSAR_SCRIPT}: unexpected shot sound node at {at:#x}")
    swaps = []
    for f in BREAKER_NODES:
        if pe.read(f + 0x21, 3) != bytes.fromhex("4c8b0b") or pe.read(f + 0x24, 10) != b"\x48\xb8" + struct.pack("<Q", BREAKER):
            raise ValueError(f"{PULSAR_SCRIPT}: unexpected flame node at {f:#x}")
        swaps.append((f + 0x24, BREAKER, EMPTY, GUN_FROM_R9))
    for f in LIGHT_NODES:
        if pe.read(f + 0x5A, 3) != bytes.fromhex("488bd1") or pe.read(f + 0x73, 10) != b"\x48\xb8" + struct.pack("<Q", LIGHT):
            raise ValueError(f"{PULSAR_SCRIPT}: unexpected muzzle light node at {f:#x}")
        swaps.append((f + 0x73, LIGHT, NO_LIGHT, GUN_FROM_RDX))
    size = 0x400
    va = add_section(pe, b".party\0\0", size)
    pos = va

    def put(code: bytes, site: int, n: int):
        nonlocal pos
        pe.write(pos, code)
        pe.write(site, b"\xe9" + rel32(site + 5, pos) + b"\x90" * (n - 5))
        pos = (pos + len(code) + 15) // 16 * 16

    put(muzzle_cave(mailbox, pos), MUZZLE_LOAD, 10)
    put(sound_cave(mailbox, pos), at, len(ins))
    for site, old_id, new_id, gun in swaps:
        put(swap_cave(mailbox, pos, site, old_id, new_id, gun), site, 10)
    if pos > va + size:
        raise ValueError("Pulsar script: the caves do not fit their section")
    return bytes(pe.d)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0))
    a = ap.parse_args(argv)
    container = open(os.path.join(a.src, EFFECT, party_fx.CONTAINER), "rb").read()
    companion = open(os.path.join(a.src, COMPANION, party_fx.CONTAINER), "rb").read()
    template = read(a.src, a.out, TEX_DESC, DESC_TEMPLATE)
    for team in party_fx.TEAMS:                          # each team's piece sheet and burst
        dds, w, h, mips = build_dds(party_fx.sheet(team), True)
        write(a.out, TEX_GPU, f"{SHEETS[team]:016x}", dds)
        write(a.out, TEX_DESC, f"{SHEETS[team]:016x}", descriptor(template, dds, w, h, mips, True))
        write(a.out, EFFECT, f"{EFFECTS[team]:016x}", party_fx.party_effect(container, SHEETS[team]))
        write(a.out, COMPANION, f"{EFFECTS[team]:016x}", companion)
        print(f"fx_party_confetti_{team}: {EFFECTS[team]:016x}, pieces {SHEETS[team]:016x} ({w}x{h} BC7)")
    write(a.out, EFFECT, f"{EMPTY:016x}", party_fx.empty_effect(container))   # fx_party_empty
    write(a.out, COMPANION, f"{EMPTY:016x}", companion)

    asset = open(os.path.join(a.src, SCRIPTS, PULSAR_SCRIPT), "rb").read()
    mz = asset.find(b"MZ")
    write(a.out, SCRIPTS, PULSAR_SCRIPT, asset[:mz] + pulsar_script(asset[mz:], a.mailbox))
    print(f"{PULSAR_SCRIPT}: party guns' muzzle flash -> confetti (PartyEffect, mailbox +{PARTY_EFFECT_FN:#x}), "
          f"no flame, light or shot sound (PartyGunActor, +{PARTY_GUN_FN:#x})")

    for level in LEVELS:                                 # the effects, where the loadout terminals are
        pairs, types, tail = read_archive(read(a.src, a.out, ARCHIVE, level))
        want = [(int(EFFECT, 16), e) for e in list(EFFECTS.values()) + [EMPTY]]
        want += [(int(TEX_DESC, 16), t) for t in SHEETS.values()]
        add = [x for x in want if x not in pairs]
        if add:
            order = {t[0]: k for k, t in enumerate(types)}
            pairs = sorted(pairs + add, key=lambda p: order[p[0]])
            write(a.out, ARCHIVE, level, write_archive(pairs, types, tail))
        print(f"{level}: party effects {'+' + str(len(add)) if add else 'listed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
