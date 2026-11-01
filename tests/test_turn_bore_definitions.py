import os,sys,importlib.util,json
from pathlib import Path
from copy import deepcopy
import pytest
root=os.environ.get('SOLIDWORKS_SKILL_ROOT')
if root:sys.path.insert(0,root)
spec=importlib.util.spec_from_file_location('turn_bore_definitions_test',Path(__file__).parents[1]/'scripts/sw_cam_turn_bore_definitions.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def event_ok():return dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


def state():
    types=[7,8,1,2,14,9,3,4,13];counts=[[40],[19],[97],[43],[],[],[],[],[]]
    operations=[dict(setup_index=0,operation_index=i,native_id=100+i,turn_operation_type=t,linked_feature_ids=[76 if i==5 else 20+i],suppressed=False) for i,t in enumerate(types)]
    inventory=dict(machine_type=3,feature_setup_count=1,feature_counts_by_setup=[5],feature_count=5,operation_setup_count=1,operation_count=9,operations=[dict(setup_index=0,operation_index=i,turn_operation_type=t,toolpath_generated=bool(counts[i]),toolpath_record_counts=counts[i]) for i,t in enumerate(types)],stock=dict(type=3))
    return dict(document=dict(path='part.SLDPRT',title='part',type=1,needs_save=False),saved_file_sha256='a'*64,inventory=inventory,operations=operations,feature_ids=[dict(setup_index=0,native_ids=[20,21,22,76,24])],feature_header=dict(turn_feature_type_raw=2,name='Bore',attribute_id_raw=0,attribute_name='Drill'))


def request(tmp_path):return dict(process_id=7,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,feature_native_id=76,anchor_operation_native_id=105,definitions=[dict(operation_type=1,default_name='Default',default_operation_id=1),dict(operation_type=2,default_name='Default',default_operation_id=2)],receipt_path=str(tmp_path/'result.json'))


def catalogue(s,p):
    before=dict(operation_native_id=105,feature_native_id=76,operation_type=9,suppressed=False,generated=False,feature_header=deepcopy(s['feature_header']))
    c=dict(scope=m.catalogue.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,process_id=7,source_path=p['expected_document_path'],source_sha256='a'*64,before=before,after=deepcopy(before),inventory_before=deepcopy(s['inventory']),inventory_after=deepcopy(s['inventory']),request=dict(setup_index=0,operation_index=5),messages=event_ok(),catalogues={str(k):dict(entries=[dict(name='Default',default_operation_id=k)]) for k in (1,2)})
    c.update({k:False for k in ('mutation_attempted','GTP_attempted','model_saved','operation_inserted','attribute_changed')});return c


def insert_state(s,kind,new_id,anchor_id):
    t=deepcopy(s);ai=next(i for i,x in enumerate(t['operations']) if x['native_id']==anchor_id);oi=t['operations'][ai]['operation_index']+1
    for x in t['operations'][ai+1:]:x['operation_index']+=1
    t['operations'].insert(ai+1,dict(setup_index=0,operation_index=oi,native_id=new_id,turn_operation_type=kind,linked_feature_ids=[76],suppressed=False))
    for x in t['inventory']['operations'][ai+1:]:x['operation_index']+=1
    t['inventory']['operations'].insert(ai+1,dict(setup_index=0,operation_index=oi,turn_operation_type=kind,toolpath_generated=False,toolpath_record_counts=[]));t['inventory']['operation_count']+=1;t['document']['needs_save']=True;return t


def test_exact_default_specs():m.validate_specs(request(Path('/tmp'))['definitions'])
@pytest.mark.parametrize('value',[[],[dict(operation_type=1,default_name='Default',default_operation_id=1)],'pair',None])
def test_wrong_pair_rejected(value):
    with pytest.raises(ValueError):m.validate_specs(value)
@pytest.mark.parametrize('field,value',[('operation_type',True),('operation_type',2),('default_name',''),('default_operation_id',False),('default_operation_id',0)])
def test_invalid_spec_rejected(field,value):
    s=request(Path('/tmp'))['definitions'];s[0][field]=value
    with pytest.raises(ValueError):m.validate_specs(s)


def test_catalogue_exact_source_feature_defaults(tmp_path):
    s=state();p=request(tmp_path);c=catalogue(s,p);assert m.validate_catalogue(c,p)==c['before'];m.verify_before(s,c,p)
@pytest.mark.parametrize('field,value',[('status','uncertain'),('readback_verified',False),('process_id',8),('source_sha256','b'*64),('GTP_attempted',True)])
def test_catalogue_wrong_authority_rejected(tmp_path,field,value):
    p=request(tmp_path);c=catalogue(state(),p);c[field]=value
    with pytest.raises(ValueError):m.validate_catalogue(c,p)
def test_unobserved_default_rejected(tmp_path):
    p=request(tmp_path);c=catalogue(state(),p);p['definitions'][0]['default_operation_id']=9
    with pytest.raises(ValueError):m.validate_catalogue(c,p)
def test_existing_definition_blocks_new_pair(tmp_path):
    s=state();p=request(tmp_path);c=catalogue(s,p);s['operations'][2]['linked_feature_ids']=[76]
    with pytest.raises(ValueError):m.verify_before(s,c,p)


@pytest.mark.parametrize('kind',(1,2))
def test_exact_insert_delta_preserves_four_streams(kind):
    a=state();b=insert_state(a,kind,201,105);assert m.verify_added(a,b,201,kind,76,105)['native_id']==201
@pytest.mark.parametrize('bad',['old_path','stock','feature','header','wrong_type','wrong_link','suppressed','new_path','duplicate','wrong_anchor','source'])
def test_other_deltas_rejected(bad):
    a=state();b=insert_state(a,1,201,105)
    if bad=='old_path':b['inventory']['operations'][0]['toolpath_record_counts']=[999]
    if bad=='stock':b['inventory']['stock']['type']=4
    if bad=='feature':b['feature_ids'][0]['native_ids'].append(90)
    if bad=='header':b['feature_header']['attribute_name']='Turn'
    if bad=='wrong_type':b['operations'][6]['turn_operation_type']=2
    if bad=='wrong_link':b['operations'][6]['linked_feature_ids']=[77]
    if bad=='suppressed':b['operations'][6]['suppressed']=True
    if bad=='new_path':b['inventory']['operations'][6]['toolpath_generated']=True
    if bad=='duplicate':b['operations'][6]['native_id']=105
    if bad=='wrong_anchor':b['operations'][6]['operation_index']=7
    if bad=='source':b['saved_file_sha256']='b'*64
    with pytest.raises(ValueError):m.verify_added(a,b,201,1,76,105)


def fake_run(tmp_path,*,fail=None):
    p=request(tmp_path);s=state();s['document']['path']=p['expected_document_path'];c=catalogue(s,p);trace=[]
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',request=p,process_id=7,source_path=p['expected_document_path'],initial_source_sha256='a'*64,actions={},native_dispatch_pending=False,mutation_attempted=False,readback_verified=False,model_saved=False,**{k:False for k in m.FORBIDDEN})
    plan=dict(catalogue=c,marker=tmp_path/'marker.json')
    def persist():Path(p['receipt_path']).write_text(json.dumps(r))
    class Backend:
        current=deepcopy(s);insert_count=0
        def start(self):trace.append('start')
        def capture(self,label):
            trace.append(label)
            if fail==label:raise ValueError('capture failure')
            t=deepcopy(self.current)
            if fail=='drift_after_first' and label=='InsertOperation_1_readback':t['inventory']['operations'][0]['toolpath_record_counts']=[999]
            if fail=='saved_drift' and label=='saved':t['feature_header']['attribute_name']='different'
            return t
        def catalogue_check(self):trace.append('catalogue')
        def boundary(self):pass
        def insert(self,spec,anchor,pending):
            pending();label='insert'+str(spec['operation_type']);trace.append(label)
            assert plan['marker'].exists() and json.loads(Path(p['receipt_path']).read_text())['actions']['InsertOperation_'+str(spec['operation_type'])]['pending'] is True
            if fail==label:raise RuntimeError('native outcome unknown')
            self.insert_count+=1;oid=200+self.insert_count;self.current=insert_state(self.current,spec['operation_type'],oid,anchor);return oid
        def save(self):
            trace.append('save');assert json.loads(Path(p['receipt_path']).read_text())['actions']['SaveActiveDocument']['pending'] is True
            if fail=='save_hresult':return False
            self.current['document']['needs_save']=False;self.current['saved_file_sha256']='b'*64;return 0
        def saved_hash(self):return self.current['saved_file_sha256']
        def finish(self):trace.append('finish');r['messages']=event_ok()
        def close(self):trace.append('close');r['messages']=event_ok()
    return lambda:m.run_backend(Backend(),p,plan,r,persist),r,trace,plan


def test_pair_then_one_save_no_gtp(tmp_path):
    call,r,trace,plan=fake_run(tmp_path);out=call();assert out['status']=='saved_definitions_no_toolpath' and out['readback_verified'] and out['model_saved']
    assert trace==['start','before','catalogue','insert1','InsertOperation_1_readback','insert2','InsertOperation_2_readback','save','saved','finish','close']
    assert out['final_state']['inventory']['operation_count']==11 and all(out[k] is False for k in m.FORBIDDEN)
    assert m.validate_saved(out)==out['final_state'] and [x['native_id'] for x in out['new_operations']]==[201,202]
@pytest.mark.parametrize('failure,expected_inserts',[('before',0),('insert1',1),('InsertOperation_1_readback',1),('drift_after_first',1),('insert2',2),('InsertOperation_2_readback',2)])
def test_partial_stops_without_save_or_repeat(tmp_path,failure,expected_inserts):
    call,r,trace,_=fake_run(tmp_path,fail=failure);call();assert not r['readback_verified'] and 'save' not in trace
    assert trace.count('insert1')+trace.count('insert2')==expected_inserts and trace[-1]=='close'
@pytest.mark.parametrize('failure',['save_hresult','saved_drift'])
def test_failed_save_or_readback_is_not_completed(tmp_path,failure):
    call,r,trace,_=fake_run(tmp_path,fail=failure);call();assert not r['readback_verified'] and trace.count('save')==1
    with pytest.raises(ValueError):m.validate_saved(r)
def test_existing_marker_prevents_first_native_payload(tmp_path):
    call,r,trace,plan=fake_run(tmp_path);plan['marker'].write_text('{}');call();assert 'insert1' not in trace and 'save' not in trace and not r['readback_verified']
def test_saved_authority_never_allows_gtp(tmp_path):
    call,r,trace,_=fake_run(tmp_path);call();r['GTP_attempted']=True
    with pytest.raises(ValueError):m.validate_saved(r)

@pytest.mark.parametrize('field,value',[('default_operation_id',9),('default_name','Other')])
def test_completed_loader_rechecks_original_catalogue(tmp_path,monkeypatch,field,value):
    call,r,trace,plan=fake_run(tmp_path);call();r['request']['definitions'][0][field]=value
    r['catalogue_pin']={'path':str(tmp_path/'catalogue.json'),'sha256':'c'*64}
    def read(path,digest):return (plan['catalogue'],{}) if str(path).endswith('catalogue.json') else (r,{})
    monkeypatch.setattr(m,'read_pin',read)
    with pytest.raises(ValueError,match='Requested default'):m.load_completed(str(tmp_path/'result.json'),'d'*64,process_id=7,expected_document_path=r['source_path'],expected_source_sha256='b'*64)


@pytest.mark.parametrize('change',['action_id','source_transition'])
def test_completed_authority_checks_recorded_actions(tmp_path,change):
    call,r,trace,plan=fake_run(tmp_path);call()
    if change=='action_id':r['actions']['InsertOperation_1']['new_native_id']=999
    else:r['source_transition']['source_after_sha256']='c'*64
    with pytest.raises(ValueError):m.validate_saved(r)
