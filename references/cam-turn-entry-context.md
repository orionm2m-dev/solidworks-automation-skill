# TURN FACE entry-context read — pilot

`solidworks_cam_read_turn_entry_context` observes one or two existing TURN FACE operations through the installed public SOLIDWORKS CAM 2026 type library. It does not change CAM, generate paths, save a model, export geometry or manipulate the application UI. Software tests and ABI checks do not constitute native qualification.

## Binding and output

The request supplies an already owned PID and exact creation time, clean saved SLDPRT path/SHA256, expected feature/operation/setup/generated/record counts, and one or two selectors containing native operation ID, native feature ID, setup index, operation index and type7 or8. A fresh JSON receipt path, `qualification_only:true`, `message_policy:"vendor_default"` and the explicit post-index policy are required. Types7/8 use `ICWTurnFaceRoughOp` / `ICWTurnFaceFinishOp`, not the general turning Rough/Finish interfaces.

One application/document/machine context is held in a single CAM event subscription. Full bounded operation inventories, native IDs and linked feature IDs are compared before/after. Source hash, process lifetime, clean document identity and runtime identity are checked at grouped boundaries. Any native exception, identity drift, unexpected event, inventory change or failed disconnect leaves a terminal error receipt and all positive verification flags false. No automatic replay is performed.

The receipt preserves each requested target, raw observations and partial results, exact source/module/type-library pins, ABI evidence, complete inventories, event cleanup and verification flags. A successful read returns `review_required`, `observation_verified:true` and `readback_verified:true`; `may_continue`, `production_qualified`, `home_point_verified`, `catalog_complete`, units/frame and cutting-mode qualification remain false.

## Public getter scope

- `ICWOperation.GetNumPostParam` and `GetPostParam` return actual named post parameters and a success flag.
- `ICWTurnOperation.GetCannedCycleOutput` and `GetCannedCycleStartPoint` return the raw Boolean and enum/X/Z tuple. A canned-cycle start point is not established as the general approach, retract or home point.
- FACE Rough/Finish read First/Max/FinalCutAmt, StepIn/OutAngle, StepIn/OutAmt, Radial/AxialStockAmt and ProgramPoint_FeatureGeometry. Finish also reads PrevAllowance and ProgramPoint_FeatureGeometry_GougeCheck.
- `IGetTurnNCParam` binds `ICWTurnNCParam`; GetSpndlSpeed and GetFeedRateIPM are retained as raw scalars. They do not independently establish CSS/RPM/IPR modes or approved304L cutting data.

All29 getter signatures and five interface IIDs are checked against the public vendor type library before application access. FACE QueryInterface is limited to the corresponding preflighted public interface. Native member reads use an explicit getter allowlist.

## Post-parameter index policy

The index base remains unqualified. The explicit policy is `probe_zero_through_count_inclusive`: strict native count0..32 is required; count0 causes no index calls; positive countN probes indexes0..N once each, at most33. This includes both candidate boundary indexes without asserting zero- or one-based indexing. Each actual Boolean result is preserved. False is a normal observation, not an exception; only true results with bounded nonempty names enter `actual_named_parameters`. Native exceptions stop the read. No alternative probes, name guessing, setters or catalog-completeness claims follow automatically.

## Installation and current qualification

Install only the reviewed module and this reference, and append the reviewed schema/endpoint snippet to the existing MCP server. No generic COM helper or historical reader is replaced. The supplied request is an example bound to the saved BASE source and owned process at preparation time; recheck those pins and fresh receipt path before dispatch.

At pack freeze: public ABI, exact inherited schema, NoApplication constructor and focused fake-native failure tests are software evidence. Native read of the current FACE pair is pending root review and a separate receipt. Discovering an actual post parameter does not prove it is safe or sufficient to modify the current home/retract behavior.