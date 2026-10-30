"""合成的只读继续流程与保留观测回归；不连接 CAD。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest
from test_existing_sandvik import m, synthetic, runtime
from scripts import sw_cam_holder_observation as h


def profile():
    return dict(status="observed",declared_chain_count=1,chains=[dict(read_complete=True,
        declared_curve_count=1,curves=[dict(curve_type=0,read_complete=True,
        start_native=[0.,0.,25.],end_native=[1.,0.,25.])])])


def recipe(count=1):
    return dict(records=[dict(kind="line",start_rz=[0.,0.],end_rz=[1.,0.])]*count)


def test_known_count_mismatch_is_observation_only():
    result=h.observe_holder_nominal(profile(),recipe(2),25)
    assert result["native_holder_shape_verified"] is False
    assert result["structural_readback"]["structural_readback_complete"] is True
    assert result["nominal_difference"]["reason"]=="Curve count differs"
    assert result["production_qualified"] is False


def test_known_shape_mismatch_is_observation_only():
    p=profile();p["chains"][0]["curves"][0]["end_native"]=[2.,0.,25.]
    result=h.observe_holder_nominal(p,recipe(),25)
    assert result["native_holder_shape_verified"] is False
    assert result["nominal_difference"]["reason"]=="Missing, extra or ambiguous segment"


def test_exact_nominal_is_separate_from_production():
    result=h.observe_holder_nominal(profile(),recipe(),25)
    assert result["native_holder_shape_verified"] is True
    assert result["nominal_difference"] is None
    assert result["production_qualified"] is False


@pytest.mark.parametrize("change",[
    lambda p:p.update(declared_chain_count=True),
    lambda p:p.update(declared_chain_count=2),
    lambda p:p.update(status="reading"),
    lambda p:p["chains"][0].update(read_complete=False),
    lambda p:p["chains"][0].update(declared_curve_count=2),
    lambda p:p["chains"][0].update(curves=[],declared_curve_count=0),
    lambda p:p["chains"][0]["curves"][0].update(read_complete=False),
    lambda p:p["chains"][0]["curves"][0].update(curve_type=9),
    lambda p:p["chains"][0]["curves"][0].update(curve_type=True),
    lambda p:p["chains"][0]["curves"][0].update(end_native=[1.,float("nan"),25.]),
    lambda p:p["chains"][0]["curves"][0].pop("start_native"),
    lambda p:p["chains"][0].update(curves=p["chains"][0]["curves"]*257,declared_curve_count=257),
])
def test_structure_cannot_be_downgraded_to_nominal(change):
    p=profile();change(p)
    with pytest.raises((ValueError,KeyError)):h.observe_holder_nominal(p,recipe(2),25)


@pytest.mark.parametrize("reason",["unknown nominal problem","Finite geometry required","Semicircle or degenerate fillet unsupported"])
def test_unknown_verifier_failure_is_stop(monkeypatch,reason):
    def fail(*a):raise ValueError(reason)
    monkeypatch.setattr(h,"verify_holder_profile",fail)
    with pytest.raises(ValueError,match=reason):h.observe_holder_nominal(profile(),recipe(),25)


@pytest.fixture
def collector_synthetic(synthetic,monkeypatch,tmp_path):
    """复用合成的前置观测；仅隔离冻结历史实现的固定摘要。"""
    args,loaded=synthetic
    args=deepcopy(args)
    data=dict(scope=m.SCOPE,read_mode=m.READ_MODE,status="error",phase="finished",
        failed_phase="preflight",native_read_count=525,dispatches=[],exports={},snapshot_diagnostics=[],
        messages=deepcopy(loaded["data"]["messages"]),
        issue=dict(type="ValueError",locations=[
            dict(file="sw_cam_existing_sandvik.py",function="observe_existing_sandvik",line=509),
            dict(file="sw_cam_existing_sandvik.py",function="candidate_snapshot",line=469),
            dict(file="sw_cam_shared_holder_geometry.py",function="verify_holder_profile",line=52)]),
        readonly_binding_stop=deepcopy(loaded["readonly_binding_stop"]),
        request_binding={k:args[k] for k in m.BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")},
        prior_receipt_pin=deepcopy(loaded["pin"]),prior_creation_marker_pin=deepcopy(loaded["creation_pin"]),
        evidence_pins=deepcopy(loaded["pins"]),anchor=loaded["anchor"].summary(),
        profile_observation=deepcopy(loaded["profile_observation"]),tool_native_id=263,
        process_id=args["process_id"],before_document=deepcopy(loaded["data"]["before_document"]),
        source_before_sha256=args["expected_source_sha256"],expected_source_sha256=args["expected_source_sha256"],
        expected_document_path=args["expected_document_path"],dispatch_marker_path=str(loaded["marker"]),
        before_tool_diagnostic=dict(capture_complete=True,stage="complete",state=deepcopy(loaded["data"]["tool"])),
        guard_diagnostics=[dict(invalid=False,native_call_attempted=False,native_call_returned=False)])
    for key in ("native_dispatch_pending","export_attempted","mutation_attempted","tool_creation_attempted",
        "MT_load_attempted","field_setter_attempted","holder_setter_attempted","operation_assignment_attempted",
        "GTP_attempted","GOP_attempted","AFR_attempted","simulation_attempted","model_saved","save_attempted",
        "TechDB_write_attempted","automatic_replay","automatic_rollback","readback_verified",
        "numeric_profile_verified","physical_tool_qualified","units_verified","cutting_partition_verified",
        "production_qualified","may_continue","raw_exports_pinned","exports_verified","post_cleanup_CAM_getters",
        "holder_profile_verified","protected_context_unchanged"):
        data[key]=False
    path=tmp_path/"holder_stop.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    backend=tmp_path/"historical_holder_observer.py"
    backend.write_text("# 合成的历史实现边界\n",encoding="utf-8")
    args.update(failed_observation_receipt_path=str(path),failed_observation_receipt_sha256=m.FAILED_HOLDER_READ_SHA,
        failed_observer_backend_path=str(backend),failed_observer_backend_sha256=m.FAILED_HOLDER_OBSERVER_SHA)
    realread=m.read_pin;realhash=m._file_hash
    def read_pin(name,digest):
        if name==str(path):
            if digest!=m.FAILED_HOLDER_READ_SHA:raise ValueError("Synthetic frozen receipt hash differs")
            return json.loads(path.read_text(encoding="utf-8")),dict(path=str(path),sha256=digest)
        return realread(name,digest)
    hashes={str(path):m.FAILED_HOLDER_READ_SHA,str(backend):m.FAILED_HOLDER_OBSERVER_SHA,
            str(Path(m.holder_geometry.__file__)):m.HOLDER_VERIFIER_SHA}
    monkeypatch.setattr(m,"read_pin",read_pin)
    monkeypatch.setattr(m,"_file_hash",lambda name:hashes.get(str(name)) or realhash(name))
    return args,m.load_collector_request(**args)


@pytest.fixture(scope="module")
def collector_local(tmp_path_factory):
    """本机历史证据只在明确提供输入路径时检查。"""
    requested=os.environ.get("SOLIDWORKS_COLLECTOR_TEST_INPUT")
    if not requested:pytest.skip("Local collector evidence requires SOLIDWORKS_COLLECTOR_TEST_INPUT")
    path=Path(requested)
    if not path.is_file():pytest.fail("Explicit collector evidence input does not exist")
    args=json.loads(path.read_text(encoding="utf-8-sig"))
    out=tmp_path_factory.mktemp("collector_local_outputs")
    for key,name in (("receipt_path","report.json"),("cutting_stl_path","cut.stl"),("noncutting_stl_path","noncut.stl")):
        args[key]=str(out/name)
    return args,m.load_collector_request(**args)


def test_explicit_local_collector_evidence(collector_local):
    args,loaded=collector_local
    assert loaded["holder_nominal_stop"]["no_export_attempt_verified"] is True


def test_synthetic_failed_holder_offline_acceptance(collector_synthetic):
    args,loaded=collector_synthetic
    assert loaded["holder_nominal_stop"]["receipt_pin"]["sha256"]==m.FAILED_HOLDER_READ_SHA
    assert loaded["holder_nominal_stop"]["new_export_identity_created"] is False
    assert loaded["holder_nominal_stop"]["original_export_marker"]==str(loaded["marker"])
    assert loaded["readonly_binding_stop"]["original_export_marker"]==str(loaded["marker"])
    assert loaded["data"]["new_tool_native_id"]==263
    assert not loaded["marker"].exists()


@pytest.fixture
def collector_cached(collector_synthetic,monkeypatch):
    args,loaded=collector_synthetic;args=deepcopy(args)
    data=json.loads(Path(args["failed_observation_receipt_path"]).read_text(encoding="utf-8-sig"))
    real=m.read_pin
    def pin(path,sha):
        if path==args["failed_observation_receipt_path"]:
            return data,{"path":path,"sha256":sha}
        return real(path,sha)
    monkeypatch.setattr(m,"read_pin",pin)
    return args,data


@pytest.mark.parametrize("change",[
    lambda d:d.update(status="uncertain"),lambda d:d.update(phase="reading"),
    lambda d:d.update(native_read_count=524),lambda d:d.update(export_attempted=True),
    lambda d:d.update(native_dispatch_pending=True),lambda d:d.update(dispatches=[{}]),
    lambda d:d.update(exports={"cutting":{}}),lambda d:d.update(before_candidate={}),
    lambda d:d.update(readback_verified=True),lambda d:d.update(holder_profile_verified=True),
    lambda d:d.update(model_saved=True),lambda d:d.update(tool_native_id=264),
    lambda d:d["issue"]["locations"][-1].update(line=53),
    lambda d:d["messages"].update(event_count=1),
    lambda d:d["before_tool_diagnostic"].update(capture_complete=False),
    lambda d:d["before_tool_diagnostic"]["state"]["parameters"].update(CutLength=63),
    lambda d:d["guard_diagnostics"][0].update(invalid=True),
    lambda d:d["guard_diagnostics"][0].update(native_call_attempted=True),
])
def test_collector_other_failure_or_side_effect_rejected(collector_cached,change):
    args,data=collector_cached;change(data)
    with pytest.raises(ValueError):m.load_collector_request(**args)


@pytest.mark.parametrize("key",["failed_observation_receipt_sha256","failed_observer_backend_sha256","failed_read_batch_backend_sha256"])
def test_collector_wrong_failure_pin_rejected(collector_cached,key):
    args,_=collector_cached;args[key]="0"*64
    with pytest.raises(ValueError):m.load_collector_request(**args)


def test_holder_mismatch_persists_before_check_and_two_exports_continue(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    real=m.observe_holder_nominal
    def verify(p,*a):
        on_disk=json.loads(Path(args["receipt_path"]).read_text(encoding="utf-8"))
        phase="after" if "CreateSTLOfNonCuttingPortion" in timeline else "before"
        assert on_disk[phase+"_holder_profile"]==p
        assert on_disk[phase+"_holder_diagnostic"]["state"]==p
        return real(p,*a)
    monkeypatch.setattr(m,"observe_holder_nominal",verify)
    r=m.observe_existing_sandvik(sw,"test","test",**args)
    assert r["readback_verified"] is True,r.get("issue",r)
    assert r["holder_profile_observed"] is True
    assert r["holder_profile_verified"] is False
    assert r["holder_readback_stable"] is True
    assert r["before_holder_nominal_verification"]["nominal_difference"]["reason"]=="Curve count differs"
    assert r["before_holder_profile"]==r["after_holder_profile"]
    assert len(r["dispatches"])==2 and r["raw_exports_pinned"] is True
    assert r["protected_context_unchanged"] is True
    assert r["physical_tool_qualified"] is False and r["may_continue"] is False


def test_partial_holder_reader_error_retained_and_exports_blocked(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    def fail(*a,**kw):
        kw["diagnostic"]["state"].update(status="reading",chains=[{"curves":[]}])
        kw["diagnostic"].update(stage="GetNumOfCurves",capture_complete=False)
        raise ValueError("Native curve count changed during read")
    monkeypatch.setattr(m,"read_segment_chains",fail)
    r=m.observe_existing_sandvik(sw,"test","test",**args)
    assert r["status"]=="error" and r["dispatches"]==[]
    assert r["before_holder_diagnostic"]["state"]["status"]=="reading"
    assert json.loads(Path(args["receipt_path"]).read_text(encoding="utf-8"))["before_holder_diagnostic"]==r["before_holder_diagnostic"]
    assert not loaded["marker"].exists()


def test_complete_but_structurally_invalid_profile_retained_and_blocks_exports(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime
    def bad(*a,**kw):
        p=profile();p["chains"][0]["curves"][0]["curve_type"]=9
        kw["diagnostic"]["state"].update(p)
    monkeypatch.setattr(m,"read_segment_chains",bad)
    r=m.observe_existing_sandvik(sw,"test","test",**args)
    assert r["status"]=="error" and r["dispatches"]==[]
    assert r["before_holder_profile"]["chains"][0]["curves"][0]["curve_type"]==9
    assert r["holder_profile_verified"] is False
    assert not loaded["marker"].exists()


def test_readback_holder_profile_change_invalidates_after_both_exports(runtime,monkeypatch):
    args,loaded,sw,timeline,doc,g=runtime;read=m.read_segment_chains;calls=[0]
    def changed(*a,**kw):
        read(*a,**kw);calls[0]+=1
        if calls[0]==2:kw["diagnostic"]["state"]["chains"][0]["curves"][0]["end_native"][0]=2.
    monkeypatch.setattr(m,"read_segment_chains",changed)
    r=m.observe_existing_sandvik(sw,"test","test",**args)
    assert r["status"]=="uncertain" and r["readback_verified"] is False
    assert r["holder_readback_stable"] is False and len(r["dispatches"])==2
    assert r["before_holder_profile"]!=r["after_holder_profile"]
    assert r["raw_exports_pinned"] is True