import ast,json
from pathlib import Path
from enum import Enum
from typing import Optional,Literal,Any
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from scripts.sw_operation_guard import absolute_document_path
from scripts import sw_cam_mill_material as backend
from scripts import sw_cam_comtypes as bridge
D=Path(__file__).resolve().parents[1]
TREE=ast.parse((D/'mcp-server/server.py').read_text(encoding='utf-8'))
NAMES={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamEvidenceInput','SolidWorksCamMillMaterialInput'}
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in NAMES]
assert {n.name for n in NODES}==NAMES
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Optional=Optional,Literal=Literal,Any=Any,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path)
exec(compile(ast.Module(body=NODES,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),NS)
MODEL=NS['SolidWorksCamMillMaterialInput'];TOOL='solidworks_cam_configure_mill_material'
NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==TOOL)
@pytest.fixture
def probe(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'target');receipt=tmp_path/'new.json';mapping=tmp_path/'mapping.json';mapping.write_text('{}')
    data=dict(addin_clsid='{11111111-2222-3333-4444-555555555555}',process_id=731,expected_document_path=str(part),expected_source_sha256='a'*64,qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(receipt),action='prepare',expected_old_material='6061-T6',value_native='304L',material_evidence=dict(path=str(mapping),sha256='b'*64))
    core=Mock(return_value={'status':'review_required'});monkeypatch.setattr(backend,'configure_mill_material',core)
    target=Mock(return_value=(object(),dict(clsid=data['addin_clsid'],addin_path=str(tmp_path/'cam.dll'))))
    registry={}
    def tool(**kw):
        def deco(fn):registry[kw['name']]=kw;return fn
        return deco
    def locked(fn,response_format):return json.dumps(fn())
    ns=dict(NS,mcp=N(tool=tool),_selected_process_id=731,_cam_target=target,_run_locked=locked)
    exec(compile(ast.Module(body=[NODE],type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),ns)
    return N(**locals())

def test_locked_route_and_exact_mutation_annotation(probe):
    model=MODEL(**probe.data)
    assert json.loads(probe.ns[TOOL](model))==probe.core.return_value
    assert probe.core.call_args.kwargs['expected_source_sha256']=='a'*64
    assert probe.registry[TOOL]['annotations']['readOnlyHint'] is False
    assert probe.registry[TOOL]['annotations']['idempotentHint'] is False
    assert probe.registry[TOOL]['annotations']['destructiveHint'] is True
    assert MODEL.model_fields['action'].is_required()

@pytest.mark.parametrize('key,value',[('process_id',True),('process_id',0),('expected_document_path','relative.sldprt'),('expected_source_sha256','A'*64),('qualification_only',1),('acknowledge_disposable_copy',False),('message_policy','accept'),('receipt_path','relative.json'),('expected_document_title','another'),('action','apply'),('generate',True),('stock_path','C:/stock.stl'),('setup_index',0),('recognize_features',True),('expected_old_material','unknown'),('value_native','6061-T6'),('value_native',' unavailable '),('material_evidence',{'path':'relative.json','sha256':'b'*64}),('prepare_receipt_path','C:/unused.json'),('techdb_source_sha256','c'*64)])
def test_bad_or_mutating_inputs_rejected(probe,key,value):
    with pytest.raises(ValueError):MODEL(**(probe.data|{key:value}))
    probe.target.assert_not_called();probe.core.assert_not_called()

def test_wrong_pid_stops_before_target(probe):
    probe.ns['_selected_process_id']=732
    with pytest.raises(ValueError):probe.ns[TOOL](MODEL(**probe.data))
    probe.target.assert_not_called();probe.core.assert_not_called()


def test_apply_requires_complete_pinned_prepare(probe):
    credentials=dict(action='apply',expected_state_sha256='c'*64,prepare_receipt_path=str(probe.tmp_path/'prepared.json'),prepare_receipt_sha256='d'*64)
    model=MODEL(**(probe.data|credentials))
    assert model.action=='apply'
    for key in ('expected_state_sha256','prepare_receipt_path','prepare_receipt_sha256'):
        invalid=probe.data|credentials;invalid.pop(key)
        with pytest.raises(ValueError):MODEL(**invalid)
    probe.target.assert_not_called()



def test_single_setter_and_turn_backend_unchanged():
    tree=ast.parse((D/'scripts/sw_cam_mill_material.py').read_text(encoding='utf-8'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='setattr']
    assert len(calls)==1 and isinstance(calls[0].args[1],ast.Constant) and calls[0].args[1].value=='Material'
    source=(D/'scripts/sw_cam_mill_material.py').read_text(encoding='utf-8')
    for name in ('ExtractMachinableFeatures','RecognizeFeatures','GenerateOperationPlan','GenerateToolpath','Save3','SetMachine2','DefineWorkpieceFromSTL2'):
        assert name not in source
