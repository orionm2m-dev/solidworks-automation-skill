# Current pocket pair retained read

The versioned `sw_cam_current_pocket_pair_retained.capture_pair` helper reads one explicit ordered Rough/Contour pair. It accepts a genuine previously admitted `context`, an exact `{inventory, parameters}` snapshot, and an explicit generated-record map. Only the first Rough can have one positive generated record count; the second Contour must remain ungenerated. Native identities are data, never project constants.

The helper reuses `sw_cam_pocket_definition_capture_v2.capture` before and after the parameter batch and `sw_cam_current_pocket_generate_v2.read_pair` unchanged. Existing body/tree/circle, feature/setup, configuration, full inventory, and exact parameter comparisons remain in force. All admitted evidence pins are preserved with the explicit 128-pin bound. The caller must pin this helper and its retained-read parent in addition to the existing complete authority chain.

`RetainedPairReadBatch` reuses the fixed typed and plane getters of the current pair reader. Each getter/QI and binding getter checks events before and after. Only owners and native arguments belonging to the retained document graph are admitted. Global CAM document reacquisition and every mutation dispatch are forbidden. A failed, invalid, or still-open batch cannot produce an accepted result.

The observation schedule differs from the ordinary guard: full content hashes, process lifetime, active document, and retained binding are checked at complete boundaries. Per-getter global document and file metadata checks are not performed. This is explicitly non-atomic, does not exclude transient external A-to-B-to-A excursions, and provides no file write lease. The implementation does not modify any setter/GTP/Save/export guard.

The complete input and output parameter schemas are unchanged. The returned value becomes usable only after the second full capture, exact parameter comparison, final source/runtime/event checks, and successful completion. Partial diagnostics never authorize a mutation.

The historical native MILL reader already has 122 fixed typed getter slots, but its native qualification stopped at a missing interface while an old host was observed. It is a possible later transport optimization; it does not replace the full body/sketch/frame checks, and it was not loaded during this work.

Qualification sequence: admit the actual terminal generated-pair authority, perform one separate read-only native comparison, record full equality and per-phase counters/times, and only then consider using the provider in a future mutation flow. Offline parity is not native compatibility, physical cutting, or production qualification.

Tests require `SWMCP_RUNTIME_ROOT` pointing to the installed runtime. They reuse the existing fixed synthetic MILL fixture and execute the unchanged Python payload readers through both guard schedules. No application is connected.

Native qualification diagnostics separately retain `timing_seconds.before_definition`, `timing_seconds.parameters`, and `timing_seconds.after_definition`, including the duration of a failed phase. These measurements do not relax either full capture. A later prebound inventory extraction is only an assessment until these phase timings justify it.
