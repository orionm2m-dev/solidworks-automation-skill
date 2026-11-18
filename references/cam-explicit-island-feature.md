# One explicit pocket with four islands

`solidworks_cam_create_pocket_with_explicit_islands` is a bounded pilot. It consumes a completed saved four-sketch batch, the existing outer-circle creator receipt, and a separate successful zero-operation lifecycle Save. The current source, owned process lifetime, CAD/CAM configuration, setup and all five sketch names are pinned.

The endpoint calls the public `ICWSetup.CreateMillFeature2` once with automatic island detection disabled. It then calls `AddIslandToFeature` once per declared sketch. A strict Boolean true and island counts 0, 1, 2, 3, 4 are required. The same target's durable attempt marker prevents automatic replay after any uncertain or failed action.

Before dispatch, it reads the five CAD sketches and checks their model-coordinate geometry using the existing circle/signed mixed-profile readers. After creation it reads PROFILE headers and exact indexed names/chains through the existing supported route. The pure chain checker compares same-axis relative geometry with an explicitly supplied scoped numeric scale. It does not fit a world transform. Its reported curve lengths are derived from start/mid/end geometry, not independent native length getters; this does not establish universal angular sweep or extra-turn semantics.

Only an empty initialized CAM setup is admitted. Existing CAD solids, the pre-existing feature tree, setup and operation inventory remain protected. Any Attribute suffix must be declared exactly in the pinned plan before dispatch; unexpected suffixes stop the action. No generic permission to add native Attributes is implied.

The endpoint creates a definition only: no Save, GOP, GTP, import, explicit rebuild, tool change or machining approval. After successful definition readback, a separate existing lifecycle Save may preserve the one-feature/zero-operation state. Reopen persistence remains separate. The older autodetected-pocket authority must not be used to label this explicit producer; any later GOP admission must name this producer truthfully.

The caller supplies `feature_plan_path` and SHA for an exact object:
- `owner_setup_native_id`, `axis_native`, `origin_native`;
- `outer_sketch_name`, four `island_sketch_names`;
- `depth_native`, `expected_shape` (different from SubType);
- `expected_attribute_suffix` (normally an empty list).

The request also pins the batch, circle and lifecycle Save receipts, current part path/SHA, PID/lifetime, exact CAD/CAM configuration names, a fresh receipt path, and explicit definition-only qualification. The inherited CAM add-in CLSID is required.

Physical depth, stock, tool/holder clearance, world placement of CAM-local chains, feeds, full removal coverage and production machining remain unqualified. A named signed CAD sketch and matching local PROFILE shape are definition evidence; the resulting toolpath still needs independent geometry review.