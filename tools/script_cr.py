"""A level's CScriptCR table (type d99f6bbd8009c92c): read-only walk.

Header 56 bytes (record count at +48), then count x 720-byte records:
  +00 type, +08 actor nodeid, +10 flags, +20 script resource id,
  +30 12 child-table descriptors of 56 bytes (size +8, elem size +32, count +48)
  (realdata ... assetelementdata; index 9 = actordata rows {key, -1, actor nodeid, 0}).
After the records, each non-empty child table's rows, record by record, 8-aligned.
The walk ends exactly at EOF on Dyson, Combustion and Arena.

    python tools/script_cr.py <extract>/d99f6bbd8009c92c/<level>
"""
import struct,sys
def parse(b,align):
    n=struct.unpack_from('<Q',b,48)[0]
    recs=[]
    o=56+n*720
    for r in range(n):
        ro=56+r*720
        tabs=[]
        for i in range(12):
            d=ro+0x30+56*i
            size=struct.unpack_from('<Q',b,d+8)[0]; es=struct.unpack_from("<Q",b,d+32)[0]; cnt=struct.unpack_from('<Q',b,d+48)[0]
            if size:
                o=(o+align-1)//align*align
                tabs.append((i,o,size,es,cnt)); o+=size
        recs.append(dict(idx=r,type=b[ro:ro+8],actor=struct.unpack_from('<Q',b,ro+8)[0],script=struct.unpack_from('<Q',b,ro+32)[0],tabs=tabs))
    return recs,o
if __name__=='__main__':
    b=open(sys.argv[1],'rb').read()
    for a in (1,8,16):
        recs,end=parse(b,a); print(a,hex(end),hex(len(b)))
