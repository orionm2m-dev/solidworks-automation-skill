# Existing TURN boring holder dimensions

`solidworks_cam_configure_turn_holder_dimensions` prepares or applies a bounded change to an existing diamond insert's boring-bar holder. Supported native properties are `BoringBarDiameter`, `ShankLength`, and `LeadAngle`. It does not rebind or create a tool, change the catalogue, generate operations or paths, or save the model. Only rough-bore and finish-bore operations are accepted.

The request identifies the owned process and creation time, isolated saved copy and its exact hash, protected original files, operation index/type/native ID, tool native ID, and holder catalogue ID. Prepare reads the full bounded shared-tool snapshot and current tool crib under message monitoring, then binds the exact desired values into `state_sha256`. Apply requires that digest, a fresh JSON receipt, and exactly all `allowed_affected_operations` reported by prepare. Any generated operation sharing the selected tool blocks writes. No-change recipes are not dispatched.

The selected operation's own tool, station tool and complete usage list must agree by native document IDs. Two complete captures must agree during prepare and apply. Each capture repeats the operation-owned tool traversal, checks every operation/tool ID and linked feature list, and compares all affected own-holder dimensions with the selected holder and current crib. Different canonical `IUnknown` identities for the same native tool are retained as diagnostics; they do not independently reject this logical binding. A positive same-COM holder alias across different tool IDs still blocks writes. Equal catalogue IDs alone do not prove shared or independent storage. Non-insert tool categories are not queried through an unsupported holder interface.

A persistent marker binds the copy's file identity and selected tool independently of the receipt name. Before each property write the module checks the source and ownership, then requires a fresh complete logical capture to match the preceding state. It dispatches through the freshly resolved selected operation's typed holder. Only requested holder scalar values in every affected own view and the crib, derived display text for that tool, and a strict Boolean document save flag may change. A setter exception never triggers another setter: when document and event guards remain valid, one guarded capture records the actual post-call state. The result remains uncertain and later writes stop. Event errors prevent further CAM reads. No automatic retry or rollback is performed.

Every supported own and crib holder capture includes raw shape, file path and file-unit fields. For custom shape, prepare requires an absolute STL path. Apply must preserve these fields exactly. `holder_file_fields_preserved` confirms those collected fields only; it does not compare external STL bytes or qualify regenerated contours, physical pose or clearances. Those remain separate reviews.

Complete and partial capture evidence is retained in the receipt before delta validation. A post-call runtime change preserves the returned evidence, revokes eligibility and readback flags, and updates only a matching receipt created by that invocation. Failed receipt updates are explicit; a new receipt name does not bypass the persistent once marker.

Unrequested coupled changes also stop the transaction. In particular, the implementation does not assume that `GetHolderThickness` is an alias of `BoringBarDiameter`. Successful readback confirms only collected scalar definitions. It does not qualify native units, vendor backing-storage independence, complete holder sharing, physical assembly, cutting clearances, full NC, CL bytes or persistence. Catalogue angles must not be mapped to `LeadAngle` without separate evidence. Physical fit and deliberate Save/reopen remain separate reviews.

Synthetic verification:

```powershell
python -m pytest tests/test_sw_cam_turn_holder_dimensions.py tests/test_mcp_cam_turn_holder_dimensions.py -q
```

## Identity diagnostics

Each snapshot retains the already read selected holder profile and toolcrib rows even when an identity guard rejects the request. `holder_inventory_stage` distinguishes collection, canonical identity guards and a completed holder snapshot. The identity observation separately reports whether the selected tool has a crib holder and whether its canonical `IUnknown` equals the retained own holder. Missing holders report an unknown comparison rather than a false identity.

Group numbers are local to one snapshot and are not native holder IDs, persistent IDs or pointer addresses. The corresponding COM references remain retained during comparison. Equal scalar values or catalogue IDs do not establish COM identity or independent vendor storage. A diagnostic failure never authorizes a setter, retry, rollback or save.

## Historical native preparation outcome

A native diagnostic preparation found the selected tool and its holder in the crib. The operation-owned and crib-owned holder views had equal reported dimensions but different canonical COM identities. The earlier ordinary writer stopped before any setter because it required canonical equality. This observation does not distinguish copied objects from live views with separate identities, and does not qualify write-through behavior. The installed core and wrapper suite passed 66 tests.

## Logical-binding qualification scope

The logical-binding revision is a pilot verified with synthetic owner/crib, identity, unrelated-field, custom-file, partial-setter and wrapper-failure cases. The separate historical single-property write-through probe remains unchanged. A successful write-through observation on one property does not qualify a different property, physical assembly, native units, or the generalized writer on a live model. Native application and deliberate Save/reopen require their own evidence.

## Explicit completed-length to LeadAngle continuation

The optional `completed_length_probe` input is limited to one new `LeadAngle` setting after a completed successful single-property `ShankLength` write-through probe on the same file identity and native tool. Supply the prior marker and receipt absolute JSON paths plus their SHA-256 hashes (`marker_path`, `marker_sha256`, `receipt_path`, `receipt_sha256`). Both prepare and apply require the same explicit pins. Other fields, mixed recipes, uncertain or pending prior outcomes, and prior scopes other than the dedicated successful length probe are rejected. This is not a general repeat-editing or retry mechanism.

The reader checks the marker/receipt linkage, original prepared and final digests, exactly one returned and verified ShankLength setter, quiet cleanup, and the original recorded scalar deltas. Fresh complete owner/crib snapshots must still report the completed length, and every prior owner must retain its native operation/tool binding. Additional current consumers are admitted only through the existing complete affected-usage and ungenerated-operation guards. Historical process and saved-source pins are retained as evidence; the new request separately pins the current process and saved source.

The legacy marker and receipt are never removed, rewritten or consumed. A separate exclusive marker binds the file identity, native tool and LeadAngle field. Its key excludes saved-source hash, request digest, target angle and receipt name, so Save, a new desired angle, or another receipt cannot replay a claimed continuation. A failure after claiming that marker blocks further attempts even if no setter outcome can be established. The existing per-setter durable intent, full actual readback, partial-failure evidence and no-rollback behavior remain in force.

Known continuation refusals include fixed `reason_code` and human-readable `reason` fields. Arbitrary exception messages are not promoted into those diagnostics. A matching historical proof is only admission evidence; it does not qualify the new LeadAngle setter, external STL bytes, geometry, physical assembly, generation, Save or production. The continuation remains a software-tested pilot until separately observed natively.
