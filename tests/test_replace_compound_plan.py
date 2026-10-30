import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import sw_cam_replace_compound_plan as m
from scripts import sw_cam_compound_plan_delta as d
from scripts import sw_cam_replaced_plan_evidence as saved

SOURCE="a"*64
SAVED="b"*64

def state():
    out=json.loads((Path(__file__).parent/"saved_plan_fixture.json").read_text(encoding="utf-8"))
    out["document"]=dict(path="C:/test/part.sldprt",title="part.sldprt",type=1,needs_save=False)
    out["saved_file_sha256"]=SOURCE
    for oid,kind,tid,ttype in ((195,8,197,6),(196,2,198,2)):
        row=deepcopy(out["operations"][0])
        row.update(native_id=oid,mill_operation_type=kind,linked_feature_ids=[64],operation_index=len(out["operations"]))
        row["assigned_tool"].update(native_id=tid,tool_type_raw=ttype)
        out["operations"].append(row)
    out["operation_count"]=4;out["operation_counts"][0]=4
    out["operation_setups"][0]["operation_count"]=4
    return out

def replaced(before,reuse=False):
    out=deepcopy(before)
    old=[r for r in out["operations"] if r["linked_feature_ids"]==[64]]
    out["operations"]=[r for r in out["operations"] if r not in old]
    for i,(oid,kind) in enumerate(((195 if reuse else 210,0),(196 if reuse else 211,1))):
        row=deepcopy(old[i])
        row.update(native_id=oid,mill_operation_type=kind,operation_index=len(out["operations"]))
        row["assigned_tool"].update(native_id=220,tool_type_raw=1)
        out["operations"].append(row)
    out["document"]["needs_save"]=True
    return out

def protected_details():
    full=dict(tool_native_id=145,geometry_read_complete=True,profile_complete=True,segments=[1,2,3])
    return dict(metadata_read_complete=True,profile_complete=True,
        generic_operation_context_unchanged=True,canonical_state_changed=False,
        items=[dict(operation_native_id=oid,full_tool=deepcopy(full)) for oid in (143,144)])

class Anchor:
    def __init__(self):
        self.state=state();self.operation_ids=[143,144];self.tool_id=145
        self.selected=dict(feature_native_id=79,owner_setup_native_id=69)
        self.baseline_tool_details=protected_details();self.pins=[]
        self.receipt_pin={"path":"saved","sha256":SOURCE}
        step=dict(feature_native_id=64,owner_setup_native_id=69,number_of_steps=3,observed_steps=[])
        self.profile=dict(pin={"path":"profile","sha256":SOURCE},details=step)
        self.details=dict(selected_tool_details=deepcopy(self.baseline_tool_details),
            three_step_profile={"compound_strategy":deepcopy(step)},
            strategy={"compound_strategy":dict(attribute_id=1,attribute_name="MSH1(mm)",
                active_attribute_name="MSH1(mm)",mill_attributes={"names_enumeration_verified":True,"values":["Rough-Finish"]})})
        self.data=dict(scope="MILL_APPEND_OPERATIONS_V1",saved_details=deepcopy(self.details))
    def summary(self):return {"scope":"appended","source":SOURCE}
    def check_files(self):pass
    def check_runtime_identity(self):pass
    def read_stock(self,*a):pass
    def verify(self,actual):
        if self.state!=actual:raise ValueError("anchor changed")

class Session:
    def __init__(self,*a):self.active=False;self.started=False
    def __enter__(self):self.active=True;self.started=True;return self
    def __exit__(self,*a):self.active=False
    def summary(self):return dict(subscribed=self.started,active=self.active,disconnected=self.started and not self.active,event_count=0)

@pytest.fixture
def engine(monkeypatch,tmp_path):
    env=SimpleNamespace(anchor=Anchor(),calls=[],mutations=[],lookup=9,gop_result=0,save_result=0,
        failure=None,open_guards=0,strategy_id=1,strategy_name="MSH1(mm)",captures=[],reuse=False)
    env.current=deepcopy(env.anchor.state);env.details=deepcopy(env.anchor.details)
    env.marker=tmp_path/"attempt.json"
    env.route={"pin":{"path":"route","sha256":SOURCE},"sources":[]}
    import scripts.sw_cam_events as events
    class ES(Session):
        def summary(self):
            value=super().summary()
            if env.failure=="cleanup" and self.started and not self.active:value["event_count"]=1
            return value
    monkeypatch.setattr(events,"CamMessageSession",ES)
    monkeypatch.setattr(m,"validate_replace_request",lambda **args:env.marker if not env.marker.exists() else (_ for _ in ()).throw(ValueError("prior attempt")))
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**k:env.anchor)
    monkeypatch.setattr(m,"load_primary_route",lambda *a:env.route)
    monkeypatch.setattr(m,"check_primary_route",lambda *a:None)
    monkeypatch.setattr(m,"_bootstrap",lambda *a:"app")
    monkeypatch.setattr(m,"_typed",lambda obj,*a:obj)
    monkeypatch.setattr(m,"raw_part_identity",lambda *a:deepcopy(env.current["document"]))
    monkeypatch.setattr(m,"_file_hash",lambda *a:env.current["saved_file_sha256"])
    class Compound:
        def __setattr__(self,name,value):
            assert name=="Attribute"
            env.mutations.append(("Attribute",value))
            env.strategy_id=value;env.strategy_name="Rough-Finish"
            env.current["document"]["needs_save"]=True
            marker=json.loads(env.marker.read_text(encoding="utf-8"))
            assert marker["stage"]=="attribute"
            if env.failure=="attribute_native":raise RuntimeError("partial setter")
            if env.failure=="attribute_readback":env.strategy_name="wrong"
            if env.failure=="implicit_gop":env.current=replaced(env.current)
            if env.failure=="protected_tool":env.details["selected_tool_details"]["items"][0]["full_tool"]["segments"]=[7]
    compound=Compound()
    monkeypatch.setattr(m,"exact_target",lambda *a:compound)
    class Guard:
        def __init__(self,*a,**k):self.used=False
        def __enter__(self):env.open_guards+=1;return self
        def __exit__(self,*a):env.open_guards-=1
        def read(self,obj,name,*a):return member(obj,name,*a)
        def typed(self,obj,*a):return obj
        def dispatch_once(self,fn,*,persist_pending):
            assert not self.used;self.used=True
            persist_pending()
            if env.failure=="pending_boundary":raise RuntimeError("identity changed after pending")
            return fn()
        def summary(self):return {"native_call_attempted":self.used,"active":False}
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",Guard)
    def member(obj,name,*args):
        if name=="GetProcessID":return 17848
        env.calls.append((name,args))
        if name=="Attribute":return env.strategy_id
        if name=="GetAttribute":return (env.strategy_name,env.strategy_id)
        if name=="IGetActiveAttribute":return env.strategy_name
        if name=="GetTdbIdForAttribute":
            assert args==("Rough-Finish",)
            return env.lookup
        if name=="GenerateOpPlan":
            assert args==(2,) and env.open_guards==1
            assert json.loads(env.marker.read_text(encoding="utf-8"))["stage"]=="regenerate"
            env.mutations.append(("GenerateOpPlan",2))
            env.current=replaced(env.current,env.reuse)
            if env.failure=="gop_native":raise RuntimeError("partial regeneration")
            if env.failure=="sibling":env.current["operations"][0]["mill_operation_type"]=2
            if env.failure=="generated_path":env.current["operations"][2]["toolpath_record_counts"]=[1]
            if env.failure=="drill_result":env.current["operations"][2]["mill_operation_type"]=8
            if env.failure=="missing_finish":env.current["operations"][3]["mill_operation_type"]=0
            if env.failure=="strategy_after_gop":env.strategy_name="other"
            return env.gop_result
        if name=="SaveActiveDocument":
            assert env.open_guards==0,"Save must have no retained source read guard"
            assert json.loads(env.marker.read_text(encoding="utf-8"))["stage"]=="save"
            env.mutations.append(("SaveActiveDocument",))
            env.current["saved_file_sha256"]=SAVED;env.current["document"]["needs_save"]=False
            if env.failure=="save_native":raise RuntimeError("partial save")
            if env.failure=="save_delta":env.current["operations"][2]["linked_feature_ids"]=[79]
            return env.save_result
        raise AssertionError(name)
    monkeypatch.setattr(m,"_member",member)
    def capture(*a,**k):
        phase=k["diagnostic"]["phase"];env.captures.append(phase)
        if env.failure==phase:raise RuntimeError("capture failure")
        details=deepcopy(env.details)
        details["strategy"]["compound_strategy"].update(attribute_id=env.strategy_id,
            attribute_name=env.strategy_name,active_attribute_name=env.strategy_name)
        k["diagnostic"]["operation_details"]=details
        return deepcopy(env.current),{"app":"app"}
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    def run():
        output=tmp_path/("result"+str(len(list(tmp_path.glob("result*.json"))))+".json")
        args=dict(process_id=17848,expected_document_path="C:/test/part.sldprt",expected_source_sha256=SOURCE,
            saved_plan_receipt_path="saved",saved_plan_receipt_sha256=SOURCE,
            primary_route_receipt_path="route",primary_route_receipt_sha256=SOURCE,
            expected_feature_native_id=79,expected_operation_native_ids=[143,144],
            expected_operation_setup_native_id=93,expected_tool_native_id=145,
            target_feature_native_id=64,target_owner_setup_native_id=69,target_operation_setup_native_id=93,
            expected_target_operation_native_ids=[195,196],expected_target_operation_types=[8,2],
            expected_target_tool_native_ids=[197,198],expected_strategy_id=1,expected_strategy_name="MSH1(mm)",
            requested_strategy_name="Rough-Finish",save_after_verified=True,
            attempt_registry_path=str(tmp_path),qualification_only=True,acknowledge_disposable_copy=True,
            receipt_path=str(output),message_policy="vendor_default")
        return m.replace_compound_strategy_plan("sw","clsid","tlb",**args)
    env.run=run
    return env

@pytest.mark.parametrize("reuse",[False,True])
def test_single_lookup_setter_regenerate_and_saved_continuation(engine,reuse):
    engine.reuse=reuse;r=engine.run()
    assert r["status"]=="review_required" and r["model_saved"] and r["readback_verified"]
    assert engine.mutations==[("Attribute",9),("GenerateOpPlan",2),("SaveActiveDocument",)]
    assert sum(name=="GetTdbIdForAttribute" for name,_ in engine.calls)==1
    assert engine.captures==["before","after_attribute","after","saved"]
    assert [x["stage"] for x in r["attempts"]]==["attribute","regenerate","save"]
    assert [x["mill_operation_type"] for x in r["replacement_operations"]]==[0,1]
    profile=m.validate_replacement_baseline(engine.anchor,**{k:r["request"][k] for k in m.TARGET_KEYS})
    assert saved.validate_saved_replacement(r,engine.anchor,profile,engine.route,
        process_id=17848,document_path="C:/test/part.sldprt",source_sha=SAVED)

@pytest.mark.parametrize("failure",["before","attribute_native","attribute_readback","implicit_gop",
    "protected_tool","after_attribute","pending_boundary","gop_native","sibling","generated_path",
    "drill_result","missing_finish","strategy_after_gop","after","save_native","save_delta","saved","cleanup"])
def test_faults_stop_and_never_replay(engine,failure):
    engine.failure=failure;r=engine.run()
    assert r["status"] in ("error","uncertain") and not r["model_saved"]
    assert sum(x[0]=="Attribute" for x in engine.mutations)<=1
    assert sum(x[0]=="GenerateOpPlan" for x in engine.mutations)<=1
    if failure not in ("save_native","save_delta","saved","cleanup"):
        assert not any(x[0]=="SaveActiveDocument" for x in engine.mutations)
    if failure!="before":
        before=list(engine.mutations);engine.failure=None
        assert engine.run()["status"]=="error"
        assert engine.mutations==before

@pytest.mark.parametrize("value",[None,True,False,0,-1,"9"])
def test_invalid_lookup_never_mutates(engine,value):
    engine.lookup=value;r=engine.run()
    assert r["status"]=="error" and not engine.mutations
    assert sum(name=="GetTdbIdForAttribute" for name,_ in engine.calls)==1

@pytest.mark.parametrize("field",["gop_result","save_result"])
@pytest.mark.parametrize("value",[None,True,False,-1,1,"0"])
def test_hresult_not_coerced(engine,field,value):
    setattr(engine,field,value);r=engine.run()
    assert r["status"]=="uncertain" and not r["model_saved"]
    if field=="gop_result":assert not any(x[0]=="SaveActiveDocument" for x in engine.mutations)

@pytest.mark.parametrize("change",[
    lambda a:a["operations"][0].update(native_id=55),
    lambda a:a["operations"].reverse(),
    lambda a:a["operations"][0]["assigned_tool"].update(cut_diameter_native=5),
    lambda a:a["operations"][2].update(suppressed=True),
    lambda a:a["operations"][2].update(linked_feature_ids=[64,79]),
    lambda a:a["operations"][2].update(setup_native_id=94),
    lambda a:a["operations"][2].update(mill_operation_type=True),
    lambda a:a["operations"][2].update(toolpath_generated=True),
    lambda a:a["features"][0]["geometry"].update(depth_native=3),
    lambda a:a["stock"].update(unknown_change=True),
    lambda a:a["sw_reference"]["solids"][0].update(unknown_change=True),
    lambda a:a.update(saved_file_sha256="c"*64),
])
def test_replacement_rejects_unrelated_or_invalid_delta(change):
    before=state();after=replaced(before);change(after)
    with pytest.raises(ValueError):d.verify_replaced_plan(before,after,64,93)

def test_protected_indices_may_shift_but_relative_order_must_stay():
    before=state();after=replaced(before)
    after["operations"]=after["operations"][2:]+after["operations"][:2]
    for i,row in enumerate(after["operations"]):row["operation_index"]=i
    assert len(d.verify_replaced_plan(before,after,64,93))==2

@pytest.mark.parametrize("change",[
    lambda r:r.update(gop_hresult=True),
    lambda r:r.update(save_hresult=None),
    lambda r:r.update(immediate_strategy_readback_verified=False),
    lambda r:r.update(explicit_delete_attempted=True),
    lambda r:r.update(global_GOP_attempted=True),
    lambda r:r.update(lookup_id=0),
    lambda r:r["attempts"].append(dict(stage="extra")),
    lambda r:r["messages"].update(event_count=1),
    lambda r:r["after_attribute"]["operations"][0].update(suppressed=True),
    lambda r:r["saved"]["operations"][2].update(mill_operation_type=8),
])
def test_saved_proof_rejects_false_success(engine,change):
    r=engine.run();change(r)
    profile=m.validate_replacement_baseline(engine.anchor,**{k:r["request"][k] for k in m.TARGET_KEYS})
    with pytest.raises(ValueError):saved.validate_saved_replacement(r,engine.anchor,profile,engine.route,
        process_id=17848,document_path="C:/test/part.sldprt",source_sha=SAVED)
