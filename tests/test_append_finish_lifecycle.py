"""Lifecycle regression with saved shapes; no native calls or source writes."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,sys
import pytest
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(RUNTIME));import scripts
STAGE=Path(__file__).resolve().parents[1]
if (STAGE/'scripts').is_dir():scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_append_finish_definitions as core

@pytest.fixture(scope='session')
def saved_state():
    p=os.environ.get('CAM_FINISH_TEST_RECEIPT')
    if not p:pytest.skip('Saved project fixture is an explicit optional offline input')
    digest=os.environ.get('CAM_FINISH_TEST_RECEIPT_SHA')
    if not digest:pytest.skip('Pinned saved receipt SHA required')
    raw=Path(p).read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
    return json.loads(raw)['saved']

@pytest.fixture
def packet(saved_state,tmp_path,monkeypatch):
    path=os.environ.get('CAM_FINISH_TEST_RECIPE');digest=os.environ.get('CAM_FINISH_TEST_RECIPE_SHA')
    if not path or not digest:pytest.skip('Pinned saved-case recipe is an explicit optional input')
    raw=Path(path).read_bytes();assert hashlib.sha256(raw).hexdigest()==digest
    state=deepcopy(saved_state);recipe=json.loads(raw)
    v=dict(receipt_path=str(tmp_path/'receipt.json'),expected_source_sha256=state['sketch_state']['saved_file_sha256'])
    data=dict(state=state,recipe=recipe,recipe_pin=dict(path='fixture_recipe',sha256='b'*64))
    r=dict(scope=core.SCOPE,status='error',phase='preflight',source_before_sha256=v['expected_source_sha256'],recipe_pin=data['recipe_pin'],actions={},captures=[],receipt_path=v['receipt_path'],dispatch_marker_path=str(tmp_path/'once.json'),mutation_attempted=False,marker_created=False,readback_verified=False)
    j=core.Journal(v['receipt_path'],r['dispatch_marker_path'],r)
    monkeypatch.setattr(core.defaults,'validate_defaults',lambda x:x)
    return data,v,r,j


def add_definition(state,definition,oid):
    out=deepcopy(state);template=deepcopy(next(x for x in state['operations']if x['mill_operation_type']==1));anchor=out['operations'][-1]
    template.update(native_id=oid,setup_native_id=anchor['setup_native_id'],setup_index=anchor['setup_index'],operation_index=anchor['operation_index']+1,mill_operation_type=1,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],linked_feature_ids=[definition['feature_native_id']])
    template['assigned_tool']=deepcopy(state['operations'][-1]['assigned_tool']);out['operations'].append(template)
    si=anchor['setup_index'];out['operation_counts'][si]+=1;out['operation_setups'][si]['operation_count']+=1;out['selected_operation_setup']['operation_count']+=1;out['operation_count']+=1
    pb=out['parameter_batch'];candidate=pb['candidate_tool']['generic']['native_id']
    if template['assigned_tool']['native_id']==candidate:
        c=deepcopy(next(iter(pb['candidate_consumers'].values())));c.update(operation_native_id=oid,assigned_tool_native_id=candidate);pb['candidate_consumer_ids'].append(oid);pb['candidate_consumers'][str(oid)]=c
    out['document']['needs_save']=True;out['sketch_state']['needs_save']=True
    return out


class Backend:
    def __init__(self,data,fail=None):self.data=data;self.state=deepcopy(data['state']);self.source=self.state['sketch_state']['saved_file_sha256'];self.fail=fail;self.calls=[];self.added_rows=[];self.n=0
    def start(self):self.calls.append('start')
    def boundary(self):return deepcopy(self.state['document'])
    def close(self):self.calls.append('close')
    def finish(self):self.calls.append('finish')
    def capture(self,label,partial):
        self.calls.append('capture:'+label)
        if self.fail==label:raise ValueError('capture failure')
        actual=deepcopy(self.state)
        if self.fail=='drift_'+label:actual['operations'][0]['suppressed']=not actual['operations'][0]['suppressed']
        partial.update(actual);return actual
    def insert(self,row,anchor,*,pending,returned):
        name='insert:'+row['role'];self.calls.append(name);pending();self.n+=1
        if self.fail==name:raise ValueError('native insert failure')
        self.state=add_definition(self.state,row,900000+self.n);returned(True)
        if self.fail==name+'_after_return':raise ValueError('post-return failure')
        return 900000+self.n
    def compact(self,label):
        self.calls.append('compact:'+label);s=deepcopy(self.state);s['target_header']=s['reference_header'];s['profile']=s['reference_profile']
        return s
    def operation_defaults(self,oid,row,label):
        self.calls.append('defaults:'+label)
        bottom=row['expected_bottom_finish']
        if self.fail=='bottom_'+row['role']:bottom=not bottom
        return dict(finish={'BottomFinOpt':bottom})
    def save(self,*,returned):
        self.calls.append('Save');returned(0)
        if self.fail=='Save_after_return':raise ValueError('post-Save read failed')
        self.source='c'*64;self.state['sketch_state']['saved_file_sha256']=self.source;self.state['document']['needs_save']=False;self.state['sketch_state']['needs_save']=False
    def adopt_saved_source(self,stage):assert stage['native_return_value']==0;return self.source


def run(packet,fail=None):
    data,v,r,j=packet;b=Backend(data,fail);result=core.run_once(b,j,data,v);return result,b,j


def test_success_two_inserts_one_save_no_gtp(packet):
    r,b,j=run(packet);assert r['status']=='review_required',r.get('reason');assert r['definitions_verified'];assert b.calls.count('Save')==1;assert [x for x in b.calls if x.startswith('insert:')]==['insert:floor','insert:wall'];assert not any('GTP'in x for x in b.calls);assert len(r['new_operations'])==2;assert len(r['saved']['operations'])==28

@pytest.mark.parametrize('fail',['before','drift_before','insert:floor','insert:floor_after_return','bottom_floor','insert:wall','insert:wall_after_return','bottom_wall','inserted','drift_inserted'])
def test_fail_before_save_never_saves(packet,fail):
    r,b,j=run(packet,fail);assert 'Save'not in b.calls;assert not r['definitions_verified'];assert r['status']==('error'if fail in ('before','drift_before')else'uncertain');assert b.calls.count('insert:floor')<=1;assert b.calls.count('insert:wall')<=1

@pytest.mark.parametrize('fail',['Save_after_return','saved','confirm_saved','drift_confirm_saved'])
def test_saved_return_durable_on_later_failure(packet,fail):
    r,b,j=run(packet,fail);assert r['status']=='uncertain';assert b.calls.count('Save')==1;assert r['actions']['SaveActiveDocument']['returned']is True;assert r['actions']['SaveActiveDocument']['native_return_value']==0;assert json.loads(j.receipt.read_text(encoding='utf-8'))==r


def test_once_marker_denies_other_receipt(packet):
    r,b,j=run(packet);other=core.Journal(j.receipt.with_name('other.json'),j.marker,deepcopy(r))
    with pytest.raises(ValueError):other.create()


def test_first_insertion_exception_is_mutation_uncertain(packet):
    r,b,j=run(packet,'insert:floor');assert r['mutation_attempted']is True;assert r['actions']['InsertOperation:floor']['native_dispatch_pending'];assert j.marker.exists();assert len([x for x in b.calls if x.startswith('insert:')])==1


def test_runtime_revocation_retains_save(packet):
    r,b,j=run(packet);r=core.finalize_runtime_failure(r,ValueError('runtime drift'));assert r['status']=='uncertain';assert r['save_stage']['native_return_value']==0;assert r['source_after_sha256']=='c'*64;assert r['model_saved'];assert not r['definitions_verified'];assert json.loads(j.receipt.read_text(encoding='utf-8'))==r
