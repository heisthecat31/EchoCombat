## Contributing back to ReVault

You are a reconstruction agent contributing to the `echovr` project in ReVault,
a reverse-engineering warehouse. You have read-write MCP access. Read access
exists so you can find work; the point is to contribute reconstruction *back*.

### The one rule before anything

`revault_orientation(role="contributor")` is the **first call, every session**.
It names the database you are pointed at, the build, and the schema verdict. Do
not trust any tool result until you have oriented and confirmed the target.

### Scope

Work on the `echovr` project, primary binary `echovr.exe`. The Quest build
(`libr15.so`) carries full C++ symbol names and is your highest-value evidence
source — prefer it over RTTI and string guessing when naming classes, methods,
parameters, and template arguments.

### The loop

1. `revault_orientation(role="contributor")` — confirm target, load the contract.
2. `revault_binaries(project="echovr")` — list the corpus.
3. `revault_function(name_or_va, binary="echovr.exe")` — read the decompilation.
4. Reconstruct clean, compilable C++20 from evidence only. Never invent sizes,
   offsets, or field counts.
5. Persist **back** — do not stop at reading:
revault_rename(va="0x<va>", name="Class::Method", binary="echovr.exe") revault_comment(va="0x<va>", comment="<one-line purpose>", binary="echovr.exe") revault_tag(name_or_va="0x<va>", tag="reconstructed", action="add", binary="echovr.exe") revault_submit_reconstruction(va="0x<va>", binary="echovr.exe", source_code="<full C++>")


### Quality bar — zero violations, no exceptions

Before submitting, run the audit and reach **zero violations**:

```bash
python3 reconstruction-kit/tools/audit_reconstruction.py src/ --fail-on-violations
Code	Violation
V001	bare FUN_* reference (rename it, or wrap /* UNRESOLVED: FUN_xxx */)
V002	TODO comment (use /* UNRESOLVED: reason */)
V003	function missing // @0x<addr> annotation
V004	struct missing static_assert(sizeof(...))
V005	struct field missing static_assert(offsetof(...))
Every reconstruction carries // @0x<VA> and /* @confidence: H|M|L */. Check the skip-list (check-skip skill / docs/kb/thirdparty_libs.yaml) before reconstructing — third-party and runtime code is never reconstructed.

Naming propagates
Renaming one function improves decompilation for every caller. After submitting, re-fetch the callers and confirm your names landed; a FUN_* caller of a function you just named is now renameable too.
