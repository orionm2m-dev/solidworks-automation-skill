"""Exact process/schema and normal target routing for the read-only recipe inspector."""
import json,sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server


@pytest.fixture
def core(context,monkeypatch):
    native=Mock(return_value={'status':'ok','read_only':True})
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_turn_feature_recipe',SimpleNamespace(inspect_turn_feature_recipe=native))
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(return_value={'status':'ready'})))
    return native


def params(context,**changes):
    return server.SolidWorksCamTurnFeatureRecipeInput(**(dict(addin_clsid=CLSID,
        process_id=731,expected_document_path=context.document,expected_source_sha256='a'*64,
        feature_setup_index=0,expected_feature_native_id=76,expected_turn_feature_type=2,
        attribute_name='Rough-Finish')|changes))


def test_registered_readonly_schema():
    tool=server.mcp._tool_manager._tools['solidworks_cam_inspect_turn_feature_recipe']
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is True


def test_exact_route_and_lock(context,core):
    p=params(context)
    assert json.loads(server.solidworks_cam_inspect_turn_feature_recipe(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,
        typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize('selection',[None,123,True])
def test_wrong_selected_process_never_connects(context,core,monkeypatch,selection):
    monkeypatch.setattr(server,'_selected_process_id',selection)
    result=json.loads(server.solidworks_cam_inspect_turn_feature_recipe(params(context)))
    assert result['status']=='error';core.assert_not_called();context.connect.assert_not_called()


def test_runtime_guard_stops_before_connect(context,core):
    server._runtime_identity.assert_current.side_effect=ValueError('Changed runtime')
    assert json.loads(server.solidworks_cam_inspect_turn_feature_recipe(params(context)))['status']=='error'
    core.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('field,value',[('process_id',True),('max_features',65),('max_operations',65),
    ('feature_setup_index',64),('expected_feature_native_id',0),('expected_turn_feature_type',False),
    ('expected_source_sha256','bad'),('attribute_name',''),('expected_document_path','relative.sldprt'),
    ('action','apply'),('GOP',True)])
def test_invalid_inputs_reject_without_connect(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()


def test_optional_name_kept_exact(context,core):
    assert params(context,attribute_name=None).attribute_name is None
    assert params(context,attribute_name=' Rough-Finish ').attribute_name==' Rough-Finish '
