# TURN drill: confirmed read scope and unavailable geometry

`solidworks_cam_inspect_operation_profile` accepts optional `include_operation_parameters=true` only for TURN operation type 9. The default is false. The declared `ICWTurnDrillOp` exposes three fields read by this option: `DrillCycleType`, `GenerateLeftOver`, and `LEFTOVER_TYPE`. Their raw integer/Boolean types are checked. `read_complete=true` covers only those three fields; enum meaning is not inferred.

Machining depth, entry plane, tip overtravel, through state, retract plane and retract amount are not exposed by this acquired interface. The response explicitly keeps `machining_depth_available=false`. Do not substitute the different centre-drill interface or derive actual depth from the tool description or linked feature alone.

A real assigned generic-tool type 15 / TURN-tool type 2 returned `E_NOINTERFACE` when queried for `ICWDrillTool`; no dimensional getter ran. The ordinary profile reader now reports the geometry unavailable without repeating that query or attempting insert/holder getters. The reported unsupported HRESULT is the retained capability observation, not a fresh probe on each call. An interface declaration in the type library does not establish that this native object implements it.

The shared `_read_tool(..., include_drill=False)` default preserves existing caller behavior. The profile entrypoint opts into the explicit unavailable report. `include_tool=false` skips the whole tool chain and permits the separately requested operation fields. None of these outcomes verifies units, drilling depth, tip breakthrough, clamping clearance or production suitability. A new geometry path needs a documented object-acquisition contract and separate qualification.
