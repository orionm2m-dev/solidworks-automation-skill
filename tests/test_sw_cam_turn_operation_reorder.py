"""Synthetic native setup dispatch, intermediate snapshots, failure and replay tests."""
from copy import deepcopy
import json
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_turn_operation_reorder as cam


def state_for(path, digest, identity):
    ids=[127,128,129,130,133,134,135,326,327,328,329]
    kinds=[7,8,1,2,3,4,13,14,9,5,6];counts=[40,19,97,43,0,0,0,0,0,0,0]
    operations=[dict(setup_index=0,operation_index=i,native_id=oid,turn_operation_type=kinds[i],linked_feature_ids=[76 if oid>=326 else 74])for i,oid in enumerate(ids)]
    return dict(document=dict(path=str(path),title=path.name,type=1,needs_save=False),source_sha256=digest,
        copy_file_identity=identity,inventory=dict(machine_type=3,operation_count=11,operation_setup_count=1,feature_count=2,
            operations=[dict(setup_index=0,operation_index=i,turn_operation_type=kinds[i],toolpath_generated=bool(c),toolpath_record_counts=[c]if c else[])for i,c in enumerate(counts)]),
        operations=operations,features=[dict(native_id=74,attribute_id_raw=0),dict(native_id=76,attribute_id_raw=50)],
        current_attribute=dict(native_id=50,name='Rough-Finish'),current_attribute_lookup_id_raw=50,current_id_matches_lookup=True,
        catalog=dict(requested_id=50),feature_spindle_type_raw=1,stock_attribute_raw=1,feature_diameters_native=dict(minimum=52.,maximum=61.),
        own_operations=[dict(operation_native_id=x['native_id'],suppressed=False,tool_native_id=x['native_id']+100,tool=dict(tool_type_raw=15,info='tool'))for x in operations],
        nc=[dict(operation_native_id=x['native_id'],status='observed',feed_rate_ipm_native=1.,spindle_speed_native=600.)for x in operations],
        toolcrib=[dict(native_id=x['native_id']+100,info_raw='tool')for x in operations],default_operations=[dict(operation_type=5,name='Default',native_id=3,names=['Default'])])


def reorder_state(state, moving, anchor):
    old=state['operations'];byid={x['native_id']:x for x in old};paths={x['native_id']:path for x,path in zip(old,state['inventory']['operations'])}
    order=list(byid);order.remove(moving);order.insert(order.index(anchor)+1,moving)
    state['operations']=[byid[x]for x in order];state['inventory']['operations']=[paths[x]for x in order]
    for values in(state['operations'],state['inventory']['operations']):
        for i,row in enumerate(values):row['operation_index']=i
    for key in('own_operations','nc'):
        rows={x['operation_native_id']:x for x in state[key]};state[key]=[rows[x]for x in order]


@pytest.fixture
def tx(tmp_path,monkeypatch):
    source=tmp_path/'original.sldprt';target=tmp_path/'copy.sldprt';db=tmp_path/'db.cwdb'
    source.write_bytes(b'original');target.write_bytes(b'saved new source');db.write_bytes(b'recipe')
    config=dict(process_id=731,expected_process_create_time=1234.,expected_document_path=str(target),expected_source_sha256=cam._file_hash(target),
        feature_setup_index=0,expected_feature_native_id=76,expected_turn_feature_type=2,attribute_name='Rough-Finish',max_features=64,max_operations=64)
    policy=dict(protected_part_pins=[dict(path=str(source),sha256=cam._file_hash(source))],techdb_path=str(db),techdb_sha256=cam._file_hash(db),
        expected_default_operations=[dict(operation_type=5,name='Default',native_id=3)])
    identity=cam.capture.files(config,policy);state=state_for(target,config['expected_source_sha256'],identity)
    plan=dict(setup_index=0,expected_operation_ids=[x['native_id']for x in state['operations']],expected_final_order=[127,128,129,130,326,327,328,329,133,134,135],
        moves=[dict(moving_native_id=x,after_native_id=a,make_copy=False)for x,a in [(326,130),(327,326),(328,327),(329,328)]])
    args=dict(config,policy=policy,plan=plan,expected_metadata_sha256=cam._digest(state))
    calls=[];fault={'kind':None,'at':1,'reads':0};receipts=[]
    class Session:
        def __init__(self,*args):self.active=False;self.entered=False
        def __enter__(self):self.active=True;self.entered=True;return self
        def __exit__(self,*args):self.active=False
        def summary(self):return dict(active=self.active,subscribed=self.entered,disconnected=self.entered and not self.active,
            event_count=int(fault['kind']=='event'and bool(calls)or fault['kind']=='cleanup'and self.entered and not self.active),
            overflow=False,callback_error_count=0,callback_errors=[],subscription_error=None,disconnect_errors=[])
    handles={}
    for row in state['operations']:
        obj=N(native_id=row['native_id']);obj.QueryInterface=Mock(return_value=obj);handles[row['native_id']]=obj
    doc=N(GetCWObjectID=lambda obj:(obj.native_id,True));setup=N(native_id=93)
    collection=N(Count=1,Item=lambda index:setup)
    machine=N(IGetEnumOpSetups=lambda:collection)
    native=dict(doc=doc,machine=machine,operations=handles,app=N(),turn_feature=N())
    def move(moving,anchor,copy):
        assert copy is False
        intent=json.loads(receipts[-1].read_text())
        assert intent['native_dispatch_pending']is True and intent['phase']=='InsertOperationAfter'
        slot=intent['actions'][-1]
        assert slot['attempted']is True and slot['returned']is False and slot['make_copy']is False
        assert intent['move_call_count']==len(calls)+1 and len(list(tmp_path.glob('turn_reorder_*.json')))==1
        calls.append((moving.native_id,anchor.native_id,copy))
        active=len(calls)==fault['at']
        if active and fault['kind']=='exception':raise RuntimeError('dispatch interrupted')
        if not(active and fault['kind']=='no_move'):reorder_state(state,moving.native_id,anchor.native_id)
        state['document']['needs_save']=fault.get('dirty',True)
        if active:
            if fault['kind']=='nc':state['nc'][0]['feed_rate_ipm_native']=999.
            elif fault['kind']=='tool':state['own_operations'][0]['tool']['info']='changed'
            elif fault['kind']=='feature':state['features'][0]['attribute_id_raw']=1
            elif fault['kind']=='path':state['inventory']['operations'][0]['toolpath_record_counts']=[41]
            elif fault['kind']=='created':state['operations'][0]['native_id']=999
            elif fault['kind']=='source':target.write_bytes(b'changed')
            elif fault['kind']=='setup':setup.native_id=99
            elif fault['kind']=='nonzero':return 1
            elif fault['kind']=='none':return None
            elif fault['kind']=='bool':return False
            elif fault['kind']=='large':return 2**80
        return 0
    setup.InsertOperationAfter=Mock(side_effect=move)
    sw=N(GetProcessID=lambda:731,GetDocuments=lambda:[N(GetPathName=lambda:str(target))])
    process=dict(alive=True,process_id=731,create_time=1234.,executable='C:/bin/SLDWORKS.exe')
    def capture(*args,clean,check=lambda:None,**kwargs):
        check();fault['reads']+=1
        if clean:assert state['document']['needs_save']is False
        return deepcopy(state),native
    monkeypatch.setattr(cam.capture,'capture',capture)
    monkeypatch.setattr(cam.capture.recipe,'_context',lambda *args:(None,None,None,None,native['app']))
    monkeypatch.setattr(cam.capture,'_process_identity',lambda _:deepcopy(process))
    monkeypatch.setattr(cam,'CamMessageSession',Session)
    monkeypatch.setattr(cam,'document_snapshot',lambda _:deepcopy(state['document']))
    monkeypatch.setattr(cam,'_typed',lambda obj,*args:obj)
    from scripts import sw_cam_turn_feature_attribute as helper
    monkeypatch.setattr(helper,'_typed',lambda obj,*args:obj)
    monkeypatch.setattr(cam,'local_evidence_root',lambda:tmp_path)
    def invoke(action='prepare',**changes):
        opts=dict(args,action=action)
        if action=='apply':
            receipt=tmp_path/('result'+str(len(receipts))+'.json');receipts.append(receipt)
            opts.update(expected_state_sha256=prepared['prepared_state_sha256'],receipt_path=str(receipt))
        opts.update(changes)
        return cam.reorder_turn_operations(sw,'clsid','tlb',**opts)
    prepared=invoke();assert prepared['status']=='prepared',prepared
    return N(**locals())


def test_prepare_then_four_moves_strict_metadata(tx):
    t=tx;assert not t.calls and t.fault['reads']==2 and t.prepared['apply_eligible']is True
    r=t.invoke('apply');assert r['status']=='review_required' and r['order_verified'] and r['readback_verified'],r
    assert r['apply_eligible']is False
    assert t.calls==[(326,130,False),(327,326,False),(328,327,False),(329,328,False)]
    assert [x['native_id']for x in r['final_state']['operations']]==t.plan['expected_final_order']
    assert all(x['readback_verified'] and x['native_return_type']=='int' and x['native_return_value']==0 for x in r['actions'])
    for field in('model_saved','GOP_attempted','GTP_attempted','tool_assignment_attempted','operation_creation_attempted','make_copy','persistence_verified','protected_CL_bytes_compared','full_model_geometry_verified','physical_sequence_qualified','production_qualified'):
        assert r[field]is False
    assert t.source.read_bytes()==b'original' and t.target.read_bytes()==b'saved new source'
    saved=json.loads(t.receipts[-1].read_text());assert saved['final_state_sha256']==cam._digest(r['final_state'])


@pytest.mark.parametrize('at',[1,2,3,4])
@pytest.mark.parametrize('kind',['exception','nonzero','none','bool','large','no_move','nc','tool','feature','path','created','source','setup'])
def test_first_failed_step_stops_without_replay(tx,at,kind):
    t=tx;t.fault.update(kind=kind,at=at)
    r=t.invoke('apply');assert r['status']=='uncertain' and not r['readback_verified'] and not r['order_verified'],r
    assert len(t.calls)==at and r['move_call_count']==at and r['apply_eligible']is False
    assert r['actions'][-1]['returned']is (kind!='exception')
    if kind in('none','bool','nonzero','large'):
        assert 'native_return_type'in r['actions'][-1]
    if kind=='exception':assert r['native_dispatch_pending']is True
    assert all(x['readback_verified']for x in r['actions'][:-1])
    again=t.invoke('apply');assert again['status']=='error' and len(t.calls)==at


@pytest.mark.parametrize('field',['copy','duplicate','self','noop','missing','final','extra','setup','digest','pid','time','source','protected','techdb'])
def test_invalid_input_or_stale_snapshot_prevents_calls(tx,field):
    t=tx;kwargs={}
    if field=='copy':t.plan['moves'][0]['make_copy']=True
    elif field=='duplicate':t.plan['moves'][1]=deepcopy(t.plan['moves'][0])
    elif field=='self':t.plan['moves'][0]['after_native_id']=326
    elif field=='noop':t.plan['moves'][0]['after_native_id']=135
    elif field=='missing':t.plan['moves'][0]['after_native_id']=999
    elif field=='final':t.plan['expected_final_order']=t.plan['expected_final_order'][::-1]
    elif field=='extra':t.plan['new_field']=True
    elif field=='setup':t.plan['setup_index']=1
    elif field=='digest':kwargs['expected_metadata_sha256']='f'*64
    elif field=='pid':t.process['process_id']=999
    elif field=='time':t.process['create_time']=1235.
    elif field=='source':t.target.write_bytes(b'changed')
    elif field=='protected':t.source.write_bytes(b'changed')
    elif field=='techdb':t.db.write_bytes(b'changed')
    r=t.invoke('apply',**kwargs);assert r['status']=='error' and not t.calls,r


def test_false_save_flag_is_observed_without_assuming_no_change(tx):
    t=tx;t.fault['dirty']=False;r=t.invoke('apply')
    assert r['status']=='review_required' and r['final_state']['document']['needs_save']is False
    assert r['move_call_count']==4 and not r['persistence_verified']


@pytest.mark.parametrize('kind',['event','cleanup'])
def test_event_or_cleanup_invalidates_transaction(tx,kind):
    t=tx;t.fault['kind']=kind;r=t.invoke('apply')
    assert r['status']=='uncertain' and not r['readback_verified']
    assert len(t.calls)==(1 if kind=='event' else 4)


def test_dispatch_object_native_identity_guard(tx):
    t=tx;t.handles[326].QueryInterface.return_value=N(native_id=999)
    r=t.invoke('apply');assert r['status']=='error' and not t.calls
    assert list(t.tmp_path.glob('turn_reorder_*.json'))


def test_prepared_digest_includes_order_plan_and_setup_identity(tx):
    t=tx;t.setup.native_id=94
    r=t.invoke('apply');assert r['status']=='error' and not t.calls


def test_return_value_observation_does_not_call_unknown_repr():
    class Unknown:
        def __repr__(self):raise AssertionError('Must not stringify unknown native object')
    value=cam.native_return_observation(Unknown())
    assert value['native_return_type']=='Unknown' and not value['native_return_value_recorded']



def test_readonly_inspect_obtains_digest_without_consuming_marker(tx):
    t=tx;r=t.invoke('inspect',expected_metadata_sha256=None)
    assert r['status']=='inspected' and r['readback_verified'] and r['final_state_sha256']==cam._digest(t.state)
    assert not r['apply_eligible'] and not r['order_verified'] and 'prepared_state_sha256'not in r
    assert not t.calls and not list(t.tmp_path.glob('turn_reorder_*.json'))


def test_final_receipt_write_failure_clears_success(tx,monkeypatch):
    t=tx;writer=cam._write_receipt
    def fail(path,report,**kwargs):
        if report.get('status')=='review_required':raise OSError('final receipt unavailable')
        return writer(path,report,**kwargs)
    monkeypatch.setattr(cam,'_write_receipt',fail)
    r=t.invoke('apply')
    assert r['status']=='uncertain' and not r['readback_verified'] and not r['order_verified'] and 'receipt_write_error'in r
    assert len(t.calls)==4 and list(t.tmp_path.glob('turn_reorder_*.json')) and r['apply_eligible']is False
    assert t.invoke('apply')['status']=='error' and len(t.calls)==4
