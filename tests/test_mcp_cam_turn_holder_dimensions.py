"""Public holder schema and selected-process routing without native calls."""
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server
from scripts import sw_cam_turn_holder_dimensions as cam


def params(context,tmp_path,**changes):
    source=tmp_path/'original.sldprt';source.write_bytes(b'source')
    values=dict(addin_clsid=CLSID,process_id=731,expected_process_create_time=1234.,expected_document_path=context.document,
        expected_source_sha256='a'*64,setup_index=0,operation_index=7,expected_operation_type=6,
        expected_operation_native_id=329,expected_tool_native_id=330,expected_holder_id=4,
        protected_part_pins=[dict(path=str(source),sha256=cam._file_hash(source))],values_native={'ShankLength':200.},
        qualification_only=True,message_policy='vendor_default')
    values.update(changes)
    return server.SolidWorksCamTurnHolderDimensionsInput(**values)


@pytest.fixture
def native(context,monkeypatch):
    result=Mock(return_value={'status':'prepared'})
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_turn_holder_dimensions',N(configure_turn_holder_dimensions=result,validate=cam.validate))
    monkeypatch.setattr(server,'_runtime_identity',N(assert_current=Mock()))
    return result


def test_real_public_route(context,native,tmp_path):
    p=params(context,tmp_path);tool=server.mcp._tool_manager._tools['solidworks_cam_configure_turn_holder_dimensions']
    assert tool.annotations.destructiveHint and not tool.annotations.idempotentHint
    assert json.loads(server.solidworks_cam_configure_turn_holder_dimensions(p))==native.return_value
    native.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize('selection',[None,True,999])
def test_wrong_selected_process_never_connects(context,native,tmp_path,monkeypatch,selection):
    monkeypatch.setattr(server,'_selected_process_id',selection)
    assert json.loads(server.solidworks_cam_configure_turn_holder_dimensions(params(context,tmp_path)))['status']=='error'
    native.assert_not_called();context.connect.assert_not_called()


def test_runtime_change_never_connects(context,native,tmp_path):
    server._runtime_identity.assert_current.side_effect=ValueError('changed')
    assert json.loads(server.solidworks_cam_configure_turn_holder_dimensions(params(context,tmp_path)))['status']=='error'
    native.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('field,value',[
    ('action','apply'),('action','retry'),('process_id',True),('expected_process_create_time',True),
    ('expected_process_create_time',float('inf')),('expected_operation_type',7),('expected_tool_native_id',True),
    ('expected_document_path','relative.sldprt'),('protected_part_pins',[]),('qualification_only',1),
    ('values_native',{'BoringBarDiameter':True}),('values_native',{'BoringBarDiameter':0}),
    ('values_native',{'ShankLength':-1}),('values_native',{'LeadAngle':float('nan')}),
    ('values_native',{'IncludedAngle':55}),('values_native',{'NoseRadius':.2}),('values_native',{'SetTool':1}),
    ('values_native',{'ShankLength':'200'}),('expected_state_sha256','b'*64),('receipt_path','C:/out.json'),('Save',True)])
def test_bad_public_inputs_stop_before_target(context,native,tmp_path,field,value):
    with pytest.raises(ValueError):params(context,tmp_path,**{field:value})
    native.assert_not_called();context.connect.assert_not_called()


def test_apply_requires_selected_exact_reference(context,native,tmp_path):
    kw=dict(action='apply',expected_state_sha256='b'*64,receipt_path=str(tmp_path/'receipt.json'),
        allowed_affected_operations=[dict(setup_index=0,operation_index=7,expected_operation_type=6)])
    p=params(context,tmp_path,**kw)
    assert p.values_native=={'ShankLength':200.}
    kw['allowed_affected_operations']=[dict(setup_index=0,operation_index=6,expected_operation_type=5)]
    with pytest.raises(ValueError):params(context,tmp_path,**kw)
