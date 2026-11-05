"""Combat private matches: make the podium terminal's RULES button pressable.

`d4653fc2065e8184` is the private-match podium terminal script (READY / RESTART /
CHANGE TEAM / SPECTATE / RULES). Its RULES page is Arena's: four -/+ rows (blue and
orange starting score, round minutes, round seconds). In a Combat match the button
stays grey: the script copies the game's `matchisarena` and `matchiscombat` flags into
its own state (bytes +169h / +16Ah of the graph's data) and its button logic follows
them.

Each copy is the same three steps:

    mov  edx, [field id of matchisarena / matchiscombat]   ; 8B 15 rel32
    ...  (lea rcx, the game expression; r8 = where to write)
    call [the expression's flag accessor]                  ; FF 15 rel32

and the accessor writes the flag through r8. This replaces each such call with

    mov  byte ptr [r8], 1 / 0 ; xchg ax, ax                ; 41 C6 00 imm 66 90

so the terminal always reads "Arena, not Combat" and behaves as it does in Arena.
Nothing else in the game reads these copies; the match itself stays Combat. Two of the
reads feed the SPECTATE button's unlock check, which therefore follows
arena_spectate_unlocked instead of combat_spectate_unlocked. The Arena
rows it then shows are layer 1 only: later layers turn them into Combat rules.

    python tools/fix_rules_terminal.py --src <extract root> --out <stage dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

SCRIPTS = "6eace9f64204fd0"
TERMINAL_SCRIPT = "d4653fc2065e8184"
#: RVAs of the globals that hold the two flags' field ids (filled when the script
#: registers its R15NetGameExpression fields)
FIELD_IDS = {0x3E250: ("matchisarena", 1), 0x3E7EC: ("matchiscombat", 0)}
#: how many reads of each the stock script has (checked, so another build is not patched)
EXPECTED = {"matchisarena": 4, "matchiscombat": 10}
CALL_WINDOW = 24            # the accessor call follows the mov edx within this many bytes

#: The rules page canvas (ui_display_mpl_mm_custom_rules1): rows MINUTES, SECONDS,
#: BLUE SCORE, ORANGE SCORE. Its texts are fixed 33-byte slots after an offset table
#: (slot k at TEXTS + 21h*k): 0 MATCH RULES, 1 MINUTES, 2 its value, 3 SECONDS, ...
#: In Combat the two time rows are the capture point's unlock time and its time to
#: capture (fix_capture_points.py keeps them as one MM:SS value).
CANVAS_TYPE = "59a9bd6e4525ecc4"
RULES_CANVAS = "b655c5c7eaa080d7"
TEXT_SLOT = 0x21
TEXT_EDITS = {1: (b"MINUTES", b"POINT UNLOCK"), 3: (b"SECONDS", b"CAPTURE TIME")}
HIDDEN_ELEMENTS = ()
ELEMENTS, ELEMENT_SIZE, E_ALPHA = 0x1B0, 0xE0, 0xBC
#: The script writes the rows as "MM" + ":00" and "00:" + "SS": both pieces (two copies
#: each, in its .rdata) become empty, so the rows read as plain seconds: 45, 04.
TIME_PIECES = (b"\x00:00\x00", b"\x0000:\x00")


def sections(pe: bytes):
    at = struct.unpack_from("<I", pe, 0x3C)[0]
    count = struct.unpack_from("<H", pe, at + 6)[0]
    opt = struct.unpack_from("<H", pe, at + 20)[0]
    out = []
    for i in range(count):
        s = at + 24 + opt + i * 40
        vsize, rva, rsize, raw = struct.unpack_from("<IIII", pe, s + 8)
        out.append((pe[s:s + 8].rstrip(b"\x00"), rva, vsize, raw, rsize))
    return out


def patch(pe: bytearray) -> dict:
    text = [s for s in sections(pe) if s[0] == b".text"][0]
    _, rva, _, raw, rsize = text
    counts = {name: 0 for name, _ in FIELD_IDS.values()}
    done = {name: 0 for name, _ in FIELD_IDS.values()}
    i = raw
    while i < raw + rsize - 6:
        if pe[i] == 0x8B and pe[i + 1] == 0x15:                     # mov edx, [rip + rel32]
            target = rva + (i - raw) + 6 + struct.unpack_from("<i", pe, i + 2)[0]
            if target in FIELD_IDS:
                name, value = FIELD_IDS[target]
                new = bytes([0x41, 0xC6, 0x00, value, 0x66, 0x90])
                j = next((k for k in range(i + 6, i + 6 + CALL_WINDOW)
                          if pe[k:k + 2] == b"\xFF\x15" or pe[k:k + 6] == new), None)
                if j is None:
                    sys.exit(f"{TERMINAL_SCRIPT}: no accessor call after the {name} read at +{i:#x}")
                if pe[j:j + 6] == new:
                    done[name] += 1
                else:
                    pe[j:j + 6] = new
                counts[name] += 1
                i = j + 6
                continue
        i += 1
    if counts != EXPECTED:
        sys.exit(f"{TERMINAL_SCRIPT}: found {counts} game-type reads, expected {EXPECTED}; not patching")
    return {k: (counts[k], done[k]) for k in counts}


def patch_canvas(d: bytes) -> tuple:
    d = bytearray(d)
    base = d.find(b"MATCH RULES\x00")
    if base < 0:
        raise ValueError(f"{RULES_CANVAS}: no MATCH RULES text")
    for k, (old, new) in TEXT_EDITS.items():
        at = base + k * TEXT_SLOT
        slot = bytes(d[at:at + TEXT_SLOT])
        if slot.rstrip(b"\x00") not in (old, new):
            raise ValueError(f"{RULES_CANVAS}: text slot {k} is {slot.rstrip(bytes(1))!r}, not {old!r}")
        d[at:at + TEXT_SLOT] = new + bytes(TEXT_SLOT - len(new))
    for j in HIDDEN_ELEMENTS:
        struct.pack_into("<f", d, ELEMENTS + j * ELEMENT_SIZE + E_ALPHA, 0.0)
    return bytes(d), "MINUTES -> POINT UNLOCK, SECONDS -> CAPTURE TIME"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help=f"dir with {SCRIPTS}/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    args = ap.parse_args(argv)

    staged = os.path.join(args.out, SCRIPTS, TERMINAL_SCRIPT)
    path = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPTS, TERMINAL_SCRIPT)
    asset = bytearray(open(path, "rb").read())
    mz = asset.find(b"MZ")
    pe = asset[mz:]
    result = patch(pe)
    blanked = 0
    for piece in TIME_PIECES:
        hits = pe.count(piece)
        if hits not in (0, 2):
            sys.exit(f"{TERMINAL_SCRIPT}: {piece!r} found {hits} times, expected 2; not patching")
        blanked += hits
        pe[:] = pe.replace(piece, bytes(len(piece)))
    print(f"{TERMINAL_SCRIPT}: time rows show plain seconds ({blanked} text pieces blanked now)")
    asset[mz:] = pe
    print(f"{TERMINAL_SCRIPT}: RULES terminal reads Arena in Combat: " +
          ", ".join(f"{k} {n} read(s) ({d} already)" for k, (n, d) in result.items()))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset)

    staged = os.path.join(args.out, CANVAS_TYPE, RULES_CANVAS)
    path = staged if os.path.exists(staged) else os.path.join(args.src, CANVAS_TYPE, RULES_CANVAS)
    try:
        canvas, what = patch_canvas(open(path, "rb").read())
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(canvas)
    print(f"{RULES_CANVAS}: rules page: {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
