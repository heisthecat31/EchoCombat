"""Print a parsed effect's structs field by field (headers skipped) as u32 / f32 / 2 x f16."""
import struct, sys
import numpy as np
import effect_file as ef

def fmt(b, start, end, skip):
    out = []
    o = start
    while o < end:
        if o in skip:
            o = skip[o]; continue
        w = b[o:o+4]
        if len(w) < 4:
            out.append(f'    +{o-start:03x} {w.hex()}'); break
        u, = struct.unpack('<I', w); f, = struct.unpack('<f', w)
        h = np.frombuffer(w, np.float16)
        fs = f'{f:.6g}' if (1e-6 < abs(f) < 1e7 or f == 0) else ''
        out.append(f'    +{o-start:03x} {u:08x} {u:>11d}  f={fs:<12} h=({h[0]:.4g},{h[1]:.4g})')
        o += 4
    return out

def show(b, s, name, depth=0, maxel=99):
    skip = {a.at: a.at + (0x20 if a.blob else 0x38) for a in s.arrays}
    print('  ' * depth + f'== {name} @{s.at:#x} size {s.size:#x}')
    for l in fmt(b, s.at, s.at + s.size, skip):
        print('  ' * depth + l)
    for i, a in enumerate(s.arrays):
        rel = a.at - s.at
        if a.blob and a.size:
            print('  ' * depth + f'  -- blob (hdr +{rel:#x}) {a.size:#x} bytes @{a.data:#x}')
            for l in fmt(b, a.data, a.data + a.size, {}): print('  ' * depth + '  ' + l)
        for k, e in enumerate(a.elems[:maxel]):
            show(b, e, f'{name}.arr(hdr+{rel:#x})[{k}]', depth + 1, maxel)

if __name__ == '__main__':
    b = open(sys.argv[1], 'rb').read()
    root = ef.parse(b)
    show(b, root, 'root')
