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
#: how many copies of the sound the event starts at once: each one starts on the same
#: sample, so they add up (2 = +6 dB, 3 = +9.5 dB, 4 = +12 dB). The sound object itself
#: is left alone: the stun-bouncing-off-a-barrier sound plays it too. 16 = +24 dB over
#: one copy (+8.5 dB over the earlier 6).
LOC_COPIES = 16
LOC_SOUND, LOC_SOUND_BANK = 159312186, 3901061564
#: POINT's sound (the arc mine sound picked from sound_candidates/) is held in the
#: grenade bank c823e2c9bc0168ad, which is not loaded in every match, so POINT went
#: silent. Its media is copied into this bank, which always is loaded (the
#: veil's sound plays from it), each as a new sound object (a copy of SOUND with the media
#: swapped), played together by event POINT_SND_EVENT (FNV-1 of
#: "play_echocombat_point"), POINT_COPIES of each.
POINT_SND_EVENT, POINT_SND_ACTION, POINT_SND_SOUND = 3404182162, 771004983, 583511709
POINT_SRC_BANK = "c823e2c9bc0168ad"
#: POINT's sound: the arc mine's media (sound_candidates/arc6_818626942.wav), copied as is
POINT_MEDIA = [818626942]
#: the largest bank the game loaded: 3,012,457 bytes played, 3,172,061 did not (3 MiB lies
#: between)
BANK_LIMIT = 3 * 1024 * 1024
POINT_COPIES = 2
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


def bank_media(asset: bytes) -> dict:
    """media id -> wem bytes, for every media embedded in a bank resource."""
    parts = dict(chunks(asset[16:-8]))
    didx, data = parts[b"DIDX"], parts[b"DATA"]
    return {m: bytes(data[o:o + n]) for m, o, n in (struct.unpack_from("<3I", didx, i)
                                                    for i in range(0, len(didx), 12))}


#: offset of DirectParentID in SOUND's body (an actor-mixer, 1014447365)
SOUND_PARENT = 21


def add_children(hirc: bytes, parent: int, ids: list, objects: bytes = b"") -> bytes:
    """HIRC with `ids` added to `parent`'s children: the list at the end of its body,
    u32 count then the ids, ascending. `objects` (those children) go in just before
    the parent: a bank lists every object before its parent, and a parent only takes
    in children already loaded (POINT's sound, after its parent, never played)."""
    out = bytearray(hirc[:4])
    n, p, found = struct.unpack_from("<I", hirc, 0)[0], 4, False
    for _ in range(n):
        kind, size, oid = struct.unpack_from("<BII", hirc, p)
        body = bytearray(hirc[p + 9:p + 5 + size])
        if oid == parent:
            for at in range(len(body) - 4, -1, -4):              # the count, from the end
                cnt = struct.unpack_from("<I", body, at)[0]
                if cnt and at + 4 + 4 * cnt == len(body):
                    break
            else:
                raise ValueError(f"no children list in object {parent}")
            kids = sorted(set(struct.unpack_from(f"<{cnt}I", body, at + 4)) | set(ids))
            body[at:] = struct.pack(f"<I{len(kids)}I", len(kids), *kids)
            found = True
            out += objects
        out += hirc_object(kind, oid, bytes(body))
        p += 5 + size
    if not found:
        raise ValueError(f"parent object {parent} not in the bank")
    return bytes(out + hirc[p:])


def replace_sound(asset: bytes, pcm: bytes, copies: int = LOC_COPIES, point_media: dict = None) -> bytes:
    start = asset.find(b"BKHD")
    if start != 16 or struct.unpack_from("<Q", asset, 0)[0] != len(asset) - 24:
        raise ValueError("unexpected bank resource wrapper")
    parts = chunks(asset[16:-8])
    tags = [t for t, _ in parts]
    bkhd, didx, data, hirc = (parts[tags.index(t)][1] for t in (b"BKHD", b"DIDX", b"DATA", b"HIRC"))
    if struct.unpack_from("<I", bkhd, 4)[0] != BANK_ID:
        raise ValueError("wrong bank")

    # DATA / DIDX (POINT's media appended)
    entries = [list(struct.unpack_from("<3I", didx, i)) for i in range(0, len(didx), 12)]
    if MEDIA not in [e[0] for e in entries]:
        raise ValueError(f"media {MEDIA} not in the bank")
    point_media = point_media or {}
    if any(m in [e[0] for e in entries] for m in point_media):
        raise ValueError("POINT's media already in the bank")
    # DIDX is kept sorted by media id (Wwise looks media up by a binary search): appended
    # out of order, POINT's media was never found and its sound played nothing
    entries = sorted(entries + [[m, 0, 0] for m in point_media])
    new = pcm_wem(pcm)
    out = bytearray()
    for e in entries:
        blob = new if e[0] == MEDIA else point_media[e[0]] if e[0] in point_media \
            else bytes(data[e[1]:e[1] + e[2]])
        out += bytes(-len(out) % 16)
        e[1], e[2] = len(out), len(blob)
        out += blob
    didx[:] = b"".join(struct.pack("<3I", *e) for e in entries)
    data[:] = out

    # HIRC: the sound's source becomes PCM of the new size
    n, p, done = struct.unpack_from("<I", hirc, 0)[0], 4, None
    for _ in range(n):
        kind, size, oid = struct.unpack_from("<BII", hirc, p)
        if kind == 2 and oid == SOUND:
            plugin, stream, source = struct.unpack_from("<IBI", hirc, p + 9)
            if source != MEDIA or stream != 0 or plugin not in (PLUGIN_VORBIS, PLUGIN_PCM):
                raise ValueError("sound object is not the embedded media we expect")
            done = bytearray(hirc[p + 9:p + 5 + size])               # the stock body, for POINT's copies
            struct.pack_into("<I", hirc, p + 9, PLUGIN_PCM)
            struct.pack_into("<I", hirc, p + 18, len(new))
        p += 5 + size
    if done is None:
        raise ValueError(f"sound object {SOUND} not found")

    def play(action: int, target: int, bank: int) -> bytes:   # Play; no props; fade curve 4; the target's bank
        return hirc_object(3, action, struct.pack("<HIB", 0x0403, target, 0) + bytes([0, 0, 4])
                           + struct.pack("<I", bank))

    added = 0
    actions = [LOC_ACTION + k for k in range(copies)]
    for a in actions:
        hirc += play(a, LOC_SOUND, LOC_SOUND_BANK)
    hirc += hirc_object(4, LOC_EVENT, bytes([len(actions)]) + b"".join(struct.pack("<I", a) for a in actions))
    added += len(actions) + 1
    if point_media:
        actions, sounds = [], bytearray()
        for k, m in enumerate(point_media):                      # a sound object per media
            body = bytearray(done)
            struct.pack_into("<IBII", body, 0, PLUGIN_PCM, 0, m, len(point_media[m]))
            sounds += hirc_object(2, POINT_SND_SOUND + k, bytes(body))
            for c in range(POINT_COPIES):
                actions.append(POINT_SND_ACTION + k * POINT_COPIES + c)
                hirc += play(actions[-1], POINT_SND_SOUND + k, BANK_ID)
        hirc += hirc_object(4, POINT_SND_EVENT, bytes([len(actions)])
                            + b"".join(struct.pack("<I", a) for a in actions))
        added += len(point_media) + len(actions) + 1
        # The copies' parent (SOUND's actor-mixer) must list them among its children, as it
        # lists SOUND, or they are never attached to the mix and play nothing.
        new_ids = [POINT_SND_SOUND + k for k in range(len(point_media))]
        hirc[:] = add_children(bytes(hirc), struct.unpack_from("<I", done, SOUND_PARENT)[0], new_ids, bytes(sounds))
    struct.pack_into("<I", hirc, 0, n + added)

    bank = b"".join(t + struct.pack("<I", len(c)) + bytes(c) for t, c in parts)
    return struct.pack("<QQ", len(bank), 0) + bank + asset[-8:]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--wav", default=os.path.join(ROOT, "assets", "umbral_veil.wav"))
    ap.add_argument("--point-wav", default=os.path.join(ROOT, "assets", "point.wav"),
                    help="POINT's sound, mono 16-bit 48 kHz, short enough to keep the bank under 3 MiB")
    args = ap.parse_args(argv[1:])
    asset = open(os.path.join(args.src, BANK_TYPE, BANK), "rb").read()
    pcm = read_wav(args.wav)
    # POINT's sound as 16-bit PCM, like the veil's. Copied as is, the arc mine's Vorbis
    # media decoded to a fizz in this bank. The whole 1.96 s as PCM put the bank past 3 MiB
    # (the game then loaded none of it), so assets/point.wav is the arc6 sound cut to
    # 1.55 s (all but its last -26 dB), with a 0.15 s fade.
    point_media = {POINT_MEDIA[0]: pcm_wem(read_wav(args.point_wav))}
    fixed = replace_sound(asset, pcm, point_media=point_media)
    if len(fixed) > BANK_LIMIT:
        sys.exit(f"{BANK}: the bank would be {len(fixed)} bytes, over the {BANK_LIMIT} the game loads")
    os.makedirs(os.path.join(args.out, BANK_TYPE), exist_ok=True)
    open(os.path.join(args.out, BANK_TYPE, BANK), "wb").write(fixed)
    print(f"{BANK_TYPE}/{BANK}: sound {MEDIA} -> {os.path.basename(args.wav)} "
          f"({len(pcm) / 2 / RATE:.2f} s PCM), event {LOC_EVENT} -> sound {LOC_SOUND} x{LOC_COPIES}, "
          f"event {POINT_SND_EVENT} -> POINT's sound(s) {list(point_media)} x{POINT_COPIES}, "
          f"bank {len(asset)} -> {len(fixed)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
