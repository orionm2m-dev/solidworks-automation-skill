# Reconcile appended TURN recipe definitions

`solidworks_cam_reconcile_turn_feature_recipe` is read-only. It consumes an exact completed uncertain recipe receipt where Attribute and feature GOP both returned, the original strict verifier stopped at the replacement-position check, and the new operation block was appended after the protected operations.

The original receipt and once marker stay immutable. Explicit parent SHA, reviewed after-state SHA, exact appended operation order, process creation time, copy/source binding, and definitions-only acknowledgment are required. The tool reruns every remaining delta guard, validates the original marker/prepared digest, and compares two current bounded metadata snapshots with the stored after-state. It never repeats Attribute/GOP, assigns tools, generates toolpaths, saves, or reorders operations.

Success produces a fresh RAM-definitions receipt with `route_order_qualified=false`. It does not accept machining order after a cutoff operation, full NC settings, complete tool geometry, CL coordinates, persistence, or production. A separate CL comparison can establish protected coordinate bytes. Save/reopen and any explicitly authorized reorder remain separate actions.

The internal append policy is available only as an explicit verifier argument; the public mutation path retains its strict replacement-position policy.

```powershell
python -m pytest tests/test_sw_cam_turn_recipe_reconcile.py tests/test_mcp_cam_turn_recipe_reconcile.py tests/test_sw_cam_turn_feature_regenerate.py -q
```

A native qualification confirmed two exact current snapshots of an appended four-operation replacement block. A separate CL export preserved all seven retained operation streams byte-for-byte. Explicit Save/reopen preserved the recorded definitions and complete CL. These observations qualify that sequence only; they do not broaden the tool to arbitrary uncertain or interrupted mutations.
