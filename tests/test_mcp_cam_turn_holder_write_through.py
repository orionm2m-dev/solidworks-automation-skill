"""Public copy-only holder probe schema/routing; no native application calls."""
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server
from scripts import sw_cam_turn_holder_dimensions as cam


def params(context,tmp_path,**changes):
    source=tmp_path/'copy_source.sldprt';source.write_bytes(b'copy source')
    original=tmp_path/'original.sldprt';original.write_bytes(b'protected original')
    sha=cam._file_hash(source)
    values=dict(addin_clsid=CLSID,process_id=731,expected_process_create_time=1234.,expected_document_path=context.document,
        expected_source_sha256=sha,copy_source_path=str(source),copy_source_sha256=sha,
        setup_index=0,operation_index=7,expected_operation_type=6,expected_operation_native_id=329,
        expected_tool_native_id=330,expected_holder_id=4,
        protected_part_pins=[dict(path=str(source),sha256=sha),dict(path=str(original),sha256=cam._file_hash(original))],
        expected_shank_length_native=250.,shank_length_native=200.,qualification_only=True,message_policy='vendor_default')
    values.update(changes)
    return server.SolidWorksCamTurnHolderWriteThroughInput(**values)


@pytest.fixture
def native(context,monkeypatch):
    result=Mock(return_value={'status':'prepared'})
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_turn_holder_dimensions',N(qualify_turn_holder_write_through=result,validate=cam.validate))
    monkeypatch.setattr(server,'_runtime_identity',N(assert_current=Mock()))
    return result


def test_registered_distinct_route_keeps_exact_args_and_lock(context,native,tmp_path):
    p=params(context,tmp_path);tool=server.mcp._tool_manager._tools['solidworks_cam_qualify_turn_holder_write_through']
    assert tool.annotations.destructiveHint and not tool.annotations.idempotentHint and not tool.annotations.readOnlyHint
    assert json.loads(server.solidworks_cam_qualify_turn_holder_write_through(p))==native.return_value
    native.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize('selection',[None,True,999])
def test_process_mismatch_does_not_connect(context,native,tmp_path,monkeypatch,selection):
    monkeypatch.setattr(server,'_selected_process_id',selection)
    assert json.loads(server.solidworks_cam_qualify_turn_holder_write_through(params(context,tmp_path)))['status']=='error'
    native.assert_not_called();context.connect.assert_not_called()


def test_runtime_change_does_not_connect(context,native,tmp_path):
    server._runtime_identity.assert_current.side_effect=ValueError('changed runtime')
    assert json.loads(server.solidworks_cam_qualify_turn_holder_write_through(params(context,tmp_path)))['status']=='error'
    native.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('field,value',[
    ('action','probe'),('action','apply'),('action','retry'),('process_id',True),('expected_process_create_time',True),
    ('expected_process_create_time',float('inf')),('expected_operation_type',7),('expected_tool_native_id',True),
    ('expected_document_path','relative.sldprt'),('protected_part_pins',[]),('qualification_only',1),
    ('shank_length_native',True),('shank_length_native',0),('shank_length_native',250.),
    ('shank_length_native',float('nan')),('shank_length_native','200'),('expected_shank_length_native',True),
    ('copy_source_path','relative.sldprt'),('copy_source_sha256','b'*64),('expected_state_sha256','b'*64),
    ('receipt_path','C:/unused.json'),('values_native',{'BoringBarDiameter':25.}),('Save',True),('retry',True)])
def test_invalid_public_recipe_never_enters_core(context,native,tmp_path,field,value):
    with pytest.raises(ValueError):params(context,tmp_path,**{field:value})
    native.assert_not_called();context.connect.assert_not_called()


def test_probe_requires_complete_exact_selected_reference(context,native,tmp_path):
    kw=dict(action='probe',expected_state_sha256='b'*64,receipt_path=str(tmp_path/'receipt.json'),
        allowed_affected_operations=[dict(setup_index=0,operation_index=7,expected_operation_type=6)])
    p=params(context,tmp_path,**kw)
    assert p.shank_length_native==200.
    kw['allowed_affected_operations']=[dict(setup_index=0,operation_index=6,expected_operation_type=5)]
    with pytest.raises(ValueError):params(context,tmp_path,**kw)
    kw['allowed_affected_operations']=[dict(setup_index=0,operation_index=7,expected_operation_type=6)]*2
    with pytest.raises(ValueError):params(context,tmp_path,**kw)


def test_copy_source_must_be_distinct_and_protected(context,native,tmp_path):
    p=params(context,tmp_path).model_dump()
    p['copy_source_path']=context.document
    with pytest.raises(ValueError):server.SolidWorksCamTurnHolderWriteThroughInput(**p)
    p=params(context,tmp_path).model_dump();p['protected_part_pins']=p['protected_part_pins'][1:]
    with pytest.raises(ValueError):server.SolidWorksCamTurnHolderWriteThroughInput(**p)


def test_old_route_has_no_identity_override_or_probe_action(context,tmp_path):
    from test_mcp_cam_turn_holder_dimensions import params as ordinary
    with pytest.raises(ValueError):ordinary(context,tmp_path,action='probe')
    with pytest.raises(ValueError):ordinary(context,tmp_path,probe_identity=True)
