import ast,json
from pathlib import Path
from enum import Enum
from typing import Optional,Literal,Any
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from scripts.sw_operation_guard import absolute_document_path
from scripts import sw_cam_mill_profile_indexed as backend
from scripts import sw_cam_comtypes as bridge
D=Path(__file__).resolve().parents[1]
TREE=ast.parse((D/'mcp-server/server.py').read_text(encoding='utf-8'))
NAMES={'ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamMillProfileIndexedInput','SolidWorksCamProfileIndexMappingInput'}
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in NAMES]
assert {n.name for n in NODES}==NAMES
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,model_validator=model_validator,Optional=Optional,Literal=Literal,Any=Any,Enum=Enum,Path=Path,absolute_document_path=absolute_document_path)
exec(compile(ast.Module(body=NODES,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),NS)
MODEL=NS['SolidWorksCamMillProfileIndexedInput'];TOOL='solidworks_cam_inspect_mill_profile_indexed'
NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==TOOL)
@pytest.fixture
def probe(tmp_path,monkeypatch):
    part=tmp_path/'part.sldprt';part.write_bytes(b'target');receipt=tmp_path/'new.json'
    headers=tmp_path/'headers.json';headers.write_text('{}')
    data=dict(addin_clsid='{11111111-2222-3333-4444-555555555555}',process_id=731,expected_document_path=str(part),expected_source_sha256='a'*64,qualification_only=True,acknowledge_disposable_copy=True,receipt_path=str(receipt),expected_feature_native_id=79,expected_owner_setup_native_id=69,expected_volume_type=2,expected_shape=2,expected_island_count=5,profile_headers_receipt_path=str(headers),profile_headers_receipt_sha256='b'*64,index_mapping=[dict(native_index=0,expected_sketch_name='Face0')])
    core=Mock(return_value={'status':'review_required'});monkeypatch.setattr(backend,'inspect_mill_profile_indexed',core)
    target=Mock(return_value=(object(),dict(clsid=data['addin_clsid'],addin_path=str(tmp_path/'cam.dll'))))
    registry={}
    def tool(**kw):
        def deco(fn):registry[kw['name']]=kw;return fn
        return deco
    def locked(fn,response_format):return json.dumps(fn())
    ns=dict(NS,mcp=N(tool=tool),_selected_process_id=731,_cam_target=target,_run_locked=locked)
    exec(compile(ast.Module(body=[NODE],type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),ns)
    return N(**locals())

def test_locked_route_and_exact_read_only_annotation(probe):
    model=MODEL(**probe.data)
    assert json.loads(probe.ns[TOOL](model))==probe.core.return_value
    assert probe.core.call_args.kwargs['expected_source_sha256']=='a'*64
    assert probe.registry[TOOL]['annotations']['readOnlyHint'] is True
    assert probe.registry[TOOL]['annotations']['idempotentHint'] is False
    assert 'action' not in MODEL.model_fields

@pytest.mark.parametrize('key,value',[('process_id',True),('process_id',0),('expected_document_path','relative.sldprt'),('expected_source_sha256','A'*64),('qualification_only',1),('acknowledge_disposable_copy',False),('message_policy','accept'),('receipt_path','relative.json'),('expected_document_title','another'),('action','apply'),('generate',True),('stock_path','C:/stock.stl'),('expected_feature_native_id',True),('expected_owner_setup_native_id',0),('expected_volume_type',True),('expected_shape',True),('expected_island_count',65),('index_mapping',[dict(native_index=True,expected_sketch_name='Face0')]),('expected_feature_native_id',4294967296)])
def test_bad_or_mutating_inputs_rejected(probe,key,value):
    with pytest.raises(ValueError):MODEL(**(probe.data|{key:value}))
    probe.target.assert_not_called();probe.core.assert_not_called()

def test_wrong_pid_stops_before_target(probe):
    probe.ns['_selected_process_id']=732
    with pytest.raises(ValueError):probe.ns[TOOL](MODEL(**probe.data))
    probe.target.assert_not_called();probe.core.assert_not_called()

@pytest.mark.parametrize('name,iid',[
    ('ICWProfileFeature','{7532C720-3BC4-11D6-A9AF-00062999E55F}')])
def test_exact_tool_interface_iid(monkeypatch,name,iid):
    assert bridge._INTERFACES[name]==iid
    klass=N(_iid_=iid)
    monkeypatch.setattr(bridge,'_load_type_library',lambda _:N(**{name:klass}))
    assert bridge._interface_class(name,'tlb') is klass
    klass._iid_='{00000000-0000-0000-0000-000000000000}'
    with pytest.raises(ValueError):bridge._interface_class(name,'tlb')




def test_explicit_mapping_is_forwarded_without_reindexing(probe):
    data=probe.data|{'index_mapping':[dict(native_index=1,expected_sketch_name='Face0')]}
    probe.ns[TOOL](MODEL(**data))
    assert probe.core.call_args.kwargs['index_mapping']==data['index_mapping']


@pytest.mark.parametrize('mapping',[
 [],[dict(native_index=-1,expected_sketch_name='Face0')],
 [dict(native_index=65,expected_sketch_name='Face0')],
 [dict(native_index=0,expected_sketch_name='')],
 [dict(native_index=0,expected_sketch_name='Face0',fallback=True)],
 [dict(native_index=0,expected_sketch_name='Face0')]*2,
 [dict(native_index=0,expected_sketch_name='Face0'),dict(native_index=1,expected_sketch_name='Face0')],
 [dict(native_index=0,expected_sketch_name=5)]])
def test_bad_or_ambiguous_mappings_stop_before_dispatch(probe,mapping):
    with pytest.raises(ValueError):MODEL(**(probe.data|{'index_mapping':mapping}))
    probe.target.assert_not_called()
    probe.core.assert_not_called()
