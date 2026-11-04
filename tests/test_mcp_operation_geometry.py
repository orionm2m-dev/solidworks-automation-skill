import ast,json,inspect
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace
import pytest
from test_mcp_cam_operation_diagnostics import CLSID,context,server
from scripts import sw_cam_mill_operation_geometry as core

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'));assert len(tree.body)==2
    server.mcp._tool_manager._tools.pop('solidworks_cam_inspect_operation_geometry',None)
    exec(compile(tree,str(SOURCE),'exec'),server.__dict__)

@pytest.fixture
def fake(context,monkeypatch):
    monkeypatch.setattr(core,'validate',Mock(return_value={}))
    signature=inspect.signature(core.inspect_operation_geometry)
    result=dict(status='review_required',readback_verified=True,observation_verified=True,guards_verified=True,parameters_complete=True,before={'raw':'kept'},after={'raw':'kept'})
    def run(*args,**kw):signature.bind(*args,**kw);return dict(result)
    fn=Mock(side_effect=run);monkeypatch.setattr(core,'inspect_operation_geometry',fn)
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(return_value=None)))
    return fn

def params(context,**kw):
    values=dict(addin_clsid=CLSID,process_id=731,expected_process_create_time=100.25,expected_document_path=context.document,
        expected_source_sha256='a'*64,configuration_receipt_path='authority.json',configuration_receipt_sha256='b'*64,
        anchor_operation_native_id=10,targets=[dict(operation_native_id=10,feature_native_id=30,feature_setup_native_id=40,operation_setup_native_id=50,mill_operation_type=0)])
    values.update(kw);return server.SolidWorksCamOperationGeometryInput(**values)


def test_actual_required_pydantic_and_wrapper_signature_forwarding(context,fake):
    p=params(context);result=json.loads(server.solidworks_cam_inspect_operation_geometry(p))
    assert result['readback_verified'] and result['runtime_unchanged'] and fake.call_count==1
    core.validate.assert_called_once_with(p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}),CLSID)
    args,kw=fake.call_args;assert args[1]==CLSID and callable(kw['runtime_check']) and kw['targets']==p.targets
    registered=server.mcp._tool_manager._tools['solidworks_cam_inspect_operation_geometry'];assert 'targets' in json.dumps(registered.parameters)
    missing=p.model_dump();missing.pop('addin_clsid')
    with pytest.raises(ValueError):server.SolidWorksCamOperationGeometryInput(**missing)

@pytest.mark.parametrize('change',[{'process_id':True},{'expected_process_create_time':float('nan')},{'expected_document_path':'relative.sldprt'},
    {'qualification_only':False},{'qualification_only':1},{'unknown':True},{'targets':[]},{'targets':[{'operation_native_id':10}]},
    {'targets':[dict(operation_native_id='10',feature_native_id=30,feature_setup_native_id=40,operation_setup_native_id=50,mill_operation_type=0)]}])
def test_actual_schema_rejects_unbounded_or_coerced_input(context,fake,change):
    with pytest.raises(ValueError):params(context,**change)
    fake.assert_not_called()

@pytest.mark.parametrize('pid',[None,True,732])
def test_process_selection_before_target_or_core(context,fake,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid);r=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context)))
    assert r['status']=='error';fake.assert_not_called();core.validate.assert_not_called()


def test_post_runtime_drift_preserves_both_observations(context,fake,monkeypatch):
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(side_effect=[None,ValueError('changed')])))
    r=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context)))
    assert r['status']=='error' and r['before']=={'raw':'kept'} and r['after']=={'raw':'kept'}
    assert not r['readback_verified'] and not r['runtime_unchanged'] and not r['parameters_complete'] and fake.call_count==1


def test_bad_authority_precedes_cam_target(context,fake,monkeypatch):
    core.validate.side_effect=ValueError('invalid authority');target=Mock();monkeypatch.setattr(server,'_cam_target',target)
    r=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context)))
    assert r['status']=='error';target.assert_not_called();fake.assert_not_called()
