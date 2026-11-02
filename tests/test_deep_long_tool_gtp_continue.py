from copy import deepcopy
from pathlib import Path
import ast,importlib.util,inspect,json,os,sys
from types import ModuleType
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(R))
P=R/'scripts/sw_cam_deep_long_tool_gtp_continue.py'
spec=importlib.util.spec_from_file_location('continuation_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
old_path=R/'tests/test_deep_long_tool_replace.py'
spec=importlib.util.spec_from_file_location('prior_tests',old_path);prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)

@pytest.fixture
def actual():
    return load_actual(evidence_root('SW_CAM_LONG_TOOL_CONTINUATION_EVIDENCE_ROOT'))

def load_actual(D):
    p=D/'deep_long_tool_replace_reconciled_20261102/ACTUAL_ASSIGNED_BEFORE_GTP_STOP.json'
    if not p.exists():p=D/'deep_long_tool_replace_20261102/ACTUAL_ASSIGNED_BEFORE_GTP_STOP.json'
    r=json.loads(p.read_text(encoding='utf-8-sig'))
    f=json.loads((R/'tests/fixtures/saved_deep_baseline.json').read_text(encoding='utf-8-sig'))
    targets=deepcopy(f['targets']);tool=r['replacement_tool'];wanted=tool['generic']
    for t in targets:t.update(tool_native_id=wanted['native_id'],assigned_tool=deepcopy(wanted),reference_tool_dimensions=deepcopy(tool))
    shallow=deepcopy(targets)
    for t,oid,fid in zip(shallow,[322,324,326,328],[82,82,83,83]):t.update(operation_native_id=oid,feature_native_id=fid)
    l=dict(ownership=deepcopy(r['ownership']),guide_parameters=dict(document=deepcopy(r['current_document']),configuration={'sw_configuration_name':'fixture'},expected_parameters=deepcopy(r['before']),targets=shallow),
      deep_targets=targets,configuration_tool=deepcopy(wanted),replacement_tool_dimensions=deepcopy(tool),tool_catalogue_ids=[273,wanted['native_id']],created_saved_cl=deepcopy(r['before_cl_reference']))
    p={k:r['request'][k]for k in ('process_id','expected_document_path','expected_source_sha256')}
    return r,l,p


def test_actual_partial_receipt_adopts_exact_configured(actual):
    r,l,p=actual
    assert m.partial_contract(r,l,p)==r['configured']
    assert r['current_document']['needs_save']is False

@pytest.mark.parametrize('damage',['attempted','pending','saved','extra_action','wrong_pid','different_source','changed_profile','configured_field','protected_path','unverified_assignment','dirty_assumption','wrong_stop'])
def test_partial_adoption_rejects_uncertainty_or_drift(actual,damage):
    r,l,p=actual
    if damage=='attempted':r['actions']['GTP:330']['attempted']=True
    elif damage=='pending':r['native_dispatch_pending']=True
    elif damage=='saved':r['model_saved']=True
    elif damage=='extra_action':r['actions']['GTP:332']={'attempted':False}
    elif damage=='wrong_pid':p['process_id']+=1
    elif damage=='different_source':p['expected_source_sha256']='f'*64
    elif damage=='changed_profile':r['replacement_tool']['mill']['EffCutlength']['raw']=3
    elif damage=='configured_field':r['configured']['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=777
    elif damage=='protected_path':r['configured']['binding']['operations'][0]['suppressed']=True
    elif damage=='unverified_assignment':r['actions']['SetTool:336']['readback_verified']=False
    elif damage=='dirty_assumption':r['current_document']['needs_save']=True
    elif damage=='wrong_stop':r['issue']['locations'][1]['line']=132
    with pytest.raises(ValueError):m.partial_contract(r,l,p)


def test_prior_actual_success_with_false_diagnostics_is_reused():
    D=evidence_root('SW_CAM_LONG_TOOL_CONTINUATION_EVIDENCE_ROOT')
    r=json.loads((D/'deep_guide_group_fix_20261102/ACTUAL_DEEP_SAVED_NATIVE.json').read_text(encoding='utf-8-sig'))
    proof=m.prior_background_contract(r)
    assert len(proof['verified_prior_false_diagnostics'])==4
    assert all(v['background_over_before']is False for v in proof['verified_prior_false_diagnostics'])


def test_actual_constructor_and_native_generation_preserve_bool_contract(actual,monkeypatch):
    r,l,p=actual;b=m.NativeBackend(l,p,object(),'metadata','metadata',{},lambda:None)
    assert isinstance(b.capture,ModuleType)and callable(b.capture_snapshot)
    b.read_nc=lambda t:deepcopy(t['reference_nc'])
    value=deepcopy(r['outcomes'][0]);b.outcome=lambda t:value
    class Guard:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def typed(self,obj,name):return obj
        def read(self,*args):return None
        def dispatch_once(self,fn,*,persist_pending):persist_pending();return fn()
    class Context:
        def guard(self):return Guard()
    b.ctx=Context();b.doc=object();b.target=lambda g,t:(object(),None)
    monkeypatch.setattr(m,'read_generic_tool',lambda *a:(l['configuration_tool'],None))
    called=[];monkeypatch.setattr(m,'_member',lambda obj,name:called.append(name)or 0)
    assert b.generate(b.learned[0],lambda:called.append('pending'))==0
    assert called==['pending','GenerateToolpath']
    value['background_over_after']=0
    with pytest.raises(ValueError):b.generate(b.learned[0],lambda:None)
    for name in ('assign','set_field','set_nc'):
        with pytest.raises(ValueError):getattr(b,name)()


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(m.cl,'_verified',lambda a:{'parse_complete':True})
    monkeypatch.setattr(m.base,'verify_protected_cl',lambda a,b:{'protected_ten_complete_streams_verified':True})
    monkeypatch.setattr(m.cl,'verify_no_new_cutcom',lambda x:{'absent':True})
    def save_stage(report,**kw):
        old=kw['capture']('before');kw['verify'](old);kw['guard']();kw['claim']();assert kw['save']()==0;kw['saved_hash']();kw['verify'](kw['capture']('after'))
    monkeypatch.setattr(m.config.save_core,'run_one_existing_save',save_stage)

class FakeBackend(prior.FakeBackend):
    def outcome(self,t):
        v=next(r for r in self.snapshot['binding']['operations']if r['native_id']==t['operation_native_id'])
        return dict(operation_native_id=t['operation_native_id'],feature_native_id=t['feature_native_id'],background_over_before=False,background_over_after=False,generated=v['toolpath_generated'],generated_for_feature=v['toolpath_generated'],record_counts=v['toolpath_record_counts'])
    def assign(self,*a):raise AssertionError('SetTool must never execute')
    def set_field(self,*a):raise AssertionError('Setters must never execute')
    def set_nc(self,*a):raise AssertionError('NC setters must never execute')


def batch(actual,damage=None):
    r,l,p=actual;l['adopted_snapshot']=m.partial_contract(r,l,p)
    j=prior.FakeJournal();j.report.update(source_sha256=p['expected_source_sha256'],request=p,ownership=r['ownership'])
    b=FakeBackend(l,j,damage);b.snapshot=deepcopy(l['adopted_snapshot']);return j,b,l


def test_four_gtp_one_save_export_no_assignment(actual,engine):
    j,b,l=batch(actual);r=m.run_backend(b,j,l)
    assert r['readback_verified'] and r['status']=='saved_assigned_deep_generation_review_required'
    assert b.calls==['start',*[f'GTP:{i}'for i in m.IDS],'Save','CL:saved','finish']
    assert r['SetTool_attempted']is False and r['setter_attempted']is False and b.closed


def test_changed_live_snapshot_stops_before_any_dispatch(actual,engine):
    j,b,l=batch(actual);b.snapshot['binding']['operations'][3]['suppressed']=True
    r=m.run_backend(b,j,l);assert r['readback_verified']is False and b.calls==['start']and b.closed


def test_unknown_gtp_outcome_stops_without_save_and_replay(actual,engine):
    j,b,l=batch(actual,'gtp_unknown');r=m.run_backend(b,j,l)
    assert r['status']=='uncertain'and not r['readback_verified']and 'Save'not in b.calls
    before=list(b.calls)
    with pytest.raises(ValueError):m.run_backend(b,j,l)
    assert b.calls==before


def test_source_marker_not_bypassed_by_pid_or_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p=dict(expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,process_id=9)
    marker=m.marker_path(p);marker.write_text('pending')
    assert m.marker_path(dict(p,process_id=10,receipt_path='other.json'))==marker


def test_real_guard_accepts64_without_native(actual,tmp_path,monkeypatch):
    from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
    r,l,p=actual;p=dict(p,expected_document_path=str(tmp_path/'part.SLDPRT'))
    Path(p['expected_document_path']).write_bytes(b'part');p['expected_source_sha256']=m.base._file_hash(p['expected_document_path'])
    l['guide_parameters']['document']=dict(path=p['expected_document_path'],type=1,needs_save=False);l['pins']=[]
    for i in range(64):
        f=tmp_path/f'dep{i}.py';f.write_text('# dep');l['pins'].append(m.common._pin(f))
    monkeypatch.setattr(ScopedCamDispatchGuard,'__enter__',lambda *a:(_ for _ in()).throw(AssertionError('native forbidden')))
    result=m.base.guard_constructor_preflight(p,l,'metadata-only')
    assert result['constructor_verified']and result['live_pin_count']==64
    f=tmp_path/'extra.py';f.write_text('extra');l['pins'].append(m.common._pin(f))
    with pytest.raises(ValueError):m.base.guard_constructor_preflight(p,l,'metadata-only')


@pytest.fixture
def completed(actual,engine):
    D=evidence_root('SW_CAM_LONG_TOOL_CONTINUATION_EVIDENCE_ROOT')
    failed,l,p=actual;j,b,l=batch(actual);r=m.run_backend(b,j,l)
    r.update(scope=m.SCOPE,module_pin=m.common._pin(m.__file__),source_path=failed['source_path'],adopted_actions=deepcopy(failed['actions']),tool_creation_pin=deepcopy(failed['tool_creation_pin']),
      adopted_assignment_receipt_pin=m.common._pin(D/'deep_long_tool_replace_reconciled_20261102/ACTUAL_ASSIGNED_BEFORE_GTP_STOP.json'),replacement_tool=deepcopy(failed['replacement_tool']),
      GTP_attempted=True,save_attempted=True,cleanup_session_active=False,messages=deepcopy(failed['messages']))
    for a in r['actions'].values():a.update(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_return={'python_type':'int','value_recorded':True,'value':0})
    doc=deepcopy(failed['current_document']);r['replacement_checkpoint_context']['document']=doc
    r['source_transition']=dict(source_before_sha256=r['source_sha256'],source_after_sha256=r['saved_source_sha256'],strict_save_return=0,document=doc)
    return r,failed


def test_completed_continuation_contract(completed):
    r,failed=completed
    assert m.validate_completed_continuation(r,failed)==r['replacement_checkpoint_context']

@pytest.mark.parametrize('damage',['empty_targets','changed_target','tool_profile','adopted_pin','creation_pin','source_transition','same_source','save_digest','settool_flag','extra_action'])
def test_completed_continuation_cannot_claim_unverified_lineage(completed,damage):
    r,failed=completed
    if damage=='empty_targets':r['replacement_checkpoint_context']['learned_targets']=[]
    elif damage=='changed_target':r['replacement_checkpoint_context']['learned_targets'][0]['feature_native_id']=81
    elif damage=='tool_profile':r['replacement_checkpoint_context']['tool_dimensions']['mill']['EffCutlength']['raw']=3
    elif damage=='adopted_pin':r['adopted_assignment_receipt_pin']['sha256']='f'*64
    elif damage=='creation_pin':r['tool_creation_pin']['sha256']='f'*64
    elif damage=='source_transition':r['source_transition']['source_before_sha256']='f'*64
    elif damage=='same_source':r['saved_source_sha256']=r['source_sha256']
    elif damage=='save_digest':r['actions']['SaveActiveDocument']['observed']='f'*64
    elif damage=='settool_flag':r['SetTool_attempted']=True
    elif damage=='extra_action':r['actions']['SetTool:330']={}
    with pytest.raises(ValueError):m.validate_completed_continuation(r,failed)
