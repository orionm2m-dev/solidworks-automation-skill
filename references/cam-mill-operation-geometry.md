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


A returned integer status1 with a null base-feature pointer is retained as
`base_getter_status1_null`; no base-interface query or parameter read is attempted
for that target. After safe identity/source/event checks, the explicitly selected
comparison target is still read. Status1 with a non-null base pointer remains an
unsupported contract and stops the probe. If the parameter getter returns integer
status1, its caller-owned outputs are preserved only as `parameter_getter_status1`
diagnostics and are never accepted as valid parameters. Other nonzero or untyped
returns still stop. None of these outcomes establishes why a toolpath is empty.
The initial native status1/null observation motivated this bounded software change;
the completed two-target continuation remains a separate native qualification.

## Explicit virtual-feature metadata observation

`observation_mode` defaults to `tp_geometry`, preserving the original two-getter
path. `virtual_features` instead requires exactly one target equal to the pinned
anchor operation. It reads that operation's `ICWOperation.IGetAllVirtualHoleFeatures`
(DISP30, HRESULT with IDispatch retval) into caller-owned storage. No virtual member
is automatically passed to GetTpBaseFeature or cast by its name.

For S_OK/non-null only, standard IDispatch GetTypeInfoCount and GetTypeInfo(0,0)
provide type metadata. Exact standard ITypeInfo binding reads GUID, raw typekind
and at most 256 name characters. GetTypeAttr uses an owned pointer and immediate
ReleaseTypeAttr in a finally block, including event/error exits. All IDispatch
outputs, including collection Item, use raw wrappers to avoid automatic
GetBestInterface discovery. GetDocumentation strings are owned BSTR buffers;
description/help-file content is not retained.

Only the observed exact ICWDispatchCollection GUID
`{670DD771-2C33-11D6-A9A1-00062999E55F}` admits collection QI, raw Count and raw Item.
Count must be 0 through 8 before any Item call; indices are exactly 0 through
Count-1. Each member contributes standard type metadata only. Unknown GUIDs,
no type information, nulls, native COM failures and integer status1 remain bounded
diagnostics, without guessed casts, alternate enumeration or retries. Unsupported
statuses/counts, invalid ABI, failed cleanup or unsafe context stop the observation
and retain partial evidence. Status1 outputs never become complete metadata.

`virtual_collection_complete` distinguishes an admitted fully observed collection
from stable diagnostics; zero Count is a collection observation, not the cause of
an empty toolpath. The existing `pointer_interfaces_traversed` flag describes the
opaque geometry outputs of the `tp_geometry` mode; the virtual mode explicitly
traverses only this bounded collection and standard metadata, never member
geometry. `parameters_complete` remains false in virtual mode. Two matching
captures and the existing source/process/event/runtime guards are still required.
The new mode has offline software coverage only and needs separate native
qualification; no geometry, feature binding, toolpath cause or machining claim is
made. There is no new endpoint, mutation, Save or GTP action.
