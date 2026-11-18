# Separate Finish definitions (pilot)

`solidworks_cam_append_finish_definitions` uses `scripts/sw_cam_append_finish_definitions.py`. Its sealed recipe contains exactly two definitions with explicit feature and setup identities, a named TechDB default and separate wall/floor roles. Recipe fields cannot be supplied as arbitrary setter or generation arguments.

This bounded action appends exactly two separate Finish definitions to an explicitly selected saved MILL qualification part. It protects the existing operation order, identities, configuration, tool catalogue and generated path counts. Definition creation and Save are distinct from toolpath generation and manufacturing acceptance.

The request must identify the registered CAM add-in, owned process and exact lifetime, current saved part and SHA, immutable predecessor receipts, an explicit recipe and a fresh result location. Validate the real request against the complete inherited public schema, including the required add-in CLSID, before acquiring the application target. Saved evidence does not substitute for current native readback.

The action must prove the complete allowed append delta before Save, then verify the saved source transition and read back both new definitions. The current qualification case protects the old 26-operation prefix and all 19 generated paths. These case counts belong to the pinned input evidence; they are not universal product assumptions.

No GTP, GOP, AFR, simulation or toolpath export is part of this step. It does not delete or repurpose the previous Finish, calculate the new operations, qualify entry/exit geometry, establish controller compensation or release production. Native defaults are observations, not accepted cutting conditions. A separate reviewed action is required for subsequent configuration or calculation.

Record pending primitive actions before dispatch. Stop on any unexpected delta, source/process/runtime drift or CAM message. Do not silently roll back or replay an uncertain insertion or Save. If a failure occurs after Save, preserve its actual return and saved-file evidence; a later readback failure cannot erase an earlier native outcome.

The endpoint remains pilot. Software contract tests and interface metadata are prerequisites, not native qualification. A successful saved append proves only the recorded definition and persistence scope. Hole access, stock, workholding, toolholder, cutting conditions and complete machining geometry remain separate checks.


## Reconcile a returned insertion before continuing

A returned native pointer does not authorize replay when reading its ID failed. The dispatch guard is consumed by its one mutation: close it before opening a fresh read scope with the actual document identity. Retain the original attempt marker and receipt.

`recovery_inspect` observes the sole added empty definition, its actual defaults and two full retained-state snapshots without claiming a mutation marker or saving. The native trial recovered operation364 and preserved the original26-operation prefix and19generated paths. The TechDB name "Contour and floor machining" did not enable BottomFinOpt: its actual value was false. Treat a template name as a selection label, never proof of a resulting machining mode. An inspection may succeed with configuration_required=true; it cannot thereby authorize machining or the former Finish-only continuation.

## Explicit pocket-clearing floor alternative (pilot)

The separate `recovery_append_floor_wall` mode consumes the completed observation, the unchanged saved source and a new explicit recipe. It appends a Rough pocket-clearing definition for the floor followed by a Finish contour definition for the wall. The existing unconfigured draft is retained and excluded from the planned machining selection; it is not represented as suppressed or finished.

This mode protects the full inspected operation prefix, previous generated paths, features and shared tools. Read the retained draft's own defaults and NC before and after insertion and across Save. New definition defaults are also observed and compared after one explicit Save. No setters, GTP, GOP, AFR or postprocessing belong to this action. `definitions_saved` is distinct from `parameters_configured`, `machining_eligible` and `production_qualified`.

Using a pocket-clearing operation for the final floor cut still requires a separate parameter recipe and inspection of its actual swept path. Verify the operation-level depth override without changing the shared feature, complete floor coverage including the centre, approach/retraction, and the transition surface. Keeping the nominal cylinder within the design void does not qualify physical cutter tolerances, holders, fixtures or cutting conditions.
