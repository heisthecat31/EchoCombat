"""Private Combat matches: a second RULES page on the podium terminal (LOADOUTS).

The podium terminal script `d4653fc2065e8184` (mpl_arena_match_podium_manager, already
made to open RULES in Combat by fix_rules_terminal.py) has one rules page: four rows,
each a label (canvas text custom<N>a) and a value (custom<N>b) with -/+ buttons
(custom_rules_btn_left_<N> / _right_<N>). RULES turns into BACK while the page is open
(its MenuPage variable, data +1A8h, is 1); RESTART stays on the terminal.

This makes RESTART the page's NEXT button and adds page 2, all in the script:

* Page state lives in spare bytes past echovr.exe's .data (the RULES mailbox,
  fix_capture_points.py; see RULES_* below), so it is this machine's own:
  +10h u8 page (0 = page 1, 1 = page 2)   +11h u8 LOADOUTS (0 ALL 1 CLASSIC 2 NEW)
  +12h u8 requests (bumped per press)      +13h u8 the value asked for
  +18h u64 / +20h u32: the label pass below (item, set while it runs)
* RestartButtonPressed: while MenuPage is 1 it flips the page and ends there (its
  own end node, the one it takes on a dedicated server), so no restart is asked for.
  The RESTART label reads NEXT while MenuPage is 1, and the button is enabled then
  even before the match has started (its two enable checks read true). The button's own
  script puts "RESTART" back whenever it is enabled, so the row-1 refresh below also runs
  the RESTART label node while the rules page is open.
* Entering the rules page (the node that sets MenuPage = 1) starts on page 1.
* The row labels (custom<N>a) are never written: writing them made the canvas texts jump
  between rows. NEXT to page 2 runs HideMenuSettingsLabels with its value nodes skipped
  (the labels go, the values stay); NEXT back runs ShowMenuSettingsLabels. RULES / BACK
  start on page 1. The value nodes' text expressions give page 2's values while page 2 is
  shown: row 1 "LOADOUTS: ALL" / "CLASSIC" / "NEW", rows 2-4 empty.
* On page 2, the row buttons do nothing, except row 1's -/+: they ask for LOADOUTS
  to step back / on (ALL, CLASSIC, NEW; +13h the value, +12h += 1); VeilNet sends that to the server, which
  keeps the rule and tells every client.

On page 1 everything is as before (the page-1 labels are the canvas's own texts).

    python tools/fix_rules_pages.py --src <extract root> --out <stage dir> --mailbox <rules mailbox rva>
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_smoke import PE, rel32  # noqa: E402
from veil_fx import add_section  # noqa: E402
from le_symbol_names import symbol64  # noqa: E402

SCRIPTS = "6eace9f64204fd0"
TERMINAL_SCRIPT = "d4653fc2065e8184"
CANVAS_TYPE = "59a9bd6e4525ecc4"
RULES_CANVAS = "b655c5c7eaa080d7"

PAGE, CLASSIC, REQUESTS, WANT, OV_ITEM, OV_ROW = 0x10, 0x11, 0x12, 0x13, 0x18, 0x20
RATE_TEXT = 0x24                            # mailbox +24h: VeilNet's page-2 text table (a pointer; 0 = none)
#: PAUSE on the TEAM READY button (VeilNet keeps the rule; tools/fix_orb_pause.py the live flag)
PAUSED, LIVE = 0x2E, 0x2F
TEAM_READY_NODE = 0x1D5E0                   # execute_node_656dc962: TeamReady's first node
TEAM_READY_PROLOGUE = bytes.fromhex("4883ec5833d2")
TEAM_READY_END_FROM = 0x3D138079            # a TeamReady node whose exit is the function's end
#: expression e5264bb8 (TEAM READY disabled: own team ready, or a spectator): the own-team
#: test goes (xor edx, edx), so players keep the button: it is PAUSE / UNPAUSE once live
READY_DISABLE, READY_DISABLE_OLD, READY_DISABLE_NEW = 0x2FB39, bytes.fromhex("84d27518"), bytes.fromhex("31d29090")
#: ... and every call of DisableButton on middle_palm_btn_a (TEAM READY) calls EnableButton
#: instead (the function id each call node starts its thread at): the script disables it on
#: each team's ready event and in MenuPage0On / UpdateAll, so the button would stay grey once
#: the match is live, when it is PAUSE / UNPAUSE.
READY_DISABLE_CALLS = (0x25571, 0x11F81, 0x14A41, 0x19451, 0x1B201, 0x1F581)
DISABLE_BUTTON, ENABLE_BUTTON = 0xD7552910, 0x9252F6F0
#: 2026-11-05 (user): the button greys again as in stock once your team is ready, and stays grey
#: until VeilNet sets mailbox +35h ("PAUSE allowed": 1 s after the match went live): each of the six
#: calls is `mov eax, DisableButton` (5) + `mov [rcx+10h], rax` (4), now a jump to a cave that
#: picks EnableButton only while +35h is set. The own-team test (READY_DISABLE) is stock again.
PAUSE_OK = 0x35
#: When +35h is set VeilNet raises delegate_onlobbymemberalignmentchanged so the podium runs UpdateAll
#: (thread f93f24), whose DisableButton site above then picks EnableButton. That handler only runs
#: when the event's user is the local player (expression_22e43fe7_shouldexecute); the raised event
#: has no user, so the check returns true (UpdateAll only lays the podium's buttons out again).
ALIGN_CHECK, ALIGN_CHECK_OLD, ALIGN_CHECK_NEW = 0x35720, bytes.fromhex("4053"), bytes.fromhex("b001c3")
READY_CALL_OLD = b"\xb8" + struct.pack("<I", DISABLE_BUTTON) + bytes.fromhex("48894110")
ROW3_PRESSES = ("9dfc89dd", "8eae68db")     # custom_rules_btn_right_3, _left_3: POINT RATE up / down
MENU_PAGE = 0x1A8                       # the script's MenuPage (int): 1 = the rules page
PAGE2_LABELS = (b"LOADOUTS", b"", b"", b"")
CHASSIS = 0x2C                              # mailbox +2Ch: SERIES-10 ONLY shown (VeilNet)
ROW2_PRESSES = ("ec7326ac", "73d7f40b")     # custom_rules_btn_right_2, _left_2
#: PAYLOAD maps (VeilNet sets mailbox +30h from the server): RULES opens on page 2, which is
#: the only page there (NEXT keeps it); the page-1 labels never show (ShowMenuSettingsLabels'
#: label-alpha nodes custom1a..4a are skipped); row 3 is PAYLOAD SPEED (the POINT RATE asks,
#: VeilNet maps them) and row 4 CHECKPOINT USED (asked as 10h | 1 up / 10h down).
PAYLOAD = 0x30
SHOW_LABELS = (0x178C0, 0x135C0, 0x24020, 0x15390)   # custom1a..4a alpha 1 (4c8bdc534883ec60)
ROW4_PRESSES = ("26356df8", "ed70639c")     # custom_rules_btn_right_4, _left_4: CHECKPOINT USED
SECTION, SECTION_SIZE = b".rules\0\0", 0x3000   # the caves (.text has no room left)

#: stock pins
EXEC_TRUE = 0x56CCD1BD99A59D3B

#: (rva of execute_node_<id>, id): the four value nodes, row 1..4, with the text
#: expression each calls and its stock prologue (5 bytes: mov [rsp+8], rbx)
VALUE_NODES = ((0x1C570, 0x730E04B5, 0x32920), (0x1E500, 0x52BB2DF9, 0x334B0),
               (0x20100, 0x3E3987DB, 0x34040), (0x10050, 0xF72A6D8D, 0x2F2F0))
PROLOGUE_RBX = bytes.fromhex("48895c2408")
#: RestartButtonPressed's entry node: sub rsp, 4A8h (7 bytes)
RESTART_NODE, RESTART_PROLOGUE = 0x1A1C0, bytes.fromhex("4881eca8040000")
#: the node that sets MenuPage = 1 (whole body, 20 bytes)
MENU1_NODE = 0x209C0
MENU1_BODY = bytes.fromhex("488b01488b486833c0c781a801000001000000c3")
#: the press nodes of the row buttons (the event handler's OnFullyDepressed targets):
#: row 1's two first
ROW1_PRESSES = (0x1D030, 0x129D0)           # custom_rules_btn_left_1, _right_1
#: the other six: right_2, left_4, right_3, right_4, left_3, left_2
OTHER_PRESSES = ("ec7326ac", "ed70639c", "9dfc89dd", "26356df8", "8eae68db", "73d7f40b")
#: the RESTART label node (2e8a40ca): copies its text from .rdata 39408h ("RESTART") through
#: r8 = the image base; this site (xor ecx,ecx; mov [rsp+38h],rax; xor eax,eax; nop) is
#: just before that copy, rcx = the script's data
LABEL_SITE, LABEL_SITE_OLD = 0x21A66, bytes.fromhex("33c94889442438" "33c090")
RESTART_LABEL_NODE = 0x219D0                # execute_node_2e8a40ca (push rbx; sub rsp, 90h)
#: the node dispatcher (execute_node: mov rax,[rcx+10h]; mov edx, first compare) and next_node
#: (cmp rcx, imm32): both get the label steps, node ids LABEL_STEP + 0..4 (unused by the script)
DISPATCH, DISPATCH_FIRST = 0xBCC0, 0xC1933832
NEXT_NODE, NEXT_NODE_FIRST = 0x28B40, bytes.fromhex("4881f9d3e3c97e")
LABEL_STEP = 0x7AB10000
#: (node, its next): row 1 -> NEXT -> row 2. Writing the row labels (custom<N>a) as steps too
#: (LABEL_STEP + 0..3) made the canvas texts jump between rows in game (2026-11-04), so the
#: rows' labels are never written: page 2 hides them instead (below).
LABEL_CHAIN = ((0x730E04B5, LABEL_STEP + 4), (LABEL_STEP + 4, 0x52BB2DF9))
#: HideMenuSettingsLabels' four value-alpha nodes (custom1b..4b; 8 bytes: mov r11,rsp; push rbx;
#: sub rsp,60h): skipped while page 2 is shown, so it hides the labels only
VALUE_HIDES = (0x12EC0, 0x14500, 0x1B070, 0x16000)
VALUE_HIDE_PROLOGUE = bytes.fromhex("4c8bdc534883ec60")
#: nodes whose any-exit runs HideMenuSettingsLabels (f8953074 -> 33326b19) and
#: ShowMenuSettingsLabels (9a09fd90 -> 85a96e9): NEXT continues the thread from them
HIDE_FROM, SHOW_FROM = 0xF8953074, 0x9A09FD90
#: RulesButtonPressed's MenuPage check (ed920d86: sub rsp,58h; xor edx,edx), run on RULES and
#: BACK: the page goes back to 1 there (the node that sets MenuPage = 1 is inlined)
RULES_CHECK, RULES_CHECK_PROLOGUE = 0x11310, bytes.fromhex("4883ec5833d2")
RESTART_TEXT = 0x39408
#: RULES / BACK were slow: the page switch (mainmenutransition) and the row texts
#: (Show/HideMenuSettingsLabels) came only after every button's btn_on / btn_enable (or
#: btn_off / btn_disable) external call, one after another, and the old page's buttons stayed
#: pressable meanwhile. The press now takes, through next_node:
#:   BACK  (2563ebbc MenuPage = 0): mainmenutransition, menupage1_off, menupage0_on, sound
#:   RULES (3827adbc MenuPage = 1): mainmenutransition, menupage0_off, menupage1_on, sound
#: and while that press runs (mailbox +17h: 1 BACK, 2 RULES, set at RulesButtonPressed's
#: MenuPage check) menupage1_off hides the labels before its eight deactivations and
#: menupage1_on shows them before its nine activations. NEXT (HIDE_FROM / SHOW_FROM) keeps
#: the stock exits: there the flag is clear. (node, its next, flag needed or 0, clear the flag)
PRESS = 0x17
PRESS_BACK, PRESS_RULES = 1, 2
PRESS_ORDER = (
    (0x2563EBBC, 0xC40DACE1, 0, False),     # MenuPage = 0 -> mainmenutransition
    (0xC40DACE1, 0xF0737B8D, 0, False),     # -> menupage1_off
    (0xF0737B8D, 0xC53D90E6, 0, False),     # -> menupage0_on
    (0xC53D90E6, 0xB1FFA591, 0, False),     # -> playbuttonsoundback
    (0x3827ADBC, 0xC9F2FCB0, 0, False),     # MenuPage = 1 -> mainmenutransition
    (0xC9F2FCB0, 0x9F24019E, 0, False),     # -> menupage0_off
    (0x9F24019E, 0x5BD13660, 0, False),     # -> menupage1_on
    (0x5BD13660, 0x4E52934F, 0, False),     # -> playbuttonsoundforward
    (0xE484F3FA, 0x33326B19, PRESS_BACK, False),      # menupage1_off: hide the labels first
    (0x33326B19, 0xFC97430A, PRESS_BACK, False),      # ... then the eight deactivations
    (0x89E87D5C, 0x189E87D5C, PRESS_BACK, True),      # ... and the end
    (0xCC63CE6E, 0x085A96E9, PRESS_RULES, False),     # menupage1_on: show the labels first
    (0x085A96E9, 0x215EF69E, PRESS_RULES, False),     # ... then the nine activations
    (0x9A09FD90, 0x19A09FD90, PRESS_RULES, True))     # ... and the end
#: next_node: the ends of ChangeRulesButtonLabelToBack / ToRules go on to the RESTART label
#: node, and its end to its enable check (1af36a89: enable / disable start_button)
EXIT_EDITS = ((0x2B87E, 0x1814FE43E, 0x2E8A40CA), (0x2B0AD, 0x1723EA031, 0x2E8A40CA),
              (0x29D57, 0x12E8A40CA, 0x1AF36A89))
#: the two start_button enable checks, made true while MenuPage is 1:
#: 1af36a89 (sub rsp,28h; call its condition) and 37ae3a95 (sub rsp,58h; xor edx,edx)
ENABLE_CHECK, ENABLE_CHECK_COND = 0x23810, 0x35DF0
MATCH_CHECK, MATCH_CHECK_PROLOGUE = 0x209E0, bytes.fromhex("4883ec5833d2")

IMAGE_BASE = bytes.fromhex("6548a16000000000000000" "488b4010")   # rax = echovr.exe's base


def d32(v: int) -> bytes:
    return struct.pack("<i", v) if v < 0x80000000 else struct.pack("<I", v)


class Asm:
    """Straight-line x64 bytes with rel32 jumps / rip-relative leas to labels or rvas."""

    def __init__(self, at: int):
        self.at, self.b, self.labels, self.fix = at, bytearray(), {}, []

    def emit(self, hexs: str, *parts):
        self.b += bytes.fromhex(hexs.replace(" ", ""))
        for p in parts:
            self.b += p
        return self

    def label(self, name):
        self.labels[name] = self.at + len(self.b)

    def jmp(self, op: str, target):            # op: "e9", "e8", or "0f84" / "0f85" ...
        self.b += bytes.fromhex(op)
        self.fix.append((len(self.b), target))
        self.b += bytes(4)

    def rip(self, prefix: str, target):        # lea / mov with a [rip+disp32] operand last
        self.b += bytes.fromhex(prefix)
        self.fix.append((len(self.b), target))
        self.b += bytes(4)

    def resolve(self, extra: dict = None) -> bytes:
        names = dict(self.labels, **(extra or {}))
        for off, t in self.fix:
            to = names[t] if isinstance(t, str) else t
            struct.pack_into("<i", self.b, off, to - (self.at + off + 4))
        return bytes(self.b)


def menu_check(a: Asm, reg_thread: str, orig: str):
    """jne orig unless MenuPage == 1 (thread in rcx; rax clobbered)."""
    a.emit("488b01 488b4068")                                  # rax = [rcx]; rax = [rax+68h] (data)
    a.emit("83b8", d32(MENU_PAGE), b"\x01")                    # cmp dword [rax+MenuPage], 1
    a.jmp("0f85", orig)


def labels_from_canvas(canvas: bytes) -> list:
    """The page-1 row labels: canvas text slots 1, 3, 5, 7 (33 bytes each after MATCH RULES)."""
    base = canvas.find(b"MATCH RULES\x00")
    if base < 0:
        raise ValueError(f"{RULES_CANVAS}: no MATCH RULES text")
    return [canvas[base + k * 0x21: base + (k + 1) * 0x21].split(b"\x00")[0] for k in (1, 3, 5, 7)]


def patch(pe_bytes: bytes, mailbox: int, page1: list, presses: dict, labels: bool = True) -> tuple:
    pe = PE(pe_bytes)
    if pe.read(RESTART_NODE, 1) == b"\xe9":
        return pe_bytes, "already patched"
    # --- the build check ---------------------------------------------------------------
    for rva, _, _ in VALUE_NODES:
        if pe.read(rva, 5) != PROLOGUE_RBX:
            raise ValueError(f"{TERMINAL_SCRIPT}: unexpected value node at {rva:#x}: wrong build")
    if pe.read(RESTART_NODE, 7) != RESTART_PROLOGUE or pe.read(MENU1_NODE, 20) != MENU1_BODY:
        raise ValueError(f"{TERMINAL_SCRIPT}: unexpected RESTART / MenuPage node: wrong build")
    for rva in ROW1_PRESSES + tuple(presses.values()):
        if pe.read(rva, 5) != PROLOGUE_RBX:
            raise ValueError(f"{TERMINAL_SCRIPT}: unexpected press node at {rva:#x}: wrong build")
    if pe.read(LABEL_SITE, 10) != LABEL_SITE_OLD or pe.read(RESTART_TEXT, 8) != b"RESTART\x00" \
            or pe.read(RESTART_LABEL_NODE, 9) != bytes.fromhex("40534881ec90000000"):
        raise ValueError(f"{TERMINAL_SCRIPT}: unexpected RESTART label node: wrong build")
    if any(pe.read(rva, 8) != VALUE_HIDE_PROLOGUE for rva in VALUE_HIDES + SHOW_LABELS)             or pe.read(RULES_CHECK, 6) != RULES_CHECK_PROLOGUE:
        raise ValueError(f"{TERMINAL_SCRIPT}: unexpected label hide / RULES check nodes: wrong build")
    if pe.read(DISPATCH, 9) != bytes.fromhex("488b4110ba") + struct.pack("<I", DISPATCH_FIRST) \
            or pe.read(NEXT_NODE, 7) != NEXT_NODE_FIRST:
        raise ValueError(f"{TERMINAL_SCRIPT}: unexpected node dispatcher / next_node: wrong build")
    for site, old, _ in EXIT_EDITS:
        if pe.read(site, 11) != b"\x48\xb8" + struct.pack("<Q", old) + b"\xc3":
            raise ValueError(f"{TERMINAL_SCRIPT}: unexpected next_node exit at {site:#x}: wrong build")
    if pe.read(ENABLE_CHECK, 4) != bytes.fromhex("4883ec28") or pe.read(ENABLE_CHECK + 4, 1) != b"\xe8" \
            or pe.read(MATCH_CHECK, 6) != MATCH_CHECK_PROLOGUE:
        raise ValueError(f"{TERMINAL_SCRIPT}: unexpected start_button checks: wrong build")
    items, sources = [], []
    for row, (rva, _, expr) in enumerate(VALUE_NODES, 1):
        body = pe.read(rva, 0x200)
        item = struct.pack("<Q", int(symbol64(f"custom{row}b"), 16))
        k = body.find(b"\x48\xb8" + item)
        if k < 0 or body[k + 10:k + 15] != bytes.fromhex("4889442448"):
            raise ValueError(f"{TERMINAL_SCRIPT}: value node {rva:#x} has no custom{row}b item: wrong build")
        items.append(rva + k)
        e = pe.read(expr, 0x100)
        k = e.find(bytes.fromhex("4881c1"))
        if k < 0 or e[k + 7:k + 10] != bytes.fromhex("483bc1"):
            raise ValueError(f"{TERMINAL_SCRIPT}: text expression {expr:#x} has no string source: wrong build")
        sources.append((expr + k, struct.unpack_from("<I", e, k + 3)[0]))

    start = add_section(pe, SECTION, SECTION_SIZE)
    a = Asm(start)
    mb = mailbox
    jumps = []                                   # (site, length, label): the jumps into the caves

    # --- strings ------------------------------------------------------------------------
    strings = {}
    for row in range(4):
        strings[f"l1_{row}"] = page1[row]
        strings[f"l2_{row}"] = PAGE2_LABELS[row]
    # the value text is right-aligned: trailing spaces bring each one to the row's middle
    # (between the - and + buttons; about 10 characters left of the right edge, less half the text)
    strings.update(empty=b"", next=b"NEXT")
    for name, text in strings.items():
        a.label("s_" + name)
        a.emit(text.hex() + "00")

    # --- the text expressions: where each value string comes from -------------------------
    for row, (site, off) in enumerate(sources):
        L = f"x{row}_"
        a.emit("00" * ((-len(a.b)) % 16))
        a.label(L + "cave")
        a.emit("50")                                                    # push rax (its buffer)
        a.emit(IMAGE_BASE.hex())
        a.emit("83b8", d32(mb + OV_ROW), b"\x00")                       # label pass?
        a.jmp("0f84", L + "value")
        # Both podiums write these texts (CCanvasUICS::SetText into the canvas's text pool,
        # apparently shared by the two podiums' copies of the canvas): what they write follows
        # the page byte alone, never a podium's own MenuPage, or the two overwrite each other.
        a.emit("80b8", d32(mb + PAGE), b"\x01")                         # page 2?
        a.jmp("0f85", L + "p1")
        a.rip("488d0d", f"s_l2_{row}"); a.jmp("e9", L + "out")
        a.label(L + "p1")
        a.rip("488d0d", f"s_l1_{row}"); a.jmp("e9", L + "out")
        a.label(L + "value")
        a.emit("80b8", d32(mb + PAGE), b"\x01")
        a.jmp("0f85", L + "stock")
        if row < 4:
            # rows 1-4: VeilNet's texts (LOADOUTS, SERIES-10 ONLY, POINT RATE / PAYLOAD SPEED,
            # CHECKPOINT USED on payload maps), 48 bytes apart
            a.emit("488b88", d32(mb + RATE_TEXT))                       # rcx = the text table
            a.emit("4885c9")
            a.jmp("0f84", L + "none")
            if row:
                a.emit("4881c1", struct.pack("<I", row * 48))           # add rcx, row * 48 (imm32: row 4 is 144)
            a.jmp("e9", L + "out")
            a.label(L + "none")
        a.rip("488d0d", "s_empty")
        a.jmp("e9", L + "out")
        a.label(L + "stock")
        a.emit("4881c1", struct.pack("<I", off))                        # add rcx, the string variable
        a.label(L + "out")
        a.emit("58")                                                    # pop rax
        a.jmp("e9", site + 7)
        jumps.append((site, 7, L + "cave"))

    # --- the value nodes' item: the label pass's when set ------------------------------------
    for row, site in enumerate(items):
        L = f"i{row}_"
        item = pe.read(site + 2, 8)
        a.label(L + "cave")
        a.emit(IMAGE_BASE.hex())
        a.emit("488b80", d32(mb + OV_ITEM))                             # mov rax, [rax+item]
        a.emit("4885c0")
        a.jmp("0f85", L + "out")
        a.emit("48b8", item)                                            # mov rax, custom<N>b
        a.label(L + "out")
        a.jmp("e9", site + 10)
        jumps.append((site, 10, L + "cave"))

    # --- the label steps: nodes of their own in the refresh loop ------------------------------
    # Running a value node twice in one step (label, then value) mixed the texts up, so each
    # label is a step of its own: next_node puts LABEL_STEP + row after each value node, and
    # the dispatcher runs that value node's body for it with the label overrides set. Step 4,
    # after row 1's label, writes NEXT on RESTART while the rules page is open (the button's
    # own script puts "RESTART" back whenever it is enabled).
    a.label("x_orig")
    a.emit("ba", struct.pack("<I", DISPATCH_FIRST))                     # mov edx, (its first compare)
    a.jmp("e9", DISPATCH + 9)
    a.label("x_cave")
    a.emit("488b4110")                                                  # rax = current node
    for k in range(5):
        a.emit("483d", struct.pack("<I", LABEL_STEP + k))               # cmp rax, LABEL_STEP + k
        a.jmp("0f84", f"x_step{k}")
    a.jmp("e9", "x_orig")
    for row, (rva, _, _) in enumerate(VALUE_NODES):
        label_item = struct.pack("<Q", int(symbol64(f"custom{row + 1}a"), 16))
        a.label(f"x_step{row}")
        a.emit("53 4883ec20 4889cb")                                    # push rbx; sub rsp,20h; rbx = thread
        a.emit(IMAGE_BASE.hex())
        a.emit("48b9", label_item)                                      # mov rcx, custom<N>a
        a.emit("488988", d32(mb + OV_ITEM))
        a.emit("c780", d32(mb + OV_ROW), struct.pack("<I", 1))
        a.emit("4889d9")
        a.jmp("e8", rva)                                                # the value node's body
        a.emit("4889442410")                                            # keep its pin
        a.emit(IMAGE_BASE.hex())
        a.emit("48c780", d32(mb + OV_ITEM), bytes(4))
        a.emit("c780", d32(mb + OV_ROW), bytes(4))
        a.emit("488b442410 4883c420 5b c3")                             # its pin; pop rbx; ret
    a.label("x_step4")
    menu_check(a, "rcx", "x_none")
    a.jmp("e9", RESTART_LABEL_NODE)                                     # NEXT (rcx = thread)
    a.label("x_none")
    a.emit("31c0 c3")
    if labels:
        jumps.append((DISPATCH, 9, "x_cave"))
    # next_node: value node -> its label step -> the value node's own next
    a.label("n_orig")
    a.emit(NEXT_NODE_FIRST.hex()); a.jmp("e9", NEXT_NODE + 7)
    a.label("n_cave")
    for k, (frm, to) in enumerate(LABEL_CHAIN):
        a.emit("b8", struct.pack("<I", frm))                            # mov eax, from (zero-extended)
        a.emit("483bc8")                                                # cmp rcx, rax
        a.jmp("0f84", f"n_to{k}")
    # RULES / BACK: the page switch first, the slow button calls after (see PRESS_ORDER), from
    # a table of 16-byte rows {u32 node, u64 next, u8 flag needed, u8 clear it} ending in 0
    # (rcx = node, edx = pin kept; r8 / r9 / rax are free here)
    a.rip("4c8d05", "q_table")                                          # lea r8, [table]
    a.label("q_loop")
    a.emit("418b00 85c0")                                               # eax = row node; test
    a.jmp("0f84", "n_orig")                                             # end: as before
    a.emit("483bc8")                                                    # cmp rcx, rax
    a.emit("7409")                                                      # je +9: hit
    a.emit("4983c010")                                                  # add r8, 16
    a.jmp("e9", "q_loop")
    a.emit("410fb6400c 85c0")                                           # eax = flag needed; test
    a.emit("7429")                                                      # jz +41: take it
    a.emit("65 4c8b0c2560000000 4d8b4910")                              # r9 = echovr.exe
    a.emit("413881", d32(mb + PRESS))                                   # cmp [r9+press], al
    a.jmp("0f85", "n_orig")                                             # not this press: as before
    a.emit("4180780d00")                                                # cmp byte [r8+13], 0
    a.emit("7408")                                                      # je +8
    a.emit("41c681", d32(mb + PRESS), b"\x00")                          # clear the flag
    a.emit("498b4004 c3")                                               # rax = row next; ret
    a.emit("00" * ((-len(a.b)) % 8))
    a.label("q_table")
    for frm, to, flag, clear in PRESS_ORDER:
        a.emit("", struct.pack("<IQBBH", frm, to, flag, int(clear), 0))
    a.emit("", bytes(16))
    for k, (frm, to) in enumerate(LABEL_CHAIN):
        a.label(f"n_to{k}")
        a.emit("48b8", struct.pack("<Q", to)); a.emit("c3")
    if labels:
        jumps.append((NEXT_NODE, 7, "n_cave"))

    # --- RESTART on the rules page: NEXT -----------------------------------------------------
    a.label("r_orig")
    a.emit(RESTART_PROLOGUE.hex()); a.jmp("e9", RESTART_NODE + 7)
    a.label("r_cave")
    menu_check(a, "rcx", "r_orig")
    a.emit(IMAGE_BASE.hex())
    a.emit("80b8", d32(mb + PAYLOAD), b"\x00")                          # payload map: one page
    a.jmp("0f85", "r_hide")
    a.emit("80b0", d32(mb + PAGE), b"\x01")                             # xor byte [page], 1
    # the thread goes on to HideMenuSettingsLabels (now page 2: the labels only) or
    # ShowMenuSettingsLabels (now page 1), as if from the node before each
    a.emit("80b8", d32(mb + PAGE), b"\x01")
    a.jmp("0f85", "r_show")
    a.label("r_hide")
    a.emit("b8", struct.pack("<I", HIDE_FROM)); a.jmp("e9", "r_go")
    a.label("r_show")
    a.emit("b8", struct.pack("<I", SHOW_FROM))
    a.label("r_go")
    a.emit("48894110 31c0 c3")                                          # [thread+10h] = it; pin 0
    jumps.append((RESTART_NODE, 7, "r_cave"))

    # --- page 2 hides the row labels only: HideMenuSettingsLabels skips its value nodes ------
    for k, rva in enumerate(VALUE_HIDES):
        a.label(f"h{k}_orig")
        a.emit(VALUE_HIDE_PROLOGUE.hex()); a.jmp("e9", rva + 8)
        a.label(f"h{k}_cave")
        a.emit(IMAGE_BASE.hex())
        a.emit("80b8", d32(mb + PAGE), b"\x01")
        a.jmp("0f85", f"h{k}_orig")
        a.emit("31c0 c3")                                               # skipped: on to the next
        jumps.append((rva, 8, f"h{k}_cave"))

    # --- payload maps: ShowMenuSettingsLabels leaves the page-1 labels hidden ----------------
    for k, rva in enumerate(SHOW_LABELS):
        a.label(f"s{k}_orig")
        a.emit(VALUE_HIDE_PROLOGUE.hex()); a.jmp("e9", rva + 8)
        a.label(f"s{k}_cave")
        a.emit(IMAGE_BASE.hex())
        a.emit("80b8", d32(mb + PAYLOAD), b"\x00")
        a.jmp("0f84", f"s{k}_orig")
        a.emit("31c0 c3")                                               # payload: the label stays hidden
        jumps.append((rva, 8, f"s{k}_cave"))

    # --- RULES / BACK: page 1 ---------------------------------------------------------------
    a.label("b_orig")
    a.emit(RULES_CHECK_PROLOGUE.hex()); a.jmp("e9", RULES_CHECK + 6)
    a.label("b_cave")
    a.emit("488b01 488b4068 8b90", d32(MENU_PAGE))                      # edx = MenuPage (1: BACK)
    a.emit(IMAGE_BASE.hex())
    a.emit("448a80", d32(mb + PAYLOAD))                                 # RULES: page 1, or 2 on payload maps
    a.emit("448880", d32(mb + PAGE))
    a.emit("c680", d32(mb + PRESS), bytes([PRESS_RULES]))
    a.emit("83fa01")                                                    # cmp edx, 1
    a.jmp("0f85", "b_orig")
    a.emit("c680", d32(mb + PAGE), b"\x00")                             # BACK: page 1, so the values hide too
    a.emit("c680", d32(mb + PRESS), bytes([PRESS_BACK]))
    a.jmp("e9", "b_orig")
    jumps.append((RULES_CHECK, 6, "b_cave"))

    # --- MenuPage = 1: start on page 1 ------------------------------------------------------
    a.label("m_cave")
    a.emit(MENU1_BODY[:-1].hex())                                       # MenuPage = 1 (eax = 0)
    a.emit(IMAGE_BASE.hex())
    a.emit("8a90", d32(mb + PAYLOAD))                                   # page 1 (2 on payload maps)
    a.emit("8890", d32(mb + PAGE))
    a.emit("31c0 c3")
    jumps.append((MENU1_NODE, 5, "m_cave"))

    # --- the row buttons on page 2 ----------------------------------------------------------
    all_presses = [(rva, 1) for rva in ROW1_PRESSES] + \
        [(rva, 2 if pid in ROW2_PRESSES else 3 if pid in ROW3_PRESSES else 4 if pid in ROW4_PRESSES else 0)
         for pid, rva in presses.items()]
    pid_of = {rva: pid for pid, rva in presses.items()}
    for k, (rva, row) in enumerate(all_presses):
        row1 = row == 1
        L = f"p{k}_"
        a.label(L + "orig")
        a.emit(PROLOGUE_RBX.hex()); a.jmp("e9", rva + 5)
        a.label(L + "cave")
        menu_check(a, "rcx", L + "orig")
        a.emit(IMAGE_BASE.hex())
        a.emit("80b8", d32(mb + PAGE), b"\x01")
        a.jmp("0f85", L + "orig")
        if row1:
            # left (k 0) steps back, right on: ALL -> CLASSIC -> NEW -> ALL
            a.emit("8a90", d32(mb + CLASSIC))                           # dl = shown (0, 1, 2)
            a.emit("80c2", bytes([2 if k == 0 else 1]))                 # add dl, 2 (-1 mod 3) / 1
            a.emit("80fa03")                                            # cmp dl, 3
            a.emit("7203")                                              # jb: in range
            a.emit("80ea03")                                            # sub dl, 3
            a.emit("8890", d32(mb + WANT))                           # the value asked for
            a.emit("fe80", d32(mb + REQUESTS))                          # one more request
        if row == 3:
            # POINT RATE: asked as 40h | 1 (right: up) or 40h (left: down)
            a.emit("c680", d32(mb + WANT), bytes([0x41 if ROW3_PRESSES.index(pid_of[rva]) == 0 else 0x40]))
            a.emit("fe80", d32(mb + REQUESTS))
        if row == 4:
            # CHECKPOINT USED (payload maps; VeilNet ignores it elsewhere): 10h | 1 up, 10h down
            a.emit("c680", d32(mb + WANT), bytes([0x11 if ROW4_PRESSES.index(pid_of[rva]) == 0 else 0x10]))
            a.emit("fe80", d32(mb + REQUESTS))
        if row == 2:
            # SERIES-10 ONLY: either button flips it (asked as 80h | the new value)
            a.emit("8a90", d32(mb + CHASSIS))                           # dl = shown
            a.emit("80f201 80ca80")                                     # xor dl, 1; or dl, 80h
            a.emit("8890", d32(mb + WANT))
            a.emit("fe80", d32(mb + REQUESTS))
        a.emit("31c0 c3")                                               # done (its end node)
        jumps.append((rva, 5, L + "cave"))

    # --- TEAM READY while the match is live: PAUSE / UNPAUSE ---------------------------------
    a.label("y_orig")
    a.emit(TEAM_READY_PROLOGUE.hex()); a.jmp("e9", TEAM_READY_NODE + 6)
    a.label("y_cave")
    a.emit(IMAGE_BASE.hex())
    a.emit("80b8", d32(mb + LIVE), bytes(1))                            # match live?
    a.jmp("0f84", "y_orig")                                             # no: TEAM READY as before
    a.emit("8a90", d32(mb + PAUSED))                                    # dl = paused
    a.emit("80f201 80ca20")                                             # xor dl, 1; or dl, 20h
    a.emit("8890", d32(mb + WANT))
    a.emit("fe80", d32(mb + REQUESTS))                                  # VeilNet asks the server
    a.emit("b8", struct.pack("<I", TEAM_READY_END_FROM))
    a.emit("48894110 31c0 c3")                                          # on to TeamReady's end
    jumps.append((TEAM_READY_NODE, 6, "y_cave"))

    # --- TEAM READY's grey: DisableButton until VeilNet allows PAUSE (+35h) ----------------------
    for k, imm in enumerate(READY_DISABLE_CALLS):
        a.label(f"r{k}_cave")
        a.emit(IMAGE_BASE.hex())                                        # rax = echovr.exe's base
        a.emit("80b8", d32(mb + PAUSE_OK), bytes(1))                    # cmp byte [PAUSE allowed], 0
        a.emit("b8", struct.pack("<I", DISABLE_BUTTON))                 # mov eax, DisableButton
        a.emit("7405")                                                  # je +5
        a.emit("b8", struct.pack("<I", ENABLE_BUTTON))                  # mov eax, EnableButton
        a.emit("48894110")                                              # mov [rcx+10h], rax
        a.jmp("e9", imm - 1 + 9)

    # --- the RESTART label: NEXT while MenuPage is 1 ---------------------------------------
    a.label("t_cave")
    a.emit("4889442438")                                                # mov [rsp+38h], rax
    a.emit("83b9", d32(MENU_PAGE), b"\x01")
    a.jmp("0f85", "t_out")
    # r8 = base + (NEXT - RESTART_TEXT): the copy reads [rax + r8 + 39408h]
    a.rip("4c8d05", "t_next_base")
    a.label("t_out")
    a.emit("31c9 31c0")
    a.jmp("e9", LABEL_SITE + 10)
    jumps.append((LABEL_SITE, 10, "t_cave"))

    # --- the start_button enable checks: true while MenuPage is 1 ---------------------------
    a.label("e_orig")
    a.emit("4883ec28"); a.jmp("e8", ENABLE_CHECK_COND); a.jmp("e9", ENABLE_CHECK + 9)
    a.label("e_cave")
    menu_check(a, "rcx", "e_orig")
    a.emit("48b8", struct.pack("<Q", EXEC_TRUE)); a.emit("c3")
    jumps.append((ENABLE_CHECK, 9, "e_cave"))
    a.label("g_orig")
    a.emit(MATCH_CHECK_PROLOGUE.hex()); a.jmp("e9", MATCH_CHECK + 6)
    a.label("g_cave")
    menu_check(a, "rcx", "g_orig")
    a.emit("48b8", struct.pack("<Q", EXEC_TRUE)); a.emit("c3")
    jumps.append((MATCH_CHECK, 6, "g_cave"))

    code = a.resolve({"t_next_base": a.labels["s_next"] - RESTART_TEXT})
    assert len(code) <= SECTION_SIZE
    pe.write(start, code)
    for site, n, name in jumps:
        pe.write(site, b"\xe9" + rel32(site + 5, a.labels[name]) + b"\x90" * (n - 5))
    if pe.read(READY_DISABLE, 4) == READY_DISABLE_NEW:              # (an older build's own-team skip)
        pe.write(READY_DISABLE, READY_DISABLE_OLD)
    for k, imm in enumerate(READY_DISABLE_CALLS):
        site = imm - 1
        if pe.read(site, 9) == READY_CALL_OLD:
            pe.write(site, b"\xe9" + rel32(site + 5, a.labels[f"r{k}_cave"]) + b"\x90" * 4)
    for site, _, new in EXIT_EDITS:
        pe.write(site + 2, struct.pack("<Q", new))
    if pe.read(ALIGN_CHECK, 2) != ALIGN_CHECK_OLD:
        raise ValueError(f"{TERMINAL_SCRIPT}: unexpected alignment check at {ALIGN_CHECK:#x}: wrong build")
    pe.write(ALIGN_CHECK, ALIGN_CHECK_NEW)
    return bytes(pe.d), (f"page 2 (LOADOUTS) behind RESTART = NEXT on the rules page; "
                         f"page state at mailbox+{PAGE:#x} ({len(code)} bytes of code)")


def pdb_nodes(asset: bytes, ids) -> dict:
    """execute_node_<id> rvas from the container's PDB (its public symbols), by name."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    i = asset.find(b"Microsoft C/C++ MSF 7.00")
    if i < 0:
        raise ValueError(f"{TERMINAL_SCRIPT}: no PDB in the container")
    pdb = asset[i:]
    bs, _, _, dirsize, _, dirmap = struct.unpack_from("<IIIIII", pdb, 32)
    nd = (dirsize + bs - 1) // bs
    dblocks = struct.unpack_from(f"<{nd}I", pdb, dirmap * bs)
    d = b"".join(pdb[b * bs:(b + 1) * bs] for b in dblocks)[:dirsize]
    n = struct.unpack_from("<I", d, 0)[0]
    sizes = struct.unpack_from(f"<{n}I", d, 4)
    at, streams = 4 + 4 * n, []
    for s in sizes:
        if s == 0xFFFFFFFF:
            streams.append(b"")
            continue
        k = (s + bs - 1) // bs
        bl = struct.unpack_from(f"<{k}I", d, at)
        at += 4 * k
        streams.append(b"".join(pdb[b * bs:(b + 1) * bs] for b in bl)[:s])
    dbi = streams[3]
    pe = PE(asset[asset.find(b"MZ"):i])
    text_va = pe.section(b".text")[3]
    want = {f"execute_node_{x}": x for x in ids}
    out = {}

    def walk(data: bytes, o: int):
        while o + 4 <= len(data):
            ln, kind = struct.unpack_from("<HH", data, o)
            if ln < 2:
                break
            rec = data[o + 4:o + 2 + ln]
            if kind == 0x110E:                                         # S_PUB32
                _, off, seg = struct.unpack_from("<IIH", rec, 0)
                name = rec[10:]
            elif kind in (0x110F, 0x1110):                             # S_LPROC32 / S_GPROC32
                off, seg = struct.unpack_from("<IH", rec, 28)
                name = rec[35:]
            else:
                o += 2 + ln
                continue
            name = name.split(b"\x00")[0].decode("latin1")
            if name in want and seg == 1:
                out[want[name]] = text_va + off
            o += 2 + ln

    walk(streams[struct.unpack_from("<H", dbi, 20)[0]], 0)            # the public symbols
    m, end = 64, 64 + struct.unpack_from("<i", dbi, 24)[0]           # the modules' own procedures
    while m < end:
        stream, size = struct.unpack_from("<HI", dbi, m + 34)
        n1 = dbi.index(b"\x00", m + 64)
        n2 = dbi.index(b"\x00", n1 + 1)
        if stream != 0xFFFF and stream < len(streams):
            walk(streams[stream][:size], 4)
        m = (n2 + 1 + 3) & ~3
    missing = set(ids) - set(out)
    if missing:
        raise ValueError(f"{TERMINAL_SCRIPT}: PDB has no execute_node for {sorted(missing)}")
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help=f"dir with {SCRIPTS}/<script>")
    ap.add_argument("--out", required=True, help="stage directory")
    ap.add_argument("--mailbox", required=True, type=lambda v: int(v, 0),
                    help="rva of the RULES mailbox in echovr.exe (fix_capture_points.py's)")
    args = ap.parse_args(argv)

    def staged_or_src(t, name):
        staged = os.path.join(args.out, t, name)
        return staged, staged if os.path.exists(staged) else os.path.join(args.src, t, name)

    _, canvas_path = staged_or_src(CANVAS_TYPE, RULES_CANVAS)
    staged, path = staged_or_src(SCRIPTS, TERMINAL_SCRIPT)
    asset = open(path, "rb").read()
    try:
        page1 = labels_from_canvas(open(canvas_path, "rb").read())
        # the PDB sits after the DLL; read it from the stock container (a staged one keeps it too)
        presses = pdb_nodes(asset, OTHER_PRESSES)
        mz = asset.find(b"MZ")
        pe, what = patch(asset[mz:], args.mailbox, page1, presses)
    except ValueError as e:
        sys.exit(str(e))
    os.makedirs(os.path.dirname(staged), exist_ok=True)
    open(staged, "wb").write(asset[:mz] + pe)
    print(f"{TERMINAL_SCRIPT}: {what}; page 1 labels {[t.decode() for t in page1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
