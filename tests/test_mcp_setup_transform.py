"""setup transform 的真实 MCP schema/包装器；不连接 CAD。"""
import ast
import inspect
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_operation_geometry import CLSID,context,params,server
from scripts import sw_cam_mill_operation_geometry as core

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'));assert len(tree.body)==2
    server.mcp._tool_manager._tools.pop('solidworks_cam_inspect_operation_geometry',None)
    exec(compile(tree,str(SOURCE),'exec'),server.__dict__)


@pytest.fixture
def setup_fake(context,monkeypatch):
    signature=inspect.signature(core.inspect_operation_geometry)
    observation=dict(operation_native_id=10,setup_transform_complete=True,
        transform_components={'scale_raw':1.0,'rotate_raw':True,'vectors':{'translation':{'coordinates_raw':[0.0,0.0,-12.6]}}},
        origin={'coordinates_raw':[0.0,0.0,-12.6]},axis={'coordinates_raw':[0.0,0.0,1.0]},
        coordinate_frame_verified=False,generic_CL_frame_verified=False,units_verified=False)
    result=dict(status='review_required',observation_mode='setup_transform',readback_verified=True,
        observation_verified=True,guards_verified=True,setup_transform_complete=True,
        parameters_complete=False,virtual_collection_complete=False,may_continue=False,
        before={'observations':[deepcopy(observation)]},after={'observations':[deepcopy(observation)]})
    def run(*args,**kwargs):signature.bind(*args,**kwargs);return deepcopy(result)
    fn=Mock(side_effect=run)
    monkeypatch.setattr(core,'inspect_operation_geometry',fn)
    monkeypatch.setattr(core,'validate',Mock(return_value={}))
    runtime=Mock(return_value=None)
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=runtime))
    return SimpleNamespace(call=fn,result=result,runtime=runtime)


def test_setup_mode_real_schema_registered_and_exact_core_signature(context,setup_fake):
    p=params(context,observation_mode='setup_transform')
    result=json.loads(server.solidworks_cam_inspect_operation_geometry(p))
    assert result['setup_transform_complete'] is True and result['runtime_unchanged'] is True
    assert result['before']==setup_fake.result['before'] and setup_fake.call.call_count==1
    core.validate.assert_called_once_with(p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}),CLSID)
    args,kw=setup_fake.call.call_args
    assert args==(context.sw,CLSID,str(context.dll.parent/'camworks.tlb'))
    assert kw['observation_mode']=='setup_transform' and kw['targets']==p.targets
    assert kw['runtime_check'] is setup_fake.runtime
    assert all(k not in kw for k in ('addin_clsid','expected_document_title','response_format'))
    tool=server.mcp._tool_manager._tools['solidworks_cam_inspect_operation_geometry']
    assert 'setup_transform' in json.dumps(tool.parameters) and tool.annotations.readOnlyHint is True
    context.connect.assert_called_once_with(wait_seconds=1)


@pytest.mark.parametrize('field',['addin_clsid','process_id','expected_process_create_time','expected_document_path','targets'])
def test_required_actual_schema_fields_not_optional(context,setup_fake,field):
    values=params(context,observation_mode='setup_transform').model_dump();values.pop(field)
    with pytest.raises(ValueError):server.SolidWorksCamOperationGeometryInput(**values)
    setup_fake.call.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('change',[{'observation_mode':'matrix'},{'process_id':True},{'expected_process_create_time':float('inf')},
    {'setup_transform_complete':True},{'targets':[dict(operation_native_id=True,feature_native_id=30,feature_setup_native_id=40,operation_setup_native_id=50,mill_operation_type=0)]}])
def test_setup_schema_rejects_guessed_or_coerced_fields(context,setup_fake,change):
    values=dict(observation_mode='setup_transform');values.update(change)
    with pytest.raises(ValueError):params(context,**values)
    setup_fake.call.assert_not_called();context.connect.assert_not_called()


@pytest.mark.parametrize('pid',[None,True,732])
def test_setup_mode_connected_process_guard_precedes_target(context,setup_fake,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid)
    result=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context,observation_mode='setup_transform')))
    assert result['status']=='error'
    setup_fake.call.assert_not_called();core.validate.assert_not_called();context.connect.assert_not_called()


def test_setup_bad_authority_never_reaches_target(context,setup_fake,monkeypatch):
    core.validate.side_effect=ValueError('fixture rejected authority')
    target=Mock();monkeypatch.setattr(server,'_cam_target',target)
    result=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context,observation_mode='setup_transform')))
    assert result['status']=='error';target.assert_not_called();setup_fake.call.assert_not_called()


def test_setup_post_runtime_drift_preserves_both_raw_observations(context,setup_fake):
    setup_fake.runtime.side_effect=[None,ValueError('runtime changed')]
    result=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context,observation_mode='setup_transform')))
    assert result['status']=='error' and result['reason']=='RUNTIME_CHANGED_AFTER_READ'
    assert result['before']==setup_fake.result['before'] and result['after']==setup_fake.result['after']
    for key in ('setup_transform_complete','parameters_complete','virtual_collection_complete','readback_verified',
                'observation_verified','guards_verified','may_continue','runtime_unchanged'):
        assert result[key] is False
    assert setup_fake.call.call_count==1


def test_setup_pre_runtime_drift_prevents_any_core_or_target(context,setup_fake):
    setup_fake.runtime.side_effect=ValueError('runtime changed')
    result=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context,observation_mode='setup_transform')))
    assert result['status']=='error';core.validate.assert_not_called();setup_fake.call.assert_not_called();context.connect.assert_not_called()


def test_existing_mode_defaults_remain_explicit(context,setup_fake):
    assert params(context).observation_mode=='tp_geometry'
    assert params(context,observation_mode='virtual_features').observation_mode=='virtual_features'
    assert params(context,observation_mode='setup_transform').observation_mode=='setup_transform'
