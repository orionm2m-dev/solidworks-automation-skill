"""One WIP export boundary, refusal and protected-state tests without CAD."""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os,sys,hashlib
import pytest
ROOT=Path(__file__).resolve().parents[1];RUNTIME=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(ROOT)))
sys.path.insert(0,str(RUNTIME));import scripts
MODULE_ROOT=Path(os.environ.get('SW_CAM_DEEP_CHECKPOINT_MODULE_ROOT',str(RUNTIME/'scripts')))
scripts.__path__.insert(0,str(MODULE_ROOT))
from scripts import sw_cam_deep_guide_wip as m


def binding():
    ids=list(m.authority.inspect.ORDER)+[401,403,405,407]
    rows=[dict(native_id=i,suppressed=False,toolpath_generated=i not in (195,196,144),
      toolpath_record_counts=[i+1]if i not in (195,196,144)else [])for i in ids]
    for row,(fid,kind)in zip(rows[13:],m.authority.writer.PAIRS):
        row.update(linked_feature_ids=[fid],mill_operation_type=kind)
    return {'operations':rows}


class Guard:
    def __init__(self,b):self.b=b
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def typed(self,obj,name):self.b.typed.append(name);return obj
    def read(self,obj,name):
        if name in ('GetDocType','MachType'):return 1
        return self.b.machine
    def dispatch_once(self,fn,persist_pending):persist_pending();return fn()
    def summary(self):return {'synthetic':True}


class Fake:
    session=None
    def __init__(self,plan,failure):
        self.plan,self.failure=plan,failure;self.machine=object();self.trace=[];self.typed=[]
        self.ctx=SimpleNamespace(app=object(),guard=lambda:Guard(self),identity=lambda:deepcopy(plan['loaded']['guide_parameters']['document']))
    def start(self):
        self.trace.append('start')
        if self.failure=='start':raise RuntimeError('cannot start')
    def capture_parameters(self,label):
        self.trace.append(label);r=deepcopy(self.plan['loaded']['guide_parameters']['expected_parameters'])
        if self.failure==label:r['parameters'].append({'unexpected':True})
        return r
    def finish(self):
        self.trace.append('finish')
        if self.failure=='cleanup':raise RuntimeError('event cleanup')
    def close(self):self.trace.append('close')


def setup(tmp_path,monkeypatch,failure=None):
    source=tmp_path/'saved.SLDPRT';source.write_bytes(b'saved source')
    doc=dict(path=str(source),title=source.name,type=1,needs_save=False)
    state=dict(binding=binding(),parameters=[{'saved':True}])
    p=dict(process_id=52,expected_document_path=str(source),expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),receipt_path=str(tmp_path/'receipt.json'))
    plan=dict(directory=tmp_path/'new_wip',canonical=(tmp_path/'new_wip').resolve(),marker=tmp_path/'marker.json',pin={'path':'corrected.json','sha256':'e'*64},abi={},expected=m.expected_generated(state['binding']),
        loaded=dict(pins=[],checkpoint_pins=[],guide_parameters=dict(document=doc,baseline=state['binding'],expected_parameters=state)))
    report=m.new_report(p,plan);backend=Fake(plan,failure)
    def native(obj,name,*args):
        assert obj is backend.machine and name=='CreateSTLOfWIPs2'
        assert args==tuple(report['native_parameters'])and args[1:]==('wip.stl','',0,0)
        backend.trace.append('native_export')
        assert plan['marker'].exists()
        if failure=='exception':raise RuntimeError('unknown export outcome')
        if failure!='empty':(plan['directory']/'wip.stl').write_bytes(b'synthetic STL')
        return False if failure=='false'else True
    monkeypatch.setattr(m,'_member',native)
    return backend,p,plan,report


def test_one_existing_path_wip_export_no_generation_save_or_parameter_change(tmp_path,monkeypatch):
    b,p,plan,r=setup(tmp_path,monkeypatch);result=m.run_backend(b,p,plan,r,lambda:None)
    assert result['status']=='review_required'and result['readback_verified']and result['export_files_verified']
    assert b.trace==['start','wip_before','native_export','wip_after','finish','close']
    assert result['native_call_count']==1 and len(result['files'])==1
    assert result['before']==result['after']
    assert not any(result[k]for k in ('GTP_attempted','GOP_attempted','AFR_attempted','model_saved','setter_attempted','assignment_attempted','simulation_attempted'))
    assert result['native_scope']=='all_wip_parts_all_setups'and result['single_operation_scope_claimed']is False
    assert 'ICWMachine5'in b.typed


@pytest.mark.parametrize('failure',['start','wip_before','exception','false','empty','wip_after','cleanup'])
def test_failure_never_replays_or_reports_verified_output(tmp_path,monkeypatch,failure):
    b,p,plan,r=setup(tmp_path,monkeypatch,failure);result=m.run_backend(b,p,plan,r,lambda:None)
    assert not result['readback_verified']and not result['export_files_verified']
    assert result['native_call_count']<2 and b.trace[-1]=='close'
    if failure in ('start','wip_before'):assert result['native_call_count']==0
    if failure in ('exception','false','empty'):assert 'wip_after'not in b.trace
    assert not any(result[k]for k in ('GTP_attempted','model_saved','setter_attempted'))


@pytest.mark.parametrize('bad',['missing','extra','reordered','emptycount','zerocount','boolean'])
def test_expected_route_is_exact_fourteen_positive_streams(bad):
    value=binding()
    if bad=='missing':value['operations'].pop()
    if bad=='extra':value['operations'].append(dict(native_id=999,toolpath_generated=True,toolpath_record_counts=[1]))
    if bad=='reordered':value['operations'].reverse()
    if bad=='emptycount':value['operations'][2]['toolpath_record_counts']=[]
    if bad=='zerocount':value['operations'][2]['toolpath_record_counts']=[0]
    if bad=='boolean':value['operations'][2]['toolpath_record_counts']=[True]
    with pytest.raises(ValueError):m.expected_generated(value)


def test_capture_rejects_source_tampering_before_export(tmp_path,monkeypatch):
    b,p,plan,r=setup(tmp_path,monkeypatch);Path(p['expected_document_path']).write_bytes(b'changed source')
    result=m.run_backend(b,p,plan,r,lambda:None)
    assert not result['native_call_attempted']and not result['readback_verified']


def test_existing_output_refuses_dispatch(tmp_path,monkeypatch):
    b,p,plan,r=setup(tmp_path,monkeypatch);plan['directory'].mkdir();(plan['directory']/'existing.stl').write_bytes(b'old')
    result=m.run_backend(b,p,plan,r,lambda:None)
    assert not result['native_call_attempted']and (plan['directory']/'existing.stl').read_bytes()==b'old'


def test_existing_marker_refuses_native_dispatch(tmp_path,monkeypatch):
    b,p,plan,r=setup(tmp_path,monkeypatch);plan['marker'].write_bytes(b'previous attempt')
    result=m.run_backend(b,p,plan,r,lambda:None)
    assert result['native_call_count']==0 and plan['marker'].read_bytes()==b'previous attempt'


def test_reader_is_existing_readonly_parameter_backend():
    assert m.authority.ParameterBackend.capture_snapshot is m.authority.writer.NativeBackend.capture_snapshot
    assert not any(hasattr(m.authority.ParameterBackend,n)for n in ('save','generate','set_candidate','assign'))
