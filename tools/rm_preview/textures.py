"""Load a game texture (beac1969cb7b8861 + streamed mips) as a float32 numpy array (H, W, C) in 0..1."""

from __future__ import annotations

import io
import os
import struct

import numpy as np

import assets
from PIL import Image

TEX, META, CHUNK = "beac1969cb7b8861", "4a4c32c49300b8a0", "ae49fad43254367a"
SRGB = {72: 71, 78: 77, 99: 98, 29: 28}


def _dds(w, h, fmt, data):
    hdr = bytearray(148)
    hdr[0:4] = b"DDS "
    struct.pack_into("<IIIII", hdr, 4, 124, 0x1007 | 0x80000, h, w, len(data))
    struct.pack_into("<I", hdr, 28, 1)
    struct.pack_into("<II", hdr, 76, 32, 4)
    hdr[84:88] = b"DX10"
    struct.pack_into("<I", hdr, 108, 0x1000)
    struct.pack_into("<IIIII", hdr, 128, fmt, 3, 0, 1, 0)
    return bytes(hdr) + data


def raw(root: str, tid: str):
    """(w, h, dxgi format, top-mip bytes)."""
    b = open(assets.path(root, TEX, tid), "rb").read()
    if b[:4] == b"DDS ":
        h, w = struct.unpack_from("<II", b, 12)
        return w, h, struct.unpack_from("<I", b, 128)[0], b[148:]
    meta = open(assets.path(root, META, tid), "rb").read()
    w, h = struct.unpack_from("<II", meta, 0xC4)
    fmt = struct.unpack_from("<I", meta, 0xD8)[0]
    ids = [struct.unpack_from("<Q", meta, o)[0] for o in range(0x40, 0x80, 8)]
    blobs = [open(assets.path(root, CHUNK, f"{c:016x}"), "rb").read()
             for c in ids if c != 2**64 - 1 and os.path.exists(assets.path(root, CHUNK, f"{c:016x}"))]
    return w, h, fmt, max(blobs, key=len)


def load(root: str, tid: str) -> np.ndarray:
    w, h, fmt, data = raw(root, tid)
    srgb = fmt in SRGB
    fmt = SRGB.get(fmt, fmt)
    if fmt == 61:
        a = np.frombuffer(data[:w * h], np.uint8).reshape(h, w, 1)
    elif fmt == 28:
        a = np.frombuffer(data[:w * h * 4], np.uint8).reshape(h, w, 4)
    else:
        im = Image.open(io.BytesIO(_dds(w, h, fmt, data)))
        im.load()
        a = np.asarray(im)
        if a.ndim == 2:
            a = a[:, :, None]
    a = a.astype(np.float32) / 255.0
    if srgb:  # the GPU samples sRGB formats as linear
        rgb = a[..., :3]
        a[..., :3] = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return a
