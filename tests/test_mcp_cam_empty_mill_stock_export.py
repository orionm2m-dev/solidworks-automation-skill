import ast,json
from pathlib import Path
from enum import Enum
from typing import Optional,Literal,Any
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from scripts.sw_operation_guard import absolute_document_path
from scripts import sw_cam_empty_mill_stock_export as backend
from scripts import sw_cam_comtypes as bridge
D=Path(__file__).resolve().parents[1]
TREE=ast.parse((D/'mcp-server/server.py').read_text(encoding='utf-8'))
NAMES={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamEvidenceInput','SolidWorksCamEmptyMillStockExportInput'}
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in NAMES]
assert {n.name for n in NODES}==NAMES
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Optional=Optional,Literal=Literal,Any=Any,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path)
exec(compile(ast.Module(body=NODES,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),NS)
MODEL=NS['SolidWorksCamEmptyMillStockExportInput'];TOOL='solidworks_cam_export_empty_mill_stock'
NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==TOOL)
@pytest.fixture
def probe(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'target');receipt=tmp_path/'new.json';stock=tmp_path/'stock.stl';stock.write_bytes(b'input')
    data=dict(addin_clsid='{11111111-2222-3333-4444-555555555555}',process_id=731,expected_document_path=str(part),expected_source_sha256='a'*64,qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(receipt),action='prepare',expected_stock_path=str(stock),expected_stock_sha256=backend._file_hash(stock),expected_stock_bounds_native=[0.,0.,0.,1.,1.,1.],output_dir=str(tmp_path/'export'),acknowledge_document_wide_export=True)
    core=Mock(return_value={'status':'review_required'});monkeypatch.setattr(backend,'export_empty_mill_stock',core)
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
    assert probe.registry[TOOL]['annotations']['destructiveHint'] is False
    assert MODEL.model_fields['action'].is_required()

@pytest.mark.parametrize('key,value',[('process_id',True),('process_id',0),('expected_document_path','relative.sldprt'),('expected_source_sha256','A'*64),('qualification_only',1),('acknowledge_disposable_copy',False),('acknowledge_document_wide_export',1),('message_policy','accept'),('receipt_path','relative.json'),('expected_document_title','another'),('action','apply'),('generate',True),('setup_index',0),('recognize_features',True),('expected_stock_bounds_native',[0,0,0,0,0,0]),('expected_stock_bounds_native',[False,0,0,1,1,1]),('expected_stock_path','relative.stl'),('prepare_receipt_path','C:/unused.json'),('techdb_source_sha256','c'*64)])
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



def test_only_one_export_expression_and_no_mutating_CAM_methods():
    source=(D/'scripts/sw_cam_empty_mill_stock_export.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_member' and len(n.args)>1 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='CreateSTLOfStock']
    assert len(calls)==1 and [n.value for n in calls[0].args[3:]]==['',0]
    for name in ('ExtractMachinableFeatures','RecognizeFeatures','GenerateOperationPlan','GenerateToolpath','Save3','SetMachine2','DefineWorkpieceFromSTL2','setattr('):
        assert name not in source
