"""Portable provenance tests using generated observations; no files or CAD needed."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', ROOT))
sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location('resume_evidence_under_test',
    ROOT / 'scripts' / 'sw_cam_taper_resume_evidence.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def build_case(tmp_path):
    profile = dict(status='observed', declared_chain_count=1, chains=[dict(index=0,
        read_complete=True, declared_curve_count=1, curves=[dict(index=0, read_complete=True,
        curve_type=0, start_native=[0., 0., 0.], end_native=[1., 0., 1.])])])
    ids = [249, 253] + list(range(1001, 1016))
    tools = [dict(native_id=i, tool_type_raw=1, CutDiameter=2., Protrusion=20., StnNo=float(n+1))
             for n, i in enumerate(ids)]
    protected = {str(i): dict(tool_native_id=i, tool_type_raw=1, profile_complete=True,
        profiles={name:deepcopy(profile) for name in ('tool', 'shank', 'holder')}) for i in ids}
    unit = dict(metric_document_scope_observed=True, unit='mm')
    document = dict(path=str(tmp_path/'part.SLDPRT'), title='part.SLDPRT', type=1, needs_save=False)
    state = dict(document=document, saved_file_sha256='a'*64,
        features=[dict(geometry=dict(native_id=264))],
        operations=[dict(native_id=267, assigned_tool=dict(native_id=249))],
        feature_setups=[dict(native_id=112)], operation_setups=[dict(native_id=113)], operation_counts=[1])
    loaded = {k:None for k in m.base.group.CURRENT_KEYS}
    loaded.update(state=state, source_sha256='a'*64,
        ownership=dict(process_id=1234, alive=True, create_time=100.0, executable='mock-cad'),
        finish_payload=dict(unit_record=unit, full_tool=deepcopy(protected['249'])),
        settings=dict(face={}), generated_face_operation_id=267, toolpath_record_counts=[1],
        parent_pin=dict(path=str(tmp_path/'parent.json'), sha256='b'*64),
        historical_source_pin=dict(path=str(tmp_path/'historical.SLDPRT'), sha256='a'*64),
        recipe=dict(scope='synthetic'), recipe_pin=dict(path=str(tmp_path/'recipe.json'), sha256='c'*64),
        catalogue_pin=dict(path=str(tmp_path/'catalogue.json'), sha256='d'*64),
        pins=[dict(path=str(tmp_path/'dependency.py'), sha256='e'*64)],
        offline_export_proof_pins=[], tool_phase_retired=[])
    current=m.base.group.current_projection(loaded)
    loaded['current_context_sha256']=m.base._digest(current)
    route=m.base.expected_route(loaded)
    baseline=dict(route=deepcopy(route), protected_tools=deepcopy(protected), tools=deepcopy(tools), units=deepcopy(unit))
    batch=dict(read_scope_complete=True, read_only=True, active=False, invalid=False,
               write_lease=False, native_call_attempted=False)
    after=deepcopy(tools)+[dict(native_id=9000, tool_type_raw=8, CutDiameter=3., Protrusion=50., StnNo=18.)]
    failed=dict(schema_version=1, scope=m.base.SCOPE, status='uncertain', phase='AddNewTool3',
        failed_phase='AddNewTool3', actions={'AddNewTool3':dict(attempted=True, returned=True,
            pending=False, native_return_type='POINTER(ICWTaperTool)', returned_interface_pointer=True)},
        mutation_attempted=True, phase_proofs_verified_after_native=True,
        full_tool_snapshot_count=1, candidate_profile_capture_count=0,
        issue=dict(type='ValueError', hresult=None, locations=[
            dict(file='sw_cam_comtypes.py', function='_interface_class'),
            dict(file='sw_cam_generation.py', function='_typed')]),
        current_before=deepcopy(current), current_before_sha256=loaded['current_context_sha256'],
        initial_source_sha256='a'*64, process_id=1234, source_path=document['path'],
        receipt_path=str(tmp_path/'receipt.json'), current_document=deepcopy(document), new_tool_native_id=9000,
        messages=dict(subscribed=True, active=True, disconnected=False, event_count=0, overflow=0,
            callback_error_count=0, events=[], callback_errors=[], disconnect_errors=[], subscription_error=None),
        initial_observation=baseline,
        protected_tool_observations=[dict(label='initial', catalogue_complete=True,
            catalogue=deepcopy(tools), partial_protected_tools=deepcopy(protected),
            route=deepcopy(route), units=deepcopy(unit),
            tool_reads=[dict(native_id=i, read_complete=True) for i in ids],
            handle_batch=deepcopy(batch), batches=[deepcopy(batch) for _ in range(5)])],
        scalar_catalogue_reads=[dict(phase='finished', complete=True, rows=deepcopy(rows), batch=deepcopy(batch))
                               for rows in (tools, after)])
    for name in ('model_saved', 'readback_verified', 'automatic_retry', 'automatic_replay',
        'assignment_attempted', 'GTP_attempted', 'GOP_attempted', 'operation_creation_attempted', 'production_qualified'):
        failed[name]=False
    for left,right in (('parent_pin','parent_pin'), ('historical_source_pin','historical_source_pin'),
        ('recipe','recipe'), ('recipe_pin','recipe_pin'), ('catalogue_pin','catalogue_pin'),
        ('settings_before','settings'), ('generated_face_operation_id','generated_face_operation_id'),
        ('toolpath_record_counts','toolpath_record_counts'), ('live_pins','pins'),
        ('offline_proof_pins','offline_export_proof_pins'), ('phase_retired_pins','tool_phase_retired')):
        failed[left]=deepcopy(loaded[right])
    marker=m.base.Journal(failed, failed['receipt_path'], tmp_path/'marker.json').marker_state()
    return failed,loaded,marker


@pytest.fixture
def case(tmp_path):
    return build_case(tmp_path)


def test_completed_failure_reuses_synthetic_baseline(case):
    failed, loaded, marker = case
    result = m.validate_resume_evidence(*case)
    assert result['new_tool_native_id'] == 9000
    assert len(result['baseline']['protected_tools']) == 17
    assert len(result['catalogue_after_creation']) == 18
    assert result['current_document']['needs_save'] is False
    assert result['event_cleanup_observed'] is False
    assert result['prior_python_exit_proved_by_receipt'] is False
    assert result['required_fresh_full_snapshots'] == 2
    assert result['requires_fresh_event_scope'] is True
    assert result['requires_reacquired_prior_holder_identities'] is True
    assert result['creator_replay_allowed'] is False
    result['baseline']['tools'].clear()
    assert len(failed['initial_observation']['tools']) == 17


@pytest.mark.parametrize('field,value', [
    ('model_saved', True), ('model_saved', 0), ('readback_verified', True),
    ('phase_proofs_verified_after_native', 1), ('automatic_replay', True),
    ('assignment_attempted', True), ('GTP_attempted', True),
    ('full_tool_snapshot_count', True), ('candidate_profile_capture_count', False),
    ('candidate_profile_capture_count', 1), ('new_tool_native_id', True),
    ('process_id', True), ('current_before_sha256', '0'*64),
])
def test_bad_failure_flag_rejected(case, field, value):
    case[0][field] = value
    with pytest.raises((ValueError, KeyError, TypeError)):
        m.validate_resume_evidence(*case)


@pytest.mark.parametrize('name', ['field_readbacks', 'save_stage', 'source_transition',
                                  'candidate_reads', 'cleanup_issue', 'phase_proof_error'])
def test_any_later_or_uncertain_work_rejected(case, name):
    case[0][name] = []
    with pytest.raises(ValueError):
        m.validate_resume_evidence(*case)


def test_pending_creator_rejected(case):
    case[0]['actions']['AddNewTool3']['pending'] = True
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_second_action_rejected(case):
    case[0]['actions']['property:EndDia'] = dict(attempted=True, returned=False, pending=True)
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_marker_substitution_rejected(case):
    case[2]['new_tool_native_id'] += 1
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_runtime_replacement_requires_separate_derived_closure(case):
    case[1]['pins'][0]['sha256'] = '0'*64
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_dirty_flag_must_not_be_inferred(case):
    case[0]['current_document']['needs_save'] = True
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_event_error_rejected(case):
    case[0]['messages']['event_count'] = 1
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_modified_route_rejected(case):
    case[0]['initial_observation']['route']['operations'][0]['native_id'] += 1000
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_incomplete_old_tool_profile_rejected(case):
    case[0]['initial_observation']['protected_tools']['253']['profiles']['tool']['chains'][0]['read_complete'] = False
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_incomplete_batch_rejected(case):
    case[0]['protected_tool_observations'][0]['batches'][0]['read_scope_complete'] = False
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_incomplete_profile_read_rejected(case):
    case[0]['protected_tool_observations'][0]['tool_reads'][0]['read_complete'] = False
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_changed_old_catalogue_rejected(case):
    case[0]['scalar_catalogue_reads'][1]['rows'][0]['Protrusion'] += 1.0
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_wrong_new_type_rejected(case):
    case[0]['scalar_catalogue_reads'][1]['rows'][-1]['tool_type_raw'] = 11
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_bool_catalogue_id_rejected(case):
    case[0]['scalar_catalogue_reads'][1]['rows'][-1]['native_id'] = True
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)


def test_wrong_process_creation_rejected(case):
    case[1]['ownership']['create_time'] = 0.0
    with pytest.raises(ValueError): m.validate_resume_evidence(*case)
