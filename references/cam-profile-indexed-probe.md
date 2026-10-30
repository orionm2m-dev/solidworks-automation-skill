# Explicit PROFILE index/name probe

`solidworks_cam_inspect_mill_profile_indexed` takes an explicit `index_mapping` of `{native_index, expected_sketch_name}` entries and a completed PROFILE headers receipt pinned by SHA-256. It never chooses an alternative index automatically.

The receipt must describe the same exact process, saved source, clean document and selected feature context. Its two header snapshots and cleanup must have completed successfully. Every requested name must occur in its observed flat name list. Candidate native indices are unique, nonnegative and bounded by the pinned sketch count inclusively, allowing a separate explicit diagnostic request for either zero- or one-based candidates. Each name has exactly one candidate per request.

For each candidate, `GetSketchNameListAt(native_index)` must yield the exact expected string, directly or as a one-element string array. Its observed representation is retained. A mismatch or native error stops before the segment-chain call. A matching name permits exactly one `GetSegmentChain(native_index)`; its non-null result receives a single `ICWSegChain` query. The existing typed linked-list decoder then reads the declared chain count, next links and bounded curves. Null, unsupported interfaces, malformed geometry or count changes stop without a collection fallback or another index attempt.

Two equal complete snapshots establish only the requested name/index correspondence and raw chain readback in this saved context. Sketch roles remain unknown: six sketches and five islands do not identify an outer contour. Universal indexing, nesting, physical dimensions, material removal, manufacturing fitness and release remain unqualified.

Guards use a fixed read-only policy: event health and pinned source/receipt file metadata before and after every getter/QI; exact PID and complete active-document identity before and after each indexed chain list, each actual linked chain, and each header/capture phase. Saved source SHA and receipt SHA are rechecked at capture boundaries and cleanup. The ordinary read handles are not exclusive locks. Changes within a chain are rejected at its next boundary and never authorize a completed result. The read budget is 4096 getter/QI calls per snapshot.

The linked-chain contract is confirmed by installed vendor typelib 25.0 and the available ICWSegChain documentation. Index base and geometric-role mapping are not documented by those sources and are deliberately treated as runtime observations. The default headers-only tool is unchanged.
