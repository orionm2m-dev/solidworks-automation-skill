"""Explicit circular lifecycle schema and existing locked dispatcher."""
import json
from pathlib import Path
import pytest
from test_mcp_cam_mill_feature_lifecycle import feature_params,context,core,server

def args(context):
    receipt=context.dll.parent/'created.json';receipt.write_text('{}')
    return dict(feature_kind='circular_pocket',expected_source_sha256='a'*64,
                circle_creation_receipt_path=str(receipt),circle_creation_receipt_sha256='b'*64)

@pytest.mark.parametrize('action',['prepare','save','close'])
def test_circle_lifecycle_exact_route(context,core,action):
    fields=args(context)
    p=feature_params(context,action,**fields)
    server.solidworks_cam_document_lifecycle(p)
    for k,v in fields.items():assert core.call_args.kwargs[k]==v
    assert core.call_args.kwargs['machine_kind']=='mill_single_feature_qualification'

@pytest.mark.parametrize('missing',['expected_source_sha256','circle_creation_receipt_path','circle_creation_receipt_sha256'])
def test_circle_requires_all_evidence(context,core,missing):
    fields=args(context);fields.pop(missing)
    with pytest.raises(ValueError):feature_params(context,**fields)
    core.assert_not_called()

@pytest.mark.parametrize('scope',['turn','mill_qualification'])
def test_other_scopes_reject_explicit_circle_options(context,core,scope):
    with pytest.raises(ValueError):feature_params(context,machine_kind=scope,**args(context))
    core.assert_not_called()

@pytest.mark.parametrize('field,value',[('expected_source_sha256','BAD'),('circle_creation_receipt_sha256',True),
    ('circle_creation_receipt_path','relative.json'),('feature_kind','hole')])
def test_bad_circle_evidence(context,core,field,value):
    fields=args(context);fields[field]=value
    with pytest.raises(ValueError):feature_params(context,**fields)
    core.assert_not_called()

def test_open_default_rejects_circle_evidence(context,core):
    fields=args(context);fields.pop('feature_kind')
    with pytest.raises(ValueError):feature_params(context,**fields)
    core.assert_not_called()

def test_default_route_omits_new_fields(context,core):
    server.solidworks_cam_document_lifecycle(feature_params(context))
    assert not {'feature_kind','expected_source_sha256','circle_creation_receipt_path','circle_creation_receipt_sha256'} & core.call_args.kwargs.keys()
