# Saved wall lead propagation

The `solidworks_cam_apply_wall_leads_to_all` tool applies a reviewed, pinned propagation recipe to an existing finish operation. It enables propagation, reapplies eight recorded entry and exit values, and calls selected toolpath generation once. Gouge checking remains enabled. It does not create or replace features, tools or operations.

The operation requires an owned process, exact saved source, completed diagnostic receipt and reviewed plan. A persistent marker prevents replay under a different output filename. Each write is read back. A completed generation call is insufficient: the generated flags and nonempty toolpath record counts must agree before saving.

## Outcomes

- `saved_generated_review_required`: an actual selected path was observed, saved and read back. Cutter, holder, remaining stock and manufacturing review are still required.
- `no_toolpath_no_save`: all requested settings were observed but no path was produced. The source file remains unchanged; intentional settings may remain unsaved in memory. Preserve them with an explicit save-only continuation before switching documents. Do not replay this request.
- `uncertain`: retain the receipt and reconcile the observed state before any new mutation.

## Qualification

The initial native qualification on 2026-11-01 confirmed all nine writes and the empty-result branch, including no save and no automatic retry. It did not qualify successful path generation for the target geometry. Portable contract tests cover the successful branch and rejection paths; those tests are not a native machining result.

The associated diagnostic reader compares selected finish definitions without modifying them. Raw numeric compensation modes remain raw unless their exact enum contract is independently established. A smaller lead arc than cutter radius alone does not establish the cause of an empty contour result.
