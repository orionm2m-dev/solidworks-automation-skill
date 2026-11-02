from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json, pytest
from scripts import sw_cam_saved18_serial_dirty_verify as m

@pytest.fixture
def case(tmp_path,monkeypatch):
    document=dict(path=str(tmp_path/'source.SLDPRT'),title='source',type=1,needs_save=True)
    p={k:None for k in m.PARAMS}
    p.update(process_id=25208,expected_document_path=document['path'],expected_source_sha256='a'*64,receipt_path=str(tmp_path/'receipt.json'),saved_cl_path=str(tmp_path/'export'/'saved.cl'),host_failure_sha256='b'*64)
    l=dict(ownership=dict(process_id=25208,create_time=1793643385.852),serial_verification={},qualified_authority_pin={},pins=[],phase_proof_pins=[],pin_partition={},guide_parameters=dict(document=document),current_snapshot=dict(binding={},parameters=[]))
    q=dict(saved_cl=dict(output=dict(path='old.cl',sha256='c'*64,bytes=20)))
    prepared=(p,l,q,'unused.tlb',Path(p['receipt_path']),m.marker_path(p))
    class Backend:
        def __init__(self):self.calls=[];self.ctx=SimpleNamespace(identity=lambda:deepcopy(document));self.report=None
        def start(self):self.calls.append('start')
        def boundary(self):self.calls.append('boundary')
        def capture_snapshot(self,*a,**k):self.calls.append('capture');return deepcopy(l['current_snapshot'])
        def finish(self):self.calls.append('finish')
        def save(self):raise AssertionError('Save forbidden')
        def generate(self,*a):raise AssertionError('GTP forbidden')
        def set_field(self,*a):raise AssertionError('setter forbidden')
    b=Backend()
    def export(backend,label,binding,path,diagnostic):
        b.calls.append('export');diagnostic['output']=deepcopy(q['saved_cl']['output'])
    monkeypatch.setattr(m.opt.cl,'export_current_cl',export)
    monkeypatch.setattr(m.opt.prior,'_file_hash',lambda p:'a'*64)
    monkeypatch.setattr(m.opt.generation,'close_checked',lambda b,r:b.calls.append('close'))
    return prepared,b,document

def test_serial_once_success_no_mutation(case):
    prep,b,doc=case;r=m.run_prepared(prep,backend=b)
    assert r['status']=='saved_eighteen_serial_dirty_verified'
    assert b.calls.count('capture')==1 and b.calls.count('export')==1
    assert doc['needs_save'] is True
    assert [x['label']for x in r['document_boundaries']]==['before_parameters','after_parameters','after_export']
    assert all(r[k]is False for k in ('model_saved','GTP_attempted','mutation_attempted','host_read_attempted','host_load_attempted','production_qualified'))
    with pytest.raises(ValueError):m.run_prepared(prep,backend=b)
    assert b.calls.count('capture')==1

def test_dirty_change_stops_before_capture(case):
    prep,b,doc=case;doc['needs_save']=False;r=m.run_prepared(prep,backend=b)
    assert r['status']=='error'and'capture'not in b.calls and'export'not in b.calls

def test_snapshot_change_stops_before_export(case):
    prep,b,doc=case;b.capture_snapshot=lambda *a,**k:dict(changed=True)
    r=m.run_prepared(prep,backend=b)
    assert r['status']=='error'and'export'not in b.calls and r['model_saved']is False

def test_source_change_stops_before_capture(case,monkeypatch):
    prep,b,doc=case;monkeypatch.setattr(m.opt.prior,'_file_hash',lambda p:'d'*64)
    r=m.run_prepared(prep,backend=b)
    assert r['status']=='error'and'capture'not in b.calls and'export'not in b.calls

def test_cl_hash_change_is_not_verified(case,monkeypatch):
    prep,b,doc=case
    def export(*args):args[-1]['output']=dict(sha256='d'*64,bytes=20)
    monkeypatch.setattr(m.opt.cl,'export_current_cl',export)
    r=m.run_prepared(prep,backend=b)
    assert r['status']=='error'and r['readback_verified']is False and r['persistence_after_reopen_verified']is False

@pytest.mark.parametrize('method',['insert','assign','set_field','set_nc','generate','save'])
def test_readonly_mutation_entrypoints_forbidden(method):
    backend=object.__new__(m.ReadOnlyParameters)
    with pytest.raises(ValueError):getattr(backend,method)()

@pytest.mark.parametrize('live,accepted',[(62,True),(63,False)])
def test_live64_bound_includes_current_source(monkeypatch,live,accepted,tmp_path):
    pins=[dict(path=str(tmp_path/str(i)),sha256='a'*64,bytes=1)for i in range(live)]
    loaded={}
    def partition(l,extra):l.update(pins=pins,phase_proof_pins=[],pin_partition={})
    monkeypatch.setattr(m.opt,'partition_pins',partition);monkeypatch.setattr(m.common,'_check',lambda p:None)
    if accepted:
        m.partition(loaded,[]);assert loaded['pin_partition']['maximum_with_source']==64
    else:
        with pytest.raises(ValueError):m.partition(loaded,[])

@pytest.fixture
def failed():
    original=dict(params=dict(process_id=25208));loaded=dict(ownership=dict(process_id=25208),source_sha256='a'*64)
    r=dict(scope=m.dirty.SCOPE,status='error',phase='finished',module_pin=dict(sha256=m.DIRTY_SHA),read_only=True,identity_attempted=True,identity=dict(loaded_artifact='old'),ownership=loaded['ownership'],source_sha256=loaded['source_sha256'],request=deepcopy(original['params']))
    r.update({k:False for k in ('mutation_attempted','model_saved','GTP_attempted','host_load_attempted','registration_attempted','readback_verified','persistence_after_reopen_verified','automatic_replay','production_qualified')})
    return r,loaded,original

def test_failed_host_zero_cam_is_explicit(failed):
    result=m.failed_host_contract(*failed)
    assert result['CAM_read_attempted']is False and result['host_native_compatibility_qualified']is False

@pytest.mark.parametrize('field',['events_before','events_after','mill_read_attempted','cl_export','cleanup_issue'])
def test_failed_host_cam_or_uncertain_cleanup_cannot_replay(failed,field):
    failed[0][field]=False
    with pytest.raises(ValueError):m.failed_host_contract(*failed)

@pytest.mark.parametrize('field',['model_saved','GTP_attempted','mutation_attempted','host_load_attempted'])
def test_failed_host_mutation_cannot_replay(failed,field):
    failed[0][field]=True
    with pytest.raises(ValueError):m.failed_host_contract(*failed)
