from contextlib import nullcontext
from copy import deepcopy
import hashlib
from pathlib import Path
import pytest
from scripts import sw_cam_turn_variable_allowance_write as m

@pytest.fixture
def env(tmp_path,monkeypatch):
    baseline=tmp_path/'baseline.SLDPRT';copy=tmp_path/'qualification.SLDPRT'
    baseline.write_bytes(b'complete saved CAM');copy.write_bytes(baseline.read_bytes());sha=hashlib.sha256(copy.read_bytes()).hexdigest()
    e={'calls':[],'hook':None,'dirty':False,'mode':0,'session':None,'setter_result':True,'pid':123,'native_id':22,'type':2,'ids':[11]}
    entries=[{'name':str(i),'radial_x_native':0.,'axial_z_native':0.} for i in range(7)]
    profile=[{'native_id':11,'profile':{'name':'OD','segment_count':7,'segments':[{'curve_parameters_available':True,'start_native':[1,0,i],'end_native':[1,0,i+1]} for i in range(7)]}}]
    inventory={'machine_type':3,'feature_count':5,'operation_count':9,'operations':[{'setup_index':0,'operation_index':3,'turn_operation_type':2,'toolpath_generated':False,'toolpath_record_counts':[]}]}
    class Session:
        def __init__(self,*args):
            self.state=dict(active=False,subscribed=False,disconnected=False,event_count=0,overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]);e['session']=self
        def __enter__(self):self.state.update(active=True,subscribed=True);return self
        def __exit__(self,*args):
            self.state.update(active=False,disconnected=True)
            if e.get('cleanup_hook'):e['cleanup_hook']()
        def summary(self):return deepcopy(self.state)
    def arrays():return (tuple(x['name'] for x in entries),tuple(x['radial_x_native'] for x in entries),tuple(x['axial_z_native'] for x in entries),len(entries),True)
    def mode_set(value):e.update(mode=value,dirty=True);return None
    def amount_set(name,x,z):
        for row in entries:
            if row['name']==name:row.update(radial_x_native=x,axial_z_native=z)
        e['dirty']=True;return e['setter_result']
    turn={'GetAllVariableAllowances':arrays,'SetVariableAllowance':amount_set,'native_id':lambda:e['native_id'],'type':lambda:e['type'],'ids':lambda:e['ids']}
    mode_obj={'GetAllowanceMethodVariable':lambda:e['mode'],'SetAllowanceMethodVariable':mode_set}
    app={};addin={'GetCWApp':app};sw={'GetProcessID':lambda:e['pid'],'GetAddInObject':lambda clsid:addin};cam={'snapshot':True}
    def member(obj,name,*args):
        if obj is not sw and obj is not addin:assert e['session'] and e['session'].state['active'],'CAM call after disconnect '+name
        e['calls'].append(name);value=obj[name];value=value(*args) if callable(value) else value
        if e['hook']:e['hook'](name)
        return value
    def doc(sw):return {'path':str(copy),'title':copy.name,'type':1,'needs_save':e['dirty']}
    def snapshot(sw,clsid,tlb,config,read,check,identity,diagnostic):
        check();state=identity();read(cam,'snapshot')
        value={'capture_complete':True,'document':state,'saved_file_sha256':sha,'inventory':deepcopy(inventory),
         'selected_operation':{'setup_index':0,'operation_index':3,'native_id':e['native_id'],'turn_operation_type':e['type'],'suppressed':False,'linked_feature_ids':e['ids']},
         'linked_features':deepcopy(profile),'variable_mode_native':read(mode_obj,'GetAllowanceMethodVariable'),'variable_mode_meaning_qualified':False,
         'allowances':m._allowances(read(turn,'GetAllVariableAllowances'))}
        if e['native_id']!=config['expected_operation_native_id'] or e['type']!=config['expected_operation_type'] or e['ids']!=config['expected_linked_feature_ids']:raise ValueError('exact selector mismatch')
        diagnostic.update(value);check();return diagnostic
    def locate(sw,clsid,tlb,config,read):
        if read(turn,'native_id')!=config['expected_operation_native_id'] or read(turn,'type')!=config['expected_operation_type'] or read(turn,'ids')!=config['expected_linked_feature_ids']:raise ValueError('exact target changed')
        return turn,mode_obj
    monkeypatch.setattr(m,'CamMessageSession',Session);monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kwargs:nullcontext())
    monkeypatch.setattr(m,'_member',member);monkeypatch.setattr(m,'_typed',lambda value,*args:value)
    monkeypatch.setattr(m,'document_snapshot',doc);monkeypatch.setattr(m,'_snapshot',snapshot);monkeypatch.setattr(m,'_locate',locate)
    changes=[{'name':'5','expected_radial_x_native':0.,'expected_axial_z_native':0.,'radial_x_native':.2,'axial_z_native':0.},
             {'name':'6','expected_radial_x_native':0.,'expected_axial_z_native':0.,'radial_x_native':.2,'axial_z_native':0.}]
    args=dict(process_id=123,expected_document_path=str(copy),setup_index=0,operation_index=3,expected_operation_native_id=22,
       expected_operation_type=2,expected_linked_feature_ids=[11],expected_source_sha256=sha,baseline_checkpoint_path=str(baseline),
       action='prepare',changes=changes,expected_mode_native=0,candidate_mode_native=1,qualification_only=True,acknowledge_unqualified_mapping_mode_units=True)
    def run(**kw):return m.qualify_turn_variable_allowance(sw,'clsid','tlb',**dict(args,**kw))
    def apply(**kw):
        prep=run();return run(**dict({'action':'apply','expected_state_sha256':prep.get('state_sha256','a'*64),'receipt_path':str(tmp_path/'apply.json')},**kw))
    e.update(locals());return e

def test_prepare_no_mutation(env):
    r=env['run']();assert r['status']=='ok' and r['apply_eligible'] and not r['mutation_attempted']
    assert env['mode']==0 and not any(x.startswith('Set') for x in env['calls'])
    assert not (env['tmp_path']/'apply.json').exists()

def test_apply_exact_bounded_changes(env):
    r=env['apply']();assert r['status']=='review_required' and r['scalar_readback_verified']
    assert r['setters_attempted']==r['setters_returned']==3
    assert env['calls'].count('SetAllowanceMethodVariable')==1 and env['calls'].count('SetVariableAllowance')==2
    assert [x['radial_x_native'] for x in env['entries']]==[0]*5+[.2,.2]
    assert r['linked_profile_unchanged'] and r['inventory_unchanged']
    assert not r['units_verified'] and not r['mode_meaning_verified'] and not r['name_to_geometry_mapping_verified']
    assert r['WIP_validation_required'] and not r['GTP_attempted'] and not r['model_saved']
    assert env['copy'].read_bytes()==env['baseline'].read_bytes()==b'complete saved CAM'

def test_candidate_already_raw1_skips_mode_setter(env):
    env['mode']=1;env['args']['expected_mode_native']=1
    r=env['apply']();assert r['status']=='review_required' and r['setters_attempted']==2
    assert 'SetAllowanceMethodVariable' not in env['calls']

@pytest.mark.parametrize('key,value',[
 ('process_id',True),('setup_index',-1),('operation_index',512),('expected_operation_native_id',0),
 ('expected_operation_type',4),('expected_operation_type',True),('expected_linked_feature_ids',[]),('expected_linked_feature_ids',[11,11]),
 ('expected_linked_feature_ids',[True]),('expected_source_sha256','X'*64),('expected_document_path','relative.SLDPRT'),
 ('baseline_checkpoint_path','relative.SLDPRT'),('action','inspect'),('qualification_only',False),
 ('acknowledge_unqualified_mapping_mode_units',False),('message_policy','ignore'),('expected_mode_native',True),
 ('expected_mode_native',2),('candidate_mode_native',0),('candidate_mode_native',True)])
def test_validation_blocks_before_calls(env,key,value):
    r=env['run'](**{key:value});assert r['status']=='error' and not env['calls']

@pytest.mark.parametrize('field,value',[
 ('name',5),('name',''),('name','x\n'),('radial_x_native',True),('radial_x_native','0.2'),
 ('radial_x_native',float('nan')),('radial_x_native',1.01),('radial_x_native',-.1),
 ('axial_z_native',-.1),('expected_radial_x_native',True),('expected_axial_z_native',2),('unexpected',0)])
def test_change_fields(env,field,value):
    change=deepcopy(env['changes'][:1]);change[0][field]=value
    r=env['run'](changes=change);assert r['status']=='error' and not env['calls']

@pytest.mark.parametrize('change',['empty','three','duplicate','decrease','same'])
def test_change_bounds(env,change):
    values=deepcopy(env['changes'])
    if change=='empty':values=[]
    elif change=='three':values.append(dict(values[0],name='3'))
    elif change=='duplicate':values[1]['name']='5'
    elif change=='decrease':values[0]['expected_radial_x_native']=.3
    else:values[0]['radial_x_native']=0
    r=env['run'](changes=values);assert r['status']=='error' and not env['calls']

def test_no_name_index_coercion(env):
    values=deepcopy(env['changes'][:1]);values[0]['name']='05'
    r=env['run'](changes=values);assert r['status']=='error' and not any(n.startswith('Set') for n in env['calls'])

def test_isolated_copy_required(env):
    r=env['run'](baseline_checkpoint_path=str(env['copy']));assert r['status']=='error' and not env['calls']

def test_baseline_bytes_changed(env):
    env['baseline'].write_bytes(b'other source')
    r=env['run']();assert r['status']=='error' and not any(n.startswith('Set') for n in env['calls'])

def test_dirty_copy_rejected(env):
    env['dirty']=True;assert env['run']()['status']=='error'

def test_existing_toolpath_rejected(env):
    env['inventory']['operations'][0]['toolpath_generated']=True
    assert env['run']()['status']=='error'

def test_expected_raw_value_changed(env):
    env['entries'][5]['radial_x_native']=.1
    assert env['run']()['status']=='error'

def test_expected_mode_changed(env):
    env['mode']=1;assert env['run']()['status']=='error'

def test_apply_stale_hash_no_setters(env):
    r=env['apply'](expected_state_sha256='f'*64);assert r['status']=='error' and r['setters_attempted']==0

@pytest.mark.parametrize('getter',['SetAllowanceMethodVariable','SetVariableAllowance'])
def test_event_after_setter_stops_without_retry(env,getter):
    prep=env['run']();env['calls'].clear()
    def hook(name):
        if name==getter:env['session'].state['event_count']=1
    env['hook']=hook
    r=env['run'](action='apply',expected_state_sha256=prep['state_sha256'],receipt_path=str(env['tmp_path']/'apply.json'))
    assert r['status']=='uncertain' and not r['scalar_readback_verified']
    assert env['calls'].count(getter)==1
    assert not r['automatic_rollback'] and not r['retry_attempted']

@pytest.mark.parametrize('value',[False,None,0,1,'true'])
def test_boolean_setter_strict(env,value):
    env['setter_result']=value;r=env['apply']()
    assert r['status']=='uncertain' and env['calls'].count('SetVariableAllowance')==1

def test_unrequested_name_side_effect_stops(env):
    def hook(name):
        if name=='SetVariableAllowance':env['entries'][0]['radial_x_native']=.1
    env['hook']=hook;r=env['apply']()
    assert r['status']=='uncertain' and env['calls'].count('SetVariableAllowance')==1

def test_geometry_side_effect_not_accepted(env):
    def hook(name):
        if name=='SetVariableAllowance':env['profile'][0]['profile']['name']='unexpected'
    env['hook']=hook;r=env['apply']();assert r['status']=='uncertain' and not r['scalar_readback_verified']

def test_inventory_side_effect_not_accepted(env):
    def hook(name):
        if name=='SetVariableAllowance':env['inventory']['operation_count']=10
    env['hook']=hook;r=env['apply']();assert r['status']=='uncertain'

def test_baseline_changed_after_setter_stops(env):
    def hook(name):
        if name=='SetAllowanceMethodVariable':env['baseline'].write_bytes(b'changed')
    env['hook']=hook;r=env['apply']();assert r['status']=='uncertain' and env['calls'].count('SetVariableAllowance')==0

def test_source_change_after_event_disconnect(env):
    def cleanup():env['copy'].write_bytes(b'changed')
    env['cleanup_hook']=cleanup
    r=env['run']();assert r['status']=='error'

def test_pid_change_after_first_setter(env):
    def hook(name):
        if name=='SetAllowanceMethodVariable':env['pid']=999
    env['hook']=hook;r=env['apply']();assert r['status']=='uncertain' and 'SetVariableAllowance' not in env['calls']

def test_receipt_no_overwrite(env):
    p=env['tmp_path']/'apply.json';p.write_text('previous evidence')
    r=env['apply']();assert r['status']=='error' and p.read_text()=='previous evidence'

def test_receipt_failure_before_setter_no_call(env,monkeypatch):
    orig=m._write_receipt
    def write(path,report,**kwargs):
        if report['phase'].startswith('before_Set'):raise OSError('disk full')
        return orig(path,report,**kwargs)
    monkeypatch.setattr(m,'_write_receipt',write)
    r=env['apply']();assert r['status']=='uncertain' and r['setters_attempted']==0

def test_final_receipt_failure_structured(env,monkeypatch):
    orig=m._write_receipt
    def write(path,report,**kwargs):
        if report['phase']=='finished':raise OSError('disk full')
        return orig(path,report,**kwargs)
    monkeypatch.setattr(m,'_write_receipt',write)
    r=env['apply']();assert r['status']=='uncertain' and 'receipt_finalize_error' in r

def test_mode_setter_side_effect_stops_before_names(env):
    def hook(name):
        if name=='SetAllowanceMethodVariable':env['entries'][0]['axial_z_native']=.1
    env['hook']=hook;r=env['apply']()
    assert r['status']=='uncertain' and 'SetVariableAllowance' not in env['calls']

def test_first_name_com_error_stops_second(env):
    def fail(name,x,z):raise OSError('COM failure')
    env['turn']['SetVariableAllowance']=fail
    r=env['apply']();assert r['status']=='uncertain' and env['calls'].count('SetVariableAllowance')==1
    assert r['completed_changes']==[] and r['setters_attempted']==2 and r['setters_returned']==1

def test_second_name_error_retains_first_completed(env):
    original=env['turn']['SetVariableAllowance']
    def setter(name,x,z):
        if name=='6':raise OSError('second COM failure')
        return original(name,x,z)
    env['turn']['SetVariableAllowance']=setter
    r=env['apply']();assert r['status']=='uncertain'
    assert [v['name'] for v in r['completed_changes']]==['5']
    assert env['entries'][5]['radial_x_native']==.2 and env['entries'][6]['radial_x_native']==0
    assert r['setters_attempted']==3 and r['setters_returned']==2

def test_current_file_changed_after_first_name_stops_second(env):
    def hook(name):
        if name=='SetVariableAllowance':env['copy'].write_bytes(b'changed externally')
    env['hook']=hook;r=env['apply']()
    assert r['status']=='uncertain' and env['calls'].count('SetVariableAllowance')==1

def test_cleanup_error_after_writes_remains_uncertain(env):
    prep=env['run']()
    def cleanup():env['session'].state['disconnect_errors']=['failed Unadvise']
    env['cleanup_hook']=cleanup
    r=env['run'](action='apply',expected_state_sha256=prep['state_sha256'],receipt_path=str(env['tmp_path']/'apply.json'))
    assert r['status']=='uncertain' and not r['scalar_readback_verified']
    assert r['setters_returned']==3 and not r['retry_attempted']

def test_new_source_sha_samebytes_guard_is_real(env):
    env['copy'].write_bytes(b'copy differs from checkpoint')
    assert env['run']()['status']=='error'
    assert not any(x.startswith('Set') for x in env['calls'])
