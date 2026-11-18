# One pocket definition with four autodetected islands

This pilot creates exactly one closed pocket through public ICWSetup.CreateMillFeature2 with autoDetectIslands=true. It consumes actual receipts from an empty native MILL setup, its existing lifecycle Save, and a verified outer-circle reference sketch. Paths, source hashes, process lifetime and current setup identity come from the request. Historical CAM IDs are never reused as target IDs.

The live source is the known unsaved sketch state after its creator receipt. The protected disk source is the saved empty-setup version; the protected original remains unchanged. Two bounded inventories before and after creation must contain the exact permitted one-feature delta, no operations and no toolpaths. The new feature must have the actual returned ID, selected setup, -Z axis, requested depth, no taper and exactly four declared islands. One target-and-sketch marker prevents replay even when the native result or readback is uncertain.

A successful result has status `definition_only`. It explicitly leaves island geometry, physical depth/frame interpretation, feature association, stock, material, tool access and production acceptance unqualified. Basic island count is not geometric proof. No unsupported island-object getter is retried. No import, AFR, GOP, GTP, Save, response override or UI action occurs.

Inputs include exact source/original and native geometry pins, setup creation/Save receipts, circle creator receipt/spec, expected CAD/CAM configurations, owner setup ID, native depth, and a fresh output JSON path. Outputs preserve the requested factory arguments, new native ID, scalar header, complete basic inventory, events, immutable file pins and original exceptions. A known creator sketch is allowed to be dirty; unrelated dirty documents are rejected.

Any event, changed identity/evidence, extra operation, wrong count or scalar mismatch stops the sequence with no follow-on action. A claimed call remains consumed. Native definition facts are retained even if later readback fails. A separate reviewed computational recipe may later bind selective GOP/GTP and inspect raw CL against exact native R25 guides; this module does not grant that authority.

The companion pure analytic-loop checker has no application calls and is not a fallback native reader. It compares four independently observed two-line/two-arc contours to pinned native geometry. Its output proves planar loops only and does not infer a coordinate frame or vertical extent.

Native qualification is pending until an actual once-only invocation is independently reviewed. Public signature checks and software tests do not establish native behavior.
## Native depth scalar comparison

The raw requested/read-back `Depth` scalars use the existing `sw_cam_added_pocket_delta.close` comparator: finite strict int/float values, absolute tolerance 1e-8 in native CAM units, zero relative tolerance. This admits binary rounding such as 25.8 - 12.6 returning 13.200000000000001. The receipt preserves both values and the comparison rule. It does not establish native-to-physical unit conversion, physical depth, island geometry, stock or machining acceptance; those flags remain false. IDs, owner, axis, counts and all other inventory comparisons retain their existing checks.


## Saved manufacturing-cap source variant

The existing `solidworks_cam_create_pocket_with_detected_islands` tool accepts `source_variant=saved_cam_caps` with exact completed-cap, whole-body geometry, native STEP export, CAD Save and post-Save zero-CAM receipt pairs, plus the observed CAD-only SHA. The original receipt fields remain mandatory. The setup-before SHA is the CAD cap Save SHA, while the protected original SHA remains separate. The new empty-setup CAM Save supplies the current source SHA. Existing requests omit the variant fields entirely; the server excludes unset optional fields before the strict backend contract. The inherited actual `addin_clsid` remains required in the MCP parameters, outside the backend request.

The old circle creator supplies only its original analytic specification. Its historical PID/path/unsaved-body state is not relabeled as current authority. The current branch reads the existing unsuppressed circle inline, twice, using the original exact native circle reader and inverse sketch transform. Current tree/body/source/dirty identity must match the saved cap baseline. The reserved fallback plane name need not exist; actual plane elevation and normal are read geometrically. No sketch, plane or circle is created or edited.

Exactly one existing CreateMillFeature2 call remains, with autodetection enabled. Immediately after its nonnull return, the saved-source branch records the actual document and permits only the observed boolean dirty-flag change from its clean initial state; all other identity/configuration/file/event checks remain strict. No dirty setter, event-baseline reset, Save, AFR, GOP, GTP or island/profile getter is added to creation. Unknown CAD additions remain an exact-delta failure after the consumed call. They do not permit another creation.

The existing recovery reader supports this variant only for its original exact reviewed Attribute-suffix failure. It validates the original inline circle capture, current observed dirty state and unchanged source receipts; it does not fabricate a successful creator or relax unknown tree changes. Definition Save and subsequent clean-source profile reads remain separate stages. Four island counts and scalar readback do not prove world geometry or authorize GOP/machining.

Tests cover legacy/saved dispatch, historical-spec role separation, all source links, paired current circle reads and plane/body/tree changes, observed clean/dirty outcomes, incompatible identity changes, raw uncertainty, and existing no-replay behavior. These offline tests do not establish native execution of this new source variant.


## Genuine definition receipt origins after Save

The existing `definition_recovery_receipt_path` / `definition_recovery_receipt_sha256` input names remain for compatibility. Their loader now dispatches on the actual receipt scope: a successful genuine creator is validated directly; an actual recovery is validated by its existing recovery verifier. Neither raw receipt is rewritten or relabeled. The context records `origin_kind=creator` or `origin_kind=recovery`. Unknown scopes, incomplete/uncertain creators, mismatched consumed markers, missing evidence pins, incomplete captures and promoted geometry claims are rejected. Legacy recovery scope and marker derivation remain unchanged.

For saved_cam_caps, zero-operation definition Save must begin from the exact document observed after the consumed Create. Its boolean needs_save value may be false or true, and the native Save must establish false; no flag setter is introduced. All other Save identity, counts, owner/frame, HRESULT, source-change, event and cleanup requirements remain unchanged.

The current sketch baseline comes from the genuine paired inline read on the saved cap source. The historical circle creator remains its original evidence and is not relabeled as current geometry authority. Known separately verified Attribute additions are taken only from the actual complete definition/recovery inventory. A subsequent Save changes only the explicitly verified source hash and clean state. Profile geometry reads, world placement proof, GOP, GTP and machining approval are separate requirements. This adapter adds no native calls or endpoints.
