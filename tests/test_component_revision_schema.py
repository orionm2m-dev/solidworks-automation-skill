"""Staged MCP input schema and registration checks without server startup."""
import ast
from copy import deepcopy
from enum import Enum
import math
from pathlib import Path
from typing import Literal,Optional

from pydantic import BaseModel,ConfigDict,Field,ValidationError,field_validator,model_validator
import pytest
from scripts.sw_operation_guard import absolute_document_path
import scripts.sw_operation_guard as guard

STAGE=Path(__file__).parents[1]
SERVER=Path(guard.__file__).parents[1]/'mcp-server/server.py'
SERVER_TEXT=SERVER.read_text(encoding='utf-8-sig')
WANTED={'BaseInput','ActiveDocumentInput','SolidWorksFrozenFileInput','ResponseFormat'}
namespace=dict(globals())
selected=ast.Module(body=[n for n in ast.parse(SERVER_TEXT).body if isinstance(n,ast.ClassDef) and n.name in WANTED],type_ignores=[])
exec(compile(selected,str(SERVER),'exec'),namespace)
INTEGRATED='class SolidWorksComponentRevisionInput(' in SERVER_TEXT
if INTEGRATED:
    wanted={'SolidWorksComponentRevisionTargetInput','SolidWorksComponentRevisionMoveInput','SolidWorksComponentRevisionInput'}
    schema_ast=ast.Module(body=[n for n in ast.parse(SERVER_TEXT).body if isinstance(n,ast.ClassDef) and n.name in wanted],type_ignores=[])
    assert len(schema_ast.body)==3
    exec(compile(schema_ast,str(SERVER),'exec'),namespace)
else:
    exec(compile((STAGE/'server_schema.fragment.py').read_text(encoding='utf8'),'schema.fragment.py','exec'),namespace)
Schema=namespace['SolidWorksComponentRevisionInput']


@pytest.fixture
def values(tmp_path):
    paths={}
    for name in ('source.sldasm','copy.sldasm','screw.sldprt','prior.json'):
        path=tmp_path/name;path.write_bytes(name.encode());paths[name]=str(path)
    target=dict(name='screw0-1',reference='PCB_SCREW_0',path=paths['screw.sldprt'],sha256='a'*64,
        configuration='Default',native_id=1,matrix=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.],fixed=True)
    target['target_matrix']=target['matrix'].copy();target['target_matrix'][9]=.001
    return dict(process_id=71,expected_document_path=paths['copy.sldasm'],expected_file_sha256='b'*64,
        source_path=paths['source.sldasm'],source_sha256='c'*64,prior_copy_receipt_path=paths['prior.json'],
        prior_copy_receipt_sha256='d'*64,moves=[target],removals=[],action='prepare',qualification_only=True)


def test_valid_schema_preserves_explicit_pose(values):
    parsed=Schema.model_validate(values)
    assert parsed.moves[0].target_matrix[9]==.001 and parsed.moves[0].fixed is True
    assert set(parsed.model_dump(exclude={'expected_document_title','response_format'}))=={
        'process_id','expected_document_path','expected_file_sha256','source_path','source_sha256',
        'prior_copy_receipt_path','prior_copy_receipt_sha256','moves','removals','action','qualification_only',
        'frozen_files','expected_state_sha256','receipt_path'}


@pytest.mark.parametrize('key,value',[('process_id','71'),('qualification_only',1),('moves',[]),
    ('receipt_path','unexpected.json'),('unknown',True),('source_path','relative.sldasm')])
def test_invalid_top_level_input(values,key,value):
    with pytest.raises(ValidationError):Schema.model_validate(values|{key:value})


@pytest.mark.parametrize('field,value',[('fixed',1),('native_id',True),('target_matrix',[0]*15),
    ('target_matrix',[float('nan')]*16),('matrix',[True]*16),('name','subassembly/part'),('unknown',1)])
def test_invalid_exact_component_input(values,field,value):
    changed=deepcopy(values);changed['moves'][0][field]=value
    with pytest.raises(ValidationError):Schema.model_validate(changed)


def test_apply_requires_fresh_receipt_and_prepared_sha(values,tmp_path):
    with pytest.raises(ValidationError):Schema.model_validate(values|{'action':'apply'})
    parsed=Schema.model_validate(values|{'action':'apply','expected_state_sha256':'e'*64,'receipt_path':str(tmp_path/'new.json')})
    assert parsed.action=='apply'
    with pytest.raises(ValidationError):Schema.model_validate(values|{'action':'apply','expected_state_sha256':'e'*64,'receipt_path':values['prior_copy_receipt_path']})


def test_server_fragments_have_unique_anchors_and_compile():
    a='class SolidWorksPartTransferInput(SolidWorksNativeTransferInput):'
    b='@mcp.tool(name="solidworks_cam_document_lifecycle",'
    assert SERVER_TEXT.count(a)==SERVER_TEXT.count(b)==1
    if INTEGRATED:
        functions=[n for n in ast.parse(SERVER_TEXT).body if isinstance(n,ast.FunctionDef) and n.name=='solidworks_qualify_component_revision']
        assert len(functions)==1
        merged=SERVER_TEXT
        tree=ast.Module(body=functions,type_ignores=[])
    else:
        assert 'def solidworks_qualify_component_revision(' not in SERVER_TEXT
        merged=SERVER_TEXT.replace(a,(STAGE/'server_schema.fragment.py').read_text(encoding='utf8')+a)
        merged=merged.replace(b,(STAGE/'server_tool.fragment.py').read_text(encoding='utf8')+b)
        tree=ast.parse((STAGE/'server_tool.fragment.py').read_text(encoding='utf8'))
    compile(merged,'prospective_server.py','exec')
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
    assert any(isinstance(n.func,ast.Name) and n.func.id=='_run_locked' for n in calls)
    assert '_selected_process_id != params.process_id' in ast.unparse(tree)
