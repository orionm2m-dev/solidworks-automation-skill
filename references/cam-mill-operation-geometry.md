# MILL operation toolpath-feature geometry read

`solidworks_cam_inspect_operation_geometry` is a bounded read-only pilot. It uses
an explicit owned process, process creation time, saved document path/SHA and a
completed current-saved configuration receipt. `anchor_operation_native_id` binds
the existing completed-configuration loader; one to four explicit targets provide
operation, feature, feature setup, operation setup and MILL operation type IDs.
The comparison target may be a different already generated operation in the same
pinned route. No default operation or feature is selected.

The reader repeats a bounded inventory and each selected logical owner binding
twice. It reuses the route reader for ordered operation IDs, links, suppression,
path counts and generic own-tool scalars. It does not repeat full parameter,
feature-profile or holder-profile reads. Current inventory must match the saved
anchor; document/source/process/runtime/events and all immutable evidence files
are checked at read boundaries. No canonical-wrapper-identity equality is assumed.
The fixed getter/QI budget is 2048 for the whole session.

The two exact declared methods are `ICWMillOperation3.GetTpBaseFeature(feature)`
(DISP25, IDispatch input and IDispatch retval) and
`ICWTpBaseFeature.GetTpFeatParameters` (DISP1, seven OUT parameters). The latter
returns machining depth, feature depth, start Z, a pattern Boolean, then start
position, island-list and segment-chain dispatch outputs, in that declared order.
Raw generated vtable wrappers use caller-owned initialized buffers and preserve
HRESULT/output observations before post-call event checks. This avoids comtypes
client automatic best-interface/type-info discovery for IDispatch OUT values.
Only integer S_OK, three finite DOUBLE values and canonical VARIANT_BOOL0/-1 are
accepted as complete parameter output. Dispatch outputs record null/non-null
presence only: no pointer address, guessed interface cast or traversal occurs.

A null base feature, a native failure of either getter, or exact E_NOINTERFACE for
the declared base-feature interface is retained for that target. The next explicit
target is read only after safe source/identity/event checks, without fallback or
retry. Other interface errors, invalid ABI/output, unsafe context or differing
snapshots stop the probe. Stable diagnostics can have `readback_verified=true`
while `parameters_complete=false`; neither null nor an HRESULT proves the reason
for an empty toolpath. `observed_target_outcomes` and `observation_result` distinguish
complete output from stable null/unsupported/COM observations. Running state is
explicitly pending; only finished results receive success/error status.

No setters, GTP, GOP, recognition, Save, exports, UI actions or database writes are
available. Units, posting/world frame, complete contours, machining cause and
production qualification remain unverified. The tool returns structured evidence,
including partial observations on failure; the caller's existing MCP job/CLI output
writer must persist that response to a fresh result path. There is no tool-specific
receipt-path input. Offline software tests do not claim native qualification.
