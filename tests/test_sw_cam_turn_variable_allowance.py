from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import pytest

from scripts import sw_cam_turn_variable_allowance as m

@pytest.fixture
def env(monkeypatch):
    e={'calls':[],'hook':None,'digest':'a'*64,'dirty':False,'session':None}
    class Session:
        def __init__(self,*args):
            self.state=dict(active=False,subscribed=False,disconnected=False,event_count=0,overflow=False,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
            e['session']=self
        def __enter__(self): self.state.update(active=True,subscribed=True); return self
        def __exit__(self,*args): self.state.update(active=False,disconnected=True)
        def summary(self): return deepcopy(self.state)
    def collection(items): return {'Count':len(items),'Item':lambda i:items[i]}
    profile={'name':'OD','segment_count':2,'segments':[{'curve_parameters_available':True,'curve_type_raw':0,'start_native':[1,0,2],'end_native':[1,0,1]},
             {'curve_parameters_available':True,'curve_type_raw':1,'start_native':[1,0,1],'end_native':[2,0,0],'arc_native':{'radius':1}}]}
    feature={'native_id':11,'profile':profile}
    operation={'native_id':22,'OpernType':2,'Suppressed':False,'IGetAllFeatures':collection([feature]),
        'GetAllowanceMethodVariable':0,'GetAllVariableAllowances':(('segment A','segment B'),(0.,.25),(0.,0.),2,True)}
    setup={'IGetEnumOperations':collection([operation])}
    inventory={'machine_type':3,'feature_count':1,'operation_count':1,'operation_setup_count':1}
    machine={'IGetEnumOpSetups':collection([setup]),'inventory':inventory}
    cam={'context':True}; app={'tag':'app'}; addin={'GetCWApp':app}; sw={'GetProcessID':123,'GetAddInObject':lambda clsid:addin}
    def member(obj,name,*args):
        if obj is not sw and obj is not addin:
            assert e['session'] is not None and e['session'].state['active'], 'CAM getter outside event subscription: '+name
        e['calls'].append(name)
        value=obj[name]; result=value(*args) if callable(value) else deepcopy(value) if name not in ('GetCWApp','IGetEnumOpSetups','IGetEnumOperations','IGetAllFeatures','Item') else value
        if e['hook']: e['hook'](name)
        return result
    def doc(sw): return {'path':r'C:\review\part.SLDPRT','title':'part.SLDPRT','type':1,'needs_save':e['dirty']}
    def context(sw,clsid,tlb,read): read(cam,'context'); return doc(sw),{},None,machine,app
    def items(raw,tlb,read,limit=512):
        count=read(raw,'Count')
        if type(count) is not int or not 0<=count<=limit: raise ValueError('bounded count')
        return [read(raw,'Item',i) for i in range(count)]
    def read_profile(raw,tlb,read,budget,result,**kw):
        result.update(read(raw,'profile')); budget[0]+=result['segment_count']
    monkeypatch.setattr(m,'CamMessageSession',Session)
    monkeypatch.setattr(m,'solidworks_operation_lock',lambda **kw:nullcontext())
    monkeypatch.setattr(m,'_member',member); monkeypatch.setattr(m,'_typed',lambda obj,*args:obj)
    monkeypatch.setattr(m,'document_snapshot',doc); monkeypatch.setattr(m,'_context',context)
    monkeypatch.setattr(m,'_inventory',lambda obj,tlb,read:read(obj,'inventory'))
    monkeypatch.setattr(m,'_items',items); monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:read(obj,'native_id'))
    monkeypatch.setattr(m,'_read_profile',read_profile); monkeypatch.setattr(m,'_file_hash',lambda p:e['digest'])
    args=dict(process_id=123,expected_document_path=r'C:\review\part.SLDPRT',setup_index=0,operation_index=0,
        expected_operation_native_id=22,expected_operation_type=2,expected_linked_feature_ids=[11],expected_source_sha256='a'*64)
    e.update(locals())
    e['run']=lambda **kw:m.inspect_turn_variable_allowance(sw,'clsid','type-library',**dict(args,**kw))
    return e

def test_readonly_complete(env):
    r=env['run'](); assert r['status']=='ok' and r['readback_verified']
    assert r['before']==r['after'] and r['before']['selected_operation']['native_id']==22
    assert r['before']['allowances']['entries'][1]['radial_x_native']==.25
    assert env['calls'].count('GetAllVariableAllowances')==2
    assert not r['mutation_attempted'] and not r['GTP_attempted'] and not r['model_saved']
    assert not r['units_verified'] and not r['name_to_geometry_mapping_verified']
    assert not any(name.startswith('Set') or name in ('Thickness','GetUnitRecordParam','GetRecordAtIndex') for name in env['calls'])
    assert r['messages']['disconnected'] and not r['messages']['active']

def test_unsaved_ram_explicitly_marked(env):
    env['dirty']=True
    r=env['run'](); assert r['status']=='ok' and r['unsaved_memory_present'] is True

@pytest.mark.parametrize('raw',[
 None,(),((),(),(),0),((),(),(),0,1),(None,None,None,0,False),
 (('a',),(0,),(0,),True,True),(('a',),(0,),(0,),513,True),
 (('a',),(0,),(),1,True),(('a','a'),(0,0),(0,0),2,True),
 (('',),(0,),(0,),1,True),(('a\n',),(0,),(0,),1,True),(('a',),(True,),(0,),1,True),
 (('a',),(float('nan'),),(0,),1,True),(('a',),(0,),(float('inf'),),1,True),
 (('a',),('0',),(0,),1,True),('a',(0,),(0,),1,True),
 (('a',),(0,),(0,),-1,True)])
def test_array_contract_rejects(raw):
    with pytest.raises(ValueError): m._allowances(raw)

@pytest.mark.parametrize('raw',[((),(),(),0,True),(('a',),(2,),(-.5,),1,True),(['x','y'],[0.,-1.],[1.,0.],2,True)])
def test_array_contract_accepts_raw_values_only(raw):
    r=m._allowances(raw); assert r['native_success'] and not r['units_verified']
    assert r['segment_count']==raw[3]

@pytest.mark.parametrize('field,value',[
 ('process_id',True),('setup_index',-1),('operation_index',512),('expected_operation_native_id',0),
 ('expected_operation_type',4),('expected_operation_type',True),('expected_document_path','part.SLDPRT'),
 ('expected_source_sha256','X'*64),('expected_linked_feature_ids',[]),('expected_linked_feature_ids',[11,11]),
 ('expected_linked_feature_ids',[True]),('message_policy','auto_accept')])
def test_input_gates_before_calls(env,field,value):
    r=env['run'](**{field:value}); assert r['status']=='error' and not env['calls']

@pytest.mark.parametrize('field,value',[('native_id',999),('OpernType',1),('Suppressed',1)])
def test_operation_identity_gate(env,field,value):
    env['operation'][field]=value
    r=env['run'](); assert r['status']=='error' and 'GetAllVariableAllowances' not in env['calls']

def test_feature_identity_gate(env):
    env['feature']['native_id']=99
    r=env['run'](); assert r['status']=='error' and 'GetAllVariableAllowances' not in env['calls'] and 'profile' not in env['calls']

def test_incomplete_profile_stops_before_new_getters(env):
    env['profile']['segments'][0]['curve_parameters_available']=False
    r=env['run'](); assert r['status']=='error' and 'GetAllowanceMethodVariable' not in env['calls']

@pytest.mark.parametrize('mode',[True,0.0,'1',2**31])
def test_exact_mode_type(env,mode):
    env['operation']['GetAllowanceMethodVariable']=mode
    r=env['run'](); assert r['status']=='error' and 'GetAllVariableAllowances' not in env['calls']

@pytest.mark.parametrize('getter',['context','Count','Item','native_id','profile','GetAllowanceMethodVariable','GetAllVariableAllowances'])
def test_first_event_stops_all_subsequent_cam_getters(env,getter):
    def hook(name):
        if name==getter: env['session'].state['event_count']=1
    env['hook']=hook
    r=env['run'](); assert r['status']=='error' and not r['readback_verified']
    assert env['calls'][-1]==getter
    assert r['messages']['disconnected']

def test_return_false_no_retry(env):
    env['operation']['GetAllVariableAllowances']=(None,None,None,None,False)
    r=env['run'](); assert r['status']=='error'
    assert env['calls'].count('GetAllVariableAllowances')==1

def test_changed_allowance_between_snapshots(env):
    calls=[0]
    def hook(name):
        if name=='GetAllVariableAllowances':
            calls[0]+=1
            if calls[0]==1: env['operation']['GetAllVariableAllowances']=(('segment A','segment B'),(.1,.25),(0.,0.),2,True)
    env['hook']=hook
    r=env['run'](); assert r['status']=='error' and not r['readback_verified']

def test_source_changed_after_getter(env):
    def hook(name):
        if name=='GetAllVariableAllowances': env['digest']='b'*64
    env['hook']=hook
    r=env['run'](); assert r['status']=='error'
    assert env['calls'].count('GetAllVariableAllowances')==1

def test_dirty_state_changed_after_getter(env):
    def hook(name):
        if name=='GetAllVariableAllowances': env['dirty']=True
    env['hook']=hook
    r=env['run'](); assert r['status']=='error'

def test_rough_operation_uses_supported_route(env):
    env['operation']['OpernType']=1
    r=env['run'](expected_operation_type=1); assert r['status']=='ok'


@pytest.mark.parametrize('getter',['GetAllowanceMethodVariable','GetAllVariableAllowances'])
def test_native_new_getter_error_preserves_profile(env,getter):
    def failed(): raise OSError('native getter failure')
    env['operation'][getter]=failed
    r=env['run']()
    assert r['status']=='error' and not r['readback_verified']
    assert r['before']['capture_complete'] is False
    assert r['before']['selected_operation']['native_id']==22
    assert r['before']['linked_features'][0]['native_id']==11
    assert r['before']['linked_features'][0]['profile']['segment_count']==2
    if getter=='GetAllVariableAllowances': assert r['before']['variable_mode_native']==0
    assert env['calls'].count(getter)==1 and env['calls'][-1]==getter
    assert r['messages']['disconnected']


@pytest.mark.parametrize('pinned_id',[None,22])
def test_identify_never_reads_profile_inventory_tools_or_allowances(env,monkeypatch,pinned_id):
    def trap(*a,**kw): raise AssertionError('Forbidden getter in identity-only mode')
    monkeypatch.setattr(m,'_inventory',trap)
    monkeypatch.setattr(m,'_read_profile',trap)
    for name in ('GetAllowanceMethodVariable','GetAllVariableAllowances','IGetTool','GetIsLicensed','Thickness'):
        env['operation'][name]=trap
    r=env['run'](action='identify',expected_operation_native_id=pinned_id,expected_linked_feature_ids=None)
    assert r['status']=='ok' and r['readback_verified'] and not r['may_continue']
    assert r['inspection_scope']=='identity_only'
    assert r['before']==r['after']
    assert r['before']['selected_operation']['native_id']==22
    assert r['before']['selected_operation']['linked_feature_ids']==[11]
    assert 'inventory' not in r['before'] and 'allowances' not in r['before']
    assert not r['before']['linked_features']
    assert env['calls'].count('native_id')==4
    assert not set(env['calls']) & {'profile','GetAllowanceMethodVariable','GetAllVariableAllowances','IGetTool','Thickness'}
    assert r['messages']['disconnected'] and not r['messages']['active']

@pytest.mark.parametrize('field',['expected_operation_native_id','expected_linked_feature_ids'])
def test_default_strict_read_still_requires_both_expected_id_sets(env,field):
    r=env['run'](**{field:None})
    assert r['status']=='error' and not env['calls']

@pytest.mark.parametrize('change',[{'action':'unknown'},{'action':'identify'},
    {'action':'identify','expected_operation_native_id':True,'expected_linked_feature_ids':None}])
def test_identify_scope_validation_before_native(env,change):
    r=env['run'](**change)
    assert r['status']=='error' and not env['calls']

def test_identify_optional_pinned_operation_id_remains_enforced(env):
    r=env['run'](action='identify',expected_operation_native_id=99,expected_linked_feature_ids=None)
    assert r['status']=='error' and 'IGetAllFeatures' not in env['calls']

def test_identify_changed_linked_ids_fail_second_capture(env):
    count=[0]
    def hook(name):
        if name=='native_id':
            count[0]+=1
            if count[0]==2: env['feature']['native_id']=99
    env['hook']=hook
    r=env['run'](action='identify',expected_linked_feature_ids=None)
    assert r['status']=='error' and not r['readback_verified']
    assert r['before']['selected_operation']['linked_feature_ids']==[11]
    assert r['after']['selected_operation']['linked_feature_ids']==[99]
    assert 'profile' not in env['calls']

def test_identify_empty_links_are_reported_without_claiming_allowance_read(env):
    env['operation']['IGetAllFeatures']={'Count':0}
    r=env['run'](action='identify',expected_linked_feature_ids=None)
    assert r['status']=='ok' and r['before']['selected_operation']['linked_feature_ids']==[]
    assert 'allowances' not in r['before']

@pytest.mark.parametrize('condition',['event','file','dirty'])
def test_identify_stops_on_event_or_document_file_change(env,condition):
    def hook(name):
        if name=='native_id':
            if condition=='event': env['session'].state['event_count']=1
            elif condition=='file': env['digest']='b'*64
            else: env['dirty']=True
    env['hook']=hook
    r=env['run'](action='identify',expected_linked_feature_ids=None)
    assert r['status']=='error' and not r['readback_verified']
    assert r['messages']['disconnected']
    if condition=='event': assert env['calls'][-1]=='native_id'
    assert 'profile' not in env['calls'] and 'GetAllVariableAllowances' not in env['calls']
