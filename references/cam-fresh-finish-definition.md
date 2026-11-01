# Fresh Finish definition and saved continuation

Use `scripts/sw_cam_fresh_finish_insert.py --request <absolute-request.json>` for the bounded creation-only action `insert_fresh_finish_definition`. `--validate-only` verifies saved inputs and the dependency closure without connecting to CAD. This persistent module does not itself expose a dedicated MCP tool.

The request binds the owned process, exact saved source and parent receipt, source/anchor operation, linked feature, and actual TechDB default. The source must be the last saved empty Finish. The module inserts one separate definition after that anchor and saves once. It does not copy the old operation, transfer settings, assign a tool, generate toolpaths or delete the source operation. Native defaults are observed, not assumed.

Before and after insertion/save it checks existing operation rows and counts, the scalar tool catalogue, feature header, source defaults and the protected lead/gouge flags. Previously saved profile geometry is reused with its source evidence; this is not a fresh full BRep or holder-clearance inspection. A durable pending marker prevents automatic replay after an unknown outcome.

The completed scope is `SAVED_FRESH_FINISH_DEFINITION_V1`. `load_completed(...)` requires the exact receipt hash, process, source path and saved hash. It returns `authority_kind=saved_fresh_finish_definition_no_toolpath`; `toolpath_generated` and `geometry_acceptance_complete` remain false. Creation and successful saving do not qualify machining. A subsequent recipe/calculation requires a separate bounded action and its own observations.

## Explicit runtime compatibility

`sw_cam_finish_runtime_compatibility.py` can qualify exactly two historical dependencies for this saved-parent workflow: the declared interface-registry additions and the unchanged default branch of the shared tool reader. It checks current bytes, immutable archives, parent/source identity and regression evidence. It does not authorize arbitrary re-pinning, execute archived code or claim the entire profile entrypoint is equivalent.

Never edit old receipts to accept new runtime bytes. Keep the compatibility receipt and its referenced regression report. The current verifier checks a nonzero test count but does not subtract skipped tests; until its separately staged fix is migrated, independently require zero failures/errors and at least one executed test in the exact pinned XML. Do not replace a verifier already pinned by completed results merely to apply this fix.
