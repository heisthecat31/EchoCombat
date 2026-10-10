"""Run DXIL shaders on the CPU: transpile `dxc -dumpbin` IR to Python.

The game's particle effects are simulated by DXIL compute shaders generated per
effect, and drawn by the engine's own vertex/pixel shaders. To render an effect
offline the way the engine does, this runs those exact shaders: every function
in the IR becomes a Python generator, one instance per GPU thread. SSA values
become locals, phi nodes become parallel assignments on each branch, a group
barrier is a `yield` (all threads of a group are stepped to it before any goes
on), and resources are looked up by name through the shader's binding table.

Values: i1 -> bool, iN -> unsigned Python int, float -> Python float (math is
done in double and rounded to f32 only where bits matter: bitcasts, stores,
half conversions). The shaders use fast math, so this is within their own
tolerance.

    sh = Shader.load("x.ll")
    sh.bind["gPSysTable"] = {0: StructBuf(data, 84)}
    sh.dispatch(groups=(n, 1, 1))
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field

import numpy as np

M32 = 0xFFFFFFFF
_f32 = struct.Struct("<f")
_u32 = struct.Struct("<I")


# ---------------------------------------------------------------- scalar helpers
def f2u(f):
    try:
        return _u32.unpack(_f32.pack(f))[0]
    except OverflowError:
        return 0x7F800000 if f > 0 else 0xFF800000


def u2f(u):
    return _f32.unpack(_u32.pack(u & M32))[0]


def rf(f):
    """Round to f32."""
    try:
        return _f32.unpack(_f32.pack(f))[0]
    except OverflowError:
        return math.inf if f > 0 else -math.inf


def s32(u):
    u &= M32
    return u - 0x100000000 if u & 0x80000000 else u


def f16_to_f32(h):
    return float(np.frombuffer(struct.pack("<H", h & 0xFFFF), np.float16)[0])


def f32_to_f16(f):
    return int(np.frombuffer(np.float16(f).tobytes(), np.uint16)[0])


def fdiv(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        if a == 0 or a != a:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)


def fptoui(f):
    if f != f or f <= 0:
        return 0
    if f >= 4294967295.0:
        return M32
    return int(f)


def fptosi(f):
    if f != f:
        return 0
    if f >= 2147483647.0:
        return 0x7FFFFFFF
    if f <= -2147483648.0:
        return 0x80000000
    return int(f) & M32


def _rsqrt(x):
    if x > 0:
        return 1.0 / math.sqrt(x)
    return math.inf if x == 0 else math.nan


def _sqrt(x):
    return math.sqrt(x) if x >= 0 else math.nan


def _log2(x):
    if x > 0:
        return math.log2(x)
    return -math.inf if x == 0 else math.nan


def _exp2(x):
    try:
        return 2.0 ** x
    except OverflowError:
        return math.inf


def _frc(x):
    return x - math.floor(x) if math.isfinite(x) else math.nan


def _sat(x):
    return 0.0 if x < 0 or x != x else (1.0 if x > 1 else x)


def _fmax(a, b):
    if a != a:
        return b
    if b != b:
        return a
    return a if a > b else b


def _fmin(a, b):
    if a != a:
        return b
    if b != b:
        return a
    return a if a < b else b


def _safe(fn):
    def g(x):
        try:
            return fn(x)
        except (ValueError, OverflowError):
            return math.nan
    return g


UNARY = {
    6: abs, 7: _sat, 12: _safe(math.cos), 13: _safe(math.sin), 14: _safe(math.tan),
    15: _safe(math.acos), 16: _safe(math.asin), 17: math.atan, 21: _exp2, 22: _frc, 23: _log2,
    24: _sqrt, 25: _rsqrt, 26: lambda x: float(round(x)) if math.isfinite(x) else x,
    27: lambda x: float(math.floor(x)) if math.isfinite(x) else x,
    28: lambda x: float(math.ceil(x)) if math.isfinite(x) else x,
    29: lambda x: float(math.trunc(x)) if math.isfinite(x) else x,
}
BINARY_F = {35: _fmax, 36: _fmin}
BINARY_I = {37: lambda a, b: max(s32(a), s32(b)) & M32, 38: lambda a, b: min(s32(a), s32(b)) & M32,
            39: max, 40: min}


# ---------------------------------------------------------------- resources
class RawBuf:
    """ByteAddressBuffer / RWByteAddressBuffer (index = byte offset)."""

    def __init__(self, data=b"", size=None):
        self.b = bytearray(data) if size is None else bytearray(size)
        if size is not None and data:
            self.b[:len(data)] = data

    def _grow(self, n):
        if n > len(self.b):
            self.b.extend(bytes(n - len(self.b)))

    def load(self, idx, wot):
        o = idx & ~3
        self._grow(o + 16)
        return struct.unpack_from("<4I", self.b, o) + (1,)

    def store(self, idx, wot, vals, mask):
        o = idx & ~3
        self._grow(o + 16)
        for i in range(4):
            if mask >> i & 1:
                struct.pack_into("<I", self.b, o + 4 * i, vals[i] & M32)


class StructBuf(RawBuf):
    def __init__(self, data=b"", stride=4, size=None):
        super().__init__(data, size)
        self.stride = stride

    def load(self, idx, wot):
        return super().load(idx * self.stride + (wot or 0), 0)

    def store(self, idx, wot, vals, mask):
        super().store(idx * self.stride + (wot or 0), 0, vals, mask)


class TypedBuf:
    """Buffer<uint> / RWBuffer<uint2>: elements of `comps` u32s."""

    def __init__(self, n, comps=1, fill=0):
        self.a = [[fill] * comps for _ in range(n)]
        self.comps = comps

    def load(self, idx, wot):
        if idx >= len(self.a):
            return (0, 0, 0, 0, 0)
        e = self.a[idx]
        return tuple(e) + (0,) * (4 - len(e)) + (1,)

    def store(self, idx, wot, vals, mask):
        while idx >= len(self.a):
            self.a.append([0] * self.comps)
        for i in range(self.comps):
            if mask >> i & 1:
                self.a[idx][i] = vals[i] & M32


class CBuf:
    def __init__(self, data=b""):
        self.b = bytes(data)

    def row(self, r, as_float):
        o = r * 16
        raw = self.b[o:o + 16].ljust(16, b"\0")
        return struct.unpack("<4f" if as_float else "<4I", raw)


class Tex2D:
    """Float texture, HxW or HxWxC (numpy float32)."""

    def __init__(self, arr):
        a = np.asarray(arr, np.float32)
        self.a = a if a.ndim == 3 else a[:, :, None]

    def sample(self, u, v, lod, wrap):
        h, w, c = self.a.shape
        if not (math.isfinite(u) and math.isfinite(v)):
            return (0.0, 0.0, 0.0, 0.0, 1)
        x, y = u * w - 0.5, v * h - 0.5
        x0, y0 = math.floor(x), math.floor(y)
        fx, fy = x - x0, y - y0

        def at(i, j):
            if wrap:
                i, j = i % w, j % h
            else:
                i, j = min(max(i, 0), w - 1), min(max(j, 0), h - 1)
            return self.a[j, i]
        p = (at(x0, y0) * (1 - fx) + at(x0 + 1, y0) * fx) * (1 - fy) + \
            (at(x0, y0 + 1) * (1 - fx) + at(x0 + 1, y0 + 1) * fx) * fy
        out = [float(p[i]) if i < c else 0.0 for i in range(4)]
        return tuple(out) + (1,)


@dataclass
class Sampler:
    wrap: bool = False


# ---------------------------------------------------------------- IR parsing
@dataclass
class ResDecl:
    cls: int          # 0 SRV, 1 UAV, 2 CBV, 3 sampler
    rid: int
    name: str
    space: int
    lower: int


@dataclass
class Func:
    blocks: list = field(default_factory=list)   # [(label, [lines])]


TOK = re.compile(r'"[^"]*"|@"[^"]*"|\[|\]|<[^>]*>|[^\s,\[\]]+')
CLASS_OF = {"T": 0, "U": 1, "CB": 2, "S": 3}


def _const_float(t):
    if t.startswith("0x"):
        return struct.unpack("<d", int(t, 16).to_bytes(8, "little"))[0]
    return float(t)


class Transpiler:
    def __init__(self, text: str):
        self.text = text
        self.globals = {}       # name -> python id
        self.gdecl = {}         # python id -> (count or None, is_float)
        self.res = self._resources()
        self.func = self._function()
        self.threads = self._numthreads()

    # ---- metadata
    def _resources(self):
        out = []
        tab = False
        for line in self.text.splitlines():
            if line.startswith("; Resource Bindings"):
                tab = True
                continue
            if tab:
                if not line.startswith(";") or line.strip() == ";" and out:
                    if out:
                        break
                    continue
                m = re.match(r";\s+(\S+)\s+\S+\s+\S+\s+\S+\s+(T|U|CB|S)(\d+)\s+([a-z]+)(\d+)(?:,space(\d+))?", line)
                if m:
                    out.append(ResDecl(CLASS_OF[m.group(2)], int(m.group(3)), m.group(1),
                                       int(m.group(6) or 0), int(m.group(5))))
        return out

    def _numthreads(self):
        m = re.findall(r"!\{i32 (\d+), i32 (\d+), i32 (\d+)\}", self.text)
        return tuple(map(int, m[-1])) if m else (1, 1, 1)

    def _function(self):
        lines = self.text.splitlines()
        for line in lines:
            m = re.match(r'(@"[^"]*"|@[\w.$]+) = (?:external |internal )?addrspace\(3\) global (\[(\d+) x (\w+)\]|(\w+))', line)
            if m:
                gid = f"g{len(self.globals)}"
                self.globals[m.group(1)] = gid
                n = int(m.group(3)) if m.group(3) else None
                ty = m.group(4) or m.group(5)
                self.gdecl[gid] = (n, ty in ("float", "half", "double"))
        f = Func()
        inside = False
        cur = ("0", [])
        pending = ""
        for line in lines:
            if line.startswith("define "):
                inside = True
                continue
            if not inside:
                continue
            if line.startswith("}"):
                f.blocks.append(cur)
                break
            s = line.split(";")[0].rstrip() if not line.lstrip().startswith(";") else ""
            lab = re.match(r"; <label>:(\d+)", line.strip()) or re.match(r"^(\w[\w.]*):", line)
            if lab:
                f.blocks.append(cur)
                cur = (lab.group(1), [])
                continue
            if not s.strip():
                continue
            if pending:
                pending += " " + s.strip()
                if s.strip() == "]":
                    cur[1].append(pending)
                    pending = ""
                continue
            if s.strip().startswith("switch") and s.rstrip().endswith("["):
                pending = s.strip()
                continue
            cur[1].append(s.strip())
        f.blocks = [b for b in f.blocks if b[1] or b[0] != "0"] or f.blocks
        return f

    # ---- values
    def v(self, tok, ty="i32"):
        if tok.startswith("%"):
            return "v_" + re.sub(r"\W", "_", tok[1:])
        if tok.startswith("@"):
            return f"('{self.globals[tok]}',)"
        if tok == "undef" or tok == "zeroinitializer":
            return "0.0" if ty in ("float", "half", "double") else "0"
        if tok == "true":
            return "True"
        if tok == "false":
            return "False"
        if tok == "null":
            return "None"
        if ty in ("float", "half", "double"):
            return repr(_const_float(tok))
        if ty == "i1":
            return "True" if tok in ("1", "-1") else "False"
        n = int(tok)
        bits = int(ty[1:]) if ty.startswith("i") and ty[1:].isdigit() else 32
        return str(n & ((1 << bits) - 1))

    # ---- code generation
    def generate(self, name="kernel"):
        blocks = self.func.blocks
        ids = {lab: i for i, (lab, _) in enumerate(blocks)}
        phis = {}
        for lab, lines in blocks:
            for ln in lines:
                m = re.match(r"(%\S+) = phi (\S+) (.*)", ln)
                if m:
                    inc = re.findall(r"\[\s*([^,\]]+),\s*%([\w.]+)\s*\]", m.group(3))
                    phis.setdefault(lab, []).append((m.group(1), m.group(2), dict((p, val.strip()) for val, p in inc)))
        out = [f"def {name}(R, tid, gid, gtid, G):", "    if False:", "        yield", "    b = 0", "    while True:"]
        first = True
        for lab, lines in blocks:
            out.append(f"        {'if' if first else 'elif'} b == {ids[lab]}:  # {lab}")
            first = False
            body = []
            for ln in lines:
                body.extend(self.inst(ln, lab, ids, phis))
            out.extend("            " + x for x in (body or ["pass"]))
        out.append("        else:")
        out.append("            raise RuntimeError(b)")
        return "\n".join(out)

    def jump(self, src, dst, ids, phis):
        lines = []
        ph = phis.get(dst, [])
        if ph:
            names = ", ".join(self.v(d) for d, _, _ in ph)
            vals = ", ".join(self.v(inc.get(src, "undef"), ty) for _, ty, inc in ph)
            lines.append(f"{names}, = ({vals},)")
        lines.append(f"b = {ids[dst]}; continue")
        return lines

    def inst(self, ln, lab, ids, phis):
        v = self.v
        if ln.startswith("br "):
            m = re.match(r"br i1 (\S+), label %([\w.]+), label %([\w.]+)", ln)
            if m:
                c, t, f = m.groups()
                return [f"if {v(c, 'i1')}:"] + ["    " + x for x in self.jump(lab, t, ids, phis)] + \
                       ["else:"] + ["    " + x for x in self.jump(lab, f, ids, phis)]
            m = re.match(r"br label %([\w.]+)", ln)
            return self.jump(lab, m.group(1), ids, phis)
        if ln.startswith("switch "):
            m = re.match(r"switch (\S+) (\S+), label %([\w.]+) \[(.*)\]", ln)
            ty, x, dflt, cases = m.groups()
            cs = re.findall(r"\S+ (-?\d+), label %([\w.]+)", cases)
            out = [f"_s = {v(x, ty)}"]
            for k, (val, dst) in enumerate(cs):
                out.append(f"{'if' if k == 0 else 'elif'} _s == {int(val) & M32}:")
                out += ["    " + y for y in self.jump(lab, dst, ids, phis)]
            out.append("else:" if cs else "if True:")
            out += ["    " + y for y in self.jump(lab, dflt, ids, phis)]
            return out
        if ln.startswith("ret"):
            return ["return"]
        if ln.startswith("store "):
            m = re.match(r"store (\S+) (\S+), (.+?)\* (\S+?),? (?:align \d+.*)?$", ln + " ")
            ty, val, _, ptr = m.groups()
            vv = v(val, ty)
            if ty == "float":
                vv = f"rf({vv})"
            return [f"_p = {v(ptr)}", f"(G if len(_p) == 1 else _p[0])[_p[0] if len(_p) == 1 else _p[1]] = {vv}"]
        if ln.startswith("call void @dx.op.barrier"):
            return ["yield"]
        if ln.startswith("call void "):
            return [self.call(None, ln)]
        m = re.match(r"(%[\w.]+) = (.*)", ln)
        if not m:
            raise ValueError("cannot parse: " + ln)
        d, rhs = v(m.group(1)), m.group(2)
        op = rhs.split()[0]
        if op == "phi":
            return []
        if op == "call":
            return [self.call(d, ln)]
        toks = [t for t in TOK.findall(rhs) if t not in ("nuw", "nsw", "exact", "fast", "inbounds")]
        if op in ("add", "sub", "mul", "and", "or", "xor", "shl", "lshr", "ashr", "udiv", "urem", "sdiv", "srem"):
            ty, a, bb = toks[1], v(toks[2], toks[1]), v(toks[3], toks[1])
            mask = (1 << int(ty[1:])) - 1
            if ty == "i1":
                e = {"and": f"{a} and {bb}", "or": f"{a} or {bb}", "xor": f"{a} != {bb}",
                     "add": f"{a} != {bb}", "sub": f"{a} != {bb}", "mul": f"{a} and {bb}"}[op]
                return [f"{d} = bool({e})"]
            e = {
                "add": f"({a} + {bb}) & {mask}", "sub": f"({a} - {bb}) & {mask}", "mul": f"({a} * {bb}) & {mask}",
                "and": f"{a} & {bb}", "or": f"{a} | {bb}", "xor": f"{a} ^ {bb}",
                "shl": f"({a} << ({bb} & 31)) & {mask}", "lshr": f"{a} >> ({bb} & 31)",
                "ashr": f"(s32({a}) >> ({bb} & 31)) & {mask}",
                "udiv": f"({a} // {bb} if {bb} else {mask})", "urem": f"({a} % {bb} if {bb} else {mask})",
                "sdiv": f"(int(s32({a}) / s32({bb})) & {mask} if {bb} else {mask})",
                "srem": f"(int(math.fmod(s32({a}), s32({bb}))) & {mask} if {bb} else {mask})",
            }[op]
            return [f"{d} = {e}"]
        if op in ("fadd", "fsub", "fmul", "fdiv", "frem"):
            a, bb = v(toks[2], "float"), v(toks[3], "float")
            e = {"fadd": f"{a} + {bb}", "fsub": f"{a} - {bb}", "fmul": f"{a} * {bb}",
                 "fdiv": f"fdiv({a}, {bb})", "frem": f"(math.fmod({a}, {bb}) if {bb} else math.nan)"}[op]
            return [f"{d} = {e}"]
        if op == "icmp":
            cond, ty, a, bb = toks[1], toks[2], v(toks[3], toks[2]), v(toks[4], toks[2])
            if cond[0] == "s":
                a, bb = f"s32({a})", f"s32({bb})"
            o = {"eq": "==", "ne": "!=", "ugt": ">", "uge": ">=", "ult": "<", "ule": "<=",
                 "sgt": ">", "sge": ">=", "slt": "<", "sle": "<="}[cond]
            return [f"{d} = {a} {o} {bb}"]
        if op == "fcmp":
            cond, a, bb = toks[1], v(toks[3], "float"), v(toks[4], "float")
            if cond in ("true", "false"):
                return [f"{d} = {cond == 'true'}"]
            if cond == "ord":
                return [f"{d} = ({a} == {a}) and ({bb} == {bb})"]
            if cond == "uno":
                return [f"{d} = ({a} != {a}) or ({bb} != {bb})"]
            o = {"eq": "==", "ne": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}[cond[1:]]
            if cond[0] == "u":
                return [f"{d} = ({a} {o} {bb}) or ({a} != {a}) or ({bb} != {bb})"]
            return [f"{d} = {a} {o} {bb}"]
        if op == "select":
            # select i1 %c, T %a, T %b
            c, ty, a, ty2, bb = toks[2], toks[3], toks[4], toks[5], toks[6]
            return [f"{d} = {v(a, ty)} if {v(c, 'i1')} else {v(bb, ty2)}"]
        if op == "extractvalue":
            return [f"{d} = {v(toks[2])}[{toks[3]}]"]
        if op in ("bitcast", "zext", "sext", "trunc", "uitofp", "sitofp", "fptoui", "fptosi", "fpext", "fptrunc"):
            ty, x, ty2 = toks[1], toks[2], toks[4]
            xv = v(x, ty)
            if op == "bitcast":
                if ty == "i32" and ty2 == "float":
                    return [f"{d} = u2f({xv})"]
                if ty == "float" and ty2 == "i32":
                    return [f"{d} = f2u({xv})"]
                return [f"{d} = {xv}"]
            if op == "zext":
                return [f"{d} = int({xv})"]
            if op == "sext":
                bits = int(ty[1:])
                mask = (1 << int(ty2[1:])) - 1
                if ty == "i1":
                    return [f"{d} = {mask} if {xv} else 0"]
                return [f"{d} = (({xv} ^ {1 << (bits - 1)}) - {1 << (bits - 1)}) & {mask}"]
            if op == "trunc":
                if ty2 == "i1":
                    return [f"{d} = bool({xv} & 1)"]
                return [f"{d} = {xv} & {(1 << int(ty2[1:])) - 1}"]
            if op == "uitofp":
                return [f"{d} = float({xv})"]
            if op == "sitofp":
                return [f"{d} = float(s32({xv}))" if ty != "i1" else f"{d} = -1.0 if {xv} else 0.0"]
            if op == "fptoui":
                return [f"{d} = fptoui({xv})"]
            if op == "fptosi":
                return [f"{d} = fptosi({xv})"]
            return [f"{d} = {xv}"]
        if op == "alloca":
            n = int(re.search(r"\[(\d+) x", rhs).group(1))
            return [f"{d} = ([0.0] * {n},)"]
        if op == "getelementptr":
            m2 = re.search(r"\* (@\"[^\"]*\"|@[\w.$]+|%[\w.]+), i32 0, i32 (\S+)", rhs)
            base, idx = m2.groups()
            if base.startswith("@"):
                return [f"{d} = (G['{self.globals[base]}'], {v(idx)})"]
            return [f"{d} = ({v(base)}[0], {v(idx)})"]
        if op == "load":
            ptr = toks[-1] if not toks[-1].isdigit() else toks[-3]
            m2 = re.search(r"\* (@\"[^\"]*\"|@[\w.$]+|%[\w.]+)", rhs)
            p = v(m2.group(1))
            return [f"_p = {p}", f"{d} = G[_p[0]] if len(_p) == 1 else _p[0][_p[1]]"]
        if op == "atomicrmw":
            m2 = re.match(r"atomicrmw (\w+) \S+ addrspace\(3\)\* (\S+), \S+ (\S+)", rhs)
            aop, ptr, val = m2.groups()
            e = {"add": "(_o + _v) & 0xFFFFFFFF", "or": "_o | _v", "and": "_o & _v", "xor": "_o ^ _v",
                 "xchg": "_v", "umax": "max(_o, _v)", "umin": "min(_o, _v)",
                 "max": "max(s32(_o), s32(_v)) & 0xFFFFFFFF", "min": "min(s32(_o), s32(_v)) & 0xFFFFFFFF"}[aop]
            return [f"_p = {v(ptr)}", "_c = G if len(_p) == 1 else _p[0]", "_k = _p[0] if len(_p) == 1 else _p[1]",
                    f"_o = _c[_k]; _v = {v(val)}", f"_c[_k] = {e}", f"{d} = _o"]
        raise ValueError("unhandled: " + ln)

    def call(self, d, ln):
        m = re.search(r"@dx\.op\.(\w+)\.?(\w*)\((.*)\)\s*$", ln)
        if not m:
            raise ValueError("call: " + ln)
        kind, suffix, args = m.group(1), m.group(2), m.group(3)
        parts = []
        for a in re.split(r",\s*(?![^<]*>)", args):
            a = a.strip()
            ty, _, val = a.rpartition(" ")
            parts.append(self.v(val, ty.split()[-1] if ty else "i32"))
        opc = parts[0]
        rest = ", ".join(parts[1:])
        lhs = f"{d} = " if d else ""
        if kind == "unary":
            if suffix == "f64":
                return f"{lhs}abs({parts[1]})"
            return f"{lhs}R.UNARY[{opc}]({parts[1]})"
        if kind == "unaryBits":
            return f"{lhs}R.unary_bits({opc}, {parts[1]})"
        if kind == "binary":
            tab = "BINARY_F" if suffix == "f32" else "BINARY_I"
            return f"{lhs}R.{tab}[{opc}]({rest})"
        if kind == "tertiary":
            if opc == "46" or opc == "47":
                return f"{lhs}{parts[1]} * {parts[2]} + {parts[3]}"
            return f"{lhs}(({parts[1]} * {parts[2]} + {parts[3]}) & 0xFFFFFFFF)"
        if kind == "dot2":
            return f"{lhs}{parts[1]} * {parts[3]} + {parts[2]} * {parts[4]}"
        if kind == "dot3":
            return f"{lhs}{parts[1]} * {parts[4]} + {parts[2]} * {parts[5]} + {parts[3]} * {parts[6]}"
        if kind == "dot4":
            return f"{lhs}{parts[1]} * {parts[5]} + {parts[2]} * {parts[6]} + {parts[3]} * {parts[7]} + {parts[4]} * {parts[8]}"
        if kind == "threadId":
            return f"{lhs}tid[{parts[1]}]"
        if kind == "groupId":
            return f"{lhs}gid[{parts[1]}]"
        if kind == "threadIdInGroup":
            return f"{lhs}gtid[{parts[1]}]"
        if kind == "flattenedThreadIdInGroup":
            return f"{lhs}R.flat(gtid)"
        if kind == "legacyF16ToF32":
            return f"{lhs}f16_to_f32({parts[1]})"
        if kind == "legacyF32ToF16":
            return f"{lhs}f32_to_f16({parts[1]})"
        if kind in ("cbufferLoadLegacy", "bufferLoad", "rawBufferLoad"):
            return f"{lhs}R.{kind}_{suffix}({rest})"
        return f"{lhs}R.{kind}({rest})"


# ---------------------------------------------------------------- runtime
class Shader:
    def __init__(self, text: str, name="kernel"):
        self.tp = Transpiler(text)
        self.source = self.tp.generate(name)
        env = dict(math=math, rf=rf, s32=s32, u2f=u2f, f2u=f2u, fdiv=fdiv, fptoui=fptoui, fptosi=fptosi,
                   f16_to_f32=f16_to_f32, f32_to_f16=f32_to_f16)
        exec(compile(self.source, f"<dxil {name}>", "exec"), env)
        self.fn = env[name]
        self.bind = {}          # resource name -> object, or {register: object} for tables
        self.decl = {(r.cls, r.rid): r for r in self.tp.res}
        self.outputs = {}
        self.inputs = {}

    @classmethod
    def load(cls, path, name="kernel"):
        return cls(open(path, encoding="latin1").read(), name)

    # dx.op handlers --------------------------------------------------
    UNARY = UNARY
    BINARY_F = BINARY_F
    BINARY_I = BINARY_I

    def createHandle(self, cls, rid, idx, nonuniform):
        r = self.decl[(cls, rid)]
        obj = self.bind.get(r.name)
        if isinstance(obj, dict):
            obj = obj.get(idx - r.lower)
        if obj is None:
            raise KeyError(f"unbound resource {r.name}[{idx}]")
        return obj

    def cbufferLoadLegacy_i32(self, h, row):
        return h.row(row, False)

    def cbufferLoadLegacy_f32(self, h, row):
        return h.row(row, True)

    def bufferLoad_i32(self, h, idx, wot):
        return h.load(idx, wot)

    def bufferLoad_f32(self, h, idx, wot):
        r = h.load(idx, wot)
        return tuple(u2f(x) for x in r[:4]) + (r[4],)

    def bufferStore(self, h, c0, c1, a, b, c, d, mask):
        vals = [x if isinstance(x, int) else f2u(x) for x in (a, b, c, d)]
        h.store(c0, c1, vals, mask)

    def sample(self, tex, smp, u, v, w, z, o0, o1, o2, clamp):
        return tex.sample(u, v, 0.0, getattr(smp, "wrap", False))

    def sampleBias(self, tex, smp, u, v, w, z, o0, o1, o2, bias, clamp):
        return tex.sample(u, v, 0.0, getattr(smp, "wrap", False))

    def sampleLevel(self, tex, smp, u, v, w, z, o0, o1, o2, lod):
        return tex.sample(u, v, lod, getattr(smp, "wrap", False))

    def textureLoad(self, tex, lod, x, y, z, o0, o1, o2):
        h, w, c = tex.a.shape
        p = tex.a[min(max(y, 0), h - 1), min(max(x, 0), w - 1)]
        return tuple(float(p[i]) if i < c else 0.0 for i in range(4)) + (1,)

    def atomicBinOp(self, h, aop, o0, o1, o2, val):
        old = h.load(o0, o1)[0]
        new = [(old + val) & M32, old & val, old | val, old ^ val,
               min(s32(old), s32(val)) & M32, max(s32(old), s32(val)) & M32,
               min(old, val), max(old, val), val][aop]
        h.store(o0, o1, [new, 0, 0, 0], 1)
        return old

    def storeOutput(self, sig, row, col, val):
        self.outputs[(sig, row, col)] = val

    def loadInput(self, sig, row, col, vtx):
        return self.inputs.get((sig, row, col), 0)

    def unary_bits(self, op, x):
        x &= M32
        if op == 31:
            return bin(x).count("1")
        if op == 32:
            return (x & -x).bit_length() - 1 if x else M32
        if op == 33:
            return 31 - (x.bit_length() - 1) if x else M32
        if op == 30:
            return int(f"{x:032b}"[::-1], 2)
        raise NotImplementedError(op)

    def flat(self, gtid):
        x, y, z = self.tp.threads
        return gtid[0] + gtid[1] * x + gtid[2] * x * y

    # dispatch --------------------------------------------------------
    def _shared(self):
        g = {}
        for gid_, (n, isf) in self.tp.gdecl.items():
            g[gid_] = [0.0 if isf else 0] * n if n else (0.0 if isf else 0)
        return g

    def dispatch(self, groups=(1, 1, 1)):
        tx, ty, tz = self.tp.threads
        for gz in range(groups[2]):
            for gy in range(groups[1]):
                for gx in range(groups[0]):
                    G = self._shared()
                    gens = []
                    for z in range(tz):
                        for y in range(ty):
                            for x in range(tx):
                                tid = (gx * tx + x, gy * ty + y, gz * tz + z)
                                gens.append(self.fn(self, tid, (gx, gy, gz), (x, y, z), G))
                    alive = gens
                    while alive:
                        nxt = []
                        for g in alive:
                            try:
                                next(g)
                                nxt.append(g)
                            except StopIteration:
                                pass
                        alive = nxt

    def run_vertex(self, inputs):
        """One vertex: inputs {(sig,row,col): value} -> outputs {(sig,row,col): value}."""
        self.inputs, self.outputs = inputs, {}
        for _ in self.fn(self, (0, 0, 0), (0, 0, 0), (0, 0, 0), self._shared()):
            pass
        return self.outputs

