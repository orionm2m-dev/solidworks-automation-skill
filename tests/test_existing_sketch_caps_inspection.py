"""Portable offline inspection tests. Fake objects only; no COM or runtime writes."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import ast
import hashlib
import json
import pytest
from test_existing_sketch_caps import m, params, FakeBackend


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeDefinition:
    ReverseDirection=True
    Merge=True
    BothDirections=False
    FromType=0
    def GetDepth(self, forward): assert forward is True; return .001
    def GetEndCondition(self, forward): assert forward is True; return 0
    def IsBossFeature(self): return True
    def IsThinFeature(self): return False
    def GetDraftWhileExtruding(self, forward): assert forward is True; return False


class FakeFeature:
    def __init__(self,p): self.p=p; self.failure=None; self.seen=[]
    @property
    def Name(self): return self.p['feature_names'][0]
    def GetTypeName2(self):
        self.seen.append('type2')
        if self.failure=='type2': raise RuntimeError('raw type getter failure')
        return 'ICE'
    def GetTypeName(self): self.seen.append('type1'); return 'Boss'
    def GetDefinition(self):
        self.seen.append('definition')
        if self.failure=='definition': raise RuntimeError('definition getter failure')
        return FakeDefinition()
    def GetParents(self): self.seen.append('parents'); return [SimpleNamespace(Name=self.p['profile_specs'][0]['sketch_name'])]


class Inspector(FakeBackend):
    inspect_feature=m.InspectionBackend.inspect_feature
    def __init__(self,p,original):
        super().__init__(p)
        self.features=deepcopy(original.features)
        self.features[-1]['type']='ICE'
        self.volume=original.volume; self.dirty=True
        self.feature=FakeFeature(p)
        self.model=SimpleNamespace(FeatureByName=lambda name:self.feature if name==p['feature_names'][0] else None)


@pytest.fixture
def inspection(params):
    b=FakeBackend(params);b.feature_defect={'type_name':'Cut'}
    result=m.run(None,params,runtime_check=lambda:None,backend=b)
    assert result['status']=='uncertain' and len(b.calls)==1
    q=dict(process_id=params['process_id'],expected_process_creation_time=params['expected_process_creation_time'],
           expected_document_path=params['expected_document_path'],partial_receipt_path=params['receipt_path'],
           partial_receipt_sha256=sha(params['receipt_path']),original_marker_sha256=sha(m.marker_path(params)),
           receipt_path=str(Path(params['receipt_path']).with_name('inspect.json')))
    return q,Inspector(params,b)


def run(q,b): return m.run_inspection(None,q,runtime_check=lambda:None,backend=b)


def test_raw_types_and_all_definition_fields_read_without_mutation(inspection):
    q,b=inspection;original=Path(q['partial_receipt_path']).read_bytes();marker=m.marker_path(b.p).read_bytes()
    r=run(q,b)
    assert r['status']=='observed_read_only' and r['readback_verified'] and r['state_unchanged']
    assert r['observed']['name']==b.p['feature_names'][0]
    assert r['observed']['type_name2']=='ICE' and r['observed']['type_name']=='Boss'
    assert r['observed']['depth_m']==.001 and r['observed']['reverse_direction'] is True
    assert r['observed']['parents']==[b.p['profile_specs'][0]['sketch_name']]
    assert b.calls==[] and b.cleans==0 and b.feature.seen==['type2','type1','definition','parents']
    assert Path(q['partial_receipt_path']).read_bytes()==original and m.marker_path(b.p).read_bytes()==marker
    assert r['mutation_attempted'] is False and r['selection_changed'] is False and r['CAM_calls']==0
    assert json.loads(Path(q['receipt_path']).read_text())==r


@pytest.mark.parametrize('failure',['type2','definition'])
def test_raw_getter_failure_persisted_and_other_fields_still_read(inspection,failure):
    q,b=inspection;b.feature.failure=failure
    r=run(q,b)
    assert r['status']=='error' and not r['readback_verified'] and r['state_unchanged']
    assert r['observed']['name']==b.p['feature_names'][0]
    assert r['observed']['type_name']=='Boss' and 'parents' in r['observed']
    field='type_name2' if failure=='type2' else 'definition'
    assert r['observed']['getter_errors'][field]['type']=='RuntimeError'
    assert b.calls==[] and b.cleans==0


def test_telemetry_is_durable_before_next_getter(inspection):
    q,b=inspection
    def check():
        recorded=json.loads(Path(q['receipt_path']).read_text())
        assert recorded['observed']['name']==b.p['feature_names'][0]
        raise RuntimeError('after durable name')
    b.feature.GetTypeName2=check
    r=run(q,b)
    assert r['observed']['getter_errors']['type_name2']['message']=='after durable name'


@pytest.mark.parametrize('field,value',[('process_id',999),('expected_process_creation_time',999.),
                                      ('partial_receipt_sha256','0'*64),('original_marker_sha256','0'*64)])
def test_wrong_owner_or_evidence_blocked_before_native_read(inspection,field,value):
    q,b=inspection;q[field]=value
    with pytest.raises(ValueError):run(q,b)
    assert b.guard_count==0 and b.feature.seen==[] and not Path(q['receipt_path']).exists()


@pytest.mark.parametrize('mode',['dirty','owner','body_drift','source_drift'])
def test_guard_failure_never_mutates_or_claims_success(inspection,mode):
    q,b=inspection
    if mode=='dirty':b.dirty=False
    if mode=='owner':b.bad_owner=True
    if mode in ('body_drift','source_drift'):
        original=b.inspect_feature
        def changed(*args):
            original(*args)
            if mode=='body_drift':b.volume*=1.01
            else:Path(b.p['protected_document_path']).write_bytes(b'drift')
        b.inspect_feature=changed
    r=run(q,b)
    assert r['status']=='error' and not r['readback_verified'] and b.calls==[] and b.cleans==0


def test_only_unique_new_feature_is_fallback_candidate(inspection):
    q,b=inspection
    b.model.FeatureByName=lambda name:None
    b.features.append(dict(name='OTHER',type='ICE'))
    r=run(q,b)
    assert r['status']=='error' and 'unique new feature' in r['issue']['message']
    assert len(r['observed']['new_top_level_candidates'])==2 and not r['observed']['expected_name_found']


def test_inspection_source_has_no_mutation_or_cleanup_dispatch():
    source=Path(m.__file__).read_text(encoding='utf-8-sig');tree=ast.parse(source)
    names={'InspectionBackend','inspection_parameters','inspection_authority','run_inspection'}
    nodes=[n for n in tree.body if getattr(n,'name',None) in names]
    attrs={n.attr for node in nodes for n in ast.walk(node) if isinstance(n,ast.Attribute)}
    assert not attrs.intersection({'cleanup','create','read_feature','ClearSelection2','Save3','ForceRebuild3','EditRebuild3','Select2'})
    assert not any(isinstance(n,ast.Attribute) and isinstance(n.ctx,ast.Store) and n.attr=='Name' for node in nodes for n in ast.walk(node))
