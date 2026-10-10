"""For every execute_node_<id> that builds a node of one of the given classes, print the
class and the constants it fills the node with (symbols / asset IDs, floats, vectors).

    python tools/re/node_dump.py . script.dll script.asm procs.txt PARTICLE,MATERIAL,TINT,LIGHT
"""
import re,struct,sys
D=sys.argv[1]; dll=sys.argv[2]; asm=sys.argv[3]; procsf=sys.argv[4]; want=sys.argv[5].split(',')
d=open(dll,'rb').read()
e=struct.unpack_from('<I',d,0x3c)[0]; n=struct.unpack_from('<H',d,e+6)[0]; so=e+24+struct.unpack_from('<H',d,e+20)[0]
secs=[struct.unpack_from('<8sIIII',d,so+40*i) for i in range(n)]
def rd(rva,k):
    for nm,vs,va,rs,rp in secs:
        if va<=rva<va+rs: return d[rp+rva-va:rp+rva-va+k]
procs={}
for l in open(procsf):
    s,ln,nm=l.split(None,2); procs[int(s,16)]=(int(ln,16),nm.strip())
cls={a:nm.split('::')[0] for a,(ln,nm) in procs.items() if nm.endswith('::Execute')}
ctor={a:nm.split('::')[0] for a,(ln,nm) in procs.items() if re.match(r'(\w+)::\1$',nm)}
lines=[]
for l in open(asm):
    m=re.match(r'\s+1800([0-9a-f]+):\s+(.*)',l)
    if m: lines.append((int(m.group(1),16),m.group(2)))
def f(u): return struct.unpack('<f',struct.pack('<I',u))[0]
for a,(ln,nm) in sorted(procs.items()):
    if not nm.startswith('execute_node_'): continue
    body=[(x,i) for x,i in lines if a<=x<a+ln]
    c=set()
    for x,i in body:
        m=re.match(r'(call|jmp)\s+0x1800([0-9a-f]+)',i)
        if m:
            t=int(m.group(2),16)
            if t in cls: c.add(cls[t])
            if t in ctor: c.add(ctor[t])
    if not any(w in cc for w in want for cc in c): continue
    vals=[]
    for x,i in body:
        m=re.match(r'movabs\s+\w+,(0x[0-9a-f]+)',i)
        if m: vals.append('sym '+m.group(1)[2:].zfill(16))
        m=re.match(r'mov\s+DWORD PTR \[(r[sb]p[^\]]*)\],(0x[0-9a-f]+)$',i)
        if m:
            u=int(m.group(2),16); fv=f(u)
            vals.append(f'{m.group(1)}={fv:.4g}' if 1e-4<abs(fv)<1e5 else f'{m.group(1)}=int {u}')
        m=re.search(r'(movss|mov)\s+\w+,DWORD PTR \[rip\+0x[0-9a-f]+\]\s+# 0x1800([0-9a-f]+)',i)
        if m:
            r=rd(int(m.group(2),16),4)
            if r: vals.append(f"const {f(struct.unpack('<I',r)[0]):.4g}")
        m=re.search(r'(movaps|movdqa|movups)\s+\w+,XMMWORD PTR \[rip\+0x[0-9a-f]+\]\s+# 0x1800([0-9a-f]+)',i)
        if m:
            b=rd(int(m.group(2),16),16)
            if b: vals.append('vec '+','.join(f'{v:.3g}' for v in struct.unpack('<4f',b)))
    print(nm[13:], '/'.join(sorted(c)), '|', '  '.join(vals))
