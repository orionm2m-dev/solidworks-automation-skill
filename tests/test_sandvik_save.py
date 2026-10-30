"""No native process is used: receipt validation and one-save fault injection."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from copy import deepcopy
import pytest

ROOT=Path(os.environ.get("SOLIDWORKS_SKILL_ROOT",Path(__file__).resolve().parents[1]))
STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import scripts
PHASE=STAGE.parents[1]/"parallel_execution/upper_strategy_review_20261029/staged_sandvik_phase1"
FIRST=STAGE.parent/"rough_firstcut_stock_20261029"
for directory in (STAGE,PHASE,FIRST):
    if (directory/"scripts").is_dir():scripts.__path__.insert(0,str(directory/"scripts"))
from scripts import sw_cam_sandvik_save as m

def blob(path, value):
    raw=json.dumps(value,sort_keys=True).encode() if type(value) is dict else value
    path.write_bytes(raw)
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())

def context(doc,sha):
    return dict(document=deepcopy(doc),saved_file_sha256=sha,
        features=[{"geometry":{"native_id":i}} for i in range(19)],
        operations=[dict(native_id=i,toolpath_generated=False,toolpath_record_counts=[]) for i in range(6)],
        sw_reference=dict(solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.,2.,3.,4.])]))

@pytest.fixture
def evidence(tmp_path,monkeypatch):
    src=blob(tmp_path/"part.SLDPRT",b"saved")
    doc=dict(path=src["path"],title="part.SLDPRT",type=1,needs_save=True)
    state=context(doc,src["sha256"])
    old=[dict(native_id=145,tool_type_raw=1,CutDiameter=2.,Protrusion=20.,StnNo=1.)]
    new=dict(native_id=250,tool_type_raw=14,CutDiameter=8.,Protrusion=25.,StnNo=2.)
    asset=blob(tmp_path/"candidate.mt",b"candidate")
    hp=blob(tmp_path/"holder.mh",b"holder")
    cp=blob(tmp_path/"candidate.json",{})
    rp=blob(tmp_path/"plan.json",{})
    fp=blob(tmp_path/"firstcut.json",{})
    settings=dict(direct_type=0,toolpath_parameters={"first_cut_Z_type_raw":0})
    args=dict(process_id=23824,expected_document_path=src["path"],expected_source_sha256=src["sha256"],
        expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145,
        saved_plan_receipt_path=rp["path"],saved_plan_receipt_sha256=rp["sha256"],
        qualification_only=True,acknowledge_disposable_copy=True,message_policy="vendor_default",
        receipt_path=str(tmp_path/"save.json"),expected_candidate_tool_native_id=250,
        phase1_receipt_path=str(tmp_path/"phase1.json"),phase1_receipt_sha256="a"*64)
    binding={k:args[k] for k in m.BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
    binding.update(firstcut_receipt_path=fp["path"],firstcut_receipt_sha256=fp["sha256"])
    anchor=SimpleNamespace(state=dict(state,document=dict(doc,needs_save=False)),
        data=dict(scope="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1",
            new_operations=[dict(native_id=247,mill_operation_type=0,setup_native_id=93)],
            new_feature_native_id=244),
        pins=[rp],summary=lambda:dict(scope="test"),check_files=lambda:None,
        check_runtime_identity=lambda:None,verify=lambda s:None)
    tool=dict(native_id=250,tool_type_raw=14,profile_complete=True,
        mt_path_raw=asset["path"],parameters=dict(m.FIELDS),profiles=dict(tool={},shank={}),
        units_verified=False,cutting_partition_verified=False)
    data=dict(scope=m.PHASE1_SCOPE,status="review_required",phase="finished",process_id=23824,
        expected_document_path=src["path"],expected_source_sha256=src["sha256"],
        source_before_sha256=src["sha256"],new_tool_native_id=250,request_binding=binding,
        before=deepcopy(state),after=deepcopy(state),before_document=deepcopy(doc),after_document=deepcopy(doc),
        firstcut_anchor=dict(pin=fp,after_settings=settings),before_firstcut=settings,after_firstcut=settings,
        anchor=anchor.summary(),before_tools=deepcopy(old),after_tools=deepcopy(old)+[new],tool=tool,
        candidate_asset=asset,candidate_contract=dict(pins=[cp]),holder_recipe=dict(pins=[hp],file_path=hp["path"]),
        holder_profile={"status":"observed"},final_scalar_observation=dict(m.FIELDS),
        metric_scope=dict(SW_document_units_raw=[0,1,0,2,0],CAM_use_document_units_raw=True),
        messages=dict(subscribed=True,disconnected=True,active=False),
        dispatches=[dict(label=x,attempted=True,returned=True,pending=False) for x in
            ("AddNewTool3","SetToolName","SetFilePathForUserDefinedHolder",
             "CreateSTLOfCuttingPortion","CreateSTLOfNonCuttingPortion")])
    data.update({k:True for k in m.TRUE_FLAGS});data.update({k:False for k in m.FALSE_FLAGS})
    data["exports"]={k:dict(pin=blob(tmp_path/(k+".stl"),b"mesh"),portion=k,mesh_health_verified=True)
                     for k in ("cutting","noncutting")}
    marker=m.attempt_marker(src["path"],src["sha256"],asset["sha256"])
    data["dispatch_marker_path"]=str(marker)
    def publish():
        blob(marker,dict(scope=m.PHASE1_SCOPE,phase="finished",status="review_required",
            native_dispatch_pending=False,new_tool_native_id=250,source_sha256=src["sha256"],
            candidate_sha256=asset["sha256"],dispatches=data["dispatches"],automatic_replay=False,
            document=src["path"],receipt_path=args["phase1_receipt_path"]))
        pin=blob(Path(args["phase1_receipt_path"]),data);args["phase1_receipt_sha256"]=pin["sha256"]
    publish()
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**kw:anchor)
    monkeypatch.setattr(m,"load_firstcut_receipt",lambda *a,**kw:dict(after_settings=settings,after_document=deepcopy(doc)))
    monkeypatch.setattr(m,"validate_native_profiles",lambda *a:None)
    monkeypatch.setattr(m,"verify_holder_profile",lambda *a:None)
    return SimpleNamespace(args=args,data=data,anchor=anchor,doc=doc,publish=publish,source=src,
                           load=lambda:m.load_stage1_for_save(**args))

def simple_compare(a,b,dirty,source):
    x=deepcopy(a)
    if dirty:x["document"]["needs_save"]=b["document"]["needs_save"]
    if source:x["saved_file_sha256"]=b["saved_file_sha256"]
    return x==b

def test_accepts_successful_stage1_with_dirty_document_and_pending_physical(evidence):
    out=evidence.load()
    assert out["data"]["after_document"]["needs_save"] is True
    assert not out["data"]["units_verified"]
    assert out["rough_id"]==247

@pytest.mark.parametrize("flag",m.TRUE_FLAGS)
def test_incomplete_stage1_cannot_save(evidence,flag):
    evidence.data[flag]=False;evidence.publish()
    with pytest.raises(ValueError):evidence.load()

@pytest.mark.parametrize("change",[
    {"status":"uncertain"},{"issue":{}},{"readback_verified":1},
    {"model_saved":True},{"native_dispatch_pending":True},{"new_tool_native_id":True},
    {"process_id":True},{"source_before_sha256":"b"*64}])
def test_failed_or_wrong_stage1_is_not_eligible(evidence,change):
    evidence.data.update(change);evidence.publish()
    with pytest.raises(ValueError):evidence.load()

def test_creation_marker_drift_rejected(evidence):
    p=Path(evidence.data["dispatch_marker_path"])
    d=json.loads(p.read_text());d["native_dispatch_pending"]=True;blob(p,d)
    with pytest.raises(ValueError):evidence.load()

def test_asset_drift_rejected(evidence):
    Path(evidence.data["candidate_asset"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError):evidence.load()

def test_old_tool_inventory_change_rejected(evidence):
    evidence.data["after_tools"][0]["CutDiameter"]=3.;evidence.publish()
    with pytest.raises(ValueError):evidence.load()

def test_same_attempt_new_report_does_not_replay(evidence):
    loaded=evidence.load()
    blob(loaded["marker"],{"save_pending":True})
    evidence.args["receipt_path"]=str(Path(evidence.args["receipt_path"]).with_name("other.json"))
    with pytest.raises(ValueError,match="Prior save"):evidence.load()

@pytest.fixture
def simulation(evidence,monkeypatch):
    e=evidence;calls=[];guards=[];fault=dict(mode=None,result=0,after_changed=False)
    app=SimpleNamespace()
    def native_save():
        assert not guards,"Save must not own read handles"
        saved=json.loads(Path(e.args["receipt_path"]).read_text())
        marker=json.loads(Path(saved["save_marker_path"]).read_text())
        assert marker["save_pending"] and saved["save_pending"]
        calls.append("SaveActiveDocument")
        if fault["mode"]=="raise":raise RuntimeError("unknown outcome")
        if fault["result"]!=0 or type(fault["result"]) is not int:return fault["result"]
        Path(e.source["path"]).write_bytes(b"saved CAM draft")
        e.doc["needs_save"]=False
        return 0
    app.SaveActiveDocument=native_save
    old_holder=object();new_holder=SimpleNamespace(GetName=lambda:e.data["holder_recipe"]["file_path"])
    tool=SimpleNamespace(native_id=250,IGetMillToolHolder=lambda:new_holder)
    crib=SimpleNamespace(GetAllTools=lambda:[tool])
    native=dict(machine=SimpleNamespace(IGetToolcrib=lambda:crib),doc=object(),operations={247:object()})
    sw=SimpleNamespace(GetProcessID=lambda:23824,ActiveDoc=object())
    monkeypatch.setattr(m,"_bootstrap",lambda *a:app)
    monkeypatch.setattr(m,"raw_part_identity",lambda s:deepcopy(e.doc))
    monkeypatch.setattr(m,"_member",lambda o,n,*a:getattr(o,n)(*a) if callable(getattr(o,n)) else getattr(o,n))
    monkeypatch.setattr(m,"_object_id",lambda d,o,r:o.native_id)
    monkeypatch.setattr(m,"_items",lambda v,*a:v)
    def capture(*a,**kw):
        state=deepcopy(e.data["after"]);state["document"]=deepcopy(e.doc)
        state["saved_file_sha256"]=m._file_hash(e.source["path"])
        if calls and fault["mode"]=="mass_noise":
            state["sw_reference"]["solids"][0]["mass_raw"][0]+=1e-12
        if calls and fault["mode"]=="geometry":
            state["features"][0]["geometry"]["native_id"]=999
        return state,native
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    def local_tools(*a):
        out=deepcopy(e.data["after_tools"])
        if calls and fault["mode"]=="crib":out[0]["CutDiameter"]=3.
        return out
    monkeypatch.setattr(m,"capture_local_tools",local_tools)
    def read_tool(*a,**kw):
        out=deepcopy(e.data["tool"])
        if calls and fault["mode"]=="tool":out["parameters"]["CutLength"]=20.
        return out
    monkeypatch.setattr(m,"read_ud14_tool",read_tool)
    monkeypatch.setattr(m,"holder_objects",lambda *a:{145:old_holder,250:new_holder})
    monkeypatch.setattr(m,"com_identity",lambda o,r=None:id(o))
    def holder_profile(*a,**kw):
        kw["diagnostic"]["state"].update(e.data["holder_profile"])
        if calls and fault["mode"]=="holder":kw["diagnostic"]["state"]["changed"]=True
    monkeypatch.setattr(m,"read_segment_chains",holder_profile)
    def firstcut(*a):
        out=deepcopy(e.data["after_firstcut"])
        if calls and fault["mode"]=="firstcut":out["direct_type"]=1
        return out
    monkeypatch.setattr(m,"read_firstcut_settings",firstcut)
    monkeypatch.setattr(m,"read_document_cam_unit_scope",lambda *a,**kw:deepcopy(e.data["metric_scope"]))
    class Guard:
        def __init__(self,*a,**kw):self.kw=kw
        def __enter__(self):
            self.kw["verify_evidence"]();guards.append(self);return self
        def __exit__(self,*a):guards.remove(self)
        def read(self,o,n,*a):return m._member(o,n,*a)
        def typed(self,o,n):return o
        def summary(self):return {"mock":True}
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",Guard)
    import scripts.sw_cam_events as ev
    class Events:
        def __init__(self,*a):self.active=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False
        def summary(self):
            return dict(subscribed=True,active=self.active,disconnected=not self.active,
                        event_count=1 if fault["mode"]=="event" else 0)
    monkeypatch.setattr(ev,"CamMessageSession",Events)
    return SimpleNamespace(e=e,calls=calls,fault=fault,run=lambda:m.save_sandvik_draft(sw,"clsid","tlb",**e.args))

def test_one_save_reuses_pending_geometry_without_native_reopen(simulation):
    r=simulation.run()
    assert r["status"]=="review_required",r
    assert simulation.calls==["SaveActiveDocument"]
    assert r["model_saved"] and r["save_readback_verified"]
    assert r["source_before_sha256"]!=r["source_after_sha256"]
    assert not r["after_document"]["needs_save"]
    assert not r["reopen_persistence_verified"] and not r["units_verified"]
    assert not r["GTP_attempted"] and not r["creator_attempted"]

@pytest.mark.parametrize("mode",["raise","geometry","tool","holder","firstcut","crib"])
def test_unknown_or_changed_save_stops_without_retry(simulation,mode):
    simulation.fault["mode"]=mode;r=simulation.run()
    assert simulation.calls==["SaveActiveDocument"]
    assert r["status"]=="uncertain" and not r["model_saved"],r
    assert r["save_pending"] is (mode=="raise")
    marker=json.loads(Path(r["save_marker_path"]).read_text())
    assert marker["automatic_replay"] is False
    simulation.e.args["receipt_path"]=str(Path(simulation.e.args["receipt_path"]).with_name("second.json"))
    r2=simulation.run()
    assert r2["status"]=="error" and len(simulation.calls)==1

@pytest.mark.parametrize("result",[False,True,None,1,-1])
def test_nonzero_or_non_hresult_return_never_readback_or_retry(simulation,result):
    simulation.fault["result"]=result;r=simulation.run()
    assert simulation.calls==["SaveActiveDocument"]
    assert r["status"]=="uncertain" and not r["model_saved"]
    assert r["capture_count"]==1

def test_preexisting_event_blocks_save(simulation):
    simulation.fault["mode"]="event";r=simulation.run()
    assert not simulation.calls and r["status"]=="error"

def test_projection_excludes_document_noise(evidence):
    p=m.stable_payload(evidence.data)
    evidence.data["after"]["document"]["needs_save"]=False
    evidence.data["after"]["saved_file_sha256"]="f"*64
    evidence.data["after"]["sw_reference"]["solids"][0]["volume"]=9.
    assert p==m.stable_payload(evidence.data)

def test_full_context_still_checks_geometry(evidence):
    changed=deepcopy(evidence.data["after"])
    changed["sw_reference"]["solids"][0]["volume"]=9.
    with pytest.raises(ValueError):m.verify_context(evidence.data["after"],changed,after_save=True)



def test_established_mass_noise_does_not_block_one_save(simulation):
    simulation.fault["mode"]="mass_noise"
    r=simulation.run()
    assert r["status"]=="review_required" and r["model_saved"],r
    assert r["before_context"]!=r["after_context"]
    assert r["before"]==r["after"]

def test_wrong_active_document_dirty_flag_blocks_before_native_save(simulation):
    simulation.e.doc["needs_save"]=False
    r=simulation.run()
    assert r["status"]=="error" and not simulation.calls
