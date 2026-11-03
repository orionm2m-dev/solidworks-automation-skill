"""MCP schema and selected-process routing for the bounded recipe transaction."""
import json,sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server
from test_sw_cam_turn_feature_regenerate import policy_for
from scripts import sw_cam_turn_feature_regenerate as cam


def params(context,tmp_path,**changes):
    source=tmp_path/'source.sldprt';database=tmp_path/'db.mdb'
    source.write_bytes(b'saved');database.write_bytes(b'recipe')
    return server.SolidWorksCamTurnFeatureRegenerateInput(**(dict(addin_clsid=CLSID,
        process_id=731,expected_process_create_time=1234.,expected_document_path=context.document,
        expected_source_sha256=cam._file_hash(source),feature_setup_index=0,expected_feature_native_id=76,
        expected_turn_feature_type=2,attribute_name='Rough-Finish',policy=policy_for(source,database,cam._file_hash(source)))|changes))


@pytest.fixture
def core(context,monkeypatch):
    native=Mock(return_value={'status':'prepared'})
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_turn_feature_regenerate',SimpleNamespace(
        qualify_turn_feature_recipe=native,validate=cam.validate))
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock()))
    return native


def test_real_server_registration_and_route(context,core,tmp_path):
    tool=server.mcp._tool_manager._tools['solidworks_cam_qualify_turn_feature_recipe']
    assert tool.annotations.destructiveHint and not tool.annotations.idempotentHint
    p=params(context,tmp_path)
    assert json.loads(server.solidworks_cam_qualify_turn_feature_recipe(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize('selection',[None,True,123])
def test_wrong_selection_no_target_call(context,core,tmp_path,monkeypatch,selection):
    monkeypatch.setattr(server,'_selected_process_id',selection)
    assert json.loads(server.solidworks_cam_qualify_turn_feature_recipe(params(context,tmp_path)))['status']=='error'
    core.assert_not_called();context.connect.assert_not_called()


def test_runtime_guard_stops_before_target(context,core,tmp_path):
    server._runtime_identity.assert_current.side_effect=ValueError('changed')
    assert json.loads(server.solidworks_cam_qualify_turn_feature_recipe(params(context,tmp_path)))['status']=='error'
    core.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('field,value',[('action','retry'),('action','apply'),('process_id',True),
    ('expected_process_create_time',True),('expected_process_create_time',float('nan')),('policy',{}),
    ('receipt_path','relative.json'),('receipt_path','C:/evidence/unused.json'),('expected_state_sha256','a'*64),('max_operations',65),('attribute_name',None),('Save',True)])
def test_invalid_request_stops_at_schema(context,core,tmp_path,field,value):
    with pytest.raises(ValueError):params(context,tmp_path,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()
