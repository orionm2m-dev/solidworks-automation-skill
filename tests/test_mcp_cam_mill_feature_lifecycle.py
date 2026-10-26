"""Single-feature MILL lifecycle schema/routes; all native operations mocked."""
from test_mcp_cam_mill_lifecycle import *

def feature_params(context,action='prepare',**changes):
    return params(context,action,**(dict(machine_kind='mill_single_feature_qualification',process_id=731,
        acknowledge_qualification_copy=True,expected_feature_native_id=55,expected_operation_native_ids=[77])|changes))

@pytest.mark.parametrize('action',['prepare','save','close'])
def test_feature_exact_route(context,core,action):
    p=feature_params(context,action);out=json.loads(server.solidworks_cam_document_lifecycle(p))
    assert out==core.return_value
    assert core.call_args.kwargs['machine_kind']=='mill_single_feature_qualification'
    assert core.call_args.kwargs['process_id']==731
    assert core.call_args.kwargs['expected_feature_native_id']==55
    assert core.call_args.kwargs['expected_operation_native_ids']==[77]

@pytest.mark.parametrize('bad',[None,True,0,-1,3.5,'55'])
def test_feature_schema_strict_feature_id(context,core,bad):
    with pytest.raises(ValueError):feature_params(context,expected_feature_native_id=bad)
    core.assert_not_called()

@pytest.mark.parametrize('bad',[None,(77,),[True],[0],[-1],[77,77],list(range(1,34)),['77'],[77.0]])
def test_feature_schema_strict_operation_ids(context,core,bad):
    with pytest.raises(ValueError):feature_params(context,expected_operation_native_ids=bad)
    core.assert_not_called()

@pytest.mark.parametrize('missing',['expected_feature_native_id','expected_operation_native_ids','process_id','acknowledge_qualification_copy'])
def test_feature_schema_all_identity_fields_required(context,core,missing):
    data=dict(addin_clsid=CLSID,expected_document_path=context.document,action='prepare',message_policy='vendor_default',
        machine_kind='mill_single_feature_qualification',process_id=731,acknowledge_qualification_copy=True,
        expected_feature_native_id=55,expected_operation_native_ids=[])
    del data[missing]
    with pytest.raises(ValueError):server.SolidWorksCamDocumentLifecycleInput(**data)
    core.assert_not_called()

@pytest.mark.parametrize('oldscope',['turn','mill_qualification'])
@pytest.mark.parametrize('field',['expected_feature_native_id','expected_operation_native_ids'])
def test_old_scopes_reject_even_explicit_null_selectors(context,core,oldscope,field):
    call=params if oldscope=='turn' else mill_params
    with pytest.raises(ValueError):call(context,**{field:None})
    core.assert_not_called()

@pytest.mark.parametrize('pinned',[None,999])
def test_feature_route_pid_guard_precedes_target(context,core,monkeypatch,pinned):
    monkeypatch.setattr(server,'_selected_process_id',pinned)
    target=Mock(side_effect=AssertionError('must not acquire target'))
    monkeypatch.setattr(server,'_cam_target',target)
    assert json.loads(server.solidworks_cam_document_lifecycle(feature_params(context)))['status']=='error'
    target.assert_not_called();core.assert_not_called()


def test_zero_and_32_ordered_ids_allowed(context):
    assert feature_params(context,expected_operation_native_ids=[]).expected_operation_native_ids==[]
    ids=list(range(32,0,-1));assert feature_params(context,expected_operation_native_ids=ids).expected_operation_native_ids==ids
