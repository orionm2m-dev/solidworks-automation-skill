"""Synthetic one-export lifecycle tests; no private evidence or COM calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import math,json
import pytest
from scripts import sw_cam_saved18_optimized_wip as m

@pytest.fixture
def authority(tmp_path):
    ids=list(range(1,18))+[344,346,348,350]
    targets=[dict(operation_native_id=oid,operation_type=i%2,feature_native_id=339+i//2,assigned_tool=dict(native_id=342))for i,oid in enumerate(ids[-4:])]
    ops=[]
    for i,oid in enumerate(ids):
        t=targets[i-17]if i>=17 else None;generated=i<14 or i>=17
        ops.append(dict(native_id=oid,toolpath_generated=generated,toolpath_record_counts=[46]if generated else[],suppressed=False,linked_feature_ids=[t['feature_native_id']]if t else[100+i],mill_operation_type=t['operation_type']if t else 0,assigned_tool=t['assigned_tool']if t else dict(native_id=273)))
    rows=[dict(operation_native_id=oid,nc=dict(feeds_compensation=dict(GetSpndlSpeed=math.nextafter(7100.,math.inf),XYFeed=math.nextafter(35.,math.inf))))for oid in ids[-12:]]
    snapshot=dict(binding=dict(operations=ops),parameters=rows);source=tmp_path/'part.sldprt';source.write_bytes(b'synthetic')
    bound=dict(scope=m.binding.SCOPE,process_id=25208,receipt_pin=dict(path=str(tmp_path/'parent.json'),sha256='b'*64),terminal_proof={},source_path=str(source),source_sha256=m.common._pin(source)['sha256'],document=dict(path=str(source),needs_save=False),configuration={},snapshot=snapshot,saved_cl={},learned_targets=targets,expected_generated_operations=m.binding.generated_streams(snapshot,targets),tool_catalogue=[],tool_dimensions={})
    bound['binding_sha256']=m.binding.digest(bound)
    return bound

class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def typed(self,value,name):return value
    def dispatch_once(self,fn,*,persist_pending):persist_pending();return fn()
    def summary(self):return dict(synthetic=True)

@pytest.fixture
def run_case(tmp_path,authority,monkeypatch):
    def run(*,native=True,drift=False,cleanup=False,racing_marker=False):
        raw=deepcopy(authority);bound,policy=m.comparison_bound(raw)
        directory=tmp_path/'wip';marker=tmp_path/'marker.json';receipt=tmp_path/'receipt.json'
        p=dict(expected_document_path=raw['source_path'],expected_source_sha256=raw['source_sha256'],receipt_path=str(receipt))
        plan=dict(directory=directory,canonical=directory.resolve(),marker=marker,loaded=dict(deep_targets=raw['learned_targets'],pins=[],phase_proof_pins=[]),bound=bound,raw_bound=raw)
        report=m.binding.new_report(bound,output_dir=directory,implementation_pin={});captures=[];calls=[]
        class Machine:
            def CreateSTLOfWIPs2(self,*args):calls.append(args);(directory/'wip.stl').write_bytes(b'synthetic STL');return native
        machine=Machine()
        def capture(backend,p,plan,report,persist,label):
            captures.append(label);snapshot=deepcopy(bound['snapshot'])
            if drift and label=='after':snapshot['parameters'][0]['changed']=True
            report.setdefault('raw_captures',[]).append(dict(label=label,snapshot=snapshot))
            return raw['document'],snapshot,dict(machine=machine)
        monkeypatch.setattr(m,'capture_existing',capture)
        class Backend:
            session=None;session_active=False
            ctx=SimpleNamespace(guard=Guard,identity=lambda:deepcopy(raw['document']))
            def start(self):
                if racing_marker:marker.write_text('other owner',encoding='utf-8')
            def finish(self):
                if cleanup:raise ValueError('synthetic cleanup failure')
            def close(self):
                if cleanup:raise ValueError('synthetic close failure')
        persist=lambda:m._write_receipt(receipt,report)
        result=m.run_backend(Backend(),p,plan,report,persist)
        return result,calls,captures,marker,directory
    return run

def test_one_export_and_full_lifecycle(run_case):
    r,calls,captures,marker,directory=run_case()
    assert r['status']=='review_required' and r['checkpoint_export_readback_verified'] is True
    assert r['readback_verified'] and r['binding_readback_verified'] and not r['outer_cleanup_still_required']
    assert len(calls)==r['native_call_count']==1 and captures==['before','after']
    assert json.loads(marker.read_text(encoding='utf-8'))['automatic_replay'] is False
    assert all(r[k] is False for k in ('GTP_attempted','GOP_attempted','AFR_attempted','model_saved','setter_attempted','assignment_attempted','simulation_attempted','geometry_verified','production_qualified'))

@pytest.mark.parametrize('native',[False,0,1,None])
def test_non_true_native_stops_without_cam_readback(run_case,native):
    r,calls,captures,marker,_=run_case(native=native)
    assert r['status']=='uncertain' and not r['readback_verified'] and not r['export_files_verified']
    assert captures==['before'] and len(calls)==1 and marker.exists()

def test_after_snapshot_drift_blocks_claim(run_case):
    r,calls,captures,_,_=run_case(drift=True)
    assert r['status']=='uncertain' and not r['checkpoint_export_readback_verified'] and len(calls)==1

def test_cleanup_failure_clears_every_success_claim(run_case):
    r,calls,_,_,_=run_case(cleanup=True)
    assert len(calls)==1 and r['status']=='uncertain' and r['outer_cleanup_still_required']
    assert all(r[k] is False for k in ('readback_verified','export_files_verified','binding_readback_verified','checkpoint_export_readback_verified'))

def test_marker_race_never_overwrites_other_owner(run_case):
    r,calls,captures,marker,_=run_case(racing_marker=True)
    assert calls==[] and captures==['before'] and marker.read_text(encoding='utf-8')=='other owner'
    assert not r['checkpoint_export_readback_verified']

def test_comparison_preserves_all_raw_values(authority):
    before=deepcopy(authority);bound,proof=m.comparison_bound(authority)
    assert authority==before and proof['raw_preserved'] and len(proof['fields'])==8
    assert all(v['ULP_distance']==1 for v in proof['fields'])
    assert bound['raw_saved_binding_sha256']==authority['binding_sha256']
    m.binding.validate_capture(bound,bound['document'],bound['snapshot'],verify_direct_pin=lambda _:None)

@pytest.mark.parametrize('kind',['two_ulp','other_field','dirty','source_tamper'])
def test_bounded_roundoff_and_saved_identity(authority,kind):
    b,_=m.comparison_bound(authority);raw=deepcopy(authority['snapshot']);doc=deepcopy(b['document'])
    with pytest.raises(ValueError):
        if kind=='two_ulp':raw['parameters'][-1]['nc']['feeds_compensation']['XYFeed']=math.nextafter(math.nextafter(35.,math.inf),math.inf)
        if kind=='other_field':raw['parameters'][0]['other']=1
        if kind=='dirty':doc['needs_save']=True
        if kind=='source_tamper':b['source_sha256']='f'*64
        projected,_=m.producer.projection(raw,b['snapshot'])
        m.binding.validate_capture(b,doc,projected,verify_direct_pin=lambda _:None)

@pytest.mark.parametrize('name',['insert','assign','set_field','set_nc','generate','save','export'])
def test_mutation_methods_are_explicitly_unavailable(name):
    with pytest.raises(ValueError,match='Only guarded'):
        getattr(m.ReadBackend,name)(object())

def test_marker_identity_ignores_output_and_pid(authority):
    p=dict(expected_document_path=authority['source_path'],expected_source_sha256=authority['source_sha256'],process_id=25208,output_dir='C:/one')
    other=dict(p,process_id=999,output_dir='C:/two')
    assert m.marker_path(p)==m.marker_path(other)

@pytest.mark.parametrize('value',[True,-1.,math.inf,math.nan,'1'])
def test_native_length_helper_rejects_nonfinite_nonnumeric(value):
    raw=[]
    with pytest.raises(ValueError):m.lengths.read_lengths(object(),read=lambda *_:value,record=lambda k,v:raw.append((k,v)))
    assert len(raw)==1

@pytest.mark.parametrize('drift',[False,True])
def test_length_batch_uses_existing_binding_and_preserves_raw(authority,monkeypatch,drift):
    def collection(values):return SimpleNamespace(Count=len(values),Item=lambda i:values[i])
    operations={}
    for row in authority['snapshot']['binding']['operations'][-4:]:
        feature=SimpleNamespace(native_id=row['linked_feature_ids'][0]);tool=SimpleNamespace(native_id=row['assigned_tool']['native_id'])
        path=SimpleNamespace(RecordCount=row['toolpath_record_counts'][0])
        operations[row['native_id']]=SimpleNamespace(native_id=row['native_id'],Suppressed=False,GetIsToolpathGenerated=True,OpernType=row['mill_operation_type'],IGetAllFeatures=collection([feature]),IGetTool=tool,IGetEnumToolpaths=collection([path]),ToolpathFeedLength=1.25,ToolpathRapidLength=2.5,ToolpathTotalLength=3.75)
    doc=SimpleNamespace(GetDocType=1,GetCWObjectFromID=lambda kind,oid:(operations[oid],True),GetCWObjectID=lambda obj:(obj.native_id,True));machine=SimpleNamespace(MachType=1)
    class Batch(Guard):
        def __init__(self,*args,**kw):assert kw['max_native_calls']==600
        def read(self,obj,name,*args):return m._member(obj,name,*args)
        def require_complete(self):pass
    monkeypatch.setattr(m.lengths,'ReadBatch',Batch)
    ctx=SimpleNamespace(identity=lambda:authority['document'],files=lambda:None,owned=lambda:None)
    backend=SimpleNamespace(sw=object(),typelib_path='synthetic.tlb',loaded=dict(generated_pin={},pins=[]),args=dict(process_id=25208,expected_source_sha256=authority['source_sha256']),ctx=ctx,events=lambda:None,learned=authority['learned_targets'])
    report={};m.capture_lengths(backend,authority['snapshot'],report,lambda:None,'before',doc,machine)
    if drift:operations[350].ToolpathFeedLength=1.5
    if drift:
        with pytest.raises(ValueError,match='statistics changed'):m.capture_lengths(backend,authority['snapshot'],report,lambda:None,'after',doc,machine)
    else:m.capture_lengths(backend,authority['snapshot'],report,lambda:None,'after',doc,machine)
    assert [r['operation_native_id']for r in report['native_length_readbacks'][0]['rows']]==[344,346,348,350]
    assert all(r['readback_verified'] and len(r['scalar_observations'])==3 for r in report['native_length_readbacks'][0]['rows'])
    assert report['native_length_readbacks'][1]['rows'][-1]['lengths']['feed_length_native']==(1.5 if drift else 1.25)
