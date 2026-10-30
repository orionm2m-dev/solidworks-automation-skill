# Exact PROFILE header probe

`solidworks_cam_inspect_mill_profile_headers` reads one exact saved feature through the installed vendor `ICWProfileFeature` interface. It verifies the selected process, saved-file SHA, feature ID and owner setup, suppression, volume/shape and island count before reading `GetSketchCount`, `GetSketchNameList` and both end conditions.

The probe makes no indexed calls. `include_contours` defaults to false; true is rejected before native calls until the indexing behavior is separately qualified. This limitation is temporary qualification status, not a claim that the API cannot read contours.

Sketch names preserve their observed Python representation. Native VARIANT type is not inferred from the marshaller's Python type. Scalar strings are not split as CSV. Flat string lists retain their observed length and whether it matches the separately read sketch count; that comparison does not establish a documented relation between the two. None is retained without claiming whether native VT_NULL or VT_EMPTY produced it.

Each end condition preserves all four declared outputs: native depth, integer type, nullable name and Boolean reversal flag. Native units and physical interpretation remain unqualified.

Two equal guarded snapshots and clean event shutdown establish only raw profile-header readback. `profile_geometry_complete`, `full_inventory_verified` and `production_qualified` remain false. Every getter/QI keeps process, document-path, dirty-state, event and source-file metadata guards. The budget is 128 calls per snapshot. No recognition, setters, saves, generation, face arrays, alternate interfaces or fallback are used.

The additional profile getters are confirmed in installed CAMWorks typelib 25.0. The older extracted CHM does not document these added methods. Native behavior for this particular feature still requires the dedicated probe run.
