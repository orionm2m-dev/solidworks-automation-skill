"""Exact installed parent/child schemas, without server boot or application access."""
import ast
from enum import Enum
import ntpath
import os
from pathlib import Path
from typing import Literal,Optional
from pydantic import BaseModel,ConfigDict,Field,StrictInt,ValidationError,field_validator,model_validator
import pytest
from scripts import sw_cam_current_floor_wall_scalars as scalar_core
from scripts import sw_cam_current_saved_finish_wip as wip_core

CLSID='{00000000-0000-0000-0000-000000000001}'  # Synthetic shape only; never dispatched.
RUNTIME=Path(scalar_core.__file__).resolve().parents[1]
COMMON=('ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput')

def schema(name):
    source=RUNTIME/'mcp-server/server.py';definitions={n.name:n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef)}
    guard=RUNTIME/'scripts/sw_operation_guard.py'
    predicate=[n for n in ast.parse(guard.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)and n.name=='absolute_document_path']
    assert len(predicate)==1
    namespace=dict(__name__=__name__,BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,StrictInt=StrictInt,
        field_validator=field_validator,model_validator=model_validator,Enum=Enum,Literal=Literal,
        Optional=Optional,Path=Path,os=os,ntpath=ntpath)
    selected=predicate+[definitions[n]for n in COMMON+(name,)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),str(source)+':isolated_schema','exec'),namespace)
    return namespace[name]

@pytest.fixture
def common(tmp_path):
    return dict(addin_clsid=CLSID,process_id=42,expected_process_create_time=12.0,
        expected_document_path=str(tmp_path/'synthetic.sldprt'),expected_source_sha256='a'*64,
        generation_receipt_path=str(tmp_path/'generation.json'),generation_receipt_sha256='b'*64,
        receipt_path=str(tmp_path/'observation.json'),qualification_only=True,message_policy='vendor_default')

def values(kind,common,tmp_path):
    if kind=='scalar':return dict(common,floor_operation_native_id=101,wall_operation_native_id=102)
    return dict(common,project_root=str(tmp_path),output_dir=str(tmp_path/'wip-output'),module_sha256='c'*64,
        declared_empty_operation_ids=[103],acknowledge_machine_scope=True)

def klass(kind):return schema('SolidWorksCamCurrentFloorWallScalarsInput'if kind=='scalar'else'SolidWorksCamCurrentSavedFinishWipInput')

@pytest.mark.parametrize('kind',['scalar','wip'])
def test_complete_real_schema_parses_and_exports_exact_core_keys(common,tmp_path,kind):
    obj=klass(kind).model_validate(values(kind,common,tmp_path))
    assert set(obj.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))==(scalar_core.KEYS if kind=='scalar'else wip_core.KEYS)

@pytest.mark.parametrize('kind',['scalar','wip'])
def test_inherited_clsid_remains_required(common,tmp_path,kind):
    cls=klass(kind);assert cls.model_fields['addin_clsid'].is_required()
    v=values(kind,common,tmp_path);v.pop('addin_clsid')
    with pytest.raises(ValidationError)as error:cls.model_validate(v)
    assert ('addin_clsid',)in[x['loc']for x in error.value.errors()]

@pytest.mark.parametrize('kind',['scalar','wip'])
@pytest.mark.parametrize('field,bad',[('addin_clsid','not-a-guid'),('process_id',True),('expected_document_path','relative.sldprt'),('qualification_only',False),('expected_document_title','another document'),('message_policy','answer_yes'),('unknown_field',1)])
def test_real_inherited_and_scope_guards_reject(common,tmp_path,kind,field,bad):
    with pytest.raises(ValidationError):klass(kind).model_validate(dict(values(kind,common,tmp_path),**{field:bad}))

@pytest.mark.parametrize('ids',[[True],[1,1],[0],[-1]])
def test_wip_empty_ids_are_distinct_positive_integers(common,tmp_path,ids):
    v=values('wip',common,tmp_path);v['declared_empty_operation_ids']=ids
    with pytest.raises(ValidationError):klass('wip').model_validate(v)

def test_whole_machine_wip_acknowledgement_is_required(common,tmp_path):
    v=values('wip',common,tmp_path);v['acknowledge_machine_scope']=False
    with pytest.raises(ValidationError):klass('wip').model_validate(v)

def test_scalar_target_ids_are_strict(common,tmp_path):
    v=values('scalar',common,tmp_path);v['floor_operation_native_id']='101'
    with pytest.raises(ValidationError):klass('scalar').model_validate(v)
