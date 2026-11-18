"""Portable MCP schema tests with a synthetic part fixture, no CAD activation."""
import ast,enum,hashlib,importlib.util,os,sys,typing
from pathlib import Path
import pytest
from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator,ValidationError
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT));sys.path.insert(0,str(RUNTIME))
import scripts
spec=importlib.util.spec_from_file_location('scripts.sw_cam_inprocess_records',ROOT/'scripts/sw_cam_inprocess_records.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)

def models():
    ns=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,StrictInt=StrictInt,model_validator=model_validator,Optional=typing.Optional,Literal=typing.Literal,Enum=enum.Enum)
    tree=ast.parse((RUNTIME/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    for name in ('ResponseFormat','BaseInput','SolidWorksCamInprocessReaderInput'):
        node=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'existing_schema','exec'),ns)
    snippet=ROOT/'SERVER_REGISTRATION_SNIPPET.py';scope=ast.parse(snippet.read_text()) if snippet.exists() else tree
    for name in ('SolidWorksCamTurnRecordSelectionInput','SolidWorksCamTurnOwnerRecordsInput'):
        node=next(x for x in scope.body if isinstance(x,ast.ClassDef) and x.name==name)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'record_schema','exec'),ns)
    return ns['SolidWorksCamTurnOwnerRecordsInput']

@pytest.fixture
def params(tmp_path):
    source=tmp_path/'fixture.sldprt';source.write_bytes(b'synthetic only')
    return dict(process_id=123,expected_process_creation_time=1234.25,expected_document_path=str(source),expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),host_dll_path=str(tmp_path/'host.dll'),host_dll_sha256='a'*64,host_tlb_path=str(tmp_path/'host.tlb'),host_tlb_sha256='b'*64,expected_host_module_version_id='12345678-1234-1234-1234-123456789abc',max_operations=16,max_tools=16,receipt_path=str(tmp_path/'out.json'),reference_receipt_path=None,reference_receipt_sha256=None,nc_operation_ids=[],record_read=dict(operation_native_id=501,feature_native_id=301,operation_type=7,setup_index=0,operation_index=0,expected_operation_count=16,expected_setup_count=2,expected_record_count=40),cam_typelib_path=str(tmp_path/'cam.tlb'),cam_typelib_sha256='c'*64,qualification_only=True,message_policy='vendor_default')

def test_generic_request(params):assert models().model_validate(params).record_read.operation_native_id==501

@pytest.mark.parametrize('value',[7.0,'7',True])
def test_strict_operation_type(params,value):
    params['record_read']['operation_type']=value
    with pytest.raises(ValidationError):models().model_validate(params)

def test_nested_unknown_rejected(params):
    params['record_read']['write']=True
    with pytest.raises(ValidationError):models().model_validate(params)

def test_no_old_nc_request(params):
    params['nc_operation_ids']=[501]
    with pytest.raises(ValidationError):models().model_validate(params)

def test_outer_unknown_rejected(params):
    params['invoke']='Save3'
    with pytest.raises(ValidationError):models().model_validate(params)
