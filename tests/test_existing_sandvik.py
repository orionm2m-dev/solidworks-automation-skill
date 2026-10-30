import ast
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/"scripts"))
spec=importlib.util.spec_from_file_location("observer_test",STAGE/"scripts/sw_cam_existing_sandvik.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

@pytest.fixture(scope="module")
def local_actual(tmp_path_factory):
    requested=os.environ.get("SOLIDWORKS_OBSERVER_TEST_INPUT")
    if not requested:
        pytest.skip("Local receipt verification requires SOLIDWORKS_OBSERVER_TEST_INPUT")
    path=Path(requested)
    if not path.is_file():
        pytest.fail("Explicit local receipt input does not exist")
    args=json.loads(path.read_text(encoding="utf-8-sig"))
    out=tmp_path_factory.mktemp("baseline_outputs")
    for key,name in (("receipt_path","report.json"),("cutting_stl_path","cut.stl"),("noncutting_stl_path","noncut.stl")):
        args[key]=str(out/name)
    loaded=m.load_strong_observation_request(**args)
    return args,loaded

def test_actual_receipt_offline_acceptance(local_actual):
    args,loaded=local_actual
    assert loaded["data"]["new_tool_native_id"]==263
    assert loaded["profile_observation"]["expected_MT_segments_present_once"] is True
    assert len(loaded["profile_observation"]["tool_extra_edges"])==4
    assert loaded["profile_observation"]["numeric_profile_verified"] is False


@pytest.fixture
def synthetic(tmp_path,monkeypatch):
    """手工构造最小历史；真实加载器验证它，不读取本机工程证据。"""
    def pin(name,content):
        path=tmp_path/name
        path.write_bytes(content)
        return dict(path=str(path),sha256=m._file_hash(path))
    source=pin("fixture.SLDPRT",b"synthetic part bytes")
    asset=pin("fixture.mt",b"synthetic tool asset")
    candidate=dict(part="Fixture tool",pins=[pin(f"candidate{i}.json",b"{}") for i in range(4)])
    holder=dict(file_path=str(tmp_path/"fixture.mh"),
        pins=[pin("fixture.mh",b"synthetic holder"),pin("holder.json",b"{}")],
        records=[dict(kind="line",start_rz=[0.,0.],end_rz=[1.,0.]),
                 dict(kind="line",start_rz=[1.,0.],end_rz=[1.,1.])])
    firstpin=pin("firstcut.json",b"{}")
    savedpin=pin("saved.json",b"{}")
    args=dict(process_id=1234,expected_document_path=source["path"],
        expected_source_sha256=source["sha256"],expected_feature_native_id=244,
        expected_operation_native_ids=[247,248],expected_operation_setup_native_id=93,
        expected_tool_native_id=145,expected_candidate_tool_native_id=263,
        saved_plan_receipt_path=savedpin["path"],saved_plan_receipt_sha256=savedpin["sha256"],
        qualification_only=True,acknowledge_disposable_copy=True,message_policy="vendor_default",
        receipt_path=str(tmp_path/"report.json"),cutting_stl_path=str(tmp_path/"cut.stl"),
        noncutting_stl_path=str(tmp_path/"noncut.stl"),
        phase1_backend_path=str(tmp_path/"phase1.py"),phase1_backend_sha256=m.PHASE1_SHA,
        profile_validator_path=str(tmp_path/"profile.py"),profile_validator_sha256=m.WRITER_SHA,
        failed_observer_backend_path=str(tmp_path/"observer.py"),
        failed_observer_backend_sha256="9746b3f1384ce5d3b65a8a724f713a597687f68ff021a6385f501f1b76548ddb",
        failed_read_batch_backend_path=str(tmp_path/"batch.py"),
        failed_read_batch_backend_sha256="670a6c544fffdb3632d8e6cc13a147b7d2a4c6426b9604732c56d2e36ee22d6e")
    # 旧实现摘要是协议常量；隔离这些源文件，不伪造真实 CAD 数据。
    hashes={args[k]:args[k.replace("_path","_sha256")] for k in (
        "phase1_backend_path","profile_validator_path","failed_observer_backend_path","failed_read_batch_backend_path")}
    realhash=m._file_hash
    monkeypatch.setattr(m,"_file_hash",lambda path:hashes.get(str(path)) or realhash(path))
    doc=dict(path=source["path"],title="fixture.SLDPRT",document_type=1,needs_save=False)
    state=dict(document=deepcopy(doc),features=[dict(native_id=i+1) for i in range(19)],
        operations=[dict(native_id=i,setup_native_id=93,mill_operation_type=0 if i==247 else 1,
            toolpath_generated=False,toolpath_record_counts=[]) for i in (143,144,195,196,247,248)])
    summary=dict(scope="synthetic_saved_anchor",pin=savedpin)
    class Anchor:
        data=dict(scope="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1",new_feature_native_id=244,
            new_operations=[dict(native_id=247,setup_native_id=93,mill_operation_type=0)])
        profile={}
        pins=[savedpin]
        def summary(self):return deepcopy(summary)
        def verify(self,observed):
            if m._digest(observed)!=m._digest(self.state):raise ValueError("Synthetic anchor state differs")
    anchor=Anchor();anchor.state=deepcopy(state)
    firstcut=dict(direct_type=0)
    first=dict(after_settings=firstcut,after_document=deepcopy(doc))
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**kw:anchor)
    monkeypatch.setattr(m,"load_candidate_contract",lambda *a:deepcopy(candidate))
    monkeypatch.setattr(m,"read_holder_recipe",lambda *a:deepcopy(holder))
    monkeypatch.setattr(m,"load_firstcut_receipt",lambda *a,**kw:deepcopy(first))
    def profile(edges):
        curves=[dict(index=i,read_complete=True,curve_type=0,
            start_native=[a[0],0.,a[1]],end_native=[b[0],0.,b[1]]) for i,(a,b) in enumerate(edges)]
        return dict(status="observed",declared_chain_count=1,chains=[dict(index=0,
            read_complete=True,declared_curve_count=len(curves),curves=curves)])
    edges=list(zip(m.POINTS,m.POINTS[1:]))
    profiles=dict(tool=profile(edges+[((0.,float(i)),(1.,float(i))) for i in range(4)]),
                  shank=profile([((0.,0.),(1.,0.))]))
    tool=dict(native_id=263,tool_type_raw=14,profile_complete=True,parameters=dict(m.FIELDS),
              mt_path_raw=asset["path"],profiles=profiles)
    dispatches=[dict(label=name,attempted=True,returned=True,pending=False,return_type="int",return_value=0)
                for name in ("AddNewTool3","SetToolName","SetFilePathForUserDefinedHolder")]
    messages=dict(subscribed=True,disconnected=True,active=False,event_count=0,overflow=False,
                  callback_errors=[],callback_error_count=0,disconnect_errors=[])
    binding={k:deepcopy(args[k]) for k in m.BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
    binding.update(firstcut_receipt_path=firstpin["path"],firstcut_receipt_sha256=firstpin["sha256"])
    data=dict(scope=m.PRIOR_SCOPE,status="uncertain",phase="finished",failed_phase="SetFilePathForUserDefinedHolder",
        native_dispatch_pending=False,readback_verified=False,new_tool_native_id=263,
        issue=dict(type="ValueError",locations=[dict(file="sw_cam_sandvik_phase1.py",function="qualify_sandvik_ud14",line=450),
            dict(file="sw_cam_sandvik_mt.py",function="validate_native_profiles",line=172)]),
        messages=messages,request_binding=binding,process_id=args["process_id"],
        source_before_sha256=source["sha256"],expected_document_path=source["path"],anchor=summary,
        before=deepcopy(state),before_document=deepcopy(doc),firstcut_anchor=dict(pin=firstpin,after_settings=firstcut),
        before_firstcut=firstcut,candidate_contract=candidate,holder_recipe=holder,tool=tool,
        candidate_asset=asset,dispatches=dispatches,
        field_attempts=[dict(property=k,setter_attempted=False,readback_verified=True) for k,v in m.FIELDS],
        before_tools=[],metric_scope=dict(document_unit="mm",cam_unit="mm"))
    for key in ("operation_assignment_attempted","GTP_attempted","GOP_attempted","AFR_attempted",
        "simulation_attempted","model_saved","save_attempted","TechDB_write_attempted","automatic_replay",
        "automatic_rollback","post_cleanup_CAM_getters","units_verified","physical_tool_qualified",
        "cutting_partition_verified","production_qualified"):
        data[key]=False
    creation=m.attempt_marker(source["path"],source["sha256"],asset["sha256"])
    data["dispatch_marker_path"]=str(creation)
    priorpin=pin("prior.json",json.dumps(data).encode())
    args.update(phase1_receipt_path=priorpin["path"],phase1_receipt_sha256=priorpin["sha256"])
    marker=dict(scope=m.PRIOR_SCOPE,status="uncertain",phase="finished",native_dispatch_pending=False,
        new_tool_native_id=263,dispatches=dispatches,candidate_sha256=asset["sha256"],source_sha256=source["sha256"],
        automatic_replay=False,document=source["path"],receipt_path=priorpin["path"])
    creation.write_text(json.dumps(marker),encoding="utf-8")
    loaded=m.load_observation_request(**args)
    failed=dict(scope=m.SCOPE,status="error",phase="finished",failed_phase="preflight",native_read_count=49,
        dispatches=[],exports={},messages=messages,request_binding={k:args[k] for k in m.BINDING_KEYS+
        ("saved_plan_receipt_path","saved_plan_receipt_sha256")},process_id=args["process_id"],tool_native_id=263,
        source_before_sha256=source["sha256"],expected_source_sha256=source["sha256"],before_document=doc,
        prior_receipt_pin=loaded["pin"],prior_creation_marker_pin=loaded["creation_pin"],anchor=summary,
        profile_observation=loaded["profile_observation"],expected_document_path=source["path"],
        dispatch_marker_path=str(loaded["marker"]),issue=dict(type="ValueError",locations=[
            dict(file="sw_cam_read_batch_guard.py",function="boundary",line=83),
            dict(file="sw_cam_read_batch_guard.py",function="_timed",line=70),
            dict(file="sw_cam_existing_sandvik.py",function="binding",line=319)]),
        read_batch_diagnostics=[dict(scope="BOUNDED_CAM_READ_BATCH_V1",active=False,invalid=True,claimed=False,
            native_call_attempted=False,native_call_returned=False,read_scope_complete=False,
            getter_calls=0,query_interface_calls=0)])
    for key in ("native_dispatch_pending","export_attempted","mutation_attempted","tool_creation_attempted",
        "MT_load_attempted","field_setter_attempted","holder_setter_attempted","operation_assignment_attempted",
        "GTP_attempted","GOP_attempted","AFR_attempted","simulation_attempted","model_saved","save_attempted",
        "TechDB_write_attempted","automatic_replay","automatic_rollback","readback_verified",
        "numeric_profile_verified","physical_tool_qualified","units_verified","cutting_partition_verified",
        "production_qualified","may_continue","raw_exports_pinned","exports_verified","post_cleanup_CAM_getters"):
        failed[key]=False
    failedpin=pin("failed.json",json.dumps(failed).encode())
    args.update(failed_observation_receipt_path=failedpin["path"],failed_observation_receipt_sha256=failedpin["sha256"])
    return args,m.load_strong_observation_request(**args)


def test_synthetic_request_acceptance(synthetic):
    args,loaded=synthetic
    assert loaded["data"]["new_tool_native_id"]==263
    assert loaded["profile_observation"]["expected_MT_segments_present_once"] is True
    assert len(loaded["profile_observation"]["tool_extra_edges"])==4
    assert loaded["profile_observation"]["numeric_profile_verified"] is False

@pytest.fixture
def cached(monkeypatch,synthetic,tmp_path):
    args,original=synthetic;args=deepcopy(args);loaded=dict(original)
    data=deepcopy(original["data"])
    first={"after_settings":loaded["firstcut"],"after_document":data["before_document"]}
    realread=m.read_pin;realhash=m._file_hash
    def read_pin(path,sha):
        if path==args["phase1_receipt_path"]:
            if sha!=loaded["pin"]["sha256"]:raise ValueError("Receipt hash mismatch")
            return data,loaded["pin"]
        return realread(path,sha)
    known={str(p["path"]):p["sha256"] for p in loaded["pins"]+loaded["anchor"].pins}
    monkeypatch.setattr(m,"read_pin",read_pin)
    monkeypatch.setattr(m,"_file_hash",lambda p:known.get(str(p)) or realhash(p))
    monkeypatch.setattr(m,"load_saved_plan_tools_evidence",lambda *a,**kw:loaded["anchor"])
    monkeypatch.setattr(m,"load_candidate_contract",lambda *a:deepcopy(loaded["candidate"]))
    monkeypatch.setattr(m,"read_holder_recipe",lambda *a:deepcopy(loaded["holder"]))
    monkeypatch.setattr(m,"load_firstcut_receipt",lambda *a,**kw:first)
    for key,name in (("receipt_path","report.json"),("cutting_stl_path","cut.stl"),("noncutting_stl_path","noncut.stl")):
        args[key]=str(tmp_path/name)
    monkeypatch.setattr(m,"export_marker",lambda *a:tmp_path/"attempt.json")
    return args,data

@pytest.mark.parametrize("key,value",[
    ("expected_source_sha256","0"*64),("expected_candidate_tool_native_id",264),
    ("expected_candidate_tool_native_id",True),("phase1_backend_sha256","0"*64),
    ("profile_validator_sha256","0"*64),("phase1_receipt_sha256","0"*64),
    ("process_id",23825)])
def test_request_mismatch_rejected(cached,key,value):
    args,data=cached;args[key]=value
    with pytest.raises((ValueError,TypeError)):m.load_observation_request(**args)

@pytest.mark.parametrize("change",[
    lambda d:d.update(native_dispatch_pending=True),
    lambda d:d.update(status="review_required"),
    lambda d:d.update(new_tool_native_id=264),
    lambda d:d["issue"]["locations"][0].update(line=449),
    lambda d:d["dispatches"][-1].update(returned=False),
    lambda d:d["dispatches"][-1].update(return_value=True),
    lambda d:d["tool"]["parameters"].update(CutLength=63.),
    lambda d:d["field_attempts"][0].update(readback_verified=False),
    lambda d:d.update(model_saved=True),
    lambda d:d.update(GTP_attempted=True),
    lambda d:d.update(exports={"cutting":{}}),
    lambda d:d["messages"].update(active=True),
])
def test_prior_mismatch_rejected(cached,change):
    args,data=cached;change(data)
    with pytest.raises((ValueError,KeyError)):m.load_observation_request(**args)

def test_existing_marker_rejects_replay(cached,tmp_path):
    args,data=cached;(tmp_path/"attempt.json").write_text("{}")
    with pytest.raises(ValueError,match="never replay"):m.load_observation_request(**args)

def test_empty_export_keeps_pin(tmp_path):
    p=tmp_path/"empty.stl";p.write_bytes(b"")
    result=m.analyze_export(str(p),"cutting")
    assert result["pin"]["bytes"]==0
    assert result["classification_pending"] is True
    assert result["mesh_health_verified"] is False
    assert "observation_issue" in result

def test_no_native_mutation_calls_in_observer():
    tree=ast.parse((STAGE/"scripts/sw_cam_existing_sandvik.py").read_text(encoding="utf-8-sig"))
    forbidden={"AddNewTool3","SetToolName","SetFilePathForUserDefinedHolder","SetTool",
               "SaveActiveDocument","GenerateToolpath","GenerateOperationPlan"}
    for node in ast.walk(tree):
        if isinstance(node,ast.Call):
            assert not (isinstance(node.func,ast.Attribute) and node.func.attr in forbidden)
            if isinstance(node.func,ast.Name) and node.func.id=="_member":
                assert not any(isinstance(a,ast.Constant) and a.value in forbidden for a in node.args[1:2])

@pytest.fixture
def runtime(monkeypatch,synthetic,tmp_path):
    original_args,original=synthetic;args=deepcopy(original_args);loaded=dict(original)
    loaded["data"]=deepcopy(original["data"]);loaded["marker"]=tmp_path/"attempt.json"
    for key,name in (("receipt_path","report.json"),("cutting_stl_path","cut.stl"),("noncutting_stl_path","noncut.stl")):
        args[key]=str(tmp_path/name)
    timeline=[];prior=loaded["data"]
    state=deepcopy(prior["before"]);tool=object();holder=object();oldholder=object();crib=object()
    native={"operations":{loaded["rough_id"]:object()},"machine":object(),"doc":object()}
    doc=deepcopy(prior["before_document"])
    class Anchor:
        data=original["anchor"].data;state=original["anchor"].state;profile=original["anchor"].profile;pins=[]
        def check_runtime_identity(self):pass
        def check_files(self):pass
        def verify(self,s):pass
        def summary(self):return prior["anchor"]
    loaded["anchor"]=Anchor();loaded["pins"]=[]
    loaded["holder_nominal_stop"]={"fixture":True}
    monkeypatch.setattr(m,"load_collector_request",lambda **kw:loaded)
    monkeypatch.setattr(m,"raw_part_identity",lambda sw:deepcopy(doc))
    realhash=m._file_hash
    monkeypatch.setattr(m,"_file_hash",lambda p:args["expected_source_sha256"] if str(p)==args["expected_document_path"] else realhash(p))
    monkeypatch.setattr(m,"_bootstrap",lambda *a:object())
    monkeypatch.setattr(m,"resolve_existing_context",lambda *a:native)
    monkeypatch.setattr(m,"same_observed_context",lambda a,b,**kw:a==b)
    monkeypatch.setattr(m,"_object_id",lambda doc,t,r:263)
    monkeypatch.setattr(m,"_items",lambda value,*a:list(value))
    monkeypatch.setattr(m,"read_firstcut_settings",lambda *a:deepcopy(loaded["firstcut"]))
    monkeypatch.setattr(m,"read_document_cam_unit_scope",lambda *a,**kw:deepcopy(prior["metric_scope"]))
    monkeypatch.setattr(m,"capture_local_tools",lambda *a:{"unchanged":True})
    monkeypatch.setattr(m,"verify_one_new_tool",lambda *a:True)
    monkeypatch.setattr(m,"read_ud14_tool",lambda *a,**kw:deepcopy(prior["tool"]))
    monkeypatch.setattr(m,"holder_objects",lambda *a:{263:holder,145:oldholder})
    monkeypatch.setattr(m,"com_identity",lambda obj,*a:id(obj))
    def holder_profile(*a,**kw):
        kw["diagnostic"]["state"].update(status="observed",declared_chain_count=1,chains=[dict(
            read_complete=True,declared_curve_count=1,curves=[dict(read_complete=True,curve_type=0,
            start_native=[0.,0.,0.],end_native=[1.,0.,0.])])])
        kw["diagnostic"].update(capture_complete=True,stage="complete")
    monkeypatch.setattr(m,"read_segment_chains",holder_profile)
    count={"capture":0}
    def capture(*a,**kw):
        count["capture"]+=1;timeline.append("capture")
        if count["capture"]==1:assert kw["operation_details_reader"] is not None
        return deepcopy(state),native
    monkeypatch.setattr(m,"capture_selected_plan",capture)
    class Guard:
        def __init__(self,*a,**kw):self.kw=kw
        def __enter__(self):timeline.append("guard_enter");return self
        def __exit__(self,*a):timeline.append("guard_exit")
        def summary(self):return {"closed":True}
        def read(self,obj,name,*values):
            if name=="ActiveDoc":return object()
            if name=="IGetToolcrib":return crib
            if name=="GetAllTools":return [tool]
            if name=="IsMillTool":return True
            if name=="IGetMillToolHolder":return holder
            if name=="GetName":return loaded["holder"]["file_path"]
            raise AssertionError(name)
        def typed(self,obj,name):return obj
        def dispatch_once(self,invoke,persist_pending):
            persist_pending();return invoke()
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",Guard)
    def member(obj,name,*values):
        if name=="GetProcessID":return args["process_id"]
        assert name in ("CreateSTLOfCuttingPortion","CreateSTLOfNonCuttingPortion")
        timeline.append(name);Path(values[0]).write_bytes(b"native export");return 0
    monkeypatch.setattr(m,"_member",member)
    def analysis(path,portion):
        assert "CreateSTLOfNonCuttingPortion" in timeline
        timeline.append("analysis_"+portion)
        return dict(pin=m.raw_export_pin(path),mesh_health_verified=False,classification_pending=True,
                    observation_issue={"reason":"unexpected native envelope"},units_verified=False)
    monkeypatch.setattr(m,"analyze_export",analysis)
    class Session:
        def __init__(self,*a):self.active=False;self.disconnected=False
        def __enter__(self):self.active=True;return self
        def __exit__(self,*a):self.active=False;self.disconnected=True
        def summary(self):return dict(subscribed=True,active=self.active,disconnected=self.disconnected,
            event_count=0,overflow=False,callback_errors=[],callback_error_count=0,disconnect_errors=[])
    import scripts.sw_cam_events
    monkeypatch.setattr(scripts.sw_cam_events,"CamMessageSession",Session)
    return args,loaded,SimpleNamespace(ActiveDoc=object()),timeline,doc,Guard

def test_exports_both_then_unexpected_cut_preserves_readback(runtime):
    args,loaded,sw,timeline,doc,g=runtime
    report=m.observe_existing_sandvik(sw,"test","test",**args)
    assert report["status"]=="review_required",report
    assert report["readback_verified"] is True
    assert report["raw_exports_pinned"] is True
    assert report["exports_verified"] is False
    assert report["numeric_profile_verified"] is False
    assert report["physical_tool_qualified"] is False
    assert report["may_continue"] is False
    assert len(report["dispatches"])==2
    assert report["mutation_attempted"] is False
    assert timeline.index("CreateSTLOfNonCuttingPortion")<timeline.index("analysis_cutting")

def test_native_unknown_persists_pending_and_never_retries(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    real=m._member
    def member(obj,name,*v):
        if name=="CreateSTLOfCuttingPortion":raise RuntimeError("native outcome unknown")
        return real(obj,name,*v)
    monkeypatch.setattr(m,"_member",member)
    result=m.observe_existing_sandvik(sw,"test","test",**args)
    assert result["status"]=="uncertain"
    assert result["native_dispatch_pending"] is True
    assert len(result["dispatches"])==1
    marker=json.loads(loaded["marker"].read_text())
    assert marker["native_dispatch_pending"] is True
    assert marker["automatic_replay"] is False

@pytest.mark.parametrize("target",["tool","firstcut","holder","context","dirty"])
def test_after_change_rejected(runtime,monkeypatch,target):
    args,loaded,sw,timeline,doc,g=runtime
    if target=="tool":
        real=m.read_ud14_tool;calls=[0]
        def tool(*a,**kw):
            calls[0]+=1;v=real(*a,**kw)
            if calls[0]==2:v["parameters"]["CutLength"]=63.
            return v
        monkeypatch.setattr(m,"read_ud14_tool",tool)
    elif target=="firstcut":
        real=m.read_firstcut_settings;calls=[0]
        def first(*a):
            calls[0]+=1;v=real(*a)
            if calls[0]==2:v["direct_type"]=1
            return v
        monkeypatch.setattr(m,"read_firstcut_settings",first)
    elif target=="holder":
        calls=[0];real=m.read_segment_chains
        def profile(*a,**kw):
            real(*a,**kw);calls[0]+=1
            kw["diagnostic"]["state"]["chains"][0]["curves"][0]["end_native"][0]=float(calls[0])
        monkeypatch.setattr(m,"read_segment_chains",profile)
    elif target=="context":
        real=m.capture_selected_plan;calls=[0]
        def capture(*a,**kw):
            calls[0]+=1;s,n=real(*a,**kw)
            if calls[0]==1:s["changed"]=True
            return s,n
        monkeypatch.setattr(m,"capture_selected_plan",capture)
    elif target=="dirty":
        real=m.analyze_export
        def analysis(*a):
            doc["needs_save"]=not doc["needs_save"];return real(*a)
        # 仅在切削导出后改变一次，非切削导出不得恢复原值。
        def once(path,portion):
            if portion=="cutting":return analysis(path,portion)
            return real(path,portion)
        monkeypatch.setattr(m,"analyze_export",once)
    result=m.observe_existing_sandvik(sw,"test","test",**args)
    assert result["readback_verified"] is False
    assert result["status"]=="uncertain"
    assert len(result["dispatches"])==2


@pytest.mark.parametrize("fault",["order","duplicate","machine","doctype"])
def test_resolver_rejects_wrong_identity_scope(monkeypatch,fault):
    doc=object();app=object();part=doc;machine=object();setup=SimpleNamespace(native_id=9)
    ops=[SimpleNamespace(native_id=1),SimpleNamespace(native_id=2)]
    expected={"before":{"operations":[{"native_id":1,"setup_native_id":9},{"native_id":2,"setup_native_id":9}]}}
    if fault=="order":ops.reverse()
    if fault=="duplicate":ops[1]=ops[0]
    def read(obj,name,*args):
        return {"IGetActiveDoc":doc,"GetDocType":True if fault=="doctype" else 1,
                "IGetMachine":machine,"MachType":0 if fault=="machine" else 1,
                "IGetEnumOpSetups":[setup],"IGetEnumOperations":ops}[name]
    monkeypatch.setattr(m,"_items",lambda value,*a:value)
    monkeypatch.setattr(m,"_object_id",lambda doc,o,read:o.native_id)
    with pytest.raises(ValueError):m.resolve_existing_context(app,read,lambda o,n:o,expected)

def test_real_unexpected_cut_keeps_numeric_extent(tmp_path):
    import struct
    p=tmp_path/"tall.stl"
    vertices=[(0.,0.,0.),(4.,0.,0.),(0.,4.,0.),(0.,0.,63.)]
    faces=[(0,2,1),(0,1,3),(0,3,2),(1,2,3)]
    data=bytearray(b"\0"*80+struct.pack("<I",4))
    for face in faces:
        row=[0.,0.,0.]
        for vi in face:row.extend(vertices[vi])
        data.extend(struct.pack("<12fH",*row,0))
    p.write_bytes(data)
    result=m.analyze_export(str(p),"cutting")
    assert result["raw_measurement"]["axial_extent_native"]==[0.,63.]
    assert result["mesh_health_verified"] is False
    assert result["classification_pending"] is True
    assert result["numeric_envelope_verified"] is False
    assert "observation_issue" in result

def test_before_changed_profile_prevents_exports(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    real=m.read_ud14_tool
    def changed(*a,**kw):
        result=real(*a,**kw);result["parameters"]["CutLength"]=63.;return result
    monkeypatch.setattr(m,"read_ud14_tool",changed)
    report=m.observe_existing_sandvik(sw,"test","test",**args)
    assert report["status"]=="error"
    assert report["export_attempted"] is False
    assert report["dispatches"]==[]
    assert not loaded["marker"].exists()

def test_read_scope_exit_failure_prevents_exports(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    class InvalidGuard(g):
        def __exit__(self,*a):raise ValueError("Read boundary changed")
    monkeypatch.setattr(m,"ScopedCamDispatchGuard",InvalidGuard)
    report=m.observe_existing_sandvik(sw,"test","test",**args)
    assert report["export_attempted"] is False
    assert report["readback_verified"] is False

def test_export_boolean_hresult_is_not_success(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    real=m._member
    def member(obj,name,*v):
        result=real(obj,name,*v)
        return True if name=="CreateSTLOfCuttingPortion" else result
    monkeypatch.setattr(m,"_member",member)
    report=m.observe_existing_sandvik(sw,"test","test",**args)
    assert report["readback_verified"] is False
    assert report["native_dispatch_pending"] is False
    assert len(report["dispatches"])==1
    assert report["status"]=="uncertain"



def test_strong_route_has_no_batch_call():
    source=(STAGE/"scripts/sw_cam_existing_sandvik.py").read_text(encoding="utf-8-sig")
    assert "ScopedCamReadBatch" not in source
    assert "def binding():" not in source
    assert "def resolve_existing_context(" in source
    assert 'after,after_native=capture("after",full=True)' in source

@pytest.fixture
def failed_cached(cached,monkeypatch):
    args,_=cached
    failed=json.loads(Path(args["failed_observation_receipt_path"]).read_text(encoding="utf-8-sig"))
    original=m.read_pin
    def read_pin(path,sha):
        if path==args["failed_observation_receipt_path"]:
            if sha!=args["failed_observation_receipt_sha256"]:raise ValueError("Failed receipt SHA")
            return failed,{"path":path,"sha256":sha}
        return original(path,sha)
    monkeypatch.setattr(m,"read_pin",read_pin)
    return args,failed

@pytest.mark.parametrize("change",[
    lambda d:d.update(export_attempted=True),
    lambda d:d.update(native_dispatch_pending=True),
    lambda d:d.update(dispatches=[{"attempted":True}]),
    lambda d:d.update(exports={"cutting":{}}),
    lambda d:d.update(before_candidate={}),
    lambda d:d["issue"]["locations"][-1].update(line=318),
    lambda d:d["read_batch_diagnostics"][0].update(getter_calls=1),
    lambda d:d["read_batch_diagnostics"][0].update(query_interface_calls=True),
    lambda d:d.update(model_saved=True),
    lambda d:d.update(tool_native_id=264),
    lambda d:d["messages"].update(active=True),
])
def test_strong_fallback_rejects_other_failed_state(failed_cached,change):
    args,failed=failed_cached;change(failed)
    with pytest.raises(ValueError):m.load_strong_observation_request(**args)

def test_failed_implementation_pin_required(failed_cached):
    args,_=failed_cached;args["failed_observer_backend_sha256"]="0"*64
    with pytest.raises(ValueError):m.load_strong_observation_request(**args)

def test_strong_fallback_keeps_original_marker_identity(synthetic):
    args,loaded=synthetic
    assert loaded["readonly_binding_stop"]["new_export_identity_created"] is False
    failed=json.loads(Path(args["failed_observation_receipt_path"]).read_text(encoding="utf-8-sig"))
    assert str(loaded["marker"])==failed["dispatch_marker_path"]
    assert not loaded["marker"].exists()

