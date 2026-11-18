# Save an existing circular GTP result

`solidworks_cam_save_generated_circular` continues one already successful GTP whose local verifier rejected an explicitly identified feed refresh. It does not calculate the operation again. The capability is pilot; passing software tests is separate from native and engineering qualification.

## Accepted evidence

The input pins the exact failed generation receipt, its original one-shot marker, current source path/SHA, process ID and process lifetime. The historical action must contain one completed GTP with native integer return 0, one earlier CL export, no Save and no setters. The selected operation and positive finite old/new XY-feed values are explicit. Only the two captured feed echoes may change beyond the generated flag and record count accepted by the existing strict generation verifier. Other operation parameters, feature/setup/source fields and all previously generated counts remain protected. Existing bounded mass comparison is reused; no new broad numeric exclusion is introduced.

The original receipt, marker and pre-generation CL stay immutable. The original generation engine fingerprint must still match. Installing an unrelated change to that engine before continuation can invalidate admission and must not be silently bypassed.

## Native sequence

1. Capture current state twice and match the complete historical generated state under the existing geometry comparison.
2. Claim a source-bound continuation marker in the original attempt registry. A new receipt filename cannot bypass it.
3. Call SaveActiveDocument once, recording native intent and primitive return durably before readback. Adopt the real new file SHA and capture/verify the saved result twice.
4. Export one new CL file into a fresh local output directory. Reuse the historical pre-generation CL and compare every previous operation stream, allowing only the one newly calculated operation.
5. Recheck source, document state, events and runtime identity. Return qualification evidence; do not release manufacturing output.

There is no GTP, GOP, AFR, operation creation, tool assignment, parameter setter, rollback or automatic retry. An unknown Save/export result leaves the marker and durable evidence in place. Diagnose the actual state before any subsequent action.

## Evidence and limits

Software qualification: 71 focused tests passed; 6 affected failure tests passed again after adding explicit durable-return assertions. File-only validation accepted the actual completed-GTP history. Independent scoped review passed. Native success is not established by those checks.

Saving an observed refreshed feed preserves the current qualification result. It does not validate spindle/feed cutting conditions, tool clearance, stock, holder, toolpath coordinates, WIP or production safety. A successful result requires separate geometry and machining review. See also [solidworks-cam](solidworks-cam.md#grouped-mill-generation-and-save).

Observed native continuation: one Save and one CL export returned integer0; saved source and repeated clean readbacks were confirmed. The initial terminal receipt remained uncertain because the CL reader rejected negative-Z tool metadata. Independent file-only reconciliation after the bounded parser fix confirmed all previous streams unchanged and the exact new native record count. Preserve that original receipt; do not repeat native calls to repair a parser result. Reopen persistence and production qualification remain separate.
