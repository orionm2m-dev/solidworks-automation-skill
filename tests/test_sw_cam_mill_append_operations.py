import json
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import pytest
from scripts import sw_cam_mill_append_operations as m
from scripts import sw_cam_mill_append_evidence as e
from scripts import sw_cam_mill_appended_plan_evidence as saved
from scripts.sw_cam_turn_tool import _digest

SOURCE = "a" * 64
SAVED = "b" * 64

def state():
    value = json.loads((Path(__file__).parent / "saved_plan_fixture.json").read_text(encoding="utf-8"))
    value["document"] = dict(path="C:/test/part.sldprt",title="part.sldprt",type=1,needs_save=False)
    value["saved_file_sha256"] = SOURCE
    return value

def added(before):
    after = deepcopy(before)
    row = deepcopy(after["operations"][0])
    row.update(native_id=200, linked_feature_ids=[64], operation_index=0)
    row["assigned_tool"]["native_id"] = 201
    for existing in after["operations"]:
        existing["operation_index"] += 1
    after["operations"].insert(0,row)
    after["operation_counts"][0] += 1
    after["operation_count"] += 1
    after["operation_setups"][0]["operation_count"] += 1
    after["document"]["needs_save"] = True
    return after

def full_details():
    tool = dict(tool_native_id=145,geometry_read_complete=True,profile_complete=True,
                profile={"segments":[{"radius":1.5,"length":39}]})
    return dict(metadata_read_complete=True,profile_complete=True,
        generic_operation_context_unchanged=True,canonical_state_changed=False,
        items=[dict(operation_native_id=x,full_tool=deepcopy(tool)) for x in (143,144)])

class Anchor:
    def __init__(self):
        self.state=state()
        self.operation_ids=[143,144];self.tool_id=145
        self.selected=dict(feature_native_id=79,owner_setup_native_id=69)
        self.baseline_tool_details=full_details()
        self.data={"scope":"MILL_SAVED_SHARED_CUTTER_CONFIG_V1"}
        self.pins=[]
    def summary(self):return dict(scope="configured",source=SOURCE)
    def check_files(self):pass
    def check_runtime_identity(self):pass
    def verify(self,actual):
        if self.state != actual:raise ValueError("baseline changed")

def profile(anchor):
    header=next(r["geometry"] for r in anchor.state["features"] if r["geometry"]["native_id"]==64)
    return dict(pin={"path":"profile","sha256":SOURCE},header=deepcopy(header),
        details=dict(metadata_read_complete=True,feature_native_id=64,owner_setup_native_id=69,
            number_of_steps=3,complete_step_coverage=True,index_base_verified=True,observed_steps=[]))

class Session:
    def __init__(self,*args):self.active=False;self.started=False
    def __enter__(self):self.active=True;self.started=True;return self
    def __exit__(self,*args):self.active=False
    def summary(self):
        return dict(subscribed=self.started,active=self.active,disconnected=self.started and not self.active,event_count=0)

@pytest.fixture
def engine(monkeypatch,tmp_path):
    env=SimpleNamespace(anchor=Anchor(),calls=[],failure=None,result=0,save_result=0,
                        captures=[],writes=[],events_bad=False)
    env.current=deepcopy(env.anchor.state);env.profile=profile(env.anchor)
    env.details=dict(selected_tool_details=full_details(),
        three_step_profile={"compound_strategy":deepcopy(env.profile["details"])},
        strategy={"compound_strategy":dict(metadata_read_complete=True,attribute_id=1,attribute_name="MSH1(mm)")})
    env.marker=tmp_path/"attempt.json"
    import scripts.sw_cam_events as events
    class FaultSession(Session):
        def summary(self):
            result=super().summary()
            if env.events_bad or (env.failure=="cleanup" and self.started and not self.active):
                result["event_count"]=1
            return result
    monkeypatch.setattr(events,"CamMessageSession",FaultSession)
    def validation(**kwargs):
        if env.marker.exists():raise ValueError("prior marker")
        return env.marker
    monkeypatch.setattr(m,"validate_append_request",validation)
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**k:env.anchor)
    monkeypatch.setattr(m,"load_target_profile",lambda *a,**k:env.profile)
    monkeypatch.setattr(m,"read_pin",lambda *a:({},env.profile["pin"]))
    monkeypatch.setattr(m,"_bootstrap",lambda *a:"app")
    monkeypatch.setattr(m,"raw_part_identity",lambda *a:deepcopy(env.current["document"]))
    monkeypatch.setattr(m,"_file_hash",lambda p:env.current["saved_file_sha256"])
    monkeypatch.setattr(m,"_typed",lambda raw,*a:raw)
    monkeypatch.setattr(m,"exact_target",lambda *a:"feature64")
    def capture(*args,**kwargs):
        phase=kwargs["diagnostic"]["phase"];env.captures.append(phase)
        if env.failure==phase:raise RuntimeError("capture failure")
        kwargs["diagnostic"]["operation_details"]=deepcopy(env.details)
        # Additional diagnostics must not participate in stable metadata equality.
        kwargs["diagnostic"]["operation_details"]["operation_details_context_recheck"]={"count":env.current["operation_count"]}
        return deepcopy(env.current),dict(app="app")
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    original_write=m._write_receipt
    def write(path,report,**kwargs):
        env.writes.append((str(path),deepcopy(report)))
        if env.failure=="pending_write" and report.get("phase")=="GenerateOpPlan":
            raise OSError("receipt disk unavailable")
        return original_write(path,report,**kwargs)
    monkeypatch.setattr(m,"_write_receipt",write)
    def member(obj,name,*args):
        if name=="GetProcessID":return 17848
        env.calls.append((obj,name,args))
        if name=="GenerateOpPlan":
            marker=json.loads(env.marker.read_text(encoding='utf-8'))
            receipt=json.loads(Path(marker["receipt_path"]).read_text(encoding='utf-8'))
            assert marker["status"]=="dispatch_pending"
            assert receipt["native_dispatch_pending"] is True
            env.current=added(env.current)
            if env.failure=="native":raise RuntimeError("partial native mutation")
            if env.failure=="existing_tool":
                env.details["selected_tool_details"]["items"][0]["full_tool"]["profile"]["segments"][0]["length"]=40
            if env.failure=="sibling":env.current["operations"][1]["mill_operation_type"]=5
            if env.failure=="target":env.details["three_step_profile"]["compound_strategy"]["observed_steps"]=[1]
            if env.failure=="strategy":env.details["strategy"]["compound_strategy"]["attribute_id"]=2
            if env.failure=="path":env.current["operations"][0]["toolpath_generated"]=True
            if env.failure=="wrong_target":env.current["operations"][0]["linked_feature_ids"]=[80]
            if env.failure=="event":env.events_bad=True
            return env.result
        if name=="SaveActiveDocument":
            env.current["saved_file_sha256"]=SAVED
            env.current["document"]["needs_save"]=False
            if env.failure=="save_native":raise RuntimeError("partial save")
            if env.failure=="save_delta":env.current["operations"][0]["suppressed"]=True
            return env.save_result
        raise AssertionError(name)
    monkeypatch.setattr(m,"_member",member)
    def run(save=True):
        receipt=tmp_path/("report"+str(len(list(tmp_path.glob("report*.json"))))+".json")
        return m.append_mill_operations("sw","clsid","tlb",process_id=17848,
            expected_document_path="C:/test/part.sldprt",expected_source_sha256=SOURCE,
            saved_plan_receipt_path="saved",saved_plan_receipt_sha256=SOURCE,
            target_profile_receipt_path="profile",target_profile_receipt_sha256=SOURCE,
            expected_feature_native_id=79,expected_operation_native_ids=[143,144],
            expected_operation_setup_native_id=93,expected_tool_native_id=145,
            target_feature_native_id=64,target_owner_setup_native_id=69,target_operation_setup_native_id=93,
            expected_strategy_id=1,expected_strategy_name="MSH1(mm)",save_after_verified=save,
            attempt_registry_path=str(tmp_path),qualification_only=True,acknowledge_disposable_copy=True,
            receipt_path=str(receipt))
    env.run=run
    return env

def test_append_then_save_preserves_all_prior_state(engine):
    result=engine.run()
    assert result["status"]=="review_required" and result["operation_delta_verified"]
    assert result["model_saved"] and result["save_readback_verified"]
    assert engine.calls==[("feature64","GenerateOpPlan",(1,)),("app","SaveActiveDocument",())]
    assert engine.captures==["before","after","saved"]
    assert result["saved_file_sha256"]==SAVED
    assert result["messages"]["disconnected"]
    assert json.loads(engine.marker.read_text(encoding='utf-8'))["status"]=="review_required"
    assert saved.validate_saved_append(result,engine.anchor,engine.profile,
        process_id=17848,document_path="C:/test/part.sldprt",source_sha=SAVED)

def test_no_save_unless_explicitly_requested(engine):
    result=engine.run(False)
    assert result["readback_verified"] and not result["model_saved"]
    assert result["saved_file_sha256"]==SOURCE
    assert len(engine.calls)==1 and "saved" not in result

@pytest.mark.parametrize("failure",["before","after","native","sibling","existing_tool","target",
    "strategy","path","wrong_target","event","cleanup","save_native","save_delta","saved","pending_write"])
def test_failures_stop_without_replay(engine,failure):
    engine.failure=failure;result=engine.run()
    assert result["status"] in ("error","uncertain")
    assert not result["readback_verified"] and not result["model_saved"]
    assert len([c for c in engine.calls if c[1]=="GenerateOpPlan"])<2
    if failure not in ("cleanup","save_native","save_delta","saved"):
        assert not any(c[1]=="SaveActiveDocument" for c in engine.calls)
    if failure=="before":assert engine.calls==[] and not engine.marker.exists()
    else:
        assert engine.marker.exists()
        count=len(engine.calls);engine.failure=None
        retry=engine.run()
        assert retry["status"]=="error" and len(engine.calls)==count

@pytest.mark.parametrize("value",[None,True,False,1,-1,"0"])
def test_hresult_not_coerced(engine,value):
    engine.result=value;r=engine.run()
    assert r["status"]=="uncertain" and len(engine.calls)==1
    assert engine.captures==["before"]

@pytest.mark.parametrize("value",[None,True,False,1,-1,"0"])
def test_save_hresult_not_coerced(engine,value):
    engine.save_result=value;r=engine.run()
    assert r["status"]=="uncertain" and not r["model_saved"]
    assert engine.captures==["before","after"]

def test_current_target_already_planned_is_rejected_before_dispatch(engine):
    engine.anchor.state=added(engine.anchor.state)
    engine.anchor.state["document"]["needs_save"]=False
    engine.current=deepcopy(engine.anchor.state)
    r=engine.run()
    assert r["status"]=="error" and not engine.calls

@pytest.mark.parametrize("mutate",[
    lambda r:r.update(save_hresult=True),
    lambda r:r.update(native_hresult=None),
    lambda r:r.update(model_saved=False),
    lambda r:r.update(native_dispatch_pending=True),
    lambda r:r.update(issue={"type":"failure"}),
    lambda r:r["messages"].update(event_count=1),
    lambda r:r["saved"]["operations"][0].update(linked_feature_ids=[80]),
    lambda r:r["after"]["operations"][1].update(toolpath_generated=True),
    lambda r:r["saved_details"]["selected_tool_details"]["items"][0]["full_tool"].update(profile_complete=False),
])
def test_appended_saved_evidence_rejects_unproven_results(engine,mutate):
    data=engine.run();mutate(data)
    with pytest.raises(ValueError):
        saved.validate_saved_append(data,engine.anchor,engine.profile,
            process_id=17848,document_path="C:/test/part.sldprt",source_sha=SAVED)

def test_full_tool_guard_rejects_uncovered_prior_operation():
    anchor=Anchor();anchor.state=added(anchor.state)
    with pytest.raises(ValueError):e.require_protected_tools(anchor,anchor.state,full_details())

def test_marker_key_stable_across_receipt_and_pid_changes(tmp_path):
    a=e.attempt_marker(str(tmp_path),"C:/test/part.sldprt",SOURCE,64)
    assert a==e.attempt_marker(str(tmp_path),"C:/test/part.sldprt",SOURCE,64)
    assert a!=e.attempt_marker(str(tmp_path),"C:/test/part.sldprt",SOURCE,65)

def test_exact_target_revalidates_header_and_reverse_id(monkeypatch):
    anchor=Anchor();p=profile(anchor)
    monkeypatch.setattr(m,"read_header",lambda *a:(deepcopy(p["header"]),"base"))
    monkeypatch.setattr(m,"_object_id",lambda *a:64)
    read=lambda *a:("raw",True)
    assert m.exact_target({"doc":"doc"},p,64,69,read,lambda *a:None)=="base"
    monkeypatch.setattr(m,"_object_id",lambda *a:79)
    with pytest.raises(ValueError):m.exact_target({"doc":"doc"},p,64,69,read,lambda *a:None)
