"""Portable schema and actual public metadata checks; no application activation."""
import ast,enum,importlib,os,sys,typing
from pathlib import Path
import pytest
from pydantic import BaseModel,Field,ConfigDict,field_validator,model_validator
STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
if str(STAGE/'scripts')not in scripts.__path__:scripts.__path__.insert(0,str(STAGE/'scripts'))
core=importlib.import_module('scripts.sw_cam_autodetected_pocket_recovery')
from scripts.sw_operation_guard import absolute_document_path

def schema():
    server=ast.parse((RUNTIME/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    fragment=STAGE/'server.fragment.py'
    declared=ast.parse(fragment.read_text(encoding='utf-8'))if fragment.is_file()else server
    names=['ResponseFormat','BaseInput','ActiveDocumentInput','SolidWorksCamTargetInput']
    nodes=[next(x for x in server.body if isinstance(x,ast.ClassDef)and x.name==n)for n in names]
    nodes.append(next(x for x in declared.body if isinstance(x,ast.ClassDef)and x.name=='SolidWorksCamPocketRecoveryInput'))
    ns=dict(vars(typing),Enum=enum.Enum,BaseModel=BaseModel,Field=Field,ConfigDict=ConfigDict,field_validator=field_validator,model_validator=model_validator,absolute_document_path=absolute_document_path)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'schema-only','exec'),ns)
    return ns['SolidWorksCamPocketRecoveryInput']

def values(tmp_path):
    return dict(process_id=123,expected_process_create_time=111.5,expected_document_path=str(tmp_path/'copy.sldprt'),expected_source_sha256='a'*64,
        expected_sw_configuration='CAD',expected_cam_configuration='CAM',creator_receipt_path=str(tmp_path/'creator.json'),creator_receipt_sha256='b'*64,
        expected_feature_native_id=456,expected_attribute_suffix=[dict(name='Observed attribute',type='Attribute')],receipt_path=str(tmp_path/'read.json'),
        qualification_only=True,message_policy='vendor_default',addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}')

def test_real_inherited_schema_accepts_generic_exact_request(tmp_path):
    model=schema()(**values(tmp_path));assert model.process_id==123 and model.expected_feature_native_id==456

@pytest.mark.parametrize('patch',[{'process_id':123.0},{'expected_feature_native_id':True},{'unexpected':True},
    {'expected_attribute_suffix':[dict(name='x',type='Attribute',unexpected='x')]}, {'expected_attribute_suffix':[dict(name=123,type='Attribute')]},
    {'qualification_only':False}, {'expected_document_title':'copy.sldprt'}])
def test_schema_rejects_coercion_and_unreviewed_scope(tmp_path,patch):
    v=values(tmp_path);v.update(patch)
    with pytest.raises(ValueError):schema()(**v)

def test_actual_public_abi_before_application():
    path=os.environ.get('SWMCP_CAM_TYPELIB_PATH')
    if not path:pytest.skip('Set SWMCP_CAM_TYPELIB_PATH to the installed public CAM typelib')
    result=core.creator.preflight(path)
    assert result['application_calls']==0 and result['method']=='CreateMillFeature2'
