# WIP after a saved circular revision (pilot)

`solidworks_cam_export_reconfigured_circular_wip` accepts one completed
`GENERATED_CIRCULAR_RECONFIGURE_V1` receipt. It validates the actual post-Save
part, exact PID and process lifetime, consumed writer marker, recipe and writer
module, five complete captured states, seven setter outcomes, GTP/Save/CL
outcomes and complete unchanged CL streams for every other generated operation.
Operation IDs and native record counts come from the pinned receipt; no fixed
18- or 19-operation rule is used by the endpoint.

The endpoint reuses the owned circular read context and the existing
`ICWMachine5.CreateSTLOfWIPs2(folder, "wip.stl", "", 0, 0)` export. Its scope is
all WIP parts and setups. It calls no setter, GTP, Save, simulation control,
document-open, document-close or UI action. A consumed marker prevents replay.
The primitive return is recorded before dispatch-guard cleanup. Success requires
strict native `True`, nonempty frozen STL files, two identical complete captures,
clean unchanged source, event disconnection and runtime/owner checks after cleanup.

An uncertain source receipt, unresolved event, dirty document, source or pin drift
must stop before export. An interrupted export is not repeated automatically.
The output does not qualify cache freshness, mesh fidelity, frame, full-circle
semantics, machining, holder/fixture clearance or production. Whole-machine WIP
is distinct from later local geometry acceptance. The preserved seven lower
surfaces do not qualify the complete R25 upper geometry or its old toolpaths.

## Observed native export case

One scoped export from the completed corrected circular revision returned native
True, produced one frozen STL, and completed two matching current-state captures
with clean event cleanup and unchanged source. No setter, generation, Save or
simulation-control action was used. An earlier attempt failed before native
export because an immutable JSON pin lacked full file metadata; the repaired
lineage rereads that pin through the existing guard without weakening validation.

The capability remains pilot. This case verifies the one-export ownership and
file-output scope. It does not independently prove cache recomputation, the
general API coordinate frame, declared tessellation error, exact nominal cavity
diameter, fixture/holder clearance or production readiness. The local saved-mesh
review and its frame/facet addendum are separate evidence, not global acceptance.
