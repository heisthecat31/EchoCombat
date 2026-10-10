"""List the functions a streaming script DLL's embedded debug info names (S_GPROC32 records):
rva, length, name -- execute_node_<id>, <CLASS>::Execute, next_node, ...

    python tools/re/script_procs.py <script.dll> > procs.txt
(script.dll: the asset from 6eace9f64204fd0/ with everything before "MZ" cut off)
"""
import sys,struct,re
d=open(sys.argv[1],'rb').read()
e=struct.unpack_from('<I',d,0x3c)[0]; n=struct.unpack_from('<H',d,e+6)[0]; so=e+24+struct.unpack_from('<H',d,e+20)[0]
secs=[struct.unpack_from('<8sIIII',d,so+40*i) for i in range(n)]
out={}
for kind in (0x1110,0x110F,0x1146,0x1147):
  for m in re.finditer(struct.pack('<H',kind),d):
    o=m.start()-2
    ln=struct.unpack_from('<H',d,o)[0]
    if ln<36 or ln>800: continue
    p,end,nxt,plen,ds,de,ti,off,seg,fl=struct.unpack_from('<IIIIIIIIHB',d,o+4)
    name=d[o+39:o+2+ln].split(b'\0')[0]
    if not (1<=seg<=n) or not name or not re.fullmatch(rb'[\x20-\x7e]+',name) or plen>0x10000: continue
    out[secs[seg-1][2]+off]=(name.decode(),plen)
for a,(nm,l) in sorted(out.items()):
    print('%6x %5x %s'%(a,l,nm))
