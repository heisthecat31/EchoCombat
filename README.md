# Echo Combat — DOT field

## What is actually wrong

The DOT field is not corrupted. It is **unfinished content that was never
registered as gear**, which is why it half-exists: it spawns, but nothing that
resolves it *by name* works.

Echo Combat keeps gear in two JSON resources that have to agree:

| resource | CSymbol64 | role |
|---|---|---|
| `rad15\json\balance\mp_equipment.json` | `f8d40525c88885d8` | **registry** — `gear_table.{weapons,ordnances,tacmods}` |
| `rad15\json\balance\mp_weapon_settings.json` | `11a8523ed4724ca7` | **tuning** — `weapon_properties`, `grenade_properties`, `ability_properties`, `damage_table` |

`CR15NetProfileSymbolLookup::InitializeForEquipment` walks the registry to build
`gWeaponNameLookup` / `gOrdnanceNameLookup` / `gTacModNameLookup`. Those three
globals are the "hash lookup" for gear. **An item missing from `gear_table` has
no symbol at all.** The engine's own failure strings for that path:

```
CR15NetProfileSymbolLookup doesn't recognize '%s'
INVALID ORDNANCE TYPE
Ordnance node id was not found
```

Run `python tools/audit_gear.py` and the split is exact:

```
ordnances  registered: det, stun, arc, burst          (4)
           tuned     : det, arc, stun, dot, burst, drone  (6)
           unregistered: dot, drone
```

`dot` and `drone` are the only two ordnances with tuning and no registry entry,
and they are the two that misbehave in game. Same pattern elsewhere: 8 weapons
tuned / 4 registered, 7 tacmods tuned / 4 registered. The shipped game was
4 / 4 / 4.

### Why the symptoms look the way they do

* **can't be picked up again** — `CR15NetMagazinePouchCS` reads exactly one
  per-ordnance property, and it builds the key at runtime from the format
  string `grenade_properties|%s|cooldown`. With `%s` unresolved the lookup
  misses, and `grenade_properties.dot` has no `cooldown` key anyway. Every
  registered ordnance has one — `det` has *nothing else*.
* **latches the instant it is grabbed, can't be triggered** —
  `grenade_properties.dot` sets `activate_on_collision: true` **and**
  `use_remote_trigger: true`. Those contradict: if first contact activates the
  field, the manual-trigger path is never reachable. Intended flow is stick
  (`stick_to_geo`), wait, then trigger.
* **does no damage** — `damage_per_tick` is scaled through `damage_table`, and
  there is no `damage_table.dot` entry.

The `r15_ord_dot` entry in `hash_lookup.json` (`0xd5ebbf55f4b0e0b6`) is
**correct** — it re-hashes cleanly under CSymbol64, as do all seven
`r15_ord_*` names. That was not the problem.

## The fix

`combatGunPatchFiles` already registers DOT (and `loc`, and the four unreleased
weapons) in `gear_table`, which is why it appears in the terminal and spawns.
What it does not do is give DOT working tuning. Those three edits are what is
left:

1. `grenade_properties.dot.cooldown` -- absent. The only grenade property the
   executable reads per ordnance.
2. `grenade_properties.dot.activate_on_collision` -- must be `false`; it
   contradicts `use_remote_trigger`.
3. `damage_table.dot` -- absent, so `damage_per_tick` scales by nothing. The
   gun patch added `magnum`/`smg`/`chain`/`rifle` here but not `dot`.

**Always rebase, never overwrite.** The gear patch and this fix touch the same
two resources. Point `--base` at the patch tree and its changes carry through
untouched:

```bash
python tools/fix_dot.py --base <combatGunPatchFiles> --deploy
```

If `--base` is omitted the pristine extract is used instead, and the DOT
registry entry is added too (useful only without the gun patch).

### Deploying

`--deploy` stages the rebuilt blobs where `evrfiletools.exe` picks them up, laid out the
way that tool expects -- the same `<resource_type_hash>/<asset_hash>` nesting as
the flat extract, **not** flat hash names at the top level:

```
Settings/input-pcvr/607d858c90268f9a/f8d40525c88885d8   (mp_equipment)
Settings/input-pcvr/607d858c90268f9a/11a8523ed4724ca7   (mp_weapon_settings)
```

Every other resource type folder in the base tree is copied across verbatim, so
the gun patch's `CR15NetGunCRWin10` (`dbaed509c67b8884`, the bullet trails for
the four unreleased weapons) ships alongside the merged JSON in one staging
pass. `607d858c90268f9a` is `CSymbol64("CJsonResourceWin10")`. The staging folder is
read from evrfiletools' own `Settings/config.json` (`pcvr_input_folder`) rather
than hard-coded. Run evrfiletools afterwards to build the package and manifest
-- `--deploy` only stages the files.

There is a second, lighter route worth knowing about: this install has a live
`sourcedb
ad15\json\` tree of loose JSON that overrides compiled resources
(`equip_slots.json` and `customization_models.json` sit there loose while also
existing as compiled resources). Dropping the patched files at
`sourcedb
ad15\jsonalance\` -- the path each resource carries in its own
header -- would skip repacking entirely. Untested here.

### Not verified in game

These are static-analysis findings from the binary's strings and the shipped
data; nothing here has been playtested. `cooldown = 30.0` and the
`damage_table.dot` multipliers are starting values chosen to sit with the
shipped spread (arc 25, burst 30, det 35, stun 35) — expect to tune them.
`barrier: 1.0` lets the field chew through an Energy Barrier at face value; set
it to `0.0` if barriers should stop it outright.

Whether clearing `activate_on_collision` also stops the *premature latch* on
grab depends on whether sticking is gated behind activation, which is inside
`CR15NetGrenadeCS` and not visible in the data. If it still latches on grab,
that part is component data on the ordnance prefab, not JSON.

`drone` is deliberately not fixed. `--drone` adds its registry and damage
entries, which is necessary but not sufficient — it also drives a firing actor
(`bullet_speed`, `fire_rate`, `max_target_distance`) with no pooled bullet actor
registered for it.

## Where the behaviour actually lives

**`StreamingScriptWin10` resources are separately compiled C++ DLLs**, one per
gameplay script -- not node-graph blobs. Each asset is a 20-byte resource header
followed by a complete PE image, built by `cl.exe` against
`sourcedb/engine/core/scripts2/includes` (`radactor.h`, `radassetelement.h`,
`radmath.h`, ...), named after its own resource hash, and exporting exactly one
symbol: `setup_bindings`. The leftover build paths are still in them:

```
d:/projects2/rad/dev/_data/5932408047/rad15/win10/multi/script_compile/1/intermediate/<hash>.obj
```

The asset hash is `CSymbol64(<script name>)`, which is how these were recovered
(`python tools/crack_scripts.py`). One DLL per ordnance:

| gear | script | asset |
|---|---|---|
| arc | `mp_combat_grenade_arc` | `97d0806e6ead8c27` |
| stun | `mp_combat_grenade_stun` | `190ed14ff6dc4ad8` |
| **dot** | **`mp_combat_grenade_dot`** | **`97d0806e6ea89130`** |
| burst | `mp_combat_grenade_burst` | `cad33e1bc81ffbee` |
| loc | `mp_combat_grenade_translocator` | `9398a165c004a9c0` |
| drone | `mp_combat_ordnance_drone` | `221a0a3a2e56d247` |
| shield | `mp_combat_ability_barrier` | `b87ba2039b049d5e` |
| sensor | `mp_combat_ability_sensor` | `0e1975416e8dcf7a` |
| wraith | `mp_combat_ability_wraith` | `0e1971566197d460` |

`det` has no script -- consistent with `grenade_properties.det` carrying nothing
but `cooldown`. The detonator is native.

### These scripts read the balance JSON themselves

This is why `echovr.exe` only ever mentions `grenade_properties|%s|cooldown`:
every *other* tuning key is read by the ordnance's own DLL, as
`CSymbol64("grenade_properties|<ord>|<key>")`. Confirmed by finding those hashes
inside each DLL:

```
dot    radius READ  lifetime READ  ticks_per_second READ  damage_per_tick READ
       activate_on_collision READ  use_occlusion READ  use_remote_trigger READ
       stick_to_geo READ           cooldown --
stun   all 10 keys READ
arc    9 of 12 READ (chain_delay, chain_radius, base_activate_speed unused)
burst  4 of 5 READ (remove_stun unused)
drone  all 6 READ
```

Two things follow, and they change the confidence on the fix:

* **`activate_on_collision` and `use_remote_trigger` are genuinely read by the
  DOT script.** Setting `activate_on_collision` to `false` will reach the code
  that decides whether contact activates the field. That edit is now verified as
  live, not inferred.
* **The DOT script never reads `cooldown`**, while arc, stun, burst and drone
  all read their own. So the `cooldown` value added here only reaches DOT
  through the generic `CR15NetMagazinePouchCS` path
  (`grenade_properties|%s|cooldown`), never through its own logic. If re-arming
  is still broken after this, that is a gap *in the script*, not in the data --
  DOT is missing the cooldown handling its siblings have.

The DOT script reads exactly the eight keys the JSON provides and no others, so
there is no missing-key fix left on the data side.

## Disassembly result: DOT is not a broken script

`tools/script_pe.py` pulls the PE out of a script asset and chases CSymbol64
constants through it. On `mp_combat_grenade_dot`:

* The balance-query descriptors sit in `.rdata` as 16-byte
  `(file_symbol, key_symbol)` pairs against `CSymbol64("mp_weapon_settings")`.
* There are **eight** of them, and every one resolves to a
  `grenade_properties|dot|*` path already present in the JSON: `radius`,
  `lifetime`, `ticks_per_second`, `damage_per_tick`, `activate_on_collision`,
  `use_occlusion`, `use_remote_trigger`, `stick_to_geo`.

So there is no hidden knob and no missing key. The data side is complete.

Comparing symbol references across all six ordnance DLLs shows the design:

| | arc | stun | dot | burst | loc | drone |
|---|---|---|---|---|---|---|
| `delegate_OnTriggered`, `R15Trigger`, `R15SetTriggerHandNode` | . | . | . | yes | yes | . |
| `delegate_OnNetTouchGrab` / `Release` | yes | yes | yes | yes | . | . |
| `delegate_OnImpact` | . | yes | yes | . | . | . |
| magazine state (`Get`/`SetStateNode`, `Stable`/`Unstable`/`Exploding`) | yes | yes | yes | yes | yes | yes |

Hand-fired trigger wiring exists only in `burst` (INSTANT REPAIR) and
`translocator` -- the two you hold and fire. DOT never having it is **normal**,
because activation and cooldown are native, in `CR15NetMagazinePouchCS`:

```
grenade_properties|%s|cooldown
[MAGAZINE POUCH] Activating magazine %llx remotely from user
[MAGAZINE] Setting magazine %llx to state %s
```

The pouch activates the magazine and drives its state; the script only reacts
via `delegate_OnStateChanged`. That is why `use_remote_trigger` works without
the script binding a trigger delegate.

**So the bug is exactly the flag conflict.** With `activate_on_collision: true`
the script self-activates on the first `delegate_OnImpact`, and a magazine held
in the hand collides immediately -- it activates and welds itself the instant it
is grabbed, and remote activation never gets a chance. Clearing the flag leaves
the native remote trigger as the only way in, which is the intended
grab -> carry -> latch -> wait -> trigger flow.

### Field test log

* **`trigger`** (`activate_on_collision: false`) -- **did not fix it.** Still
  welds to the nearest geometry immediately, trigger still does nothing.

  That rules out activation being what drives the weld, and corrects the
  reasoning above: `dot` has **no transform-attach nodes of its own**
  (`TransformSetParentNode` / `SetPositionNode` / `SetRotationNode` are present
  in other ordnance scripts and absent from `dot`), so the sticking is native
  and gated on `stick_to_geo` ALONE. The engine side of it is
  `R15RigidAttachConstraint`, which `echovr.exe` names in
  `No R15RigidAttachConstraint found on R15NetMagazine!`.

  This also explains the dead trigger as a consequence rather than a separate
  fault: the magazine welds on spawn, so it is no longer held, so there is
  nothing for the trigger to fire.

* **`trigger-nostick`** -- staged, awaiting test. If the weld stops, the chain
  above is confirmed and the remaining work is making the attach happen on wall
  contact instead of immediately.

### Activation presets

Only three keys change between these, and the script reads all three, so each is
a genuinely different code path. If one does not behave, try the next.

| preset | `activate_on_collision` | `use_remote_trigger` | `stick_to_geo` | |
|---|---|---|---|---|
| `trigger` *(default)* | false | true | true | grab, carry, latch, press trigger |
| `impact` | true | false | true | arms itself where it lands -- use if `trigger` leaves it inert |
| `impact-nostick` | true | false | false | tells a sticking problem from an activation problem |
| `stock` | true | true | true | exactly as shipped; reproduces the bug, keep to A/B |

```bash
python tools/fix_dot.py --base <combatGunPatchFiles> --preset impact --deploy
```

`cooldown` and `damage_table.dot` are applied in every preset -- they are not
activation-mode dependent.

## The `CR15NetGrenadeCS` thread -- closed, wrong tree

`CR15NetGrenadeCS` was a dead end. The logic is in the script DLLs, not in
component data. Recorded so it is not re-walked:

* No `CR15NetGrenadeCRWin10` type folder exists in the extract, while
  `CR15NetGunCRWin10`, `CR15NetMagazineCRWin10` and `CR15NetMagazinePouchCRWin10`
  all do.
* No magazine, pouch or gun component resource references any `r15_ord_*` hash;
  those seven appear only in the name tables of the five combat
  `CActorDataResourceWin10` files, as bare marker actors with no components.
* `evr_actor_data`'s component-to-actor mapping desyncs on these files -- it
  reports each actor's own prefab hash as its component type, and all 288
  component type hashes fail to resolve. Unrelated to DOT, but it is a real bug
  in that reader.

## Tools

| tool | what it does |
|---|---|
| `tools/json_resource.py` | read / rebuild `CJsonResourceWin10` blobs. `verify` round-trips all 21 shipped JSON resources. |
| `tools/audit_gear.py` | diff the gear registry against the tuning tables. Exits non-zero while items are unregistered. |
| `tools/fix_dot.py` | apply the fix; `--base` to rebase onto a gear patch, `--preset` to switch activation mode, `--deploy` to stage. |
| `tools/crack_scripts.py` | name the `StreamingScriptWin10` DLLs (34 of 567 so far). |
| `tools/script_pe.py` | extract a script's PE, locate a CSymbol64 constant in it, disassemble around its references. |

### `CJsonResourceWin10` format

544-byte header, then raw minified JSON — no compression, no terminator.

```
0x000  u64        0
0x008  u64        length of the JSON body
0x010  u64[2]     0
0x020  char[512]  NUL-padded source path
0x220  u8[]       JSON body
```

The asset filename is `CSymbol64(<source filename stem>)`, verified for all 21.
That cracked 15 names not in `hash_lookup.json` — see
`data/hash_lookup_additions.json`, including all five combat map settings
(`mpl_combat_{dyson,fission,combustion,pebbles,gauss}_map_settings`).
