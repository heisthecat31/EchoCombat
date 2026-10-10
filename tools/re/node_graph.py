"""Rebuild a script's node graph from its next_node function: "<node> -> <next nodes>" per line.

    objdump -d --no-show-raw-insn -M intel script.dll > script.asm
    python tools/re/node_graph.py script.asm <next_node rva hex> <end rva hex> > graph.txt
(next_node's rva and length come from script_procs.py)
"""
import re,sys
asm=sys.argv[1]; lo,hi=int(sys.argv[2],16),int(sys.argv[3],16)
ins=[]
for l in open(asm):
    m=re.match(r'\s+([0-9a-f]+):\s+(.*)',l)
    if m:
        a=int(m.group(1),16)-0x180000000
        if lo<=a<hi: ins.append((a,m.group(2).strip()))
idx={a:i for i,(a,_) in enumerate(ins)}
def val(s):
    m=re.search(r',(0x[0-9a-f]+)$',s); return int(m.group(1),16) if m else None
# dispatcher: cmp rcx,ID (or mov r8d,ID; cmp rcx,r8) then je T
entries={}
reg={}
for i,(a,s) in enumerate(ins):
    if s.startswith('mov ') and re.match(r'mov\s+(r\w+),0x',s):
        r=re.match(r'mov\s+(r\w+?)d?,(0x[0-9a-f]+)',s); reg[r.group(1)]=int(r.group(2),16)
    m0=re.match(r'mov\s+e(\w\w),(0x[0-9a-f]+)$',s)
    if m0: reg['r'+m0.group(1)]=int(m0.group(2),16)
    m=re.match(r'cmp\s+rcx,(\S+)',s)
    if m:
        v=m.group(1); nid=int(v,16) if v.startswith('0x') else reg.get(v.rstrip('d'),None)
        # find following je
        for j in range(i+1,min(i+4,len(ins))):
            mm=re.match(r'je\s+0x([0-9a-f]+)',ins[j][1])
            if mm: entries[nid]=int(mm.group(1),16)-0x180000000; break
            if ins[j][1].startswith('jne') and j==i+1: entries[nid]=ins[j+1][0]; break
def follow(t,depth=0,seen=None):
    seen=seen or set(); outs=set(); i=idx.get(t)
    if i is None or t in seen or depth>30: return outs
    seen.add(t)
    while i<len(ins):
        a,s=ins[i]
        m=re.match(r'(mov|movabs)\s+[re]ax,(0x[0-9a-f]+)',s)
        if m and i+1<len(ins) and ins[i+1][1]=='ret': outs.add(int(m.group(2),16)&0xffffffff); return outs
        m=re.match(r'(je|jne|jmp|jg|jl)\s+0x([0-9a-f]+)',s)
        if m:
            tgt=int(m.group(2),16)-0x180000000
            if m.group(1)=='jmp': return outs|follow(tgt,depth+1,seen)
            outs|=follow(tgt,depth+1,seen)
        if s=='ret': return outs
        i+=1
    return outs
for n,t in sorted((k,v) for k,v in entries.items() if k is not None):
    if n is None: continue
    o=follow(t)
    print('%08x -> %s'%(n,' '.join('%08x'%x for x in sorted(o) if x!=0xffffffff)))
