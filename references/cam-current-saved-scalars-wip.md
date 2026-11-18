# Current saved CAM scalars and WIP export (pilot)

These tools consume a strictly verified saved boundary from an interrupted circular-finish generation producer. They preserve the producer's original terminal status. Acceptance is limited to the exact producer scope, failure boundary, durable Save facts, marker and ancestry supported by the installed binder; it is not permission to accept an arbitrary uncertain receipt.

The shared binder is `sw_cam_current_saved_finish_read_authority.load_saved_boundary`. It checks the original receipt location and hash, saved source, process lifetime, configuration and creation history, consumed marker and implementation pins. A copied receipt at a different path does not replace an original-path authority. The binder is file-only; the endpoint separately verifies the live owned process and active clean saved part.

## Common request and execution rules

Both endpoints inherit `SolidWorksCamTargetInput`. Include the mandatory `addin_clsid` from an observed registered CAM installation, even though it is removed from the core request before dispatch. Supply the connected `process_id`, exact `expected_process_create_time`, absolute `expected_document_path`, `expected_source_sha256`, original `generation_receipt_path` and `generation_receipt_sha256`, and a fresh absolute `receipt_path`. Use `qualification_only=true` and `message_policy="vendor_default"`; unsaved-title targeting is not supported.

Populate identity and paths from current observations; no process, operation, document or installation constants are built into these instructions. Validate the complete request against the installed parent and child Pydantic schemas before submitting it. Testing only a child class or a permissive replacement base does not cover inherited required fields.

Call `solidworks_connect` for the owned process in the same MCP server session. The endpoints do not launch a new application or choose a process. Keep runtime files unchanged while a call is active. A private one-use prepared bundle validates the expensive history once; admission rechecks immutable pins, outputs and runtime instead of repeating the whole loader. This is not a persistent authority cache and never skips a fresh source hash.

Use `scripts/mcp_request.py` with a reviewed request file and a fresh output file. A request file has the form `{"requests":[{"name":"tool_name","arguments":{"params":{...}}}]}`. The standard client preserves partial/error output and does not automatically replay a failed tool call. A new output filename does not authorize repetition of a consumed native WIP export.

## Bounded generated floor/wall scalar read

Endpoint: `solidworks_cam_read_current_floor_wall_scalars`.

In addition to common fields, provide `floor_operation_native_id` and `wall_operation_native_id`. The saved selected-pair observation must own the requested generated Rough operation; the verified saved boundary must own the requested generated Finish. Feature, setup, tool, order and positive native record counts come from the pinned saved state. IDs are not inferred from labels, filenames or record counts.

The payload consists of two repeated `ICWOperation` feed/rapid/total length triples per selected operation (12 scalar getter calls) and one `ICWNCParam3.FeedPlaneType`, `FeedPlaneDistance` and `ICWNCParam4.GetUseCurrentMachiningDepthForFeedPlane` read per operation (6 scalar getter calls). Selected target and setup membership bindings are observed before and after. Additional binding getters and interface queries count toward a bounded read budget. The remaining saved route is historical pinned evidence, not a fresh complete native inventory.

The receipt records `before`, `after`, `scalars.first`, `scalars.second` and `scalars.feed_planes`. Verification requires stable repeated triples, strict finite types, unchanged source/runtime/owner, clean CAM event cleanup and completed selected bindings. No setter, GTP, GOP, Save, stock read, WIP export or CL export is called. An error leaves diagnostic groups unverified and is not retried.

Native length units and feed-plane enum meanings remain unqualified observations. Do not infer a complete circle merely from coincident endpoints. A total length can be insufficient to distinguish several ambiguous arcs; independent geometric or WIP evidence may be required. A scalar result does not qualify entry clearance, feeds, tools, holder/fixture clearance or machining.

## One WIP export at the verified saved boundary

Endpoint: `solidworks_cam_export_current_saved_finish_wip`.

Additional fields are absolute `project_root` and `output_dir`, the exact installed exporter `module_sha256`, `declared_empty_operation_ids`, and `acknowledge_machine_scope=true`. Empty operation IDs are explicit strict positive integers obtained from the saved route. Raw empty toolpath collections, including a zero-count collection, remain unchanged and are not silently converted into generated paths or cleaned up.

The scope is the complete machine and all setups, not just the selected Finish. The tool reuses `ICWMachine5.CreateSTLOfWIPs2(output_dir, "wip.stl", "", 0, 0)` once. It requires strict Boolean `True`, frozen nonempty STL outputs, matching complete native captures around the export, preserved plane observations, clean source and event cleanup, and a receipt-consumed marker. It performs no generation, model Save, parameter write, simulation control or UI action.

The WIP-specific guard validates the complete bounded pin union before dispatch. Larger unions are validated in bounded chunks, retaining all unique rows; they are not truncated. Inherited phase boundaries still hash the complete union. Conflicts, bad metadata, source/runtime drift or constructor-preflight failures stop before native export. Existing historical guards remain unchanged.

Use a fresh output directory and receipt. If a native call was attempted or its result is uncertain, preserve the marker and raw outcome; do not clear it, rename the output to evade it, or retry automatically. A failure before export is distinct from a failed export. Cleanup failure revokes verification while retaining the actual native return and file facts.

A returned mesh does not prove cache recomputation, physical material removal, coordinate-frame semantics, tessellation accuracy, nominal geometry, collision freedom or production readiness. Those require separate, source-bound reviews. A qualified export from a raw-stock branch does not establish a production turning-to-milling WIP transfer or a regrip frame.

## Qualification and regression coverage

The tools remain pilot. A successful narrow native scalar case establishes the exact selected-read path and cleanup for that saved source only. A successful WIP export must have its own completed receipt and independent output checks; successful scalar reads, an installed endpoint or passing mocked tests are not a WIP qualification.

Portable offline tests cover strict scalar types and repeated values, selected identity drift, no replay, one-use prepared admission, current request inheritance, raw empty-row preservation, WIP return types and cleanup, and complete pin-union validation. They use synthetic IDs and temporary files and do not connect to CAD. See the matching `test_current_floor_wall_scalars`, `test_current_saved_cam_request_schemas`, `test_current_route_wip_comparison`, `test_current_saved_finish_wip` and `test_wip_complete_dispatch_guard` test modules.
