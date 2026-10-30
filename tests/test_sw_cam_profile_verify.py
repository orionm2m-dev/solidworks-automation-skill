"""Native-method fakes for bounded existing circle readback; no CAD application."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import sw_cam_profile_sketch as m
from scripts import sw_cam_profile_verify as v
from test_sw_cam_profile_sketch import (
    circle, NativeModel, NativeSegment, NativeSketch, Transform, NativeFeature,
    NativeSW, native,
)

@pytest.fixture
def existing(native, monkeypatch, tmp_path):
    path=tmp_path/"part.SLDPRT";path.write_bytes(b"saved source")
    spec=circle("Z",10.9);model=NativeModel(2);native.ActiveDoc=model
    model.dirty=False
    native.GetProcessID=lambda:100
    model.GetType=lambda:1
    model.GetSaveFlag=lambda:model.dirty
    model.GetPathName=lambda:str(path)
    model.GetTitle=lambda:path.name
    model.IsOpenedReadOnly=lambda:False
    model.GetConfigurationNames=lambda:["Default"]
    body=type("Body",(),{})()
    body.box=[0.,0.,0.,1.,1.,1.];body.mass=[1.,2.,3.,4.]
    body.GetBodyBox=lambda:list(body.box)
    body.GetMassProperties=lambda density:list(body.mass)
    model.GetBodies2=lambda *args:[body]
    class Lock:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(m,"solidworks_operation_lock",lambda **kw:Lock())
    before,_,refs=m._snapshot(native,100,str(path),spec)
    receipt=dict(status="uncertain",phase="create_profile",mutation_attempted=True,
        saved=False,CAD_solid_edit_attempted=False,CAM_calls=0,native_readback_verified=False,
        before=deepcopy(before),state_sha256=m._state_digest(before))
    m._create(native,model,before,refs,lambda:None,receipt)
    receipt.pop("sketch_readback",None)
    receipt["failed_phase"]="create_profile"
    receipt["issue"]={"type":"ValueError","message":"full circle required"}
    model.dirty=True
    for feat in model.features:feat.IsSuppressed=lambda:False
    prior=tmp_path/"creator.json"
    def rewrite():
        prior.write_text(json.dumps(receipt,allow_nan=False),encoding="utf-8")
    rewrite()
    original_calls=list(model.SketchManager.calls)
    monkeypatch.setattr(m,"_create",lambda *a:pytest.fail("creation forbidden"))
    model.ClearSelection2=lambda *a:pytest.fail("selection forbidden")
    model.InsertRefPlane=lambda *a:pytest.fail("plane creation forbidden")
    model.SketchManager.InsertSketch=lambda *a:pytest.fail("sketch edit forbidden")
    args=dict(expected_process_id=100,expected_document_path=str(path),
        action="verify_existing",spec=spec,qualification_only=True,
        expected_source_sha256=m._sha(path),creation_receipt_path=str(prior),
        creation_receipt_sha256=m._sha(prior),receipt_path=str(tmp_path/"verify.json"))
    return dict(sw=native,model=model,body=body,path=path,spec=spec,prior=prior,
        receipt=receipt,rewrite=rewrite,args=args,original_calls=original_calls)

def run(e,**changes):
    return m.create_cam_profile_sketch(e["sw"],**(e["args"]|changes))

def test_verify_dirty_existing_circle_is_readonly(existing):
    e=existing;original=e["prior"].read_bytes();out=run(e)
    assert out["status"]=="ok" and out["native_readback_verified"]
    assert out["before"]==out["after"]
    assert out["before"]["needs_save"] is True
    assert out["native_read_diagnostics"][0]["diagnostic"]["IsCircle"]=={"native_type":"int","native_value":1}
    assert not out["mutation_attempted"] and not out["saved"] and out["CAM_calls"]==0
    assert e["prior"].read_bytes()==original
    assert e["model"].SketchManager.calls==e["original_calls"]
    assert e["path"].read_bytes()==b"saved source"
    assert json.loads(Path(e["args"]["receipt_path"]).read_text())["native_readback_verified"]

def test_verify_clean_existing_circle_allowed(existing):
    existing["model"].dirty=False
    assert run(existing)["native_readback_verified"]

@pytest.mark.parametrize("value",[0,-1,True,False,1.0,"1",None,2])
def test_native_IsCircle_strict_and_error_retains_raw(existing,value):
    e=existing;sketch=e["model"].features[-1].obj
    sketch.segments[0].IsCircle=lambda:value
    out=run(e)
    assert out["status"]=="error" and not out["native_readback_verified"]
    raw=out["native_read_diagnostics"][0]["diagnostic"]["IsCircle"]
    assert raw["native_type"]==type(value).__name__
    assert raw["native_value"]==value
    disk=json.loads(Path(e["args"]["receipt_path"]).read_text())
    assert disk["native_read_diagnostics"]==out["native_read_diagnostics"]

@pytest.mark.parametrize("getter,value",[("GetProcessID",True),("GetProcessID",100.0),
    ("GetProcessID",101),("GetType",True),("GetType",1.0),("GetType",2),
    ("GetSaveFlag",None),("GetSaveFlag",0),("GetSaveFlag","True")])
def test_native_identity_types_not_coerced(existing,getter,value):
    e=existing
    setattr(e["sw"] if getter=="GetProcessID" else e["model"],getter,lambda:value)
    out=run(e)
    assert out["status"]=="error" and not out["native_readback_verified"]
    assert out["native_read_diagnostics"]==[]

@pytest.mark.parametrize("fault",["old_feature","extra_feature","missing_plane","missing_sketch",
    "body_mass","body_box","plane","radius","center","sketch_plane","suppressed"])
def test_existing_delta_or_geometry_mismatch(existing,fault):
    e=existing;model=e["model"]
    if fault=="old_feature":model.features[0].Name="Changed"
    if fault=="extra_feature":model.features.append(NativeFeature(model,"Unrelated","Boss",None))
    if fault=="missing_plane":model.features.pop(-2)
    if fault=="missing_sketch":model.features.pop()
    if fault=="body_mass":e["body"].mass[0]+=.1
    if fault=="body_box":e["body"].box[0]+=.1
    if fault=="plane":model.features[-2].obj.Transform.offset+=.001
    if fault=="radius":model.features[-1].obj.segments[0].r+=.001
    if fault=="center":model.features[-1].obj.segments[0].a[0]+=.001
    if fault=="sketch_plane":model.features[-1].obj.ModelToSketchTransform=Transform(0,.0109)
    if fault=="suppressed":model.features[-1].IsSuppressed=lambda:True
    out=run(e)
    assert out["status"]=="error" and not out["native_readback_verified"]
    assert not out["mutation_attempted"] and not out["saved"]

@pytest.mark.parametrize("field,value",[("sketch_edit_exited",False),("saved",True),
    ("CAM_calls",True),("CAM_calls",1),("plane_create_attempted",False),
    ("sketch_create_attempted",False),("CAD_solid_edit_attempted",True),
    ("status","error"),("cleanup_errors",["unclosed"])])
def test_creator_evidence_scope_failure_before_native(existing,monkeypatch,field,value):
    e=existing;e["receipt"][field]=value;e["rewrite"]()
    monkeypatch.setattr(v,"_identity",lambda *a:pytest.fail("native not permitted"))
    out=run(e,creation_receipt_sha256=m._sha(e["prior"]))
    assert out["status"]=="error" and not Path(e["args"]["receipt_path"]).exists()

@pytest.mark.parametrize("key,value",[("pid",101),("needs_save",True),
    ("saved_file_sha256","f"*64)])
def test_baseline_identity_mismatch(existing,key,value):
    e=existing;e["receipt"]["before"][key]=value
    e["receipt"]["state_sha256"]=m._state_digest(e["receipt"]["before"]);e["rewrite"]()
    assert run(e,creation_receipt_sha256=m._sha(e["prior"]))["status"]=="error"

def test_source_hash_mismatch_no_native(existing,monkeypatch):
    e=existing;e["path"].write_bytes(b"changed")
    monkeypatch.setattr(m,"_snapshot",lambda *a:pytest.fail("snapshot forbidden"))
    out=run(e)
    assert out["status"]=="error" and not out["native_readback_verified"]

def test_creator_sha_change_rejected(existing):
    e=existing;e["prior"].write_text(e["prior"].read_text()+" ")
    assert run(e)["status"]=="error"

def test_duplicate_creator_keys_rejected(existing):
    e=existing;e["prior"].write_text('{"status":"ok","status":"uncertain"}')
    assert run(e,creation_receipt_sha256=m._sha(e["prior"]))["status"]=="error"

def test_existing_output_not_replayed(existing,monkeypatch):
    e=existing;out=Path(e["args"]["receipt_path"]);out.write_text("unchanged")
    monkeypatch.setattr(v,"_identity",lambda *a:pytest.fail("native forbidden"))
    assert run(e)["status"]=="error" and out.read_text()=="unchanged"

def test_intent_receipt_failure_has_no_native_calls(existing,monkeypatch):
    monkeypatch.setattr(m,"_write_receipt",lambda *a,**kw:(_ for _ in ()).throw(OSError("locked")))
    monkeypatch.setattr(v,"_identity",lambda *a:pytest.fail("native forbidden"))
    assert run(existing)["status"]=="error"

@pytest.mark.parametrize("fault",["source","receipt","dirty"])
def test_change_during_getter_stops_before_second_read(existing,fault):
    e=existing;calls=[]
    def native_flag():
        calls.append(1)
        if fault=="source":e["path"].write_bytes(b"changed")
        if fault=="receipt":e["prior"].write_text(e["prior"].read_text()+" ")
        if fault=="dirty":e["model"].dirty=False
        return 1
    e["model"].features[-1].obj.segments[0].IsCircle=native_flag
    out=run(e)
    assert out["status"]=="error" and len(calls)==1 and "after" not in out

def test_state_change_between_readbacks_rejected(existing,monkeypatch):
    e=existing;original=m._snapshot;calls=[]
    def snapshot(*args):
        calls.append(1)
        if len(calls)==2:e["body"].mass[0]+=.1
        return original(*args)
    monkeypatch.setattr(m,"_snapshot",snapshot)
    out=run(e)
    assert out["status"]=="error" and not out["native_readback_verified"] and len(calls)==2

@pytest.mark.parametrize("newfield",["expected_source_sha256","creation_receipt_path","creation_receipt_sha256"])
def test_old_creation_actions_reject_new_nonnull_evidence(existing,newfield):
    e=existing;kw=dict(expected_process_id=100,expected_document_path=str(e["path"]),
        action="prepare",spec=e["spec"],qualification_only=True)
    kw[newfield]="x"
    assert m.create_cam_profile_sketch(e["sw"],**kw)["status"]=="error"

def test_verify_module_contains_no_native_mutators():
    import inspect
    source=inspect.getsource(v)
    for name in ("ClearSelection2","Select2","InsertSketch","InsertRefPlane","CreateCircleByRadius",
                 "Save3","SaveAs","GenerateToolpath","DeleteSelection","EditUndo"):
        assert name not in source

@pytest.mark.parametrize("value",[float("nan"),float("inf"),-float("inf")])
def test_nonfinite_native_IsCircle_keeps_json_receipt(existing,value):
    e=existing;e["model"].features[-1].obj.segments[0].IsCircle=lambda:value
    out=run(e)
    assert out["status"]=="error" and "receipt_write_error" not in out
    raw=out["native_read_diagnostics"][0]["diagnostic"]["IsCircle"]
    assert raw["native_type"]=="float" and raw["native_value"] is None
    assert raw["native_repr"]==repr(value)
    assert json.loads(Path(e["args"]["receipt_path"]).read_text())["status"]=="error"
