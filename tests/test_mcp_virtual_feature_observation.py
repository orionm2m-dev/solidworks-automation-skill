import json
import pytest
from test_mcp_operation_geometry import server,params,fake,context

def test_actual_schema_wrapper_forwards_explicit_virtual_mode(context,fake):
    p=params(context,observation_mode='virtual_features');r=json.loads(server.solidworks_cam_inspect_operation_geometry(p))
    assert r['readback_verified'] and fake.call_args.kwargs['observation_mode']=='virtual_features'
    assert params(context).observation_mode=='tp_geometry'

@pytest.mark.parametrize('value',['unknown',None,1,True])
def test_actual_schema_rejects_unknown_observation(context,fake,value):
    with pytest.raises(ValueError):params(context,observation_mode=value)
    fake.assert_not_called()

def test_virtual_mode_rejects_nonanchor_and_multiple(context,fake):
    row=dict(operation_native_id=11,feature_native_id=31,feature_setup_native_id=41,operation_setup_native_id=51,mill_operation_type=0)
    with pytest.raises(ValueError):params(context,observation_mode='virtual_features',targets=[row])
    first=params(context).targets[0]
    with pytest.raises(ValueError):params(context,observation_mode='virtual_features',targets=[first,row])
    fake.assert_not_called()


def test_post_runtime_drift_revokes_virtual_completeness_preserving_payload(context,fake,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    fake.side_effect=None
    fake.return_value=dict(status='review_required',virtual_collection_complete=True,readback_verified=True,before={'members':'kept'},after={'members':'kept'})
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(side_effect=[None,ValueError('changed')])))
    r=json.loads(server.solidworks_cam_inspect_operation_geometry(params(context,observation_mode='virtual_features')))
    assert r['status']=='error' and not r['virtual_collection_complete'] and not r['readback_verified']
    assert r['before']==r['after']=={'members':'kept'} and fake.call_count==1
