"""Bounded additive circular pocket checks; existing CAM work is immutable."""
from copy import deepcopy
import math
from scripts.sw_cam_profile_sketch import _input
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_mill_append_delta import verify_added_plan
from scripts.sw_cam_mill_compound_strategy import validate_compound_scope

SCOPE = "MILL_ADDED_CIRCULAR_POCKET_PLAN_V1"
SKETCH_SCOPE = "MILL_ADDED_CIRCLE_SKETCH_V1"
TOL_NATIVE = 1e-8

def close(a, b):
    if type(a) not in (int, float) or type(b) not in (int, float):
        return False
    return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=0,abs_tol=TOL_NATIVE)

def vector_close(a, b):
    return isinstance(a,(tuple,list)) and len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))

def cylinder_spec(anchor, args):
    """Bind the requested nominal circle to one fully read cylindrical MSH step."""
    if anchor.data.get("scope") != "MILL_APPEND_OPERATIONS_V1":
        raise ValueError("An original verified appended plan is required")
    if len(anchor.state["features"]) != 18:
        raise ValueError("Expected original 18-feature context")
    header=validate_compound_scope(anchor,args["reference_feature_native_id"],
        args["owner_setup_native_id"],3)
    if header["axis_native"] != [0.,0.,-1.]:
        raise ValueError("Only the previously observed negative-Z setup is supported")
    details=anchor.data["saved_details"]
    profile=details["three_step_profile"]["compound_strategy"]
    if (profile.get("step_dimensions_read") is not True
        or profile.get("complete_step_coverage") is not True
        or profile.get("index_base_verified") is not True):
        raise ValueError("Complete original three-step readback required")
    index=args["cylinder_step_index"]
    if type(index) is not int or index != 1:
        raise ValueError("This bounded route uses only the middle cylindrical step")
    step=profile["observed_steps"][index]
    if step["index"]!=index or step["type_raw"]!=1 or step["method"]!="GetCylParams":
        raise ValueError("Exact cylindrical step required")
    spec=_input(args["sketch_spec"])
    if spec["plane_axis"]!="Z" or spec["profile"]["kind"]!="circle":
        raise ValueError("One XY circular sketch required")
    center=spec["profile"]["center_model_mm"]
    if not vector_close(center,step["start_native"]):
        raise ValueError("Sketch center differs from pinned cylinder")
    if not close(2*spec["profile"]["radius_mm"],step["diameter_native"]):
        raise ValueError("Sketch diameter differs from pinned cylinder")
    depth=args["depth_native"]
    if not close(depth,step["depth_native"]) or depth<=0:
        raise ValueError("Exact positive cylindrical depth required")
    if args["reverse_direction"] is not False:
        raise ValueError("Only the qualified non-reversed negative-Z route is supported")
    if any(r["name"].casefold() in {spec["sketch_name"].casefold(),spec["plane_name"].casefold()}
           for r in anchor.state["sw_reference"]["feature_tree"]):
        raise ValueError("Requested new sketch/plane already exists; no duplicate or replay")
    setups=[s for s in anchor.state["feature_setups"] if s["native_id"]==args["owner_setup_native_id"]]
    if len(setups)!=1 or setups[0]["axis_native"] != [0.,0.,-1.]:
        raise ValueError("Exact existing negative-Z owner setup required")
    if args["operation_setup_native_id"] not in [s["native_id"] for s in anchor.state["operation_setups"]]:
        raise ValueError("Exact existing operation setup required")
    return dict(header=deepcopy(header),details=deepcopy(details),step=deepcopy(step),sketch_spec=spec,
        depth_native=float(depth),nominal_end_native=[center[0],center[1],center[2]-depth])

def verify_sketch_delta(before,after,created,spec):
    if not isinstance(created,list) or not 1<=len(created)<=2:
        raise ValueError("Only one sketch and optional plane may be added")
    expected=[dict(name=spec["sketch_name"],type="ProfileFeature")]
    if len(created)==2:
        expected.insert(0,dict(name=spec["plane_name"],type="RefPlane"))
    if created != expected:
        raise ValueError("Exact named circle/plane creation delta required")
    names={r["name"] for r in created}
    old=before["sw_reference"]["feature_tree"]
    observed=after["sw_reference"]["feature_tree"]
    if any(r["name"] in names for r in old):
        raise ValueError("A named object existed before creation")
    if [r for r in observed if r["name"] not in names] != old:
        raise ValueError("Existing SolidWorks feature tree changed")
    if [r for r in observed if r["name"] in names] != expected:
        raise ValueError("Unexpected or duplicate new SolidWorks feature")
    wanted=deepcopy(before)
    wanted["sw_reference"]["feature_tree"]=deepcopy(observed)
    if not same_observed_context(wanted,after,allow_dirty=True):
        raise ValueError("Sketch creation changed captured CAM, bodies or other context")
    if after["document"]["needs_save"] is not True:
        raise ValueError("Expected unsaved sketch change was not observed")
    return True

def verify_pocket_delta(before,after,new_id,owner_id,spec,depth):
    if type(new_id) is not int or new_id<=0:
        raise ValueError("Exact new native feature ID required")
    old=before["features"]; rows=after["features"]
    oldids=[r["geometry"]["native_id"] for r in old]
    allids=[r["geometry"]["native_id"] for r in rows]
    if len(set(allids))!=len(allids) or new_id in oldids or len(rows)!=len(old)+1:
        raise ValueError("Exactly one new feature identity required")
    added=[r for r in rows if r["geometry"]["native_id"] not in oldids]
    if len(added)!=1 or added[0]["geometry"]["native_id"]!=new_id:
        raise ValueError("Unexpected added feature")
    retained=[r for r in rows if r["geometry"]["native_id"] in oldids]
    if [r["geometry"]["native_id"] for r in retained]!=oldids:
        raise ValueError("Existing feature relative order changed")
    for previous,current in zip(old,retained):
        a=deepcopy(previous);b=deepcopy(current)
        a.pop("feature_index");b.pop("feature_index")
        if a!=b: raise ValueError("An existing feature changed")
    row=added[0];g=row["geometry"];p=spec["profile"];diam=2*p["radius_mm"]
    if (row["setup_native_id"]!=owner_id or g["volume_type"]!=2
        or g["suppressed"] is not False or g["subtype_raw"]!=0
        or not vector_close(g["axis_native"],[0,0,-1])
        or not vector_close(g["start_native"],p["center_model_mm"])
        or not vector_close(g["bounds_native"],[diam,diam,depth]) or not close(g["depth_native"],depth)):
        raise ValueError("New pocket identity, dimensions, direction or ownership differs")
    wanted=deepcopy(before)
    if len(before["feature_setups"])!=len(after["feature_setups"]):
        raise ValueError("Feature setups changed")
    target_found=False
    for i,(a,b) in enumerate(zip(before["feature_setups"],after["feature_setups"])):
        local=[r for r in rows if r["setup_index"]==i]
        if [r["feature_index"] for r in local]!=list(range(len(local))):
            raise ValueError("Invalid feature ordering")
        expected=deepcopy(a)
        if a["native_id"]==owner_id:
            target_found=True;expected["feature_count"]+=1
            if row["setup_index"]!=i: raise ValueError("New pocket setup index mismatch")
        if b!=expected or len(local)!=b["feature_count"]:
            raise ValueError("Unrequested setup or feature count change")
    if not target_found: raise ValueError("Pocket owner not present")
    wanted["features"]=deepcopy(rows)
    wanted["feature_setups"]=deepcopy(after["feature_setups"])
    if not same_observed_context(wanted,after,allow_dirty=True):
        raise ValueError("Pocket creation changed operations, bodies or captured context")
    return deepcopy(row)

def verify_pocket_operations(before,after,new_id,operation_setup_id):
    added=verify_added_plan(before,after,new_id,operation_setup_id)
    kinds=[r["mill_operation_type"] for r in added]
    if any(type(v) is not int or v not in (0,1) for v in kinds) or set(kinds)!={0,1}:
        raise ValueError("New circular pocket must have only rough0 and finish1, both present")
    return added

def verify_circle_observation(observation,spec,depth,new_id):
    row=observation["feature"]
    if row["native_id"]!=new_id or row["volume_type"]!=2 or row["suppressed"] is not False:
        raise ValueError("Circle observation identity differs")
    diam=2*spec["profile"]["radius_mm"]
    if (not close(row["depth_native"],depth)
        or not vector_close(row["axis_native"],[0,0,-1])
        or not vector_close(row["bounds_native"],[diam,diam,depth])
        or not vector_close(row["start_native"],spec["profile"]["center_model_mm"])):
        raise ValueError("Measured pocket headers differ")
    from scripts.sw_cam_mill_circle_geometry import prove_mill_circle_geometry
    proof=prove_mill_circle_geometry(observation["sketch_circle_m"],row["top_curves_native"],
        row["bottom_curves_native"],depth,row["axis_native"])
    if (proof.get("contour_verified") is not True
        or proof.get("relation") not in ("coplanar","depth_separated")
        or not close(proof["native_units_per_mm"],1.)):
        raise ValueError("Circular contour or native scale verification failed")
    return proof

def profile_for_action(anchor,args):
    if args["action"]=="create_sketch":
        return cylinder_spec(anchor,args)
    if args["action"]!="create_pocket_plan" or anchor.data.get("scope")!=SKETCH_SCOPE:
        raise ValueError("Pocket creation requires a verified saved circle anchor")
    previous=anchor.data["request"]
    for key in ("reference_feature_native_id","owner_setup_native_id","operation_setup_native_id",
                "cylinder_step_index","sketch_spec","depth_native","reverse_direction"):
        if type(args[key]) is not type(previous[key]) or args[key]!=previous[key]:
            raise ValueError("Saved circle scope differs: "+key)
    return deepcopy(anchor.data["profile"])
