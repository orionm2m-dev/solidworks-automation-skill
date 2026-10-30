# Exact volume-island probe

The read-only MCP tool `solidworks_cam_inspect_mill_volume_islands` checks one explicitly selected saved CAM feature through `ICWDoc3.GetCWObjectFromID(CW_OBJ_FEAT, id)`, verifies its returned ID, owner setup, suppression, volume/shape and island count, then uses only `ICWVolumeFeature.IGetIslands` followed by `ICWDispatchCollection` and `ICWIslandInfo`.

The default `include_contours=false` reads each island's start position and depth only. Two equal snapshots with clean event shutdown establish a representation/header observation. `islands_geometry_complete` remains false. This is not a full feature inventory or manufacturing qualification.

With explicit `include_contours=true`, the existing bounded typed segment-chain decoder reads top, bottom and wall contours. Missing contours remain unavailable, never fabricated. Face pointer arrays and profile-sketch setters are not used. There is no alternate-interface fallback.

Each getter and QI retains exact process/path/document-save-state, event and source-file metadata guards. Saved-file SHA and complete document identity are checked at capture boundaries. The budget is 2048 getter/QI calls per snapshot. Partial diagnostics are persisted at island/contour boundaries; a unique receipt is never reused. The operation does not save, recognize features, generate operations or generate toolpaths.

The volume-interface contract is confirmed by the installed CAMWorks type library 25.0. The available older CHM does not contain its IGetIslands page. Island scalar and contour getter contracts are additionally documented in CHM. Native support for the selected feature remains unqualified until this exact probe succeeds.
