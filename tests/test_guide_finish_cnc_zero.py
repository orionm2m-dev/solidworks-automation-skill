"""Two-contour candidate protocol and real inherited native boundaries, no CAD."""
from copy import deepcopy
from pathlib import Path
from types import ModuleType
import importlib.util,os,sys
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',ROOT))
sys.path.insert(0,str(RUNTIME));import scripts;scripts.__path__.insert(0,str(ROOT/'scripts'))
from scripts import sw_cam_guide_finish_cnc_zero as m
spec=importlib.util.spec_from_file_location('prior_generated_tests',RUNTIME/'tests/test_guide_group_generation.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)


def fixture():
    state,targets=old.fixture()
    for row in state['binding']['operations']:
        if row['native_id']in(322,324,326,328):row.update(toolpath_generated=True,toolpath_record_counts=[row['native_id']+5])
    for row in state['parameters']:
        if row['operation_native_id']in m.IDS:
            row['nc']['feeds_compensation']['GetCNCComp']=1;row['nc']['feeds_compensation']['GetTlpComp']=1
            row['protected_finish']['compensation']=[1,1]
    return state,targets


class Fake(old.Fake):
    def set_candidate(self,target,expected,state,pending):
        oid=target['operation_native_id'];pending();self.trace.append(('NC',oid))
        if self.failure=='setter_exception':raise RuntimeError('unknown setter result')
        if self.failure=='setter_return':return -1
        row=m.nc_row(self.state,oid);row['nc']['feeds_compensation']['GetCNCComp']=0;row['protected_finish']['compensation'][1]=0
        if self.failure=='offset':row['nc']['feeds_compensation']['GetTlpComp']=0
        if self.failure=='other_parameter':self.state['parameters'][0]['nc']['unexpected']=True
        if self.failure=='invalidate':
            row=next(v for v in self.state['binding']['operations']if v['native_id']==oid)
            row.update(toolpath_generated=False,toolpath_record_counts=[])
        return 0
    def regenerate(self,target,expected,state,pending):return self.generate(target,pending)


def setup(tmp_path,monkeypatch,failure=None):
    state,targets=fixture();pin={'path':'generated.json','sha256':'e'*64}
    loaded=dict(guide_parameters={'expected_parameters':deepcopy(state),'targets':targets,'configuration':{'synthetic':True}},
        generated={'saved_cl':{'old_signatures':list(range(8)),'new_signatures':[1,2]}},generated_checkpoint_pin=pin)
    report=dict(source_path='synthetic.SLDPRT',source_sha256='a'*64,generated_checkpoint_pin=pin,request={'process_id':52},ownership={'process_id':52})
    journal=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    monkeypatch.setattr(m.cl,'_verified',lambda value:True)
    def protected(a,b):
        if failure=='protected_cl':raise ValueError('protected path changed')
        return {'protected_eight_complete_streams_verified':True}
    def absent(value):
        if failure=='cutcom':raise ValueError('CUTCOM remains')
        return {'finish_CL_without_CUTCOM_verified':True}
    monkeypatch.setattr(m.finish_cl,'verify_protected_eight',protected)
    monkeypatch.setattr(m.finish_cl,'verify_finish_without_cutcom',absent)
    monkeypatch.setattr(m.cl,'verify_all',lambda a,b:{'unchanged':True})
    return Fake(state,report,failure),journal,loaded


@pytest.mark.parametrize('failure',[None,'invalidate'])
def test_two_nc_changes_then_only_two_regenerations_then_one_save(tmp_path,monkeypatch,failure):
    b,j,l=setup(tmp_path,monkeypatch,failure);r=m.run_backend(b,j,l)
    assert r['status']=='saved_finish_cnc_candidate_review_required',r.get('issue')
    assert [v for v in b.trace if isinstance(v,tuple)]==[('NC',324),('GTP',324),('NC',328),('GTP',328)]
    assert b.trace.count('save')==1 and 'cl:before'not in b.trace
    assert r['empirical_finish_cutcom_absence_verified']and r['protected_cl_verified']and r['saved_cl_verified']
    assert r['changed_operation_ids']==r['regenerated_operation_ids']==[324,328]
    assert r['saved_checkpoint_context']['prior_generated_checkpoint_pin']==l['generated_checkpoint_pin']
    assert not r['production_qualified']and not r['numeric_enum_meaning_qualified']and not r['SetTool_attempted']


@pytest.mark.parametrize('failure',['before','setter_exception','setter_return','offset','other_parameter','exception','return','old_path','parameters','protected_cl','cutcom','export_generated','save_return','saved_delta','export_saved'])
def test_failure_prefix_never_replays_or_saves_unqualified_result(tmp_path,monkeypatch,failure):
    b,j,l=setup(tmp_path,monkeypatch,failure);r=m.run_backend(b,j,l)
    assert not r['readback_verified']and not r['continuation_ready']
    assert r['model_saved']is(failure in ('saved_delta','export_saved'))
    gtps=[v for v in b.trace if isinstance(v,tuple)and v[0]=='GTP']
    assert all(v[1]in m.IDS for v in gtps)and len(gtps)<=2
    if failure in ('before','setter_exception','setter_return','offset','other_parameter'):assert gtps==[]
    if failure not in ('save_return','saved_delta','export_saved'):assert 'save'not in b.trace
    bytes_before=(j.receipt.read_bytes(),j.marker.read_bytes()if j.marker.exists()else None)
    with pytest.raises(ValueError):m.run_backend(b,j,l)
    assert bytes_before==(j.receipt.read_bytes(),j.marker.read_bytes()if j.marker.exists()else None)


@pytest.mark.parametrize('oid',[267,322,326,328])
def test_nonselected_paths_are_protected_at_each_candidate_stage(oid):
    before,_=fixture();actual=deepcopy(before)
    actual['parameters']=m.expected_parameters(before,[324])
    next(v for v in actual['binding']['operations']if v['native_id']==oid)['toolpath_record_counts']=[999]
    with pytest.raises(ValueError):m.verify_snapshot(before,actual,[324],{})


def test_readback_requires_both_nc_aliases_and_preserves_feed():
    before,_=fixture();actual=deepcopy(before)
    m.nc_row(actual,324)['nc']['feeds_compensation']['GetCNCComp']=0
    with pytest.raises(ValueError):m.verify_snapshot(before,actual,[324],{})
    actual['parameters']=m.expected_parameters(before,[324]);m.verify_snapshot(before,actual,[324],{})
    m.nc_row(actual,324)['nc']['feeds_compensation']['XYFeed']+=1
    with pytest.raises(ValueError):m.verify_snapshot(before,actual,[324],{})


def constructed(tmp_path):
    previous=old.constructed(tmp_path)
    return m.NativeBackend(previous.loaded,previous.args,previous.sw,previous.clsid,previous.typelib_path,{},lambda:None)


def test_actual_constructor_and_start_preserve_capture_module(tmp_path,monkeypatch):
    b=constructed(tmp_path);assert isinstance(b.capture,ModuleType)
    assert not[k for k in vars(b)if callable(getattr(type(b),k,None))]
    calls=[];b.ctx.files=lambda:calls.append('files');b.ctx.identity=lambda:calls.append('identity')
    class Entered(Exception):pass
    def bootstrap(*a):calls.append('bootstrap');raise Entered()
    monkeypatch.setattr(b.capture.cone,'_bootstrap',bootstrap)
    with pytest.raises(Entered):b.start()
    assert calls==['files','identity','bootstrap']


def test_actual_bound_setter_passes_exact_fresh_state_and_pending(tmp_path,monkeypatch):
    b=constructed(tmp_path);t={'operation_native_id':324};expected={'raw':1};state={'generated':True,'record_counts':[116]};seen=[]
    def setter(backend,target,actual,pending,path_state=None):
        assert backend is b and target is t and actual is expected and path_state is state
        pending();seen.append('native');return 0
    monkeypatch.setattr(m.candidate,'set_raw_zero_candidate',setter)
    assert b.set_candidate(t,expected,state,lambda:seen.append('pending'))==0 and seen==['pending','native']