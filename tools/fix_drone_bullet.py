"""Give the DRONE's bullets visible effects.

The drone fires through `CR15NetAutoTargetCS`, which spawns its own pooled
bullet actor `a8f84e7dd40b806e` with NO gun. Most bullets draw their tracer
from the gun that fired them (it lives in `CR15NetGunCR`), so the drone's
shots are invisible -- the client also logs "Bullet Damage has invalid gun"
for every hit, which only means no damage falloff.

Some bullets carry their effects themselves instead: their `CR15NetBulletCR`
record names two particle COMPONENTS (+0x58, +0x60), and those components are
`CParticleEffectCR` records on the bullet actor. Bullet `12001003b8e9a2a6`
does exactly that. The fix copies its two particle records onto the drone's
bullet actor and points the drone bullet record's +0x58/+0x60 at them:

* `CParticleEffectCRWin10` (stride 152): two records appended, actor swapped.
* `CR15NetBulletCRWin10` (stride 136): +0x58/+0x60 copied from the donor.

Neither table has a trailing heap, and records bind to their actor by nodeid
(+0x08), so nothing else changes.

    python tools/fix_drone_bullet.py --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

BULLET_CR = "4fd65c8d2b63d470"     # CSymbol64("CR15NetBulletCRWin10")
PARTICLE_CR = "21a09c2016d8f3e6"   # CSymbol64("CParticleEffectCRWin10")
LEVELS = {
    "42670f2bed45703c": "mpl_combat_combustion",
    "43e2da7914642604": "mpl_combat_dyson",
    "43e2da7a0c623a19": "mpl_combat_gauss",
    "cb9977f7fc2b4526": "mpl_lobby_b_combat",
    "df5ca7b7dfa383d4": "mpl_combat_fission",
}
DONOR_BULLET = 0x12001003B8E9A2A6
DRONE_BULLET = 0xA8F84E7DD40B806E
#: The drone bullet's lifetime (its CR15NetBulletCR record +0x28; seconds: 3 on most bullets, 5 on
#: the long-range ones). A shot every 0.15 s with 3 s bullets keeps ~20 per drone in flight and
#: empties the pool ("No available bullets of type 0xA8F84E7DD40B806E"); at 120 m/s, 1 s still
#: reaches 120 m, past any arena.
DRONE_BULLET_LIFETIME = 1.0
HDR = 0x38


def u64(blob, offset):
    return struct.unpack_from("<Q", blob, offset)[0]


def split(blob):
    size, count = u64(blob, 0x08), u64(blob, 0x28)
    if not count or size % count or len(blob) != HDR + size or u64(blob, 0x30) != count:
        raise ValueError("unexpected CR framing (or a trailing heap)")
    stride = size // count
    return stride, [bytearray(blob[HDR + i * stride:HDR + (i + 1) * stride]) for i in range(count)]


def join(blob, records):
    head = bytearray(blob[:HDR])
    struct.pack_into("<Q", head, 0x08, sum(len(r) for r in records))
    struct.pack_into("<Q", head, 0x28, len(records))
    struct.pack_into("<Q", head, 0x30, len(records))
    return bytes(head) + b"".join(bytes(r) for r in records)


def patch(bullets: bytes, particles: bytes) -> tuple[bytes, bytes]:
    _, brecs = split(bullets)
    donor = next(r for r in brecs if u64(r, 8) == DONOR_BULLET)
    drone = next(r for r in brecs if u64(r, 8) == DRONE_BULLET)
    wanted = {u64(donor, 0x58), u64(donor, 0x60)} - {0xFFFFFFFFFFFFFFFF}

    _, precs = split(particles)
    if not any(u64(r, 8) == DRONE_BULLET for r in precs):
        copies = [bytearray(r) for r in precs if u64(r, 8) == DONOR_BULLET and u64(r, 0) in wanted]
        if len(copies) != len(wanted):
            raise ValueError("donor particle components not found")
        for c in copies:
            struct.pack_into("<Q", c, 8, DRONE_BULLET)
        precs.extend(copies)

    drone[0x58:0x68] = donor[0x58:0x68]
    struct.pack_into("<f", drone, 0x28, DRONE_BULLET_LIFETIME)
    return join(bullets, brecs), join(particles, precs)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv[1:])
    for t in (BULLET_CR, PARTICLE_CR):
        os.makedirs(os.path.join(args.out, t), exist_ok=True)
    for level, name in LEVELS.items():
        bullets = open(os.path.join(args.src, BULLET_CR, level), "rb").read()
        particles = open(os.path.join(args.src, PARTICLE_CR, level), "rb").read()
        nb, np_ = patch(bullets, particles)
        open(os.path.join(args.out, BULLET_CR, level), "wb").write(nb)
        open(os.path.join(args.out, PARTICLE_CR, level), "wb").write(np_)
        print(f"{name}: particle records {u64(particles, 0x28)} -> {u64(np_, 0x28)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
