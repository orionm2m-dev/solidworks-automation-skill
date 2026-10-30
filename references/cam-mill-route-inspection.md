# Assigned milling tool inspection

`solidworks_cam_inspect_mill_route_tool` observes an assigned milling tool in a bounded route containing multiple features and operation setups. It reads native getters through the existing typed CAM bridge. It does not generate operations or toolpaths, assign a tool, alter stock, update TechDB, or save the model.

The entry point is a pilot capability. Synthetic tests validate its contracts and failure handling; native qualification of this complete wrapper remains outstanding.

## Required evidence

Pass the exact managed process, saved part path and SHA-256, a pinned completed zero-operation feature inventory, and exact selected feature ID, operation ID and milling-operation type. The target must be a disposable qualification copy. A prior inventory binds all feature geometry, setup frames, stock, material, recognition options and SolidWorks geometry. In-memory generated operations may differ from that inventory; the saved source cannot differ.

If the inventory was captured after a process restart, it must carry explicit, verified current-process recovery evidence. Passing the old receipt directly is not accepted. The route reader forwards the saved-process recovery opt-in only from that verified inventory and checks every pinned evidence file again during capture.

## Observed data

Two guarded captures enumerate up to eight setups, 64 features and 32 operations. All sibling operations retain their identities, feature links, suppression and generated-path flags, record counts, and generic assigned-tool identities and dimensions. Shared tools are permitted; collisions between different object kinds are rejected.

The selected, unsuppressed operation must link solely to the exact selected feature. Its assigned tool and holder use the existing complete tool-geometry decoder and the reviewed set of 30 primary getters. Missing optional profile data remains explicit; an incomplete profile is never reported as complete. No cutter-location records are read.

The result preserves partial diagnostics on failure and requires identical captures, stable source files, unchanged document state, and clean event-session shutdown. A unique receipt is created exclusively. Failure does not replay any native operation.

## Interpretation limits

Native dimensions retain their native-unit labels until a separate unit check is complete. Reading assigned-tool geometry does not prove that a physical cutter or holder matches it. Holder clearance, incoming workpiece, cutting depth, feed/speed suitability, material removal, collision clearance and manufacturing release remain unqualified. The receipt therefore keeps `apply_eligible`, `may_continue` and `production_qualified` false even after a successful read.

This extension does not implement multi-feature GOP, tool assignment or GTP. The existing public feature-inventory tool keeps its zero-operation contract; only the internal capture helper accepts the bounded operation-reader callback.

## Implementation

- `scripts/sw_cam_mill_route_tool.py`: guarded public read-only operation.
- `scripts/sw_cam_mill_route_context.py`: bounded multi-feature route observation.
- `scripts/sw_cam_mill_route_evidence.py`: pinned completed-inventory evidence.
- `scripts/sw_cam_mill_tool_geometry.py`: reusable tool and holder decoder.
- `scripts/sw_cam_mill_inventory.py`: existing inventory capture with an internal optional operation reader.
- `mcp-server/server.py`: strict MCP schema and selected-process locked dispatch.

No project-specific paths or model names are required by the reusable modules.
