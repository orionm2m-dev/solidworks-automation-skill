from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_defined_rough_levels as m
from scripts import sw_cam_mill_levels as shared
from scripts import sw_cam_events as events

READS = [
    "QueryInterface.IDispatch.feature", "QueryInterface.ICWMillOperation",
    "ICWMillOperation.GetMachiningDepth", "QueryInterface.ICWMillOperation3",
    "ICWMillOperation3.GetOverrideMachiningDepth", "ICWMillOperation3.GetToolpathParam",
    "QueryInterface.ICWToolpathParam", "ICWToolpathParam.GetToolpathParameters",
    "ICWMillOperation3.GetSetupParameters", "QueryInterface.ICWPosition",
    "ICWPosition.GetCoordinates", "QueryInterface.ICWUnitVector", "ICWUnitVector.GetCoordinates",
]

def full_details():
    full=dict(tool_native_id=145,geometry_read_complete=True,profile_complete=True,segments=[1,2,3])
    return dict(metadata_read_complete=True,profile_complete=True,
        generic_operation_context_unchanged=True,canonical_state_changed=False,
        items=[dict(operation_native_id=i,full_tool=deepcopy(full)) for i in (143,144)])

@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=tmp_path/"qualification.sldprt";path.write_bytes(b"saved additive nineteen-feature plan")
    receipt=tmp_path/"levels.json";sha=m._file_hash(path)
    current=json.loads((Path(__file__).parent/"saved_plan_fixture.json").read_text(encoding="utf-8"))
    current["document"]=dict(path=str(path),title=path.name,type=1,needs_save=False)
    current["saved_file_sha256"]=sha
    for oid,kind,tid,ft in ((195,8,197,64),(196,2,198,64),(247,0,249,244),(248,1,249,244)):
        row=deepcopy(current["operations"][0])
        row.update(native_id=oid,mill_operation_type=kind,linked_feature_ids=[ft],
            operation_index=len(current["operations"]),suppressed=False,
            toolpath_generated=False,toolpath_record_counts=[])
        row["assigned_tool"].update(native_id=tid,tool_type_raw=1 if tid==249 else 6)
        current["operations"].append(row)
    current["operation_count"]=6;current["operation_counts"][0]=6
    current["operation_setups"][0]["operation_count"]=6
    f=deepcopy(current["features"][0]);f.update(setup_native_id=69,feature_index=12)
    f["geometry"].update(native_id=244,volume_type=2,suppressed=False)
    current["features"].insert(12,f);current["feature_setups"][0]["feature_count"]+=1
    protected=full_details()
    details=dict(selected_tool_details=protected,
        three_step_profile=dict(compound_strategy=dict(step_count=3,steps=[26,25.8,12.6,12.3])),
        strategy=dict(compound_strategy=dict(attribute_id=1,attribute_name="MSH1(mm)")))
    data=dict(scope="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1",new_feature_native_id=244,
        new_operations=deepcopy(current["operations"][-2:]),saved_details=deepcopy(details),
        request=dict(operation_setup_native_id=93,owner_setup_native_id=69,reference_feature_native_id=64))
    anchor=N(data=data,state=deepcopy(current),operation_ids=[143,144],tool_id=145,pins=[],
        profile=dict(header=dict(native_id=64,volume_type=11)),baseline_tool_details=deepcopy(protected),
        check_files=Mock(),check_runtime_identity=Mock(),summary=lambda:dict(scope=data["scope"]))
    def verify(state):
        if not m._same_inventory(state,anchor.state):raise ValueError("Saved full state changed")
    anchor.verify=verify
    control=dict(on_capture=None,on_call=None,on_exit=None,values={},on_details=None)
    session_state=dict(subscribed=False,active=False,disconnected=False,event_count=0,
        overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    seen=[]
    class Session:
        def __enter__(self):session_state.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            session_state.update(active=False,disconnected=True)
            if control["on_exit"]:control["on_exit"]()
        def summary(self):return deepcopy(session_state)
    def boundary():
        if session_state["event_count"]:raise ValueError("CAM event")
        if current["document"]["needs_save"] is not False:raise ValueError("Dirty document")
        if path.read_bytes()!=b"saved additive nineteen-feature plan":raise ValueError("Source changed")
        if sw.GetProcessID()!=23824:raise ValueError("PID changed")
    def called(label,default):
        durable=json.loads(receipt.read_text(encoding="utf-8"))
        assert durable["native_dispatch_pending"] is True
        assert durable["native_reads"][-1]["name"]==label
        assert durable["native_reads"][-1]["attempted"] is True
        assert durable["native_reads"][-1]["returned"] is False
        assert all(r["validated"] for r in durable["native_reads"][:-1])
        seen.append(label)
        if control["on_call"]:control["on_call"](label)
        return control["values"].get(label,default)
    owner=N(native_id=69);feature=N(native_id=244,GetOwner=lambda:owner)
    operation=N(native_id=247);dispatch=object();transform=object()
    origin=N(GetCoordinates=lambda:called("ICWPosition.GetCoordinates",(0.,0.,0.)))
    vector=N(GetCoordinates=lambda:called("ICWUnitVector.GetCoordinates",(0.,0.,1.)))
    params=N(GetToolpathParameters=lambda:called("ICWToolpathParam.GetToolpathParameters",
        (False,False,False,0,False,12.6,25.8)))
    base=N(GetMachiningDepth=lambda f:called("ICWMillOperation.GetMachiningDepth",13.2))
    op3=N(GetOverrideMachiningDepth=lambda f:called("ICWMillOperation3.GetOverrideMachiningDepth",False),
        GetToolpathParam=lambda:called("ICWMillOperation3.GetToolpathParam",params),
        GetSetupParameters=lambda:called("ICWMillOperation3.GetSetupParameters",(transform,origin,vector)))
    types={"ICWMillOperation":base,"ICWMillOperation3":op3,"ICWToolpathParam":params,
           "ICWPosition":origin,"ICWUnitVector":vector}
    expected={"ICWMillOperation":operation,"ICWMillOperation3":operation,"ICWToolpathParam":params,
              "ICWPosition":origin,"ICWUnitVector":vector}
    def typed(raw,name):
        boundary()
        if name=="ICWFeature":assert raw is feature;return feature
        assert raw is expected[name]
        return called("QueryInterface."+name,types[name])
    def read(raw,name,*args):
        boundary();value=getattr(raw,name)
        result=value(*args) if callable(value) else value
        boundary();return result
    def lookup(kind,oid):
        assert (kind,oid)==(1,244);return feature,True
    doc=N(GetCWObjectFromID=lookup)
    def capture(*_,**kw):
        kw["check"]();boundary()
        if control["on_capture"]:control["on_capture"]()
        kw["check"]();boundary()
        state=deepcopy(current);diag=kw["diagnostic"].setdefault("operation_details",{})
        kw["operation_details_reader"](state,dict(doc=doc,operations={247:operation}),read,typed,diag,boundary)
        return state,{}
    def tool_reader(state,native,read,typed,diag,**kw):
        diag["selected_tool_details"]=deepcopy(protected)
        if control["on_details"]:control["on_details"]("tools",diag)
    def compound_reader(state,native,read,typed,diag,**kw):
        diag.update(deepcopy(details[kw["observation"]]))
        if control["on_details"]:control["on_details"](kw["observation"],diag)
    sw=N(GetProcessID=Mock(return_value=23824))
    captures=Mock(side_effect=capture);bootstrap=Mock(return_value=object())
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *_args,**_kw:anchor)
    monkeypatch.setattr(m,"raw_part_identity",lambda *_:deepcopy(current["document"]))
    monkeypatch.setattr(m,"_bootstrap",bootstrap)
    monkeypatch.setattr(m,"capture_selected_plan",captures)
    monkeypatch.setattr(m,"read_selected_operation_tool_details",tool_reader)
    monkeypatch.setattr(m,"read_compound_strategy",compound_reader)
    monkeypatch.setattr(m,"_object_id",lambda doc,obj,read:obj.native_id)
    monkeypatch.setattr(shared,"_dispatch_feature",lambda raw:called("QueryInterface.IDispatch.feature",dispatch) if raw is feature else None)
    monkeypatch.setattr(events,"CamMessageSession",lambda *_:Session())
    def run(**extra):
        args=dict(process_id=23824,expected_document_path=str(path),expected_source_sha256=sha,
            expected_feature_native_id=79,expected_operation_native_ids=[143,144],
            expected_operation_setup_native_id=93,expected_tool_native_id=145,
            saved_plan_receipt_path=str(tmp_path/"saved.json"),saved_plan_receipt_sha256="a"*64,
            qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(receipt),
            message_policy="vendor_default",target_feature_native_id=244,
            target_operation_native_id=247,target_operation_setup_native_id=93)
        return m.inspect_defined_rough_levels(sw,"clsid","tlb",**(args|extra))
    return N(**locals())

def test_zero_path_read_only_two_stable_observations(probe):
    out=probe.run()
    assert out["status"]=="review_required",out
    assert out["levels_read_complete"] and out["readback_verified"]
    assert probe.seen==READS*2 and probe.captures.call_count==2
    assert out["before"]==out["after"]==probe.current
    assert out["levels"]["machining_depth_native"]==13.2
    assert out["levels"]["toolpath_parameters"]["start_Z_native"]==25.8
    assert out["setup"]["axis_native"]==[0.,0.,1.]
    assert all(out[k] is False for k in m.FALSE_FLAGS)
    assert out["may_continue"] is False
    assert all(not r["toolpath_record_counts"] for r in out["after"]["operations"])
    assert json.loads(probe.receipt.read_text(encoding="utf-8"))==out

@pytest.mark.parametrize("field,value",[
    ("target_feature_native_id",64),("target_operation_native_id",248),
    ("target_operation_setup_native_id",69),("target_feature_native_id",True),
    ("target_operation_native_id",True)])
def test_exact_target_preflight(probe,field,value):
    out=probe.run(**{field:value})
    assert out["status"]=="error" and not probe.seen
    probe.bootstrap.assert_not_called()

@pytest.mark.parametrize("field,value",[
    ("mill_operation_type",True),("mill_operation_type",1),("linked_feature_ids",[64]),
    ("toolpath_generated",True),("toolpath_record_counts",[1]),("suppressed",True),
    ("setup_native_id",69)])
def test_zero_path_rough_scope_strict(probe,field,value):
    probe.anchor.state["operations"][-2][field]=value
    out=probe.run()
    assert out["status"]=="error" and not probe.seen

@pytest.mark.parametrize("label,value",[
    ("ICWMillOperation.GetMachiningDepth",True),
    ("ICWMillOperation3.GetOverrideMachiningDepth",0),
    ("ICWToolpathParam.GetToolpathParameters",(False,False,False,True,False,12.6,25.8)),
    ("ICWUnitVector.GetCoordinates",(0.,0.,0.)),
    ("ICWPosition.GetCoordinates",(0.,float("nan"),0.)),
    ("ICWMillOperation3.GetSetupParameters",(None,None,None))])
def test_getter_types_and_shapes_fail_closed(probe,label,value):
    probe.control["values"][label]=value
    out=probe.run()
    assert out["status"]=="error" and not out["levels_read_complete"]
    assert probe.seen[-1]==label
    assert out["native_reads"][-1]["returned"]
    assert out["native_reads"][-1]["validated"] is (label=="ICWUnitVector.GetCoordinates")

def test_native_failure_stops_without_replay(probe):
    def fail(label):
        if label=="ICWMillOperation.GetMachiningDepth":raise RuntimeError("native read failed")
    probe.control["on_call"]=fail
    out=probe.run()
    assert out["status"]=="error" and probe.seen==READS[:3]
    assert out["native_reads"][-1]["raised"] and not out["native_reads"][-1]["returned"]
    again=probe.run()
    assert again["status"]=="error" and probe.seen==READS[:3]
    assert all(out[k] is False for k in m.FALSE_FLAGS)

@pytest.mark.parametrize("kind",["stock","old_operation","full_tool","compound","target_tool","source","dirty","PID","events"])
def test_preserved_context_blocks(probe,kind):
    if kind in ("full_tool","compound"):
        def change(label,diag):
            if kind=="full_tool" and label=="tools":
                diag["selected_tool_details"]["items"][0]["full_tool"]["segments"]=[99]
            if kind=="compound" and label=="strategy":
                diag["compound_strategy"]["attribute_id"]=42
        probe.control["on_details"]=change
    else:
        def change():
            if kind=="stock":probe.current["stock"]["type_raw"]=99
            if kind=="old_operation":probe.current["operations"][0]["suppressed"]=True
            if kind=="target_tool":probe.current["operations"][-2]["assigned_tool"]["native_id"]=999
            if kind=="source":probe.path.write_bytes(b"changed")
            if kind=="dirty":probe.current["document"]["needs_save"]=True
            if kind=="PID":probe.sw.GetProcessID.return_value=123
            if kind=="events":probe.session_state["event_count"]=1
        probe.control["on_capture"]=change
    out=probe.run()
    assert out["status"]=="error" and not out["readback_verified"]
    assert all(out[k] is False for k in m.FALSE_FLAGS)

def test_observation_change_is_not_accepted(probe):
    calls=[]
    def changing(label):
        calls.append(label)
        if label=="ICWMillOperation.GetMachiningDepth" and calls.count(label)==2:
            probe.control["values"][label]=13.3
    probe.control["on_call"]=changing
    out=probe.run()
    assert out["status"]=="error" and len(probe.seen)==26

def test_cleanup_identity_change_fails(probe):
    probe.control["on_exit"]=lambda:probe.path.write_bytes(b"changed")
    out=probe.run()
    assert out["status"]=="error" and len(probe.seen)==26
