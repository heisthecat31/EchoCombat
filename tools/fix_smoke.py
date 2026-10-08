"""UMBRAL VEIL (the cut `smoke` tac mod) as a fifth tac mod, with its own script.

No script among the 567 reads any `ability_properties|smoke|*` key and no smoke
wall actor exists, so the tac mod is built here. How tac mods work (the
player's scripts, global level 3f9915d3001dc28e):

* the combat player actors (91d8de0806964a11, f1e70acd0dde0312, the one the
  client swaps to in a match) run all four tac mod scripts plus a controller,
  4b65d1b009973281 (b113997837c29003 has neither barrier nor controller)
* the controller's graph runs one EXTERNALFUNCTION node per tac mod, in a
  chain: fa6ff977 -> sensor 8e119d0a -> heal 59aa7284 -> barrier 5e2732a4 ->
  wraith 5613c5a8 -> end. Each calls its script's enable function
  (3efff939e87f2683) with a flag param (43e1ed75065c0148) = "equipped == <name>"
* the engine calls `Activate` (37ee801e3ffe9063); the enabled script acts, e.g.
  the barrier script creates the pooled wall actor 3d8b8ca4d5292926.

Stage 1 (enable the barrier for smoke too) proved the engine side: UMBRAL VEIL
can be equipped, charges, and its use reaches the scripts. This is stage 2:

1. `smoke` is registered in gear_table.tacmods as UMBRAL VEIL (its tuning is
   already in ability_properties.smoke).
2. A new script, `mp_combat_ability_smoke` (CSymbol64 94ba7ca09dcf7b0b), is a
   copy of the barrier script whose wall spawn is replaced by detonator smoke
   clouds (veil_fx.py): no wall, no collision, both teams see it. It gets its
   `CScriptResourceWin10` entry and is attached to each actor that runs the
   barrier script, right after it.
3. The controller gets a fifth branch, wraith -> new node 5613c5a9 -> end,
   calling the smoke script's enable function with "equipped == smoke":
   * the controller's .text grows into the free address space before .rdata
     (later sections shift down in the file; RVAs do not change)
   * the new node is a byte copy of the barrier call node (execute_node_5e2732a4,
     851 bytes, checked by SHA-256) with its 11 references outside the function
     re-aimed, the script hash swapped, and its flag call pointed at a new
     "equipped == smoke" expression; it gets a .pdata entry reusing the
     original's unwind info
   * execute_node's entry jumps to a stub that runs the copy for node 5613c5a9;
     next_node's default case jumps to a stub that sends wraith's `out` to it.
   The barrier's own flag stays "== shield".
4. Networked (default): the tac mod graph runs on the user's client only, so
   the smoke script no longer spawns anything itself. It creates the barrier
   wall as the barrier does, with a marker in the wall's symbol param; the wall
   script, on every machine, reads it back and turns that wall into the veil
   (veil_fx.network_wall). --local keeps the old client-only veil.

    python tools/fix_smoke.py --base <dir with 607d858c90268f9a/> --src <extract root> --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fix_drone import EQUIPMENT, load, save

SCRIPTS = "6eace9f64204fd0"            # CSymbol64("StreamingScriptWin10")
SCRIPT_RESOURCE = "991421b41de58370"   # CSymbol64("CScriptResourceWin10")
SCRIPT_CR = "d99f6bbd8009c92c"         # CSymbol64("CScriptCRWin10")
GLOBAL_LEVEL = "3f9915d3001dc28e"
CONTROLLER = "4b65d1b009973281"
BARRIER_SCRIPT = 0xB87BA2039B049D5E
SMOKE_SCRIPT = 0x94BA7CA09DCF7B0B      # CSymbol64("mp_combat_ability_smoke")
PLAYER_ACTORS = (0x91D8DE0806964A11, 0xF1E70ACD0DDE0312)
SMOKE_GEAR = {"name": "smoke", "display_name": "UMBRAL VEIL"}
SMOKE = 0xE32DC7C9D4804FB5             # CSymbol64("smoke")

DET_SCRIPT = "190ed14fe3da5ed1"          # mp_combat_grenade_det: its smoke particle node
WALL_SCRIPT = "ac4e9374a146d3a4"         # the barrier wall's own script (smoke wall mode added)

# --- controller layout (checked) -------------------------------------------
NODE_FN = 0x12670                      # execute_node_5e2732a4 (barrier enable call)
NODE_LEN = 851
NODE_SHA = "2c495b37b8e9a34997bdec0d3582f9ecd37d781153ec9a25109d1884ae874aed"
NODE_SCRIPT_IMM = 197                  # movabs r12, <script hash>: imm offset in fn
FLAG_CALL = 374                        # call expression_5e2732a4_params_0_flagvalue
#: (rel32 offset in fn, target rva, offset of the next instruction in fn)
FIXUPS = [(229, 0x2B938, 233), (315, 0x2B4A8, 319), (374, 0x20CA0, 378),
          (430, 0x2B840, 434), (469, 0x2BFC8, 473), (522, 0x2BCA0, 526),
          (578, 0x2C0E0, 582), (642, 0x2BE28, 646), (681, 0x2BD50, 685),
          (722, 0x2BF28, 726), (771, 0x2B780, 775)]
NODE_UNWIND = 0x28F0C
EXEC_ENTRY = 0xB5C0                    # execute_node: mov rax,[rcx+10h]; mov edx,8936533Fh
EXEC_ENTRY_OLD = bytes.fromhex("488b4110ba3f533689")
EXEC_RESUME = 0xB5C9                   # cmp rax, rdx
NEXT_DEFAULT = 0x1B2BF                 # next_node default: or rax,-1; ret
NEXT_DEFAULT_OLD = bytes.fromhex("4883c8ffc3")
WRAITH_NODE = 0x5613C5A8
NEW_NODE = 0x5613C5A9
OUT_PORT = 0x33F5911416F09172


def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def u64(b, o): return struct.unpack_from("<Q", b, o)[0]


class PE:
    """Just enough PE32+ to grow .text into its trailing address space."""

    def __init__(self, data: bytes):
        self.d = bytearray(data)
        self.e = u32(self.d, 0x3C)
        self.nsec = u16(self.d, self.e + 6)
        self.opt = self.e + 24
        self.sec0 = self.opt + u16(self.d, self.e + 20)

    def sections(self):
        for i in range(self.nsec):
            o = self.sec0 + i * 40
            yield o, self.d[o:o + 8].rstrip(b"\0"), *struct.unpack_from("<IIII", self.d, o + 8)

    def section(self, name):
        for s in self.sections():
            if s[1] == name:
                return s
        raise ValueError(f"no {name} section")

    def raw(self, rva):
        for _, _, vsize, va, rsize, rawp in self.sections():
            if va <= rva < va + max(vsize, rsize):
                return rawp + rva - va
        raise ValueError(f"rva {rva:#x} not in any section")

    def read(self, rva, n): return bytes(self.d[self.raw(rva):self.raw(rva) + n])

    def write(self, rva, b): self.d[self.raw(rva):self.raw(rva) + len(b)] = b

    def grow_text(self, new_vsize):
        o, _, vsize, va, rsize, rawp = self.section(b".text")
        next_va = min(s[3] for s in self.sections() if s[3] > va)
        if va + new_vsize > next_va:
            raise ValueError("not enough address space after .text")
        falign = u32(self.d, self.opt + 36)
        new_rsize = (new_vsize + falign - 1) // falign * falign
        delta = max(0, new_rsize - rsize)
        end = rawp + rsize
        self.d[end:end] = bytes(delta)
        struct.pack_into("<II", self.d, o + 8, new_vsize, va)
        struct.pack_into("<I", self.d, o + 16, rsize + delta)
        for so, _, _, _, _, p in self.sections():
            if p >= end and so != o:
                struct.pack_into("<I", self.d, so + 20, p + delta)
        struct.pack_into("<I", self.d, self.opt + 4, u32(self.d, self.opt + 4) + delta)  # SizeOfCode
        dbg_rva, dbg_size = struct.unpack_from("<II", self.d, self.opt + 112 + 6 * 8)
        for k in range(dbg_size // 28):
            ent = self.raw(dbg_rva) + k * 28
            p = u32(self.d, ent + 24)
            if p >= end:
                struct.pack_into("<I", self.d, ent + 24, p + delta)


def rel32(src_next, target):
    return struct.pack("<i", target - src_next)


def add_branches(pe_bytes: bytes, branches) -> bytes:
    """Chain new tac mods after wraith: wraith -> NEW_NODE -> NEW_NODE+1 -> ...;
    branches = [(CSymbol64 of the tac mod's name, its script hash), ...]."""
    pe = PE(pe_bytes)
    if pe.read(EXEC_ENTRY, 9) != EXEC_ENTRY_OLD:
        if pe.read(EXEC_ENTRY, 1) == b"\xe9":
            return pe_bytes                           # already patched
        raise ValueError("unexpected execute_node entry: wrong controller build")
    original = pe.read(NODE_FN, NODE_LEN)
    if hashlib.sha256(original).hexdigest() != NODE_SHA:
        raise ValueError("barrier call node differs: wrong controller build")
    if pe.read(NEXT_DEFAULT, 5) != NEXT_DEFAULT_OLD:
        raise ValueError("unexpected next_node default: wrong controller build")
    if u64(original, NODE_SCRIPT_IMM) != BARRIER_SCRIPT:
        raise ValueError("barrier script hash not where expected")

    _, _, vsize, text_va, _, _ = pe.section(b".text")
    at = (text_va + vsize + 15) & ~15
    writes, nodes = [], []
    for i, (symbol, script) in enumerate(branches):
        # 1. "equipped == <name>"
        expr_rva = at
        expr = (bytes.fromhex("488b01 488b4068 48ba") + struct.pack("<Q", symbol)
                + bytes.fromhex("483990f0000000 0f94c0 c3"))
        # 2. the copied node, calling this tac mod's script
        node_rva = (expr_rva + len(expr) + 15) & ~15
        node = bytearray(original)
        for off, target, nxt in FIXUPS:
            node[off:off + 4] = rel32(node_rva + nxt, expr_rva if off == FLAG_CALL else target)
        struct.pack_into("<Q", node, NODE_SCRIPT_IMM, script)
        writes += [(expr_rva, expr), (node_rva, bytes(node))]
        nodes.append((NEW_NODE + i, node_rva))
        at = (node_rva + NODE_LEN + 15) & ~15
    # 3. execute_node hook: each new node id runs its copy
    exec_rva = at
    stub_a = bytearray(bytes.fromhex("488b4110"))                     # mov rax, [rcx+10h]
    for node_id, node_rva in nodes:
        stub_a += b"\x48\x3d" + struct.pack("<I", node_id) + b"\x0f\x84"   # cmp rax, id; je copy
        stub_a += rel32(exec_rva + len(stub_a) + 4, node_rva)
    stub_a += b"\xba" + struct.pack("<I", 0x8936533F) + b"\xe9"            # mov edx, ...; jmp resume
    stub_a += rel32(exec_rva + len(stub_a) + 4, EXEC_RESUME)
    # 4. next_node hook: wraith --out--> first new node --out--> second ...
    next_rva = (exec_rva + len(stub_a) + 15) & ~15
    chain = [WRAITH_NODE] + [n for n, _ in nodes]
    blocks = len(nodes) * 35
    stub_b = bytearray()
    for prev, new in zip(chain, chain[1:]):
        base = len(stub_b)
        to_l = blocks - (base + 29)                                  # from the 2nd jne to L
        stub_b += (b"\x48\x81\xf9" + struct.pack("<I", prev)          # cmp rcx, prev
                   + b"\x75\x1a"                                     # jne next block
                   + b"\x48\x85\xd2" + b"\x74\x0f"                   # test rdx,rdx; je G
                   + b"\x48\xb8" + struct.pack("<Q", OUT_PORT)       # mov rax, out
                   + b"\x48\x39\xc2" + b"\x75" + bytes([to_l])       # cmp rdx,rax; jne L
                   + b"\xb8" + struct.pack("<I", new) + b"\xc3")      # G: mov eax,new; ret
        assert len(stub_b) - base == 35 and to_l < 128
    stub_b += b"\x48\x83\xc8\xff\xc3"                              # L: or rax,-1; ret
    end = next_rva + len(stub_b)

    pe.grow_text(end - text_va)
    for rva, data in writes:
        pe.write(rva, data)
    pe.write(exec_rva, bytes(stub_a))
    pe.write(next_rva, bytes(stub_b))
    pe.write(EXEC_ENTRY, b"\xe9" + rel32(EXEC_ENTRY + 5, exec_rva) + b"\x90" * 4)
    pe.write(NEXT_DEFAULT, b"\xe9" + rel32(NEXT_DEFAULT + 5, next_rva))

    # 5. .pdata entries for the copied nodes (sorted: they are the highest addresses)
    exc_rva, exc_size = struct.unpack_from("<II", pe.d, pe.opt + 112 + 3 * 8)
    o, _, pvsize, pva, prsize, _ = pe.section(b".pdata")
    if exc_rva != pva or exc_size + 12 * len(nodes) > prsize:
        raise ValueError("no room for .pdata entries")
    last = u32(pe.read(exc_rva + exc_size - 12, 4), 0)
    if last >= nodes[0][1]:
        raise ValueError(".pdata would not stay sorted")
    for _, node_rva in nodes:
        pe.write(exc_rva + exc_size, struct.pack("<III", node_rva, node_rva + NODE_LEN, NODE_UNWIND))
        exc_size += 12
    struct.pack_into("<I", pe.d, pe.opt + 112 + 3 * 8 + 4, exc_size)
    struct.pack_into("<I", pe.d, o + 8, max(pvsize, exc_size))
    return bytes(pe.d)


def add_smoke_branch(pe_bytes: bytes) -> bytes:
    return add_branches(pe_bytes, [(SMOKE, SMOKE_SCRIPT)])


def smoke_script(barrier_asset: bytes, det_asset: bytes, **veil) -> bytes:
    """The barrier script, spawning smoke clouds instead of the wall."""
    from veil_fx import add_smoke_fx
    mz, dmz = barrier_asset.find(b"MZ"), det_asset.find(b"MZ")
    return barrier_asset[:mz] + add_smoke_fx(barrier_asset[mz:], det_asset[dmz:], **veil)


def patch_controller(asset: bytes, extra=()) -> bytes:
    """The fifth branch (smoke), plus any `extra` (symbol, script) tac mods after it."""
    mz = asset.find(b"MZ")
    return asset[:mz] + add_branches(asset[mz:], [(SMOKE, SMOKE_SCRIPT), *extra])


def attach_smoke_script(blob: bytes) -> bytes:
    """Add a smoke-script entry after each player actor's barrier-script entry."""
    stride, hdr = 720, 0x38
    count = u64(blob, 0x28)
    if u64(blob, 0x08) != count * stride or u64(blob, 0x30) != count:
        raise ValueError("unexpected CScriptCR framing")
    entries = [blob[hdr + stride * i:hdr + stride * (i + 1)] for i in range(count)]
    pool = blob[hdr + stride * count:]
    out, added = [], 0
    for e in entries:
        out.append(e)
        if u64(e, 8) in PLAYER_ACTORS and u64(e, 32) == BARRIER_SCRIPT:
            if any(u64(x, 8) == u64(e, 8) and u64(x, 32) == SMOKE_SCRIPT for x in entries):
                continue                              # already attached
            for t in (48, 104, 160, 216, 272, 328, 384, 440, 496, 552, 608, 664):
                if u64(e, t + 8):
                    raise ValueError("barrier entry carries pool data")
            new = bytearray(e)
            struct.pack_into("<Q", new, 0, SMOKE_SCRIPT)
            struct.pack_into("<Q", new, 32, SMOKE_SCRIPT)
            out.append(bytes(new))
            added += 1
    head = bytearray(blob[:hdr])
    struct.pack_into("<Q", head, 0x08, len(out) * stride)
    struct.pack_into("<Q", head, 0x28, len(out))
    struct.pack_into("<Q", head, 0x30, len(out))
    return bytes(head) + b"".join(out) + pool, added


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="dir holding the live 607d858c90268f9a/ JSON")
    ap.add_argument("--src", required=True, help="extract root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-buff", action="store_true",
                    help="also give the controller POWER BOOST's branch (wraith -> smoke -> buff); fix_buff.py does the rest")
    ap.add_argument("--count", type=int, default=7, help="smoke clouds per use")
    ap.add_argument("--scale", type=float, default=6.0, help="cloud size (the detonator's is about 2)")
    ap.add_argument("--life", type=float, default=8.0, help="how much longer the smoke lasts than the detonator's")
    ap.add_argument("--spread", type=float, default=1.5, help="metres between the clouds")
    ap.add_argument("--emission", type=float, default=8.0, help="particles per cloud, x the detonator's")
    ap.add_argument("--particle-scale", type=float, default=2.5, help="size of each smoke puff")
    ap.add_argument("--alpha", type=float, default=10.0, help="opacity multiplier")
    ap.add_argument("--shade", type=float, default=0.9, help="colour multiplier (lower = darker)")
    ap.add_argument("--local", action="store_true",
                    help="the old, client-only veil: clouds and sound spawned by the smoke script itself, so only "
                         "the user sees and hears them. Default: networked through the barrier wall (veil_fx.network_wall)")
    ap.add_argument("--mailbox", type=lambda v: int(v, 0), default=0,
                    help="rva of the spare bytes in echovr.exe (veil_fx.mailbox_rva): the sound then plays "
                         "from an invisible smoke wall, so it stays where the veil went off; 0 = it follows the player")
    args = ap.parse_args(argv[1:])

    eq_path, equipment = load(args.base, EQUIPMENT)
    tacmods = equipment["gear_table"]["tacmods"]
    if not any(t["name"] == "smoke" for t in tacmods):
        tacmods.append(dict(SMOKE_GEAR))
    print(save(args.out, EQUIPMENT, eq_path, equipment))
    print("tacmods:", [t["name"] for t in tacmods])

    os.makedirs(os.path.join(args.out, SCRIPTS), exist_ok=True)
    ctrl = open(os.path.join(args.src, SCRIPTS, CONTROLLER), "rb").read()
    extra = [(0xC8C33E48386618B6, 0x4B65D1B0088D2682)] if args.with_buff else []   # buff, its script
    open(os.path.join(args.out, SCRIPTS, CONTROLLER), "wb").write(patch_controller(ctrl, extra))
    print(f"{SCRIPTS}/{CONTROLLER}: fifth tac mod branch -> mp_combat_ability_smoke"
          + (", sixth -> mp_combat_ability_buff" if extra else ""))

    barrier = open(os.path.join(args.src, SCRIPTS, f"{BARRIER_SCRIPT:x}"), "rb").read()
    det = open(os.path.join(args.src, SCRIPTS, DET_SCRIPT), "rb").read()
    networked = not (args.local or args.mailbox)
    if networked:
        from veil_fx import QUERY_SCRIPT, mark_param, network_wall
        mz, dmz = barrier.find(b"MZ"), det.find(b"MZ")
        open(os.path.join(args.out, SCRIPTS, f"{SMOKE_SCRIPT:x}"), "wb").write(
            barrier[:mz] + mark_param(barrier[mz:]))
        wall = open(os.path.join(args.src, SCRIPTS, WALL_SCRIPT), "rb").read()
        query = open(os.path.join(args.src, SCRIPTS, QUERY_SCRIPT), "rb").read()
        wmz = wall.find(b"MZ")
        open(os.path.join(args.out, SCRIPTS, WALL_SCRIPT), "wb").write(wall[:wmz] + network_wall(
            wall[wmz:], query[query.find(b"MZ"):], det[dmz:], count=args.count, scale=args.scale, life=args.life,
            spread=args.spread, emission=args.emission, particle_scale=args.particle_scale, alpha=args.alpha,
            shade=args.shade))
        print(f"{SCRIPTS}/{WALL_SCRIPT}: barrier wall script: a wall carrying the veil marker hides, has no "
              f"collision, and spawns the smoke and sound -- on every machine")
    else:
        open(os.path.join(args.out, SCRIPTS, f"{SMOKE_SCRIPT:x}"), "wb").write(smoke_script(
            barrier, det, count=args.count, scale=args.scale, life=args.life, spread=args.spread,
            emission=args.emission, particle_scale=args.particle_scale, alpha=args.alpha, shade=args.shade,
            mailbox=args.mailbox))
    if args.mailbox and not networked:
        from veil_fx import anchor_wall
        wall = open(os.path.join(args.src, SCRIPTS, WALL_SCRIPT), "rb").read()
        mz = wall.find(b"MZ")
        open(os.path.join(args.out, SCRIPTS, WALL_SCRIPT), "wb").write(wall[:mz] + anchor_wall(wall[mz:], args.mailbox))
        print(f"{SCRIPTS}/{WALL_SCRIPT}: barrier wall script gains the smoke wall mode (mailbox {args.mailbox:#x})")
    os.makedirs(os.path.join(args.out, SCRIPT_RESOURCE), exist_ok=True)
    open(os.path.join(args.out, SCRIPT_RESOURCE, f"{SMOKE_SCRIPT:x}"), "wb").write(bytes(4))
    print(f"{SCRIPTS}/{SMOKE_SCRIPT:x}: mp_combat_ability_smoke: {args.count} smoke clouds, "
          f"scale {args.scale}, life x{args.life}, {args.spread} m apart, "
          f"emission x{args.emission}, puffs x{args.particle_scale}, alpha x{args.alpha}, shade {args.shade}, "
          + ("networked: the wall it creates carries the smoke and sound to every machine" if networked else
             "sound from an invisible smoke wall" if args.mailbox else "LOCAL ONLY: no wall, sound on the player"))

    os.makedirs(os.path.join(args.out, SCRIPT_CR), exist_ok=True)
    staged = os.path.join(args.out, SCRIPT_CR, GLOBAL_LEVEL)
    src = staged if os.path.exists(staged) else os.path.join(args.src, SCRIPT_CR, GLOBAL_LEVEL)
    fixed, added = attach_smoke_script(open(src, "rb").read())
    open(staged, "wb").write(fixed)
    print(f"global level: smoke script attached to {added} player actor(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
