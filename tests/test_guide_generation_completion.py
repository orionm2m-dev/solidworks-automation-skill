"""Regression: global background flag is diagnostic, never an idle/completion predicate."""
from copy import deepcopy
from pathlib import Path
import json,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_group_generation as m
from test_guide_group_generation import fixture,setup


def outcome(before,after,generated=True):return dict(operation_native_id=322,feature_native_id=82,generated=generated,
    generated_for_feature=generated,record_counts=[12]if generated else[],background_over_before=before,background_over_after=after)
TARGET={'operation_native_id':322,'feature_native_id':82}


@pytest.mark.parametrize('before,after',[(False,False),(True,False),(False,True),(True,True)])
def test_background_booleans_do_not_decide_selected_completion(before,after):
    m.status_contract(outcome(before,after),TARGET,True)
    m.status_contract(outcome(before,after,False),TARGET,False)
    with pytest.raises(ValueError):m.status_contract(outcome(before,after,False),TARGET,True)


@pytest.mark.parametrize('bad',[0,1,None,'false',[],{}])
def test_background_diagnostic_type_remains_strict(bad):
    with pytest.raises(ValueError):m.status_contract(outcome(bad,False),TARGET,True)
    with pytest.raises(ValueError):m.status_contract(outcome(False,bad),TARGET,True)


def test_global_false_with_complete_paths_finishes_once(tmp_path,monkeypatch):
    b,j,l=setup(tmp_path,monkeypatch,'background');r=m.run_backend(b,j,l)
    assert r['status']=='saved_generated_review_required',r.get('issue')
    assert b.trace.count('save')==1 and [x[1]for x in b.trace if isinstance(x,tuple)]==[322,324,326,328]


def predecessor(monkeypatch):
    state,targets=fixture();doc=dict(path='synthetic.SLDPRT',title='synthetic.SLDPRT',type=1,needs_save=False)
    proof=dict(output={'path':'baseline.cl','sha256':'c'*64},source_sha256='a'*64,document=doc,expected_generated_operations=[])
    loaded=dict(guide_parameters={'targets':targets,'document':doc,'expected_parameters':state},ownership={'process_id':52},reopen_pin={'path':'reopen.json','sha256':'b'*64})
    r=dict(scope=m.SCOPE,status='error',phase='finished',failed_phase='GenerateToolpath:322',mutation_attempted=False,GTP_attempted=False,
        save_attempted=False,model_saved=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
        generated_operation_ids=[],actions={'GenerateToolpath:322':dict(status='prepared',attempted=False,returned=False,readback_verified=False)},
        issue={'type':'ValueError','locations':[{'function':'status_contract'}]},outcomes=[outcome(False,False,False)],
        messages=dict(active=False,subscribed=True,disconnected=True),ownership={'process_id':52},request={'process_id':52},
        source_sha256='a'*64,source_path=doc['path'],reopen_receipt_pin=deepcopy(loaded['reopen_pin']),before=deepcopy(state),before_cl=proof)
    p=dict(process_id=52,expected_document_path=doc['path'],expected_source_sha256='a'*64,before_cl_path='baseline.cl')
    monkeypatch.setattr(m.cl,'_verified',lambda value:None);monkeypatch.setattr(m.cl,'contract',lambda binding:[])
    return r,p,loaded


@pytest.mark.parametrize('bad',[None,'attempted','returned','pending','save','owner','source','baseline','reopen','event','cl'])
def test_zero_attempt_gate_never_accepts_uncertain_execution(monkeypatch,bad):
    r,p,l=predecessor(monkeypatch)
    if bad=='attempted':r['actions']['GenerateToolpath:322']['attempted']=True
    if bad=='returned':r['native_call_returned']=True
    if bad=='pending':r['native_dispatch_pending']=True
    if bad=='save':r['save_attempted']=True
    if bad=='owner':r['ownership']['process_id']=53
    if bad=='source':r['source_sha256']='d'*64
    if bad=='baseline':r['before']['parameters'][0]['nc']['extra']=1
    if bad=='reopen':r['reopen_receipt_pin']['sha256']='d'*64
    if bad=='event':r['messages']['event_count']=1
    if bad=='cl':p['before_cl_path']='foreign.cl'
    if bad:
        with pytest.raises(ValueError):m.zero_attempt_contract(r,p,l)
    else:m.zero_attempt_contract(r,p,l)


def test_verified_prior_baseline_export_is_not_repeated(tmp_path,monkeypatch):
    b,j,l=setup(tmp_path,monkeypatch,'background')
    proof=b.export_cl('before',l['guide_parameters']['expected_parameters']['binding']);b.trace=[]
    l.update(zero_attempt={'before_cl':proof},zero_attempt_pin={'path':'failed.json','sha256':'d'*64})
    monkeypatch.setattr(m.cl,'_verified',lambda value:None)
    r=m.run_backend(b,j,l)
    assert r['status']=='saved_generated_review_required',r.get('issue')
    assert 'cl:before'not in b.trace and r['before_cl_reused_from']==l['zero_attempt_pin']
    assert b.trace.count('save')==1
