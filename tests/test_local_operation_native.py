from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib
import pytest
from cam_public_test_support import add_runtime, required_module, required_test_module
R=add_runtime()
engine=required_module('sw_cam_local_operation_group')
native=required_module('sw_cam_local_operation_native')
cl=required_module('sw_cam_local_operation_cl')
guard_module=required_module('sw_cam_dispatch_guard')
fixture=required_test_module('test_local_operation_group').fixture


def loaded_fixture():
    b,p,_,_=fixture()
    return dict(guide_parameters=dict(document=dict(path='synthetic.sldprt',needs_save=False),expected_parameters=b),
        configuration_tool=p['tool'],local_plan=p,local_feature_owners={k:69 for k in b['binding']['features']})


def test_actual_backend_constructor_without_com():
    loaded=loaded_fixture();backend=native.NativeBackend(loaded,{},None,None,'metadata',{},lambda:None,
        before_generate=lambda *a:None,exporter=lambda *a:None)
    assert len(backend.protected_targets)==8 and backend.learned==[]
    assert callable(backend.capture_snapshot) and callable(backend.capture_binding)
    assert not callable(backend.capture)  # inherited metadata module, never shadowed
    assert backend.ctx.expected_document==loaded['guide_parameters']['document']
    assert backend.session is None and backend.session_active is False


def test_unknown_target_rejected_before_read():
    backend=native.NativeBackend(loaded_fixture(),{},None,None,'metadata',{},lambda:None,before_generate=lambda *a:None,exporter=lambda *a:None)
    class NoRead:
        def read(self,*a):raise AssertionError('must reject before native getter')
    with pytest.raises(ValueError):backend.target(NoRead(),dict(operation_native_id=999,feature_native_id=900,operation_type=0))


def make_guard(tmp_path,monkeypatch,counts):
    source=tmp_path/'part.sldprt';source.write_bytes(b'synthetic source');proof=tmp_path/'proof';proof.write_bytes(b'proof')
    pin=lambda p:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    monkeypatch.setattr(guard_module.ScopedCamDispatchGuard,'_identity',lambda self:None)
    def typed(raw,name,path):counts['QI']+=1;return raw
    monkeypatch.setattr(guard_module,'_typed',typed)
    return guard_module.ScopedCamDispatchGuard(None,'metadata',process_id=1,
        expected_document=dict(path=str(source),title=source.name,type=1,needs_save=False),source_sha256=pin(source)['sha256'],
        evidence_pins=[pin(proof)],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=lambda:None)


def test_real_guard_gtp_prebind_and_false_diagnostics(tmp_path,monkeypatch):
    counts=dict(QI=0,vendor=0,pending=0,nc=0);g=make_guard(tmp_path,monkeypatch,counts);raw=object();tool={'native_id':700}
    target=dict(operation_native_id=1000,feature_native_id=900,assigned_tool=tool)
    backend=native.NativeBackend.__new__(native.NativeBackend);backend.ctx=SimpleNamespace(guard=lambda:g,app=object());backend.doc=object()
    backend.target=lambda *a:(raw,object())
    backend.outcome=lambda _:dict(operation_native_id=1000,feature_native_id=900,background_over_before=False,background_over_after=False,
        generated=False,generated_for_feature=False,record_counts=[])
    def preflight(*a):counts['nc']+=1
    backend.before_generate=preflight
    monkeypatch.setattr(native.generation,'read_generic_tool',lambda *a:(tool,raw))
    # The real guard performs this read through its own member boundary.
    monkeypatch.setattr(guard_module,'_member',lambda obj,name,*a:False if name=='IsBackgroundProcessForGTPOver' else None)
    def vendor(obj,name,*args):assert obj is raw and name=='GenerateToolpath';counts['vendor']+=1;return 0
    monkeypatch.setattr(native.generation,'_member',vendor)
    def pending():counts['pending']+=1
    assert backend.generate(target,pending)==0
    assert counts==dict(QI=1,vendor=1,pending=1,nc=1)
    assert g._claimed and g._attempted and g._returned


def generated_binding():
    b,p,_,_=fixture();current=deepcopy(b['binding']);targets=[]
    for i,r in enumerate(p['rows']):
        oid=1000+i;target=dict(r,operation_native_id=oid,assigned_tool=p['tool']);targets.append(target)
        current['operations'].append(dict(native_id=oid,setup_index=0,setup_native_id=93,operation_index=17+i,
            mill_operation_type=r['operation_type'],linked_feature_ids=[r['feature_native_id']],assigned_tool=deepcopy(p['tool']),
            suppressed=False,toolpath_generated=True,toolpath_record_counts=[100]))
    current['operation_setups'][0]['operation_count']=21
    return b['binding'],current,targets


def test_dynamic_eighteen_cl_contract():
    before,after,targets=generated_binding();result=cl.contract(after,before,targets)
    assert len(result)==18 and [x['operation_native_id']for x in result[-4:]]==[1000,1001,1002,1003]


@pytest.mark.parametrize('change',['old_count','new_feature','new_tool','new_missing','new_boolcount'])
def test_cl_contract_rejects_identity_or_prefix_change(change):
    before,after,targets=generated_binding()
    if change=='old_count':after['operations'][5]['toolpath_record_counts']=[99]
    elif change=='new_feature':after['operations'][-1]['linked_feature_ids']=[900]
    elif change=='new_tool':after['operations'][-1]['assigned_tool']['native_id']=800
    elif change=='new_missing':after['operations'][-1]['toolpath_generated']=False
    else:after['operations'][-1]['toolpath_record_counts']=[True]
    with pytest.raises(ValueError):cl.contract(after,before,targets)
