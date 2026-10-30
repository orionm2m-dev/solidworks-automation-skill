# Saved selected MILL plan tools

This permanent read-only endpoint reads assigned tools from a completed saved-plan receipt. It does not generate operations, save the model, assign a tool, create toolpaths or replay older receipts.

## Scope and reuse

- Pinned successful `MILL_SELECTED_PLAN_18_HEADERS_V1/save_checked` receipt, current process, exact part path and saved SHA.
- Existing `capture_selected_plan`: 18 feature headers, PROFILE metadata without contours, all generic sibling operations, stock and SolidWorks geometry fingerprints.
- Existing `read_selected_operation_tool_details` and full tool/holder decoder.
- Two identical compact captures and identical detail observations.
- Every user of the selected shared tool must be in the explicit ordered operation list.
- Feature owner and operation setup are distinct. In R18 these are 69 and 93.
- The saved receipt and STL stock bytes remain pinned throughout capture. Old receipt paths are retained as reported provenance and are not reopened.
- A known unsupported tool/holder detail remains partial. Stable partial observations may verify unchanged compact context; they do not set `tools_readback_verified` or `tool_geometry_read_complete`.
- Units, physical tool identity, holder clearance, full contours, incoming WIP and production remain unqualified.

## API

`solidworks_cam_inspect_saved_mill_plan_tools` consumes the pinned saved-plan receipt plus expected feature, ordered operation IDs, operation setup and shared tool ID. Existing qualification-copy and exact-source fields are required. It writes a unique receipt.

For a later setter, retain `anchor`, `state_sha256`, `tool_details_sha256`, `before/after` and `before_tool_details/after_tool_details`. The selected-tools reader grants no mutation authorization and contains no setter.

## Installation

Add the two new scripts and the test file. Merge the schema and tool snippets into the current server after its existing definitions and before the **last** main guard. The full staged server is a tested merge reference; replace it only if the installed server still matches the recorded base SHA. No existing full-inventory reader or GOP/save implementation changes.

## Validation

52 new synthetic tests pass, including actual merged-server import without serving or connecting, strict schema inputs, malformed saved evidence, source/PID/tool/member/file changes, neighbor changes, stable partial details, event failures and cleanup failures. The unchanged adapter has 26 prior synthetic passes and independent review. A disk-only load of real R18 passes. No native execution occurred in this staging task.
