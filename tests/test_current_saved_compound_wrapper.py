import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_mill_current_compound_read as core

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
    TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))
    assert len(TREE.body)==2 and isinstance(TREE.body[0],ast.ClassDef) and isinstance(TREE.body[1],ast.FunctionDef)
    exec(compile(TREE,str(SOURCE),'exec'),server.__dict__)
else:
    assert hasattr(server,'SolidWorksCamCurrentSavedCompoundInput')
    assert hasattr(server,'solidworks_cam_inspect_current_saved_compound')


@pytest.fixture
def fake(context,monkeypatch):
    f=Mock(return_value=dict(status='review_required',observation_verified=True,readback_verified=True,guards_verified=True,
        before={'target_header':{'native_id':70},'capture_complete':True},after={'target_header':{'native_id':70},'capture_complete':True}))
    monkeypatch.setattr(core,'inspect_current_saved_compound',f)
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=lambda:None))
    return f


def params(context,**kw):
    v=dict(process_id=731,expected_process_create_time=100.25,addin_clsid=CLSID,
        expected_document_path=context.document,expected_source_sha256='ab'*32,
        expected_feature_native_id=70,expected_feature_setup_native_id=71,expected_operation_setup_native_id=94,
        expected_operation_native_ids=[195,267],expected_generated_operation_count=1,expected_total_record_count=40,
        observation='three_step_profile',qualification_only=True)
    v.update(kw);return server.SolidWorksCamCurrentSavedCompoundInput(**v)


def test_exact_forwarding_and_readonly_annotation(context,fake):
    p=params(context);r=json.loads(server.solidworks_cam_inspect_current_saved_compound(p))
    assert r['readback_verified'] and r['runtime_unchanged']
    fake.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),**p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    t=server.mcp._tool_manager._tools['solidworks_cam_inspect_current_saved_compound']
    assert t.annotations.readOnlyHint and not t.annotations.destructiveHint


@pytest.mark.parametrize('kw',[{'process_id':True},{'expected_process_create_time':True},{'expected_process_create_time':float('inf')},
 {'expected_feature_native_id':True},{'expected_operation_native_ids':[True]},{'expected_operation_native_ids':[1.,2]},
 {'expected_operation_native_ids':[1,1]},{'qualification_only':False},{'qualification_only':1},
 {'expected_generated_operation_count':3},{'expected_total_record_count':100001},{'read_mode':'historical'},
 {'observation':'all_steps'},{'expected_document_title':'part'},{'expected_document_path':'x.sldprt'},
 {'message_policy':'auto_accept'},{'saved_plan_receipt_path':'old.json'},{'action':'apply'},{'index':3}])
def test_schema_rejects_before_connect(context,fake,kw):
    with pytest.raises(ValueError):params(context,**kw)
    fake.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('pid',[None,True,732])
def test_wrong_bound_pid_no_native(context,fake,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid)
    r=json.loads(server.solidworks_cam_inspect_current_saved_compound(params(context)))
    assert r['status']=='error';fake.assert_not_called();context.connect.assert_not_called()


def test_runtime_postdrift_keeps_both_native_observations(context,fake,monkeypatch):
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(side_effect=[None,RuntimeError('drift')])))
    r=json.loads(server.solidworks_cam_inspect_current_saved_compound(params(context)))
    assert r['status']=='error' and not r['runtime_unchanged']
    assert not r['observation_verified'] and not r['readback_verified'] and not r['guards_verified']
    assert r['before']['capture_complete'] and r['after']['capture_complete']
    assert r['before']['target_header']['native_id']==70 and fake.call_count==1
