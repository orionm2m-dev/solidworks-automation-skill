"""Existing-circle verification schema and exact locked route; no native application."""
from copy import deepcopy
import json
import pytest
from test_mcp_cam_apt_sketch import inputs,invoke,cores,context,SPEC,server

def verify_params(context,**changes):
    prior=context.dll.parent/'created.json'
    if not prior.exists():prior.write_text('{}')
    spec=deepcopy(SPEC)
    spec['profile']=dict(kind='circle',center_model_mm=[1,1,2],radius_mm=.5)
    values=dict(spec=spec,expected_source_sha256='a'*64,creation_receipt_path=str(prior),
                creation_receipt_sha256='b'*64,receipt_path=str(context.dll.parent/'verify.json'))
    return inputs(context,'sketch','verify_existing',**(values|changes))

def test_exact_existing_verify_route(context,cores):
    p=verify_params(context)
    assert json.loads(invoke('sketch',p))['status']=='ok'
    cores.sketch.assert_called_once_with(context.sw,expected_process_id=731,expected_document_path=context.document,
        action='verify_existing',spec=p.spec,expected_state_sha256=None,receipt_path=p.receipt_path,
        qualification_only=True,expected_source_sha256='a'*64,
        creation_receipt_path=p.creation_receipt_path,creation_receipt_sha256='b'*64)
    context.discover.assert_not_called()
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]

@pytest.mark.parametrize('key',['expected_source_sha256','creation_receipt_path','creation_receipt_sha256','receipt_path'])
def test_verify_requires_bound_evidence(context,cores,key):
    with pytest.raises(ValueError):verify_params(context,**{key:None})
    cores.sketch.assert_not_called()

@pytest.mark.parametrize('key,value',[('expected_state_sha256','c'*64),('creation_receipt_path','relative.json'),
    ('creation_receipt_path','C:/absent_creator.json'),('creation_receipt_sha256','bad'),
    ('creation_receipt_sha256',True),('expected_source_sha256',True),('receipt_path','relative.json'),
    ('spec',SPEC),('save',True),('process_id',True),('qualification_only',False)])
def test_verify_scope_strict(context,cores,key,value):
    with pytest.raises(ValueError):verify_params(context,**{key:value})
    cores.sketch.assert_not_called()

@pytest.mark.parametrize('action',['inspect','prepare','apply'])
@pytest.mark.parametrize('key',['expected_source_sha256','creation_receipt_path','creation_receipt_sha256'])
@pytest.mark.parametrize('value',[None,'forbidden'])
def test_old_actions_reject_explicit_new_fields(context,cores,action,key,value):
    with pytest.raises(ValueError):inputs(context,'sketch',action,**{key:value})
    cores.sketch.assert_not_called()

def test_verify_never_overwrites_existing_receipt(context,cores):
    path=context.dll.parent/'verify.json';path.write_text('unchanged')
    with pytest.raises(ValueError):verify_params(context)
    assert path.read_text()=='unchanged'
    cores.sketch.assert_not_called()

@pytest.mark.parametrize('change',['pid','path','type'])
def test_verify_target_guard_precedes_backend(context,cores,monkeypatch,change):
    p=verify_params(context)
    if change=='pid':monkeypatch.setattr(server,'_selected_process_id',732)
    if change=='path':context.model.GetPathName=str(context.dll.parent/'other.sldprt')
    if change=='type':context.model.GetType=2
    assert json.loads(invoke('sketch',p))['status']=='error'
    cores.sketch.assert_not_called()
    if change=='pid':context.connect.assert_not_called()

@pytest.mark.parametrize('action',['inspect','prepare','apply'])
def test_existing_route_has_identical_arguments(context,cores,action):
    p=inputs(context,'sketch',action)
    invoke('sketch',p)
    assert not {'expected_source_sha256','creation_receipt_path','creation_receipt_sha256'} & cores.sketch.call_args.kwargs.keys()
