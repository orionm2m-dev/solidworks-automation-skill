# Axial CL metadata and positions

The observed generic MILL CL can declare a lower setup with `TLAXIS/0,0,-1` while its `GOTO` positions and `CIRCLE` normal remain in a local +Z frame. Treat these as separately declared data. Do not flip positions or tool-axis metadata to satisfy a reader, and do not apply the same transform twice.

The bounded reader accepts finite axial +Z or -Z tool metadata for the already supported local +Z, descending, CCW single-minor-arc helix. Start/end axis metadata must stay equal. Tilted metadata, changed axis, negative circle normal, upward motion, unsupported direction or hidden-turn assumptions remain rejected. The -Z case records its antiparallel relation and leaves physical/frame qualification false. Existing +Z result objects remain unchanged.

Use a separately verified native setup frame for geometry review. For the observed lower cardinal frame, local positions transform by R=diag(1,-1,-1) and its measured origin; the raw -Z tool metadata already agrees with the expected part direction and must not be transformed again. This is a scoped interpretation, not a universal export convention.

A rejected circle can leave an operation logically unclosed and cause the terminal FINI record to appear in its diagnostic count. Never compensate by subtracting one or changing expected native counts. Fix the exact parsing limitation, reparse the original saved bytes, and demand the same native record counts and complete old operation-stream signatures.

Software evidence:31 focused regression tests passed; the actual saved nineteen-block CL parsed with exact native counts and unchanged complete signatures for eighteen previous blocks. File-only reconciliation does not rewrite an uncertain native receipt or retry Save, export or GTP. Cutting conditions and production still require separate review.
