"""Independent focused receipt authority tests; fake Save callbacks touch tmpfiles only."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
extra=Path(os.environ.get('SWMCP_SAVED_CONTEXT_ROOT',ROOT.parent/'cam_current_pocket_context_finalize_20261111'))/'scripts'
if extra.is_dir():scripts.__path__.insert(0,str(extra))
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_current_pocket_context as current
from scripts import sw_cam_current_pocket_cl_recovery as c


def write(path,value):
    path.write_text(json.dumps(value,allow_nan=False),encoding='utf-8');return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

@pytest.fixture
def probe(tmp_path):
    target=tmp_path/'part.sldprt';target.write_bytes(b'before');old=hashlib.sha256(target.read_bytes()).hexdigest()
    root=write(tmp_path/'root.json',{'frozen':'root'})
    previous=dict(scope=current.pair.SCOPE,status='observed',phase='finished',**{k:True for k in current.pair.FLAGS})
    predecessor=write(tmp_path/'read.json',previous)
    doc=dict(path=str(target),title=target.name,type=1,needs_save=False)
    header=dict(native_id=10,owner_setup_native_id=20,island_count=4)
    rows=[dict(native_id=i,assigned_tool={'native_id':t})for i,t in [(30,50),(31,51)]]
    state=dict(document=doc,saved_file_sha256=old,operations=rows,selected_feature=header,feature_setups=[{'origin_native':[0,0,0]}],operation_setups=[{'native_id':21}])
    params=[dict(operation_native_id=i,read_complete=True,levels={'setup':{'origin_native':[0,0,26]}},tool={'native_id':t})for i,t in [(30,50),(31,51)]]
    d=dict(scope=current.definition.SCOPE,process_id=123,expected_document_path=str(target),expected_source_sha256=old,expected_feature_native_id=10,
        evidence=root,save_pin=root,saved_transition={'document':deepcopy(doc)},expected_inventory={'features':[header]},current_sketch_baseline={'saved_file_sha256':old,'needs_save':False,'features':[],'solids':[]},
        spec={'circle':8},request=dict(process_id=123,expected_process_create_time=12.,expected_document_path=str(target),expected_sw_configuration='Default',expected_cam_configuration='Mill',owner_setup_native_id=20),
        creator=dict(status='uncertain',feature_header=header),sketch={'sketch_readback':{'circle':8}},pins=[root,predecessor,dict(path=str(target),sha256=old)])
    previous.update(request={'expected_document_path':str(target)},evidence_pins=[root],after=deepcopy(state),before_diagnostic={'actual_sketch_snapshot':dict(deepcopy(d['current_sketch_baseline']),needs_save=False)})
    predecessor=write(tmp_path/'read.json',previous);d['pins']=[root,predecessor,dict(path=str(target),sha256=old)]
    bundle=dict(context=d,state=state,parameters=params,receipt_pin=predecessor,root_pins=[root,predecessor],pins=d['pins'],lineage_pins=[predecessor])
    calls=[];observed=dict(inventory=deepcopy(state),parameters=deepcopy(params));report={};persisted=[]
    def capture(label):calls.append('capture:'+label);return deepcopy(observed)
    def save():calls.append('save');target.write_bytes(b'after');return 0
    def adopt(new):calls.append('adopt');observed['inventory']['saved_file_sha256']=new['expected_source_sha256'];observed['inventory']['document']['needs_save']=False
    def persist():persisted.append(deepcopy(report))
    kw=dict(capture=capture,save=save,guard=lambda:calls.append('guard'),claim=lambda:calls.append('claim'),persist=persist,adopt_context=adopt)
    return dict(target=target,bundle=bundle,expected=deepcopy(observed),observed=observed,report=report,calls=calls,kw=kw,persisted=persisted)


def run(p):return current.save_current_baseline(p['report'],p['bundle'],p['expected'],**p['kw'])


def terminal(p,out,name='changed.json'):
    r=p['report'];r.update(status='review_required',phase='finished',current_context_verified=True,inventory_delta_verified=True,parameter_delta_verified=True,runtime_unchanged=True,
        GOP_attempted=False,GTP_attempted=False,Import_attempted=False,automatic_replay=False,production_qualified=False,
        messages=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]),
        after_cleanup_identity=dict(document=deepcopy(out['state']['document']),saved_file_sha256=out['state']['saved_file_sha256']))
    pin=write(p['target'].parent/name,r);v=deepcopy(out['payload']['identity']);v.update(current_context_receipt_path=pin['path'],current_context_receipt_sha256=pin['sha256']);return v




@pytest.fixture
def historical(probe):
    p=probe;out=run(p);v=terminal(p,out);pin={'path':v['current_context_receipt_path'],'sha256':v['current_context_receipt_sha256']}
    pins=deepcopy(out['context']['pins'])
    # A later native Save has legitimately changed the live file. This function
    # must authenticate the old immutable record, never pretend it is live.
    p['target'].write_bytes(b'later native save')
    return p,pin,v,pins


def hcheck(case):
    p,pin,v,pins=case
    return c.historical_baseline(p['report'],pin,v,evidence_pins=pins)


def test_historical_baseline_preserves_old_authority_without_rebinding_live_target(historical):
    old=deepcopy(historical);out=hcheck(historical)
    assert historical==old and out['historical_only']is True
    assert out['context']['authority_scope']=='HISTORICAL_CURRENT_CONTEXT_NOT_LIVE'
    assert out['context']['expected_source_sha256']==historical[2]['expected_source_sha256']
    assert hashlib.sha256(historical[0]['target'].read_bytes()).hexdigest()!=out['context']['expected_source_sha256']
    assert out['state']['operations']==historical[0]['report']['current_context']['snapshot']['inventory']['operations']


@pytest.mark.parametrize('damage',['terminal_flag','identity','cleanup','native_bool','limit','root_drop','capture_geometry','root_bytes'])
def test_historical_current_guards_remain_strict(historical,damage):
    p,pin,v,pins=historical;r=p['report'];payload=r['current_context']
    if damage=='terminal_flag':r['current_context_verified']=False
    elif damage=='identity':v['process_id']+=1
    elif damage=='cleanup':r['after_cleanup_identity']['document']['title']='another part'
    elif damage=='native_bool':r['native_save']['native_return_value']=True
    elif damage=='limit':payload['limitations']['persistence_verified']=True
    elif damage=='root_drop':payload['root_pins']=payload['root_pins'][1:]
    elif damage=='capture_geometry':payload['capture_context']['current_sketch_baseline']['features']=[{'changed':True}]
    elif damage=='root_bytes':Path(p['bundle']['root_pins'][0]['path']).write_bytes(b'changed immutable evidence')
    with pytest.raises(ValueError):hcheck(historical)


@pytest.mark.parametrize('damage',['missing','duplicate','wrong_sha'])
def test_historical_target_preimage_is_exactly_one_recorded_pin(historical,damage):
    p,pin,v,pins=historical
    target=next(x for x in pins if c.definition.creator.same_path(x['path'],str(p['target'])))
    if damage=='missing':pins.remove(target)
    elif damage=='duplicate':pins.append(deepcopy(target))
    else:target['sha256']='a'*64
    with pytest.raises(ValueError,match='historical target'):hcheck(historical)


@pytest.fixture
def saved_attempt(probe):
    p=probe;out=run(p);terminal(p,out);r=deepcopy(p['report']);root=p['target'].parent
    identity=dict(process_id=123,expected_process_create_time=12.,expected_document_path=str(p['target']),expected_source_sha256=p['bundle']['context']['expected_source_sha256'],expected_feature_native_id=10,expected_operation_native_ids=[30,31],selected_operation_native_id=30)
    old=dict(identity,failed_generation_receipt_path=str(root/'failed.json'),failed_generation_receipt_sha256='a'*64,observed_xy_feed_before=100.,observed_xy_feed_after=200.,receipt_path=str(root/'save.json'),saved_cl_path=str(root/'never-exported.cl'),qualification_only=True,acknowledge_observed_feed_save_export=True,message_policy='vendor_default')
    v=dict(identity,expected_source_sha256=r['saved_file_sha256_after_native_return'],saved_attempt_receipt_path=str(root/'save.json'),saved_attempt_receipt_sha256='b'*64,receipt_path=str(root/'fresh.json'),saved_cl_path=str(root/'fresh.cl'),qualification_only=True,acknowledge_export_only=True,message_policy='vendor_default')
    r.pop('current_context');r.update(scope=c.recovery.SCOPE,status='uncertain',phase='finished',failed_phase='after',reason='Bounded explicit evidence pins required',request=old,
      issue=dict(type='ValueError',hresult=None,locations=[dict(file=f,function=fn)for f,fn in [('sw_cam_current_pocket_context.py','save_current_baseline'),('sw_cam_current_pocket_context.py','_pins'),('sw_cam_process_import.py','require')]]),
      native_dispatch_pending=False,second_capture_roles=['generated_state_confirmation','save_before'],before=deepcopy(p['expected']),confirm_before=deepcopy(p['expected']))
    r.update({k:False for k in c.recovery.FLAGS})
    r.update({k:True for k in ('Save_attempted','save_attempted','save_readback_verified','model_saved','mutation_attempted','native_call_attempted','native_call_returned','receipt_created','marker_created')})
    r.update({k:False for k in ('operation_parameter_setters_attempted','setters_replayed','GTP_attempted','GTP_replayed','GOP_attempted','Import_attempted','CL_export_attempted','automatic_replay','production_qualified','native_units_verified','cutting_conditions_qualified')})
    r['actions']={'SaveActiveDocument':dict(attempted=True,returned=True,native_dispatch_pending=False,native_return_type='int',native_return_value=0)}
    r['captures']=[]
    for label in ['recovery_current','before','after']:
        snapshot=p['expected']if label=='recovery_current'else r['save_snapshots'][label]
        r['captures'].append(dict(label=label,observation=deepcopy(snapshot),diagnostic=dict(capture_complete=True,state=deepcopy(snapshot['inventory']))))
    return r,v,deepcopy(p['expected'])


def test_saved_attempt_admits_only_recorded_completed_save_without_promoting_raw_status(saved_attempt):
    before=deepcopy(saved_attempt)
    assert c.verify_saved_attempt(*saved_attempt)is True
    assert saved_attempt==before and saved_attempt[0]['status']=='uncertain'
    assert saved_attempt[0]['model_saved']is True and saved_attempt[0]['CL_export_attempted']is False


@pytest.mark.parametrize('damage',['pid','source','save_bool','extra_action','new_save_pending','failure_kind','after_incomplete','after_conflict','confirm_conflict','event','new_CL','replayed_GTP','promoted_raw_flag'])
def test_saved_attempt_rejects_unrelated_or_incomplete_boundaries(saved_attempt,damage):
    r,v,expected=saved_attempt
    if damage=='pid':v['process_id']+=1
    elif damage=='source':v['expected_source_sha256']=r['request']['expected_source_sha256']
    elif damage=='save_bool':r['actions']['SaveActiveDocument']['native_return_value']=True
    elif damage=='extra_action':r['actions']['postCL']={}
    elif damage=='new_save_pending':r['native_dispatch_pending']=True
    elif damage=='failure_kind':r['issue']['locations'][0]['function']='different_failure'
    elif damage=='after_incomplete':r['captures'][-1]['diagnostic']['capture_complete']=False
    elif damage=='after_conflict':r['captures'][-1]['observation']['parameters'][1]['tool']['native_id']=99
    elif damage=='confirm_conflict':r['confirm_before']['parameters'][0]['tool']['native_id']=99
    elif damage=='event':r['messages']['event_count']=1;r['messages']['events']=[{}]
    elif damage=='new_CL':r['postCL']={}
    elif damage=='replayed_GTP':r['GTP_replayed']=True
    elif damage=='promoted_raw_flag':r['runtime_unchanged']=True
    with pytest.raises(ValueError):c.verify_saved_attempt(*saved_attempt)
