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
