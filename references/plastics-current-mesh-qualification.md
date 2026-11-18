# Current CAP native mesh qualification

## Later current-case evidence

The baseline mesh-save observations below are historical within this case. Later modernFillPackApply+Save produced260/80 inPRC, and nativeRunF consumed current mesh andoneinlet. See plastics-current-fill-qualification.md for the active preliminary run; do not infer no current solver from the earlier baseline subsection.

Independent boundary analysis found0degenerate triangles,0duplicate faces, every boundary edge shared twice, and enclosed volume18142.938201mm3, about0.06757% above nativeCAD. This is a diagnostic difference, not an assigned acceptance tolerance. Geometric aspect proxies differ from native measures; do not substitute them for native maxaspect445.525421.

Sample lines through six actual snap regions were checked using standardlinear tetra decompositions of the saved native cells. UIstems cross4-5originalcells andselectednosechords3-4; LTE/RFstems cross5-7 andnosechords6/5. Across36selected stem lines, maximum mesh/CAD chord difference is below3.9e-8mm. This confirms representation at those sample lines only. Oblique crossings do not prove independent layer count or solution convergence; nosechords are not universalminimumwallmeasurements. No mesh mutation occurred.

Current snapsection/mechanics interpretation is in cap-r26-snapfit-screen.md. Fresh518sections replace reliance on ambiguous whole-region Boolean cuts for the preliminary mechanicalscreen. No production acceptance has been granted.

Evidence date: 11 November 2026. Exact-build, single-current-case integration result, not production release.

## Completed native sequence

The owned current R26 part has one valid solid, 495 faces, native volume18130.6874485034 mm3 and no Check3 findings. Its BASF Ultradur S4090G6 injection-unit card and260/80 process settings remain saved. A current CAD point at[0,27.85935732379086,16] mm is bound to the actual1-degree skirt face. Select the point after opening the CAD injection page: opening cleared the initial selection. Native Select4 mark0 was accepted and became mark1. The3mm UI field is labelled pointer diameter; it is not yet a qualified physical gate diameter.

Surface meshing opened page38. SWPAPI_SliderPosition("SurfaceMesh2_SetMeshDensity",3) is a relative step operation, not an absolute slider setter. Actual density changed0 to3. One SurfaceMesh2_Create changed the target size from1.6017408483 to0.8008704242 mm. NextPropPage then opened page39, the current Tetrahedral Hybrid step. Do not substitute legacy page23 commands or infer the displayed page directly from the internal workflow45.

Page39 manager offset408 holds the active property page; Create is SWPAPI_ButtonPress("TetraHybrid_Create"). The default settings read back as two prismatic layers, minimum layer height0.1, gradation5. This is not proof of achieved resolution across the thin snaps. The final page intentionally disables Next: its8b4 flag is always cleared by the native update routine. A zero flag is not a mesher failure. All surface-to-volume map entries were present (page605=1), cavity settings no longer dirty. ApplyPropPage completed the workflow, returned to page-1 and wrote fresh current mesh files. One native Save3 succeeded with0 errors/0 warnings and unchanged geometry.

The mesh has362854 volume elements and149035 nodes. Fresh PG3 header counts agree with the loaded MoldWorks counts. File parsing found186637 six-node code7 cells,3639 five-node code6 cells,172578 four-node code5 cells; all nodes are finite and IDs unique. Raw PG3 coordinates are centimetres in this case (multiply10 for mm); historical loader scaling0.01 produces SI metres.

## Quality and remaining input work

Public ISimpoeWorks.ToolbarEN_MeshDetail returned1, ToolbarCB_MeshDetail opened the native summary. Read-only accessibility extracted the diagnostic SysListView32; no UI controls, scrolling, focus changes or CAD actions were invoked. Surface summary:50779 nodes,101562 elements,watertight yes,one group,zero intersections and unmatched elements,bad0.988559%,very bad0.026585%,max aspect34.306874. Volume max aspect445.525421. These outliers require location/resolution review before engineering acceptance. These are percentages, not counts.

TreeItem_EditMesh returnedfalse and left the native page/context unchanged. Its receipt's optimistic completion label is not proof that an editor opened. Do not replay it. The public MeshDetail route is the verified diagnostic alternative. A whole-screen rectangle capture showed an occluding unrelated window; it is not CAD evidence. PrintWindow of the owned summary and its accessibility text are the actual evidence.

The current CAD gate and260/80 remain saved, but the post-mesh BC3 Gate_Info is empty and the global PRC31002/31003 are247/76, matching the material card defaults. Whether subsequent native input generation supplies per-unit260/80 and maps the CAD gate must be proved before Fill. Do not manually edit input files or reuse historical R4 gate/node IDs. No solver was launched for this mesh.

## Exact-build diagnostic lessons

DataProjectWorks.GetDomainCorrespondIndex(-1) returns0 and its companion index mapping returns1: the mesh object's domain code-1 is valid cavity1, not unassigned. Do not change domain attributes based on this negative code. Public CAD domain type1/index1/unit1 is independently verified.

The native integration uses public COM callbacks/setters only. Bounded process reads are exact-build diagnostics; they do not expose private invocation or memory writes. The native Next controller stopped before any call on the final page; the correct Apply route was then independently established. A first public method inventory read TYPEATTR.cImplTypes instead of cFuncs and was empty; corrected cFuncs is tuple index6. No application callbacks were invoked by either inventory.

Snap applicability checks found minute additions at the exact roof-cut plane in five regions (max height0.0000151mm), while LTE compared empty. A second cropped Boolean comparison was inconsistent (near-whole-region added results); it is not evidence of an actual redesign or exact equivalence. Preserve these limitations, use native change bounds and fresh section comparisons before transferring mechanical conclusions. Prior beam calculations remain preliminary, not material allowables or cycle qualification.

## Continuation

Resolve current native gate/process input generation, locate/refine mesh quality outliers and thin regions, then run fresh Fill/Pack with geometry/material binding and convergence. Complete current assembly integration, functional tolerances, ISO drawing and handoff artifacts. No production-ready status is granted by this integration evidence.
