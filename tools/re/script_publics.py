"""List a streaming script DLL's public symbols (S_PUB32 / data records) with their rva,
filtered by a regex: e.g. the ctor / Execute / Bind of a node class, or its *_offset slots.

    python tools/re/script_publics.py <script.dll> "ACTIVATEEXPLOSION"
"""
import sys,struct,re
d=open(sys.argv[1],'rb').read()
e=struct.unpack_from('<I',d,0x3c)[0]; n=struct.unpack_from('<H',d,e+6)[0]; so=e+24+struct.unpack_from('<H',d,e+20)[0]
secs=[struct.unpack_from('<8sIIII',d,so+40*i) for i in range(n)]
out={}
for kind in (0x110E,0x110C,0x110D,0x1110,0x1125,0x1127):
  for m in re.finditer(struct.pack('<H',kind),d):
    o=m.start()-2
    if o<0: continue
    ln=struct.unpack_from('<H',d,o)[0]
    if ln<12 or ln>600: continue
    if kind==0x110E:
        flags,off,seg=struct.unpack_from('<IIH',d,o+4); name=d[o+14:o+2+ln].split(b'\0')[0]
    elif kind in (0x110C,0x110D):
        typ,off,seg=struct.unpack_from('<IIH',d,o+4); name=d[o+14:o+2+ln].split(b'\0')[0]
    else: continue
    if not (1<=seg<=n) or not name or not re.fullmatch(rb'[\x20-\x7e]+',name): continue
    va=secs[seg-1][2]+off
    out[name.decode()]=va
for k,v in sorted(out.items(),key=lambda x:x[1]):
    if re.search(sys.argv[2] if len(sys.argv)>2 else '.',k): print('%6x'%v,k)
