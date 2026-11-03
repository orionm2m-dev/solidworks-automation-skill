"""Read-only reconcile wrapper uses normal selected-process routing and locked execution."""
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server


@pytest.fixture
def core(context,monkeypatch):
    native=Mock(return_value={'status':'review_required','read_only':True})
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_turn_recipe_reconcile',N(reconcile_turn_feature_recipe=native))
    monkeypatch.setattr(server,'_runtime_identity',N(assert_current=Mock()))
    return native


def params(context,**changes):
    return server.SolidWorksCamTurnRecipeReconcileInput(**(dict(addin_clsid=CLSID,process_id=731,
        expected_process_create_time=1234.,expected_document_path=context.document,expected_source_sha256='a'*64,
        parent_receipt_path=str(context.dll.parent/'completed.json'),parent_receipt_sha256='b'*64,
        expected_after_state_sha256='c'*64,expected_operation_order=[127,135,400,401,402,403],
        receipt_path=str(context.dll.parent/'reconcile.json'),acknowledge_append_definitions_only=True)|changes))


def test_readonly_registration_and_exact_routing(context,core):
    tool=server.mcp._tool_manager._tools['solidworks_cam_reconcile_turn_feature_recipe']
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    p=params(context);assert json.loads(server.solidworks_cam_reconcile_turn_feature_recipe(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize('selection',[None,True,555])
def test_wrong_selection_stops_before_connect(context,core,monkeypatch,selection):
    monkeypatch.setattr(server,'_selected_process_id',selection)
    assert json.loads(server.solidworks_cam_reconcile_turn_feature_recipe(params(context)))['status']=='error'
    core.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('field,value',[('process_id',True),('expected_operation_order',[True]),
    ('expected_operation_order',[127,127]),('parent_receipt_path','relative.json'),
    ('parent_receipt_sha256','bad'),('action','apply'),('GOP',True)])
def test_bad_schema_never_connects(context,core,field,value):
    with pytest.raises(ValueError):params(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()
