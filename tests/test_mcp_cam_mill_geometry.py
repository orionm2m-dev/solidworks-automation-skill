"""Staged MILL geometry export schema/route; all native paths replaced with mocks."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server

@pytest.fixture
def core(context,monkeypatch):
    value=Mock(return_value={'status':'review_required','may_continue':False})
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_mill_geometry',SimpleNamespace(export_mill_feature_geometry=value))
    return value

def params(context,action='inspect',**changes):
    data=dict(addin_clsid=CLSID,process_id=731,expected_document_path=context.document,
        expected_source_sha256='b'*64,expected_feature_native_id=111,
        expected_operation_native_ids=[114,115],expected_generated_operation_native_ids=[],
        export_kind='target',output_dir=str(context.dll.parent/'fresh_export'),action=action,
        qualification_only=True,acknowledge_document_wide_export=True,message_policy='vendor_default')
    if action=='apply':data.update(expected_state_sha256='a'*64,receipt_path=str(context.dll.parent/'export_receipt.json'))
    return server.SolidWorksCamMillFeatureGeometryInput(**(data|changes))

@pytest.mark.parametrize('action',['inspect','prepare','apply'])
@pytest.mark.parametrize('kind',['target','stock','wip'])
def test_exact_native_kwargs_and_no_unrequested_actions(context,core,action,kind):
    p=params(context,action,export_kind=kind,expected_generated_operation_native_ids=[114] if kind=='wip' else [])
    assert json.loads(server.solidworks_cam_export_mill_feature_geometry(p))==core.return_value
    core.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/'camworks.tlb'),
        **p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'}))
    assert context.runners==[{'format':server.ResponseFormat.JSON,'automation':True}]
    assert not Path(p.output_dir).exists()
    if p.receipt_path:assert not Path(p.receipt_path).exists()

@pytest.mark.parametrize('field',['process_id','expected_feature_native_id'])
@pytest.mark.parametrize('bad',[True,False,0,-1,1.0,'1',None,4294967296])
def test_strict_identity(context,core,field,bad):
    with pytest.raises(ValueError):params(context,**{field:bad})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize('field',['expected_operation_native_ids','expected_generated_operation_native_ids'])
@pytest.mark.parametrize('bad',[None,(114,),[True],[False],[0],[-1],[114.0],['114'],[114,114],list(range(1,34)),[4294967296]])
def test_strict_bounded_ordered_ids(context,core,field,bad):
    with pytest.raises(ValueError):params(context,**{field:bad})
    core.assert_not_called()

@pytest.mark.parametrize('ops,generated',[([114,115],[115,114]),([114],[115]),([],[114])])
def test_generated_must_be_exact_ordered_subset(context,core,ops,generated):
    with pytest.raises(ValueError):params(context,expected_operation_native_ids=ops,expected_generated_operation_native_ids=generated)
    core.assert_not_called()


def test_wip_requires_generated_operation(context,core):
    with pytest.raises(ValueError):params(context,export_kind='wip')
    core.assert_not_called()

@pytest.mark.parametrize('kind',['target','stock'])
def test_empty_operation_lists_allowed_for_non_wip(context,kind):
    p=params(context,export_kind=kind,expected_operation_native_ids=[],expected_generated_operation_native_ids=[])
    assert p.expected_operation_native_ids==[]

@pytest.mark.parametrize('field,bad',[
    ('qualification_only',False),('qualification_only',1),('qualification_only','true'),
    ('acknowledge_document_wide_export',False),('acknowledge_document_wide_export',1),
    ('expected_source_sha256','wrong'),('expected_source_sha256','A'*64),('expected_source_sha256',None),
    ('expected_document_path','relative.SLDPRT'),('expected_document_path','C:/file.txt'),
    ('expected_document_title','unsaved'),('message_policy','accept'),('action','retry'),
    ('export_kind','target,stock'),('export_kind',['target']),('save',True),('simulation',True),
    ('GTP',True),('typelib_path','foreign.tlb')])
def test_rejects_extra_or_unapproved_scope(context,core,field,bad):
    with pytest.raises(ValueError):params(context,**{field:bad})
    core.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize('action',['inspect','prepare'])
@pytest.mark.parametrize('field,value',[('expected_state_sha256','a'*64),('receipt_path','C:/new.json')])
def test_read_actions_reject_mutation_inputs(context,core,action,field,value):
    with pytest.raises(ValueError):params(context,action,**{field:value})
    core.assert_not_called()

@pytest.mark.parametrize('field,value',[('expected_state_sha256',None),('expected_state_sha256','bad'),
    ('receipt_path',None),('receipt_path','relative.json'),('receipt_path','C:/wrong.txt')])
def test_apply_requires_fresh_receipt_and_state(context,core,field,value):
    with pytest.raises(ValueError):params(context,'apply',**{field:value})
    core.assert_not_called()


def test_receipt_exists_is_rejected_and_preserved(context,core):
    p=context.dll.parent/'prior.json';p.write_text('retain')
    with pytest.raises(ValueError):params(context,'apply',receipt_path=str(p))
    assert p.read_text()=='retain';core.assert_not_called()

@pytest.mark.parametrize('action',['inspect','prepare','apply'])
@pytest.mark.parametrize('case',['relative','existing','missing_parent','UNC','canonical_UNC'])
def test_export_directory_is_new_local_all_actions(context,core,monkeypatch,action,case):
    value=str(context.dll.parent/'fresh_export')
    if case=='relative':value='relative_export'
    elif case=='existing':value=str(context.dll.parent)
    elif case=='missing_parent':value=str(context.dll.parent/'missing'/'fresh_export')
    elif case=='UNC':value=r'\\server\share\fresh_export'
    else:
        original=server.Path.resolve
        def mapped(path,*args,**kwargs):
            if path.name=='fresh_export':return server.Path(r'\\server\share\fresh_export')
            return original(path,*args,**kwargs)
        monkeypatch.setattr(server.Path,'resolve',mapped)
    with pytest.raises(ValueError):params(context,action,output_dir=value)
    core.assert_not_called()

@pytest.mark.parametrize('failure',['unbound','wrong_pid','wrong_document','wrong_version','unknown_registration'])
def test_existing_target_guards_stop_before_core(context,core,monkeypatch,failure):
    changes={}
    if failure=='unbound':monkeypatch.setattr(server,'_selected_process_id',None)
    elif failure=='wrong_pid':changes['process_id']=732
    elif failure=='wrong_document':context.model.GetPathName=str(context.dll.parent/'foreign.sldprt')
    elif failure=='wrong_version':context.sw.RevisionNumber='33.1.0'
    else:changes['addin_clsid']='{00000000-0000-0000-0000-000000000002}'
    result=json.loads(server.solidworks_cam_export_mill_feature_geometry(params(context,**changes)))
    assert result['status']=='error';core.assert_not_called()
    if failure in ('unbound','wrong_pid'):context.connect.assert_not_called()


def test_registered_schema_and_mutability_contract():
    tool=server.mcp._tool_manager._tools['solidworks_cam_export_mill_feature_geometry']
    assert tool.annotations.readOnlyHint is False and tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False
    schema=tool.parameters
    text=json.dumps(schema)
    for key in ['expected_generated_operation_native_ids','export_kind','process_id','expected_source_sha256','output_dir']:
        assert key in text
    assert 'additionalProperties' in text
