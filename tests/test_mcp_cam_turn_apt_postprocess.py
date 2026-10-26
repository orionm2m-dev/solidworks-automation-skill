"""Real runtime schema/route AST, offline namespace: no MCP server or CAD startup."""
import ast,json
from pathlib import Path
from enum import Enum
from typing import Optional,Literal,Any
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from scripts.sw_operation_guard import absolute_document_path
from scripts import sw_cam_turn_apt_postprocess as backend
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'mcp-server/server.py').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
NAMES={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamTurnAptPostprocessInput'}
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in NAMES]
assert {n.name for n in NODES}==NAMES
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
    model_validator=model_validator,Optional=Optional,Literal=Literal,Any=Any,Enum=Enum,Path=Path,
    absolute_document_path=absolute_document_path)
exec(compile(ast.Module(body=NODES,type_ignores=[]),'<real runtime schemas>','exec'),NS)
MODEL=NS['SolidWorksCamTurnAptPostprocessInput']
TOOL='solidworks_cam_qualify_turn_apt_postprocess'
NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==TOOL)

@pytest.fixture
def probe(tmp_path,monkeypatch):
    document=tmp_path/'actual.sldprt';document.write_bytes(b'fixture')
    output=tmp_path/'exclusive'/'operation.apt';receipt=tmp_path/'receipt.json'
    core=Mock(return_value=dict(status='review_required',geometry_verified=False))
    monkeypatch.setattr(backend,'qualify_turn_apt_postprocess',core)
    registry={};sw=object();registration=dict(clsid='{00000000-0000-0000-0000-000000000001}',addin_path=str(tmp_path/'cam.dll'))
    target=Mock(return_value=(sw,registration));calls=[]
    def tool(**kw):
        def deco(fn):registry[kw['name']]=kw;return fn
        return deco
    def locked(fn,response_format):
        calls.append(response_format)
        try:return json.dumps(fn())
        except Exception as exc:return json.dumps(dict(status='error',message=str(exc)))
    ns=dict(NS,mcp=N(tool=tool),_selected_process_id=731,_cam_target=target,_run_locked=locked)
    exec(compile(ast.Module(body=[NODE],type_ignores=[]),'<real runtime wrapper>','exec'),ns)
    def params(**changes):
        values=dict(process_id=731,addin_clsid=registration['clsid'],expected_document_path=str(document),
            setup_index=0,operation_index=3,expected_operation_type=2,expected_operation_native_id=130,
            expected_linked_feature_ids=[75],expected_controller_name='turn',expected_record_count=43,
            expected_source_sha256='ab'*32,action='inspect',qualification_only=True)
        return MODEL(**(values|changes))
    return N(**locals())

@pytest.mark.parametrize('kind',[1,2])
def test_route_all_guards_to_exact_backend(probe,kind):
    request=probe.params(expected_operation_type=kind)
    result=json.loads(probe.ns[TOOL](request));assert result==probe.core.return_value
    probe.core.assert_called_once_with(probe.sw,probe.registration['clsid'],
        typelib_path=str(Path(probe.registration['addin_path']).parent/'camworks.tlb'),
        **request.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert probe.calls==[NS['ResponseFormat'].JSON]
    ann=probe.registry[TOOL]['annotations']
    assert not any(ann[k] for k in ['readOnlyHint','destructiveHint','idempotentHint','openWorldHint'])

@pytest.mark.parametrize('value',[None,732])
def test_pid_mismatch_stops_before_target_or_core(probe,value):
    probe.ns['_selected_process_id']=value
    assert json.loads(probe.ns[TOOL](probe.params()))['status']=='error'
    probe.core.assert_not_called();probe.target.assert_not_called()

@pytest.mark.parametrize('field,value',[
    ('process_id',True),('setup_index',1.0),('operation_index',512),('expected_operation_type',True),
    ('expected_operation_type',1.0),('expected_operation_type',12),('expected_operation_native_id',0),
    ('expected_record_count',True),('expected_record_count',0),('expected_source_sha256','X'*64),
    ('expected_document_path','relative.sldprt'),('qualification_only',1),('qualification_only',False),
    ('message_policy','accept'),('expected_linked_feature_ids',[]),('expected_linked_feature_ids',[True]),
    ('expected_linked_feature_ids',[1.0]),('expected_linked_feature_ids',[75,75]),('expected_linked_feature_ids',[0]),
    ('expected_linked_feature_ids',[2**32]),('expected_linked_feature_ids',(75,)),
    ('expected_controller_name',''),('expected_controller_name',' turn'),('expected_controller_name','turn '),
    ('expected_controller_name','turn\x00'),('action','retry')])
def test_schema_rejects_coercion_and_scope_changes(probe,field,value):
    with pytest.raises(ValueError):probe.params(**{field:value})
    probe.core.assert_not_called();probe.target.assert_not_called()

@pytest.mark.parametrize('field',['controller_path','include_tool','units','radial_x','generate','save','send','typelib_path'])
def test_no_hidden_mutation_or_coordinate_assumption_inputs(probe,field):
    with pytest.raises(ValueError):probe.params(**{field:1})

@pytest.mark.parametrize('action',['prepare','apply'])
def test_valid_output_evidence_contract(probe,action):
    extra=dict(action=action,output_path=str(probe.output))
    if action=='apply':extra.update(expected_state_sha256='cd'*32,receipt_path=str(probe.receipt))
    assert probe.params(**extra).action==action
    assert not probe.output.parent.exists() and not probe.receipt.exists()

@pytest.mark.parametrize('change',['inspect_output','prepare_receipt','prepare_hash','apply_missing_receipt',
    'apply_missing_hash','existing_output_dir','nc_extension','existing_receipt'])
def test_one_use_path_and_action_guards(probe,change):
    extra=dict(action='apply',output_path=str(probe.output),expected_state_sha256='cd'*32,receipt_path=str(probe.receipt))
    if change=='inspect_output':extra=dict(output_path=str(probe.output))
    elif change=='prepare_receipt':extra.update(action='prepare',expected_state_sha256=None)
    elif change=='prepare_hash':extra.update(action='prepare',receipt_path=None)
    elif change=='apply_missing_receipt':extra['receipt_path']=None
    elif change=='apply_missing_hash':extra['expected_state_sha256']=None
    elif change=='existing_output_dir':probe.output.parent.mkdir()
    elif change=='nc_extension':extra['output_path']=str(probe.output.with_suffix('.nc'))
    elif change=='existing_receipt':probe.receipt.write_text('preserve')
    with pytest.raises(ValueError):probe.params(**extra)
    probe.core.assert_not_called();probe.target.assert_not_called()
