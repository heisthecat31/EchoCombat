"""UMBRAL VEIL's sound: put assets/umbral_veil.wav into the game's unused 14 s sound slot.

Bank 03f1464db1fe49b5 (`CWWiseSoundBankResourceWin10`, type folder
6d358eef7bb85a98) holds an unused sound:

    event 2092801294 -> action 752655010 -> sound 1028260926 -> media 19531070
    (embedded in the bank: 48 kHz mono Wwise Vorbis, 14.15 s)

The smoke script plays event 2092801294 when the veil is used (veil_fx.py).
This replaces media 19531070 with the baked smoke sound as 16-bit PCM, the
format of the game's 74 PCM sounds (0xFFFE wem, plugin 0x00010001), so no
Vorbis encoder is needed:

* the wem gets the exact header the game's own mono 48 kHz PCM wems carry
* DATA is rebuilt (every media 16-byte aligned, as Wwise lays it out) and
  DIDX re-pointed; sound 1028260926's codec becomes PCM and its in-memory
  size the new one
* the 16-byte resource header (u64 bank size) and 8-byte trailer are kept

It also adds TRANSLOCATOR's teleport sound (fix_loc_fx.py), event LOC_EVENT -> a Play
action on sound LOC_SOUND, media 279761503 alone (in bank b2afe679127b4904, loaded in
matches). The game's own event for that media, 3590143152, goes through a switch
whose default branch is the stun-bouncing-off-a-barrier sound.

    python tools/veil_sound.py --src <extract root> --out <dir> [--wav assets/umbral_veil.wav]
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK_TYPE = "6d358eef7bb85a98"         # CWWiseSoundBankResourceWin10
BANK = "3f1464db1fe49b5"               # 03f1464db1fe49b5 (the extract drops the leading 0)
BANK_ID = 3271234526
MEDIA = 19531070
SOUND = 1028260926
PLUGIN_VORBIS, PLUGIN_PCM = 0x00040001, 0x00010001
RATE = 48000
#: TRANSLOCATOR's teleport sound: a new event and Play action (Wwise FNV-1 ids of
#: "play_echocombat_translocate" / "echocombat_translocate_play_action") on sound
#: LOC_SOUND (media 279761503) in bank LOC_SOUND_BANK.
LOC_EVENT, LOC_ACTION = 2819690668, 1031878165
LOC_SOUND, LOC_SOUND_BANK = 159312186, 3901061564
#: RIFF header of the game's mono 48 kHz PCM wems, up to the data chunk's size.
FMT = bytes.fromhex("666d742018000000feff010080bb0000007701000200100006000000014100004a554e4b0400000000000000")


def chunks(bank: bytes) -> list:
    """[(tag, payload)] of a Wwise bank (starting at BKHD)."""
    out, o = [], 0
    while o + 8 <= len(bank):
        tag, size = bank[o:o + 4], struct.unpack_from("<I", bank, o + 4)[0]
        out.append((tag, bytearray(bank[o + 8:o + 8 + size])))
        o += 8 + size
    if o != len(bank):
        raise ValueError("bank does not parse into chunks")
    return out


def hirc_object(kind: int, oid: int, body: bytes) -> bytes:
    return struct.pack("<BII", kind, 4 + len(body), oid) + body


def pcm_wem(pcm: bytes) -> bytes:
    body = b"WAVE" + FMT + b"data" + struct.pack("<I", len(pcm)) + pcm
    return b"RIFF" + struct.pack("<I", len(body)) + body


def read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
            raise ValueError(f"{path} must be mono 16-bit {RATE} Hz (make_veil_sound.py makes it)")
        return w.readframes(w.getnframes())


def replace_sound(asset: bytes, pcm: bytes) -> bytes:
    start = asset.find(b"BKHD")
    if start != 16 or struct.unpack_from("<Q", asset, 0)[0] != len(asset) - 24:
        raise ValueError("unexpected bank resource wrapper")
    parts = chunks(asset[16:-8])
    tags = [t for t, _ in parts]
    bkhd, didx, data, hirc = (parts[tags.index(t)][1] for t in (b"BKHD", b"DIDX", b"DATA", b"HIRC"))
    if struct.unpack_from("<I", bkhd, 4)[0] != BANK_ID:
        raise ValueError("wrong bank")

    # DATA / DIDX
    entries = [list(struct.unpack_from("<3I", didx, i)) for i in range(0, len(didx), 12)]
    if MEDIA not in [e[0] for e in entries]:
        raise ValueError(f"media {MEDIA} not in the bank")
    new = pcm_wem(pcm)
    out = bytearray()
    for e in entries:
        blob = new if e[0] == MEDIA else bytes(data[e[1]:e[1] + e[2]])
        out += bytes(-len(out) % 16)
        e[1], e[2] = len(out), len(blob)
        out += blob
    didx[:] = b"".join(struct.pack("<3I", *e) for e in entries)
    data[:] = out

    # HIRC: the sound's source becomes PCM of the new size
    n, p, done = struct.unpack_from("<I", hirc, 0)[0], 4, False
    for _ in range(n):
        kind, size, oid = struct.unpack_from("<BII", hirc, p)
        if kind == 2 and oid == SOUND:
            plugin, stream, source = struct.unpack_from("<IBI", hirc, p + 9)
            if source != MEDIA or stream != 0 or plugin not in (PLUGIN_VORBIS, PLUGIN_PCM):
                raise ValueError("sound object is not the embedded media we expect")
            struct.pack_into("<I", hirc, p + 9, PLUGIN_PCM)
            struct.pack_into("<I", hirc, p + 18, len(new))
            done = True
        p += 5 + size
    if not done:
        raise ValueError(f"sound object {SOUND} not found")
    hirc += hirc_object(3, LOC_ACTION, struct.pack("<HIB", 0x0403, LOC_SOUND, 0) + bytes([0, 0, 4])
                        + struct.pack("<I", LOC_SOUND_BANK))   # Play; no props; fade curve 4; its bank
    hirc += hirc_object(4, LOC_EVENT, bytes([1]) + struct.pack("<I", LOC_ACTION))
    struct.pack_into("<I", hirc, 0, n + 2)

    bank = b"".join(t + struct.pack("<I", len(c)) + bytes(c) for t, c in parts)
    return struct.pack("<QQ", len(bank), 0) + bank + asset[-8:]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--wav", default=os.path.join(ROOT, "assets", "umbral_veil.wav"))
    args = ap.parse_args(argv[1:])
    asset = open(os.path.join(args.src, BANK_TYPE, BANK), "rb").read()
    pcm = read_wav(args.wav)
    fixed = replace_sound(asset, pcm)
    os.makedirs(os.path.join(args.out, BANK_TYPE), exist_ok=True)
    open(os.path.join(args.out, BANK_TYPE, BANK), "wb").write(fixed)
    print(f"{BANK_TYPE}/{BANK}: sound {MEDIA} -> {os.path.basename(args.wav)} "
          f"({len(pcm) / 2 / RATE:.2f} s PCM), event {LOC_EVENT} -> sound {LOC_SOUND}, bank {len(asset)} -> {len(fixed)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
