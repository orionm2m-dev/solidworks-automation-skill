# Existing TURN boring holder dimensions

`solidworks_cam_configure_turn_holder_dimensions` prepares or applies a bounded change to an existing diamond insert's boring-bar holder. Supported native properties are `BoringBarDiameter`, `ShankLength`, and `LeadAngle`. It does not rebind or create a tool, change the catalogue, generate operations or paths, or save the model. Only rough-bore and finish-bore operations are accepted.

The request identifies the owned process and creation time, isolated saved copy and its exact hash, protected original files, operation index/type/native ID, tool native ID, and holder catalogue ID. Prepare reads the full bounded shared-tool snapshot and current tool crib under message monitoring, then binds the exact desired values into `state_sha256`. Apply requires that digest, a fresh JSON receipt, and exactly all `allowed_affected_operations` reported by prepare. Any generated operation sharing the selected tool blocks writes. No-change recipes are not dispatched.

The selected operation's own tool, station tool and complete usage list must agree. The current holder is compared through canonical `IUnknown` identity with insert holders in the bounded crib. If a different tool ID shares that COM object, the operation stops before writing. Equal holder catalogue IDs alone are recorded as an unresolved alias condition; they are not treated as proof of shared or independent storage. Non-insert tool categories are not probed through an unsupported holder interface. These limits remain explicit in the result.

A persistent marker binds the copy's file identity and selected tool independently of the receipt name. Before each property write the module checks the source, ownership, own tool and retained holder identity. It records attempted/returned evidence, verifies the scalar, and reads the complete collected state again. Only requested selected-holder values, the selected derived display text and a strict Boolean document save flag may change. Any other change, message, exception or incomplete receipt stops later writes without retry or rollback. The original holder references stay alive throughout the transaction.

Unrequested coupled changes also stop the transaction. In particular, the implementation does not assume that `GetHolderThickness` is an alias of `BoringBarDiameter`. Successful readback confirms only collected scalar definitions. It does not qualify native units, vendor backing-storage independence, complete holder sharing, physical assembly, cutting clearances, full NC, CL bytes or persistence. Catalogue angles must not be mapped to `LeadAngle` without separate evidence. Physical fit and deliberate Save/reopen remain separate reviews.

Synthetic verification:

```powershell
python -m pytest tests/test_sw_cam_turn_holder_dimensions.py tests/test_mcp_cam_turn_holder_dimensions.py -q
```

## Identity diagnostics

Each snapshot retains the already read selected holder profile and toolcrib rows even when an identity guard rejects the request. `holder_inventory_stage` distinguishes collection, canonical identity guards and a completed holder snapshot. The identity observation separately reports whether the selected tool has a crib holder and whether its canonical `IUnknown` equals the retained own holder. Missing holders report an unknown comparison rather than a false identity.

Group numbers are local to one snapshot and are not native holder IDs, persistent IDs or pointer addresses. The corresponding COM references remain retained during comparison. Equal scalar values or catalogue IDs do not establish COM identity or independent vendor storage. A diagnostic failure never authorizes a setter, retry, rollback or save.

## Native preparation outcome

A native diagnostic preparation found the selected tool and its holder in the crib. The operation-owned and crib-owned holder views had equal reported dimensions but different canonical COM identities. The ordinary writer correctly stopped before any setter. This observation does not distinguish copied objects from live views with separate identities, and does not qualify write-through behavior. The installed core and wrapper suite passed 66 tests.
