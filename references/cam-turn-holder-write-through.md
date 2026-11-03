# Copy-only TURN holder write-through qualification

`solidworks_cam_qualify_turn_holder_write_through` is a separate, experimental prepare/probe command. It tests whether a single documented `ShankLength` property put through a retained operation-owned holder is visible through fresh owner and toolcrib getters. It does not authorize or change the ordinary `solidworks_cam_configure_turn_holder_dimensions` identity policy.

The native getter returns an `IDispatch` holder and the current type library declares the length getter/putter. The available primary API documentation does not specify whether repeated getters return live views or detached copies, or document a required TURN-holder commit. Different canonical `IUnknown` values establish different COM identities, not different vendor backing storage. Toolcrib save methods are not used as undocumented commits: they concern the tool database.

The request supplies one isolated, clean saved copy, its source path and matching SHA-256, at least two protected original files including that source, the exact process lifetime, selected operation/type/native ID, tool native ID, holder catalogue ID, expected current length and proposed length. The source and target must be distinct file identities. The two lengths must be finite, positive and different. Values are native-unit numbers; their physical unit interpretation is not qualified by this command.

`prepare` performs no write and returns a digest and all affected operation references. `probe` requires that exact digest, all and only those references, and a fresh absolute JSON receipt. A generated operation sharing the selected tool blocks the put. The request exposes no other holder field, assignment, database, save, retry or rollback option.

The probe permits observed operation-owned versus selected-crib canonical inequality only within this separate copy qualification. It still rejects missing selected crib holders, different own/crib scalars, wrong operation/tool identities, and a known shared canonical holder with another tool ID. Equal catalogue IDs are recorded and do not prove storage independence. Original holder and crib references remain alive throughout the call.

Before dispatch, a durable once marker binds the copy file identity and tool. The ordinary writer and probe use the same marker namespace, preventing cross-command replay. The pending receipt is written before the only property put. Source hashes, file identity, process lifetime, active document, event subscription and selected own tool binding are checked around the native call. A pending call or incomplete receipt never authorizes repetition.

Readback covers the retained own holder, every retained crib holder, a fresh selected-own profile and the whole bounded fresh toolcrib/operation/feature snapshot. Only selected `ShankLength` and a strictly Boolean document save flag may change. Tool display text and all other collected scalars must remain exact. Known aliases are blocked before dispatch; unexpected storage coupling stops after the single put without retry or rollback.

A successful result is `review_required` with `write_through_outcome=observed_in_fresh_owner_and_crib` and `owner_write_through_verified=true`. This means RAM readback for this request only. `not_persisted_to_observed_owner` means fresh owner and crib still report the old value, after checking that collected fresh and retained fields have no unexpected coupling. The enclosing status is still `uncertain`, not a safe retry. Mixed views, unexpected changes, events, native exceptions or incomplete receipts report `uncertain` and stop.

The command never saves, reopens, generates operations or paths, assigns a tool, or modifies TechDB. Persistence, physical assembly, units, complete storage independence, all uncollected holder sharing, CL bytes, full NC parameters, geometry and production suitability remain unqualified. A separate reviewed Save/reopen and applicable path verification are required before persistence or machining can be claimed.

Synthetic tests do not establish native behavior:

```powershell
python -m pytest tests/test_sw_cam_turn_holder_dimensions.py tests/test_sw_cam_turn_holder_write_through.py tests/test_mcp_cam_turn_holder_dimensions.py tests/test_mcp_cam_turn_holder_write_through.py -q
```

## Native qualification

On one isolated saved qualification copy, a single `ShankLength` put changed the raw value from 250 to 200. The retained own holder, fresh own holder and selected crib holder all reported 200; an unrelated tool with the same holder catalogue ID retained 250. The remaining collected scalars stayed unchanged and zero CAM messages were observed. The document `needs_save` flag remained false, so that flag did not indicate the CAM change.

A separate explicit Save, close and reopen was followed by a selected-own-holder read of 200. This establishes persistence of that selected scalar for this case. The complete toolcrib was not reread after reopening, so persistence of all unrelated holder values and complete storage independence remain unverified. Native units, physical assembly, clearances, machining and production suitability remain unqualified. The ordinary holder writer's canonical-identity policy is unchanged.
