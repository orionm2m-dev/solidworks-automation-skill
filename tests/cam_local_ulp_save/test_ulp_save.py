from copy import deepcopy
from pathlib import Path
import math,json,pytest
from scripts import sw_cam_local_ulp_save as m

@pytest.fixture(scope='module')
def original():
    # Synthetic unique21/12 shape; no project file or actual receipt dependency.
    operations=[dict(native_id=i,toolpath_record_counts=[100+i])for i in range(1,18)]
    parameters=[dict(operation_native_id=i,sentinel=i)for i in range(1,9)]
    targets=[]
    for index,oid in enumerate(m.IDS):
        operations.append(dict(native_id=oid,toolpath_record_counts=deepcopy(m.COUNTS[oid])))
        parameters.append(dict(operation_native_id=oid,nc=dict(feeds_compensation=dict(GetSpndlSpeed=math.nextafter(7100.,math.inf),XYFeed=math.nextafter(35.,math.inf),GetCNCComp=0))))
        targets.append(dict(operation_native_id=oid,operation_type=index%2,key='synthetic_'+str(oid)))
    return dict(generated=dict(binding=dict(operations=operations),parameters=parameters),learned_targets=targets)

def test_exact_original_eight_nextafter_preserves_raw(original):
    raw=deepcopy(original['generated']);before=deepcopy(raw)
    reference,proof=m.projection(raw,initial=True)
    assert raw==before and len(proof['fields'])==8
    assert all(v['ULP_distance']==1 for v in proof['fields'])
    assert all(v['raw']==math.nextafter(v['anchor'],math.inf)for v in proof['fields'])
    assert m.projection(raw,reference)[0]==reference

@pytest.mark.parametrize('direction',[-math.inf,0,math.inf])
def test_current_and_saved_bound_uses_nominal_anchor(original,direction):
    reference,_=m.projection(original['generated'],initial=True);raw=deepcopy(reference)
    for p in raw['parameters']:
        if p['operation_native_id']in m.IDS:
            for field,anchor in m.ANCHORS.items():p['nc']['feeds_compensation'][field]=anchor if direction==0 else math.nextafter(anchor,direction)
    assert m.projection(raw,reference)[0]==reference

@pytest.mark.parametrize('fault',['two_up','two_down','nan','inf','bool','integer','other_nc','other_operation','pathcount'])
def test_all_other_drift_or_more_than_one_ulp_rejected(original,fault):
    reference,_=m.projection(original['generated'],initial=True);raw=deepcopy(original['generated']);rows={p['operation_native_id']:p for p in raw['parameters']};nc=rows[344]['nc']['feeds_compensation']
    if fault=='two_up':nc['XYFeed']=math.nextafter(math.nextafter(35.,math.inf),math.inf)
    elif fault=='two_down':nc['XYFeed']=math.nextafter(math.nextafter(35.,-math.inf),-math.inf)
    elif fault=='nan':nc['XYFeed']=float('nan')
    elif fault=='inf':nc['XYFeed']=float('inf')
    elif fault=='bool':nc['XYFeed']=True
    elif fault=='integer':nc['XYFeed']=35
    elif fault=='other_nc':nc['GetCNCComp']=1
    elif fault=='other_operation':raw['parameters'][0]['sentinel']='new unplanned field'
    else:raw['binding']['operations'][-1]['toolpath_record_counts']=[47]
    with pytest.raises(ValueError):m.projection(raw,reference)

def test_initial_precursor_requires_exact_upward_ulp(original):
    raw=deepcopy(original['generated']);next(p for p in raw['parameters']if p['operation_native_id']==344)['nc']['feeds_compensation']['XYFeed']=35.
    with pytest.raises(ValueError):m.projection(raw,initial=True)

@pytest.mark.parametrize('method',['insert','assign','set_field','set_nc','generate'])
def test_mutation_methods_forbidden(method):
    backend=object.__new__(m.NativeBackend)
    with pytest.raises(ValueError):getattr(backend,method)()

def workflow(original,tmp_path,monkeypatch,*,fail_save=False,bad_before=False,bad_saved=False):
    expected,_=m.projection(original['generated'],initial=True);raw=deepcopy(original['generated']);targets=deepcopy(original['learned_targets'])
    pins={key:dict(path=key,sha256='c'*64)for key in ['qualified_receipt_pin','rebind_receipt_pin','recipe_pin','optimizer_receipt_pin']}
    r=dict(scope=m.SCOPE,source_path=str(tmp_path/'part.sldprt'),source_sha256='a'*64,ownership=dict(process_id=77),request=dict(process_id=77),phase_proof_checks=[],**pins)
    j=m.Journal(r,tmp_path/'receipt.json',tmp_path/'marker.json')
    l=dict(source_sha256='a'*64,ownership=dict(process_id=77),guide_parameters=dict(document=dict(path=r['source_path'],needs_save=True)),optimization=dict(targets=targets,prior_cl={}),ulp_continuation=dict(canonical_generated=expected),**pins)
    class Backend:
        def __init__(self):self.calls=[];self.capture_count=0
        def start(self):self.calls.append('start');r['phase_proof_checks'].append(dict(phase='before_native_start',verified=True))
        def boundary(self):pass
        def capture_snapshot(self,*a,**k):
            self.capture_count+=1;self.calls.append('capture');value=deepcopy(raw if self.capture_count==1 else expected)
            if bad_before and self.capture_count==1:value['binding']['operations'][-1]['toolpath_record_counts']=[99]
            if bad_saved and self.capture_count==2:next(p for p in value['parameters']if p['operation_native_id']==344)['nc']['feeds_compensation']['XYFeed']=math.nextafter(math.nextafter(35.,math.inf),math.inf)
            return value
        def save(self):
            self.calls.append('save');r['phase_proof_checks'].append(dict(phase='before_save',verified=True))
            if fail_save:raise RuntimeError('unknown Save outcome')
            return 0
        def saved_hash(self,stage):r['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,strict_save_return=0,document=dict(path=r['source_path'],needs_save=False));return 'b'*64
        def export(self,*a):self.calls.append('export');return dict(source_sha256='b'*64)
        def finish(self):self.calls.append('finish');r['phase_proof_checks'].append(dict(phase='after_export_and_cleanup',verified=True));r['messages']=dict(subscribed=True,disconnected=True,active=False,event_count=0)
        def close(self):self.calls.append('close')
        def generate(self,*a):pytest.fail('GTP must never run')
        def set_field(self,*a):pytest.fail('Setter must never run')
        def set_nc(self,*a):pytest.fail('NC setter must never run')
    b=Backend();monkeypatch.setattr(m.opt.generation,'close_checked',lambda b,r:b.close());monkeypatch.setattr(m.opt.cl,'verify_saved',lambda *a:dict(protected14=True))
    return b,j,l

def test_save_once_raw_bounded_change_and_no_gtp_or_setters(original,tmp_path,monkeypatch):
    b,j,l=workflow(original,tmp_path,monkeypatch);r=m.run_once(b,j,l)
    assert r['readback_verified'],r.get('issue')
    assert b.calls==['start','capture','save','capture','export','finish','close']
    assert list(r['actions'])==['SaveActiveDocument']and r['GTP_attempted']is False and r['parameter_setter_attempted']is False
    assert r['before']!=r['saved']and r['save_stage']['before']==r['save_stage']['after']
    assert m.validate_completed(r,l)['Save']==1
    with pytest.raises(ValueError):m.run_once(b,j,l)
    assert b.calls.count('save')==1

@pytest.mark.parametrize('fault',['bad_before','fail_save','bad_saved'])
def test_unknown_or_bad_state_never_replays_or_exports(original,tmp_path,monkeypatch,fault):
    b,j,l=workflow(original,tmp_path,monkeypatch,**{fault:True});r=m.run_once(b,j,l)
    assert r['readback_verified']is False and'export'not in b.calls
    assert b.calls.count('save')==(0 if fault=='bad_before'else 1)
    with pytest.raises(ValueError):m.run_once(b,j,l)
