"""Announcer equip callouts for the gear that has none: TRANSLOCATOR, DOT FIELD, DRONE,
UMBRAL VEIL, OVERCHARGE, POINT and BLAZAR. The game's own lines are left as they are.

How the game plays them: when an item is equipped, script e0fdfda9a944e8ff fires the
event CSymbol64("evt_vo_hra_equip_" + kind + "_" + gear name), e.g.
evt_vo_hra_equip_weapon_assault, for every item. The announcer script
(VO_SCRIPT, 7c10e713aec2f12b) has a listener for 20 of those events: each starts a script
thread at its own node, the thread runs to a node that plays the line's Wwise event from
bank 03f1464db1fe49b5 (PULSAR: listener node 0x72657a17 -> play node 0xcc64c5c4, which
plays vo_hra_gun_equip_pulsar, 0x18A0F124). There is no listener (and no recording) for
loc, dot, drone, smoke, buff or point, and chain's (BLAZAR) has no line.

This adds, in the announcer script:

* in its event handler, before the listener checks: for each of our events, a check
  that starts PULSAR's thread (node 0x72657a17, its busy counter +0Ch, exactly as
  PULSAR's own listener does) with VO_OVERRIDE set to our line's Wwise event, then
  returns (so chain's own listener does not also run);
* at PULSAR's play node: the event played is VO_OVERRIDE when set (and cleared), else
  PULSAR's own.

veil_sound.py adds the lines themselves (assets/vo/<name>.wav, mono 16-bit 48 kHz PCM)
to bank 03f1464db1fe49b5: a sound object per line (a copy of PULSAR's sound, so the same
mix and volume), a Play action and the event, ids from vo_lines().

    python tools/fix_vo.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fix_smoke import PE, rel32, SCRIPTS                      # noqa: E402
from gear_icons import symbol64                               # noqa: E402
from veil_fx import add_section                               # noqa: E402

ROOT = os.path.dirname(_HERE)
VO_DIR = os.path.join(ROOT, "assets", "vo")
VO_SCRIPT = 0x7C10E713AEC2F12B
#: (asset name, the event's kind and gear name as the game builds it)
VO = [
    ("translocator", "grenade", "loc"),
    ("dot_field", "grenade", "dot"),
    ("drone", "grenade", "drone"),
    ("umbral_veil", "ability", "smoke"),
    ("overcharge", "ability", "buff"),
    ("point", "ability", "point"),
    ("blazar", "weapon", "chain"),
]
#: Wwise names of the game's own callout events: gun / grenade / ability
WWISE_KIND = {"weapon": "gun", "grenade": "grenade", "ability": "ability"}

# the announcer script (RVAs)
HANDLER_HOOK = 0x4B8B            # movabs rax, evt_vo_hra_equip_ability_sensor (2nd check: rbx, rdi set)
HANDLER_END = 0x51C7             # the handler's epilogue
START_THREAD = 0x5BC0            # (rcx = script, edx = node) -> thread
PULSAR_NODE = 0x72657A17         # PULSAR's listener node; its busy counter is [[rdi+68h]+0Ch]
PULSAR_COUNTER = 0x0C
PLAY_AT = 0x3B2B                 # mov dword [rbp-11h], 0x18A0F124 (PULSAR's play node)
PULSAR_EVENT = 0x18A0F124
#: the script tells the engine which events it listens for: the query function at
#: EVENTS_QUERY answers (for its events key) with the name table at .data 0xA000 and
#: EVENTS_COUNT; the engine routes only those events to the handler, so ours are added
EVENTS_LEA = 0x323F              # lea rax, [rip -> 0xA000]; mov [rdx], rax; mov dword [r8], 20; ...
EVENTS_TABLE, EVENTS_COUNT = 0xA000, 20
SECTION = b".vo\0\0\0\0\0"
SECTION_SIZE = 0x800
NAMES_TABLE, NAMES_STRINGS, NAMES_STUB = 0x400, 0x500, 0x700


def fnv1(name: str) -> int:
    """Wwise's id of a name: 32-bit FNV-1 of the lower-case name."""
    h = 2166136261
    for c in name.lower().encode():
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= c
    return h


def vo_lines() -> list:
    """[{name, game_event (CSymbol64), event, action, sound, media (Wwise ids), wav}]"""
    out = []
    for name, kind, gear in VO:
        out.append(dict(name=name, game_event=symbol64(f"evt_vo_hra_equip_{kind}_{gear}"),
                        event=fnv1(f"vo_hra_{WWISE_KIND[kind]}_equip_{name}"),
                        action=fnv1(f"echocombat_vo_{name}_action"), sound=fnv1(f"echocombat_vo_{name}_sound"),
                        media=fnv1(f"echocombat_vo_{name}_media"), wav=os.path.join(VO_DIR, f"{name}.wav")))
    return out


def jmp(at: int, to: int) -> bytes:
    return b"\xe9" + rel32(at + 5, to)


#: --trace: every event the announcer's handler sees goes into a ring at TRACE_RING (32
#: u64 CSymbol64s) of our section, the next slot's index at TRACE_INDEX; read it from the
#: running game (tools/vo_trace.py) to see which events an equip fires
TRACE_INDEX, TRACE_RING, TRACE_SLOTS = 0x8, 0x300, 32


def patch(pe_bytes: bytes, trace: bool = False) -> bytes:
    pe = PE(pe_bytes)
    hook_old = pe.read(HANDLER_HOOK, 10)
    if hook_old[:2] != b"\x48\xb8" or struct.unpack_from("<Q", hook_old, 2)[0] != symbol64("evt_vo_hra_equip_ability_sensor"):
        raise ValueError("announcer script: unexpected event handler (wrong script build)")
    if pe.read(PLAY_AT, 7) != b"\xc7\x45\xef" + struct.pack("<I", PULSAR_EVENT):
        raise ValueError("announcer script: unexpected PULSAR play node")
    events_old = pe.read(EVENTS_LEA, 7 + 3 + 6)
    if events_old[:3] != b"\x48\x8d\x05" or EVENTS_LEA + 7 + struct.unpack_from("<i", events_old, 3)[0] != EVENTS_TABLE \
            or events_old[7:10] != b"\x48\x89\x02" or events_old[10:16] != b"\x41\xc7\x00" + bytes([EVENTS_COUNT, 0, 0]):
        raise ValueError("announcer script: unexpected event list query")
    va = add_section(pe, SECTION, SECTION_SIZE)
    blob = bytearray(SECTION_SIZE)
    override = va                                          # u32: the Wwise event to play instead
    lines = vo_lines()

    # the event list: the game's 20 names, then ours (those without a listener of their own).
    # The table is filled at the first query: the game's entries are pointers the loader
    # relocates, ours lea'd from this section.
    names =[f"evt_vo_hra_equip_{k}_{g}" for _, k, g in VO if (k, g) != ("weapon", "chain")]
    strings, offs = bytearray(), []
    for n in names:
        offs.append(NAMES_STRINGS + len(strings))
        strings += n.encode() + b"\0"
        strings += bytes(-len(strings) % 8)
    assert NAMES_STRINGS + len(strings) <= NAMES_STUB
    blob[NAMES_STRINGS:NAMES_STRINGS + len(strings)] = strings
    at = va + NAMES_STUB
    total = EVENTS_COUNT + len(names)
    b = bytearray(b"\x48\x8d\x05" + rel32(at + 7, va + NAMES_TABLE))             # lea rax, table
    b += b"\x48\x83\x38\x00" + b"\x75"; j_filled = len(b); b += b"\0"            # filled already?
    b += b"\x4c\x8d\x15" + rel32(at + len(b) + 7, EVENTS_TABLE)                  # lea r10, the game's table
    b += b"\x45\x31\xc9"                                                        # xor r9d, r9d
    loop = len(b)
    b += b"\x4f\x8b\x1c\xca" + b"\x4e\x89\x1c\xc8"                              # r11 = [r10+r9*8]; [rax+r9*8] = r11
    b += b"\x41\xff\xc1" + b"\x41\x83\xf9" + bytes([EVENTS_COUNT])              # r9d++; cmp r9d, 20
    b += b"\x72" + bytes([(loop - (len(b) + 2)) & 0xFF])                        # jb loop
    for k, off in enumerate(offs):
        b += b"\x4c\x8d\x1d" + rel32(at + len(b) + 7, va + off)                 # lea r11, our name
        b += b"\x4c\x89\x98" + struct.pack("<I", 8 * (EVENTS_COUNT + k))        # [rax+8*(20+k)] = r11
    b[j_filled] = len(b) - (j_filled + 1)
    b += b"\x48\x89\x02" + b"\x41\xc7\x00" + struct.pack("<I", total)           # [rdx] = table; [r8] = count
    b += b"\xb8\x01\x00\x00\x00\xc3"                                            # return 1
    assert NAMES_STUB + len(b) <= SECTION_SIZE and 8 * total <= NAMES_STRINGS - NAMES_TABLE
    blob[NAMES_STUB:NAMES_STUB + len(b)] = b
    pe.write(EVENTS_LEA, jmp(EVENTS_LEA, at) + b"\x90" * 2)

    # PULSAR's play node: eax = override (cleared) or PULSAR's event
    at = va + 0x10
    b = bytearray(b"\x8b\x05" + rel32(at + 6, override))                # mov eax, [override]
    b += b"\x85\xc0\x75\x05" + b"\xb8" + struct.pack("<I", PULSAR_EVENT)  # test; jnz +5; mov eax, pulsar
    b += b"\xc7\x05" + rel32(at + len(b) + 10, override) + bytes(4)     # mov dword [override], 0
    b += b"\x89\x45\xef"                                                # mov [rbp-11h], eax
    b += jmp(at + len(b), PLAY_AT + 7)
    blob[0x10:0x10 + len(b)] = b
    pe.write(PLAY_AT, jmp(PLAY_AT, at) + b"\x90\x90")

    # the event handler (rbx = the event, rdi = the script)
    at = va + 0x60
    b = bytearray()
    if trace:                                   # rcx / rdx are free here: the checks set them
        b += b"\x48\x8b\x03"                                             # mov rax, [rbx]
        b += b"\x8b\x0d" + rel32(at + len(b) + 6, va + TRACE_INDEX)       # mov ecx, [index]
        b += b"\x83\xe1" + bytes([TRACE_SLOTS - 1])                       # and ecx, 31
        b += b"\x48\x8d\x15" + rel32(at + len(b) + 7, va + TRACE_RING)    # lea rdx, ring
        b += b"\x48\x89\x04\xca"                                         # mov [rdx+rcx*8], rax
        b += b"\xff\x05" + rel32(at + len(b) + 6, va + TRACE_INDEX)       # inc dword [index]
    matches = []
    for line in lines:
        b += b"\x48\xb8" + struct.pack("<Q", line["game_event"])          # mov rax, our event
        b += b"\x48\x39\x03" + b"\x0f\x84"                                  # cmp [rbx], rax; je match
        matches.append(len(b)); b += bytes(4)
    b += hook_old + jmp(at + len(b) + 10, HANDLER_HOOK + 10)            # none: the game's checks
    starts = []
    for k, line in enumerate(lines):
        b[matches[k]:matches[k] + 4] = struct.pack("<i", len(b) - (matches[k] + 4))
        b += b"\xb8" + struct.pack("<I", line["event"]) + b"\xe9"           # mov eax, our line; jmp start
        starts.append(len(b)); b += bytes(4)
    start = len(b)
    for j in starts:
        b[j:j + 4] = struct.pack("<i", start - (j + 4))
    b += b"\x48\x8b\x4f\x68" + b"\x83\x79" + bytes([PULSAR_COUNTER]) + b"\x01"   # rcx = counters; busy?
    b += b"\x0f\x8d" + rel32(at + len(b) + 6, HANDLER_END)              # jge: return
    b += b"\x89\x05" + rel32(at + len(b) + 6, override)                 # mov [override], eax
    b += b"\xba" + struct.pack("<I", PULSAR_NODE) + b"\x48\x89\xf9"      # mov edx, node; mov rcx, rdi
    b += b"\xe8" + rel32(at + len(b) + 5, START_THREAD)                 # call start thread (rax = it)
    b += bytes.fromhex("488b4b30 488b5008 48890a")                      # its data, as the listeners do
    b += bytes.fromhex("488b4b18 48894850 488b4b28 48894858")
    b += bytes.fromhex("488b4f68 ff41") + bytes([PULSAR_COUNTER])        # counter++
    b += bytes.fromhex("488b4f68 4883c1") + bytes([PULSAR_COUNTER]) + bytes.fromhex("48894870")
    b += jmp(at + len(b), HANDLER_END)
    assert 0x60 + len(b) <= TRACE_RING
    blob[0x60:0x60 + len(b)] = b
    pe.write(HANDLER_HOOK, jmp(HANDLER_HOOK, at) + b"\x90" * 5)
    pe.write(va, bytes(blob))
    return bytes(pe.d)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--trace", action="store_true", help="record every event the handler sees (tools/vo_trace.py)")
    args = ap.parse_args(argv[1:])
    missing = [l["wav"] for l in vo_lines() if not os.path.exists(l["wav"])]
    if missing:
        sys.exit(f"missing callout audio: {missing}")
    path = os.path.join(args.src, SCRIPTS, f"{VO_SCRIPT:x}")
    asset = open(path, "rb").read()
    mz = asset.find(b"MZ")
    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    open(os.path.join(args.out, SCRIPTS, f"{VO_SCRIPT:x}"), "wb").write(asset[:mz] + patch(asset[mz:], args.trace))
    print(f"{SCRIPTS}/{VO_SCRIPT:x}: announcer callouts for " + ", ".join(f"{k}_{g}" for _, k, g in VO))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
