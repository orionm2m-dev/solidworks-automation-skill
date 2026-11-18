# Four existing-sketch merged caps (pilot)

`solidworks_extrude_existing_sketch_caps` consumes exactly four complete signed mixed-profile specifications and four new feature names. These are request data, not project-specific defaults. It does not recreate sketches. The existing signed native reader checks the actual model-space line/arc geometry. An inverse of ModelToSketchTransform maps local +Z into the actual sketch normal; a scalar product with the supplied world ±Z vector determines the native reverse flag. Non-unit, non-axial or reflected frames fail before mutation.

The command requires a separate initially identical saved part copy, exact source/target SHA256, exact owned PID/lifetime, one loaded part, one configuration, clean initial state and one valid solid. A target once marker and a fresh durable receipt record each attempt/return/readback. One null result, exception, file/state drift or readback mismatch stops the batch; no rollback or automatic retry occurs. Selection cleanup is restricted to the bound target. Solid fingerprints reuse `_same_bodies` (exact box, mass rel_tol1e-10/abs0); this handles native read noise, not geometric tolerance. Each accepted cap adds positive volume beyond that noise.

Native calls reuse `sw_part.extrude_boss` with an exact existing SketchSelectionRef, explicit direction, merge=True and no start offset. Returned `GetDefinition` scalar readback requires boss/nonthin/blind/from-sketch/single-direction/no-draft, requested depth and reverse direction. `GetParents` must include the intended sketch. Each source feature remains addressable and only the exact boss prefix may be added; absorbed sketches may leave the top-level tree. All four sketches are rechecked after completion. No Save, CAM feature/operation/generation, deletion or document closure is performed.

The source backend's historical `direction=True` description must not be treated as positive direction. The official API defines Dir=true as reversal of the default normal. This endpoint always passes the computed Boolean explicitly; it does not alter sw_part or its other callers.

Public API references (primary documentation; signatures/semantics, not live qualification):

- [FeatureExtrusion3](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.ifeaturemanager~featureextrusion3.html): default boss direction follows sketch normal; Dir reverses it. Parent independently retrieved this exact page; the web tool's direct extraction here yielded only its shell.
- [IExtrudeFeatureData2 members](https://help.solidworks.com/2022/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IExtrudeFeatureData2_members.html): ReverseDirection, Merge, BothDirections, FromType, IsBossFeature, IsThinFeature, GetDraftWhileExtruding supply scalar observations.
- [IFeature.GetParents](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeature~GetParents.html) supplies the source sketch relationship.
- [GetDepth](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IExtrudeFeatureData2~GetDepth.html?format=P&value=): Forward=true selects the primary feature direction.
- [GetEndCondition](https://help.solidworks.com/2023/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IExtrudeFeatureData2~GetEndCondition.html): forward-direction end condition is read separately.

Status `caps_observed_ram_only` is scalar/native readback only. Original-volume preservation, added-volume containment and exact top-profile acceptance stay false pending separate native STEP export and the OCP gate. No persisted-model, CAM autodetection, toolpath or machining acceptance is implied. The new feature-definition reader and R25 batch still require one root-owned native qualification after deployment.


## Read-only inspection of the first returned cap

`solidworks_inspect_first_existing_sketch_cap` reads the existing first feature from a terminal partial batch. It binds the original receipt and once marker by SHA, exact PID/lifetime/document and unchanged saved source/copy. The original batch implementation is unchanged.

The inspector records raw `Name`, `GetTypeName2`, `GetTypeName`, definition availability, depth, end condition, ReverseDirection, Merge, BothDirections, FromType, IsBossFeature, IsThinFeature, draft and bounded parent names. Each getter result or error is persisted before the next read. Before/after body/tree/dirty captures must agree using the existing narrow mass tolerance. No rename, rebuild, Save, selection change, cleanup setter, extrusion or CAM method is called.

The expected feature name is tried first. If absent, only one new top-level candidate relative to the pinned batch baseline may be read. This fallback is diagnostic and does not authorize adoption or continuation. Getter errors are preserved; observation success means complete stable readback, not geometric or production acceptance.

Official Instant3D semantics: GetTypeName2 can report ICE; GetTypeName exposes its underlying type. The inspector records both strings without canonicalization. This does not establish that the actual feature is ICE/Boss until native readback succeeds. Source: https://help.solidworks.com/2022/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeature~GetTypeName2.html


## Corrected raw type readback and remaining-three continuation

The boss reader now records raw Name/GetTypeName2/GetTypeName and all bounded definition getters durably before validation. Rename is a separate operation. Only the documented pairs Boss/Boss and ICE/Boss are interpreted as a boss; full IsBoss/depth/direction/merge/parent checks remain required. Feature-tree captures remain raw. The added prefix must match each separately read feature's exact raw GetTypeName2.

`solidworks_continue_existing_sketch_caps` takes the inspection request fields plus `inspection_receipt_path` and `inspection_receipt_sha256`; `receipt_path` names a fresh continuation receipt. It requires the original terminal partial batch, unchanged original once marker and successful read-only inspection, each pinned by hash. It checks the exact original PID/lifetime/path, saved copy/protected-source bytes, one dirty part/configuration, current body/tree against inspection.after, first feature against the complete inspected observation, and all four original signed profiles and frames. Only then does it claim a separate target-specific remaining-three marker and invoke the shared original batch loop at indices 1, 2, 3. Index 0 is never recreated or renamed by continuation.

The first feature counts as adopted only after live validation. Each new action is journaled before dispatch and stops the sequence on any unexpected result. Original partial and inspection receipts and the original once marker are never rewritten. A failed remaining-three attempt is not resumable through this endpoint; the separate marker prevents replay. No Save, CAM or automatic retry is added. Native execution and the separate STEP Boolean volume proof remain required.

Actual prerequisite observation: the first cap was read as ICE/Boss with depth 0.001 m, reverse true, merge true, blind end 0, from-sketch 0, boss true, thin/draft/both-directions false, expected sketch parent, and unchanged before/after body/tree. This establishes the readback correction, not completion of the remaining caps.
