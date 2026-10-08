"""A small BC7 encoder: every 4x4 block as mode 6 (one RGBA endpoint pair, 7.7.7.7 + a
p-bit each, 16 interpolation levels). Plenty for flat UI icons; vectorised with numpy.

    blocks = encode(rgba)      # rgba: (h, w, 4) uint8, h and w multiples of 4 -> bytes
"""

from __future__ import annotations

import numpy as np

WEIGHTS = np.array([0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64], np.int32)


def _quantise(e: np.ndarray):
    """Endpoint colours (n, 4) -> (7-bit values (n, 4), p-bit (n,), reconstructed (n, 4))."""
    best_q = best_p = best_r = best_err = None
    for p in (0, 1):
        q = np.clip(np.rint((e.astype(np.int32) - p) / 2), 0, 127).astype(np.int32)
        r = q * 2 + p
        err = np.abs(r - e).sum(axis=1)
        if best_err is None:
            best_q, best_p, best_r, best_err = q, np.full(len(e), p), r, err
        else:
            take = err < best_err
            best_q[take], best_p[take], best_r[take], best_err[take] = q[take], p, r[take], err[take]
    return best_q, best_p, best_r


def encode(rgba: np.ndarray) -> bytes:
    h, w, _ = rgba.shape
    if h % 4 or w % 4:
        raise ValueError("size must be a multiple of 4")
    px = rgba.reshape(h // 4, 4, w // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4).astype(np.int32)
    lo, hi = px.min(axis=1), px.max(axis=1)                       # the block's colour box
    q0, p0, e0 = _quantise(lo)
    q1, p1, e1 = _quantise(hi)
    d = (e1 - e0)[:, None, :]
    dd = (d * d).sum(axis=2)
    t = np.where(dd > 0, ((px - e0[:, None, :]) * d).sum(axis=2) / np.maximum(dd, 1), 0.0)
    idx = np.abs(t[:, :, None] * 64 - WEIGHTS[None, None, :]).argmin(axis=2)   # nearest level
    flip = idx[:, 0] >= 8                                          # the anchor index has a 0 top bit
    q0[flip], q1[flip] = q1[flip].copy(), q0[flip].copy()
    p0[flip], p1[flip] = p1[flip].copy(), p0[flip].copy()
    idx[flip] = 15 - idx[flip]

    n = len(px)
    out = np.zeros((n, 2), np.uint64)                              # 128 bits, little-endian words
    pos = 0

    def put(vals, bits):
        nonlocal pos
        v = vals.astype(np.uint64) & np.uint64((1 << bits) - 1)
        for b in range(bits):
            bit = (v >> np.uint64(b)) & np.uint64(1)
            word, off = divmod(pos + b, 64)
            out[:, word] |= bit << np.uint64(off)
        pos += bits

    put(np.full(n, 1 << 6), 7)                                     # mode 6
    for c in range(4):                                             # R0 R1 G0 G1 B0 B1 A0 A1
        put(q0[:, c], 7)
        put(q1[:, c], 7)
    put(p0, 1)
    put(p1, 1)
    put(idx[:, 0], 3)
    for k in range(1, 16):
        put(idx[:, k], 4)
    return out.astype("<u8").tobytes()
