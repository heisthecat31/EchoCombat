# Phase 2: AI bots in Echo Combat

Goal: `-bots N` (max 9) on a combat server gives bots that move, fight, respawn,
take the teleport orbs out of the war room, and choose between hunting players and
holding the capture point. Start on Dyson (`mpl_combat_dyson`), then the other maps.
Random loadouts come last; bots keep their current loadout until then.

## What the game already has (from the Quest build, libr15.so, via ReVault)

Bots are `CR15NetBotCS` components (the "R14NetBot" actor). The engine gives them
everything a combat bot needs as primitives -- only the decisions are missing:

| need | CR15NetBotCS method / node |
|---|---|
| move | `MoveToPoint(h, ...)`, `MoveToTransform`, `BoostToTransform`, `StopMovement`, `IsMoving` |
| pathing | `R15EchoPathing` (needs `CR15NetBotAnimCS`) |
| aim | `R15NetBotSetLookDirectionNode` (script node), head layers (`GetActiveLayer`, `ClearHeadLayer`) |
| shoot | `FireHeld`, `HoldFire`, `ReleaseFire`, `ToggleFire`, `CycleGun` |
| ordnance | `CurrentOrdnance`, `CycleOrdnance`, `TriggerGrenade` |
| tac mod | `CurrentAbility`, `ActivateBarrier` / `ActivateRepair` / `ActivateSensor` / `ActivateWraith` |
| who / where | `Transform(h)`, `UserId(h)`, `FindHandle(userId)`, `DistanceToPlayer(h)`, `SetOccluded` |
| loadout | `SR15NetBotSetGear` message, `CR15NetBotSetLoadoutSlots`, `CR15NetBotLoadoutShuffle` |

Behaviours are `CR15AIB*` classes made by a factory (`CR15AIInstallers::InstallFactories`)
and driven by scenarios (`CR15NetAIScenarios`: `SR15NetBotActivateScenario`,
`SR15NetBotDisableScenario`, `SR15NetBotSetGear`). Every shipped behaviour is for
arena: Block, ClearDisc, Defense, EnterTube, GetDisc, Goalie, Idle, MoveToProp,
PostGame, PostRound, PreGame, Punch, RandomMove, Stunned, Throw, TravelToPass,
TravelToScore, TravelToTunnel, TubeEscape, TubeLaunch. Nothing for combat -- which
is why combat bots stand still.

## Findings so far (step 1)

The bot "methods" are plain writes into each bot's record, so `CombatBots.dll` can
drive a bot by writing the record itself -- no engine calls needed. Same layout in
both builds (checked on PC through CycleGun / CycleOrdnance, below):

    record = *(cs + 0x100) + slot * 0x1B0,  slot = ((u16 *)*(cs + 0xD0))[handle & 0xFFFF] (u32 entries)
    cs + 0x168   u32  "authority": fire setters only act when non-zero (set by Update)
    cs + 0xFC    u16  enabled component count

| field | meaning | written by (Quest, libr15.so) |
|---|---|---|
| +0x28 u16 | ordnance cycle counter | CycleOrdnance (PC 0x140cbfed0) |
| +0x2A u16 | gun cycle counter | CycleGun (PC 0x140cc00b0) |
| +0x60 u32 | moving (1) / stopped (0) | MoveToPoint, BoostToTransform, StopMovement |
| +0x64..+0x83 | target transform (CTransfQ, 32 bytes) | BoostToTransform |
| +0x74/+0x78/+0x7C f32 | target point | MoveToPoint |
| +0xC8 u32 | fire held | HoldFire (1) / ReleaseFire (0) |
| +0x12C u32 | boost | BoostToTransform (1), StopMovement (0) |

Quest addresses: MoveToPoint 0x211dcf4, MoveToTransform 0x211dd24, BoostToTransform
0x211dd5c, FireHeld 0x211dcbc, HoldFire 0x211cae4, ReleaseFire 0x211cb14,
StopMovement 0x211deb8, IsMoving 0x211dee0, Transform 0x2118ee4, TriggerGrenade
0x211db28, CycleGun 0x211cdb4, SetLookDir 0x211dda0 / 0x211de10 / 0x211de84 (three
overloads), Update 0x211b60c. PC: CR15NetBotCS vtable 0x141ca8178 (95 slots),
ctor 0x140c90810, SetOrdnance 0x140d47170, ThrowGrenade 0x140d5e620.

Still to find on PC: the bot system instance at runtime (capture it from a bot
method's `this`, e.g. SetOrdnance on spawn), a per-frame hook on the game thread to
run the brain from, the look-direction fields (SetLookDir), and where players'
positions / teams are read.

## Plan

A server-side plugin, `CombatBots.dll` (loaded by the plugin loader like
PowerBoost / VeilNet), runs a brain per bot each frame on combat maps and drives it
through the methods above. No new engine classes: the decisions live in the DLL.

1. **Map the primitives onto echovr.exe.** The Quest build has the names; the PC
   build has the constructors named (`CR15NetBotCS::CR15NetBotCS` @ 0x140c90810)
   but not the methods. Match each needed method (vtable slots first, then callers
   from the arena behaviours and the script nodes above).
2. **World state.** Players (position, team, alive), bots (handle, team), capture
   point, war room teleport orbs, match score -- per map, read from the game where
   possible, else a per-map table (Dyson first).
3. **Respawn.** Find why combat bots stay dead (combat respawns into the war room
   on input; arena bots respawn through PostRound) and drive it.
4. **War room.** Move to an orb, grab it (touch), get teleported. Pick the orb by
   where it lands relative to enemies and the point.
5. **Fight.** Target the nearest visible enemy (occlusion), aim with lead, fire in
   bursts; strafe / boost while engaging.
6. **Strategy.** Per team: split hunters vs point holders by bot count, score gap
   and where enemies are; re-decide every few seconds.
7. **Loadouts** (last): random loadout per life through `SR15NetBotSetGear`, and use
   ordnance / tac mods.
