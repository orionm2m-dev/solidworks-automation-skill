"""Strict qualification schema and mocked route; no CAD."""
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID, context, server

CHANGE=dict(name='5',expected_radial_x_native=0.,expected_axial_z_native=0.,radial_x_native=.1,axial_z_native=0.)

@pytest.fixture
def core(context,monkeypatch):
    stub=ModuleType('scripts.sw_cam_turn_variable_allowance_write')
    stub.qualify_turn_variable_allowance=Mock(return_value=dict(status='review_required',may_continue=False))
    monkeypatch.setitem(sys.modules,stub.__name__,stub)
    return stub.qualify_turn_variable_allowance

def model(context,**kw):
    values=dict(process_id=731,addin_clsid=CLSID,expected_document_path=context.document,
        setup_index=0,operation_index=3,expected_operation_type=2,expected_operation_native_id=130,
        expected_linked_feature_ids=[75],expected_source_sha256='a'*64,
        baseline_checkpoint_path=str(context.dll.parent/'baseline.sldprt'),action='prepare',changes=[dict(CHANGE)],
        expected_mode_native=0,candidate_mode_native=1,qualification_only=True,
        acknowledge_unqualified_mapping_mode_units=True,message_policy='vendor_default')
    values.update(kw)
    if values['action']=='apply':
        values.setdefault('expected_state_sha256','b'*64)
        values.setdefault('receipt_path',str(context.dll.parent/'new.json'))
    return server.SolidWorksCamVariableAllowanceQualificationInput(**values)

@pytest.mark.parametrize('action',['prepare','apply'])
def test_complete_exact_route(context,core,action):
    p=model(context,action=action)
    r=json.loads(server.solidworks_cam_qualify_turn_variable_allowance(p))
    assert r==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    t=server.mcp._tool_manager._tools['solidworks_cam_qualify_turn_variable_allowance']
    assert not t.annotations.readOnlyHint and t.annotations.destructiveHint and not t.annotations.idempotentHint

@pytest.mark.parametrize('field,value',[
 ('process_id',True),('expected_operation_native_id',0),('expected_operation_type',3),
 ('expected_linked_feature_ids',[True]),('expected_linked_feature_ids',[]),('expected_linked_feature_ids',[75,75]),
 ('expected_mode_native',True),('expected_mode_native',1.0),('candidate_mode_native',0),('candidate_mode_native',True),
 ('candidate_mode_native',2),('qualification_only',1),('qualification_only',False),
 ('acknowledge_unqualified_mapping_mode_units',1),('acknowledge_unqualified_mapping_mode_units',False),
 ('expected_source_sha256','A'*64),('expected_document_path','relative.sldprt'),
 ('baseline_checkpoint_path','relative.sldprt'),('message_policy','accept'),('action','identify')])
def test_strict_scope_before_connection(context,core,field,value):
    with pytest.raises(ValueError):model(context,**{field:value})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize('field,value',[
 ('radial_x_native',True),('radial_x_native','0.1'),('radial_x_native',Decimal('0.1')),
 ('radial_x_native',float('nan')),('radial_x_native',float('inf')),('radial_x_native',1.1),
 ('radial_x_native',-1),('expected_axial_z_native',-.1),('name',5),('name',''),('name',' '),('name','5\n')])
def test_exact_recipe_no_coercion(context,core,field,value):
    with pytest.raises(ValueError):model(context,changes=[dict(CHANGE,**{field:value})])
    core.assert_not_called()

@pytest.mark.parametrize('changes',[[],[CHANGE,CHANGE],[dict(CHANGE,name=str(i)) for i in range(3)],
 [dict(CHANGE,radial_x_native=0.)],[dict(CHANGE,expected_radial_x_native=.2)],
 [dict(CHANGE,unexpected=1)]])
def test_only_one_or_two_unique_positive_changes(context,changes):
    with pytest.raises(ValueError):model(context,changes=changes)

def test_exact_names_preserved_not_stripped(context):
    p=model(context,changes=[dict(CHANGE,name=' 5 ')])
    assert p.changes[0].name==' 5 '

def test_distinct_baseline_required(context):
    with pytest.raises(ValueError):model(context,baseline_checkpoint_path=context.document)

@pytest.mark.parametrize('field',['expected_state_sha256','receipt_path'])
def test_prepare_rejects_apply_inputs(context,field):
    value='b'*64 if field=='expected_state_sha256' else str(context.dll.parent/'new.json')
    with pytest.raises(ValueError):model(context,**{field:value})

@pytest.mark.parametrize('field',['expected_state_sha256','receipt_path'])
def test_apply_requires_both_guards(context,field):
    with pytest.raises(ValueError):model(context,action='apply',**{field:None})

def test_existing_receipt_not_replayed(context,core):
    path=context.dll.parent/'new.json';path.write_text('prior')
    with pytest.raises(ValueError):model(context,action='apply')
    assert path.read_text()=='prior';core.assert_not_called()

@pytest.mark.parametrize('failure',['pid','unbound','document','version','registration'])
def test_target_scope_before_core(context,core,monkeypatch,failure):
    p=model(context)
    if failure=='pid':monkeypatch.setattr(server,'_selected_process_id',732)
    elif failure=='unbound':monkeypatch.setattr(server,'_selected_process_id',None)
    elif failure=='document':context.model.GetPathName='C:/foreign.sldprt'
    elif failure=='version':context.sw.RevisionNumber='33.1.0'
    else:context.inventory['errors']=[{'stage':'registry'}]
    assert json.loads(server.solidworks_cam_qualify_turn_variable_allowance(p))['status']=='error'
    core.assert_not_called()
    if failure in {'pid','unbound'}:context.connect.assert_not_called()
