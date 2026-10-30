"""Offline circular-chain proof: no native application dependencies."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "sw_cam_mill_circle_geometry.py"
spec = importlib.util.spec_from_file_location("circle_geometry", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
prove = module.prove_mill_circle_geometry
Error = module.GeometryProofError
TAU = 2*math.pi


def sketch():
    return {"center_model_m":[0,0,.0109], "radius_m":.00265, "normal_model":[0,0,1]}


def circle(z=10.9, scale=1):
    return {"curve_type":2,"centre_native":[0,0,z*scale],"radius_native":2.65*scale,
            "normal_native":[0,0,1],"direction_raw":17}


def arc(start,end,z=10.9,mid=None,normal=None):
    mid=(start+end)/2 if mid is None else mid
    row={"curve_type":1,"centre_native":[0,0,z],"radius_native":2.65,
         "normal_native":normal or [0,0,1],"sense_raw":-29}
    for name,angle in [("start_native",start),("end_native",end),("mid_native",mid)]:
        row[name]=[2.65*math.cos(angle),2.65*math.sin(angle),z]
    return row


def arcs(n=4,z=10.9):
    return [arc(TAU*i/n,TAU*(i+1)/n,z) for i in range(n)]


def run(top=None,bottom=None,depth=4.1,**kwargs):
    return prove(sketch(),[circle()] if top is None else top,
                 [circle(6.8)] if bottom is None else bottom,depth,[0,0,-1],**kwargs)


def fails(code,**kwargs):
    with pytest.raises(Error) as caught:run(**kwargs)
    assert caught.value.code==code
    return caught.value


def test_explicit_circle_noninteger_depth_and_signed_axis():
    result=run()
    assert result["status"]=="ok"
    assert result["relation"]=="depth_separated"
    assert result["contour_verified"] and result["depth_matches_requested_native"]
    assert result["measured_separation_native"]==pytest.approx(4.1)
    assert result["signed_separation_along_feature_axis_native"]==pytest.approx(4.1)
    assert result["native_units_per_mm"]==pytest.approx(1)
    assert result["top_circle_native"]["curves"][0]["direction_raw"]==17
    for flag in ["physical_depth_verified","absolute_frame_verified","coordinate_provenance_verified",
                 "global_native_units_verified","depth_axis_metric_independently_verified",
                 "qualification_complete","may_continue","direction_semantics_verified"]:
        assert result[flag] is False


def test_coplanar_is_contour_only_and_not_depth_pass():
    result=run(bottom=[circle()])
    assert result["status"]=="review_required" and result["relation"]=="coplanar"
    assert result["contour_verified"] and result["depth_matches_requested_native"] is False
    assert result["measured_separation_native"]==0
    assert result["physical_depth_verified"] is False


def test_uniform_scale_observed_not_assumed_one():
    result=run(top=[circle(scale=2)],bottom=[circle(6.8,scale=2)],depth=8.2)
    assert result["native_units_per_mm"]==pytest.approx(2)
    assert result["measured_separation_mm_using_radial_scale"]==pytest.approx(4.1)


def test_common_center_shift_is_reported_without_absolute_position_proof():
    top,bottom=circle(),circle(6.8)
    top["centre_native"][0]=bottom["centre_native"][0]=100
    result=run(top=[top],bottom=[bottom])
    assert result["aligned_axes_center_residual_native"]==pytest.approx([100,0,0])
    assert result["aligned_axes_center_comparison_is_frame_proof"] is False
    assert result["absolute_frame_verified"] is False


@pytest.mark.parametrize("count",[2,3,4,5,8,32,64])
def test_complete_arc_chain_unique_coverage(count):
    result=run(top=arcs(count),bottom=arcs(count,6.8))
    assert result["contour_verified"]
    assert result["top_circle_native"]["angular_coverage"]==pytest.approx(TAU)
    assert result["top_circle_native"]["representation"]=="geometrically_complete_arc_chain"


def test_arcs_reordered_and_endpoint_orientation_reversed_are_still_one_geometric_loop():
    top=arcs()
    top.reverse()
    for row in top:
        row["start_native"],row["end_native"]=row["end_native"],row["start_native"]
        row["normal_native"]=[0,0,-1]
    result=run(top=top,bottom=arcs(4,6.8))
    assert result["contour_verified"] and not result["direction_semantics_verified"]


def test_antiparallel_contour_normals_allowed_without_cut_direction_claim():
    top,bottom=circle(),circle(6.8);bottom["normal_native"]=[0,0,-1]
    assert run(top=[top],bottom=[bottom])["contour_verified"]


def test_actual_major_arc_midpoint_can_select_unique_full_cycle():
    top=[arc(0,1.5*math.pi),arc(1.5*math.pi,TAU)]
    bottom=[arc(0,1.5*math.pi,6.8),arc(1.5*math.pi,TAU,6.8)]
    assert run(top=top,bottom=bottom)["contour_verified"]


@pytest.mark.parametrize("kind",[True,False,1.0,2.0,"2",None,0,3,-1])
def test_curve_discriminator_is_strict_and_supported(kind):
    row=circle();row["curve_type"]=kind
    fails("SUPPORTED_CIRCULAR_CURVE_TYPE_REQUIRED",top=[row])


@pytest.mark.parametrize("value",[True,False,None,"4.1",float("nan"),float("inf"),0,-1])
def test_requested_depth_strict_finite_positive(value):
    with pytest.raises(Error):run(depth=value)


@pytest.mark.parametrize("field",["radius_native","centre_native","normal_native","direction_raw"])
def test_circle_required_native_fields(field):
    row=circle();del row[field]
    fails("MISSING_CURVE_FIELD",top=[row])


@pytest.mark.parametrize("value",[True,1.0,"0",None,2**31,-2**31-1])
def test_raw_direction_remains_strict_long(value):
    row=circle();row["direction_raw"]=value
    fails("STRICT_NATIVE_LONG_REQUIRED",top=[row])


@pytest.mark.parametrize("value",[True,"2",None,float("nan"),float("inf"),0,-2])
def test_radius_strict_positive_finite(value):
    row=circle();row["radius_native"]=value
    with pytest.raises(Error):run(top=[row])


@pytest.mark.parametrize("field",["centre_native","normal_native"])
@pytest.mark.parametrize("value",[[0,0],[0,0,0,1],[True,0,1],[0,float("nan"),1],"abc"])
def test_vectors_strict_shape_and_scalars(field,value):
    row=circle();row[field]=value
    with pytest.raises(Error):run(top=[row])


def test_normal_zero_rejected():
    row=circle();row["normal_native"]=[0,0,0]
    fails("DEGENERATE_DIRECTION",top=[row])


def test_native_normal_must_parallel_feature_axis():
    row=circle();row["normal_native"]=[1,0,0]
    fails("CONTOUR_NORMAL_NOT_PARALLEL_TO_FEATURE_AXIS",top=[row])


def test_top_bottom_radius_mismatch():
    row=circle(6.8);row["radius_native"]=2.7
    fails("TOP_BOTTOM_RADII_DIFFER",bottom=[row])


def test_top_bottom_coaxial_center_required():
    row=circle(6.8);row["centre_native"][0]=.1
    fails("TOP_BOTTOM_LATERAL_SHIFT",bottom=[row])


def test_separated_wrong_depth_not_contour_only_exception():
    fails("MEASURED_SEPARATION_DIFFERS_FROM_REQUESTED_DEPTH",bottom=[circle(6.7)])


@pytest.mark.parametrize("rows",[[],[circle(),circle()],[circle(),arc(0,math.pi)],arcs(65)])
def test_one_full_circle_or_bounded_arcs_only(rows):
    with pytest.raises(Error):run(top=rows)


def test_single_same_end_arc_never_promoted_to_circle():
    fails("AMBIGUOUS_SINGLE_ARC_NOT_FULL_CIRCLE",top=[arc(0,TAU)])


def test_coincident_end_arc_inside_chain_rejected():
    fails("COINCIDENT_ARC_ENDPOINTS_AMBIGUOUS",top=[arc(0,TAU),arc(0,math.pi)])


def test_arc_midpoint_is_actual_midpoint_witness_not_arbitrary_point():
    rows=arcs(2);rows[0]["mid_native"]=arc(0,math.pi/2)["mid_native"]
    fails("ARC_MIDPOINT_DOES_NOT_SELECT_UNIQUE_SPAN",top=rows)


def test_duplicate_half_arc_coverage_rejected_even_when_endpoints_form_cycle():
    rows=[arc(0,math.pi),arc(math.pi,0,mid=math.pi/2)]
    fails("ARC_COVERAGE_OVERLAP",top=rows)


def test_two_turn_duplicate_quarters_rejected():
    fails("ARC_CHAIN_JOIN_NOT_UNIQUE",top=arcs()+arcs())


def test_gap_in_arc_chain_rejected():
    rows=[arc(0,math.pi),arc(math.pi+.01,TAU)]
    fails("ARC_CHAIN_JOIN_NOT_UNIQUE",top=rows)


@pytest.mark.parametrize("field,value,code",[
    ("centre_native",[.02,0,10.9],"ARC_CENTRES_DIFFER"),
    ("radius_native",2.66,"ARC_RADII_DIFFER"),
    ("normal_native",[1,0,0],"ARC_NORMALS_NOT_PARALLEL"),
    ("mid_native",[0,2.7,10.9],"ARC_POINT_OFF_CIRCLE"),
    ("sense_raw",True,"STRICT_NATIVE_LONG_REQUIRED")])
def test_arc_local_geometry_and_raw_sense(field,value,code):
    rows=arcs(2);rows[1][field]=value
    fails(code,top=rows)


def test_arc_point_off_plane_even_if_on_sphere():
    rows=arcs(2);z=.01
    rows[0]["mid_native"]=[0,math.sqrt(2.65**2-z*z),10.9+z]
    fails("ARC_POINT_OFF_PLANE",top=rows)


@pytest.mark.parametrize("value",[0,-1,True,"1",float("nan"),.1])
def test_tolerance_cannot_disable_proof(value):
    with pytest.raises(Error):run(relative_tolerance=value)


def test_inputs_not_mutated_and_repeated_proof_equal():
    s=sketch();top=arcs();bottom=arcs(4,6.8);before=deepcopy((s,top,bottom))
    first=prove(s,top,bottom,4.1,[0,0,-1])
    assert (s,top,bottom)==before
    assert first==prove(s,top,bottom,4.1,[0,0,-1])


def test_normalization_does_not_claim_native_unit_vector_length():
    row=circle();row["normal_native"]=[0,0,2]
    assert run(top=[row])["top_circle_native"]["normal"]==[0,0,1]


def test_sketch_center_and_normal_not_substituted_from_native_circle():
    s=sketch();s["center_model_m"]=[.2,.3,.4];s["normal_model"]=[1,0,0]
    result=prove(s,[circle()],[circle(6.8)],4.1,[0,0,-1])
    assert result["sketch_circle_m"]["center_model_m"]==s["center_model_m"]
    assert result["sketch_native_normal_parallel_if_axes_aligned"] is False
    assert result["absolute_frame_verified"] is False

def test_native_normal_raw_value_retained_beside_normalized_direction():
    row=circle();row["normal_native"]=[0,0,2]
    result=run(top=[row])
    evidence=result["top_circle_native"]["curves"][0]
    assert evidence["normal_native"]==[0,0,2]
    assert evidence["normal_unit"]==[0,0,1]
