# One current pocket tool definition and assignment

Pilot endpoint `solidworks_cam_create_assign_current_pocket_tool` consumes one immediate successful current-pair context. It binds current source/PID/lifetime, one feature, exactly two ungenerated Rough/Contour operations and the selected Rough ID. All project IDs, paths, catalogue identity and dimensional values are request/evidence data.

The operation reads the full pair and bounded local tool catalogue, checks same-diameter duplicate candidates, claims one durable target/source marker, calls the existing AddNewTool3 flat factory once, then uses the existing thirteen-property order and custom holder attachment. Every changed field has immediate readback. Existing full tool/shank/holder geometry validation must pass before the sole selected SetTool call. The unselected operation and original assigned tools/holders are protected. Selected automatic defaults are retained as raw observations; machining levels stay exact. No operation-parameter setter or GTP is exposed.

One existing Save primitive runs after all guarded source handles close. Raw return and new source SHA are recorded before post-Save checks. Complete inventory/parameter snapshots, full new tool profile and original tool profiles are compared again. Terminal current context is published only after clean events, cleanup, identity/source and runtime checks. Late failure keeps actual Save facts and is uncertain; no automatic retry, rollback, deletion or fallback is provided.

The cutter envelope is a verified native representation, not physical manufacturer/collet/spindle qualification. Numeric units, material cutting data, island association and machining acceptance remain unqualified. The first native execution is pending owner review.
