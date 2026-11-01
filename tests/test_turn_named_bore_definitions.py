import os,sys,importlib.util,json
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT')
if root:sys.path.insert(0,root)
spec=importlib.util.spec_from_file_location('named_bore_test',Path(__file__).parents[1]/'scripts/sw_cam_turn_named_bore_definitions.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def event_ok():return dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


def state():
    types=[7,8,1,2,14,9,3,4,13];counts=[[40],[19],[97],[43],[],[],[],[],[]]
    operations=[dict(setup_index=0,operation_index=i,native_id=100+i,turn_operation_type=t,linked_feature_ids=[76 if i==5 else 20+i],suppressed=False) for i,t in enumerate(types)]
    inventory=dict(machine_type=3,feature_setup_count=1,feature_counts_by_setup=[5],feature_count=5,operation_setup_count=1,operation_count=9,operations=[dict(setup_index=0,operation_index=i,turn_operation_type=t,toolpath_generated=bool(counts[i]),toolpath_record_counts=counts[i]) for i,t in enumerate(types)],stock=dict(type=3))
    return dict(document=dict(path='part.SLDPRT',title='part',type=1,needs_save=False),saved_file_sha256='a'*64,inventory=inventory,operations=operations,feature_ids=[dict(setup_index=0,native_ids=[20,21,22,76,24])],feature_header=dict(turn_feature_type_raw=2,name='Bore',attribute_id_raw=0,attribute_name='Drill'))


def insert_state(s,kind,new_id,anchor_id):
    t=deepcopy(s);ai=next(i for i,x in enumerate(t['operations']) if x['native_id']==anchor_id);oi=t['operations'][ai]['operation_index']+1
    for x in t['operations'][ai+1:]:x['operation_index']+=1
    t['operations'].insert(ai+1,dict(setup_index=0,operation_index=oi,native_id=new_id,turn_operation_type=kind,linked_feature_ids=[76],suppressed=False))
    for x in t['inventory']['operations'][ai+1:]:x['operation_index']+=1
    t['inventory']['operations'].insert(ai+1,dict(setup_index=0,operation_index=oi,turn_operation_type=kind,toolpath_generated=False,toolpath_record_counts=[]));t['inventory']['operation_count']+=1;t['document']['needs_save']=True;return t



def resolved(rough=5,finish=6):
    return m.roles.resolve_roles(SimpleNamespace(CW_TURN_OP_ROUGH_BORE=rough,CW_TURN_OP_FINISH_BORE=finish,CW_TURN_OP_ROUGH_TURN=1,CW_TURN_OP_FINISH_TURN=2),list(m.roles.ROLE_SYMBOLS))


def request(tmp_path):
    return dict(process_id=7,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,feature_native_id=76,anchor_operation_native_id=105,definitions=[dict(role='rough_bore',default_name='Default',default_operation_id=3),dict(role='finish_bore',default_name='Default',default_operation_id=4)],receipt_path=str(tmp_path/'result.json'))


def catalogue(s,p,rs):
    before=dict(operation_native_id=105,feature_native_id=76,operation_type=9,suppressed=False,generated=False,feature_header=deepcopy(s['feature_header']))
    obs=[];cats={}
    for spec,d in zip(rs,p['definitions']):
        role=spec['role'];obs.extend([dict(key=role+'_names',value=['Default'],returned_type='tuple'),dict(key=role+'_id_Default',value=d['default_operation_id'],returned_type='int')])
        cats[role]=dict(spec,operation_type=1,converted_python_type='tuple',entries=[dict(name='Default',default_operation_id=d['default_operation_id'])],unique_default_available=True,selected_default_operation_id=None,selection_performed=False)
    r=dict(scope=m.roles.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,source_path=p['expected_document_path'],source_sha256='a'*64,before=before,after=deepcopy(before),inventory_before=deepcopy(s['inventory']),inventory_after=deepcopy(s['inventory']),request=dict(process_id=7,setup_index=0,operation_index=5,roles=list(m.roles.ROLE_SYMBOLS)),messages=event_ok(),abi=dict(roles=rs),observations=obs,catalogues=cats)
    r.update({k:False for k in ('mutation_attempted','GTP_attempted','model_saved','operation_inserted','assignment_attempted')});return r


def reference(oid):return dict(operation_native_id=oid,tool_native_id=oid+1000,tool_type_raw=15,turn_tool_type_raw=1,insert_type_raw=1,holder_type_raw=2,holder_id_raw=2)


def fake_run(tmp_path,*,fail=None,kinds=(5,6)):
    p=request(tmp_path);s=state();s['document']['path']=p['expected_document_path'];rs=resolved(*kinds);c=catalogue(s,p,rs);trace=[]
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',request=p,process_id=7,source_path=p['expected_document_path'],source_sha256='a'*64,actions={},native_dispatch_pending=False,mutation_attempted=False,readback_verified=False,**{k:False for k in m.FORBIDDEN})
    plan=dict(catalogue=c,roles=rs,marker=tmp_path/'marker.json')
    def persist():Path(p['receipt_path']).write_text(json.dumps(r))
    class Backend:
        current=deepcopy(s);insert_count=0;tool_calls=0
        def start(self):trace.append('start')
        def capture(self,label):
            trace.append(label)
            if fail==label:raise RuntimeError('capture failed')
            value=deepcopy(self.current)
            if fail=='drift_after_first' and label=='InsertOperation_rough_bore_readback':value['inventory']['operations'][0]['toolpath_record_counts']=[999]
            return value
        def catalogue_check(self):trace.append('catalogue')
        def insert(self,spec,anchor,pending):
            pending();label='insert'+str(spec['operation_type']);trace.append(label)
            assert plan['marker'].exists() and json.loads(Path(p['receipt_path']).read_text())['native_dispatch_pending'] is True
            if fail==label:raise RuntimeError('native outcome unknown')
            self.insert_count+=1;oid=200+self.insert_count;self.current=insert_state(self.current,spec['operation_type'],oid,anchor)
            if fail=='wrong_turn_type' and self.insert_count==1:
                self.current['operations'][6]['turn_operation_type']=1;self.current['inventory']['operations'][6]['turn_operation_type']=1
            return oid
        def assigned(self,oid):
            trace.append('tool'+str(oid));self.tool_calls+=1
            if fail=='tool'+str(oid):raise RuntimeError('IGetTool unavailable')
            value=reference(oid)
            if fail=='final_first_tool_drift' and self.tool_calls==3:value['tool_native_id']+=1
            if fail=='final_second_tool_drift' and self.tool_calls==4:value['tool_native_id']+=1
            if fail=='wrong_holder' and oid==201:value['holder_type_raw']=1
            if fail=='zero_tool' and oid==201:value['tool_native_id']=0
            return value
        def finish(self):trace.append('finish');r['messages']=event_ok()
        def close(self):trace.append('close');r['messages']=event_ok()
        def save(self):raise AssertionError('Save forbidden')
    return lambda:m.run_backend(Backend(),p,plan,r,persist),r,trace,plan


def test_named_pair_with_both_immediate_tool_gates_no_save(tmp_path):
    call,r,trace,plan=fake_run(tmp_path);call()
    assert r['status']=='created_bore_pair_ram_no_save' and r['readback_verified']
    assert trace==['start','before','catalogue','insert5','InsertOperation_rough_bore_readback','tool201','insert6','InsertOperation_finish_bore_readback','tool202','tool201','tool202','after','finish','close']
    assert all(r[k] is False for k in m.FORBIDDEN)
    assert m.validate_created(r,plan['catalogue'],plan['roles'])==r['after']
    assert r['after']['inventory']['operation_count']==11
    assert [x['toolpath_record_counts'] for x in r['after']['inventory']['operations'][:4]]==[[40],[19],[97],[43]]


def test_declared_sentinel_roles_are_used_for_native_arguments(tmp_path):
    call,r,trace,plan=fake_run(tmp_path,kinds=(105,106));call()
    assert r['readback_verified'] and 'insert105' in trace and 'insert106' in trace
    assert [x['turn_operation_type'] for x in r['new_operations']]==[105,106]

@pytest.mark.parametrize('fail,insert_count',[('before',0),('insert5',1),('InsertOperation_rough_bore_readback',1),('drift_after_first',1),('wrong_turn_type',1),('tool201',1),('wrong_holder',1),('zero_tool',1),('insert6',2),('tool202',2),('final_first_tool_drift',2),('final_second_tool_drift',2),('after',2)])
def test_partial_or_unknown_stops_without_next_insert_or_save(tmp_path,fail,insert_count):
    call,r,trace,plan=fake_run(tmp_path,fail=fail);call()
    assert not r['readback_verified'] and not r['model_saved']
    assert sum(x.startswith('insert') for x in trace)==insert_count and trace[-1]=='close'
    with pytest.raises(ValueError):m.validate_created(r,plan['catalogue'],plan['roles'])


def test_marker_prevents_replay_before_insert(tmp_path):
    call,r,trace,plan=fake_run(tmp_path);plan['marker'].write_text('{}');call()
    assert not any(x.startswith('insert') for x in trace) and not r['readback_verified']


def test_marker_does_not_change_with_default_candidate(tmp_path):
    p=request(tmp_path);a=m.marker_path(p);p['definitions'][0]['default_operation_id']=333
    assert m.marker_path(p)==a

@pytest.mark.parametrize('role',['rough_turn','finish_turn',1,5,True])
def test_wrong_role_or_numeric_type_is_rejected(tmp_path,role):
    specs=request(tmp_path)['definitions'];specs[0]['role']=role
    with pytest.raises(ValueError):m.validate_specs(specs)

@pytest.mark.parametrize('field,value',[('default_operation_id',False),('default_operation_id',0),('default_name','')])
def test_invalid_default_rejected(tmp_path,field,value):
    specs=request(tmp_path)['definitions'];specs[0][field]=value
    with pytest.raises(ValueError):m.validate_specs(specs)

@pytest.mark.parametrize('bad',['old_path','stock','feature','header','wrong_type','wrong_link','suppressed','new_path','duplicate','wrong_anchor','source'])
def test_exact_delta_rejects_other_changes(bad):
    a=state();b=insert_state(a,5,201,105)
    if bad=='old_path':b['inventory']['operations'][0]['toolpath_record_counts']=[999]
    if bad=='stock':b['inventory']['stock']['type']=4
    if bad=='feature':b['feature_ids'][0]['native_ids'].append(90)
    if bad=='header':b['feature_header']['attribute_name']='Turn'
    if bad=='wrong_type':b['operations'][6]['turn_operation_type']=1
    if bad=='wrong_link':b['operations'][6]['linked_feature_ids']=[77]
    if bad=='suppressed':b['operations'][6]['suppressed']=True
    if bad=='new_path':b['inventory']['operations'][6]['toolpath_generated']=True
    if bad=='duplicate':b['operations'][6]['native_id']=105
    if bad=='wrong_anchor':b['operations'][6]['operation_index']=7
    if bad=='source':b['saved_file_sha256']='b'*64
    with pytest.raises(ValueError):m.verify_added(a,b,201,'rough_bore',76,105,resolved())

@pytest.mark.parametrize('field,value',[('status','uncertain'),('readback_verified',False),('source_sha256','b'*64),('GTP_attempted',True)])
def test_wrong_catalogue_authority_rejected(tmp_path,field,value):
    p=request(tmp_path);r=catalogue(state(),p,resolved());r[field]=value
    with pytest.raises(ValueError):m.validate_catalogue(r,p,resolved())


def test_legacy_payload_one_does_not_control_insert_type(tmp_path):
    p=request(tmp_path);r=catalogue(state(),p,resolved());n=m.validate_catalogue(r,p,resolved())
    assert [n[x]['operation_type'] for x in m.roles.ROLE_SYMBOLS]==[5,6]
    assert [n[x]['entries'][0]['default_operation_id'] for x in m.roles.ROLE_SYMBOLS]==[3,4]


def test_default_not_observed_is_rejected(tmp_path):
    p=request(tmp_path);r=catalogue(state(),p,resolved());p['definitions'][0]['default_operation_id']=8
    with pytest.raises(ValueError):m.validate_catalogue(r,p,resolved())

@pytest.mark.parametrize('kind',[1,2,5,6])
def test_existing_target_definition_prohibits_repeat(tmp_path,kind):
    p=request(tmp_path);s=state();r=catalogue(s,p,resolved());s['operations'][2].update(turn_operation_type=kind,linked_feature_ids=[76])
    with pytest.raises(ValueError):m.verify_before(s,r,p,resolved())

@pytest.mark.parametrize('field,value',[('holder_type_raw',1),('tool_native_id',0),('tool_type_raw',False),('turn_tool_type_raw',2),('insert_type_raw',2)])
def test_reference_requires_actual_boring_insert_holder(field,value):
    r=reference(201);r[field]=value
    with pytest.raises(ValueError):m.validate_reference(r,201)

@pytest.mark.parametrize('bad',['tool','default','save','action','after'])
def test_completed_ram_loader_validation_rejects_tamper(tmp_path,bad):
    call,r,_,plan=fake_run(tmp_path);call()
    if bad=='tool':r['verified_tool_references'][0]['holder_type_raw']=1
    elif bad=='default':r['request']['definitions'][0]['default_operation_id']=99
    elif bad=='save':r['model_saved']=True
    elif bad=='action':r['actions']['InsertOperation_rough_bore']['new_native_id']=999
    elif bad=='after':r['after']['saved_file_sha256']='b'*64
    with pytest.raises(ValueError):m.validate_created(r,plan['catalogue'],plan['roles'])



def load_fixture(monkeypatch,tmp_path,*,bad=None):
    p=request(tmp_path);p.update(catalogue_receipt_path=str(tmp_path/'raw.json'),catalogue_receipt_sha256='c'*64,producer_archive_path=str(tmp_path/'archive.py'),producer_archive_sha256='b'*64)
    raw=catalogue(state(),p,resolved());raw['request'].update(module_sha256='b'*64,generated_path=str(tmp_path/'binding.py'),generated_sha256='d'*64,typelib_path='metadata')
    old=dict(path=str(tmp_path/Path(m.roles.__file__).name),sha256='b'*64);third=dict(path=str(tmp_path/'other_reader.py'),sha256='e'*64);raw['runtime_and_evidence_pins']=[old,third]
    if bad=='missing_old':raw['runtime_and_evidence_pins']=[third]
    if bad=='duplicate_old':raw['runtime_and_evidence_pins'].append(deepcopy(old))
    if bad=='old_sha':old['sha256']='0'*64
    if bad=='request_sha':raw['request']['module_sha256']='0'*64
    checks=[]
    monkeypatch.setattr(m,'read_pin',lambda *a:(raw,dict(path=p['catalogue_receipt_path'],sha256=p['catalogue_receipt_sha256'])))
    def pin(path):
        name=Path(path).name
        return dict(path=str(path),sha256=('0'*64 if bad=='archive_sha' else 'b'*64) if name=='archive.py' else 'd'*64 if name=='binding.py' else 'f'*64)
    monkeypatch.setattr(m.common,'_pin',pin)
    def check(pins):
        checks.extend(pins)
        if bad=='third_changed':raise ValueError('retained dependency changed')
    monkeypatch.setattr(m.common,'_check',check)
    monkeypatch.setattr(m.roles,'audit',lambda *a:dict(roles=resolved()))
    monkeypatch.setattr(m,'_file_hash',lambda _:'a'*64)
    return p,checks


def test_historical_producer_is_only_retired_pin(monkeypatch,tmp_path):
    p,checks=load_fixture(monkeypatch,tmp_path);plan=m.load_catalogue(p)
    assert [Path(x['path']).name for x in checks]==['other_reader.py']
    assert any(Path(x['path']).name=='archive.py' and x['sha256']=='b'*64 for x in plan['pins'])
    assert [plan['normalized_catalogues'][x]['operation_type'] for x in m.roles.ROLE_SYMBOLS]==[5,6]

@pytest.mark.parametrize('bad',['missing_old','duplicate_old','old_sha','request_sha','archive_sha','third_changed'])
def test_historical_normalization_does_not_weaken_other_pins(monkeypatch,tmp_path,bad):
    p,_=load_fixture(monkeypatch,tmp_path,bad=bad)
    with pytest.raises(ValueError):m.load_catalogue(p)
