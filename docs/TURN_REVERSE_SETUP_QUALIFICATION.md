# Reverse TURN setup qualification

The MCP tool `solidworks_cam_qualify_turn_reverse_setup` prepares or applies one native insertion on a saved, isolated part. It starts with exactly one feature setup and one linked operation setup. The existing bore operation (type 5 or 6) provides an exact operation/feature witness; the insertion anchor is the feature setup object obtained from `IGetEnumSetups`.

The only mutation is typed `ICWTurnMachine.InsertTurnSetup1(True, feature_setup)`. Its exact current contract is DISPID 25, HRESULT, two IN parameters (VARIANT_BOOL and IDispatch*) and an OUT retval IDispatch**. The returned value is a new setup object, not a Boolean. The implementation validates this signature before acquiring the application.

The vendor's Turn Setup help describes Reverse Direction as reversing positive Z, and describes this setup in the feature tree. The type library alone does not promise whether an associated operation setup will be created. This qualification therefore accepts one additional empty feature setup and optionally one additional empty operation setup linked to it. It rejects any added features or operations. It does not call InsertTurnOpSetup, move/copy features, generate operations or toolpaths, save, retry, or roll back.

## Request and execution

Both actions require exact process ID and process creation time, saved part path and SHA-256, selected operation index/type/native ID and linked feature IDs, both native setup IDs, and all inventory counts. The part must be the sole loaded document. At least two protected part pins are required, including a separate archive with the current source SHA-256. All protected files must exist, match their hashes, and be distinct from the active copy by normalized path and filesystem identity.

`prepare` performs two complete equal captures under one CAM event subscription and returns `state_sha256`. No once marker is written. The original setup must have forward direction and a finite nonzero axis. `qualification_only: true` and `message_policy: "vendor_default"` are required.

`apply` additionally requires that exact prepared digest and an unused absolute JSON receipt path. It repeats both complete captures, checks the digest, writes and flushes a once marker keyed by scope plus the copy's device/inode, and durably publishes a pending receipt. A further complete capture must still equal the prepared state, and the feature setup anchor is resolved again from that fresh enumeration before the one insertion. The once marker is retained on all outcomes; changing an index or setup ID cannot enable replay on the same file.

After the call, the returned native ID must equal the only additional feature setup, located directly after the anchor. Its feature collection must be empty, reverse flag strictly true, and normalized axis opposite the original within 1e-9 per component. Any additional operation setup must be empty and link to this new feature setup. Two complete post-insertion captures must agree. Every original setup, feature association, operation order, native tool ID, operation type, suppression flag, generated flag and per-path record-count list must remain unchanged. Setup position indices and document dirty state are the only permitted differences in original rows.

Any event, ambiguous return, unexpected side effect, changed source or process, failed receipt, or failed readback stops qualification. A possibly dispatched attempt reports `uncertain`; it is never retried. Success is `review_required` with `readback_verified: true`, not production approval.

## Observation limits

Existing qualified setup-reader helpers provide Axis, IsReverseDirection, reference point, operation FCS origin, GetSetup links, and transform metadata. GetData output GUIDs, scale and rotation flag are observed; output vectors and matrices remain undecoded. Canonical IUnknown inequality is recorded and does not override a consistent native setup link.

Preservation covers the recorded metadata, not all hidden CAM state, numeric transform matrices, CL bytes, complete part geometry or saved persistence. Raw axes/origins do not establish a coordinate mapping to CL or tool contours. A successful empty reverse setup does not prove low-end origin relocation, tool access, collision clearance, complete material removal or a finished machining process.

## Verification and installation

Synthetic native-shaped tests exercise the actual capture helpers, exact one-call routing, durable receipt ordering, once-marker replay prevention, source/process/event guards, original-operation drift, unexpected setup side effects, and uncertain outcomes. Separate wrapper tests cover strict schema, action guards, connected process binding and runtime checks.

Install the one new core module, its tests and this document. Add only the two new server AST nodes (`SolidWorksCamTurnReverseSetupInput` and `solidworks_cam_qualify_turn_reverse_setup`) to the current server. Existing readers, parser, bridge and server nodes are unchanged. Native insertion requires a reviewed guarded call; observed qualification is described below.


## Observed qualification

A saved TURN qualification part was exercised through the guarded native call. One empty reverse feature setup and one empty linked operation setup were created. The reverse flag and opposite axis were verified in two full captures. All 11 existing operations, their associations and per-path record counts (six generated paths, 409 records) remained unchanged; no CAM events were emitted.

An explicit native save and reopen preserved the two setup IDs, their empty/new and original feature associations, all 11 operation IDs/order and the six path record counts. The new reverse axis was not separately reread after reopening in that persistence check. Full CL byte preservation, decoded coordinate transforms, machining access and production suitability were not established by this qualification.
