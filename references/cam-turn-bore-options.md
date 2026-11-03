# TURN Bore Rough option inspection

`solidworks_cam_inspect_turn_bore_options` reads eleven raw operation-owned parameters from an existing TURN Bore Rough operation (native type 5). It reuses the two-snapshot, source-pinned, event-guarded operation reader. The existing OD variable-allowance entry and its read/identify behavior remain unchanged.

The caller supplies the connected process ID and creation time, exact saved part path and SHA-256, setup/operation indices, native operation ID, and linked feature IDs. The only action is `read`. No receipt/write options, tool getters, profile traversal, CAM generation, or model saving are exposed. A stable unsaved document may be inspected; unchanged RAM does not prove persistence.

The reader validates the exact `ICWTurnBoreRoughOp` IID and getter ABI before calling the application. It reads `RadialCut`, `AxialCut`, `ReverseCut`, `MirrorAboutCenterline`, `Undercut`, `FirstCutAmt`, `MaxCutAmt`, `FinalCutAmt`, `RadialStockAmt`, `AxialStockAmt`, and `GetAllowanceMethodVariable`. Boolean, finite double, and native LONG results are checked without coercing Boolean values into numbers.

Both snapshots contain the document identity, saved-file hash, complete collected TURN inventory, selected native operation identity, suppression state, linked feature IDs, and the eleven values. A further inventory read closes each capture. All CAM getters run under the subscribed message session; any message, changed source, changed process lifetime, metadata drift, or unclean disconnect prevents a successful readback claim.

The result is metadata only. It does not qualify an undercut toolpath, material removal, holder clearance, coordinate system, units, spindle semantics, or an executable machining process. A documented `Undercut` option and a readable value are separate from engineering approval to enable it. Reversing a cut does not create an opposite-face setup.

## Native qualification

The installed implementation read all eleven options twice on an existing rough-boring operation. Both scalar captures and complete inventories agreed, the source stayed unchanged, and no CAM messages were observed. The observed undercut flag was already enabled; the reader therefore ruled out that particular configuration hypothesis. This does not qualify material removal, units or a tool envelope. The installed focused and legacy regression suite passed 307 tests.
