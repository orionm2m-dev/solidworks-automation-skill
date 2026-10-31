"""Saved rough-pocket WIP export tests using the existing native-call core."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_pocket_rough_wip as m
spec=importlib.util.spec_from_file_location('wip_saved_rough_fixture',ROOT/'tests/test_pocket_rough_exports.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


@pytest.fixture
def case(tmp_path,monkeypatch):
    f=t.case.__wrapped__(tmp_path,monkeypatch)
    f.loaded['wip_phase_retired_pins']=[]
    f.control.result=True
    f.control.extra=False; f.control.empty=False; f.control.cleanup_fail=False
    original=t.m.cl.ReadBackend
    class Machine:
        def CreateSTLOfWIPs2(self,directory,name,coordinate,units,quality):
            f.control.calls+=1
            assert coordinate=='' and units==0 and quality==0
            marker=m.marker_path(f.source,f.args['expected_source_sha256'],143)
            assert json.loads(marker.read_text(encoding='utf-8'))['native_dispatch_pending'] is True
            assert json.loads(Path(f.args['receipt_path']).read_text(encoding='utf-8'))['native_dispatch_pending'] is True
            Path(directory,name).write_text('' if f.control.empty else 'solid fixture\nendsolid fixture\n')
            if f.control.extra:Path(directory,'unexpected.txt').write_text('unexpected')
            if f.control.fail:raise RuntimeError(f.control.fail)
            if f.control.after_native:f.control.after_native()
            return f.control.result
    class Guard:
        def __init__(self,backend):self.backend=backend
        def __enter__(self):self.backend.boundary();return self
        def __exit__(self,*args):self.backend.boundary()
        def typed(self,obj,name):assert name=='ICWMachine5';return obj
        def dispatch_once(self,call,*,persist_pending):persist_pending();self.backend.boundary();return call()
        def summary(self):return {'invalid':False}
    class Backend(original):
        def __init__(self,loaded,args,sw,clsid,tlb,report,persist):
            super().__init__(loaded,args,sw,clsid,tlb,report,persist,self.events)
            self.native={'machine':Machine()};self.ctx.guard=lambda:Guard(self)
            self.session=None
        def events(self,active=True):
            assert not f.control.event
            if self.session is not None:
                self.report['messages']=self.session.summary();assert self.session.active is active
        def start(self):self.session=t.Session();self.session.__enter__();self.boundary()
        def finish(self):self.session.__exit__();self.events(False);self.files();self.identity()
        def close(self):
            if self.session is not None and self.session.active:self.session.__exit__()
            if f.control.cleanup_fail:raise RuntimeError('cleanup failure')
    monkeypatch.setattr(m,'ReadBackend',Backend)
    return f


def run(f):
    return m.export_wip(object(),'fixture','fixture.tlb',loaded=f.loaded,args=f.args,
                        project_root=str(f.root),output_dir=str(f.root/'wip_output'))


def test_one_existing_wip_export_keeps_route_and_does_not_claim_fidelity(case):
    r=run(case)
    assert r['readback_verified'] is True,r
    assert r['export_files_verified'] is True and r['checkpoint_export_readback_verified'] is True
    assert r['phase_proofs_verified_after_export'] is True
    assert case.control.calls==1 and case.control.labels==['before','after']
    assert r['native_parameters'][-2:]==[0,0]
    assert r['before']==r['after']
    assert r['export_quality_label']=='FINE' and r['mesh_error_bound_qualified'] is False
    assert all(r[k] is False for k in ('GTP_attempted','GOP_attempted','model_saved','setter_attempted',
        'geometry_verified','production_qualified','manufacturing_tolerance_qualified'))
    assert m._file_hash(case.source)==case.args['expected_source_sha256']


@pytest.mark.parametrize('value',[None,False,0,1,0.0,'true',float('nan'),object()])
def test_only_strict_true_accepted_and_repeat_is_forbidden(case,value):
    case.control.result=value;r=run(case)
    assert r['readback_verified'] is False and r['status']=='uncertain'
    assert case.control.calls==1 and case.control.labels==['before']
    before=Path(case.args['receipt_path']).read_bytes()
    case.args['receipt_path']=str(case.root/'another.json')
    with pytest.raises(ValueError):run(case)
    assert case.control.calls==1 and (case.root/'export.json').read_bytes()==before


def test_native_exception_keeps_pending_attempt(case):
    case.control.fail='injected';r=run(case)
    assert r['native_dispatch_pending'] is True and r['readback_verified'] is False
    assert case.control.calls==1 and case.control.labels==['before']


@pytest.mark.parametrize('kind',['empty','extra'])
def test_nonempty_stl_only_result_required(case,kind):
    setattr(case.control,kind,True);r=run(case)
    assert r['readback_verified'] is False and case.control.calls==1
    assert case.control.labels==['before']


@pytest.mark.parametrize('label',['before','after'])
def test_catalogue_or_parameter_drift_invalidates_export(case,label):
    def drift(actual,observed):
        if actual==label:observed['selected_defaults']['finish']['GetChamferLength']+=.1
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is False and case.control.calls==(1 if label=='after' else 0)
    raw=json.loads(Path(case.args['receipt_path']).with_suffix('.observations.json').read_text(encoding='utf-8'))
    assert raw['observations'][-1]['selected_defaults']['finish']['GetChamferLength']!=case.loaded['configured_contour']['defaults']['finish']['GetChamferLength']


def test_cleanup_failure_prevents_public_success(case):
    case.control.cleanup_fail=True;r=run(case)
    assert case.control.calls==1 and r['readback_verified'] is False
    assert r['checkpoint_export_readback_verified'] is False and r['export_files_verified'] is False


def test_phase_proof_change_after_call_invalidates_result(case):
    p=case.root/'offline.json';p.write_text('{}')
    case.loaded['offline_export_proof_pins']=[m.common._pin(p)]
    case.control.after_native=lambda:p.write_text('changed')
    r=run(case)
    assert case.control.calls==1 and r['readback_verified'] is False
    assert r['phase_proofs_verified_after_export'] is False


def test_wip_marker_does_not_consume_cl_export(case):
    c=m.rough.marker_path(case.source,case.args['expected_source_sha256'])
    w=m.marker_path(case.source,case.args['expected_source_sha256'],143)
    assert c!=w
    r=run(case)
    assert r['readback_verified'] is True and w.is_file() and not c.exists()


def test_wip_closure_retires_only_inactive_cl_core(case,monkeypatch):
    names=['sw_cam_mill_generic_cl.py','sw_cam_thread_postprocess.py','sw_cam_operation_profile.py']
    for name in names:
        p=case.root/name;p.write_text('immutable phase proof');case.loaded['pins'].append(m.common._pin(p))
    monkeypatch.setattr(m.rough,'load_checkpoint',lambda *a,**kw:case.loaded)
    result=m.load_checkpoint('fixture','a'*64)
    assert {Path(p['path']).name for p in result['wip_phase_retired_pins']}==set(names)
    assert not set(names).intersection(Path(p['path']).name for p in result['pins'])
    assert all(any(x['sha256']==p['sha256'] for x in result['offline_export_proof_pins'])
               for p in result['wip_phase_retired_pins'])


@pytest.mark.parametrize('kind',['order','rough_count','rough_tool','dirty','catalogue','defaults'])
@pytest.mark.parametrize('label',['before','after'])
def test_exact_current_route_drift_blocks_public_success(case,kind,label):
    def drift(phase,observed):
        if phase!=label:return
        if kind=='order':observed['state']['operations'][0:2]=reversed(observed['state']['operations'][0:2])
        elif kind=='rough_count':observed['state']['operations'][6]['toolpath_record_counts']=[7]
        elif kind=='rough_tool':observed['state']['operations'][6]['assigned_tool']['native_id']=249
        elif kind=='dirty':observed['state']['document']['needs_save']=True
        elif kind=='catalogue':observed['catalogue'][0]['CutDiameter']+=1
        elif kind=='defaults':observed['selected_defaults']['finish']['GetChamferLength']+=.1
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is False
    assert case.control.calls==(0 if label=='before' else 1)
    assert r['checkpoint_export_readback_verified'] is False


def test_actual_count_contract_is_saved_authority_not_fixed_contour(case):
    case.loaded['generated_pocket']['record_counts']=[31196]
    case.loaded['state']['operations'][6]['toolpath_record_counts']=[31196]
    r=run(case)
    assert r['readback_verified'] is True,r
    assert r['expected_generated_operations']==[
        {'operation_native_id':267,'toolpath_record_counts':[760]},
        {'operation_native_id':247,'toolpath_record_counts':[191]},
        {'operation_native_id':248,'toolpath_record_counts':[74]},
        {'operation_native_id':271,'toolpath_record_counts':[29]},
        {'operation_native_id':143,'toolpath_record_counts':[31196]}]
    assert r['expected_ungenerated_operation_ids']==[195,196,144]
    assert json.loads(Path(r['marker_path']).read_text(encoding='utf-8'))['operation_native_id']==143
    assert r['single_operation_scope_claimed'] is False
    assert r['native_scope']=='all_wip_parts_all_setups'


def test_mass_roundoff_raw_preserved_and_normalized_once(case):
    def drift(label,observed):observed['state']['sw_reference']['solids'][0]['mass_raw'][0]*=1+1e-13
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is True,r
    raw=json.loads(Path(r['observations_path']).read_text(encoding='utf-8'))
    assert raw['observations'][0]['state']!=r['before']
    assert r['before']==r['after']==case.loaded['state']


def test_source_change_after_native_prevents_terminal_success(case):
    case.control.after_native=lambda:case.source.write_bytes(b'changed source')
    r=run(case)
    assert case.control.calls==1 and r['readback_verified'] is False
