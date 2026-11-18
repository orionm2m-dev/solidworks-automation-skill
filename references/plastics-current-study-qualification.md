# Current-geometry Plastics study: native integration qualification

Evidence date: 11 November 2026. Generic integration notes from a bounded live case, separate from static API research and completed historical Fill.

## Verified current native load

ISldWorks.LoadAddIn with the installed SimpoeWorks.dll returned0. GetAddInObject("SimpoePlastics.SimpoePlastics.34") returned ISimpoeWorks, IID {2584D3FA-8A8C-4314-AE96-485B5742A021}. The add-in established its own Wrapper HWND binding to the owned SOLIDWORKS process; no SetHandle was called.

Loading a clean part created project/injection-location attributes and made the document dirty without changing its geometry. This is an observed lifecycle effect, so later guards must explicitly distinguish saved geometry from intentional unsaved study metadata. It is not proof of a populated study or mesh. The new model stem was empty and native mesh counters were zero.

Hold the Wrapper global mutex and owned process mutex, inspect active solver ownership and exact module hashes, and verify the active CAD/configuration/body before and after the call. Other application sessions are not closed, saved or rebound through private writes.

## New-study typed calls: verified single-unit Solid study

Study_NewStudy, NewStudy_StudyName and NewStudy_AnalysisProcSolid were accepted. NewStudy_InjectUnitNum returned false because the ordinary injection process fixes this disabled field at1. Static routing proved SWPAPI_ComboBoxSelect("NewStudy_InjectProcess",0) means process1; one Apply then produced native process1/count1/analysis_kind2/name, project attribute and fresh PRC/MCH/MAL sidecars. The pre-Apply global process0 was stale initialization, not the selected combo value. No CAD Save followed.

Always read UTF8 JSON explicitly: a default Windows cp1251 reader produced mojibake in an inspector; actual native filesystem and COM configuration names matched. This was not a native Unicode path defect.

## Injection-unit lifecycle: acknowledgements are not commit proof

SWPAPI_DblClkTreeItemEx("TreeItem_InjectUnitSettings","0") returned false while opening its property page. Static receiver analysis proved the branch does not set a true result. Check actual page lifecycle before deciding whether to retry. Activate a verified PlasticsManager tab through ModelViewManager native API when needed; do not use ordinary UI clicks.

On a disconnected second unit page, material and temperature setters and Apply returned true, but the CAD attributes stayed empty/230/80. Subsequent bounded reads proved the correct27-line BASF/PBT card was in the local page. The cause was the controller reopening after the false acknowledgement: the first native page remained active, the manager pointed at a second object with no native Close-target. Close returnsS_OK when this target is null and does not call OnClose. Material validation was not the cause.

The public Close target was traced by exact build to sldapiu.dll RVA9cb300. A bound native window is required in addition to a nonnull property-page COM interface. Do not call raw COM pointers externally, write memory, send window commands directly or manually free orphan pages.

Recovery was executed through native APIs: preserve the card/attributes; verify the first owned page and an empty deferred-action queue; select the native PropertyManager tab; call RunCommand(swCommands_PmCancel=-1) once; verify the old window gone, manager unit page cleared, geometry/attributes unchanged; open the unit page exactly once; verify a bound owned window. Material setters and one Apply then committed the full expected card and260/80. Native Save3 succeeded with zero errors/warnings, clean document and unchanged geometry. Public body.FindAttribute verified cavity domain type1/index1/unit1.

AfterClose clears the manager page pointer without an owner comparison, so cancelling the old page intentionally abandons the disconnected second page. This is a specific recovery, not permission to close unrelated commands or replay old controllers. The disconnected object's local card was saved first; no unknown destructor was called.

Read-only exact-build diagnostics excluded unit conversion (CA scale1/offset0), null project context, nonempty material-child-window branch and user-fill-time validation (Auto mirror0x2727). Public active-page name DveApiPage2 alone does not identify an add-in owner. One pre-action CString consistency check failed; that controller performed zero actions and later stable inspection succeeded.

The saved CAD unit now has the expected BASF card SHA c1dff9b39e6409e65c8502b8ee41034a7972a8bfc8e6715e5ef136765ae8fdd7 and260/80. Its pre-mesh PRC still has default230/80. Native save alone is not proof that solver input is current: the new mesh/input lifecycle must rewrite and independently verify it before a solve. Do not manually patch the PRC.

## Mesh controls and evidence

The project static research records typed new-study, injection-unit/material, gate, surface/tetra mesh and summary routes. A catalog of707 keys is not a blanket allowlist. Most setters acknowledge dispatch, not completion. Mesh summary getters require the actual native summary page31 and fresh mesh context; zero/empty values outside it are invalid evidence.

Rebind gate geometry after any shape edit. Mesh-request Position and Diameter serialization was statically traced with a factor1000, but runtime units and actual inlet node mapping must be checked. Historical mesh/results never become current merely because the material and a point location match.

Current study/material creation and saving are verified; gate/mesh/solver-input/Fill/Pack qualification is still in progress. Read the latest project checkpoint and individual receipts before continuing. Do not replay historical solver controllers or read solver-owned log files during a solve.
