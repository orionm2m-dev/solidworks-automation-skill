# Current Finish modes and leads (pilot)

`solidworks_cam_read_current_finish_context` reads one explicit Finish operation (type1) in a clean saved MILL part after a completed generated-circular revision. It does not configure, generate, save, simulate or export.

A pinned completed-revision receipt and consumed marker are revalidated by the existing pure completed-revision binder, including actual setter/GTP/Save outcomes, saved source transition, recipe deltas, generated native mapping and every protected complete CL stream. The producer's generated Rough ID is separate from the requested Finish ID. The requested Finish feature and tool IDs must match the bound saved snapshot.

Two matching current operation tables protect order, operation types, suppression, assigned tool IDs, generated flags and record counts. The selected Finish reads exact DOUBLE/VARIANT_BOOL first-depth, maximum-depth and side-cut pairs, preserving the value-before-percent order. Lead-in and lead-out geometry uses the established feature-aware getters and strict pair/triple decoding. Gouge check, single-depth, tool-radius contribution, apply-to-all and depth-process settings are observed explicitly. Spindle, XY feed, feed method, link-to-tool, lock, absolute/percentage Z and lead feeds are kept with their native modes.

No inactive percentage setting is substituted for an absolute feed. Native units, valid machining approach, gouge prevention, cutting conditions and production release are not inferred from settings. The selected modes and flags are observations, not a pass/fail judgement about the machining recipe.

The bound is1536 getter/QI calls over at most32 operations and one explicit Finish. Exact PID/lifetime, active clean source, evidence hashes, runtime and CAM events are checked around both captures and cleanup. Failed readback or event/runtime drift revokes verification without mutating the document. Old receipts and source files remain immutable. No UI control or automatic retry is used.

Install the two already reviewed pure circular-WIP binding modules if absent; the WIP exporter/endpoint is not needed for this read-only tool. The reader remains pilot. A completed modes-only native case is recorded below; full lead-object observation and general native coverage are not qualified by it.


## Bounded modes and NC read after unavailable lead objects

`read_scope="modes_nc_only"` excludes `IGetLeadin`, `IGetLeadout` and the `ICWLeadInOut` interface. It reads the same exact current operation table, depth/side value-mode pairs, Finish flags, NC mode/link, and NC lead-in feed scalar. Lead geometry remains `not_observed`; no default geometry or gouge acceptance is inferred.

This scope requires `prior_read_receipt_path` and `prior_read_receipt_sha256` for the finished read-only failure at `read_lead_details` with HRESULT `0x80040202`, no mutation/events, and the same exact saved authority, PID lifetime, target and tool. The earlier failure is not reclassified, replayed, or edited. A fresh output receipt is required.

Full reads now persist completed inventory, paired values, Finish scope and NC groups before requesting lead objects. Partial groups remain unverified if the whole read fails. The original failed read did not persist its pair values; they cannot be reconstructed from call count and must be observed in the bounded read.

Inherited public request fields still apply, including mandatory `addin_clsid`. Validate a real request against the installed parent schema plus the staged child schema before dispatch; a permissive test double does not qualify the full request contract.

## Observed modes-only native case

The bounded modes/NC request completed 908 native reads with two identical inventories and targeted groups, no mutation or CAM events, clean subscription cleanup and unchanged saved source. The saved route retained 26 operations and 19 generated paths with 83563 records. The explicit Finish remained ungenerated.

Observed first/max-depth and side-cut pairs were 1/1/10 with their native boolean flags false. The NC observation retained spindle 200, XY 500, LinkToTool true, absolute-mode lead value 2 and Z value 2 with flag false. The separate stored lead-in percentage 30 does not replace the absolute lead value. Physical units, active cutting conditions and controller compensation are not qualified by this observation.

Lead geometry was not requested in this scope and remains not_observed. A complete modes-only capture is not a complete full-scope capture. The original full-read failure remains immutable and is not reclassified as success.
