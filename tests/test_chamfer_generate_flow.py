"""Portable single-target Contour configuration/generation protocol tests."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

STAGE = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', STAGE))
sys.path.insert(0, str(RUNTIME))
import scripts
scripts.__path__.insert(0, str(STAGE/'scripts'))
from scripts import sw_cam_chamfer_generate as m
spec = importlib.util.spec_from_file_location('generate_insert_fixture', RUNTIME/'tests/test_chamfer_insert_defaults.py')
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)


class Fake:
    def __init__(self, loaded, report, source):
        self.loaded, self.report, self.source = loaded, report, source
        self.current_state = deepcopy(loaded['state'])
        self.route = m.tools.expected_route(loaded)
        self.settings = deepcopy(loaded['inserted_contour']['defaults'])
        self.calls = []; self.fault = None; self.save_return = 0
        self.assign_return = 0; self.generate_return = 0; self.angle_value = 45.
        self.field_return = {}; self.skip_write = None
    @property
    def row(self): return self.route['operations'][-1]
    def call(self, name):
        self.calls.append(name)
        if self.fault == name: raise RuntimeError('injected '+name)
    def start(self):
        self.call('start')
        self.report['recipe_interface_audit']=dict(all_resolved=True,native_calls=0)
    def snapshot(self, label):
        self.call('snapshot:'+label)
        route = deepcopy(self.route)
        catalog = deepcopy(self.loaded['operation_checkpoint']['final_observation']['tools'])
        feature = deepcopy(self.loaded['cone_observation']['feature'])
        if self.fault == 'old_state:'+label: route['operations'][0]['suppressed'] = True
        if self.fault == 'tools:'+label: catalog[0]['CutDiameter'] += 1
        if self.fault == 'feature:'+label: feature['taper_angle_readback'] = 46.
        if self.fault == 'counts_bool' and label == 'generated': route['operations'][-1]['toolpath_record_counts'] = [True]
        self.current_state['operations'] = deepcopy(route['operations'])
        return dict(route=route, tools=catalog, feature=feature)
    def operation_defaults(self, oid, label):
        assert oid == 100
        self.call('defaults:'+label)
        value = deepcopy(self.settings)
        if self.fault == 'defaults_drift:'+label: value['finish']['GetContainAllowance'] += .1
        return value
    def assign(self, pending):
        pending(); self.call('assign')
        self.row['assigned_tool'] = m.expected_tool(self.loaded)
        self.settings['finish']['GetChamferAngle'] = self.angle_value
        return self.assign_return
    def current_tool(self):
        self.call('current_tool')
        value = deepcopy(self.row['assigned_tool'])
        if self.fault == 'wrong_tool': value['native_id'] += 1
        return value
    def angle(self):
        self.call('angle'); return self.settings['finish']['GetChamferAngle']
    def field(self, spec):
        self.call('field:'+spec[0])
        if spec[0] == 'depth_override': return self.settings['level_state']['levels']['override_machining_depth']
        if spec[0] == 'machining_depth': return self.settings['level_state']['levels']['machining_depth_value_native']
        return self.settings['finish'][spec[2]]
    def write_field(self, spec, value, pending):
        pending(); self.call('write:'+spec[0])
        if self.skip_write != spec[0]:
            if spec[0] == 'depth_override': self.settings['level_state']['levels']['override_machining_depth'] = value
            elif spec[0] == 'machining_depth': self.settings['level_state']['levels'].update(machining_depth_value_native=value, machining_depth_native=value)
            else: self.settings['finish'][spec[2]] = value
        return self.field_return.get(spec[0], None if spec[4] == 'property' else 0)
    def depth_readback(self):
        self.call('depth_readback'); v = self.settings['level_state']['levels']
        return dict(machining_depth=.2 if self.fault == 'depth_not_effective' else v['machining_depth_native'],
            override=v['override_machining_depth'], stored_depth=v['machining_depth_value_native'])
    def refresh_dirty(self): self.call('refresh_dirty')
    def generate(self, pending):
        pending(); self.call('generate')
        self.row.update(toolpath_generated=True, toolpath_record_counts=[32])
        return self.generate_return
    def boundary(self): self.call('guard')
    def save(self):
        self.call('save')
        if self.fault != 'unchanged_source': self.source.write_bytes(b'generated-contour-saved')
        return self.save_return
    def saved_hash(self, save):
        self.call('saved_hash'); sha = m._file_hash(self.source)
        self.current_state['saved_file_sha256'] = sha
        self.current_state['document']['needs_save'] = False
        self.report['source_transition'] = dict(source_before_sha256=self.loaded['source_sha256'],
            source_after_sha256=sha, strict_save_return=0, document=deepcopy(self.current_state['document']))
        return sha
    def finish(self):
        self.call('finish')
        self.report['messages'] = dict(subscribed=True,active=False,disconnected=True,event_count=0,
            overflow=False,callback_errors=[],callback_error_count=0)
    def close(self): self.call('close')


@pytest.fixture
def case(tmp_path, monkeypatch):
    prior = t.case.__wrapped__(tmp_path, monkeypatch)
    loaded = deepcopy(prior.loaded)
    settings = deepcopy(prior.b.defaults)
    settings['finish'].update(SideAllow=1., DepthAllow=0., SpringPass=2, OverridePrevAllow=False,
        GetPreviousAllowance=1., GetContainType=0, GetContainAllowance=2.54,
        GetIsChamferMachining=False,GetChamferType=0,GetChamferLength=2.54,
        GetChamferClearance=0.,GetChamferAngle=90.)
    settings['level_state']['levels'].update(machining_depth_native=.2,
        override_machining_depth=False,machining_depth_value_native=.2)
    default_tool = dict(native_id=121,is_mill_tool=True,native_read_complete=True,
        units_verified=False,holder_geometry_verified=False,tool_type_raw=1,
        cut_diameter_native=12.,protrusion_native=50.)
    row=dict(setup_index=0,setup_native_id=20,operation_index=7,native_id=100,
        mill_operation_type=1,base_operation_type=9,suppressed=False,toolpath_generated=False,
        linked_feature_ids=[70],toolpath_record_counts=[],assigned_tool=default_tool)
    loaded['state']['operations'].append(row); loaded['state']['operation_count']=8
    loaded['state']['operation_counts'][0]=8; loaded['state']['operation_setups'][0]['operation_count']=8
    loaded['local_tool_candidate'] = dict(native_id=120,tool_type_raw=8,
        parameters=dict(CutDiameter=.6,EndDia=.6,MaxDia=2.,Protrusion=20.))
    catalog=[dict(native_id=120,tool_type_raw=8,CutDiameter=.6,Protrusion=20.,StnNo=0),
             dict(native_id=121,tool_type_raw=1,CutDiameter=12.,Protrusion=50.,StnNo=0)]
    loaded.update(inserted_contour=dict(native_id=100,feature_native_id=70,defaults=settings),
        operation_checkpoint=dict(final_observation=dict(tools=catalog)),
        insertion_source_archive_pin=loaded['tool_source_archive_pin'], generation_phase_retired_pins=[],
        recipe=dict(fields=[dict(field=x[0],target=x[-1]) for x in m.FIELDS],
            physical_target=dict(chamfer_width_mm=.2,flank_degrees=45.,tool_tip_world_z_mm=25.5,
                tool_axis_radius_mm=22.75,profile='accepted_existing_tool'),
            angle_policy='raw_getter_preserved_physical_acceptance_requires_CL',
            preserved_defaults=dict(OverridePrevAllow=False,GetPreviousAllowance=1.,GetContainType=0,GetContainAllowance=2.54),
            source_pins=[loaded['parent_pin']]),recipe_pin=loaded['parent_pin'])
    loaded['current_context_sha256']=m._digest(m.group.current_projection(loaded))
    params=dict(prior.p,receipt_path=str(tmp_path/'generate.json'),operation_native_id=100,tool_native_id=120)
    monkeypatch.setattr(m,'load_inputs',lambda p,check_current=True:deepcopy(loaded))
    monkeypatch.setattr(m,'marker_path',lambda *args:tmp_path/'generate.marker.json')
    _,report,marker=m.prepare(params)
    journal=m.Journal(report,params['receipt_path'],marker)
    return SimpleNamespace(loaded=loaded,p=params,r=report,j=journal,b=Fake(loaded,report,prior.source),source=prior.source)


def run(c): return m.run_backend(c.b,c.j,c.loaded)


def complete(c):
    result=run(c); assert result['readback_verified'], result.get('issue')
    result['phase_proofs_verified_after_native']=True
    result['checkpoint']=m.make_checkpoint(result); result['checkpoint_sha256']=m._digest(result['checkpoint'])
    m.validate_terminal(result,c.loaded)
    c.j.persist(); result['marker_pin']=m.exports._pin(c.j.marker); c.j.persist()
    return result


def test_existing_target_one_assignment_one_gtp_one_save(case):
    r=complete(case); assert r['readback_verified'],r.get('issue')
    assert r['model_saved'] and r['target_generated'] and not r['geometry_acceptance_complete']
    assert case.b.calls.count('assign')==case.b.calls.count('generate')==case.b.calls.count('save')==1
    assert [x for x in case.b.calls if x.startswith('snapshot:')]==[
        'snapshot:before','snapshot:configured','snapshot:generated','snapshot:saved']
    assert r['generated_record_counts']==[32] and r['full_tool_profile_capture_count']==0
    assert r['assignment_after']['cut_diameter_native']==.6
    assert 'field:depth_allowance' not in r['actions']
    assert r['final_defaults']['finish']['GetPreviousAllowance']==1.
    assert r['final_defaults']['finish']['GetContainType']==0
    assert set(r['actions'])=={'SetTool','GenerateToolpath','SaveActiveDocument'}|{
        'field:'+s[0] for s in m.FIELDS if s[0]!='depth_allowance'}
    assert all('Create' not in x and 'Insert' not in x and 'Profile' not in x for x in case.b.calls)
    assert r['before']['route']['operations'][:-1]==r['final_observation']['route']['operations'][:-1]


@pytest.mark.parametrize('fault',['start','old_state:before','tools:before','feature:before','defaults_drift:before_configuration'])
def test_stale_baseline_stops_before_mutation(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and r['actions']=={} and not case.j.marker.exists()
    assert 'assign' not in case.b.calls and 'generate' not in case.b.calls and 'save' not in case.b.calls


@pytest.mark.parametrize('stage,label',[('assign','SetTool'),('write:chamfer_length','field:chamfer_length'),
    ('generate','GenerateToolpath'),('save','SaveActiveDocument')])
def test_pending_failure_never_replayed(case,stage,label):
    case.b.fault=stage;r=run(case)
    assert not r['readback_verified'] and r['status']=='uncertain' and r['actions'][label]['pending'] is True
    assert case.b.calls.count(stage)==1
    other=m.Journal(r,Path(case.p['receipt_path']).with_name('renamed.json'),case.j.marker)
    with pytest.raises(ValueError):other.claim()
    with pytest.raises(ValueError):case.j.pending(label)


@pytest.mark.parametrize('fault',['wrong_tool','depth_not_effective','old_state:configured','tools:configured',
    'feature:configured','defaults_drift:configured'])
def test_changed_affected_or_protected_state_blocks_gtp_and_save(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and 'generate' not in case.b.calls and 'save' not in case.b.calls


def test_unapplied_scalar_write_stops_at_immediate_readback(case):
    case.b.skip_write='chamfer_length';r=run(case)
    assert not r['readback_verified'] and 'write:side_allowance' not in case.b.calls
    assert case.b.calls.count('write:chamfer_length')==1 and 'generate' not in case.b.calls


@pytest.mark.parametrize('action,value',[('assign',False),('generate',False),('save',False),('save',0.),
    ('property',0),('method',None)])
def test_exact_native_return_shapes_required(case,action,value):
    if action=='property':case.b.field_return['side_allowance']=value
    elif action=='method':case.b.field_return['chamfer_length']=value
    else:setattr(case.b,action+'_return',value)
    r=run(case);assert not r['readback_verified']
    assert case.b.calls.count('save') <= 1
    if action not in ('generate','save'):assert 'generate' not in case.b.calls
    if action=='save':assert 'saved_hash' not in case.b.calls


@pytest.mark.parametrize('fault',['counts_bool','old_state:generated','defaults_drift:generated'])
def test_invalid_generation_never_saved(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and case.b.calls.count('generate')==1 and 'save' not in case.b.calls


@pytest.mark.parametrize('fault',['unchanged_source','old_state:saved','defaults_drift:saved','finish'])
def test_failed_save_readback_never_saves_twice(case,fault):
    case.b.fault=fault;r=run(case)
    assert not r['readback_verified'] and case.b.calls.count('save')==1
    assert r['actions']['SaveActiveDocument']['returned'] is True


def test_raw_90_degree_getter_is_not_false_geometry_rejection(case):
    case.b.angle_value=90.;r=run(case)
    assert r['readback_verified'],r.get('issue')
    assert r['assigned_tool_angle_raw']==90. and r['angle_readback_is_not_physical_qualification'] is True
    assert r['geometry_acceptance_complete'] is False
