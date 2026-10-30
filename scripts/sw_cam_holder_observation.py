"""Retain complete holder geometry while reporting nominal differences separately."""
import math
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile, point, num
from scripts.sw_cam_mill_inventory_geometry import MAX_TOTAL_CURVES, MAX_SPLINE_FACETS

NOMINAL_DIFFERENCES=frozenset({"Curve count differs","Missing, extra or ambiguous segment",
    "Arc centre differs","Arc radius differs","Arc takes wrong sweep"})


def complete_holder_profile(profile):
    """Structural/read-budget validation only; no nominal shape acceptance."""
    chains=profile.get("chains")
    if (profile.get("status")!="observed" or type(chains) is not list or not 1<=len(chains)<=16
        or type(profile.get("declared_chain_count")) is not int or profile["declared_chain_count"]!=len(chains)):
        raise ValueError("Complete bounded holder chains required")
    total=0;top_level=0
    def curve(c,facet=False):
        nonlocal total
        total+=1
        if total>MAX_TOTAL_CURVES:raise ValueError("Holder curve/facet budget exceeded")
        kind=c.get("curve_type")
        if c.get("read_complete") is not True or type(kind) is not int or kind not in (0,1,2,3) or (facet and kind==3):
            raise ValueError("Complete supported native holder curve required")
        if kind in (0,1,3):
            point(c["start_native"],3);point(c["end_native"],3)
        if kind in (1,2):
            point(c["centre_native"],3);point(c["normal_native"],3)
            if num(c["radius_native"])<=0:raise ValueError("Positive holder radius required")
            flag=c.get("sense_raw" if kind==1 else "direction_raw")
            if type(flag) is not int:raise ValueError("Strict holder direction flag required")
        if kind==1:point(c["mid_native"],3)
        if kind==3:
            facets=c.get("facets");count=c.get("declared_facet_count")
            if (type(facets) is not list or type(count) is not int or not 0<=count<=MAX_SPLINE_FACETS
                or count!=len(facets) or c.get("facets_status")!=("observed_unknown_tolerance" if count else "observed_no_facets")):
                raise ValueError("Complete bounded holder spline facets required")
            for f in facets:curve(f,True)
    for chain in chains:
        curves=chain.get("curves")
        if (chain.get("read_complete") is not True or type(curves) is not list or not curves
            or type(chain.get("declared_curve_count")) is not int or chain["declared_curve_count"]!=len(curves)):
            raise ValueError("Complete holder curve collection required")
        top_level+=len(curves)
        if top_level>256:raise ValueError("Holder top-level curve budget exceeded")
        for c in curves:curve(c)
    def finite(value,depth=0):
        if depth>16:raise ValueError("Holder observation nesting budget exceeded")
        if type(value) is float and not math.isfinite(value):raise ValueError("Finite holder observation required")
        if type(value) is dict:
            for x in value.values():finite(x,depth+1)
        elif type(value) in (list,tuple):
            for x in value:finite(x,depth+1)
        elif value is not None and type(value) not in (str,int,float,bool):
            raise ValueError("Serializable holder observation required")
    finite(profile)
    return dict(structural_readback_complete=True,chain_count=len(chains),curve_count=top_level,
        total_curve_and_facet_count=total,nominal_shape_verified=False)


def observe_holder_nominal(profile,recipe,protrusion):
    """Only known nominal mismatches become findings; structural failures propagate."""
    structure=complete_holder_profile(profile)
    try:
        proof=verify_holder_profile(profile,recipe,protrusion)
    except ValueError as exc:
        if str(exc) not in NOMINAL_DIFFERENCES:raise
        return dict(native_holder_shape_verified=False,structural_readback=structure,
            nominal_match=False,nominal_difference=dict(type=type(exc).__name__,reason=str(exc)),
            expected_nominal_curve_count=len(recipe["records"]),
            physical_grip_verified=False,spindle_compatibility_verified=False,
            collision_clearance_verified=False,production_qualified=False)
    return dict(proof,structural_readback=structure,nominal_match=True,nominal_difference=None)