# Existing TURN tool contours

`solidworks_cam_inspect_turn_tool_contours` reads the selected operation's own tool. Rough-bore type 5 and finish-bore type 6 retain their existing diamond-insert/boring-holder branch. CutOff type 13 has a separate Groove-insert type 2/shank-holder type 1 branch. It requires the exact process ID and creation time, saved document path and SHA-256, operation index/type/native ID, linked feature IDs and tool native ID. Only `action="read"` and `message_policy="vendor_default"` are supported.

The tool reuses the existing bore reader's two complete captures under one active CAM event subscription. Each capture reads both `ICWTool.GetToolProfile()` and `ICWTurnToolHolder.GetHolderProfile(operation)`, together with the operation orientation, insert dimensions and X/Z offsets. The existing decoder limits each contour to 32 chains and 512 line/arc curves. Unsupported tool/holder kinds, missing or incomplete contours, identity drift, inventory change, events and cleanup failures stop the read. No further CAM getter follows an observed event.

This dedicated endpoint reads no rough-bore options, variable allowances, linked-feature profiles or THREAD catalogue. It performs no setter, tool assignment, generation, CL read or Save. The existing rough-bore-options endpoint and its default behavior are unchanged.

A successful result establishes two matching bounded observations. Stable unsaved CAM state is reported explicitly; the saved-file hash does not identify all RAM data. Inventory equality covers operation metadata and path record counts, not full CL coordinates or all CAM parameters. The process, document and saved file are checked again after event cleanup, with no later CAM reads.

The default insert contour frame is not defined by the method help. The holder contour is operation-specific; raw orientation and offsets do not establish a common insert/holder/CL frame, tool program point, physical assembly or swept clearance. Units, frame, program point, full solid geometry and production qualification remain false. A native finish-bore read produced two equal captures: a six-curve insert profile and a ten-curve, two-chain holder profile. No CAM events or collected inventory changes were observed. This verifies the bounded read for that input; physical access and coordinate transformation remain unqualified.

The CutOff branch reads raw Groove `Thickness`, `Width`, `length`, `Radius1` and `Radius2`, plus holder shape, thickness, shank length/width, protrusion and three angles. Catalogue holder IDs and turret/station numbers do not replace the required document-native own-tool ID. Both contours use the same declared getter ABI and the same bounded decoder as bore contours. The branch reads no CutOff options.

CutOff support is staged/programmatically tested only until a separate native receipt establishes successful two-capture observation. It does not qualify the default contour origin, orientation-to-CL/world transform, units, program point, a presumed slot location, holder collision or machining fitness. No tool-ID discovery or relaxed identity fallback is added.

If runtime identity changes after the core returns, the wrapper preserves all returned observations, reports an error, revokes `readback_verified` and `may_continue`, and performs no retry.
