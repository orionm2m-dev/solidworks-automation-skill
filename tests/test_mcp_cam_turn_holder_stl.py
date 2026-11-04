import ast,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from test_sw_cam_turn_holder_stl import graph
from scripts import sw_cam_turn_holder_stl as cam
SOURCE=Path(__file__).parents[1]/'mcp-server/server.py'
NAMES={'SolidWorksCamTurnHolderSTLInput','solidworks_cam_qualify_turn_holder_stl'}
TREE=ast.Module(body=[n for n in ast.parse(SOURCE.read_text(encoding='utf-8-sig')).body if getattr(n,'name',None) in NAMES],type_ignores=[])
TRANSPORT={'addin_clsid','expected_document_title','response_format'}

def request(graph,context,**changes):
    values=graph.defaults|dict(addin_clsid=CLSID,expected_document_path=context.document)|changes
    return server.SolidWorksCamTurnHolderSTLInput(**values)

@pytest.fixture
def native(context,monkeypatch):
    call=Mock(return_value=dict(status='prepared',mutation_attempted=False,apply_eligible=True))
    monkeypatch.setattr(cam,'qualify_turn_holder_stl',call)
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock()))
    return call

def test_exactly_two_ast_nodes_and_explicit_mutating_tool(context):
    assert len(TREE.body)==2 and isinstance(TREE.body[0],ast.ClassDef) and isinstance(TREE.body[1],ast.FunctionDef)
    tool=server.mcp._tool_manager._tools['solidworks_cam_qualify_turn_holder_stl']
    assert tool.annotations.destructiveHint and not tool.annotations.readOnlyHint and not tool.annotations.idempotentHint
    assert not tool.annotations.openWorldHint

@pytest.mark.parametrize('action',['prepare','apply'])
def test_routing_preserves_pins_and_recipe_under_lock(graph,context,native,action):
    extra={} if action=='prepare' else dict(expected_state_sha256='ab'*32,receipt_path=str(graph.receipt))
    params=request(graph,context,action=action,**extra)
    result=json.loads(server.solidworks_cam_qualify_turn_holder_stl(params))
    assert result==native.return_value
    native.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),**params.model_dump(exclude=TRANSPORT))
    assert context.runners==[dict(format=server.ResponseFormat.JSON,automation=True)]
    assert server._runtime_identity.assert_current.call_count==2

@pytest.mark.parametrize('field,value',[('holder_file_unit_raw',2.),('holder_file_unit_raw',True),('expected_holder_shape_raw',False),('expected_holder_orientation_raw',4),('process_id',True),('expected_process_create_time',True),('setup_index',False),('operation_index','0'),('expected_operation_type',5),('expected_tool_native_id',0),('qualification_only',1),('affected_operations',[{}]),('holder_stl_sha256','BAD'),('holder_stl_path','relative.stl'),('expected_document_path','relative.sldprt'),('expected_state_sha256','ab'*32),('save',True),('generate_toolpath',True),('retry',True),('insert_file','new.cwtt')])
def test_strict_schema_no_unrequested_parameters(graph,context,native,field,value):
    with pytest.raises(ValueError):request(graph,context,**{field:value})
    native.assert_not_called();context.connect.assert_not_called()

def test_affected_native_ids_are_not_coerced(graph,context,native):
    refs=graph.defaults['affected_operations'];refs[0]['operation_native_id']=True
    with pytest.raises(ValueError):request(graph,context,affected_operations=refs)
    native.assert_not_called()

def test_wrong_connected_pid_blocks_core(graph,context,native,monkeypatch):
    monkeypatch.setattr(server,'_selected_process_id',999)
    result=json.loads(server.solidworks_cam_qualify_turn_holder_stl(request(graph,context)))
    assert result['status']=='error';native.assert_not_called()

@pytest.mark.parametrize('attempted',[False,True])
def test_post_runtime_drift_retains_native_evidence_and_updates_owned_receipt(graph,context,native,attempted):
    params=request(graph,context,action='apply',expected_state_sha256='ab'*32,receipt_path=str(graph.receipt))
    outcome=dict(status='review_required',mutation_attempted=attempted,readback_verified=True,apply_eligible=False,
        receipt_created=True,receipt_path=str(graph.receipt),setters=[dict(method='SetTurnHolderSTLFile',returned=True)],native_calls_returned_count=1)
    graph.receipt.write_text(json.dumps(outcome));native.return_value=outcome
    server._runtime_identity.assert_current.side_effect=[None,RuntimeError('runtime drift')]
    result=json.loads(server.solidworks_cam_qualify_turn_holder_stl(params))
    assert result['status']==('uncertain' if attempted else 'error') and not result['readback_verified'] and not result['apply_eligible']
    assert result['setters']==outcome['setters'] and result['native_calls_returned_count']==1
    assert result['runtime_drift_receipt_updated'] and json.loads(graph.receipt.read_text())==result

def test_runtime_drift_does_not_overwrite_unowned_receipt(graph,context,native):
    params=request(graph,context,action='apply',expected_state_sha256='ab'*32,receipt_path=str(graph.receipt))
    native.return_value=dict(status='error',mutation_attempted=False,receipt_created=False)
    graph.receipt.write_text('unowned')
    server._runtime_identity.assert_current.side_effect=[None,RuntimeError('runtime drift')]
    result=json.loads(server.solidworks_cam_qualify_turn_holder_stl(params))
    assert not result['runtime_drift_receipt_updated'] and graph.receipt.read_text()=='unowned'
