# Exact hole metadata probe

This read-only tool reads at most five explicitly selected CAM features from a pinned, completed diagnostic inventory. It is a permanent MCP operation; the staging package does not change runtime or CAD.

Supported metadata routes:

- Type 11: ICWMultiStepFeature — number of steps, start position and overall depth. No indexed step method is called.
- Type 1: ICWMSHoleFeat — diameter, depth, start position, tip angle and nullable thread metadata.
- Type 9: ICWMSHoleCtrSunkFeat — main and sink diameters, depth, start position, angles and nullable thread metadata.
- Axis and exact ownership/classification come from the existing ICWFeature / ICWMillFeature getters.
- An observed pattern is enumerated through ICWPatternFeature.IGetEnumChildFeatures. Every child retains its own ID, owner, position, classification and parameters. A group name is never used as proof of a pattern.

The input inventory is SHA-pinned, current-PID-bound, clean, diagnostic-only and contains two equivalent snapshots. Its earlier incomplete geometry is not promoted. The tool checks source and anchor file metadata plus event transport around every getter/QI; exact PID/path/dirty state are checked at capture, feature and child boundaries. Both files are hashed at capture boundaries. Two independent metadata snapshots and clean event cleanup are required.

Successful readback proves repeated metadata observation only. Units, coordinate frame, step-index convention, full geometry, saved-process rebind, toolpath quality and manufacturing suitability remain unverified. Null values are retained as observations. Bounds sentinels are neither read nor substituted as physical dimensions.

Install only after native calls end:

1. Add scripts/sw_cam_mill_hole_metadata.py.
2. Apply the five IID additions from merge/sw_cam_comtypes.patch after confirming the bridge baseline.
3. Add merge/imports.py (Annotated), merge/SolidWorksCamMillHoleMetadataInput.py and merge/solidworks_cam_inspect_mill_hole_metadata.py to the current server. Do not replace the server with the staging baseline.
4. Run the bounded probe on the explicit saved request after current PID, source SHA and R13 SHA checks. No source edits during execution.

Synthetic tests: 59 passed. Actual R13 anchor loader passed with native_called=false. Native behavior of the new hole parameter getters has not yet been qualified.
