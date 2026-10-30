"""Shared provenance and adapter plumbing, with no native application calls."""
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import importlib
import pytest
from scripts import sw_cam_mill_feature_context as shared
from test_sw_cam_circular_mill_lifecycle import saved,case

def request(**changes):
    return dict(process_id=731,expected_document_path="C:/part.sldprt",
        expected_feature_native_id=99,expected_source_sha256="a"*64,
        feature_kind="circular_pocket",circle_creation_receipt_path="C:/creation.json",
        circle_creation_receipt_sha256="b"*64)|changes

def test_legacy_capture_exact_args_and_state():
    state={"old":"digest shape"};native=object();legacy=Mock(return_value=(state,native));check=Mock();diagnostic={}
    out=shared.capture_selected_mill_context("sw","clsid","tlb","C:/part.sldprt",
        expected_feature_native_id=99,check=check,diagnostic=diagnostic,legacy_capture=legacy)
    assert out[0] is state and out[1] is native
    legacy.assert_called_once_with("sw","clsid","tlb","C:/part.sldprt",
        expected_feature_native_id=99,check=check,diagnostic=diagnostic)
    check.assert_not_called()

def test_legacy_load_is_noop():
    assert shared.load_selected_mill_context(process_id=None,expected_document_path=None,
        expected_feature_native_id=None,expected_source_sha256=None) is None

@pytest.mark.parametrize("field,value",[
 ("feature_kind",None),("feature_kind",True),("feature_kind","circle"),
 ("expected_feature_native_id",True),("expected_feature_native_id",0),("expected_feature_native_id",1.0),
 ("expected_source_sha256",None),("expected_source_sha256","A"*64),("expected_source_sha256",True),
 ("circle_creation_receipt_sha256",None),("circle_creation_receipt_sha256","x"),
 ("circle_creation_receipt_path",None),("circle_creation_receipt_path","relative.json"),
 ("circle_creation_receipt_path","C:/wrong.txt"),("process_id",True),("process_id",0),
 ("expected_document_path","relative.sldprt"),("expected_document_path","C:/wrong.sldasm")])
def test_invalid_context_fails_before_evidence(field,value,monkeypatch):
    from scripts import sw_cam_circle_lifecycle_evidence as evidence
    loader=Mock(side_effect=AssertionError("must not read evidence"));monkeypatch.setattr(evidence,"read_circle_creation_evidence",loader)
    with pytest.raises(ValueError):shared.load_selected_mill_context(**request(**{field:value}))
    loader.assert_not_called()

@pytest.mark.parametrize("field",["circle_creation_receipt_path","circle_creation_receipt_sha256"])
def test_default_rejects_circle_inputs(field):
    data=request(feature_kind="open_pocket",circle_creation_receipt_path=None,circle_creation_receipt_sha256=None)
    data[field]="C:/x.json" if field.endswith("path") else "a"*64
    with pytest.raises(ValueError):shared.load_selected_mill_context(**data)

def context(saved):
    return shared.load_selected_mill_context(**{k:v for k,v in saved.base.items()
        if k not in ("acknowledge_qualification_copy","expected_operation_native_ids")})

def capture(saved,ctx,diagnostic=None):
    saved.case.status.update(subscribed=True,active=True,disconnected=False)
    return shared.capture_selected_mill_context(saved.case.sw,"clsid","tlb",str(saved.case.part),
        expected_feature_native_id=99,check=lambda:None,context=ctx,diagnostic=diagnostic,
        legacy_capture=saved.capture)

def test_shared_capture_preserves_raw_mass_diagnostics_outside_prepared_digest(saved):
    from scripts.sw_cam_turn_tool import _digest
    ctx=context(saved);first_diagnostic={};second_diagnostic={}
    first,_=capture(saved,ctx,first_diagnostic)
    original=deepcopy(saved.case.state["solids"])
    saved.case.state["solids"][0]["mass_raw"][3]*=1+5e-14
    second,_=capture(saved,ctx,second_diagnostic)
    assert first["circle_reference"]["solids"]==second["circle_reference"]["solids"]==original
    assert _digest(first)==_digest(second)
    assert first_diagnostic["circle_solid_observation"]["observed"]==original
    assert second_diagnostic["circle_solid_observation"]["observed"]!=original
    assert second_diagnostic["circle_solid_observation"]["comparison_verified"] is True
    assert "circle_solid_observation" not in second


def test_actual_creator_geometry_survives_mutable_operations_and_saved_checkpoint(saved):
    # The creator had zero operations and the original disk checkpoint.
    saved.case.part.write_bytes(b"explicitly saved feature and generated operations")
    saved.base["expected_source_sha256"]=shared_hash(saved.case.part)
    saved.state.update(operations=[{"native_id":125,"toolpath_generated":True,"toolpath_record_counts":[42]}],
                       operation_counts=[1],operation_setup_count=1)
    state,_=capture(saved,context(saved))
    assert state["operations"]==saved.state["operations"]
    assert state["selected_feature"]==saved.creation["observed_feature"]
    assert state["selected_mill_context"]["process_id"]==731
    assert state["circle_reference"] and state["circle_creation_evidence"]

def shared_hash(path):
    from scripts.sw_cam_thread import _file_hash
    return _file_hash(path)

@pytest.mark.parametrize("field,value",[("type",True),("type",1.0),("needs_save",None),("needs_save",0),("needs_save",1)])
def test_strict_circle_identity_before_capture(saved,field,value):
    ctx=context(saved);saved.case.document[field]=value
    with pytest.raises(ValueError):capture(saved,ctx)

def test_pid_cross_context_not_accepted(saved):
    ctx=context(saved);ctx["process_id"]=732
    with pytest.raises(ValueError,match="PID"):capture(saved,ctx)

def test_current_checkpoint_and_receipt_are_independent_pins(saved):
    ctx=context(saved);saved.case.part.write_bytes(b"unexpected file drift")
    with pytest.raises(ValueError,match="source SHA"):capture(saved,ctx)

@pytest.mark.parametrize("field",["expected_document_path","expected_feature_native_id"])
def test_capture_selector_cannot_override_loaded_provenance(saved,field):
    ctx=context(saved);ctx[field]="C:/other.sldprt" if field.endswith("path") else 100
    with pytest.raises(ValueError,match="differs"):capture(saved,ctx)

def test_lifecycle_source_refresh_only_after_explicit_save(saved):
    result=saved.apply()
    assert result["save_readback_verified"],result
    assert all(d["circle_solid_observation"]["comparison_verified"] is True
               for d in result["snapshot_diagnostics"])
    assert result["after"]["saved_file_sha256"]!=result["before"]["saved_file_sha256"]
    assert result["after"]["selected_mill_context"]==result["before"]["selected_mill_context"]

def test_lifecycle_drift_before_native_action_cannot_be_rebased(saved,monkeypatch):
    from scripts import sw_cam_mill_feature_lifecycle as lifecycle
    original=lifecycle.capture_selected_mill_context;calls=[]
    def drift(*args,**kwargs):
        calls.append(kwargs.get("current_source_sha256"))
        if len(calls)==2:saved.case.part.write_bytes(b"external drift before dispatch")
        return original(*args,**kwargs)
    p=saved.run();monkeypatch.setattr(lifecycle,"capture_selected_mill_context",drift)
    out=saved.run("save",expected_state_sha256=p["state_sha256"],receipt_path=str(saved.output))
    assert out["status"]=="error" and not out["mutation_attempted"],out
    assert calls==[None,None];saved.app.SaveActiveDocument.assert_not_called()

ADAPTERS=[
 ("test_sw_cam_mill_feature_process","run",{"action":"prepare"}),
 ("test_sw_cam_mill_toolpath","run",{"action":"prepare"}),
 ("test_sw_cam_mill_tool_diameter","run",{"action":"prepare"}),
 ("test_sw_cam_mill_levels","run",{}),
 ("test_sw_cam_mill_rough_boundary","run",{}),
 ("test_sw_cam_mill_rough_boundary_set","run",{}),
 ("test_sw_cam_mill_generic_cl","call",{"action":"prepare"}),
 ("test_sw_cam_mill_geometry","run",{"action":"prepare"})]
@pytest.mark.parametrize("module,runner,extra",ADAPTERS)
def test_all_consumers_explicitly_forward_context_without_changing_mutation_policy(tmp_path,monkeypatch,module,runner,extra):
    fixture=importlib.import_module(module);adapter=importlib.import_module("scripts."+module.removeprefix("test_"));monkeypatch.setattr(fixture,"cam",adapter);probe=fixture.probe.__wrapped__(tmp_path,monkeypatch)
    marker={"sentinel":"explicit context"};loader=Mock(return_value=marker)
    monkeypatch.setattr(adapter,"load_selected_mill_context",loader)
    monkeypatch.setattr(adapter,"selected_context_identity",lambda *_:{"document":deepcopy(probe.current["document"])})
    seen=[]
    def forward(*args,context,legacy_capture,**kwargs):
        seen.append(context);return legacy_capture(*args,**kwargs)
    monkeypatch.setattr(adapter,"capture_selected_mill_context",forward)
    out=getattr(probe,runner)(**extra,feature_kind="circular_pocket",
        circle_creation_receipt_path=str(tmp_path/"creator.json"),circle_creation_receipt_sha256="b"*64)
    assert out["status"] in ("ok","review_required"),out
    assert seen and all(x is marker for x in seen)
    assert loader.call_args.kwargs["feature_kind"]=="circular_pocket"
    assert not out.get("mutation_attempted")
