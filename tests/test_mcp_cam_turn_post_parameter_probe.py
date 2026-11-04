import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_turn_post_parameter_probe as core


@pytest.fixture
def fake(context,monkeypatch):
    f=Mock(return_value=dict(status='review_required',observation_verified=True,guards_verified=True,index_zero_acceptance_verified=True,
        entry_raw={'name':'x','value':'.1'},before={'capture_complete':True},after={'capture_complete':True}))
    monkeypatch.setattr(core,'probe_turn_post_parameter',f)
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=lambda:None))
    return f

def params(context,**changes):
    v=dict(process_id=731,expected_process_create_time=100.25,addin_clsid=CLSID,expected_document_path=context.document,expected_source_sha256='ab'*32,
        expected_operation_count=1,expected_generated_operation_count=1,expected_total_record_count=40,qualification_only=True)
    v.update(changes);return server.SolidWorksCamTurnPostParameterProbeInput(**v)


def test_public_exact_forwarding(context,fake):
    p=params(context);r=json.loads(server.solidworks_cam_probe_turn_post_parameter(p))
    assert r['runtime_unchanged'] and r['observation_verified']
    fake.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),**p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    t=server.mcp._tool_manager._tools['solidworks_cam_probe_turn_post_parameter']
    assert t.annotations.readOnlyHint and not t.annotations.destructiveHint

@pytest.mark.parametrize('changes',[{'qualification_only':False},{'qualification_only':1},{'process_id':True},
 {'expected_process_create_time':True},{'expected_process_create_time':float('inf')},{'expected_operation_count':1.},
 {'expected_generated_operation_count':2},{'action':'apply'},{'action':'read'},{'index':1},{'count':4},
 {'expected_document_path':'relative.sldprt'},{'message_policy':'auto_accept'},{'values_native':{}},{'receipt_path':'a.json'}])
def test_schema_stops_before_connect(context,fake,changes):
    with pytest.raises(ValueError):params(context,**changes)
    fake.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize('pid',[None,True,732])
def test_wrong_bound_pid_no_call(context,fake,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid)
    r=json.loads(server.solidworks_cam_probe_turn_post_parameter(params(context)))
    assert r['status']=='error';fake.assert_not_called();context.connect.assert_not_called()


def test_runtime_drift_keeps_native_result_revokes_acceptance(context,fake,monkeypatch):
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(side_effect=[None,RuntimeError('drift')])))
    r=json.loads(server.solidworks_cam_probe_turn_post_parameter(params(context)))
    assert r['status']=='error' and not r['guards_verified'] and not r['observation_verified'] and not r['index_zero_acceptance_verified']
    assert r['entry_raw']=={'name':'x','value':'.1'} and r['before']['capture_complete'] and r['after']['capture_complete']
    assert fake.call_count==1 and not r['runtime_unchanged']
