from copy import deepcopy
from pathlib import Path
import pytest
from cam_public_test_support import add_runtime, required_module
R=add_runtime()
m=required_module('sw_cam_local_operation_group')
M=Path(m.__file__)


def fixture():
    tool=dict(native_id=700,native_read_complete=True,cut_diameter_native=.8)
    oldtool=dict(native_id=600,native_read_complete=True,cut_diameter_native=2.)
    ops=[]
    for i in range(17):
        generated=i>=3
        ops.append(dict(native_id=100+i,setup_index=0,setup_native_id=93,operation_index=i,mill_operation_type=i%2,
            base_operation_type=1,suppressed=False,toolpath_generated=generated,toolpath_record_counts=[12]if generated else[],
            linked_feature_ids=[80 if i%2 else 81],assigned_tool=deepcopy(oldtool)))
    levels=dict(top=10.9,floor=7.5)
    def param(oid,fid,assigned):return dict(operation_native_id=oid,feature_native_id=fid,read_complete=True,levels=deepcopy(levels),
        tool=dict(generic=deepcopy(assigned)),nc=dict(feeds_compensation=dict(XYFeed=35.,GetCNCComp=0,GetTlpComp=1)))
    baseline=dict(binding=dict(features={'80':{'native_id':80},'81':{'native_id':81},'900':{'native_id':900},'901':{'native_id':901}},
        operation_setups=[dict(index=0,native_id=93,operation_count=17)],operations=ops),
        parameters=[param(o['native_id'],o['linked_feature_ids'][0],oldtool)for o in ops[-8:]])
    rows=[]
    for key,fid,kind in zip(m.KEYS,[900,900,901,901],[0,1,0,1]):
        specs=m.config.ROUGH_FIELDS if kind==0 else m.config.FINISH_FIELDS
        rows.append(dict(key=key,feature_native_id=fid,operation_type=kind,operation_setup_native_id=93,
            feature_owner_setup_native_id=69,default_operation_id=10+kind,default_operation_name='actual'+str(kind),
            expected_levels=deepcopy(levels),fields={s[0]:0 for s in specs}))
    plan=dict(rows=rows,tool=tool,feed_policy={k:[]for k in m.KEYS},physical_cutting_conditions_qualified=False)
    return baseline,plan,param,oldtool

class Journal:
    def __init__(self):self.report=dict(source_sha256='a'*64);self.log=[]
    def create(self):self.log.append('create')
    def persist(self):pass
    def entry(self,name):
        self.report['phase']=name
        return self.report['actions'].setdefault(name,dict(attempted=False,returned=False,status='prepared',native_dispatch_pending=False))
    def pending(self,name):
        a=self.entry(name);assert not a['attempted'];a.update(attempted=True,native_dispatch_pending=True,status='pending')
        self.report.update(mutation_attempted=True,native_call_attempted=True,native_dispatch_pending=True);self.log.append(name)
    def execute(self,name,fn):
        a=self.entry(name);value=fn(lambda:self.pending(name));a.update(returned=True,native_dispatch_pending=False,native_return=value)
        self.report.update(native_call_returned=True,native_dispatch_pending=False);return value
    def verified(self,name,value):self.entry(name).update(status='verified',readback_verified=True,observed=deepcopy(value))

class Backend:
    def __init__(self,b,p,param,oldtool,j,feed_delta=False,fail_at=None):
        self.value=deepcopy(b);self.plan=p;self.param=param;self.oldtool=oldtool;self.j=j
        self.calls=[];self.learned=[];self.feed_delta=feed_delta;self.fail_at=fail_at;self.next_id=1000
    def start(self):self.calls.append('start')
    def boundary(self):pass
    def refresh_dirty(self):pass
    def finish(self):self.calls.append('finish')
    def close(self):self.calls.append('close');self.j.report['cleanup_session_active']=False
    def capture_snapshot(self,label,full=False,own=None):
        v=deepcopy(self.value)
        if own is not None:v['parameters']=[p for p in v['parameters']if p['operation_native_id']==own['operation_native_id']]
        return v
    def capture_binding(self,label):return deepcopy(self.value['binding'])
    def insert(self,row,anchor,pending,returned):
        pending();returned(object());oid=self.next_id;self.next_id+=1
        b=self.value['binding'];b['operations'].append(dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=len(b['operations']),
            mill_operation_type=row['operation_type'],base_operation_type=1,suppressed=False,toolpath_generated=False,toolpath_record_counts=[],
            linked_feature_ids=[row['feature_native_id']],assigned_tool=deepcopy(self.oldtool)))
        b['operation_setups'][0]['operation_count']+=1
        self.value['parameters'].append(self.param(oid,row['feature_native_id'],self.oldtool));self.calls.append('insert');return oid
    def assign(self,target,pending):
        pending();oid=target['operation_native_id'];self.calls.append('assign')
        next(o for o in self.value['binding']['operations']if o['native_id']==oid)['assigned_tool']=deepcopy(self.plan['tool'])
        next(o for o in self.value['parameters']if o['operation_native_id']==oid)['tool']['generic']=deepcopy(self.plan['tool']);return 0
    def generate(self,target,pending):
        pending();oid=target['operation_native_id'];self.calls.append('generate')
        if self.fail_at==len([x for x in self.calls if x=='generate']):raise RuntimeError('uncertain vendor outcome')
        row=next(o for o in self.value['binding']['operations']if o['native_id']==oid);row.update(toolpath_generated=True,toolpath_record_counts=[100])
        if self.feed_delta:next(o for o in self.value['parameters']if o['operation_native_id']==oid)['nc']['feeds_compensation']['XYFeed']=70.
        return 0
    def outcome(self,target):return dict(operation_native_id=target['operation_native_id'],feature_native_id=target['feature_native_id'],
        background_over_before=False,background_over_after=False,toolpath_generated=True,record_counts=[100])
    def save(self):self.calls.append('save');return 0
    def saved_hash(self,stage):return 'b'*64
    def export(self,label,binding):self.calls.append('export');return dict(rows=18)


def hooks():
    def assigned(before,after,target,loaded):assert after['tool']['generic']==loaded['local_plan']['tool']
    return m.Hooks(assigned,lambda *a:None,lambda *a:None,lambda *a:dict(protected_count=14))


def setup_run(monkeypatch,feed_delta=False,policy=False,fail_at=None):
    b,p,param,old=fixture();j=Journal();backend=Backend(b,p,param,old,j,feed_delta,fail_at)
    if policy:p['feed_policy']={k:[[35.,70.]]for k in m.KEYS}
    monkeypatch.setattr(m.generation,'status_contract',lambda outcome,target,generated:outcome)
    monkeypatch.setattr(m.generation,'close_checked',lambda backend,r:backend.close())
    def save_core(stage,*,capture,verify,guard,claim,persist,save,saved_hash):
        verify(capture('before'));guard();claim();assert save()==0;stage['saved_source_sha256']=saved_hash();verify(capture('after'));return stage
    monkeypatch.setattr(m.config.save_core,'run_one_existing_save',save_core)
    loaded=dict(guide_parameters=dict(expected_parameters=b),local_plan=p,generated=dict(saved_cl=dict(saved14=True)))
    result=m.run_backend(backend,j,loaded,hooks())
    return backend,j,result


def test_complete_group_counts_and_order(monkeypatch):
    backend,j,r=setup_run(monkeypatch)
    assert r['readback_verified'] and r['model_saved'] and r['status']=='saved_local_group_review_required'
    assert backend.calls==['start']+['insert']*4+['assign']*4+['generate']*4+['save','export','finish','close']
    assert len(r['saved']['binding']['operations'])==21 and len(r['saved']['parameters'])==12
    assert len(r['actions'])==13 and r['actual_new_ids']==[1000,1001,1002,1003]
    assert not r['production_qualified'] and not r['geometry_accepted']


def test_unknown_feed_stops_after_four_gtp_before_save(monkeypatch):
    backend,j,r=setup_run(monkeypatch,feed_delta=True)
    assert r['status']=='uncertain' and not r['model_saved'] and not r['readback_verified']
    assert backend.calls.count('generate')==4 and 'save'not in backend.calls and 'export'not in backend.calls
    assert len(r['completed_gtp_counts'])==4 and all(r['actions']['GTP:'+str(v)]['readback_verified'] for v in r['actual_new_ids'])


def test_sealed_selected_feed_pairs_only(monkeypatch):
    backend,j,r=setup_run(monkeypatch,feed_delta=True,policy=True)
    assert r['readback_verified'] and len(r['generation_verification']['allowed_feed_changes'])==4
    assert not r['generation_verification']['physical_cutting_conditions_qualified']


@pytest.mark.parametrize('step',[1,2,3,4])
def test_uncertain_gtp_never_replayed_or_saved(monkeypatch,step):
    backend,j,r=setup_run(monkeypatch,fail_at=step)
    assert r['status']=='uncertain' and backend.calls.count('generate')==step and 'save'not in backend.calls
    assert r['actions']['GTP:'+str(999+step)]['native_dispatch_pending']


def test_marker_bound_to_source_not_process_or_recipe():
    assert m.marker_key(str(M),'a'*64)==m.marker_key(str(M),'a'*64)
    assert m.marker_key(str(M),'a'*64)!=m.marker_key(str(M),'b'*64)


@pytest.mark.parametrize('bad',[True,0,-1,1.2,'900'])
def test_strict_feature_ids(bad):
    b,p,*_=fixture();p['rows'][0]['feature_native_id']=bad
    with pytest.raises(ValueError):m.validate_plan(p,b)


@pytest.mark.parametrize('bad',[[[35.,float('nan')]],[[35.,0]],[[True,70]],[[35.,70.],[35.,70.]]])
def test_invalid_feed_policy(bad):
    b,p,*_=fixture();p['feed_policy']['left_rough']=bad
    with pytest.raises(ValueError):m.validate_plan(p,b)


def test_existing_feature_operation_rejects():
    b,p,*_=fixture();b['binding']['operations'][0]['linked_feature_ids']=[900]
    with pytest.raises(ValueError):m.validate_plan(p,b)


def test_protected_feature_header_change_rejected():
    b,p,*_=fixture();v=deepcopy(b['binding']);v['features']['900']['depth']=5
    with pytest.raises(ValueError):m.protect_binding(b['binding'],v,0)


def test_protected_parameter_change_rejected():
    b,p,*_=fixture();v=deepcopy(b);v['parameters'][0]['nc']['feeds_compensation']['XYFeed']=36
    with pytest.raises(ValueError):m.protect_snapshot(b,v,0)


def test_stolen_learned_identity_rejected():
    b,p,*_=fixture();targets=[dict(r,operation_native_id=1000+i)for i,r in enumerate(p['rows'])]
    targets[0]['feature_native_id']=901
    with pytest.raises(ValueError):m.learned_contract(targets,p,b)


def test_generation_feed_allowance_does_not_allow_other_field(monkeypatch):
    _,_,r=setup_run(monkeypatch,feed_delta=True,policy=True)
    generated=deepcopy(r['generated']);generated['parameters'][-1]['nc']['feeds_compensation']['GetCNCComp']=1
    with pytest.raises(ValueError):m.verify_generation(r['configured'],generated,r['learned_targets'],r['completed_gtp_counts'],{k:[[35.,70.]]for k in m.KEYS})


def test_generation_cannot_modify_old_feed(monkeypatch):
    _,_,r=setup_run(monkeypatch);generated=deepcopy(r['generated']);generated['parameters'][0]['nc']['feeds_compensation']['XYFeed']=70.
    with pytest.raises(ValueError):m.verify_generation(r['configured'],generated,r['learned_targets'],r['completed_gtp_counts'],{k:[[35.,70.]]for k in m.KEYS})


def test_assignment_cannot_change_another_new_binding(monkeypatch):
    _,_,r=setup_run(monkeypatch);current=deepcopy(r['after_tools']['binding']);current['operations'][-1]['suppressed']=True
    with pytest.raises(ValueError):m.verify_assigned_binding(r['definitions']['binding'],current,r['actual_new_ids'],r['learned_targets'][0]['assigned_tool'])


def test_assignment_cannot_generate_path(monkeypatch):
    _,_,r=setup_run(monkeypatch);current=deepcopy(r['after_tools']['binding']);current['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[4])
    with pytest.raises(ValueError):m.verify_assigned_binding(r['definitions']['binding'],current,r['actual_new_ids'],r['learned_targets'][0]['assigned_tool'])


def test_real_journal_complete_group_and_source_marker(tmp_path,monkeypatch):
    from scripts import sw_cam_deep_guide_group as old
    class RealJournal(old.Journal):
        def _marker_state(self):
            value=super()._marker_state();value['scope']=m.SCOPE;return value
    b,p,param,oldtool=fixture();report=dict(source_sha256='a'*64,source_path=str(tmp_path/'source.sldprt'))
    receipt=tmp_path/'receipt.json';marker=tmp_path/'source_once.json';j=RealJournal(report,receipt,marker)
    backend=Backend(b,p,param,oldtool,j)
    monkeypatch.setattr(m.generation,'status_contract',lambda value,*a:value)
    monkeypatch.setattr(m.generation,'close_checked',lambda backend,r:backend.close())
    def save_core(stage,*,capture,verify,guard,claim,persist,save,saved_hash):
        verify(capture('before'));guard();claim();assert save()==0;saved_hash();verify(capture('after'))
    monkeypatch.setattr(m.config.save_core,'run_one_existing_save',save_core)
    loaded=dict(guide_parameters=dict(expected_parameters=b),local_plan=p,generated=dict(saved_cl={}))
    result=m.run_backend(backend,j,loaded,hooks())
    assert result['readback_verified'] and j.claimed and receipt.is_file()and marker.is_file()
    second=RealJournal(dict(source_sha256='a'*64,source_path=report['source_path']),tmp_path/'second.json',marker)
    with pytest.raises(ValueError):second.create()


def test_ambiguous_defaults_stop_before_first_mutation(monkeypatch):
    b,p,param,old=fixture();j=Journal();backend=Backend(b,p,param,old,j)
    monkeypatch.setattr(m.generation,'close_checked',lambda backend,r:backend.close())
    loaded=dict(guide_parameters=dict(expected_parameters=b),generated=dict(saved_cl={}))
    def compiler(backend,loaded):raise ValueError('Native default is ambiguous')
    result=m.run_backend(backend,j,loaded,hooks(),plan_compiler=compiler)
    assert result['status']=='error'and not result['mutation_attempted']and result['actions']=={}
    assert backend.calls==['start','close']
