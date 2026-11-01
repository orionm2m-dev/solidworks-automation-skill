"""Read batching equivalence, retained identities, raw failure evidence and durability."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',STAGE));sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('fresh_fields_under_test',STAGE/'scripts/sw_cam_fresh_finish_field_batch.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Node:
    def __init__(self,name):self.name=name


class FakeReads:
    def __init__(self,owner,**kwargs):
        self.owner=owner;self.calls=[];self.complete=False
        self.binding=kwargs.get('verify_retained_binding')
        self.progress=kwargs.get('progress_callback',lambda:None)
        self.state=kwargs.get('progress_state',{})
        self.limit=kwargs.get('max_native_calls',100)
    def __enter__(self):
        if self.binding:self.binding()
        return self
    def __exit__(self,typ,exc,tb):
        if typ is None and self.binding:
            if self.owner.drift:self.owner.changed=True
            self.binding()
        self.complete=typ is None
    def require_complete(self):
        if not self.complete:raise ValueError('Incomplete batch')
    def summary(self):return dict(read_scope_complete=self.complete,native_calls=len(self.calls),read_only=True)
    def observed(self,kind,name,invoke):
        assert len(self.calls)<self.limit
        self.state.update(member=name,attempted=True,returned=False,native_call_count=len(self.calls))
        self.progress();self.calls.append((kind,name))
        value=invoke()
        self.state.update(returned=True,native_call_count=len(self.calls));self.progress()
        return value
    def typed(self,obj,name):return self.observed('qi',name,lambda:obj)
    def read(self,obj,name,*args):
        def invoke():
            o=self.owner
            if name=='GetCWObjectFromID':return (o.op if args[0]==3 else o.feature,True)
            if name=='GetCWObjectID':
                return ((o.oid+1 if o.changed else o.oid) if args[0] is o.op else o.fid,True)
            if name=='Suppressed':return False
            if name=='OpernType':return 1
            if name=='IGetAllFeatures':return [o.feature]
            if name=='Count':return len(obj)
            if name=='Item':return obj[args[0]]
            if name=='IGetLeadin':return o.lead_in
            if name=='IGetLeadout':return o.lead_out
            if name==o.fail_member:raise RuntimeError('field getter failed')
            if name==o.bad_member:return True
            spec=next(s for s in m._recipe().FIELDS if s[2]==name)
            if spec[4]=='depth_pair':return (0.3,False)
            if spec[4]=='pair':return (0.2,False,0.0)
            if spec[0] in m.BOOL_KEYS:return False
            if spec[0] in m.INT_KEYS:return 1
            return 0.25
        return self.observed('getter',name,invoke)


@pytest.fixture
def case(tmp_path,monkeypatch):
    f=SimpleNamespace(oid=320,fid=79,op=Node('operation'),feature=Node('feature'),
        doc=Node('document'),lead_in=Node('lead-in'),lead_out=Node('lead-out'),
        changed=False,drift=False,fail_member=None,bad_member=None,ordinary_guards=0,batches=[],snapshots=[])
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'saved')
    receipt=tmp_path/'owner.json';marker=tmp_path/'once.json'
    args=dict(operation_native_id=f.oid,feature_native_id=f.fid,process_id=123,
        expected_document_path=str(source),expected_source_sha256='0'*64,receipt_path=str(receipt))
    report=dict(actions={})
    class Journal:
        def __init__(self):self.marker=marker
        def persist(self):
            f.snapshots.append(deepcopy(report));receipt.write_text(json.dumps(report),encoding='utf-8')
    def guard():
        f.ordinary_guards+=1;return FakeReads(f)
    ctx=SimpleNamespace(guard=guard,identity=lambda:{'path':str(source),'needs_save':False},
        args=args,files=lambda:None,owned=lambda:None)
    f.backend=SimpleNamespace(args=args,loaded=dict(
        pins=[m._recipe().common._pin(m.__file__),m._recipe().common._pin(m.progress.__file__)],
        generated_pin={}),report=report,persist=Journal().persist,native={'doc':f.doc,'operations':{}},
        sw=None,typelib_path='fixture',ctx=ctx,events=lambda:None)
    f.backend.target=lambda g:m._recipe().NativeBackend.target(f.backend,g)
    def batch(*args,**kw):
        v=FakeReads(f,**kw);f.batches.append(v);return v
    monkeypatch.setattr(m,'FreshFinishFieldBatch',batch)
    f.receipt=receipt;f.source=source;f.progress=receipt.with_name('owner.fields.before.320.json')
    return f


def test_one_guard_and_one_batch_same_twenty_values(case):
    result=m.read_fields(case.backend,'before')
    assert len(result)==20 and case.ordinary_guards==1 and len(case.batches)==1
    # Two complete target bindings (12+2 each), five ownerQI, two lead getters and20 fields.
    assert len(case.batches[0].calls)==55
    assert len(case.snapshots)==2
    diag=case.snapshots[-1]['fresh_finish_field_batches'][0]
    assert diag['complete'] is True and diag['batch']['read_scope_complete'] is True
    assert set(diag['raw_fields'])==set(result)
    assert result['first_depth']==[0.3,False] and type(result['spring_passes']) is int
    compact=json.loads(case.progress.read_text())
    assert compact['status']=='completed' and compact['mutation_authority'] is False
    assert compact['read_updates']==110


def test_read_cached_owners_once_and_27_calls(case):
    read=FakeReads(case);diag={}
    fields=m.read_cached_fields(read,case.op,case.feature,diag)
    assert len(read.calls)==27 and len(fields)==20
    assert [x[1] for x in read.calls if x[0]=='qi']==[
        'ICWFinishMillOp','ICWFinishMillOp2','ICWFinishMillOp3','ICWLeadInOut','ICWLeadInOut']
    assert [x[1] for x in read.calls if x[1] in ('IGetLeadin','IGetLeadout')]==['IGetLeadin','IGetLeadout']


def test_mismatched_type_is_recorded_before_rejection(case):
    case.bad_member='GetMaxDepthCut'
    with pytest.raises(ValueError,match='max_depth'):m.read_fields(case.backend,'before')
    diag=case.snapshots[-1]['fresh_finish_field_batches'][0]
    assert diag['raw_fields']['max_depth']['value'] is True and diag['complete'] is False
    assert len(case.snapshots)==2 and json.loads(case.progress.read_text())['status']=='failed'


def test_getter_failure_keeps_partial_fields(case):
    case.fail_member='GetMaxDepthCut'
    with pytest.raises(RuntimeError,match='getter failed'):m.read_fields(case.backend,'before')
    diag=case.snapshots[-1]['fresh_finish_field_batches'][0]
    assert set(diag['raw_fields'])=={'side_allowance','final_side','spring_passes','first_depth'}
    assert diag['complete'] is False and json.loads(case.progress.read_text())['status']=='failed'


def test_changed_exit_binding_returns_no_values(case):
    case.drift=True
    with pytest.raises(ValueError,match='identity'):m.read_fields(case.backend,'before')
    assert len(case.snapshots)==2
    assert case.snapshots[-1]['fresh_finish_field_batches'][0]['complete'] is False
    assert json.loads(case.progress.read_text())['status']=='failed'


def test_duplicate_progress_path_prevents_second_batch(case):
    m.read_fields(case.backend,'before')
    with pytest.raises(ValueError,match='Fresh absolute'):m.read_fields(case.backend,'before')
    assert len(case.batches)==1


@pytest.mark.parametrize('name',('GenerateToolpath','SetSideCutAmt','SaveActiveDocument','QueryInterface'))
def test_getter_allowlist_rejects_mutations_and_arbitrary_qi(name):
    b=object.__new__(ORIGINAL_BATCH);b._invalid=False;b._completed=True;b._known_objects=set()
    with pytest.raises(ValueError):b.read(object(),name)
    assert b._invalid is True and b._completed is False


@pytest.mark.parametrize('value',(None,True,0,0.0,float('nan'),[0.3,0],[True,False]))
def test_depth_pair_shape_rejects_ambiguous_native_values(value):
    spec=next(s for s in m._recipe().FIELDS if s[0]=='max_depth')
    with pytest.raises(ValueError):m.checked_value(spec,value)


def test_invalid_native_float_evidence_is_json_safe():
    row=m.raw_observation(float('nan'))
    assert row['value_recorded'] is False and row['nonfinite_repr']=='nan'
    json.dumps(row,allow_nan=False)


def test_new_reader_requires_live_module_pin_before_any_guard(case):
    case.backend.loaded['pins'].pop(0)
    with pytest.raises(ValueError,match='live pinned'):m.read_fields(case.backend,'before')
    assert case.ordinary_guards==0 and not case.snapshots


def test_owner_actions_and_marker_are_not_replaced(case):
    case.backend.report['actions']={'GenerateToolpath':{'pending':True,'returned':False}}
    case.backend.persist.__self__.marker.write_text('existing durable intent')
    m.read_fields(case.backend,'before')
    assert case.backend.persist.__self__.marker.read_text()=='existing durable intent'
    assert all(s['actions']==case.backend.report['actions'] for s in case.snapshots)


ORIGINAL_BATCH=m.FreshFinishFieldBatch


def test_helper_import_accepts_partially_initialized_writer(monkeypatch):
    partial=SimpleNamespace(__name__='scripts.sw_cam_fresh_finish_recipe')
    monkeypatch.setitem(sys.modules,'scripts.sw_cam_fresh_finish_recipe',partial)
    spec=importlib.util.spec_from_file_location('helper_circular_import_check',Path(m.__file__))
    loaded=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert loaded._recipe() is partial
    assert 'SideAllow' in loaded.GETTERS
