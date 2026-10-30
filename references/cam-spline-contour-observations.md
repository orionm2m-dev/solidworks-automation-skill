# Native spline contour observations (pilot)

`sw_cam_mill_inventory_geometry.read_segment_chains(owner, method, *, read, typed,
diagnostic, budget)` is the shared callback-only contour decoder. The caller
owns PID/document/source identity, event checks and native access. Existing MILL
feature/island reads reuse this helper with their previous analytic getter order.

Installed `CWCurveType_e` defines LINE0, ARC1, CIRCLE2 and SPLINE3. SPLINE3 uses
only typed `ICWSpline` (`{6C37410C-1710-4F0A-BEFF-7BF83EFA7374}`), exact finite
raw scalar metadata and the existing typed `ICWCurve` endpoints. Degree/order,
dimension, control-point count, periodic/rational INT flags and parameter bounds
are observations; the decoder does not reconstruct or validate a spline equation.
Flags remain signed native INT values and are not converted to Boolean meaning.

`GetNumOfFacet` and `GetFacetAtIndex(INT*, IDispatch**)` provide bounded native
facet observations. Each returned object must support one typed ICWCurve QI and
have analytic LINE0/ARC1/CIRCLE2 type. Unknown interfaces/types and recursive
spline facets stop, without fallback. Zero facets are explicitly recorded as
`observed_no_facets`; only spline metadata/endpoints were then read.

Every spline has `geometry_exact=false`, `approximation_tolerance_native=null`,
`approximation_tolerance_status=native_facet_tolerance_not_exposed`, and false
`exact_control_points_read`/`exact_knots_read`. `read_complete` means the bounded
observation contract completed; it does not establish a precise contour or
machining validity. The existing feature flags for physical depth, loop closure
and island nesting remain false. Facet data must not be treated as an exact
spline, a chosen chord tolerance, repaired topology or a toolpath approval.

No `GetControlPointsData`, `IGetKnotsData`, `GetBCurveParams`, `IFacetCurve` or
`IFacetCurveTol` is invoked. The saved pointer-out method signatures do not state
safe ownership/layout contracts, and no unmanaged pointer is dereferenced.

Bounds: 256 facets per spline; 4096 declared control points; degree1..32,
order2..33, dimension1..4; finite scalar parameters and endpoint coordinates.
Facet count and control-point count are rechecked after reading. Facets consume
the same8192 global curve budget as outer curves; the budget is checked before
indexed facets and again before every subsequent outer curve. Partial diagnostics
and spent budgets are retained on any exception. Existing32-chain/256-curve and
64-island limits remain.

The primary method/enum/IID sources and their byte hashes are pinned in the
project staging manifest. Q18 observed curve3 but no successful native spline
metadata/facet read is claimed yet. Focused synthetic tests passed; root must
qualify the new observation path through read-only recovery of the already saved
EMF result. Do not replay Q18 extraction. Exact native-generated machining and
stock/target comparisons remain separate future work.
