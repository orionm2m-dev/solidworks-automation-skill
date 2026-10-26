"""归属进程恢复的严格 MCP 路由；所有进程 API 与 COM 均为 trap/mock。"""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import server
from scripts import sw_owned_process_recovery as recovery

@pytest.fixture
def probe(tmp_path,monkeypatch):
    evidence=dict(path=str(tmp_path/"evidence.json"),sha256="ab"*32)
    spec=dict(process_id=31316,expected_executable_path="C:/Vendor/SLDWORKS.exe",
        expected_creation_filetime=134374603574011237,ownership_receipt=evidence,
        process_identity_evidence=deepcopy(evidence),recovery_manifest=deepcopy(evidence))
    core=Mock(return_value=dict(status="ok",may_continue=False,COM_calls=0,UI_calls=0))
    guard=Mock()
    monkeypatch.setattr(recovery,"recover_owned_process",core)
    monkeypatch.setattr(server,"_runtime_identity",SimpleNamespace(assert_current=guard))
    forbidden=Mock(side_effect=AssertionError("No COM/bootstrap/automation wrapper in recovery"))
    for name in ["connect_solidworks","_cam_target","_run_locked","_coinitialize","_load_automation_modules"]:
        monkeypatch.setattr(server,name,forbidden,raising=False)
    def raw(**changes):
        values=dict(action="prepare",spec=deepcopy(spec))
        values.update(changes)
        if values["action"]=="apply":
            values.setdefault("expected_state_sha256","cd"*32)
            values.setdefault("acknowledge_terminate_owned_process",True)
            values.setdefault("acknowledged_discard_ids",["gop-unsaved"])
            values.setdefault("receipt_path",str(tmp_path/"new.json"))
        return values
    def model(**changes):return server.SolidWorksOwnedProcessRecoveryInput(**raw(**changes))
    return SimpleNamespace(**locals())

@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_process_only_exact_route_without_connect_or_com(probe,action):
    params=probe.model(action=action)
    result=json.loads(server.solidworks_recover_owned_process(params))
    assert result==probe.core.return_value
    probe.core.assert_called_once_with(**params.model_dump(exclude={"response_format"}))
    probe.guard.assert_called_once();probe.forbidden.assert_not_called()
    schema=server.mcp._tool_manager._tools["solidworks_recover_owned_process"]
    assert schema.annotations.destructiveHint and not schema.annotations.idempotentHint
    assert "_api" not in json.dumps(schema.parameters) and "_lock_factory" not in json.dumps(schema.parameters)

@pytest.mark.parametrize("field,value",[("wait_milliseconds",True),("wait_milliseconds",1.0),
    ("wait_milliseconds",-1),("wait_milliseconds",10001),("acknowledge_terminate_owned_process",1),
    ("acknowledged_discard_ids",[1]),("acknowledged_discard_ids",["a","a"]),
    ("acknowledged_discard_ids",["invalid id"]),("expected_state_sha256","x"*64)])
def test_invalid_inputs_before_process_core(probe,field,value):
    with pytest.raises(ValueError):probe.model(action="apply",**{field:value})
    probe.core.assert_not_called();probe.forbidden.assert_not_called()

@pytest.mark.parametrize("field,value",[("process_id",True),("process_id",0),("process_id",1.0),
    ("expected_creation_filetime",True),("expected_creation_filetime",1),
    ("expected_executable_path","C:/Vendor/foreign.exe"),("expected_executable_path","SLDWORKS.exe")])
def test_spec_identity_strict(probe,field,value):
    spec=deepcopy(probe.spec);spec[field]=value
    with pytest.raises(ValueError):probe.model(spec=spec)
    probe.core.assert_not_called()

@pytest.mark.parametrize("field",["expected_state_sha256","acknowledged_discard_ids","receipt_path","acknowledge_terminate_owned_process"])
def test_read_only_action_refuses_termination_inputs(probe,field):
    values=probe.raw(action="apply")
    with pytest.raises(ValueError):probe.model(**{field:values[field]})

@pytest.mark.parametrize("field",["expected_state_sha256","acknowledged_discard_ids","receipt_path"])
def test_apply_requires_every_guard(probe,field):
    with pytest.raises(ValueError):probe.model(action="apply",**{field:None})

@pytest.mark.parametrize("field",["_api","_lock_factory","process_id","addin_clsid"])
def test_no_extra_hooks_or_generic_target_allowed(probe,field):
    with pytest.raises(ValueError):probe.model(**{field:"injected"})

@pytest.mark.parametrize("suffix",["", ".tmp"])
def test_owned_receipt_or_pending_temp_blocks_replay(probe,suffix):
    path=probe.tmp_path/("new.json"+suffix);path.write_text("prior")
    with pytest.raises(ValueError):probe.model(action="apply")
    assert path.read_text()=="prior";probe.core.assert_not_called()

def test_runtime_source_mismatch_stops_before_process_core(probe):
    probe.guard.side_effect=RuntimeError("source changed")
    result=json.loads(server.solidworks_recover_owned_process(probe.model()))
    assert result["status"]=="error";probe.core.assert_not_called();probe.forbidden.assert_not_called()

def test_blocked_and_uncertain_reports_are_preserved(probe):
    probe.core.return_value=dict(status="review_required",termination_attempted=True,process_exit_verified=False)
    assert json.loads(server.solidworks_recover_owned_process(probe.model(action="apply")))==probe.core.return_value

def test_no_connect_required_even_when_server_has_no_pinned_pid(probe,monkeypatch):
    monkeypatch.setattr(server,"_selected_process_id",None)
    assert json.loads(server.solidworks_recover_owned_process(probe.model()))["status"]=="ok"
    probe.forbidden.assert_not_called()
