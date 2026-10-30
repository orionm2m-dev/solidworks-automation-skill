"""Portable addressed-resume orchestration tests; no native dispatch."""
from copy import deepcopy
import importlib.util
import math
import os
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', ROOT))
os.environ.setdefault('SOLIDWORKS_SKILL_ROOT', str(RUNTIME))
sys.path.insert(0, str(RUNTIME))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


for name in ('sw_cam_taper_interfaces', 'sw_cam_taper_resume_evidence'):
    module('scripts.'+name, ROOT/'scripts'/f'{name}.py')
m = module('taper_resume_flow_under_test', ROOT/'scripts/sw_cam_taper_tool_resume.py')
w = module('taper_resume_shared_writer_fixture', RUNTIME/'tests/test_taper_tool_writer.py')


class FakeResume(w.FakeBackend):
    def __init__(self, loaded, recipe, report):
        super().__init__(loaded, recipe, report)
        self.new = True
        self.parameters.update(EndDia=1., TaperLength=1., TaperAngle=45., MaxDia=3., CutDiameter=3.)

    def create(self, *args, **kwargs):
        raise AssertionError('Creator must never be reached in addressed resume')

    def tools(self):
        out = super().tools()
        out[-1]['CutDiameter'] = self.parameters['MaxDia']
        return out

    def bind_created(self, ident):
        self.call('bind_created')
        assert ident == 900
        rows = self.tools()
        if self.fault == 'catalogue_changed': rows[-1]['native_id'] += 1
        return rows

    def read_narrow(self, label):
        self.call('read_narrow:'+label)
        row = m.base.expected_route(self.loaded)
        if self.fault == 'route_changed': row['operation_counts'] = [999]
        return row

    def save_projection(self, current):
        return deepcopy(current)

    def property(self, name, value, pending):
        result = super().property(name, value, pending)
        self.parameters['MaxDia'] = self.parameters['EndDia'] + 2*self.parameters['TaperLength']*math.tan(
            math.radians(self.parameters['TaperAngle']))
        self.parameters['CutDiameter'] = self.parameters['MaxDia']
        return result


@pytest.fixture
def case(tmp_path, monkeypatch):
    c = w.case.__wrapped__(tmp_path, monkeypatch)
    c.b = FakeResume(c.loaded, c.recipe, c.r)
    c.r.update(scope=m.SCOPE, new_tool_native_id=900, full_tool_snapshot_count=0,
        candidate_profile_capture_count=0, inherited_full_tool_snapshot_count=1,
        failure_pin=dict(sha256='f'*64), creation_marker_pin=dict(sha256='e'*64),
        initial_observation=dict(route=m.base.expected_route(c.loaded),
            units=deepcopy(c.loaded['finish_payload']['unit_record']),
            protected_tools={'249':deepcopy(c.loaded['finish_payload']['full_tool'])},
            tools=deepcopy(c.b.old)), inherited_created_catalogue=c.b.tools())
    c.j = m.Journal(c.r, tmp_path/'resume.json', tmp_path/'resume.marker.json')
    monkeypatch.setattr(m.base, 'verify_holder_profile', lambda *args: {'scope':'separate_holder_reader_tests'})
    return c


def run(c):
    return m.run_backend(c.b, c.j, c.loaded, c.recipe)


def test_success_reuses_initial_and_never_creates(case):
    result = run(case)
    assert result['readback_verified'] is True, result.get('issue')
    assert result['full_tool_snapshot_count'] == 2
    assert result['candidate_profile_capture_count'] == 3
    assert [v for v in case.b.calls if v.startswith('snapshot:')] == ['snapshot:configured', 'snapshot:save_after']
    assert [v for v in case.b.calls if v.startswith('candidate:')] == ['candidate:cone_proof', 'candidate:configured', 'candidate:save_after']
    assert case.b.calls.count('bind_created') == 1
    assert case.b.calls.count('save') == 1
    assert 'AddNewTool3' not in result['actions']
    assert result['exact_one_tool_created'] is False
    assert result['existing_created_tool_resumed'] is True
    assert result['angle_unit_gate']['degree_compatible'] is True
    assert case.b.calls.index('fields') < case.b.calls.index('property:EndDia')
    assert case.b.calls.index('holder') < case.b.calls.index('property:Protrusion')
    assert case.b.calls.count('property:Protrusion') == 1
    assert case.b.calls[-2:] == ['finish', 'close']


@pytest.mark.parametrize('fault', ['start', 'bind_created', 'catalogue_changed', 'route_changed', 'fields'])
def test_prewrite_failure_does_not_modify_or_repeat(case, fault):
    case.b.fault = fault
    result = run(case)
    assert result['status'] == 'error' and result['readback_verified'] is False
    assert result['actions'] == {} and not case.j.marker.exists()
    assert not any(v.startswith('property:') for v in case.b.calls)
    assert 'save' not in case.b.calls
    assert result['full_tool_snapshot_count'] == 0
    assert case.b.calls[-1] == 'close'


@pytest.mark.parametrize('change', [dict(TaperAngle=math.pi/4), dict(TaperAngle=4.),
                                    dict(TaperLength=0.), dict(TaperAngle=True), dict(MaxDia=0.)])
def test_unknown_angle_units_stop_before_any_setter(case, change):
    case.b.parameters.update(change)
    case.r['inherited_created_catalogue'] = case.b.tools()
    result = run(case)
    assert result['readback_verified'] is False and result['actions'] == {}
    assert result['angle_unit_gate']['degree_compatible'] is False
    assert not any(v.startswith(('property:', 'snapshot:', 'candidate:')) for v in case.b.calls)
    assert 'holder' not in case.b.calls and 'save' not in case.b.calls


@pytest.mark.parametrize('fault', ['property:EndDia', 'holder', 'save'])
def test_failed_native_mutation_stays_pending_and_never_repeats(case, fault):
    case.b.fault = fault
    result = run(case)
    assert result['status'] == 'uncertain' and result['readback_verified'] is False
    label = {'holder':'SetFilePathForUserDefinedHolder', 'save':'SaveActiveDocument'}.get(fault, fault)
    assert result['actions'][label]['pending'] is True
    assert result['actions'][label]['returned'] is False
    assert case.b.calls.count(fault) == 1 and 'AddNewTool3' not in result['actions']


@pytest.mark.parametrize('fault', ['geometry:cone_proof', 'geometry:configured', 'protected:configured'])
def test_profile_or_preservation_failure_blocks_save(case, fault):
    case.b.fault = fault
    result = run(case)
    assert result['status'] == 'uncertain' and result['readback_verified'] is False
    assert 'save' not in case.b.calls
    if fault == 'geometry:cone_proof':
        assert 'property:ShankDia' not in case.b.calls and 'holder' not in case.b.calls


@pytest.mark.parametrize('fault', ['geometry:save_after', 'protected:save_after', 'finish'])
def test_failure_after_save_not_reported_complete(case, fault):
    case.b.fault = fault
    result = run(case)
    assert result['readback_verified'] is False and result['status'] == 'uncertain'
    assert case.b.calls.count('save') == 1 and result['saved_source_sha256'] == 'b'*64


@pytest.mark.parametrize('value', [False, True, None, 1, '0'])
def test_save_requires_strict_zero_hresult(case, value):
    case.b.save_return = value
    result = run(case)
    assert result['readback_verified'] is False and result['status'] == 'uncertain'
    assert case.b.calls.count('save') == 1 and 'saved_hash' not in case.b.calls


def test_existing_resume_marker_stops_first_setter(case):
    case.j.marker.write_text('{"prior":true}')
    result = run(case)
    assert result['readback_verified'] is False
    assert not any(v.startswith('property:') for v in case.b.calls)
    assert 'save' not in case.b.calls
    assert case.j.marker.read_text() == '{"prior":true}'


def test_native_backend_explicitly_disables_creator():
    with pytest.raises(ValueError, match='cannot create'):
        m.NativeBackend.create(None)


def test_save_without_source_change_remains_unverified(case):
    def unchanged(stage):
        case.b.call('saved_hash')
        return 'a'*64
    case.b.saved_hash = unchanged
    result = run(case)
    assert result['readback_verified'] is False and result['status'] == 'uncertain'
    assert case.b.calls.count('save') == 1 and 'saved_source_sha256' not in result
    assert 'snapshot:save_after' not in case.b.calls
