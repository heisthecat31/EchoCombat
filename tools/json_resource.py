r"""Read and rebuild `CJsonResourceWin10` blobs.

An Echo VR JSON resource is a 544-byte header followed by the raw, minified
JSON bytes -- no compression, no terminator:

    0x000  u64   always 0
    0x008  u64   length of the JSON body in bytes
    0x010  u64   always 0
    0x018  u64   always 0
    0x020  char[512]  NUL-padded source path, e.g. `rad15\json\balance\mp_equipment.json`
    0x220  u8[]  the JSON body

The asset's own filename is `CSymbol64(<source filename stem>)`, so
`mp_equipment.json` is stored as `f8d40525c88885d8`.  That is verified for all
21 JSON resources in the PC extract by `--verify`.

    python tools/json_resource.py dump  <resource>            > out.json
    python tools/json_resource.py path  <resource>
    python tools/json_resource.py build <in.json> <resource>  # keeps the header
    python tools/json_resource.py verify <extract_dir>
"""

from __future__ import annotations

import json
import os
import struct
import sys

HEADER_SIZE = 0x220
PATH_OFFSET = 0x20
PATH_SIZE = 0x200

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:                       # le_symbol_names.py sits next to this file
    sys.path.insert(0, _HERE)


class JsonResourceError(ValueError):
    """The blob does not parse as a `CJsonResourceWin10`."""


def read(blob: bytes) -> tuple[str, bytes]:
    """`(source_path, json_bytes)`."""
    if len(blob) < HEADER_SIZE:
        raise JsonResourceError(f"too short: {len(blob)} < {HEADER_SIZE}")
    declared = struct.unpack_from("<Q", blob, 8)[0]
    body = blob[HEADER_SIZE:]
    if declared != len(body):
        raise JsonResourceError(
            f"header says {declared} body bytes, file has {len(body)}")
    path = blob[PATH_OFFSET:PATH_OFFSET + PATH_SIZE].split(b"\x00")[0]
    return path.decode("ascii", "replace"), body


def build(source_path: str, body: bytes) -> bytes:
    """Assemble a resource blob from a source path and minified JSON bytes."""
    encoded = source_path.encode("ascii")
    if len(encoded) >= PATH_SIZE:
        raise JsonResourceError(f"source path too long: {len(encoded)}")
    out = bytearray(HEADER_SIZE)
    struct.pack_into("<Q", out, 8, len(body))
    out[PATH_OFFSET:PATH_OFFSET + len(encoded)] = encoded
    return bytes(out) + body


def minify(obj) -> bytes:
    """Encode exactly the way the shipped resources are encoded."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify(extract_dir: str) -> int:
    from le_symbol_names import symbol64
    bad = 0
    for name in sorted(os.listdir(extract_dir)):
        # Only files whose name IS the CSymbol64 are resources; skip backups
        # and anything else a working directory has collected.
        if not (1 <= len(name) <= 16 and all(c in "0123456789abcdef" for c in name)):
            continue
        blob = open(os.path.join(extract_dir, name), "rb").read()
        try:
            path, body = read(blob)
        except JsonResourceError as exc:
            print(f"  {name}  HEADER FAIL: {exc}")
            bad += 1
            continue
        stem = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0]
        name_ok = symbol64(stem) == name.rjust(16, "0")
        obj = json.loads(body.decode("utf-8"))
        rebuilt = minify(obj)
        rebuild_ok = build(path, body) == blob
        # Two levels of round-trip.  Byte-exact is what 19 of the 21 shipped
        # resources achieve.  The other two only differ by a redundant trailing
        # zero in a float literal (`"time":0.20` re-encodes as `0.2`), so they
        # are still safe to edit and rebuild -- the parsed values are equal.
        exact = rebuilt == body
        equal = json.loads(rebuilt.decode("utf-8")) == obj
        if not (name_ok and rebuild_ok and equal):
            bad += 1
            print(f"  {name}  FAIL  name={name_ok} value_equal={equal} "
                  f"rebuild={rebuild_ok}  {stem}")
        elif exact:
            print(f"  {name}  ok         {stem}")
        else:
            print(f"  {name}  ok (fmt)   {stem}  "
                  f"[{len(body)}->{len(rebuilt)} B, float literals only]")
    return bad


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, target = argv[1], argv[2]
    if cmd == "verify":
        bad = _verify(target)
        print(f"\n{'all resources verified' if not bad else str(bad) + ' FAILED'}")
        return 1 if bad else 0
    if cmd == "dump":
        _path, body = read(open(target, "rb").read())
        sys.stdout.write(json.dumps(json.loads(body.decode("utf-8")), indent=1))
        return 0
    if cmd == "path":
        print(read(open(target, "rb").read())[0])
        return 0
    if cmd == "build":
        if len(argv) < 4:
            print("build needs <in.json> <resource>")
            return 2
        resource = argv[3]
        source_path, _old = read(open(resource, "rb").read())
        obj = json.load(open(target, "r", encoding="utf-8"))
        open(resource, "wb").write(build(source_path, minify(obj)))
        print(f"wrote {resource}  ({source_path})")
        return 0
    print(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
