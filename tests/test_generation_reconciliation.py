"""Synthetic saved-generation recovery tests using committed public fakes.

These cases do not load project receipts or establish native qualification.
"""
from pathlib import Path
from copy import deepcopy
import json,sys
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
R=add_runtime()
sys.path.insert(0,str(R/'scripts'))
c=required_module('generation_saved_reconciliation')
q=required_module('saved_generation_engagement')
p=required_module('sw_cam_local_generation')
generation_fixture=required_test_module('test_local_generation')

@pytest.fixture(scope='session')
def evidence(tmp_path_factory):
    """Construct one synthetic complete21/12 Save followed by a parser-cap stop."""
    work=tmp_path_factory.mktemp('synthetic_generation')
    with pytest.MonkeyPatch.context() as patch:
        backend,journal,loaded=generation_fixture.workflow(work,patch)
        r=p.run_once(backend,journal,loaded)
    assert r['readback_verified']is True and r['model_saved']is True
    oldcounts=[760,191,74,29,31196,2284,4500,104,4500,104,17118,368,17118,368]
    newcounts=[40232,464,38756,464]
    def set_counts(snapshot,new):
        generated=[o for o in snapshot['binding']['operations'][:17]if o['toolpath_generated']is True]
        assert len(generated)==14
        for row,n in zip(generated,oldcounts):row['toolpath_record_counts']=[n]
        if new:
            for row,n in zip(snapshot['binding']['operations'][17:],newcounts):row.update(toolpath_generated=True,toolpath_record_counts=[n])
    for key in ['before','configured']:set_counts(r[key],False)
    for key in ['generated','saved']:set_counts(r[key],True)
    set_counts(loaded['guide_parameters']['expected_parameters'],False)
    loaded['configuration_generation']['snapshot']=deepcopy(r['before'])
    r['completed_gtp_counts']={str(t['operation_native_id']):[n]for t,n in zip(r['learned_targets'],newcounts)}
    for t,n in zip(r['learned_targets'],newcounts):r['actions']['GTP:'+str(t['operation_native_id'])]['observed']['record_counts']=[n]
    r['generation_verification']=p.engine.verify_generation(r['configured'],r['generated'],r['learned_targets'],{int(k):v for k,v in r['completed_gtp_counts'].items()},r['feed_policy'])
    for key in ['saved_cl','saved_cl_verification','saved_checkpoint','terminal_verification']:r.pop(key,None)
    r.update(status='uncertain',phase='finished',failed_phase='SaveActiveDocument',issue=deepcopy(c.ISSUE),readback_verified=False,continuation_ready=False)
    r['phase_proof_checks']=r['phase_proof_checks'][:2]
    r['save_stage'].update(before=deepcopy(r['generated']),after=deepcopy(r['saved']))
    r['current_document']=deepcopy(r['source_transition']['document'])
    path=str(work/'saved.cl');r['request']=dict(process_id=123,saved_cl_path=path)
    read_batch=dict(read_scope_complete=True,active=False,invalid=False)
    r['captures']=[dict(label=label,read_batch=deepcopy(read_batch),**deepcopy(r[key]))for label,key in [('saved_configuration_before_gtp','before'),('generated_four','generated'),('saved_generated_four','saved')]]
    r['captures'] += [dict(label=label,read_batch=deepcopy(read_batch),binding=deepcopy(r['saved']['binding']),parameters=[])for label in ['saved_before_cl','saved_after_cl']]
    rows=[dict(operation_native_id=o['native_id'],toolpath_record_counts=deepcopy(o['toolpath_record_counts']))for o in r['saved']['binding']['operations']if o['toolpath_generated']is True]
    r['cl_exports']={'saved':dict(label='saved',status='pending',native_call_attempted=True,native_call_returned=True,output_directory_created=True,output_absent_before_dispatch=True,native_dispatch_pending=False,output_verified=False,readback_verified=False,parent_session_preserved=False,GTP_attempted=False,model_saved=False,production_qualified=False,native_return=dict(python_type='int',value_recorded=True,value=0),output_path=path,source_sha256=r['saved_source_sha256'],document=deepcopy(r['current_document']),expected_generated_operations=rows)}
    assert len(r['saved']['binding']['operations'])==21 and len(r['saved']['parameters'])==12
    assert len(rows)==18 and sum(x['toolpath_record_counts'][0]for x in rows)==158630
    # Run the real pure validators before exposing the fixture to negative cases.
    assert c.native_completion(r,loaded,p)['original_status']=='uncertain'
    assert c.completed_export_observation(r,p)['status']=='pending'
    return r,loaded,p

def setpath(value,path,replacement):
    for k in path[:-1]:value=value[k]
    value[path[-1]]=replacement

def test_actual_native_contract_preserves_uncertain(evidence):
    r,l,p=evidence;before=json.dumps(r,sort_keys=True)
    v=c.native_completion(r,l,p)
    assert v['operations']==21 and v['parameters']==12 and v['original_receipt_modified']is False
    assert json.dumps(r,sort_keys=True)==before and r['status']=='uncertain'

@pytest.mark.parametrize('path,value',[
 (['status'],'saved_configured_local_generation_review_required'),(['readback_verified'],True),
 (['continuation_ready'],True),(['cleanup_session_active'],True),(['native_dispatch_pending'],True),
 (['operation_creation_attempted'],True),(['physical_cutting_conditions_qualified'],True),
 (['messages','disconnected'],False),(['issue','locations',1,'line'],125),
 (['source_transition','strict_save_return'],True),(['source_transition','document','needs_save'],True),
 (['save_stage','save_readback_verified'],False),(['save_stage','native_return_value'],False),
 (['actions','GTP:344','attempted'],False),(['actions','SaveActiveDocument','native_return','value'],1),
 (['completed_gtp_counts','344'],[1]),(['feed_policy','left_rough'],[[35,70]]),
 (['phase_proof_checks',1,'verified'],False),(['actual_new_ids',0],999),
 (['saved','parameters',8,'nc','feeds_compensation','XYFeed'],70.0),
])
def test_native_contract_rejects_mutated_actual(evidence,path,value):
    raw,l,p=evidence;r=deepcopy(raw);setpath(r,path,value)
    with pytest.raises((ValueError,KeyError,AssertionError)):c.native_completion(r,l,p)

def test_forbids_fabricated_checkpoint(evidence):
    raw,l,p=evidence;r=deepcopy(raw);r['saved_checkpoint']={}
    with pytest.raises(ValueError):c.native_completion(r,l,p)

def test_actual_export_observation(evidence):
    r,l,p=evidence;v=c.completed_export_observation(r,p)
    assert sum(x['toolpath_record_counts'][0]for x in v['expected_generated_operations'])==158630
    assert v['status']=='pending' and v['output_verified']is False

@pytest.mark.parametrize('path,value',[
 (['cl_exports','saved','native_call_returned'],False),
 (['cl_exports','saved','native_return','value'],True),
 (['cl_exports','saved','parent_session_preserved'],True),
 (['cl_exports','saved','output_verified'],True),
 (['cl_exports','saved','output_path'],'wrong.cl'),
 (['captures',4,'read_batch','read_scope_complete'],False),
 (['captures',4,'binding','operations',17,'native_id'],999),
 (['cl_exports','saved','source_sha256'],'0'*64),
])
def test_export_rejects_mutated_actual(evidence,path,value):
    raw,l,p=evidence;r=deepcopy(raw);setpath(r,path,value)
    with pytest.raises(ValueError):c.completed_export_observation(r,p)

@pytest.mark.parametrize('text',['{"a":1,"a":2}','{"x":NaN}','{"x":1e999}','[]'])
def test_json_rejects_ambiguous_nonfinite(tmp_path,text):
    p=tmp_path/'input.json';p.write_text(text)
    with pytest.raises(ValueError):q.read(p,q.pin(p)['sha256'])

def test_pin_catches_byte_count(tmp_path):
    p=tmp_path/'input';p.write_text('abc');v=q.pin(p);v['bytes']=4
    with pytest.raises(ValueError):q.check(v)

@pytest.mark.parametrize('scope',['SAVED_LOCAL_ROUGH_FINISH_GROUP_V1','EXISTING_LOCAL_DEFINITIONS_DEPTH_REPRESENTATION_CONTINUATION_V1','anything'])
def test_legacy_scopes_rejected_before_fields(scope):
    from types import SimpleNamespace as N
    p=N(group=N(),prior=N(),configured=N(),engine=N(ids=lambda t,k:[]),SCOPE='SAVED_CONFIGURED_LOCAL_FOUR_GENERATION_V1')
    l={'configuration_generation':{'targets':[]}}
    with pytest.raises(ValueError):c.native_completion({'scope':scope},l,p)

def test_reconciliation_no_native_dispatch_imports():
    text=Path(c.__file__).read_text()
    assert 'connect_solidworks'not in text and 'NativeBackend'not in text and 'dispatch_once'not in text

def test_wrapper_offline_and_one_output():
    import ast
    tree=ast.parse((R/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    public=next(v for v in tree.body if isinstance(v,ast.FunctionDef)and v.name=='solidworks_cam_offline_reconcile_local_generation')
    calls=[v for v in ast.walk(public)if isinstance(v,ast.Call)]
    locked=next(v for v in calls if isinstance(v.func,ast.Name)and v.func.id=='_run_locked')
    assert {v.arg:ast.literal_eval(v.value)for v in locked.keywords}=={'load_automation':False,'desktop_guard':False}
    assert '_selected_process_id'not in ast.unparse(public)


def test_historical_configuration_does_not_recheck_old_current_hash():
    from types import SimpleNamespace as N
    calls=[]
    def load(*args,**kwargs):calls.append((args,kwargs));return 'checked'
    r={'configuration_receipt_pin':{'path':'archive.json','sha256':'old'},'request':{'process_id':12},'source_path':'current.SLDPRT','source_sha256':'historical'}
    assert q.load_historical_configuration(N(context=N(load_completed=load)),r)=='checked'
    assert calls==[(('archive.json','old'),{'process_id':12,'expected_document_path':'current.SLDPRT','expected_source_sha256':'historical','check_current':False})]

@pytest.fixture
def qualified_input(tmp_path,monkeypatch):
    f=tmp_path/'proof';f.write_bytes(b'proof');proof=q.pin(f)
    source=tmp_path/'current';source.write_bytes(b'current');sp=q.pin(source)
    own=q.pin(q.__file__)
    for name in ['PRODUCER_SHA','CONTEXT_SHA','PARSER_SHA','CONTRACT_SHA','PRIOR_AUTHORITY_SHA']:monkeypatch.setattr(q,name,proof['sha256'])
    value=dict(scope=q.SCOPE,status='qualified_saved_input',producer_terminal_semantics_independently_revalidated=True,
        qualifier_pin=own,generation_receipt_pin=proof,configuration_receipt_pin=proof,generation_producer_pin=proof,historical_context_producer_pin=proof,prior_authority_pin=proof,source_pin=sp,source_backup_pin=sp,reconciliation_contract_pin=proof,extended_parser_pin=proof,
        historical_configuration_current_hash_required=False,counts={'operations':21,'parameters':12,'paths':18,'protected_paths':14},terminal_verification={'status':'saved_generation_native_facts_reconciled_offline','source_sha256':sp['sha256']},
        direct_dependency_pins=[proof,sp,own],source_sha256=sp['sha256'],receipt_pin=proof,producer_pin=proof,frame={'qualification_verified':True,'xy_identity':True,'z_offset_mm':26},prefix_check={'protected14_full_streams_unchanged':True},learned_targets=[{}, {}, {}, {}],
        saved_cl={'output':proof,'expected_generated_operations':[{}]*18},prior_cl={'output':proof,'expected_generated_operations':[{}]*14},
        tool_profile_authority={'receipt_pin':proof,'tool_native_id':342,'native_saved_profile_verified':True,'physical_tool_identity_qualified':False},
        original_receipt_status='uncertain',original_receipt_modified=False,offline_postcleanup_proof_closure_verified=True,production_qualified=False,whole_operation_engagement_verified=False)
    return value,source

def test_load_qualified_checks_direct_inputs(tmp_path,qualified_input):
    v,source=qualified_input;p=tmp_path/'q.json';p.write_text(json.dumps(v));digest=q.pin(p)['sha256']
    assert q.load_qualified(p,digest)['source_sha256']==v['source_sha256']
    source.write_bytes(b'changed')
    with pytest.raises(ValueError):q.load_qualified(p,digest)

@pytest.mark.parametrize('key,value',[('historical_configuration_current_hash_required',True),('original_receipt_status','saved'),('original_receipt_modified',True),('production_qualified',True),('offline_postcleanup_proof_closure_verified',False),('direct_dependency_pins',[])])
def test_prepared_authority_fail_closed(tmp_path,qualified_input,key,value):
    v,_=qualified_input;v[key]=value;p=tmp_path/'q.json';p.write_text(json.dumps(v))
    with pytest.raises(ValueError):q.load_qualified(p,q.pin(p)['sha256'])


def wrapper_helper(scripts):
    import ast
    tree=ast.parse((R/'mcp-server/server.py').read_text(encoding='utf-8-sig'))
    node=next(v for v in tree.body if isinstance(v,ast.FunctionDef)and v.name=='_cam_local_generation_reconciliation_payload')
    namespace={'SCRIPTS_DIR':str(scripts)};exec(compile(ast.Module(body=[node],type_ignores=[]),'wrapper','exec'),namespace)
    return namespace[node.name]

def wrapper_fixture(tmp_path):
    scripts=tmp_path/'scripts';scripts.mkdir();module=scripts/'saved_generation_engagement.py';module.write_text('pass')
    p={'process_id':12,'module_sha256':q.pin(module)['sha256'],'output_path':str(tmp_path/'output.json')}
    for key in ['receipt_path','prior_authority_path','archived_cl_path','source_backup_path']:p[key]=str(tmp_path/key)
    payload={'action':q.ACTION,'params':p};request=tmp_path/'request.json';request.write_text(json.dumps(payload))
    return wrapper_helper(scripts),request,payload,module

def test_wrapper_valid_seal(tmp_path):
    helper,request,payload,module=wrapper_fixture(tmp_path)
    assert helper(str(request),q.pin(request)['sha256'],12)==payload

@pytest.mark.parametrize('change',['pid','action','output_alias','module','duplicate'])
def test_wrapper_seal_rejects(tmp_path,change):
    helper,request,payload,module=wrapper_fixture(tmp_path)
    if change=='pid':payload['params']['process_id']=True
    if change=='action':payload['action']='generate_configured_local_group'
    if change=='output_alias':payload['params']['output_path']=str(request)
    if change=='module':module.write_text('changed')
    request.write_text(json.dumps(payload))
    if change=='duplicate':request.write_text('{"action":"offline_reconcile_local_generation","action":"offline_reconcile_local_generation","params":{}}')
    with pytest.raises(ValueError):helper(str(request),q.pin(request)['sha256'],12)


@pytest.mark.parametrize('path',[
 ['save_stage','before','binding','operations',17,'native_id'],
 ['save_stage','after','binding','operations',17,'native_id'],
 ['captures',0,'binding','operations',17,'native_id'],
 ['captures',1,'binding','operations',17,'native_id'],
 ['captures',2,'binding','operations',17,'native_id']])
def test_conflicting_capture_or_save_stage_rejected(evidence,path):
    raw,l,p=evidence;r=deepcopy(raw);setpath(r,path,999)
    with pytest.raises(ValueError):
        c.native_completion(r,l,p);c.completed_export_observation(r,p)

def test_cutcom_declaration_even_without_affected_motion_rejected():
    prior={'declared_units':['MM'],'commands':[]}
    current={'declared_units':['MM'],'commands':[],'motions':[{'block':b,'cutcom_state':{'status':'not_declared'}}for b in range(14,18)],'cutcom_records':[{'block':14}]}
    with pytest.raises(ValueError):c.cl_protection(prior,current,[],[],[],None,lambda *a:{})
