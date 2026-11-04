# TURN bore option inspection

`solidworks_cam_inspect_turn_bore_options` reads eleven raw operation-owned parameters by default from an existing TURN Bore Rough operation (native type 5). It reuses the two-snapshot, source-pinned, event-guarded operation reader. The existing OD variable-allowance entry and its read/identify behavior remain unchanged.

The caller supplies the connected process ID and creation time, exact saved part path and SHA-256, setup/operation indices, native operation ID, and linked feature IDs. The only action is `read`. The default request does not traverse tool or feature profiles. No receipt/write options, CAM generation, or model saving are exposed. A stable unsaved document may be inspected; unchanged RAM does not prove persistence.

The reader validates the exact `ICWTurnBoreRoughOp` IID and getter ABI before calling the application. It reads `RadialCut`, `AxialCut`, `ReverseCut`, `MirrorAboutCenterline`, `Undercut`, `FirstCutAmt`, `MaxCutAmt`, `FinalCutAmt`, `RadialStockAmt`, `AxialStockAmt`, and `GetAllowanceMethodVariable`. Boolean, finite double, and native LONG results are checked without coercing Boolean values into numbers.

Both snapshots contain the document identity, saved-file hash, complete collected TURN inventory, selected native operation identity, suppression state, linked feature IDs, and the eleven values. A further inventory read closes each capture. All CAM getters run under the subscribed message session; any message, changed source, changed process lifetime, metadata drift, or unclean disconnect prevents a successful readback claim.

The default result is scalar metadata only. It does not qualify an undercut toolpath, material removal, holder clearance, coordinate system, units, spindle semantics, or an executable machining process. A documented `Undercut` option and a readable value are separate from engineering approval to enable it. Reversing a cut does not create an opposite-face setup.

## Native qualification

The installed implementation read all eleven options twice on an existing rough-boring operation. Both scalar captures and complete inventories agreed, the source stayed unchanged, and no CAM messages were observed. The observed undercut flag was already enabled; the reader therefore ruled out that particular configuration hypothesis. This does not qualify material removal, units or a tool envelope. The installed focused and legacy regression suite passed 307 tests.


## Optional leftover controls

`include_leftover_control=true` adds only `ICWTurnBoreRoughOp.GenerateLeftOver` (strict Boolean) and `LEFTOVER_TYPE` (raw native enum) to each scalar capture. The flag defaults to `false`, preserving the original eleven-field request; enabling it gives thirteen fields and does not enable tool contours. Both extra getters use the existing source, process, operation, feature, inventory and event guards.

The reviewed type library declares `NONE=0`, `FEAT=1`, `WIP=2`, `NEW_STOCK=3`, and `NOT_DEFINED=4`. The reader checks a strict integer in this range and the exact getter signature. It does not independently validate the enum constants at runtime or infer a complete correspondence to the UI stock modes. The older bundled SDK enum page lists only values 0 through 2 without descriptions. Reading these controls does not define new stock or establish stock transfer between setups. Native readback on SOLIDWORKS 2026 SP4 produced two equal thirteen-property captures on one existing rough-bore operation. The observed values were `GenerateLeftOver=true` and `LEFTOVER_TYPE=1` (declared symbol `FEAT`). The original eleven values, collected inventory, saved source and pre-existing unsaved state remained unchanged. This verifies the bounded read, not the UI stock-mode meaning or the stock supplied to a subsequent operation.

## Finish-bore leftover controls

For an existing Bore Finish operation (native type 6), the same tool accepts only `include_leftover_control=true` with `include_tool_contours=false` and no expected tool ID. It reads exactly `ICWTurnBoreFinishOp.GenerateLeftOver` (DISPID 22, strict Boolean) and `LEFTOVER_TYPE` (DISPID 23, strict integer 0 through 4). Rough-bore properties and their DISPIDs are not reused for finish operations. The eleven-field rough default and thirteen-field rough opt-in remain unchanged.

The finish branch validates the exact interface IID and two getter signatures before connecting to CAM. Its two snapshots retain the exact process lifetime, document and saved-source pins, selected native operation and linked feature IDs, complete collected inventory, and raw values in `bore_options_native`. It does not read feature or tool contours. Stable unsaved RAM is allowed but does not prove persistence. A changed value, identity, inventory, event state, or cleanup result revokes readback verification; partial evidence is retained.

This finish branch has software-only pilot validation. It does not claim a native successful read until separately observed. These are the selected operation's own controls; another operation's values cannot substitute for them. Neither the enum value nor `GenerateLeftOver` proves incoming-stock shape, a UI mode correspondence, a previous-operation WIP link, or a complete simulation replay. No setter, New Stock definition, stock export, GTP, GOP, CL or Save is performed.

A post-read runtime change preserves the returned captures and revokes `readback_verified` and `may_continue`. Reconnect to a current server after installing runtime changes.

## Optional existing tool contours

`include_tool_contours=true` additionally requires `expected_tool_native_id` to identify the selected operation's own tool. Both inputs are strict: Boolean flags and integer IDs are not coerced; an unused expected tool ID is rejected. The default remains `include_tool_contours=false` with no expected tool ID.

This bounded extension accepts an existing single-point TURN diamond insert with a boring-bar holder. It checks the exact own tool ID before reading tool dimensions or geometry and reports the raw insert type, dimensions, holder type/ID, operation orientation and X/Z insert offsets. Unsupported tool or holder types stop the read; there is no catalogue lookup or replacement tool.

The reader validates the exact interface IIDs and getter signatures before accessing the application. `ICWTool.GetToolProfile()` takes no input argument and returns the insert extrusion section. `ICWTurnToolHolder.GetHolderProfile(operation)` and `GetToolOrientationForOperation(operation)` receive the exact selected operation object. Both contours are read inside each of the same two captures as the bore scalars, under the existing source, process lifetime, operation/feature identity, full inventory and event-session guards. No THREAD default-operation catalogue or linked-feature profile is requested.

The shared decoder is extracted from the existing holder-profile reader without changing that reader's calling contract. Each contour is bounded to 32 chains and 512 total curves. Lines retain endpoints; arcs retain endpoints, midpoint, centre, radius and raw sense. Null, empty, oversized or unsupported contours prevent successful readback and keep any partial evidence. `parameters_complete` means that supported native curve parameters were decoded; it does not establish closure, topology, units, valid solid geometry, common coordinate frame or manufacturing suitability.

The default insert profile's frame is not explicitly defined by the method help. Holder geometry is operation-specific; orientation and X/Z offsets do not by themselves prove a common insert/holder/CL frame or the toolpath program point. This extension does not call the separate Down Left insert getter, read CL, infer a transformation or qualify a cutting sweep. All coordinate-frame, program-point, physical-holder and production-qualification flags remain false.

The optional contour extension retrieved the selected own insert and operation-specific holder contours in two matching native captures on one existing rough-boring operation. The source and full collected inventory remained unchanged, and zero CAM messages were observed. This qualifies that bounded native retrieval only. Native units, the insert/holder/CL frame, program point, contour closure and solid geometry, physical tooling and production suitability remain unqualified. Offline mocked and ABI-contract tests cover routing and failure handling separately from this native observation.
