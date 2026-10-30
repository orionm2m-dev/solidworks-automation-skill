"""Real runtime schema/route AST, offline namespace: no MCP server or CAD startup."""
import ast,json,importlib.util,sys
from pathlib import Path
from enum import Enum
from typing import Optional,Literal,Any
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from scripts.sw_operation_guard import absolute_document_path
ROOT=Path(__file__).resolve().parents[1]
STAGED=ROOT/'scripts/sw_cam_mill_rough_boundary.py'
if (ROOT/"server_proposed.py").exists():
    spec=importlib.util.spec_from_file_location("scripts.sw_cam_mill_rough_boundary",STAGED)
    backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
    sys.modules["scripts.sw_cam_mill_rough_boundary"]=backend
    SOURCE=(ROOT/"server_proposed.py").read_text(encoding="utf-8-sig")
else:
    from scripts import sw_cam_mill_rough_boundary as backend
    SOURCE=(ROOT/"mcp-server/server.py").read_text(encoding="utf-8-sig")
TREE=ast.parse(SOURCE)
NAMES={'ResponseFormat','BaseInput',"SolidWorksCamSelectedFeatureContextInput",'ActiveDocumentInput','SolidWorksCamTargetInput','SolidWorksCamMaterialCatalogueInput','SolidWorksCamMillOperationLevelsInput','SolidWorksCamMillRoughBoundaryInput'}
NODES=[n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name in NAMES]
assert {n.name for n in NODES}==NAMES
NS=dict(BaseModel=BaseModel,ConfigDict=ConfigDict,Field=Field,field_validator=field_validator,
    model_validator=model_validator,Optional=Optional,Literal=Literal,Any=Any,Enum=Enum,Path=Path,
    absolute_document_path=absolute_document_path)
exec(compile(ast.Module(body=NODES,type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),NS)
MODEL=NS['SolidWorksCamMillRoughBoundaryInput']
TOOL='solidworks_cam_inspect_mill_rough_boundary'
NODE=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==TOOL)

@pytest.fixture
def probe(tmp_path,monkeypatch):
    document=tmp_path/'actual.sldprt';document.write_bytes(b'fixture')
    output=tmp_path/'exclusive'/'machine.cl';receipt=tmp_path/'receipt.json'
    core=Mock(return_value=dict(status='review_required',geometry_verified=False))
    monkeypatch.setattr(backend,'inspect_mill_rough_boundary',core)
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
    exec(compile(ast.Module(body=[NODE],type_ignores=[]),str(Path(__file__).resolve().parents[1] / 'mcp-server/server.py'),'exec'),ns)
    def params(**changes):
        values=dict(process_id=731,addin_clsid=registration['clsid'],expected_document_path=str(document),
            expected_feature_native_id=211,expected_operation_native_id=214,expected_mill_operation_type=0,
            expected_toolpath_record_counts=[68],expected_ungenerated_operation_ids=[215],
            acknowledge_disposable_copy=True,receipt_path=str(receipt),
            expected_source_sha256='ab'*32,qualification_only=True)
        return MODEL(**(values|changes))
    return N(**locals())

def test_route_all_guards_to_exact_backend(probe):
    request=probe.params()
    result=json.loads(probe.ns[TOOL](request));assert result==probe.core.return_value
    probe.core.assert_called_once_with(probe.sw,probe.registration['clsid'],
        typelib_path=str(Path(probe.registration['addin_path']).parent/'camworks.tlb'),
        **request.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert probe.calls==[NS['ResponseFormat'].JSON]
    ann=probe.registry[TOOL]['annotations']
    assert ann['readOnlyHint'] is True
    assert not any(ann[k] for k in ['destructiveHint','idempotentHint','openWorldHint'])

@pytest.mark.parametrize('value',[None,732])
def test_pid_mismatch_stops_before_target_or_core(probe,value):
    probe.ns['_selected_process_id']=value
    assert json.loads(probe.ns[TOOL](probe.params()))['status']=='error'
    probe.core.assert_not_called();probe.target.assert_not_called()

@pytest.mark.parametrize('field,value',[
 ('process_id',True),('expected_feature_native_id',0),('expected_operation_native_id',214.),
 ('expected_mill_operation_type',False),('expected_toolpath_record_counts',[True]),
 ('expected_toolpath_record_counts',[0]),('expected_toolpath_record_counts',(68,)),
 ('expected_ungenerated_operation_ids',[214]),('expected_ungenerated_operation_ids',[215,215]),
 ('expected_ungenerated_operation_ids',[False]),('expected_ungenerated_operation_ids',(215,)),
 ('expected_source_sha256','X'*64),('expected_document_path','relative.sldprt'),
 ('expected_document_title','unused'),('qualification_only',1),('qualification_only',False),
 ('acknowledge_disposable_copy',False),('message_policy','accept'),('action','retry'),
 ('expected_mill_operation_type',1),('expected_mill_operation_type',0.0)])
def test_schema_rejects_coercion_and_scope_changes(probe,field,value):
    with pytest.raises(ValueError):probe.params(**{field:value})
    probe.core.assert_not_called();probe.target.assert_not_called()

@pytest.mark.parametrize('field',['controller_name','setup_index','operation_index','generate','save','send','typelib_path'])
def test_no_hidden_mutation_or_coordinate_assumption_inputs(probe,field):
    with pytest.raises(ValueError):probe.params(**{field:1})


def test_existing_receipt_is_rejected_without_native_access(probe):
    probe.receipt.write_text("prior evidence")
    with pytest.raises(ValueError):probe.params()
    probe.target.assert_not_called()
    probe.core.assert_not_called()
    assert probe.receipt.read_text() == "prior evidence"


def test_bridge_adds_only_the_documented_rough_interface():
    staged = ROOT / "sw_cam_comtypes.proposed.py"
    source = staged if staged.exists() else ROOT / "scripts/sw_cam_comtypes.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_INTERFACES" for t in n.targets))
    interfaces = ast.literal_eval(node.value)
    assert interfaces["ICWRghMillOp"] == "{4EDDCA80-325A-11D6-A9A7-00062999E55F}"
