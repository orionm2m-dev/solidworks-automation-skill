# TURN feature recipe qualification

`solidworks_cam_qualify_turn_feature_recipe` provides `prepare` and `apply` for one existing TURN feature on a distinct, isolated copy. The copy must be the only loaded document. The selected process ID and creation time, exact saved-file digest, protected source pins, active TechDB path/digest, raw current attribute, desired native lookup, condition scalars, and ordered operations are explicit inputs.

Prepare observes the complete bounded recipe metadata twice under CAM event monitoring and returns `prepared_state_sha256`. It performs no CAM mutation. Prepare rejects an apply digest or receipt path.

Apply requires that exact digest and a fresh absolute JSON receipt. A persistent marker binds the copy file identity and feature independently of the receipt name. It prevents another attempt after success, failure, or an interrupted call. Do not remove a marker to retry an uncertain mutation.

The only native mutations are one `ICWTurnFeature.Attribute` assignment followed, after exact readback, by one feature-level `ICWFeature.GenerateOpPlan(2)` call. Each call has durable attempted/returned evidence. A failure stops the sequence. There is no operation insertion, direct tool assignment, GTP, model Save, global/setup GOP, UI automation, or automatic retry.

Readback verifies the exact replacement block, new type sequence and feature links, and preservation of all other operation IDs/order, generated flags and record counts, feature headers, observed own tools, and the two available own NC scalars. Existing crib rows must remain unchanged; any added tool must be used by a new operation. Optional per-operation tool signatures are checked against the new operation's own tool. A null signature records selection without qualifying it; native tool IDs are never equated to TechDB row IDs.

The reused NC reader covers only `GetSpndlSpeed` and `GetFeedRateIPM`. Tool geometry follows the existing profile and diamond-tool crib getter scope; unsupported drill geometry remains explicitly unavailable. Record counts do not compare CL coordinates. Neither a successful RAM result nor a clean document flag qualifies persistence, physical tools, complete NC settings, geometry, or production. Separate pinned CL export and comparison are required to protect coordinate bytes; a later explicit Save/reopen is a different qualification.

Public read-only recipe inspection remains clean-document-only. The optional dirty-document allowance is internal to the transaction's guarded after-write observations. All feature metadata and other fields must remain exact except the expected target attribute, replacement block, explained tools, and document dirty flag.

Synthetic verification:

```powershell
python -m pytest tests/test_sw_cam_turn_feature_regenerate.py tests/test_mcp_cam_turn_feature_regenerate.py tests/test_sw_cam_turn_feature_recipe.py tests/test_mcp_cam_turn_feature_recipe.py -q
```

These checks use synthetic native objects and never activate CAD. Passing them does not qualify a live vendor mutation.

A native qualification confirmed both Attribute and feature GOP returned, creating the requested four operation types with matching own tools and recorded NC fields. The vendor appended the replacement block after retained operations. The original strict position check correctly stopped acceptance; the separate read-only reconciliation retained that evidence and confirmed the definitions without repeating GOP. Appended order must be reviewed and corrected separately before dependent machining.
