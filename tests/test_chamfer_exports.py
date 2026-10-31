"""Eight-operation CL adapter tests with real export core and synthetic COM."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

STAGE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', STAGE))
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'tests'))
import scripts
scripts.__path__.insert(0, str(STAGE/'scripts'))
from scripts import sw_cam_chamfer_exports as m
from scripts import sw_cam_mill_generic_cl as cl
from scripts import sw_cam_events
from cam_face_test_fixtures import current
spec = importlib.util.spec_from_file_location('chamfer_export_defaults_graph', ROOT/'tests/test_chamfer_defaults.py')
graph = importlib.util.module_from_spec(spec); spec.loader.exec_module(graph)


class Session:
    def __init__(self, *args): self.active = False
    def __enter__(self): self.active = True; return self
    def __exit__(self, *args): self.active = False
    def summary(self):
        return dict(subscribed=True, active=self.active, disconnected=not self.active, event_count=0,
            overflow=False, callback_errors=[], callback_error_count=0, subscription_error=None, disconnect_errors=[])


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    source = tmp_path/'source.SLDPRT'; source.write_bytes(b'synthetic saved generated CAM')
    loaded = current(); state = loaded['state']
    state['document'].update(path=str(source), title=source.name, needs_save=False)
    state['saved_file_sha256'] = loaded['source_sha256'] = m._file_hash(source)
    byid = {v['native_id']:v for v in state['operations']}
    state['operations'] = [byid[n] for n in m.PREFIX]
    byid[267].update(toolpath_generated=True, toolpath_record_counts=[760], assigned_tool=deepcopy(byid[248]['assigned_tool']))
    for i, v in enumerate(state['operations']): v['operation_index'] = i
    candidate = dict(native_id=269, tool_type_raw=8, parameters={'CutDiameter':.6, 'Protrusion':20., 'StnNo':18.})
    row = deepcopy(byid[248]); row.update(native_id=271, operation_index=7, linked_feature_ids=[264],
        mill_operation_type=1, setup_native_id=93, setup_index=0, toolpath_generated=True,
        toolpath_record_counts=[32], assigned_tool={'native_id':269, 'tool_type_raw':8})
    state['operations'].append(row); state['operation_count'] = 8
    state['operation_counts'][0] = 8; state['operation_setups'][0]['operation_count'] = 8
    # Reduced scalar-only fixture from the actual saved catalogue chain.
    catalogue_rows = [(250,1,6.,25.), (251,1,10.,50.), (252,1,12.,50.), (249,1,8.,25.),
        (145,1,2.,20.), (253,6,6.,22.5), (254,1,4.,25.), (255,1,10.,40.),
        (256,1,12.,50.), (257,3,1.,76.), (258,9,5.,40.), (259,18,50.,40.),
        (260,19,4.,100.), (261,20,10.,50.), (197,6,10.,25.), (198,2,19.,170.), (263,14,8.,25.)]
    tools = [dict(native_id=i, tool_type_raw=k, CutDiameter=d, Protrusion=p, StnNo=float(n+1))
        for n,(i,k,d,p) in enumerate(catalogue_rows)]
    loaded['payload']['candidate'] = {'tools':deepcopy(tools)}
    loaded['payload']['candidate']['tools'][3].update(CutDiameter=16.,Protrusion=60.)
    loaded['tool_checkpoint'] = {'initial_observation':{'tools':deepcopy(tools)}}
    tools.append(dict(native_id=269, tool_type_raw=8, **candidate['parameters']))
    loaded['tool_checkpoint']['final_observation'] = {'tools':deepcopy(tools)}
    loaded['insertion_checkpoint'] = {'final_observation':{'tools':deepcopy(tools)}}
    setting = graph.Graph().run()
    loaded.update(settings=m.group.expected_settings(True), generated_face_operation_id=267,
        toolpath_record_counts=[760], local_tool_candidate=candidate,
        configured_contour=dict(native_id=271, feature_native_id=264, tool_native_id=269,
            operation_type=1, generated=True, record_counts=[32], defaults=setting),
        operation_checkpoint={'final_observation':{'tools':tools}},
        pins=[], offline_export_proof_pins=[], bootstrap_export_pins=[], export_phase_retired_pins=[])
    loaded['cone_observation'] = {'feature':{'native_id':264,'taper_enabled':True,'taper_angle_readback':45.}}
    loaded['finish_payload']['unit_record'] = {'metric_document_scope_observed':True}
    for key, name in [('parent_pin','generation.json'), ('group_marker_pin','generated-marker.json')]:
        path = tmp_path/name; path.write_text('{}'); loaded[key] = m.common._pin(path); loaded['pins'].append(loaded[key])
    loaded['current_context_sha256'] = m._digest(m.group.current_projection(loaded))
    args = dict(process_id=123, expected_document_path=str(source), expected_source_sha256=m._file_hash(source),
        receipt_path=str(tmp_path/'export.json'), qualification_only=True, acknowledge_disposable_copy=True,
        message_policy='vendor_default')
    control = SimpleNamespace(calls=0, labels=[], result=0, fail=None, drift=None, event=False, after_native=None)
    class Machine:
        def GetController2(self): return [False, 'fixture-controller', True]
        def SaveCLFile(self, path):
            control.calls += 1
            receipt = json.loads(Path(args['receipt_path']).read_text())
            marker = m.marker_path(source, args['expected_source_sha256'], 271)
            assert receipt['native_dispatch_pending'] is True
            assert json.loads(marker.read_text())['native_dispatch_pending'] is True
            Path(path).write_text('UNITS/MM\nFINI\n')
            if control.fail: raise RuntimeError(control.fail)
            if control.after_native: control.after_native()
            return control.result
    machine = Machine()
    class Backend:
        def __init__(self, loaded, args, sw, clsid, tlb, report, persist, external_events):
            self.loaded, self.args, self.report, self.persist = loaded, args, report, persist
            self.native = {'machine':machine}; self.external_events = external_events
            self.ctx = SimpleNamespace(app=None, files=self.files, identity=self.identity)
        def files(self): m.common._check(self.loaded['pins'])
        def identity(self):
            if m._file_hash(source) != self.args['expected_source_sha256']: raise ValueError('Changed source')
            return deepcopy(loaded['state']['document'])
        def boundary(self): self.files(); self.identity(); self.external_events(True)
        def capture_export(self, label):
            self.boundary(); control.labels.append(label)
            observed = dict(state=deepcopy(loaded['state']), catalogue=deepcopy(tools),
                selected_defaults=deepcopy(setting), selected_feature=deepcopy(loaded['cone_observation']['feature']),
                settings=deepcopy(loaded['settings']), units=deepcopy(loaded['finish_payload']['unit_record']),
                binding=deepcopy(byid[267]['assigned_tool']))
            if control.drift: control.drift(label, observed)
            return observed
    monkeypatch.setattr(m, 'ReadBackend', Backend)
    monkeypatch.setattr(cl, '_bootstrap', lambda *a:object())
    monkeypatch.setattr(cl, '_typed', lambda obj,*a:obj)
    class BoundSession(Session):
        def summary(self):
            r = super().summary(); r['event_count'] = 1 if control.event else 0; return r
    monkeypatch.setattr(sw_cam_events, 'CamMessageSession', BoundSession)
    return SimpleNamespace(loaded=loaded, args=args, source=source, root=tmp_path, control=control)


def run(f):
    return m.export_cl(object(), 'fixture', 'fixture.tlb', loaded=f.loaded, args=f.args,
                       output_path=str(f.root/'cl_output'/'out.cl'))


def test_existing_core_exports_exact_four_without_mutating_or_profiles(case):
    r = run(case)
    assert r['readback_verified'] is True, r
    assert r['output_verified'] is True and r['checkpoint_export_readback_verified'] is True
    assert r['phase_proofs_verified_after_export'] is True
    assert case.control.calls == 1 and len(case.control.labels) == 3
    assert r['before']['expected_generated_operations'] == m.operation_contract(case.loaded)
    assert [v['operation_native_id'] for v in m.operation_contract(case.loaded)] == [267,247,248,271]
    assert all(r[k] is False for k in ('GTP_attempted','GOP_attempted','model_saved','assignment_attempted','setter_attempted'))
    assert r['full_tool_profile_capture_count'] == 0
    assert 'all_tool_profiles' in r['reused_fields'] and 'scalar_tool_catalogue' in r['fresh_fields']
    assert m._file_hash(case.source) == case.args['expected_source_sha256']


@pytest.mark.parametrize('value',[None, False, True, 1, -1, 0.0])
def test_nonstrict_return_consumes_once_and_never_retries(case, value):
    case.control.result = value
    r = run(case)
    assert r['status'] == 'uncertain' and r['readback_verified'] is False and case.control.calls == 1
    assert len(case.control.labels) == 2
    before = Path(case.args['receipt_path']).read_bytes()
    case.args['receipt_path'] = str(case.root/'renamed.json')
    with pytest.raises(ValueError): run(case)
    assert (case.root/'export.json').read_bytes() == before and case.control.calls == 1


def test_native_exception_preserves_pending_no_postread(case):
    case.control.fail = 'injected'
    r = run(case)
    assert r['native_dispatch_pending'] is True and r['status'] == 'uncertain'
    assert case.control.calls == 1 and len(case.control.labels) == 2


@pytest.mark.parametrize('kind',['old_count','new_count','tool','catalogue','defaults','feature','dirty','face','units'])
def test_changed_preexport_observation_blocks_dispatch(case, kind):
    def drift(label, obs):
        if kind == 'old_count': obs['state']['operations'][4]['toolpath_record_counts'] = [761]
        elif kind == 'new_count': obs['state']['operations'][-1]['toolpath_record_counts'] = [33]
        elif kind == 'tool': obs['state']['operations'][-1]['assigned_tool']['native_id'] = 252
        elif kind == 'catalogue': obs['catalogue'][-1]['CutDiameter'] = 2.
        elif kind == 'defaults': obs['selected_defaults']['finish']['GetChamferLength'] += .1
        elif kind == 'feature': obs['selected_feature']['extra'] = 1
        elif kind == 'dirty': obs['state']['document']['needs_save'] = True
        elif kind == 'face': obs['settings']['face']['CutOrder'] += 1
        elif kind == 'units': obs['units']['metric_document_scope_observed'] = False
    case.control.drift = drift
    r = run(case)
    assert r['readback_verified'] is False and case.control.calls == 0


def test_postexport_target_drift_persists_actual_evidence(case):
    def drift(label, obs):
        if 'after' in label: obs['selected_defaults']['finish']['GetChamferLength'] += .1
    case.control.drift = drift
    r = run(case)
    assert r['status'] == 'uncertain' and r['readback_verified'] is False and case.control.calls == 1
    raw = json.loads(Path(case.args['receipt_path']).with_suffix('.observations.json').read_text())
    assert raw['observations'][-1]['selected_defaults']['finish']['GetChamferLength'] != case.loaded['configured_contour']['defaults']['finish']['GetChamferLength']


@pytest.mark.parametrize('value',[True,0,-1,32.0])
def test_saved_target_counts_are_not_guessed(case,value):
    case.loaded['configured_contour']['record_counts'] = [value]
    case.loaded['state']['operations'][-1]['toolpath_record_counts'] = [value]
    with pytest.raises(ValueError): m.operation_contract(case.loaded)


def test_same_counts_with_wrong_operation_order_rejected(case):
    case.loaded['state']['operations'][4:6] = reversed(case.loaded['state']['operations'][4:6])
    with pytest.raises(ValueError): m.operation_contract(case.loaded)


def test_old_catalogue_mismatch_not_filtered_away(case):
    case.loaded['operation_checkpoint']['final_observation']['tools'][0]['CutDiameter'] = 3.
    with pytest.raises(ValueError): m.validate_catalogue_authority(case.loaded)


def test_offline_proof_drift_after_export_invalidates_success(case):
    path = case.root/'offline.json'; path.write_text('{}')
    case.loaded['offline_export_proof_pins'] = [m.common._pin(path)]
    case.control.after_native = lambda:path.write_text('{"changed":true}')
    r = run(case)
    assert case.control.calls == 1 and r['readback_verified'] is False
    assert r['phase_proofs_verified_after_export'] is False and r['status'] == 'uncertain'


def test_mass_roundoff_only_is_preserved_in_raw_evidence(case):
    def drift(label, obs): obs['state']['sw_reference']['solids'][0]['mass_raw'][0] *= 1.+1e-13
    case.control.drift = drift
    r = run(case)
    assert r['readback_verified'] is True
    raw = json.loads(Path(case.args['receipt_path']).with_suffix('.observations.json').read_text())
    assert raw['observations'][0]['state']['sw_reference']['solids'][0]['mass_raw'][0] != case.loaded['state']['sw_reference']['solids'][0]['mass_raw'][0]

@pytest.mark.parametrize('value',[float('nan'),float('inf'),complex(1,2),object()])
def test_non_json_native_return_is_bounded_and_once_consumed(case,value):
    case.control.result = value
    r = run(case)
    assert r['readback_verified'] is False and r['status'] == 'uncertain'
    assert case.control.calls == 1 and len(case.control.labels) == 2
    assert r['native_hresult'] is None and r['bounded_native_hresult']['value_recorded'] is False
    raw = json.loads(Path(case.args['receipt_path']).read_text())
    assert raw['native_hresult'] is None and raw['readback_verified'] is False
    case.args['receipt_path'] = str(case.root/'second.json')
    with pytest.raises(ValueError): run(case)
    assert case.control.calls == 1


def test_phase_closure_keeps_exact64_with_documented_inactive_retirements(case):
    names = ['sw_cam_chamfer_generate.py','sw_cam_ud14_save.py','sw_cam_taper_profile.py',
             'sw_cam_ud14_qualification.py','sw_cam_shared_holder_geometry.py']
    pins = []
    for name in names + ['live_'+str(i)+'.py' for i in range(59)]:
        path = case.root/name; path.write_text('immutable proof')
        pins.append(m.common._pin(path))
    case.loaded['pins'] = pins
    live, offline, retired = m.derive_closure(case.loaded)
    assert len(live) == 64 and len(offline) == 5
    assert {Path(p['path']).name for p in retired} == set(names)
    assert not {p['path'] for p in live}.intersection({p['path'] for p in retired})
    assert case.loaded['pins'] == pins
    Path(retired[0]['path']).write_text('changed proof')
    with pytest.raises(ValueError): m.common._check(offline)


def test_missing_phase_role_is_not_silently_dropped(case):
    with pytest.raises(ValueError): m.derive_closure(case.loaded)


def test_actual_replaced_tool_metadata_uses_qualified_current_chain(case):
    old = case.loaded['payload']['candidate']['tools'][3]
    qualified = case.loaded['tool_checkpoint']['initial_observation']['tools'][3]
    assert old['native_id'] == qualified['native_id'] == 249
    assert (old['CutDiameter'], old['Protrusion']) == (16.,60.)
    assert (qualified['CutDiameter'], qualified['Protrusion']) == (8.,25.)
    before = deepcopy(case.loaded)
    actual = m.validate_catalogue_authority(case.loaded)
    assert actual[3] == qualified and len(actual) == 18
    assert case.loaded == before


@pytest.mark.parametrize('checkpoint,phase',[('tool_checkpoint','initial_observation'),
    ('tool_checkpoint','final_observation'),('insertion_checkpoint','final_observation')])
def test_changed_qualified_catalogue_chain_rejected(case,checkpoint,phase):
    case.loaded[checkpoint][phase]['tools'][3]['CutDiameter'] = 16.
    with pytest.raises(ValueError): m.validate_catalogue_authority(case.loaded)
