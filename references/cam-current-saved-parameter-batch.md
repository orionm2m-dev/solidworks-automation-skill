# Current saved MILL parameter batch

`solidworks_cam_configure_guide_definitions` also accepts the explicit
`configuration_mode="current_saved"` input. The historical sealed four-guide
branch remains unchanged. This mode is an offline-tested pilot; native prepare
and apply qualification are separate steps.

Prepare pins an actual successful parameter-read request and result, the completed
Save authority behind that read, the current source hash, exact process lifetime,
feature/setup IDs, ordered operation IDs and path counts. It repeats the complete
capture twice. It exposes the existing candidate tool's observed mill/holder
scalars, all current consumers, and operation-owned spindle, XY feed and CNC/toolpath
compensation for both selected parameters and candidate consumers. Consumer NC is
not a tool preset or recommended cutting condition. Full profiles and physical
cutting conditions remain unqualified.

The external versioned JSON recipe contains explicit operation/feature/type IDs,
expected own tool ID, optional existing candidate ID and fields with exact expected
and new values. The initial allowlist supports rough0 only: entry_type,
spiral_radius, spiral_pitch, first_depth, subsequent_depth, side_allowance,
floor_allowance and side_step. Pair values are `[bool, double]`. No interface name,
COM member or arbitrary property can be supplied by a caller. Units and raw enum
interpretation are not established by numeric validation.

Apply requires the exact immutable prepare. A source/feature claim in the pinned
attempt registry precedes any mutation. Each attempt and returned outcome is
persisted before further checking. Existing-tool assignment uses the same-document
bounded toolcrib and full observed dimensions; it never edits that shared tool.
Two full captures after SetTool must show only the requested tool binding and its
exact derived usage rows changed. All rough parameters, levels, feed, speed and
compensation remain unchanged. Any reset stops the batch for review.

Each field setter verifies the immediate own expected value, dispatches once and
reads that field back. Source/process/runtime/events are checked at these boundaries.
Two full final captures protect the unselected operation, old path counts/order,
profile, NC and observed tools. Only the established FirstDepthAmt/SbsqDepthAmt
aliases accompany their depth setters; DepthAllow remains protected. Full hidden
geometry and complete CL coordinates are outside this capture.

Optional Save reuses the checked `ICWApp.SaveActiveDocument` sequence, once, only
after the full parameter delta passes. The returned HRESULT, new file hash and two
full saved captures are required. No GTP, GOP, feature creation or tool database
write occurs. A false host `needs_save` flag does not prove CAM definitions are
already saved. Interface-registry and exact primary ABI compatibility checks run
before any native mutation.

Unknown outcomes retain the partial receipt and exclusive claim. There is no
replay, automatic rollback or implicit continuation. Runtime drift revokes success
while retaining all returned native evidence. Completed receipts use
`MILL_CURRENT_SAVED_PARAMETER_BATCH_V1`, `saved == confirm_saved` and separate
Save/readback/source flags. `request_pin` hashes the canonical binding; it is not
the byte hash of an external MCP envelope. Real input file pins are recorded in
`qualified_read_pins`.


## Explicit Save-only recovery

`prepare_recover_save` and `recover_save` are separate actions in the same
current-saved input. They require immutable partial-receipt, old-marker and original
apply-request path/SHA pairs; the original prepare pin is derived from that request.
The original receipt and claim are never rewritten. A distinct recovery claim is
bound to the partial receipt hash and prevents a second recovery attempt.

The admitted historical case is deliberately narrow: the complete eight-action
batch returned integer zero and each own-field readback succeeded, but the final
comparison stopped on the three recorded representations of `DepthAllow` changing
from 1.0 to 0.2 with `GetZAllowance`. A pure history validator checks the original
request, prepare, marker, full baseline, strict tool-assignment barrier and exact
final state. This observed relationship is not a universal API alias. Ordinary
parameter batches still protect `DepthAllow`; no caller-controlled alias switch
is exposed.

Recovery prepare repeats the exact final partial state twice with all original
identity, file, runtime and event guards. Recovery apply repeats that proof and
performs only one checked Save, followed by two full saved captures. It cannot
assign a tool, repeat a field setter or generate a path. Its receipt retains
`action="recover_save"`, separate historical evidence and exactly one Save action;
it is never relabelled as a new ordinary apply. Completed recovery can become
subsequent read/generation authority only after all recovery and Save checks pass.
These recovery paths have offline software tests; native qualification is separate.
