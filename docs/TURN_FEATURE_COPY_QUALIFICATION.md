# Copy one TURN feature into an empty reverse setup

The MCP tool `solidworks_cam_qualify_turn_feature_copy` prepares or applies one isolated copy qualification. It requires exactly two existing feature setups and two operation setups: the original linked pair and an empty, reverse target pair. An exact rough/finish bore operation supplies the source-feature witness. All objects are resolved from current native enumerations and native IDs.

The only mutation is typed `ICWBaseSetup.CopyFeatureToThisSetup(source_feature, None, True, False)` on the target feature setup. The current type-library contract is DISPID 13, HRESULT, four IN parameters (`IDispatch* pFeat, IDispatch* pAfter, VARIANT_BOOL bMakeCopy, VARIANT_BOOL bCloneOperation`) and an OUT retval `VARIANT_BOOL* pRet`. The ABI and exact interface IID are checked before application access.

Vendor user help describes copying TURN features between setups and separately enabling operation copying. The installed API help does not document this method's parameters or NULL-anchor behavior. Passing `None` marshals a null IDispatch pointer, but that fact does not prove accepted insertion semantics. This tool qualifies that one candidate on an empty target. It never substitutes another anchor, retries with different arguments, moves the original, or calls GOP, GTP, Save or rollback. Some feature directions may be incompatible with another setup; a method's existence does not establish that a particular copy will work.

## Guards and results

Both actions require exact process ID/lifetime, saved part path/SHA-256, the original and target native setup IDs, the source native feature ID, the witnessed operation ID/type/links, and complete inventory counts. Source and target setup IDs must be distinct. The source must remain in its original setup and in the witnessed operation's links. Target operation setup must be empty and link to the exact target feature setup. Original direction must be forward; target reverse flag must be true and its finite nonzero axis opposite the original within the existing normalized-axis tolerance.

The sole loaded document must initially be clean. Protect the original files and a separate archive of the current saved state with exact SHA-256 pins. Each protected file must be distinct from the working copy by normalized path and filesystem identity. `qualification_only: true` and `message_policy: "vendor_default"` are required.

`prepare` takes two complete, equal captures and returns `state_sha256`. It does not claim a mutation attempt. `apply` requires that exact prepared digest and an unused absolute JSON receipt path, repeats the captures, durably writes a once marker and pending receipt, then takes another full capture before dispatch. The fresh state and source/target IDs must still match. The once marker is keyed by scope and the copy's device/inode, not a changeable selector.

The source's full native line/arc profile and spindle metadata are captured with existing qualified getters. Profile collection reads use the same event gate. Each profile is limited to half the shared parser budget (256 segments), so the complete source-plus-copy readback fits the existing 512-segment bound. Oversized sources stop before mutation.

After the single call, only one new positive feature ID in the exact target setup is acceptable. There must be no new operations and no movement of the original. All existing setup IDs/order/frame observations, feature IDs/links, operation IDs/order/tool IDs/types/suppression/generated flags/per-path record counts, and the full source profile must remain unchanged. The copied feature's type, attribute ID/name, spindle and segment count must match the source; its full raw profile is recorded twice. The final two captures must agree.

A strict native Boolean True is necessary. False with a readable added feature is still diagnosed and rejected; False without the expected count increase stops at the bounded inventory gate. Exceptions, events, unexpected additions, source/process drift, receipt failures and ambiguous returns stop qualification with no replay or automatic rollback. A possibly dispatched attempt is uncertain. Success reports `review_required` and verified readback only.

## Coordinate and preservation limits

Changing setup can change the coordinate representation of a copied profile. The tool does not require equality between source and copied coordinates or infer a sign flip, translation, tool frame or origin relocation. Setup axes, reference point, operation FCS origin, and transform output GUIDs/scale/rotation flag are observations; transform vectors and matrices remain undecoded. A single successful NULL-anchor call does not establish general NULL semantics.

The result does not qualify physical profile equivalence, storage independence, all hidden CAM parameters, complete part geometry, CL byte preservation, collision clearance, machining access, saved persistence or production readiness. No recipe change or generation follows automatically. Those are separate reviewed actions after examining the new feature's raw profile.

## Verification and installation

Tests exercise the real guarded line/arc getter path for both source and copy, exact NULL/True/False arguments, strict Boolean returns, one-call durability, events during profile reads, source and setup drift, operation cloning, unexpected feature deltas, original profile preservation, and replay prevention. Wrapper tests cover strict schema, process/runtime binding and prepare/apply requirements.

Install the new core module, its two new test files and this document. Add only `SolidWorksCamTurnFeatureCopyInput` and `solidworks_cam_qualify_turn_feature_copy` from the server AST patch. Existing readers, reverse-setup qualification and server nodes remain unchanged. Native copy behavior remains pending until the guarded result is reviewed.
