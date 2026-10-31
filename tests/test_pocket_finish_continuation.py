"""Bounded partial-finish continuation and failure regressions."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import os
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_pocket_finish_continuation as m
spec=importlib.util.spec_from_file_location('finish_baseline_fixture',ROOT/'tests/test_sw_cam_pocket_finish_apply.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


def failed(loaded):
    r=t.report(loaded)
    r.update(status='uncertain',phase='finished',failed_phase='field:max_depth',mutation_attempted=True,
        initial_headers=deepcopy(loaded['state']),initial_parameters=dict(parameters=deepcopy(loaded['pocket_parameters']),startpoints=deepcopy(loaded['pocket_startpoints'])),
        initial_catalogue=deepcopy(loaded['neck_tool_checkpoint']['catalogue']),
        initial_fields={x[0]:[x[5],False] if x[4]=='depth_pair' else deepcopy(x[5]) for x in m.original.FIELDS},
        current_document=deepcopy(loaded['state']['document']),phase_proofs_verified=False,
        issue={'type':'OSError','locations':[{'function':'_file_hash'}]},phase_proof_error={'type':'OSError','locations':[{'function':'_file_hash'}]},
        messages={'subscribed':True,'disconnected':True,'active':False})
    values={'SetTool':m.original.wanted_assignment(loaded),**{'field:'+x[0]:x[6] for x in m.PREFIX_FIELDS}}
    r['actions']={key:dict(attempted=True,returned=True,pending=False,readback_verified=True,
        native_return_type='int',native_return_value=0,observed=deepcopy(value)) for key,value in values.items()}
    return r


def report(loaded,f):
    r=t.report(loaded);r.update(scope=m.SCOPE,inherited_actions=deepcopy(f['actions']),inherited_action_count=4,
        new_action_count=0,unchanged_previous_allowance_verified=False)
    for key in ('initial_headers','initial_parameters','initial_catalogue','initial_fields'):r[key]=deepcopy(f[key])
    return r


class Backend(t.Backend):
    def __init__(self,loaded,r,f,fail=None):
        super().__init__(loaded,r,fail=fail);self.failed=f
        self.values=deepcopy(f['initial_fields'])
        for x in m.PREFIX_FIELDS:self.values[x[0]]=deepcopy(x[6])
    def headers(self,label):
        result=deepcopy(self.loaded['state']);result['operations'][-1]['assigned_tool']=m.original.wanted_assignment(self.loaded)
        if self.fail=='route':result['operations'][6]['toolpath_record_counts']=[42]
        if self.fail=='assignment':result['operations'][-1]['assigned_tool']['native_id']=145
        if self.fail=='already_generated':result['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[9])
        return result
    def parameters(self,label):
        parameters=m.partial_parameters(self.loaded['pocket_parameters'])
        if self.fail=='parameters':parameters['144']['finish']['DepthAllow']=.1
        return dict(parameters=parameters,startpoints=deepcopy(self.loaded['pocket_startpoints']))
    def catalogue(self):
        result=super().catalogue()
        if self.fail=='catalogue':result[-1]['Protrusion']=27.
        return result
    def field(self,spec):
        if self.fail=='prefix' and spec[0]=='max_depth':return [10.,False]
        if self.fail=='old_field' and spec[0]=='side_step':return [.25,False]
        if self.fail=='unchanged_allowance' and spec[0]=='previous_allowance':return .25
        return super().field(spec)
    def assign(self,pending):raise AssertionError('Assignment replay forbidden')
    def set_field(self,spec,pending):
        assert spec in m.REMAINING_FIELDS
        return super().set_field(spec,pending)
    def capture_narrow(self,label):
        result=super().capture_narrow(label)
        if self.fail=='configured_drift' and label=='configured':result['parameters']['144']['finish']['DepthAllow']=.1
        return result
    def save(self):
        if self.fail=='save':self.calls.append('save');return 1
        return super().save()


def run(loaded=None,kind=None):
    loaded=loaded or t.baseline();f=failed(loaded);r=report(loaded,f);backend=Backend(loaded,r,f,kind)
    m.validate_failed(f)
    m.run_backend(backend,t.Journal(r),loaded,f)
    return r,backend,f


def test_full_flow_reuses_four_actions_and_dispatches_only_eleven_fields_gtp_save():
    r,b,f=run()
    assert r['readback_verified'] is True,r
    assert b.calls==['start']+[x[0] for x in m.REMAINING_FIELDS]+['generate','save','close']
    assert len(m.REMAINING_FIELDS)==11 and set(r['actions'])==set(m.NEW_ACTIONS)
    assert r['new_action_count']==13 and r['inherited_actions']==f['actions']
    assert 'field:previous_allowance' not in r['actions'] and r['unchanged_previous_allowance_verified'] is True
    assert r['actual_full_capture_count']==1


@pytest.mark.parametrize('kind',['route','assignment','already_generated','parameters','catalogue','prefix','old_field','unchanged_allowance'])
def test_any_partial_baseline_difference_stops_before_first_new_mutation(kind):
    r,b,_=run(kind=kind)
    assert r['readback_verified'] is False and r['actions']=={} and b.calls==['start','close']


@pytest.mark.parametrize('kind',['side_step','lead_in_radius','configured_drift','generate','save'])
def test_unknown_failure_never_replays_prefix_or_attempted_actions(kind):
    r,b,f=run(kind=kind)
    assert r['readback_verified'] is False
    assert len(b.calls)==len(set(b.calls)) and not {'assign','out_independent','first_depth','max_depth','previous_allowance'}.intersection(b.calls)
    assert r['inherited_actions']==f['actions']
    if kind not in ('generate','save'):assert 'generate' not in b.calls and 'save' not in b.calls
    if kind=='generate':assert 'save' not in b.calls


@pytest.mark.parametrize('kind',['pending','wrong_return','missing_action','extra_action','events','saved','wrong_error','unverified','changed_observed'])
def test_inherited_four_action_receipt_strict(kind):
    f=failed(t.baseline())
    if kind=='pending':f['actions']['field:max_depth']['pending']=True
    elif kind=='wrong_return':f['actions']['SetTool']['native_return_value']=True
    elif kind=='missing_action':f['actions'].pop('field:max_depth')
    elif kind=='extra_action':f['actions']['GenerateToolpath']=deepcopy(f['actions']['SetTool'])
    elif kind=='events':f['messages']['active']=True
    elif kind=='saved':f['saved_source_sha256']='f'*64
    elif kind=='wrong_error':f['issue']['type']='RuntimeError'
    elif kind=='unverified':f['actions']['field:first_depth']['readback_verified']=False
    elif kind=='changed_observed':f['actions']['field:max_depth']['observed']=[.3,True]
    with pytest.raises(ValueError):m.validate_failed(f)


def test_real_journal_marks_once_before_remaining_mutation(tmp_path):
    loaded=t.baseline();f=failed(loaded);r=report(loaded,f)
    r.update(source_path=str(tmp_path/'source.SLDPRT'),recipe_pin={'path':'recipe.json','sha256':'a'*64},failed_receipt_pin={'path':'failed.json','sha256':'b'*64})
    receipt=tmp_path/'receipt.json';marker=tmp_path/'marker.json';j=m.Journal(r,receipt,marker)
    j.pending('field:side_step')
    saved=json.loads(marker.read_text());assert saved['actions']['field:side_step']['pending'] is True and saved['inherited_action_count']==4
    with pytest.raises(ValueError):j.pending('field:side_step')
    other=m.Journal(report(loaded,f),tmp_path/'other.json',marker)
    with pytest.raises(ValueError):other.pending('field:side_step')


@pytest.mark.parametrize('validate_only,reply,status',[(True,{'status':'validated_offline'},0),(False,{'readback_verified':True},0),
 (False,{'readback_verified':False},1),(False,{'readback_verified':1},1)])
def test_cli_permanent_entrypoint(tmp_path,monkeypatch,capsys,validate_only,reply,status):
    request={'action':'continue_partial_pocket_finish','params':{}};p=tmp_path/'request.json';p.write_text(json.dumps(request),encoding='utf-8-sig');calls=[]
    def dispatch(value,*,validate_only):calls.append((value,validate_only));return reply
    monkeypatch.setattr(m,'dispatch_request',dispatch)
    assert m.main(['--request',str(p)]+(['--validate-only'] if validate_only else []))==status
    assert calls==[(request,validate_only)];json.loads(capsys.readouterr().out)


@pytest.mark.parametrize('label',['SetTool','field:first_depth','field:previous_allowance'])
def test_terminal_rejects_replayed_or_unnecessary_mutation_before_loading_parent(monkeypatch,label):
    r,_,_=run();r['phase_proofs_verified']=True
    r['actions'][label]=deepcopy(next(iter(r['actions'].values())))
    def forbidden(*a,**kw):raise AssertionError('Invalid action inventory must fail before parent loading')
    monkeypatch.setattr(m,'failed_evidence',forbidden)
    with pytest.raises(ValueError):m.validate_terminal(r)
