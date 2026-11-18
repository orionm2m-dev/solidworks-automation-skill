# Generated circular rough revision (pilot)

`solidworks_cam_reconfigure_generated_circular` changes one explicitly selected, already generated circular Rough operation in a current saved MILL part. It is a native pilot; successful tests or interface availability do not qualify a machining process.

The request pins a completed current NC-reader receipt, its saved-state reconciliation, the source file and a separate explicit recipe. The historical configuration and generated receipts remain immutable. Current process ID, process lifetime, active document, source SHA, runtime and CAM message boundaries are checked separately.

The bounded recipe permits exactly these fields: operation-level LinkToTool=false, spindle, XY feed, absolute lead-in feed; equal first and subsequent depth, spiral pitch. The shared nominal tool, tool assignment, Z feed, planes, compensation, geometry, other operations and all protected CL streams must remain unchanged. Physical serial-tool assignment and production release are separate work.

The implementation observes retained cached path state. Either a retained generated flag or explicit invalidation after setters is allowed only for the selected operation; neither proves a fresh toolpath. It invokes one explicitly selected GTP, verifies the complete configured state and all other operations, saves once, and exports one CL file. The old and new generated inventories must match in order, with complete native-count binding and exact full signatures for every other CL block.

Every setter, GTP, Save and CL action has a durable pending/returned record. A failed or uncertain outcome consumes the attempt marker; the tool does not retry setters, regeneration, saving or export automatically. Post-Save failures preserve actual Save return/source facts while revoking whole-workflow verification. Preserve the old CL and all original receipts for independent reconciliation.

Seven full captures are planned: before, configured, generated, saved, confirm_saved, pre-export and post-export. The before-Save state is explicitly the immediately preceding genuine generated capture, not a second native observation. Each setter also has immediate scalar readback. Final CL geometry, feed interpretation, cutter containment, stock/fixture/holder clearance, cutting conditions and reopen persistence require their own evidence.

Installed typed metadata is checked before dispatch, including legacy zero-direction HRESULT setters and explicit IDispatch feature arguments. Only native application interfaces are used; no user-interface control is involved.

## Observed native case

A scoped saved case completed the bounded seven-field revision, one GTP, one Save and one CL export. The selected circular Rough changed from 11158 to 198 native records. All 18 other complete generated CL streams remained exact; the saved route retained 19 generated paths with 83563 records. The final saved source and returned primitive outcomes were independently bound to the completed receipt.

This confirms that recorded configuration/generation/save/export case, not general machining readiness. Continuous nominal containment was reviewed separately; unresolved coincident-arc turn semantics and complete removal coverage are not inferred from the reduced record count. No general reopen, serial-tool, holder, fixture, cutting-force or production qualification is granted. The capability remains pilot.

