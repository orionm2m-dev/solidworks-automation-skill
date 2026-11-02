from pathlib import Path
from copy import deepcopy
import importlib.util,os,sys,json
from types import ModuleType
import pytest
from cam_optional_test_evidence import evidence_root, required_evidence
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(R))
P=R/'scripts/sw_cam_deep_long_tool_completed_save.py'
spec=importlib.util.spec_from_file_location('save_only_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
old_path=Path(__file__).parent/'test_deep_long_tool_gtp_continue.py'
spec=importlib.util.spec_from_file_location('assigned_fixtures',old_path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)

@pytest.fixture
def actual():
    D=evidence_root('SW_CAM_COMPLETED_DEEP_SAVE_EVIDENCE_ROOT')
    assigned,l,p=old.load_actual(D)
    gp=D/'deep_long_tool_zero_native_recovery_20261102/ACTUAL_FOUR_GENERATED_FEED_CHANGE.json'
    g=json.loads(gp.read_text(encoding='utf-8-sig'))
    return g,l,p,gp


def test_actual_four_generated_paths_only_exact_feed_delta(actual):
    g,l,p,gp=actual;snapshot,policy=m.completed_gtp_contract(g,l,p)
    assert snapshot==g['generated'] and len(policy['changes'])==4 and not policy['production_qualified']
    assert all(v['requested']==500 and v['observed']==1000 for v in policy['changes'])

@pytest.mark.parametrize('damage',['pending','save_attempt','extra_action','failed_action','return','feed999','shallow_feed','coordinate','tool_profile','source','owner','wrong_stack'])
def test_save_adoption_rejects_any_unqualified_change(actual,damage):
    g,l,p,gp=actual
    if damage=='pending':g['native_dispatch_pending']=True
    elif damage=='save_attempt':g['save_attempted']=True
    elif damage=='extra_action':g['actions']['SaveActiveDocument']={}
    elif damage=='failed_action':g['actions']['GTP:336']['readback_verified']=False
    elif damage=='return':g['actions']['GTP:330']['native_return']['value']=1
    elif damage=='feed999':g['generated']['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=999
    elif damage=='shallow_feed':g['generated']['parameters'][0]['nc']['feeds_compensation']['XYFeed']=1000
    elif damage=='coordinate':g['generated']['binding']['features']['80']['depth_native']=4.5
    elif damage=='tool_profile':g['replacement_tool']['mill']['EffCutlength']['raw']=3
    elif damage=='source':p['expected_source_sha256']='f'*64
    elif damage=='owner':g['ownership']['create_time']+=1
    elif damage=='wrong_stack':g['issue']['locations'][1]['line']=78
    with pytest.raises(ValueError):m.completed_gtp_contract(g,l,p)


def test_real_backend_constructor_has_no_mutating_non_save_entrypoints(actual):
    g,l,p,gp=actual;b=m.NativeBackend(l,p,object(),'metadata','metadata',{},lambda:None)
    assert isinstance(b.capture,ModuleType)and callable(b.capture_snapshot)
    for name in ('assign','generate','set_field','set_nc'):
        with pytest.raises(ValueError):getattr(b,name)()
    assert m.NativeBackend.save is m.base.NativeBackend.save

@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(m.cl,'_verified',lambda a:{'parse_complete':True});monkeypatch.setattr(m.base,'verify_protected_cl',lambda a,b:{'protected_ten_complete_streams_verified':True});monkeypatch.setattr(m.cl,'verify_no_new_cutcom',lambda x:{'absent':True})
    def save_stage(report,**kw):
        before=kw['capture']('before');kw['verify'](before);kw['guard']();kw['claim']();assert kw['save']()==0;kw['saved_hash']();kw['verify'](kw['capture']('after'))
    monkeypatch.setattr(m.config.save_core,'run_one_existing_save',save_stage)

class FakeBackend(old.prior.FakeBackend):
    def assign(self,*a):raise AssertionError('No SetTool')
    def generate(self,*a):raise AssertionError('No GTP')
    def set_field(self,*a):raise AssertionError('No setter')
    def set_nc(self,*a):raise AssertionError('No feed restoration')
    def save(self):
        if self.damage=='unknown_save':raise RuntimeError('unknown Save outcome')
        return super().save()


def batch(actual,damage=None):
    g,l,p,gp=actual;l['adopted_snapshot'],l['feed_adoption']=m.completed_gtp_contract(g,l,p)
    j=old.prior.FakeJournal();j.report.update(source_sha256=p['expected_source_sha256'],source_path=p['expected_document_path'],request=p,ownership=g['ownership'],feed_adoption=l['feed_adoption'])
    b=FakeBackend(l,j,damage);b.snapshot=deepcopy(l['adopted_snapshot']);return j,b,l


def test_only_one_save_one_export_and_actual_nc_checkpoint(actual,engine):
    j,b,l=batch(actual);r=m.run_backend(b,j,l)
    assert r['readback_verified'] and b.calls==['start','Save','CL:saved','finish']
    assert not r['GTP_attempted']and not r['SetTool_attempted']and not r['setter_attempted']
    assert all(t['reference_nc']['XYFeed']==1000 for t in r['replacement_checkpoint_context']['learned_targets'])


def test_live_snapshot_drift_stops_before_save(actual,engine):
    j,b,l=batch(actual);b.snapshot['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=999
    r=m.run_backend(b,j,l);assert not r['readback_verified']and b.calls==['start']


def test_unknown_save_cannot_replay(actual,engine):
    j,b,l=batch(actual,'unknown_save');r=m.run_backend(b,j,l)
    assert r['status']=='uncertain'and not r['readback_verified']and not any(x.startswith('CL:')for x in b.calls)
    with pytest.raises(ValueError):m.run_backend(b,j,l)


def test_marker_not_bypassed_by_pid_receipt_or_generated_pin(tmp_path,monkeypatch):
    monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    p=dict(expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,process_id=1,generated_receipt_sha256='b'*64)
    first=m.marker_path(p);first.write_text('pending')
    assert m.marker_path(dict(p,process_id=2,receipt_path='other',generated_receipt_sha256='c'*64))==first

@pytest.fixture
def saved(actual,engine):
    g,l,p,gp=actual;j,b,l=batch(actual);r=m.run_backend(b,j,l)
    r.update(scope=m.SCOPE,module_pin=m.common._pin(m.__file__),adopted_generated_receipt_pin=m.common._pin(gp),adopted_GTP_actions=deepcopy(g['actions']),tool_creation_pin=deepcopy(g['tool_creation_pin']),replacement_tool=deepcopy(g['replacement_tool']),save_attempted=True,cleanup_session_active=False,messages=deepcopy(g['messages']))
    a=r['actions']['SaveActiveDocument'];a.update(status='verified',attempted=True,returned=True,readback_verified=True,native_dispatch_pending=False,native_return={'python_type':'int','value_recorded':True,'value':0})
    doc=deepcopy(g['current_document']);r['replacement_checkpoint_context']['document']=doc
    r['source_transition']=dict(source_before_sha256=r['source_sha256'],source_after_sha256=r['saved_source_sha256'],strict_save_return=0,document=doc)
    return r,g


def test_completed_save_validator(saved):
    r,g=saved;assert m.validate_completed_save(r,g)==r['replacement_checkpoint_context']

@pytest.mark.parametrize('damage',['bad_pin','empty_targets','wrong_feed','wrong_profile','extra_gtp','changed_saved','wrong_savehash','dirty','changed_source','production','assigned_tool','tool_native_id'])
def test_saved_authority_requires_exact_profile_feed_and_save(saved,damage):
    r,g=saved
    if damage=='bad_pin':r['adopted_generated_receipt_pin']['sha256']='f'*64
    elif damage=='empty_targets':r['replacement_checkpoint_context']['learned_targets']=[]
    elif damage=='wrong_feed':r['replacement_checkpoint_context']['learned_targets'][0]['reference_nc']['XYFeed']=500
    elif damage=='wrong_profile':r['replacement_checkpoint_context']['tool_dimensions']['mill']['EffCutlength']['raw']=3
    elif damage=='extra_gtp':r['GTP_attempted']=True
    elif damage=='changed_saved':r['saved']['binding']['operations'][0]['suppressed']=True
    elif damage=='wrong_savehash':r['actions']['SaveActiveDocument']['observed']='f'*64
    elif damage=='dirty':r['replacement_checkpoint_context']['document']['needs_save']=True
    elif damage=='changed_source':r['source_transition']['source_before_sha256']='f'*64
    elif damage=='production':r['production_qualified']=True
    elif damage=='assigned_tool':r['replacement_checkpoint_context']['learned_targets'][0]['assigned_tool']['native_id']=999
    elif damage=='tool_native_id':r['replacement_checkpoint_context']['learned_targets'][0]['tool_native_id']=999
    with pytest.raises(ValueError):m.validate_completed_save(r,g)
