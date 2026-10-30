"""Explicit one-operation regeneration guards; all native calls are mocked."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import os
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get("SW_CAM_TEST_RUNTIME_ROOT",str(ROOT)))
sys.path.insert(0,str(RUNTIME/"tests"))
import test_sw_cam_mill_toolpath as legacy

def _load():
    p=ROOT/"scripts/sw_cam_mill_toolpath.py"
    if not p.is_file():p=RUNTIME/"scripts/sw_cam_mill_toolpath.py"
    spec=importlib.util.spec_from_file_location("qualified_regenerate_under_test",p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
cam=_load()

@pytest.fixture
def probe(tmp_path,monkeypatch):
    monkeypatch.setattr(legacy,"cam",cam)
    return legacy.probe.__wrapped__(tmp_path,monkeypatch)

@pytest.fixture
def regen(probe,monkeypatch):
    p=probe
    from types import SimpleNamespace
    p.sw.ActiveDoc=SimpleNamespace(**{name:Mock(side_effect=lambda key=key:p.current["document"][key])
        for name,key in [("GetPathName","path"),("GetTitle","title"),("GetType","type"),("GetSaveFlag","needs_save")]})
    p.current["operations"][0].update(toolpath_generated=True,toolpath_record_counts=[68])
    p.percent=0.
    def read(*args):
        args[3]()
        if p.state.get("on_percent"):p.state["on_percent"]()
        args[3]()
        return dict(native_read_complete=True,tool_diameter_percent_native=p.percent)
    monkeypatch.setattr(cam,"_read_regeneration_percent",Mock(side_effect=read))
    prep_path=p.path.parent/"prepare.json"
    options=dict(generation_mode="regenerate",expected_toolpath_record_counts=[68],expected_tool_diameter_percent=0.)
    def prepare(**kw):return p.run("prepare",receipt_path=str(prep_path),**(options|kw))
    def apply(prepared,**kw):
        args=options|dict(expected_state_sha256=prepared["state_sha256"],prepare_receipt_path=str(prep_path),
            prepare_receipt_sha256=cam._file_hash(prep_path))
        return p.run(**(args|kw))
    p.prepare=prepare;p.apply=apply;p.prep_path=prep_path;p.options=options
    return p

def test_generated_rough_prepare_and_one_apply_keep_sibling(regen):
    p=regen;prepared=p.prepare()
    assert prepared["status"]=="ok" and prepared["apply_eligible"]
    assert p.captures.call_count==2 and not p.op.GenerateToolpath.called
    assert prepared["prepared_state"]["generation_mode"]=="regenerate"
    assert prepared["before"]["selected_rough_boundary"]["tool_diameter_percent_native"]==0.
    out=p.apply(prepared)
    assert out["status"]=="review_required" and out["readback_verified"]
    assert out["before"]["operations"][1]==out["after"]["operations"][1]
    assert out["before"]["selected_rough_boundary"]==out["after"]["selected_rough_boundary"]
    assert out["fresh_CL_WIP_required"] and not out["fresh_path_geometry_verified"]
    p.op.GenerateToolpath.assert_called_once();p.other.GenerateToolpath.assert_not_called()
    assert json.loads(p.receipt.read_text())==out
    assert Path(str(p.prep_path)+".apply_attempt.json").is_file()

@pytest.mark.parametrize("value",[[],[0],[True],[1.],[100001],[50001,50000],(68,),None])
def test_invalid_record_list_blocks_before_capture(regen,value):
    out=regen.prepare(expected_toolpath_record_counts=value)
    assert out["status"]=="error" and not regen.captures.called
    regen.op.GenerateToolpath.assert_not_called()

@pytest.mark.parametrize("value",[None,True,False,"0",float("nan"),float("inf"),-1,151])
def test_invalid_percent_blocks_before_capture(regen,value):
    out=regen.prepare(expected_tool_diameter_percent=value)
    assert out["status"]=="error" and not regen.captures.called

@pytest.mark.parametrize("case",["dirty","wrong_counts","ungenerated","wrong_type","stale_percent","percent_changes"])
def test_bad_preparation_cannot_generate(regen,case):
    p=regen;kw={}
    if case=="dirty":p.current["document"]["needs_save"]=True
    if case=="wrong_counts":p.current["operations"][0]["toolpath_record_counts"]=[67]
    if case=="ungenerated":p.current["operations"][0]["toolpath_generated"]=False
    if case=="wrong_type":kw["expected_mill_operation_type"]=1
    if case=="stale_percent":p.percent=75.
    if case=="percent_changes":
        def change():
            if p.captures.call_count==2:p.percent=75.
        p.state["on_percent"]=change
    out=p.prepare(**kw)
    assert out["status"]=="error";p.op.GenerateToolpath.assert_not_called()

@pytest.mark.parametrize("case",["missing_prep","bad_sha","changed_receipt","not_prepared","old_counts","percent","process","other_op","tool","feature","prewrite"])
def test_apply_exact_prepared_state_cannot_be_bypassed(regen,case):
    p=regen;prepared=p.prepare();kw={}
    if case=="missing_prep":kw["prepare_receipt_path"]=str(p.path.parent/"missing.json")
    if case=="bad_sha":kw["prepare_receipt_sha256"]="0"*64
    if case=="changed_receipt":p.prep_path.write_text("{}")
    if case=="not_prepared":
        invalid=json.loads(p.prep_path.read_text());invalid["phase"]="unfinished";p.prep_path.write_text(json.dumps(invalid))
    if case=="old_counts":kw["expected_toolpath_record_counts"]=[67]
    if case=="percent":kw["expected_tool_diameter_percent"]=75.
    if case=="process":kw["process_id"]=999
    if case=="other_op":p.current["operations"][1]["toolpath_record_counts"]=[5]
    if case=="tool":p.tool["cut_diameter_native"]=3.
    if case=="feature":p.current["selected_feature"]["depth_native"]=4.
    if case=="prewrite":
        def change():
            if p.captures.call_count==4:p.current["material_raw"]="different"
        p.state["on_capture"]=change
    out=p.apply(prepared,**kw)
    assert out["status"]=="error" and not out["mutation_attempted"]
    p.op.GenerateToolpath.assert_not_called()

def test_same_counts_after_success_still_need_external_fresh_geometry(regen):
    p=regen;prepared=p.prepare()
    p.state["on_native"]=lambda:p.current["operations"][0].update(toolpath_record_counts=[68])
    out=p.apply(prepared)
    assert out["readback_verified"] and not out["fresh_path_geometry_verified"]
    assert out["fresh_CL_WIP_required"]
    p.current["document"]["needs_save"]=False
    replay=p.apply(prepared,receipt_path=str(p.path.parent/"replay.json"))
    assert replay["status"]=="error" and Path(str(p.prep_path)+".apply_attempt.json").is_file()
    p.op.GenerateToolpath.assert_called_once()

@pytest.mark.parametrize("case",["percent","sibling","exception","event","returned_bool"])
def test_after_dispatch_uncertain_never_replays(regen,case):
    p=regen;prepared=p.prepare()
    def change():
        if case=="percent":p.percent=75.
        if case=="sibling":p.current["operations"][1]["toolpath_record_counts"]=[3]
        if case=="exception":raise RuntimeError("unknown native completion")
        if case=="event":p.data["event_count"]=1
    p.state["on_native"]=change
    if case=="returned_bool":p.state["returned"]=False
    out=p.apply(prepared)
    assert out["status"]=="uncertain" and not out["readback_verified"]
    p.op.GenerateToolpath.assert_called_once()
    replay=p.apply(prepared,receipt_path=str(p.path.parent/"replay.json"))
    assert replay["status"]=="error";p.op.GenerateToolpath.assert_called_once()

def test_consumed_before_durable_dispatch_intent_and_no_call_if_write_fails(regen,monkeypatch):
    p=regen;prepared=p.prepare();writer=cam._write_receipt
    def write(path,report,**kw):
        if report.get("native_dispatch_pending"):
            assert Path(str(p.prep_path)+".apply_attempt.json").is_file()
            raise OSError("intent write failed")
        return writer(path,report,**kw)
    monkeypatch.setattr(cam,"_write_receipt",write)
    out=p.apply(prepared)
    assert out["status"] in ("error","uncertain") and not out["mutation_attempted"];p.op.GenerateToolpath.assert_not_called()
    replay=p.apply(prepared,receipt_path=str(p.path.parent/"replay.json"))
    assert replay["status"]=="error";p.op.GenerateToolpath.assert_not_called()

def test_prepare_receipt_cannot_be_overwritten(regen):
    p=regen;first=p.prepare();raw=p.prep_path.read_bytes()
    out=p.prepare()
    assert out["status"]=="error" and p.prep_path.read_bytes()==raw
    p.op.GenerateToolpath.assert_not_called()

def test_prepare_cleanup_failure_is_not_usable(regen):
    p=regen;p.state["on_exit"]=lambda:p.data.update(disconnected=False)
    prepared=p.prepare()
    assert prepared["status"]=="error"
    out=p.apply(prepared);assert out["status"]=="error"
    p.op.GenerateToolpath.assert_not_called()

def test_raw_percent_helper_uses_exact_rough_interface_feature_once(monkeypatch):
    from types import SimpleNamespace
    from scripts import sw_cam_mill_rough_boundary as reader
    rawfeature=object();dispatchfeature=object()
    op=SimpleNamespace(GetToolDiameterPercent=Mock(return_value=0.))
    monkeypatch.setattr(reader,"_dispatch_feature",lambda value:dispatchfeature if value is rawfeature else None)
    typed=Mock(side_effect=lambda raw,name,tlb:raw)
    monkeypatch.setattr(cam,"_typed",typed)
    diagnostic={};checks=Mock();persist=Mock()
    out=cam._read_regeneration_percent(dict(selected_feature=rawfeature,operations={4:op}),4,"tlb",checks,diagnostic,persist)
    typed.assert_called_once_with(op,"ICWRghMillOp","tlb")
    op.GetToolDiameterPercent.assert_called_once_with(dispatchfeature)
    assert out==dict(native_read_complete=True,tool_diameter_percent_native=0.)

@pytest.mark.parametrize("key,value",[("type",True),("type",1.),("needs_save",None),("needs_save",0),("needs_save",1)])
def test_regenerate_raw_document_types_are_not_coerced(regen,key,value):
    regen.current["document"][key]=value
    out=regen.prepare()
    assert out["status"]=="error" and not regen.captures.called
    regen.op.GenerateToolpath.assert_not_called()

def test_null_feature_dispatch_stops_before_rough_qi(monkeypatch):
    from scripts import sw_cam_mill_rough_boundary as reader
    monkeypatch.setattr(reader,"_dispatch_feature",lambda value:None)
    typed=Mock();monkeypatch.setattr(cam,"_typed",typed)
    diagnostic={}
    with pytest.raises(ValueError):
        cam._read_regeneration_percent(dict(selected_feature=object(),operations={4:object()}),4,"tlb",lambda:None,diagnostic,lambda:None)
    typed.assert_not_called()
    assert diagnostic["selected_rough_boundary"]["reads"][0]["returned"]
    assert not diagnostic["selected_rough_boundary"]["reads"][0]["validated"]

def test_returned_percent_retained_before_event_error(monkeypatch):
    from scripts import sw_cam_mill_rough_boundary as reader
    from types import SimpleNamespace
    event=dict(active=False)
    def getter(*args):event["active"]=True;return 0.
    op=SimpleNamespace(GetToolDiameterPercent=getter)
    monkeypatch.setattr(reader,"_dispatch_feature",lambda value:object())
    monkeypatch.setattr(cam,"_typed",lambda *args:op)
    def check():
        if event["active"]:raise ValueError("CAM event")
    diagnostic={}
    with pytest.raises(ValueError):
        cam._read_regeneration_percent(dict(selected_feature=object(),operations={4:op}),4,"tlb",check,diagnostic,lambda:None)
    last=diagnostic["selected_rough_boundary"]["reads"][-1]
    assert last["returned"] and last["native_value"]==0. and not last["validated"]
