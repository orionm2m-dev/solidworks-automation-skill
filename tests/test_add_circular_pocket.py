import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_cam_add_circular_pocket as m
from scripts import sw_cam_added_pocket_delta as d
from scripts import sw_cam_added_pocket_evidence as saved

SOURCE="a"*64
SKETCH="b"*64
SAVED="c"*64
SPEC=dict(plane_axis="Z",plane_offset_mm=25.8,sketch_name="CAM_CYLINDER",
    plane_name="CAM_CYLINDER_PLANE",profile=dict(kind="circle",center_model_mm=[0,0,25.8],radius_mm=23.35))
CREATED=[dict(name=SPEC["plane_name"],type="RefPlane"),dict(name=SPEC["sketch_name"],type="ProfileFeature")]

def state():
    out=json.loads((Path(__file__).parent/"saved_plan_fixture.json").read_text(encoding="utf-8"))
    out["document"]=dict(path="C:/test/part.sldprt",title="part.sldprt",type=1,needs_save=False)
    out["saved_file_sha256"]=SOURCE
    for oid,kind,tid,ttype in ((195,8,197,6),(196,2,198,2)):
        row=deepcopy(out["operations"][0])
        row.update(native_id=oid,mill_operation_type=kind,linked_feature_ids=[64],operation_index=len(out["operations"]))
        row["assigned_tool"].update(native_id=tid,tool_type_raw=ttype)
        out["operations"].append(row)
    out["operation_count"]=4;out["operation_counts"][0]=4;out["operation_setups"][0]["operation_count"]=4
    return out

def sketched(before):
    out=deepcopy(before);out["sw_reference"]["feature_tree"]+=deepcopy(CREATED)
    out["document"]["needs_save"]=True
    return out

def pocket(before):
    out=deepcopy(before)
    row=deepcopy(out["features"][0])
    row.update(setup_index=0,setup_native_id=69,feature_index=12)
    row["geometry"].update(native_id=210,volume_type=2,subtype_raw=0,shape_raw=2,suppressed=False,
        name="Circular pocket",axis_native=[0,0,-1],depth_native=13.2,
        bounds_native=[46.7,46.7,13.2],start_native=[0,0,25.8])
    # Native ordering can insert into setup0 before the subsequent setups.
    out["features"].insert(12,row);out["feature_setups"][0]["feature_count"]+=1
    out["document"]["needs_save"]=True
    return out

def planned(before):
    out=deepcopy(before)
    for oid,kind in ((220,0),(221,1)):
        row=deepcopy(out["operations"][0])
        row.update(native_id=oid,mill_operation_type=kind,linked_feature_ids=[210],
            operation_index=len(out["operations"]))
        row["assigned_tool"].update(native_id=222,tool_type_raw=1)
        out["operations"].append(row)
    out["operation_count"]=6;out["operation_counts"][0]=6;out["operation_setups"][0]["operation_count"]=6
    return out

def sketch_observation():
    return dict(entities=[dict(type="circle",center_model_m=[0,0,.0258],radius_m=.02335)],
        model_to_sketch_transform=[1,0,0,0,1,0,0,0,1,0,0,-.0258,1,0,0,0])

def circle_observation():
    curve=dict(curve_type=2,centre_native=[0,0,25.8],radius_native=23.35,
        normal_native=[0,0,1],direction_raw=1)
    return dict(feature=dict(native_id=210,volume_type=2,suppressed=False,name="Circular pocket",
        axis_native=[0,0,-1],depth_native=13.2,bounds_native=[46.7,46.7,13.2],start_native=[0,0,25.8],
        top_curves_native=[deepcopy(curve)],bottom_curves_native=[deepcopy(curve)]),
        sketch_circle_m=dict(center_model_m=[0,0,.0258],radius_m=.02335,normal_model=[0,0,1]))

def protected_details():
    full=dict(tool_native_id=145,geometry_read_complete=True,profile_complete=True,segments=[1,2,3])
    return dict(metadata_read_complete=True,profile_complete=True,generic_operation_context_unchanged=True,
        canonical_state_changed=False,items=[dict(operation_native_id=oid,full_tool=deepcopy(full)) for oid in (143,144)])

class Anchor:
    def __init__(self):
        self.state=state();self.operation_ids=[143,144];self.tool_id=145
        self.selected=dict(feature_native_id=79,owner_setup_native_id=69)
        self.baseline_tool_details=protected_details();self.pins=[]
        self.receipt_pin=dict(path="saved",sha256=SOURCE)
        step=dict(feature_native_id=64,owner_setup_native_id=69,number_of_steps=3,
            observed_steps=[{},dict(index=1,type_raw=1,method="GetCylParams",
                start_native=[0,0,25.8],diameter_native=46.7,depth_native=13.2),{}],
            step_dimensions_read=True,complete_step_coverage=True,index_base_verified=True)
        self.profile=dict(pin=dict(path="profile",sha256=SOURCE),details=deepcopy(step))
        self.details=dict(selected_tool_details=deepcopy(self.baseline_tool_details),
            three_step_profile=dict(compound_strategy=deepcopy(step)),
            strategy=dict(compound_strategy=dict(attribute_id=1,attribute_name="MSH1(mm)",active_attribute_name="MSH1(mm)")))
        self.data=dict(scope="MILL_APPEND_OPERATIONS_V1",saved_details=deepcopy(self.details))
    def summary(self):return dict(scope="appended",source=SOURCE)
    def check_files(self):pass
    def check_runtime_identity(self):pass
    def read_stock(self,*a):pass
    def verify(self,actual):
        if self.state!=actual:raise ValueError("anchor changed")

def args(tmp_path):
    return dict(action="create_sketch",process_id=17848,expected_document_path="C:/test/part.sldprt",expected_source_sha256=SOURCE,
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        saved_plan_receipt_path="saved",saved_plan_receipt_sha256=SOURCE,
        route_receipt_path="route",route_receipt_sha256=SOURCE,
        reference_feature_native_id=64,owner_setup_native_id=69,operation_setup_native_id=93,
        cylinder_step_index=1,sketch_spec=deepcopy(SPEC),depth_native=13.2,reverse_direction=False,
        qualification_only=True,acknowledge_disposable_copy=True,message_policy="vendor_default",
        save_after_verified=True,attempt_registry_path=str(tmp_path),receipt_path=str(tmp_path/"result.json"))

def test_nominal_cylinder_and_coplanar_limit(tmp_path):
    profile=d.cylinder_spec(Anchor(),args(tmp_path))
    assert profile["nominal_end_native"]==[0,0,12.600000000000001]
    proof=d.verify_circle_observation(circle_observation(),SPEC,13.2,210)
    assert proof["relation"]=="coplanar"
    assert proof["physical_depth_verified"] is False

@pytest.mark.parametrize("edit",[
    lambda a:a.update(depth_native=13.5),lambda a:a.update(reverse_direction=True),
    lambda a:a.update(cylinder_step_index=True),lambda a:a["sketch_spec"]["profile"].update(radius_mm=23.55),
    lambda a:a["sketch_spec"]["profile"].update(center_model_mm=[0,0,26]),
])
def test_reject_different_cylinder(tmp_path,edit):
    a=args(tmp_path);edit(a)
    with pytest.raises(ValueError):d.cylinder_spec(Anchor(),a)

def test_successful_deltas_preserve_all_old_operations():
    b=state();s=sketched(b);f=pocket(s);p=planned(f)
    assert d.verify_sketch_delta(b,s,CREATED,SPEC)
    assert d.verify_pocket_delta(s,f,210,69,SPEC,13.2)["geometry"]["native_id"]==210
    assert [r["native_id"] for r in d.verify_pocket_operations(f,p,210,93)]==[220,221]
    assert [r["native_id"] for r in p["operations"][:4]]==[143,144,195,196]

@pytest.mark.parametrize("change",[
    lambda x:x["operations"][0].update(suppressed=True),
    lambda x:x["features"][0]["geometry"].update(depth_native=999),
    lambda x:x["sw_reference"]["solids"][0]["box_m"].__setitem__(0,999),
    lambda x:x["material_raw"].update(name="changed") if isinstance(x["material_raw"],dict) else x.update(material_raw="changed"),
])
def test_sketch_cannot_change_protected_state(change):
    b=state();s=sketched(b);change(s)
    with pytest.raises(ValueError):d.verify_sketch_delta(b,s,CREATED,SPEC)

@pytest.mark.parametrize("change",[
    lambda x:x["features"][12]["geometry"].update(depth_native=13.5),
    lambda x:x["features"][12]["geometry"].update(volume_type=11),
    lambda x:x["features"][12]["geometry"].update(start_native=[0,0,26]),
    lambda x:x["operations"][2]["assigned_tool"].update(native_id=999),
    lambda x:x["features"][0]["geometry"].update(suppressed=True),
    lambda x:x["features"].append(deepcopy(x["features"][12])),
])
def test_pocket_rejects_bad_delta(change):
    b=sketched(state());a=pocket(b);change(a)
    with pytest.raises(ValueError):d.verify_pocket_delta(b,a,210,69,SPEC,13.2)

@pytest.mark.parametrize("change",[
    lambda x:x["operations"][4].update(mill_operation_type=8),
    lambda x:x["operations"][5].update(mill_operation_type=True),
    lambda x:x["operations"][0]["assigned_tool"].update(native_id=999),
    lambda x:x["operations"][4].update(toolpath_generated=True),
    lambda x:x["operations"][4].update(linked_feature_ids=[64]),
])
def test_gop_rejects_bad_delta(change):
    b=pocket(sketched(state()));a=planned(b);change(a)
    with pytest.raises(ValueError):d.verify_pocket_operations(b,a,210,93)

class Session:
    def __init__(self,*a):self.active=False;self.started=False
    def __enter__(self):self.active=True;self.started=True;return self
    def __exit__(self,*a):self.active=False
    def summary(self):return dict(subscribed=self.started,active=self.active,
        disconnected=self.started and not self.active,event_count=0)

@pytest.fixture
def engine(monkeypatch,tmp_path):
    env=SimpleNamespace(anchor=Anchor(),calls=[],failure=None,open_guards=0,save_count=0,sketch_result=None)
    env.original_anchor=env.anchor
    env.current=deepcopy(env.anchor.state);env.details=deepcopy(env.anchor.details)
    env.marker=tmp_path/"attempt.json";env.route=dict(pin=dict(path="route",sha256=SOURCE),sources=[])
    import scripts.sw_cam_events as events
    monkeypatch.setattr(events,"CamMessageSession",Session)
    monkeypatch.setattr(m,"validate_add_pocket_request",lambda **a:env.marker if not env.marker.exists()
        else (_ for _ in ()).throw(ValueError("prior attempt")))
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**k:env.anchor)
    monkeypatch.setattr(m,"load_circle_route",lambda *a:env.route)
    monkeypatch.setattr(m,"check_circle_route",lambda *a:None)
    monkeypatch.setattr(m,"_bootstrap",lambda *a:"app")
    monkeypatch.setattr(m,"_typed",lambda obj,*a:obj)
    monkeypatch.setattr(m,"raw_part_identity",lambda *a:deepcopy(env.current["document"]))
    monkeypatch.setattr(m,"_file_hash",lambda *a:env.current["saved_file_sha256"])
    monkeypatch.setattr(m,"_nonnull",lambda *a:a[0])
    monkeypatch.setattr(m,"_object_id",lambda doc,obj,read:69 if obj=="setup" else 210)
    monkeypatch.setattr(m,"_select_plane",lambda *a:None)
    monkeypatch.setattr(m,"sketch_snapshot",lambda *a:(dict(features=deepcopy(env.current["sw_reference"]["feature_tree"]),
        solids=deepcopy(env.current["sw_reference"]["solids"]),needs_save=False,spec=SPEC),"model",[]))
    def create(*arguments):
        assert json.loads(env.marker.read_text(encoding="utf-8"))["stage"]=="sketch"
        env.calls.append("sketch");env.current=sketched(env.current)
        if env.failure=="sketch_native":raise RuntimeError("partial sketch")
        return [r["name"] for r in CREATED]
    monkeypatch.setattr(m,"create_sketch",create)
    class Guard:
        def __init__(self,*a,**k):self.used=False
        def __enter__(self):env.open_guards+=1;return self
        def __exit__(self,*a):env.open_guards-=1
        def typed(self,obj,*a):return obj
        def read(self,obj,name,*a):return member(obj,name,*a)
        def dispatch_once(self,fn,*,persist_pending):
            assert not self.used;self.used=True;persist_pending()
            if env.failure=="pending" or (env.failure=="feature_pending"
                and json.loads(env.marker.read_text(encoding="utf-8"))["stage"]=="feature"):
                raise RuntimeError("changed after marker")
            return fn()
        def summary(self):return dict(active=False,native_call_attempted=self.used)
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",Guard)
    def member(obj,name,*a):
        if name=="GetProcessID":return 17848
        if name=="GetCWObjectFromID":return ("pocket",True)
        if name=="GetOwner":return "setup"
        if name=="Suppressed":return False
        if name=="CreateMillFeature2":
            assert a==(0,"CAM_CYLINDER",False,13.2,False,False,False,False,0.,-1,False,0,0)
            assert env.current["saved_file_sha256"]==SKETCH
            assert json.loads(env.marker.read_text(encoding="utf-8"))["stage"]=="feature"
            env.calls.append("feature");env.current=pocket(env.current)
            if env.failure=="feature_native":raise RuntimeError("partial feature")
            if env.failure=="feature_bad":env.current["features"][12]["geometry"]["depth_native"]=14
            return "pocket"
        if name=="GenerateOpPlan":
            assert a==(1,) and env.open_guards==1
            assert json.loads(env.marker.read_text(encoding="utf-8"))["stage"]=="gop"
            env.calls.append("gop");env.current=planned(env.current)
            if env.failure=="gop_native":raise RuntimeError("partial gop")
            if env.failure=="gop_bad":env.current["operations"][4]["mill_operation_type"]=8
            return 0
        if name=="SaveActiveDocument":
            assert env.open_guards==0
            env.save_count+=1;stage="save_sketch" if env.save_count==1 else "save"
            assert json.loads(env.marker.read_text(encoding="utf-8"))["stage"]==stage
            env.calls.append(stage)
            if env.failure==stage+"_native":raise RuntimeError("partial save")
            env.current["saved_file_sha256"]=SKETCH if env.save_count==1 else SAVED
            env.current["document"]["needs_save"]=False
            if env.failure==stage+"_drift":env.current["operations"][0]["assigned_tool"]["native_id"]=999
            return 0
        raise AssertionError((obj,name,a))
    monkeypatch.setattr(m,"_member",member)
    def capture(*a,**kw):
        phase=kw["diagnostic"]["phase"]
        if env.failure==phase+"_capture":raise RuntimeError("capture failed")
        assert kw["expected_feature_count"]==len(env.current["features"])
        diag=kw["diagnostic"];diag["operation_details"]=deepcopy(env.details)
        if phase!="before" or env.args["action"]=="create_pocket_plan":diag["operation_details"]["new_sketch"]=sketch_observation()
        if phase in ("after_feature","after","saved"):diag["operation_details"]["new_circle"]=circle_observation()
        return deepcopy(env.current),dict(app="app",doc="doc",setups=["setup","s2","s3"])
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    env.args=args(tmp_path)
    return env

def run(env):
    if env.sketch_result is None:
        first=m.add_circular_pocket_plan(None,None,None,**env.args)
        if first["status"]!="review_required":return first
        env.sketch_result=first
        env.anchor=saved.AddedPocketEvidence(first,dict(path="sketch",sha256="d"*64),
            env.original_anchor,env.route)
        env.anchor.check_files=lambda:None
        env.anchor.check_runtime_identity=lambda:None
        env.args.update(action="create_pocket_plan",expected_source_sha256=SKETCH,
            saved_plan_receipt_path="sketch",saved_plan_receipt_sha256="d"*64,
            receipt_path=str(Path(env.args["receipt_path"]).with_name("pocket_result.json")))
        env.marker=env.marker.with_name("pocket_attempt.json")
    return m.add_circular_pocket_plan(None,None,None,**env.args)


def test_native_lifecycle_and_saved_evidence(engine):
    result=run(engine)
    assert result["status"]=="review_required",result
    assert engine.calls==["sketch","save_sketch","feature","gop","save"]
    assert result["model_saved"] and not result["cones_completed"] and not result["physical_depth_verified"]
    profile=d.profile_for_action(engine.anchor,engine.args)
    assert saved.validate_saved_pocket(result,engine.anchor,profile,engine.route,process_id=17848,
        document_path="C:/test/part.sldprt",source_sha=SAVED)
    again=run(engine)
    assert again["status"]=="error"
    assert engine.calls==["sketch","save_sketch","feature","gop","save"]

@pytest.mark.parametrize("failure",[
    "pending","sketch_native","after_sketch_capture","save_sketch_native","save_sketch_drift",
    "feature_native","feature_bad","after_feature_capture","gop_native","gop_bad",
    "after_capture","save_native","save_drift","saved_capture",
])
def test_unknown_or_bad_result_stops_without_replay(engine,failure):
    engine.failure=failure
    out=run(engine)
    assert out["status"]=="uncertain"
    assert not out["model_saved"] and not out["readback_verified"]
    prior=list(engine.calls);run(engine);assert engine.calls==prior
    if failure.startswith("feature") or failure=="after_feature_capture":assert "gop" not in engine.calls
    if failure in ("gop_bad","after_capture"):assert "save" not in engine.calls

@pytest.mark.parametrize("change",[
    lambda x:x.update(model_saved=False),
    lambda x:x["saved"]["features"][0]["geometry"].update(depth_native=888),
    lambda x:x["saved"]["operations"][0]["assigned_tool"].update(native_id=888),
    lambda x:x.update(cones_completed=True),
    lambda x:x["attempts"].pop(1),
])
def test_saved_adapter_rejects_forged_completion(engine,change):
    out=run(engine);assert out["status"]=="review_required"
    change(out)
    with pytest.raises((ValueError,KeyError)):
        saved.validate_saved_pocket(out,engine.anchor,d.profile_for_action(engine.anchor,engine.args),
            engine.route,process_id=17848,document_path="C:/test/part.sldprt",source_sha=SAVED)

def test_saved_sketch_is_separate_valid_continuation(engine):
    first=m.add_circular_pocket_plan(None,None,None,**engine.args)
    assert first["status"]=="review_required" and engine.calls==["sketch","save_sketch"]
    assert saved.validate_saved_pocket(first,engine.original_anchor,
        d.profile_for_action(engine.original_anchor,engine.args),engine.route,
        process_id=17848,document_path="C:/test/part.sldprt",source_sha=SKETCH)
    assert first["scope"]==d.SKETCH_SCOPE and not first["feature_delta_verified"]

def test_new_stage_pins_saved_circle_dimensions(engine):
    out=run(engine);assert out["model_saved"]
    engine.args["depth_native"]=13.5
    with pytest.raises(ValueError):d.profile_for_action(engine.anchor,engine.args)

def test_saved_sketch_survives_failure_before_pocket_dispatch(engine):
    engine.failure="feature_pending"
    out=run(engine)
    assert out["status"]=="uncertain"
    assert engine.calls==["sketch","save_sketch"]
    assert engine.current["saved_file_sha256"]==SKETCH
    first=engine.sketch_result
    assert saved.validate_saved_pocket(first,engine.original_anchor,first["profile"],engine.route,
        process_id=17848,document_path="C:/test/part.sldprt",source_sha=SKETCH)
    run(engine)
    assert engine.calls==["sketch","save_sketch"]
