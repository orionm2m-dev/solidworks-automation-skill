from copy import deepcopy
from pathlib import Path
import json,hashlib
import pytest
from test_current_saved_compound import env,collection
from scripts import sw_cam_mill_current_compound_read as m
from scripts import sw_cam_mill_current_parameters as p

@pytest.fixture
def params_env(env,monkeypatch,tmp_path):
    e=env;monkeypatch.setattr(p,'preflight',lambda *a:dict(native_calls=0));target=e['target'];target['QueryInterface']=lambda cls:target
    ops=[]
    for oid,kind in [(355,0),(356,1)]:
        ops.append(dict(_id=oid,OpernType=kind,Suppressed=False,GetIsToolpathGenerated=False,IGetAllFeatures=collection([target]),IGetEnumToolpaths=collection([]),IGetTool=e['tool'],DepthReading=7.6,AllowReading=.25))
    e['os1']['IGetEnumOperations']=collection(ops);e['args']['expected_operation_native_ids']=[195,267,355,356]
    e['doc']['GetCWObjectFromID']=lambda kind,oid:(target,True) if kind==1 else (next(x for x in ops if x['_id']==oid),True)
    baseline=e['run']();assert baseline['readback_verified'],baseline
    state=deepcopy(baseline['before']);state['document']=deepcopy(baseline['document']);state['strategy_diagnostics']={'compound_strategy':{'attribute_id':1}};state['default_operation_catalogues']=[]
    def strategy(*args,**kwargs):args[4].update(compound_strategy={'attribute_id':1})
    monkeypatch.setattr(p,'read_compound_strategy',strategy);monkeypatch.setattr(p,'read_catalogues',lambda *a,**k:[])
    def levels(op,feature,*,read,typed,feature_dispatch):return {'machining_depth':read(op,'DepthReading')}
    monkeypatch.setattr(p.pocket,'read_levels',levels)
    monkeypatch.setattr(p.pocket.rough,'read_rough_entry_parameters',lambda op,feature,*,read,typed,diagnostic:{'SideAllow':read(op,'AllowReading')})
    monkeypatch.setattr(p.pocket,'read_finish_parameters',lambda op,feature,*,read,typed:{'SideAllow':read(op,'AllowReading')})
    monkeypatch.setattr(p,'read_tool_dimensions',lambda tool,generic,batch:dict(generic=deepcopy(generic),cut_diameter=batch.read(tool,'CutDiameter'),native_units_verified=False))
    keys=('process_id','expected_process_create_time','expected_document_path','expected_feature_native_id','expected_feature_setup_native_id','expected_operation_setup_native_id')
    authority=dict(scope='MILL_CURRENT_SAVED_APPEND_V1',status='review_required',phase='finished',action='apply',binding={k:e['args'][k] for k in keys},saved_file_sha256='a'*64,source_after_sha256='a'*64,saved=state,confirm_saved=deepcopy(state),new_operations=deepcopy(state['operations'][-2:]),GTP_attempted=False,GOP_attempted=False,native_dispatch_pending=False,save_hresult=0,messages=dict(subscribed=True,active=False,disconnected=True,event_count=0))
    authority['binding']['definition_mode']='selected_insert'
    for k in ('readback_verified','runtime_unchanged','operation_delta_verified','save_readback_verified','model_saved','source_update_verified','save_call_returned'):authority[k]=True
    path=tmp_path/'authority.json'
    def save():
        path.write_text(json.dumps(authority),encoding='utf-8');e['args']['parameters_authority_receipt_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    e['args'].update(observation='operation_parameters',parameter_operation_native_ids=[355,356],parameters_authority_receipt_path=str(path));save()
    monkeypatch.setattr(m,'_file_hash',lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else e['digest'])
    e['calls'].clear();e.update(ops=ops,authority=authority,save_authority=save,authority_path=path)
    return e

def test_two_real_captures_exact_authority_and_own_parameters(params_env):
    e=params_env;r=e['run']();assert r['readback_verified'],r
    assert r['parameter_observations_verified'] and r['before']==r['after']
    assert [v['operation_native_id'] for v in r['before']['operation_parameters']]==[355,356]
    assert r['before']['operation_parameters'][0]['levels']['machining_depth']==7.6
    assert r['before']['operation_parameters'][1]['finish']['SideAllow']==.25
    assert not any(n.startswith(('Set','Save','Insert','Generate'))for n in e['calls'])
    assert not r['units_verified'] and not r['full_tool_profiles_read'] and not r['physical_tool_qualified']

@pytest.mark.parametrize('defect',['source','lifetime','binding','rough_type','flags','newids','saved_equal','generated','incomplete','gop','tool'])
def test_bad_authority_before_any_native(params_env,defect):
    e=params_env;d=e['authority']
    if defect=='source':d['source_after_sha256']='b'*64
    elif defect=='lifetime':d['binding']['expected_process_create_time']=500.
    elif defect=='binding':d['binding']['definition_mode']='retain_plan'
    elif defect=='rough_type':d['new_operations'][0]['mill_operation_type']=2
    elif defect=='flags':d['save_readback_verified']=False
    elif defect=='newids':d['new_operations'][1]['native_id']=357
    elif defect=='saved_equal':d['confirm_saved']['operation_count']=99
    elif defect=='generated':d['new_operations'][0]['toolpath_generated']=True
    elif defect=='incomplete':d['saved']['capture_complete']=False
    elif defect=='gop':d['GOP_attempted']=True
    else:d['new_operations'][0]['assigned_tool']['native_id']=199
    e['save_authority']();r=e['run']();assert not r['readback_verified'] and not e['calls']

@pytest.mark.parametrize('change',['own_tool','lookup_alias','source','lifetime','authority','parameter'])
def test_fresh_drift_stops_or_fails_exact_repeat(params_env,change):
    e=params_env
    if change=='own_tool':e['tool']['Protrusion']=99.
    elif change=='lookup_alias':
        old=e['doc']['GetCWObjectFromID'];e['doc']['GetCWObjectFromID']=lambda kind,oid:(dict(e['ops'][1],_id=356),True)if kind==3 and oid==355 else old(kind,oid)
    else:
        fired=False
        def hook(name):
            nonlocal fired
            if name!='DepthReading' or fired:return
            fired=True
            if change=='source':e['digest']='b'*64
            elif change=='lifetime':e['process']['create_time']=200.
            elif change=='authority':e['authority_path'].write_text('{}',encoding='utf-8')
            else:e['ops'][0]['AllowReading']=.75
        e['hook']=hook
    r=e['run']()
    # A one-time parameter change before first parameter observation yields a stable new value;
    # use after-first-value drift below for the actual double-observation test.
    if change=='parameter':assert r['readback_verified']
    else:assert not r['readback_verified'] and not r['parameter_observations_verified']

def test_parameter_value_changes_after_return_fails_double_capture(params_env):
    e=params_env;fired=False
    def hook(name):
        nonlocal fired
        if name=='AllowReading'and not fired:fired=True;e['ops'][0]['AllowReading']=.75
    e['hook']=hook;r=e['run']();assert not r['readback_verified'];assert r['before']['operation_parameters'][0]['rough']['SideAllow']==.25
    assert r['after']['operation_parameters'][0]['rough']['SideAllow']==.75

def test_event_after_native_parameter_retains_raw_then_no_more_getters(params_env):
    e=params_env
    def hook(name):
        if name=='DepthReading':e['session'].state['event_count']=1
    e['hook']=hook;r=e['run']();assert not r['readback_verified'];assert e['calls'][-1]=='DepthReading'
    assert r['parameter_getter_diagnostics'][-1]['returned']and r['parameter_getter_diagnostics'][-1]['raw']['raw']==7.6
    assert 'after'not in r

@pytest.mark.parametrize('value',[None,[],[355],[355,355],[True,356],['355',356],[355,357]])
def test_target_list_rejects_before_native(params_env,value):
    e=params_env;r=e['run'](parameter_operation_native_ids=value);assert not r['readback_verified']and not e['calls']

def test_legacy_mode_rejects_parameter_authority_before_native(params_env):
    e=params_env;r=e['run'](observation='three_step_profile');assert not r['readback_verified']and not e['calls']

@pytest.fixture
def continued_env(params_env,monkeypatch):
    e=params_env;d=e['authority'];d['binding'].update(definition_mode='selected_continue',retained_operation_native_id=355)
    d['retained_operations']=[d['new_operations'].pop(0)];d['continuation_retained_operation_native_id']=355;d['continuation_recovery_verified']=True
    d['definition_actions']=[dict(kind='insert',anchor_native_id=355,actual_native_id=356,choice=dict(operation_type=1,feature_native_id=70,operation_setup_native_id=94),attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False)]
    nc=dict(read_complete=True,spindle_speed_native=1000.,xy_feed_native=250.,physical_units_qualified=False,cutting_conditions_qualified=False,full_parameters_read=False)
    d['saved']['retained_operation_nc']=dict(operation_native_id=355,read_complete=True,nc=deepcopy(nc));d['confirm_saved']=deepcopy(d['saved'])
    d['after']=deepcopy(d['saved']);d['after']['document']['needs_save']=True;d['confirm_after']=deepcopy(d['after'])
    monkeypatch.setattr(p.definitions,'read_own_nc',lambda raw,read,typed:deepcopy(nc))
    e['save_authority']();return e

def test_completed_recovery_uses_retained_rough_and_new_finish(continued_env):
    e=continued_env;r=e['run']();assert r['readback_verified'],r
    assert r['before']==r['after']and r['before']['retained_operation_nc']['operation_native_id']==355
    assert [x['operation_native_id']for x in r['before']['operation_parameters']]==[355,356]

@pytest.mark.parametrize('bad',['recoveryflag','retainedid','pendingfinish','extraaction','save_delta','retainednc','partialstatus'])
def test_recovery_completed_loader_rejects_partial_or_wrong_chain(continued_env,bad):
    e=continued_env;d=e['authority']
    if bad=='recoveryflag':d['continuation_recovery_verified']=False
    elif bad=='retainedid':d['binding']['retained_operation_native_id']=999
    elif bad=='pendingfinish':d['definition_actions'][0]['native_dispatch_pending']=True
    elif bad=='extraaction':d['definition_actions'].append(deepcopy(d['definition_actions'][0]))
    elif bad=='save_delta':d['after']['operation_count']+=1;d['confirm_after']=deepcopy(d['after'])
    elif bad=='retainednc':d['saved']['retained_operation_nc']['read_complete']=False;d['confirm_saved']=deepcopy(d['saved']);d['after']=deepcopy(d['saved']);d['confirm_after']=deepcopy(d['after'])
    else:d['status']='uncertain'
    e['save_authority']();r=e['run']();assert not r['readback_verified']and not e['calls']

def test_changed_retained_nc_rejected_by_fresh_authority_before_parameters(continued_env,monkeypatch):
    e=continued_env;monkeypatch.setattr(p.definitions,'read_own_nc',lambda *a,**k:dict(read_complete=True,spindle_speed_native=42.))
    r=e['run']();assert not r['readback_verified']and 'DepthReading'not in e['calls']

def test_missing_parameter_interface_stops_before_native(params_env,monkeypatch):
    def fail(*a):raise ValueError('Interface not admitted')
    monkeypatch.setattr(p,'preflight',fail);r=params_env['run']()
    assert not r['readback_verified']and not params_env['calls']
