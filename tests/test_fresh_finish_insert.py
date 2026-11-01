"""Portable creation-only protocol tests; all CAD identities are synthetic."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME))
import scripts
scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_fresh_finish_insert as m

spec=importlib.util.spec_from_file_location('reuse_insert_fixture',RUNTIME/'tests/test_chamfer_insert_defaults.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)

class Fake(old.Fake):
    def catalogue_preflight(self):self.call('catalogue')
    def snapshot(self,label):
        original=self.fault
        if original=='new_generated' and not self.new:self.fault=None
        try:value=super().snapshot(label)
        finally:self.fault=original
        value['feature']=deepcopy(self.loaded['state']['features'][0])
        value['source_defaults']=deepcopy(self.defaults)
        value['source_restrictions']=deepcopy(self.loaded['wall_apply_all_configuration']['restrictions'])
        if self.fault=='source_drift:'+label:value['source_defaults']['finish']['GetChamferLength']+=.1
        if self.fault=='gouge_drift:'+label:value['source_restrictions']['GougeCheck']=False
        return value
    def operation_defaults(self,oid,label,feature_native_id=None):
        return super().operation_defaults(oid,label,feature_native_id)

@pytest.fixture
def case(tmp_path,monkeypatch):
    c=old.case.__wrapped__(tmp_path,monkeypatch)
    loaded=c.loaded
    loaded['state']['operations'][-1].update(linked_feature_ids=[70],toolpath_generated=False,toolpath_record_counts=[])
    loaded['neck_tool_checkpoint']={'catalogue':deepcopy(loaded['tool_checkpoint']['final_observation']['tools'])}
    loaded['wall_apply_all_configuration']=dict(operation_native_id=90,feature_native_id=70,
        restrictions={'LeadInOutApplyToAll':True,'GougeCheck':True})
    loaded['current_context_sha256']=m._digest(m.group.current_projection(loaded))
    p={k:v for k,v in c.p.items() if k in m.PARAMS}
    p.update(source_operation_native_id=90,module_sha256=m._file_hash(m.__file__))
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],
        initial_source_sha256=p['expected_source_sha256'],module_pin=m.common._pin(m.__file__),checkpoint_pin=loaded['parent_pin'],
        loaded_context_before=deepcopy(loaded),request=p,feature_native_id=70,anchor_operation_native_id=90,
        actions={},mutation_attempted=False,readback_verified=False,model_saved=False,live_pins=loaded['pins'],
        offline_proof_pins=[],bootstrap_export_pins=[],**{k:False for k in m.FORBIDDEN})
    marker=tmp_path/'fresh.marker.json'
    j=m.Journal(r,p['receipt_path'],marker)
    monkeypatch.setattr(m,'marker_path',lambda *args:marker)
    return SimpleNamespace(loaded=loaded,p=p,r=r,j=j,b=Fake(loaded,r,c.source),source=c.source)

def run(c):return m.run_backend(c.b,c.j,c.loaded,c.p)
def complete(c):
    r=run(c)
    assert r['readback_verified'],r.get('issue')
    r['phase_proofs_verified']=True
    loaded=m.validate_saved(r)
    r['checkpoint_digest']=m._digest(m.group.current_projection(loaded))
    c.j.persist();r['marker_pin']=m.common._pin(c.j.marker);c.j.persist()
    return r

def test_one_creation_one_save_no_settings_transfer_or_generation(case):
    r=complete(case)
    assert list(r['actions'])==['InsertOperation','SaveActiveDocument']
    assert case.b.calls.count('insert')==case.b.calls.count('save')==1
    assert r['new_operation_native_id']==100
    assert r['new_operation']['assigned_tool'] is None
    assert all(r[k] is False for k in m.FORBIDDEN)
    assert r['new_operation']['linked_feature_ids']==[70]
    assert case.b.calls.index('catalogue')<case.b.calls.index('insert')
    assert r['before']['source_restrictions']==r['final_observation']['source_restrictions']

@pytest.mark.parametrize('fault',['start','catalogue','snapshot:before','old_state:before','tools:before','gouge_drift:before'])
def test_preflight_failure_no_mutation(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and not r['actions']
    assert 'insert' not in case.b.calls and 'save' not in case.b.calls
    assert not case.j.marker.exists()

@pytest.mark.parametrize('fault',['insert','save'])
def test_pending_no_replay_under_renamed_receipt(case,fault):
    case.b.fault=fault;r=run(case)
    name='InsertOperation' if fault=='insert' else 'SaveActiveDocument'
    assert r['actions'][name]['pending'] is True
    assert case.b.calls.count(fault)==1 and not r['readback_verified']
    alternate=m.Journal(r,Path(case.p['receipt_path']).with_name('different.json'),case.j.marker)
    with pytest.raises(ValueError):alternate.claim()

@pytest.mark.parametrize('fault',['bind','old_id','old_state:inserted','tools:inserted','source_drift:inserted',
    'gouge_drift:inserted','new_generated','defaults:new_defaults','defaults_bad:new_defaults'])
def test_post_insert_failure_no_save(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and case.b.calls.count('insert')==1
    assert 'save' not in case.b.calls

@pytest.mark.parametrize('value',[False,True,None,1,0.,'0'])
def test_save_requires_strict_zero(case,value):
    case.b.save_return=value;r=run(case)
    assert not r['readback_verified'] and case.b.calls.count('save')==1
    assert 'saved_hash' not in case.b.calls

@pytest.mark.parametrize('fault',['unchanged_source','defaults_drift','old_state:saved','tools:saved',
    'source_drift:saved','gouge_drift:saved','finish'])
def test_postsave_failure_never_repeats_save(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and case.b.calls.count('save')==1

def test_completed_loader_only_definition_authority(case):
    r=complete(case)
    loaded=m.load_completed(case.p['receipt_path'],m._file_hash(case.p['receipt_path']),
        process_id=case.p['process_id'],expected_document_path=str(case.source),expected_source_sha256=r['saved_source_sha256'])
    assert loaded['state']['operation_count']==8
    assert loaded['fresh_finish_definition']['native_id']==100
    assert loaded['authority_kind']=='saved_fresh_finish_definition_no_toolpath'
    assert loaded['fresh_finish_definition']['toolpath_generated'] is False
    assert loaded['fresh_finish_definition']['parameters_transferred'] is False
    assert loaded['fresh_finish_definition']['geometry_acceptance_complete'] is False

@pytest.mark.parametrize('field',['other_feature','other_source','not_last','generated','dirty','wrong_type','count','suppressed'])
def test_binding_rejects_other_or_unstable_source(case,field):
    l=deepcopy(case.loaded);p=deepcopy(case.p);row=l['state']['operations'][-1]
    if field=='other_feature':p['feature_native_id']=71
    if field=='other_source':p['source_operation_native_id']=89
    if field=='not_last':l['state']['operations'].reverse()
    if field=='generated':row['toolpath_generated']=True
    if field=='dirty':l['state']['document']['needs_save']=True
    if field=='wrong_type':row['mill_operation_type']=9
    if field=='count':l['state']['operation_count']+=1
    if field=='suppressed':row['suppressed']=True
    with pytest.raises(ValueError):m.binding(l,p)

@pytest.mark.parametrize('field',['actions','source_defaults','restrictions','savebool','status','issue','extra_op','new_defaults','inventory'])
def test_terminal_tamper_rejected(case,field):
    r=complete(case)
    if field=='actions':r['actions']['SetTool']={}
    if field=='source_defaults':r['final_observation']['source_defaults']['finish']['GetChamferLength']+=1
    if field=='restrictions':r['final_observation']['source_restrictions']['GougeCheck']=False
    if field=='savebool':r['source_transition']['strict_save_return']=False
    if field=='status':r['status']='error'
    if field=='issue':r['issue']='injected'
    if field=='extra_op':r['final_observation']['route']['operations'].append(deepcopy(r['new_operation']))
    if field=='new_defaults':r['final_defaults']['finish']['GetChamferLength']+=1
    if field=='inventory':r['final_state']['operations'][-1]['native_id']=999
    with pytest.raises((ValueError,KeyError)):m.validate_saved(r)

def test_request_accepts_arbitrary_synthetic_ids(case):
    assert m.validate_request({'action':'insert_fresh_finish_definition','params':case.p})==case.p
    bad=deepcopy(case.p);bad['feature_native_id']=True
    with pytest.raises(ValueError):m.validate_request({'action':'insert_fresh_finish_definition','params':bad})

def test_other_mutator_journal_forbidden(case):
    with pytest.raises(ValueError):case.j.pending('GenerateToolpath')
    assert not case.j.marker.exists()
