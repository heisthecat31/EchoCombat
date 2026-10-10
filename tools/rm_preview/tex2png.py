"""Decode the collected textures (beac1969cb7b8861 DDS + streamed mips) to PNG."""
import io, os, struct, sys
from PIL import Image
V = sys.argv[1]; OUT = sys.argv[2]
TEX, META, CHUNK = 'beac1969cb7b8861', '4a4c32c49300b8a0', 'ae49fad43254367a'
BPB = {71: 8, 72: 8, 80: 8, 77: 16, 78: 16, 83: 16, 98: 16, 99: 16}

def dds(w, h, fmt, data):
    hdr = bytearray(148)
    hdr[0:4] = b'DDS '
    struct.pack_into('<IIIII', hdr, 4, 124, 0x1007 | 0x80000, h, w, len(data))
    struct.pack_into('<I', hdr, 28, 1)
    struct.pack_into('<II', hdr, 76, 32, 4); hdr[84:88] = b'DX10'
    struct.pack_into('<I', hdr, 108, 0x1000)
    struct.pack_into('<IIIII', hdr, 128, fmt, 3, 0, 1, 0)
    return bytes(hdr) + data

def decode(w, h, fmt, data):
    fmt = {72: 71, 78: 77, 99: 98, 30: 28}.get(fmt, fmt)
    if fmt == 61:  # R8
        return Image.frombytes('L', (w, h), data[:w * h])
    if fmt in (28, 29):
        return Image.frombytes('RGBA', (w, h), data[:w * h * 4])
    im = Image.open(io.BytesIO(dds(w, h, fmt, data))); im.load(); return im

for n in sorted(os.listdir(f'{V}/{TEX}')):
    b = open(f'{V}/{TEX}/{n}', 'rb').read()
    meta = open(f'{V}/{META}/{n}', 'rb').read() if os.path.exists(f'{V}/{META}/{n}') else b''
    try:
        if b[:4] == b'DDS ':
            h, w = struct.unpack_from('<II', b, 12); fmt = struct.unpack_from('<I', b, 128)[0]
            data = b[148:]
        else:  # streamed: full size at meta+0xc4, top mip in the highest-numbered chunk
            w, h = struct.unpack_from('<II', meta, 0xc4); fmt = struct.unpack_from('<I', meta, 0xd8)[0]
            chunks = [struct.unpack_from('<Q', meta, o)[0] for o in range(0x40, 0x80, 8)]
            chunks = [c for c in chunks if c != 0xFFFFFFFFFFFFFFFF]
            data = max((open(f'{V}/{CHUNK}/{c:016x}', 'rb').read() for c in chunks if os.path.exists(f'{V}/{CHUNK}/{c:016x}')), key=len)
        im = decode(w, h, fmt, data)
        im.save(f'{OUT}/{n}.png')
        print(n, w, h, fmt, im.mode, 'ok')
    except Exception as e:
        print(n, 'FAIL', e)
