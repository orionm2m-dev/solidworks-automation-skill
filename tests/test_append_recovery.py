"""Scoped append recovery tests; all application boundaries are offline doubles."""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,os,sys
import pytest
ROOT=Path(os.environ['SOLIDWORKS_SKILL_ROOT']);sys.path.insert(0,str(ROOT));import scripts
ST=Path(__file__).resolve().parents[1];scripts.__path__.insert(0,str(ST/'scripts'))
from scripts import sw_cam_append_finish_recovery as core
spec=importlib.util.spec_from_file_location('append_prior_lifecycle',ST.parent/'tests/test_append_finish_lifecycle.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)

@pytest.fixture(scope='session')
def authority():
    receipt=Path(os.environ['CAM_FINISH_TEST_RECEIPT']);return json.loads(receipt.read_text(encoding='utf8'))['saved']

class Backend(prior.Backend):
    def __init__(self,data,fail=None):
        super().__init__(data,fail);self.state=prior.add_definition(self.state,data['recipe']['definitions'][0],900001);self.n=1
    def compact(self,label):
        s=super().compact(label)
        if self.fail=='two_existing':s=prior.add_definition(s,self.data['recipe']['definitions'][1],900002)
        if self.fail=='zero_existing':
            s=deepcopy(self.data['state']);s['target_header']=s['reference_header'];s['profile']=s['reference_profile']
        if self.fail=='wrong_feature':s['operations'][-1]['linked_feature_ids']=[70]
        if self.fail=='changed_prefix':s['operations'][0]['toolpath_record_counts']=[999]
        return s

@pytest.fixture
def packet(authority,tmp_path,monkeypatch):
    state=deepcopy(authority);recipe=json.loads((ST.parent/'RECIPE_01.json').read_text(encoding='utf8'));v=dict(mode='recovery_inspect',receipt_path=str(tmp_path/'inspect.json'),expected_source_sha256=state['sketch_state']['saved_file_sha256'])
    data=dict(state=state,recipe=recipe,recipe_pin=dict(path='recipe',sha256='b'*64),failure_pin=dict(path='failed',sha256='f'*64),failure_marker_pin=dict(path='consumed',sha256='e'*64))
    monkeypatch.setattr(core.base.defaults,'validate_defaults',lambda x:x)
    return data,v,tmp_path

def execute(packet,mode='recovery_inspect',fail=None,inspection=None):
    data,v,tmp=packet;data=deepcopy(data);v=deepcopy(v);v['mode']=mode;v['receipt_path']=str(tmp/('inspect.json'if mode=='recovery_inspect'else'continue.json'))
    if inspection:data['inspection']=inspection
    r=dict(scope=core.SCOPE,mode=mode,status='error',phase='preflight',request=deepcopy(v),recipe=data['recipe'],source_before_sha256=v['expected_source_sha256'],recipe_pin=data['recipe_pin'],failure_pin=data['failure_pin'],failure_marker_pin=data['failure_marker_pin'],actions={},captures=[],receipt_path=v['receipt_path'],dispatch_marker_path=str(tmp/'once.json'),mutation_attempted=False,native_call_attempted=False,save_attempted=False,GTP_attempted=False,operation_creation_attempted=False,marker_created=False,readback_verified=False)
    j=core.Journal(v['receipt_path'],r['dispatch_marker_path'],r);b=Backend(data,fail);result=core.run_once(b,j,data,v);return result,b,j

def test_inspection_observes_single_floor_without_mutation(packet):
    r,b,j=execute(packet);assert r['inspection_verified'],r.get('reason');assert r['recovered_floor_id']==900001;assert len(r['observed']['operations'])==27;assert not r['mutation_attempted'];assert not j.marker.exists();assert not any(x=='Save'or x.startswith('insert:')for x in b.calls)
    assert b.calls.index('compact:recovery_route')<b.calls.index('defaults:recovered_floor')<b.calls.index('capture:observed')
    assert json.loads(j.receipt.read_text(encoding='utf8'))==r

@pytest.mark.parametrize('failure',['two_existing','zero_existing','wrong_feature','changed_prefix','bottom_floor','observed','confirm_observed','drift_confirm_observed'])
def test_ambiguous_or_changed_inspection_never_mutates(packet,failure):
    r,b,j=execute(packet,fail=failure);assert r['status']=='error';assert not r['inspection_verified'];assert not j.marker.exists();assert not any(x=='Save'or x.startswith('insert:')for x in b.calls)

def test_compact_id_defaults_are_durable_when_full_capture_fails(packet):
    r,b,j=execute(packet,fail='observed');saved=json.loads(j.receipt.read_text(encoding='utf8'));assert saved['recovered_floor_id']==900001;assert saved['observed_defaults']['finish']['BottomFinOpt']is True

def test_continuation_only_missing_wall_then_one_save(packet):
    inspection,_,_=execute(packet);r,b,j=execute(packet,'recovery_continue',inspection=inspection);assert r['definitions_verified'],r.get('reason');assert [x for x in b.calls if x.startswith('insert:')]==['insert:wall'];assert b.calls.count('Save')==1;assert [x['native_id']for x in r['new_operations']]==[900001,900002];assert len(r['saved']['operations'])==28;assert r['parameters_configured']is False;assert r['generation_performed']is False

@pytest.mark.parametrize('failure',['changed_prefix','bottom_floor','insert:wall','insert:wall_after_return','bottom_wall','inserted','drift_inserted'])
def test_failed_continuation_does_not_replay_or_save(packet,failure):
    inspection,_,_=execute(packet);r,b,j=execute(packet,'recovery_continue',failure,inspection);assert not r['definitions_verified'];assert b.calls.count('insert:wall')<=1;assert 'insert:floor'not in b.calls;assert 'Save'not in b.calls

@pytest.mark.parametrize('failure',['Save_after_return','saved','confirm_saved','drift_confirm_saved'])
def test_saved_return_remains_durable(packet,failure):
    inspection,_,_=execute(packet);r,b,j=execute(packet,'recovery_continue',failure,inspection);assert r['status']=='uncertain';assert b.calls.count('Save')==1;assert r['actions']['SaveActiveDocument']['returned'];assert r['save_stage']['native_return_value']==0;assert json.loads(j.receipt.read_text(encoding='utf8'))==r

def test_changed_inspection_stops_before_marker(packet):
    inspection,_,_=execute(packet);inspection['confirm_observed']['cutting_context']['nc']['XYFeed']+=1
    r,b,j=execute(packet,'recovery_continue',inspection=inspection);assert r['status']=='error';assert not j.marker.exists();assert 'insert:wall'not in b.calls

def test_recovery_marker_prevents_another_continuation(packet):
    inspection,_,_=execute(packet);r,b,j=execute(packet,'recovery_continue',inspection=inspection)
    other=core.Journal(j.receipt.with_name('another.json'),j.marker,deepcopy(r))
    with pytest.raises(ValueError):other.create()

def test_read_only_context_rejects_mutators():
    c=object.__new__(core.RecoveryContext);c.recovery_mode='recovery_inspect'
    with pytest.raises(ValueError):c.insert({'role':'wall'},900001,pending=lambda:None,returned=lambda x:None)
    with pytest.raises(ValueError):c.save(returned=lambda x:None)
    with pytest.raises(ValueError):c.generate()

def test_inspect_journal_forbids_all_dispatch(packet):
    r,b,j=execute(packet)
    for name in ('InsertOperation:floor','InsertOperation:wall','SaveActiveDocument','GTP:361'):
        with pytest.raises(ValueError):j.pending(name)

@pytest.fixture(scope='session')
def actual_failure():
    p=Path(os.environ['CAM_APPEND_FAILED_RECEIPT']);r=json.loads(p.read_text(encoding='utf8'));m=json.loads(Path(r['dispatch_marker_path']).read_text(encoding='utf8'));v=deepcopy(r['request']);v.update(failure_receipt_path=str(p),failure_receipt_sha256=core._file_hash(p),failure_marker_path=r['dispatch_marker_path']);return r,m,v

def test_actual_failure_exactly_admitted(actual_failure):
    r,m,v=deepcopy(actual_failure);assert core.validate_failure(r,m,v)is r

@pytest.mark.parametrize('change',['other_action','pending','not_returned','scalar','actual_id','saved','generated','runtime_error','cleanup_error','changed_pid','changed_source','marker_sha','reason'])
def test_failure_authority_rejects_ambiguous_history(actual_failure,change):
    r,m,v=deepcopy(actual_failure);a=r['actions']['InsertOperation:floor']
    if change=='other_action':r['actions']['InsertOperation:wall']={}
    elif change=='pending':a['native_dispatch_pending']=True
    elif change=='not_returned':a['returned']=False
    elif change=='scalar':a['native_return_type']='int'
    elif change=='actual_id':a['actual_operation_native_id']=999
    elif change=='saved':r['save_attempted']=True
    elif change=='generated':r['GTP_attempted']=True
    elif change=='runtime_error':r['runtime_error']={'message':'changed'}
    elif change=='cleanup_error':r['cleanup_error']={'message':'changed'}
    elif change=='changed_pid':v['process_id']+=1
    elif change=='changed_source':r['source_before_sha256']='0'*64
    elif change=='marker_sha':m['receipt_sha256']='0'*64
    elif change=='reason':r['reason']='other'
    with pytest.raises(ValueError):core.validate_failure(r,m,v)

@pytest.mark.parametrize('dirty',[True,False])
def test_initial_dirty_is_observed_not_assumed(authority,monkeypatch,dirty):
    c=object.__new__(core.RecoveryContext);c.append_plan={'state':deepcopy(authority)};c.data={};c.report={};c.persist=lambda:None
    actual=deepcopy(authority['document']);actual['needs_save']=dirty;c.identity=lambda:deepcopy(actual)
    monkeypatch.setattr(core.base.AppendContext,'start',lambda self:'started')
    assert c.start()=='started';assert c.data['recovery']['expected_state']['document']==actual;assert c.report['recovery_initial_document']==actual

@pytest.mark.parametrize('change',['path','title','type','dirtyint'])
def test_initial_document_other_changes_rejected(authority,monkeypatch,change):
    c=object.__new__(core.RecoveryContext);c.append_plan={'state':deepcopy(authority)};c.data={};c.report={};c.persist=lambda:None
    actual=deepcopy(authority['document'])
    if change=='dirtyint':actual['needs_save']=1
    elif change=='type':actual['type']=2
    else:actual[change]='changed'
    c.identity=lambda:actual
    monkeypatch.setattr(core.base.AppendContext,'start',lambda self:pytest.fail('Changed document reached native start'))
    with pytest.raises(ValueError):c.start()

@pytest.mark.parametrize('change',[None,'source','pid','state','mode','mutation','marker'])
def test_inspection_loader_requires_exact_read_only_proof(packet,actual_failure,change):
    r,b,j=execute(packet);r['messages']=deepcopy(actual_failure[0]['messages']);data,v,tmp=packet;v=deepcopy(v);v.update(mode='recovery_continue',receipt_path=str(tmp/'continue.json'),inspection_receipt_path='inspect',inspection_receipt_sha256='a'*64)
    if change=='source':v['expected_source_sha256']='0'*64
    elif change=='pid':v['process_id']=123
    elif change=='state':r['confirm_observed']['operations'][0]['suppressed']=True
    elif change=='mode':r['mode']='recovery_continue'
    elif change=='mutation':r['mutation_attempted']=True
    elif change=='marker':r['marker_created']=True
    if change is None:core.validate_inspection(r,data,v)
    else:
        with pytest.raises(ValueError):core.validate_inspection(r,data,v)
