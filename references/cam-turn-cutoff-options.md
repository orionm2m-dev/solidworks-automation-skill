# Existing TURN CutOff options

`solidworks_cam_inspect_turn_cutoff_options` reads eighteen declared operation-owned scalar properties from one existing TURN CutOff operation (native type 13). This is a pilot inspection capability. Supply the connected process ID and creation time, exact saved part path and SHA-256, setup/operation indices, native operation ID, and ordered linked feature IDs. Only `action="read"` and `message_policy="vendor_default"` are accepted.

The reader validates the exact `ICWTurnCutOffOp` IID and each zero-input property-getter signature before accessing the application. It reads the native values twice:

- Peck controls: `CutOff_GrvType`, `FirstPeckAmt`, `SubPeckAmt`, `MinPeckAmt`, and `PercentPeckAmt`.
- Centre overcut: `DepthClearance`.
- Corner break: `CornerBreakType`, `CornerBreakChamferLength`, `CornerBreakChamferAngle`, `CornerBreakChamferExt`, `CornerBreakRadius`, and `CornerBreakStepover`.
- Other scalars: `MirrorAboutCenterline`, `GenerateLeftOver`, `CNCCompMethod`, `ProgramPoint_GrooveTool_Shift`, `RadialStockAmt`, and `AxialStockAmt`.

Boolean results must be exact Booleans; numeric results must be finite doubles or exact native LONG values. Raw enum values, units and orientation conventions are not relabelled or inferred. `MirrorAboutCenterline` is not interpreted as machining side.

Both captures reuse the source, process lifetime, document identity, selected operation, linked-feature identity, complete collected inventory and CAM event guards. An additional inventory check closes each capture. Any event, mismatch, incomplete capture or cleanup failure prevents successful readback. Post-read runtime drift preserves captured evidence but revokes successful readback. Stable unsaved state may be observed; an unchanged saved-file hash does not prove persistence of all CAM data.

This scope reads no feature profile, tool contour, variable allowance or toolpath record. It performs no setter, toolpath generation or Save. Inventory equality covers the collected operation metadata and record counts, not every CAM parameter or CL coordinate.

## Parameter limits

The bundled CutOff help defines Depth clearance as the amount the tool overcuts the material centre. A readable `DepthClearance` value alone does not establish a final diameter or actual path endpoint. The declared interface provides no direct getter for final diameter, numeric feature Start Length/End Length, or machining side; these are explicitly listed as unavailable in the result.

The Feature Parameters help separately makes Start Length/End Length applicable to CutOff. The distinct Override Feature Extensions section does not list CutOff. The generic override getter is therefore not substituted for numeric extension lengths. The SDK interface index and installed type library establish the available getter contract; the bundled SDK does not provide individual CutOff property pages.

## Verification status

The focused and legacy programmatic suite passed 541 tests, including the current generated type-library getter contracts. Native readback on SOLIDWORKS 2026 SP4 produced two equal captures of all eighteen properties on one existing CutOff operation. The complete collected inventory and saved source stayed unchanged. The document already had unsaved data before the read, and that state was unchanged; this observation does not establish persistence. Successful scalar retrieval does not qualify part separation, stock transfer, reclamping, coordinate frames, holder clearance, material removal or production machining.
