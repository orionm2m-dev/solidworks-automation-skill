"""Bounded adapter tests: recorded R115 state/CL and one synthetic new route."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE))
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_pocket_rough_exports as m
from scripts import sw_cam_mill_generic_cl as core
from scripts import sw_cam_events
from test_chamfer_exports import Session

FIX=Path(__file__).parent/'fixtures/pocket_rough_exports'
ROUGH=('CUTTER/ 2,0,1,0,0,0,39,\nTLAXIS/ 0,0,1\nOPFEATSTART/R143\n'
       'RAPID/\nGOTO/ 0,14,50\nFEDRAT/ MMPM,25\nGOTO/ 0,14,12.1\nRAPID/\nGOTO/ 0,14,50\nOPFEATEND/R143\nFINI\n').encode('ascii')
BASE=(FIX/'prior_four.cl').read_bytes()
NEW=BASE[:BASE.rindex(b'FINI')]+ROUGH


def make_loaded(tmp_path):
    loaded=json.loads((FIX/'recorded_r115_context.json').read_text(encoding='utf-8'))
    source=tmp_path/'source.SLDPRT';source.write_bytes(b'Synthetic post-143-save fixture, not a native result')
    state=loaded['state'];state['document'].update(path=str(source),title=source.name,needs_save=False)
    state['saved_file_sha256']=loaded['source_sha256']=m._file_hash(source)
    byid={r['native_id']:r for r in state['operations']};state['operations']=[byid[i] for i in m.ORDER]
    for i,row in enumerate(state['operations']):row['operation_index']=i
    byid[143].update(toolpath_generated=True,toolpath_record_counts=[6])
    loaded.update(authority_kind=m.AUTHORITY,generated_pocket=dict(native_id=143,feature_native_id=79,
        tool_native_id=145,record_counts=[6],geometry_acceptance_complete=False),pocket_parameters={'143':{},'144':{}},pocket_startpoints={},
        pins=[],offline_export_proof_pins=[],bootstrap_export_pins=[],export_phase_retired_pins=[])
    for key,name in [('parent_pin','generation.json'),('group_marker_pin','generation-marker.json')]:
        p=tmp_path/name;p.write_text('{}');loaded[key]=m.common._pin(p);loaded['pins'].append(loaded[key])
    loaded['current_context_sha256']=m._digest(m.group.current_projection(loaded))
    prior=FIX/'recorded_r115_export_reduced.json'
    loaded.update(m.protected_reference(str(prior),m._file_hash(prior),str(FIX/'prior_four.cl'),loaded))
    return loaded,source


@pytest.fixture
def case(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    loaded,source=make_loaded(tmp_path)
    args=dict(process_id=123,expected_document_path=str(source),expected_source_sha256=m._file_hash(source),
        receipt_path=str(tmp_path/'export.json'),qualification_only=True,acknowledge_disposable_copy=True,message_policy='vendor_default')
    control=SimpleNamespace(calls=0,labels=[],result=0,fail=None,drift=None,output=NEW,event=False,after_native=None)
    class Machine:
        def GetController2(self):return [False,'fixture-controller',True]
        def SaveCLFile(self,path):
            control.calls+=1
            assert json.loads(Path(args['receipt_path']).read_text(encoding='utf-8'))['native_dispatch_pending'] is True
            marker=m.marker_path(source,args['expected_source_sha256'])
            assert json.loads(marker.read_text(encoding='utf-8'))['native_dispatch_pending'] is True
            Path(path).write_bytes(control.output)
            if control.fail:raise RuntimeError(control.fail)
            if control.after_native:control.after_native()
            return control.result
    machine=Machine()
    class Backend:
        def __init__(self,loaded,args,sw,clsid,tlb,report,persist,external_events):
            self.loaded,self.args,self.report,self.persist=loaded,args,report,persist
            self.native={'machine':machine};self.external_events=external_events
            self.ctx=SimpleNamespace(app=None,files=self.files,identity=self.identity)
        def files(self):m.common._check(self.loaded['pins'])
        def identity(self):
            if m._file_hash(source)!=self.args['expected_source_sha256']:raise ValueError('Changed source')
            return deepcopy(loaded['state']['document'])
        def boundary(self):self.files();self.identity();self.external_events(True)
        def capture_export(self,label):
            self.boundary();control.labels.append(label)
            observed=dict(state=deepcopy(loaded['state']),catalogue=m.cl.validate_catalogue_authority(loaded),
                selected_defaults=deepcopy(loaded['configured_contour']['defaults']),selected_feature=deepcopy(loaded['cone_observation']['feature']),
                settings=deepcopy(loaded['settings']),units=deepcopy(loaded['finish_payload']['unit_record']),
                binding=deepcopy(next(r['assigned_tool'] for r in loaded['state']['operations'] if r['native_id']==267)))
            if control.drift:control.drift(label,observed)
            return observed
    monkeypatch.setattr(m.cl,'ReadBackend',Backend)
    monkeypatch.setattr(core,'_bootstrap',lambda *a:object());monkeypatch.setattr(core,'_typed',lambda obj,*a:obj)
    class BoundSession(Session):
        def summary(self):
            r=super().summary();r['event_count']=1 if control.event else 0;return r
    monkeypatch.setattr(sw_cam_events,'CamMessageSession',BoundSession)
    return SimpleNamespace(loaded=loaded,source=source,args=args,root=tmp_path,control=control)


def run(f):
    return m.export_cl(object(),'fixture','fixture.tlb',loaded=f.loaded,args=f.args,output_path=str(f.root/'cl_output/out.cl'))


def test_one_native_export_preserves_actual_four_streams(case):
    r=run(case)
    assert r['readback_verified'] is True,r
    assert r['checkpoint_export_readback_verified'] is True and r['protected_streams_verified'] is True
    assert r['protected_stream_association']['added_operation_native_id']==143
    assert case.control.calls==1 and len(case.control.labels)==3
    assert r['before']==r['after'] and r['before']['selected_operation_native_id']==143
    assert r['before']['expected_ungenerated_operation_ids']==[195,196,144]
    assert [v['operation_native_id'] for v in r['before']['expected_generated_operations']]==[267,247,248,271,143]
    assert all(r[k] is False for k in ('GTP_attempted','GOP_attempted','model_saved','assignment_attempted','setter_attempted','geometry_verified'))
    assert r['full_tool_profile_capture_count']==0


@pytest.mark.parametrize('kind',['order','counts','tool','dirty','catalogue','defaults'])
def test_actual_shape_observation_drift_blocks_native(case,kind):
    def drift(label,obs):
        if kind=='order':obs['state']['operations'][0:2]=reversed(obs['state']['operations'][0:2])
        elif kind=='counts':obs['state']['operations'][6]['toolpath_record_counts']=[7]
        elif kind=='tool':obs['state']['operations'][6]['assigned_tool']['native_id']=249
        elif kind=='dirty':obs['state']['document']['needs_save']=True
        elif kind=='catalogue':obs['catalogue'][0]['CutDiameter']+=1
        elif kind=='defaults':obs['selected_defaults']['finish']['GetChamferLength']+=.1
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is False and case.control.calls==0


@pytest.mark.parametrize('value',[False,True,0,-1,6.0])
def test_actual_target_count_strict(case,value):
    case.loaded['generated_pocket']['record_counts']=[value]
    case.loaded['state']['operations'][6]['toolpath_record_counts']=[value]
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


@pytest.mark.parametrize('value',[None,False,True,1])
def test_once_native_return_no_retry(case,value):
    case.control.result=value;r=run(case)
    assert case.control.calls==1 and r['readback_verified'] is False
    case.args['receipt_path']=str(case.root/'retry.json')
    with pytest.raises(ValueError):run(case)
    assert case.control.calls==1


def test_native_exception_keeps_pending(case):
    case.control.fail='injected';r=run(case)
    assert case.control.calls==1 and r['native_dispatch_pending'] is True and r['readback_verified'] is False


def test_changed_prior_feed_fails_after_single_export(case):
    case.control.output=NEW.replace(b'MMPM,500.000000',b'MMPM,499.000000',1)
    r=run(case)
    assert case.control.calls==1 and r['protected_streams_verified'] is False and r['readback_verified'] is False
    assert r['status']=='uncertain'


def test_changed_prior_tool_cannot_hide_outside_block(case):
    case.control.output=NEW.replace(b'CUTTER/ 8.000000,0.000000,4.000000',b'CUTTER/ 8.000000,0.000000,3.900000',1)
    r=run(case)
    assert case.control.calls==1 and r['protected_streams_verified'] is False


def test_mass_only_roundoff_accepted_raw_preserved(case):
    def drift(label,obs):obs['state']['sw_reference']['solids'][0]['mass_raw'][0]*=1+1e-13
    case.control.drift=drift;r=run(case)
    assert r['readback_verified'] is True,r
    raw=json.loads(Path(r['observations_path']).read_text(encoding='utf-8'))
    assert raw['observations'][0]['state']['sw_reference']['solids'][0]['mass_raw']!=case.loaded['state']['sw_reference']['solids'][0]['mass_raw']


def test_prior_receipt_and_bytes_pinned(case):
    p=FIX/'recorded_r115_export_reduced.json'
    with pytest.raises(ValueError):m.protected_reference(str(p),'0'*64,str(FIX/'prior_four.cl'),case.loaded)


def test_terminal_source_drift_invalidates(case):
    case.control.after_native=lambda:case.source.write_bytes(b'changed')
    r=run(case)
    assert r['readback_verified'] is False and case.control.calls==1


def test_all_current_positions_required(case):
    case.loaded['state']['operations'][6]['operation_index']=0
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


def test_old_fixed_order_rejected(case):
    byid={r['native_id']:r for r in case.loaded['state']['operations']}
    case.loaded['state']['operations']=[byid[n] for n in [143,144,195,196,267,247,248,271]]
    with pytest.raises(ValueError):m.operation_contract(case.loaded)


@pytest.mark.parametrize('change',[(b'UNITS/ MM',b'UNITS/ INCH'),(b'BOX/ -1.592082',b'BOX/ -1.592083')])
def test_global_cl_declarations_protected(case,change):
    case.control.output=NEW.replace(*change,1);r=run(case)
    assert case.control.calls==1 and r['protected_streams_verified'] is False


def test_future_flat_loader_and_bounded_phase_retirement(case,monkeypatch):
    inherited=deepcopy(case.loaded)
    writer=case.root/'sw_cam_pocket_rough_apply.py';writer.write_text('completed writer fixture')
    inherited['pins']=[inherited['parent_pin']]
    for name in sorted(m.RETIRED)+['active_'+str(i)+'.py' for i in range(53)]:
        p=case.root/name
        if not p.exists():p.write_text('immutable phase fixture')
        inherited['pins'].append(m.common._pin(p))
    assert len(inherited['pins'])==63
    module=SimpleNamespace(__file__=str(writer),load_completed=lambda *a,**kw:deepcopy(inherited))
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_pocket_rough_apply',module)
    prior=FIX/'recorded_r115_export_reduced.json'
    result=m.load_checkpoint(case.loaded['parent_pin']['path'],case.loaded['parent_pin']['sha256'],process_id=123,
        expected_document_path=str(case.source),expected_source_sha256=m._file_hash(case.source),
        protected_cl_receipt_path=str(prior),protected_cl_receipt_sha256=m._file_hash(prior),protected_cl_path=str(FIX/'prior_four.cl'))
    assert len(result['pins'])<=64 and m.operation_contract(result)[-1]['toolpath_record_counts']==[6]
    assert len(result['export_phase_retired_pins'])==len(m.RETIRED)
    assert any(p['path']==str(writer.resolve()) for p in result['offline_export_proof_pins'])
    assert result['state']==case.loaded['state'] and result['parent_pin']==case.loaded['parent_pin']
    assert case.control.calls==0


def test_preservation_is_not_geometry_acceptance(case):
    result=m.preserved_streams(NEW,case.loaded)
    assert result['prior_four_complete_streams_unchanged'] is True
    assert result['new_rough_geometry_verified'] is False
