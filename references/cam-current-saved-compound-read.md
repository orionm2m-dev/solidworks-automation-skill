# Current saved MILL compound observation

`solidworks_cam_inspect_current_saved_compound` is a pilot read-only mode for an exact compound feature in a currently saved part. It is independent of historic selected-plan receipts. Existing saved-plan loaders and their constraints stay unchanged.

Inputs pin the selected PID and process creation time, absolute part path and SHA-256, target feature ID, owning feature-setup ID, operation-setup ID, complete ordered operation IDs, generated-operation count and summed path-record count. `read_mode="current_saved"`, `qualification_only=true` and `message_policy="vendor_default"` are required. The part must be clean. No API mutation, AFR, GOP, GTP, Save, file export or TechDB access is performed.

The reader observes bounded setup/feature membership, setup axes/origins, operation identities/links/flags/path counts and generic assigned-tool scalars. The selected operation setup is bound to its feature setup using declared `ICWBaseOpSetup.GetSetup` (DISPID30, HRESULT, OUT retval IDispatch). It resolves the target both through enumeration and `ICWDoc3.GetCWObjectFromID`, checks native IDs and `GetOwner`, then reuses the existing `read_header` and compound step decoder. No canonical IUnknown equality assumption is made.

`header_and_count` reads the header and bounded native count without indexed step getters. `three_step_profile` calls the existing explicit indices0,1,2 reader only if the actual count is exactly3, otherwise it stops before the first indexed call. The cylinder/cone selection uses `GetTypeAtStep`; unsupported types stop without fallback. Count discovery does not establish an arbitrary index base. A successful profile observation describes those three valid indices for the exact feature only.

Two full captures must match. Every CAM getter is guarded by the event session; exact source/process/document checks occur at capture and setup boundaries. A native error or event stops further CAM getters. Partial captures and the converted shapes of returned step outputs are retained before checking post-call events. After event disconnect only document/file/process checks run. Wrapper runtime drift preserves the returned observations and revokes verification.

`readback_verified` and `observation_verified` mean stable raw observations in this bounded scope. They do not establish native units, world coordinates, full hidden tool/holder geometry, exact old CL coordinate preservation, machining suitability or production acceptance. Because the tool only reads, it uses no apply marker. Failures never trigger an automatic retry. This staging mode has synthetic traversal and metadata tests; native current-saved qualification is pending.

The legacy reusable implementation contracts are `sw_cam_mill_selected_plan_context.read_header`, `sw_cam_mill_route_context.read_route_operations`, `sw_cam_compound_step_probe.read_three_step_profile` and the existing collection decoder. ABI preflight checks the exact five compound/setup getters against local declared metadata, without COM calls.

## Saved operation parameter observation

`solidworks_cam_inspect_current_saved_compound` adds explicit `observation="operation_parameters"`. Supply `parameters_authority_receipt_path`, its SHA-256, and exactly two `parameter_operation_native_ids` in Rough0 / Finish1 order, alongside the existing current saved source, owned PID/lifetime, feature/setup IDs and complete operation/path count pins.

The authority must be a completed checked Save from `selected_insert`, or a completed `selected_continue` with one retained Rough and one newly inserted Finish. An uncertain or partial mutation receipt cannot authorize this reader. The original writer authority loaders are unchanged.

The reader admits declared interfaces before bootstrap, compares the complete captured context with the saved authority, resolves each own operation and assigned tool, and repeats the full observation twice. It reuses existing levels, rough/finish allowance and tool/holder scalar readers. For completed continuation it also rereads the retained Rough's own NC values. A CAM event or failed getter stops the read without retries; returned raw/shape evidence is retained before event checks.

This mode performs no setters, GOP, GTP, Save, export or simulation. Results are raw observations; tool dimensions and holder scalars do not establish physical tool identity, units, coordinate frames, full profiles, clearances, reopening persistence or manufacturing acceptance. Existing header/count and three-step modes remain unchanged.
