# Interrupted existing-tool recovery

`solidworks_cam_recover_current_pocket_tool` accepts an immutable original
`CURRENT_POCKET_CREATE_ASSIGN_ONE_FLAT_TOOL_V1` partial receipt, its original
once journal, a terminal CLI timeout, and an observed executor-exit record.
All paths, process identities, source hashes and tool IDs come from request data.
The original raw evidence is never modified or promoted to a successful result.

The original factory, holder, thirteen fields and SetTool must have returned and
have complete validated readbacks. Pending or ambiguous actions are rejected.
The original full after-assignment observation is required. The current target,
process lifetime, CAD circle/body/tree, two operations, full candidate profile,
holder and protected assigned tools are freshly checked. An unexpected dirty
transition, any event or source drift stops recovery.

* If Save was never attempted (including exactly phase=before_capture), the
  same observed post-assignment dirty boolean is required. The existing
  save_current_baseline helper performs one native Save and full readback.
* If Save explicitly returned integer zero and observed changed bytes/model_saved
  were already durable, recovery requires a clean target and performs fresh
  paired reads only. It reconstructs a new current context with provenance to
  that original Save; it does not call Save again.

This first recovery variant requires the original completed pair-reader baseline.
Later mutation baselines and unknown native outcomes are deliberately rejected.
A separate once marker prevents repeating this recovery with a renamed report.
The reader uses existing Win32 process identity: a recycled PID is unrelated,
access-denied/unknown states block execution, and conhost is diagnostic only.

No tool creation, field/holder writes, SetTool, GOP or GTP is reachable. A new
terminal result can be consumed by the existing current-context loader. Physical
tool identity, units, cutting conditions and production remain unqualified.

This package was tested offline with synthetic backends and actual frozen
receipt admission. Native recovery has not been qualified by those tests.
