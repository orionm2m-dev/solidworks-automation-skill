# Native draft qualification and manufacturing handoff checks

Evidence date: 11 November 2026. One live case on SOLIDWORKS Design 2026 SP4.1; this is a qualified method example, not a general production-release tool.

## Native edit and selection

Use IFeatureManager.InsertMultiFaceDraft(angleRadians, FlipDir, EdgeDraft, PropType, IsStepDraft, IsBodyDraft). The verified neutral-plane case used selection mark1 for the neutral plane and mark2 for two conical faces, EdgeDraft=false, PropType=0, IsStepDraft=false, IsBodyDraft=false. Verify actual selected objects before calling once. The requested1 degree produced an absolute1 degree surface angle in the saved native export; do not assume an incremental angle.

Neutral-plane location is a design decision. A lower-plane trial rebuilt into a valid single solid but changed adjacent guide backing geometry. It was rejected. A separate upper-plane trial preserved the internal, upper and lower functional regions, adding material only to the outer skirt. Successful BOOL, rebuild, face count and Check3 do not prove a local edit stayed local.

IBody2.Check3 returns IFaultEntity; read Count. IBody2.GetFaceCount avoids expensive GetFaces COM marshaling when only a count is needed. IFace2.GetBox is approximate: observed planar-face extent error was about0.0145 mm. Use exact PlaneParams or verified analytic geometry for the datum; never use that approximate box as a precision measurement.

## Verification sequence

Pin process creation time, physical executable identity, saved document path/hash/configuration and dirty state. Work on an isolated native revision; retain the editable original feature tree and frozen source files. Serialize cooperating COM calls with the normal PID/global operation guards.

After a single native feature call, verify rebuild, one solid, no sheet and Check3.Count0. Save only the intended native revision, export STEP, and perform bidirectional Boolean comparison and region-specific checks. Compare the new geometry with actual current assembly partners, including the motion path; zero closed-position interference is insufficient.

A rotationally invariant enclosing volume can prove a continuous path for a bounded change: demonstrate complete containment of added material, exact absence of counterpart material in that envelope, and explain why the permitted translation/rotation cannot invalidate separation. This only transfers the unchanged geometry's previously qualified path; it does not manufacture proof for unrelated old regions.

Keep native and exchange-kernel mass properties separate. In this case, native and STEP mass integration differed already in the source. Within native measurements, repeated unchanged-body volume reads differed by about1e-11 mm3. Do not use exact floating-point equality as a shape predicate. Keep a tight, documented numerical comparison and verify the actual topology/STEP differences independently.

## Lifecycle and previews

Write durable intent and returned records around native mutations and saves. If a post-save observer fails, first read the existing saved file and current document; do not repeat the save or feature call blindly. Preserve failed/rejected receipts and name archived variants explicitly.

SaveBMP at explicit1400x1100 dimensions returned white images despite success in one case. GraphicsRedraw2 and SaveBMP with dimensions0,0 produced an inspectable image. Inspect the exported image; do not infer GPU health or global repair from this one observation.

## Limits

Draft must be evaluated relative to the assigned core/cavity/side-action direction. Functional seal cylinders, snap undercuts and PCB-guide slots need their own tooling and fit decisions. A generic2 mm DFM minimum is a screening threshold, not a material-specific manufacturing rule. Thin snap noses, short beams, tolerances, mesh resolution, material/process assignment, current Fill/Pack and physical tests remain distinct acceptance checks.

Use the project's knowledge topic and evidence receipts for actual paths/hashes/status. These generic notes authorize no replay of a consumed case controller.
