"""运行时漂移保留实际状态，且只更新本次拥有的回执；无 CAD 调用。"""
from copy import deepcopy
import json,sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_turn_holder_dimensions as cam
from test_mcp_cam_operation_diagnostics import context,server
from test_mcp_cam_turn_holder_dimensions import params


def evidence(path,mutation=True):
    return dict(scope=cam.SCOPE,status="review_required" if mutation else "prepared",mutation_attempted=mutation,
        readback_verified=mutation,apply_eligible=not mutation,logical_binding_verified=True,
        holder_file_fields_preserved=mutation,receipt_created=path is not None,receipt_path=str(path) if path else None,
        request={"action":"apply" if mutation else "prepare","values_native":{"LeadAngle":-32.}},
        before={"actual":-10.},after={"actual":-32.},captures=[{"state":{"actual":-32.},"capture_complete":True}],
        setters=[{"attempted":True,"returned":True,"after":{"actual":-32.}}] if mutation else [])


@pytest.mark.parametrize("mutation",[False,True])
def test_wrapper_post_call_drift_preserves_native_evidence_without_replay(context,tmp_path,monkeypatch,mutation):
    path=tmp_path/"owned.json" if mutation else None
    raw=evidence(path,mutation);retained=deepcopy(raw)
    if path:cam._write_receipt(path,raw,create=True)
    native=Mock(return_value=raw)
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_turn_holder_dimensions",SimpleNamespace(
        configure_turn_holder_dimensions=native,validate=cam.validate,revoke_runtime_verification=cam.revoke_runtime_verification))
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=Mock(side_effect=[None,ValueError("runtime changed")])) )
    kw={} if not mutation else dict(action="apply",expected_state_sha256="b"*64,receipt_path=str(path),
        allowed_affected_operations=[dict(setup_index=0,operation_index=7,expected_operation_type=6)])
    result=json.loads(server.solidworks_cam_configure_turn_holder_dimensions(params(context,tmp_path,**kw)))
    native.assert_called_once()
    assert result["status"]==("uncertain" if mutation else "error")
    assert all(result[k] is False for k in ("readback_verified","apply_eligible","logical_binding_verified","holder_file_fields_preserved","runtime_unchanged","may_continue"))
    assert all(result[k]==retained[k] for k in ("before","after","captures","setters"))
    assert result["historical_verification_before_runtime_drift"]["status"]==retained["status"]
    if path:assert json.loads(path.read_text(encoding="utf-8"))==result and result["runtime_drift_receipt_updated"]


@pytest.mark.parametrize("mismatch",["unowned","wrong_path","wrong_request","wrong_scope","missing"])
def test_runtime_drift_never_rewrites_foreign_receipt(tmp_path,mismatch):
    path=tmp_path/"owned.json";result=evidence(path);disk=deepcopy(result)
    if mismatch=="unowned":result["receipt_created"]=False
    elif mismatch=="wrong_path":result["receipt_path"]=str(tmp_path/"other.json")
    elif mismatch=="wrong_request":disk["request"]={"different":True}
    elif mismatch=="wrong_scope":disk["scope"]="other"
    if mismatch!="missing":cam._write_receipt(path,disk,create=True)
    original=path.read_bytes() if path.exists() else None
    returned=cam.revoke_runtime_verification(result,ValueError("drift"),str(path))
    assert returned is result and not returned["runtime_drift_receipt_updated"]
    assert returned["status"]=="uncertain" and not returned["readback_verified"]
    assert (path.read_bytes() if path.exists() else None)==original


def test_runtime_drift_failed_owned_receipt_write_is_explicit(tmp_path,monkeypatch):
    path=tmp_path/"owned.json";result=evidence(path);cam._write_receipt(path,result,create=True)
    original=path.read_bytes()
    monkeypatch.setattr(cam,"_write_receipt",Mock(side_effect=OSError("disk failed")))
    result=cam.revoke_runtime_verification(result,ValueError("drift"),str(path))
    assert not result["runtime_drift_receipt_updated"] and result["runtime_drift_receipt_error"]["type"]=="OSError"
    assert result["status"]=="uncertain" and not result["readback_verified"]
    assert result["after"]=={"actual":-32.} and path.read_bytes()==original
