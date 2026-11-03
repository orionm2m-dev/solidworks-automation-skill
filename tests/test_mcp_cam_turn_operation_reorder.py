"""Strict public schema and exact selected-process routing; no CAD connection."""
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server
from scripts import sw_cam_turn_operation_reorder as cam


def params(context,tmp_path,**changes):
    source=tmp_path/'source.sldprt';db=tmp_path/'db.cwdb';source.write_bytes(b'source');db.write_bytes(b'db')
    values=dict(addin_clsid=CLSID,process_id=731,expected_process_create_time=1234.,expected_document_path=context.document,
        expected_source_sha256=cam._file_hash(source),feature_setup_index=0,expected_feature_native_id=76,expected_turn_feature_type=2,
        attribute_name='Rough-Finish',expected_metadata_sha256='a'*64,
        policy=dict(protected_part_pins=[dict(path=str(source),sha256=cam._file_hash(source))],techdb_path=str(db),techdb_sha256=cam._file_hash(db),
            expected_default_operations=[dict(operation_type=5,name='Default',native_id=3)]),
        plan=dict(setup_index=0,expected_operation_ids=[1,2,3],expected_final_order=[1,3,2],
            moves=[dict(moving_native_id=3,after_native_id=1,make_copy=False)]))
    values.update(changes)
    return server.SolidWorksCamTurnOperationReorderInput(**values)


@pytest.fixture
def native(context,monkeypatch):
    result=Mock(return_value=dict(status='prepared'))
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_turn_operation_reorder',N(reorder_turn_operations=result,validate=cam.validate))
    monkeypatch.setattr(server,'_runtime_identity',N(assert_current=Mock()))
    return result


def test_registered_wrapper_passes_exact_arguments_under_lock(context,native,tmp_path):
    tool=server.mcp._tool_manager._tools['solidworks_cam_reorder_turn_operations']
    assert tool.annotations.destructiveHint and not tool.annotations.idempotentHint
    p=params(context,tmp_path)
    assert json.loads(server.solidworks_cam_reorder_turn_operations(p))==native.return_value
    native.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize('selection',[None,True,123])
def test_selected_process_mismatch_rejected_before_connect(context,native,tmp_path,monkeypatch,selection):
    monkeypatch.setattr(server,'_selected_process_id',selection)
    assert json.loads(server.solidworks_cam_reorder_turn_operations(params(context,tmp_path)))['status']=='error'
    native.assert_not_called();context.connect.assert_not_called()


def test_runtime_identity_stops_before_connection(context,native,tmp_path):
    server._runtime_identity.assert_current.side_effect=ValueError('runtime changed')
    assert json.loads(server.solidworks_cam_reorder_turn_operations(params(context,tmp_path)))['status']=='error'
    native.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('field,value',[('action','retry'),('action','apply'),('action','inspect'),('expected_metadata_sha256',None),
    ('process_id',True),('process_id',731.),('expected_process_create_time',True),('expected_process_create_time',float('nan')),
    ('expected_state_sha256','a'*64),('receipt_path','relative.json'),('receipt_path','C:/evidence/unused.json'),('plan',{}),('policy',{}),
    ('max_operations',65),('attribute_name',None),('allow_dirty',True),('save',True)])
def test_invalid_requests_fail_before_tool(context,native,tmp_path,field,value):
    with pytest.raises(ValueError):params(context,tmp_path,**{field:value})
    native.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('change',['copy','bool_id','wrong_final','noop','extra'])
def test_nested_plan_is_strict(context,native,tmp_path,change):
    p=params(context,tmp_path).model_dump();plan=p['plan']
    if change=='copy':plan['moves'][0]['make_copy']=1
    elif change=='bool_id':plan['moves'][0]['moving_native_id']=True
    elif change=='wrong_final':plan['expected_final_order']=[3,1,2]
    elif change=='noop':plan['moves'][0]['after_native_id']=2
    elif change=='extra':plan['moves'][0]['retry']=True
    with pytest.raises(ValueError):server.SolidWorksCamTurnOperationReorderInput(**p)


def test_inspect_has_no_prepared_authority_or_receipt_input(context,native,tmp_path):
    p=params(context,tmp_path,action='inspect',expected_metadata_sha256=None)
    assert json.loads(server.solidworks_cam_reorder_turn_operations(p))==native.return_value
    assert native.call_args.kwargs['expected_metadata_sha256']is None and native.call_args.kwargs['action']=='inspect'
    with pytest.raises(ValueError):params(context,tmp_path,action='inspect',expected_metadata_sha256=None,receipt_path='C:/evidence/file.json')
