"""Synthetic grouped mutation protocol tests; no native host is created."""
from copy import deepcopy
from collections import Counter
from pathlib import Path
import importlib.util
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('grouped_face_staged', ROOT/'scripts/sw_cam_grouped_face_recipe.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


APPROVED_SYNTHETIC_CONTRACT = {'scope': 'GROUPED_EXISTING_FACE_RECIPE_V1', 'identity': {'operation_native_id': 267, 'feature_native_id': 265, 'setup_native_id': 93, 'required_confirmed_operation_order': [143, 144, 195, 196, 267, 247, 248]}, 'face_changes': [{'index': 1, 'interface': 'ICWFaceMillOp', 'member': 'ShapeExtent', 'kind': 'property', 'readback': 'ShapeExtent', 'expected_old': 1, 'requested': 0, 'args': [0]}, {'index': 2, 'interface': 'ICWFaceMillOp', 'member': 'AutoAngle', 'kind': 'property', 'readback': 'AutoAngle', 'expected_old': True, 'requested': False, 'args': [False]}, {'index': 3, 'interface': 'ICWFaceMillOp', 'member': 'CutOrder', 'kind': 'property', 'readback': 'CutOrder', 'expected_old': 0, 'requested': 1, 'args': [1]}, {'index': 4, 'interface': 'ICWFaceMillOp', 'member': 'SetMaxStepOver', 'kind': 'pair', 'readback': 'GetMaxStepOver', 'expected_old': [70.0, True], 'requested': [3.2, False], 'args': [3.2, False]}, {'index': 5, 'interface': 'ICWFaceMillOp', 'member': 'SetMinSideOffset', 'kind': 'pair', 'readback': 'GetMinSideOffset', 'expected_old': [10.0, True], 'requested': [0.5, False], 'args': [0.5, False]}, {'index': 6, 'interface': 'ICWFaceMillOp', 'member': 'SetMaxSideOffset', 'kind': 'pair', 'readback': 'GetMaxSideOffset', 'expected_old': [25.0, True], 'requested': [1.0, False], 'args': [1.0, False]}, {'index': 7, 'interface': 'ICWFaceMillOp', 'member': 'SetFirstCutAmount', 'kind': 'pair', 'readback': 'GetFirstCutAmount', 'expected_old': [1.0, False], 'requested': [0.5, False], 'args': [0.5, False]}, {'index': 8, 'interface': 'ICWFaceMillOp', 'member': 'SetMaxCutAmount', 'kind': 'pair', 'readback': 'GetMaxCutAmount', 'expected_old': [1.0, False], 'requested': [0.5, False], 'args': [0.5, False]}, {'index': 9, 'interface': 'ICWFaceMillOp', 'member': 'SetLeadInClearance', 'kind': 'feature_pair', 'readback': 'GetLeadInClearance', 'expected_old': [55.0, True], 'requested': [2.0, False], 'args': ['exact_feature265_IDispatch', 2.0, False]}, {'index': 10, 'interface': 'ICWFaceMillOp', 'member': 'SetLeadOutClearance', 'kind': 'feature_pair', 'readback': 'GetLeadOutClearance', 'expected_old': [55.0, True], 'requested': [2.0, False], 'args': ['exact_feature265_IDispatch', 2.0, False]}, {'index': 11, 'interface': 'ICWFaceMillOp', 'member': 'SetPassClearance', 'kind': 'feature_pair', 'readback': 'GetPassClearance', 'expected_old': [5.0, True], 'requested': [2.0, False], 'args': ['exact_feature265_IDispatch', 2.0, False]}, {'index': 12, 'interface': 'ICWFaceMillOp', 'member': 'SetLinkTypeAlongCutAboveThreshold', 'kind': 'feature_int', 'readback': 'GetLinkTypeAlongCutAboveThreshold', 'expected_old': 1, 'requested': 0, 'args': ['exact_feature265_IDispatch', 0]}, {'index': 13, 'interface': 'ICWFaceMillOp', 'member': 'SetLinkTypeBetweenCutsAboveThreshold', 'kind': 'feature_int', 'readback': 'GetLinkTypeBetweenCutsAboveThreshold', 'expected_old': 1, 'requested': 0, 'args': ['exact_feature265_IDispatch', 0]}], 'face_already_at_target_or_protected': {'CutMethod': 1, 'NumberOfCuts': 1, 'EqualizeToolLoading': False, 'MachiningExtent': 0, 'IslandXYAllowance': 0.5, 'IslandCleanupPass': False, 'CutAngle': 0.0, 'MillingType': 0, 'ZigZagType': True, 'GetBottomAllowance': 0.0, 'GetFinalCutAmount': 0.0, 'GetAvoidAllowance': 0.002, 'GetContainAllowance': 0.002, 'GetContainType': 0, 'GetLinkThresholdAlongCut': [100.0, True], 'GetLinkThresholdBetweenCuts': [70.0, True], 'GetLinkTypeAlongCutUptoThreshold': 0, 'GetLinkTypeBetweenCutsUptoThreshold': 0, 'GetMachiningDepth': 2.0, 'GetOverrideMachiningDepth': False}, 'nc_expected_unchanged': {'GetSpndlSpeed': 1000.0, 'GetTlpComp': 1, 'GetCNCComp': 0, 'GetRetractType': 0, 'GetClrPlaneUseSetupStatus': False, 'GetRpdPlaneUseSetupStatus': False, 'XYFeed': 500.0}, 'tool_assignment': {'expected_old_id': 252, 'target_existing_id': 249, 'interface': 'ICWMillOperation', 'member': 'SetTool'}, 'feeds': {'no_feed_or_spindle_setters': True, 'plunging_allowed': False}}

class Backend:
    def __init__(self, journal):
        self.journal = journal
        self.settings = m.expected_settings()
        self.calls = Counter()
        self.tool = 252
        self.generated = False
        self.source = 'a'*64
        self.dirty = False
        self.returns = {}
        self.after = {}
        self.full_labels = []
    def boundary(self): pass
    def start(self): self.calls['start'] += 1
    def close(self): self.calls['close'] += 1
    def finish(self): self.calls['finish'] += 1
    def refresh_dirty(self):
        assert type(self.dirty) is bool
    def state(self):
        return dict(settings=deepcopy(self.settings), tool=self.tool, generated=self.generated,
                    source=self.source, dirty=self.dirty, protected='same')
    def capture_full(self, label):
        self.full_labels.append(label)
        return self.state()
    def verify_baseline(self, value):
        assert value['tool'] == 252 and value['generated'] is False
    def read_settings(self, label): return self.state()
    def read_narrow(self, label):
        if label in self.after: self.after[label](self)
        return self.state()
    def read_field(self, name): return deepcopy(self.settings['face'][name])
    def native(self, name, pending, mutate):
        pending()
        on_disk = json.loads(self.journal.receipt.read_text())
        assert on_disk['actions'][name]['attempted']
        assert on_disk['native_dispatch_pending']
        marker = json.loads(self.journal.marker.read_text())
        assert marker['actions'][name]['native_dispatch_pending']
        self.calls[name] += 1
        mutate()
        return self.returns.get(name, 0)
    def assign_tool(self, pending):
        return self.native('SetTool', pending, lambda:setattr(self, 'tool', 249))
    def verify_assignment(self, state): assert state['tool'] == 249
    def write_field(self, name, kind, target, pending):
        getter = next(g for member, k, g, o, t in m.CHANGES if member == name)
        value = self.native(name, pending, lambda:self.settings['face'].__setitem__(getter, target))
        return None if kind == 'property' and name not in self.returns else value
    def verify_configured(self, state):
        assert state['tool'] == 249 and not state['generated']
    def generate(self, pending):
        return self.native('GenerateToolpath', pending, lambda:setattr(self, 'generated', True))
    def verify_generated(self, state):
        assert state['tool'] == 249 and state['generated'] and state['protected'] == 'same'
    def verify_final(self, state):
        self.verify_generated(state)
        assert state['source'] == 'b'*64 and state['dirty'] is False
    def save_projection(self, state):
        return {k:deepcopy(state[k]) for k in ['settings','tool','generated','protected']}
    def save(self):
        on_disk = json.loads(self.journal.receipt.read_text())
        assert on_disk['actions']['SaveActiveDocument']['native_dispatch_pending']
        self.calls['SaveActiveDocument'] += 1
        return self.returns.get('SaveActiveDocument', 0)
    def saved_hash(self, save_report):
        assert type(save_report['native_return_value']) is int and save_report['native_return_value'] == 0
        self.source = 'b'*64
        return self.source
    def checkpoint(self, state): return deepcopy(state)

@pytest.fixture
def case(tmp_path):
    report = dict(source_path=str(tmp_path/'fixture.SLDPRT'), source_sha256='a'*64,
                  recipe_sha256='b'*64)
    journal = m.GroupJournal(report, tmp_path/'result.json', tmp_path/'once.json')
    backend = Backend(journal)
    return backend, journal

def test_approved_plan_contract():
    plan = deepcopy(APPROVED_SYNTHETIC_CONTRACT)
    result = m.validate_plan(plan)
    assert len(result['changes']) == 13
    assert result['number_of_cuts_policy'] == 'EXACT1_BASELINE_CONFIG_POSITIVE_LONG_AFTER_GTP_FREEZE_THROUGH_SAVE'

@pytest.mark.parametrize('field', ['member','kind','readback','expected_old','requested','args'])
def test_changed_plan_contract_rejected(field):
    plan = deepcopy(APPROVED_SYNTHETIC_CONTRACT)
    plan['face_changes'][0][field] = 'different'
    with pytest.raises(ValueError): m.validate_plan(plan)

def test_single_group_full_baseline_and_final_only(case):
    b,j = case
    result = m.run_grouped_backend(b,j)
    assert result['readback_verified'], result
    assert result['model_saved'] and result['full_capture_count'] == 2
    assert b.full_labels == ['baseline','final']
    assert b.calls['SetTool'] == b.calls['GenerateToolpath'] == b.calls['SaveActiveDocument'] == 1
    assert all(b.calls[name] == 1 for name, *_ in m.CHANGES)
    assert not result['production_qualified'] and not result['physical_geometry_verified']
    assert result['save_stage']['native_return_value'] == 0

def test_false_dirty_is_valid_and_not_set(case):
    b,j = case
    assert b.dirty is False
    result = m.run_grouped_backend(b,j)
    assert result['readback_verified'] and b.dirty is False

@pytest.mark.parametrize('value', [None, True, False, 1, 0.0, '0'])
def test_assignment_return_preserved_and_no_following_mutation(case,value):
    b,j = case;b.returns['SetTool'] = value
    result = m.run_grouped_backend(b,j)
    assert result['status'] == 'uncertain'
    row = json.loads(j.receipt.read_text())['actions']['SetTool']
    assert row['native_return']['python_type'] == type(value).__name__
    assert row['native_return']['value'] == value
    assert b.calls['SetTool'] == 1 and b.calls['GenerateToolpath'] == b.calls['SaveActiveDocument'] == 0

@pytest.mark.parametrize('value', [None, True, False, 1, 0.0, '0'])
def test_save_strict_return_stops_before_full_final(case,value):
    b,j = case;b.returns['SaveActiveDocument'] = value
    result = m.run_grouped_backend(b,j)
    assert result['status'] == 'uncertain' and not result['model_saved']
    assert result['save_stage']['native_return_type'] == type(value).__name__
    assert result['save_stage']['native_return_value'] == value
    assert b.full_labels == ['baseline'] and b.calls['SaveActiveDocument'] == 1
    assert b.source == 'a'*64

@pytest.mark.parametrize('value',[1,4,2147483647])
def test_derived_number_of_cuts_freezes_through_save(case,value):
    b,j=case
    b.after['generated']=lambda backend:backend.settings['face'].__setitem__('NumberOfCuts',value)
    result=m.run_grouped_backend(b,j)
    assert result['readback_verified'] and b.calls['SaveActiveDocument']==1
    assert result['automatic_count_observation']==dict(before=1,after=value,physical_pass_count_verified=False)

@pytest.mark.parametrize('value',[True,False,0,-1,2147483648,1.0,'1',None])
def test_derived_number_of_cuts_invalid_holds_before_save(case,value):
    b,j=case
    b.after['generated']=lambda backend:backend.settings['face'].__setitem__('NumberOfCuts',value)
    result=m.run_grouped_backend(b,j)
    assert result['status']=='uncertain' and b.calls['SaveActiveDocument']==0

@pytest.mark.parametrize('phase',['configured','before_save'])
def test_number_of_cuts_cannot_change_outside_generation(case,phase):
    b,j=case
    b.after[phase]=lambda backend:backend.settings['face'].__setitem__('NumberOfCuts',4)
    result=m.run_grouped_backend(b,j)
    assert result['status']=='uncertain' and b.calls['SaveActiveDocument']==0

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf'),2**100])
def test_nonjson_save_return_is_durable_and_never_replayed(case,value):
    b,j=case;b.returns['SaveActiveDocument']=value
    result=m.run_grouped_backend(b,j)
    assert result['status']=='uncertain' and b.calls['SaveActiveDocument']==1
    raw=json.loads(j.receipt.read_text())
    assert raw['actions']['SaveActiveDocument']['returned']
    assert raw['actions']['SaveActiveDocument']['native_return']['value_recorded'] is False
    assert b.source=='a'*64


def test_unrelated_nc_change_blocks_generation(case):
    b,j = case
    b.after['configured'] = lambda backend:backend.settings['nc'].__setitem__('XYFeed', 600.0)
    result = m.run_grouped_backend(b,j)
    assert result['status'] == 'uncertain'
    assert b.calls['GenerateToolpath'] == 0
    assert result['configured']['settings']['nc']['XYFeed'] == 600.0

def test_existing_group_marker_blocks_new_receipt(case):
    b,j = case;j.marker.write_text('unknown old attempt')
    result = m.run_grouped_backend(b,j)
    assert result['status'] == 'error' and b.calls['start'] == 0
    assert j.marker.read_text() == 'unknown old attempt'
    assert not j.receipt.exists()

def test_changed_recipe_cannot_rearm_same_group(case):
    b,j = case
    result = m.run_grouped_backend(b,j);assert result['readback_verified']
    marker_original=j.marker.read_bytes()
    report=dict(source_path=j.report['source_path'],source_sha256='a'*64,recipe_sha256='c'*64)
    second=m.GroupJournal(report,j.receipt.with_name('different.json'),j.marker)
    second_backend=Backend(second)
    result=m.run_grouped_backend(second_backend,second)
    assert result['status']=='error' and second_backend.calls['SetTool']==0
    assert j.marker.read_bytes()==marker_original

@pytest.mark.parametrize('a,b', [(True,1),(False,0),(1,1.0),([2.,False],[2.,0]),(float('nan'),float('nan'))])
def test_native_type_ambiguity_rejected(a,b): assert not m.exact(a,b)

def test_marker_canonical_aliases_and_recipe_independence(tmp_path):
    source=tmp_path/'fixture.SLDPRT'
    assert m.group_marker(source,'a'*64) == m.group_marker(source.parent/'.'/source.name,'a'*64)

def test_pending_native_exception_remains_unknown(case):
    b,j=case
    def interrupted(pending):
        pending();b.calls['SetTool']+=1;raise RuntimeError('native return unknown')
    b.assign_tool=interrupted
    result=m.run_grouped_backend(b,j)
    assert result['status']=='uncertain' and result['native_dispatch_pending']
    assert json.loads(j.marker.read_text())['actions']['SetTool']['native_dispatch_pending']
    assert b.calls['GenerateToolpath']==0
