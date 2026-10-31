"""Failure-path tests for the bounded saved Contour approach adapter."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import json
import math
import pytest

STAGE=Path(__file__).resolve().parent
MODULE=STAGE/'sw_cam_chamfer_approach_correction.py'
if not MODULE.is_file():MODULE=STAGE.parent/'scripts/sw_cam_chamfer_approach_correction.py'
spec=importlib.util.spec_from_file_location('bounded_approach',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture():
    source='a'*64
    lead=dict(LeadType=4,LeadAngle=0.,ArcAngle=90.,SidePassType=0,CutDepthType=0,StartAngle=0.,
        GetArcRadius2=[0.,True,0.],GetLeadOverlap2=[0.,True,0.],GetLeadAmt2=[40.,True,0.],
        GetIsSameLeadinout=False,GetFeedRate=[100.,True])
    baseline=dict(nc=dict(FeedPlaneType=0,FeedPlaneDistance=0.,GetUseCurrentMachiningDepthForFeedPlane=False,
        GetClrPlaneUseSetupStatus=True,GetRpdPlaneUseSetupStatus=True),
        local_planes=dict(GetClrPlanePrms=[20.,0],GetRpdPlnPrms=[50.,0]),
        setup_planes=dict(ClearancePlaneType=0,ClearancePlaneDistance=20.,RapidPlaneType=0,RapidPlaneDistance=50.),
        leads={'lead_in':deepcopy(lead),'lead_out':dict(deepcopy(lead),GetIsSameLeadinout=True)})
    changes=[dict(key='same',side='lead_out',before=True,after=False),
        dict(key='clearance_use_setup',side=None,before=True,after=False),
        dict(key='clearance_parameters',side=None,before=[20.,0],after=[.5,0])]
    for side in ('lead_in','lead_out'):
        changes += [dict(key='type',side=side,before=4,after=1),
            dict(key='radius',side=side,before=[0.,True,0.],after=[1.,False,0.]),
            dict(key='length',side=side,before=[40.,True,0.],after=[0.,False,0.])]
    expected=deepcopy(baseline)
    for change in changes:m.put(expected,m.field_path(change),change['after'])
    plan=dict(scope=m.SCOPE,production_qualified=False,target=dict(operation_native_id=271,feature_native_id=264,tool_native_id=269),
        source_sha256=source,baseline=baseline,expected=expected,changes=changes,source_pins=[],
        entry_review_required=True,protected_paths_review_required=True,
        geometry_precheck=dict(accepted_for_native_trial=True,production_qualified=False))
    ops=[]
    for oid,count in ((143,0),(144,0),(195,0),(196,0),(267,760),(247,191),(248,74),(271,22)):
        ops.append(dict(native_id=oid,toolpath_generated=bool(count),toolpath_record_counts=[count] if count else [],
            assigned_tool={'native_id':269 if oid==271 else 249},linked_feature_ids=[264 if oid==271 else oid]))
    state=dict(operation_count=8,operations=ops,features=[{'id':i} for i in range(21)],
        document={'needs_save':False,'path':'unit-test-source'},saved_file_sha256=source,
        operation_setups=[{'id':93}])
    loaded=dict(source_sha256=source,configured_contour=dict(native_id=271,feature_native_id=264,tool_native_id=269),
        state=state,approach_plan=plan)
    before=dict(state=deepcopy(state),approach=deepcopy(baseline),settings={'protected':'FACE'},
        binding={'native_id':249},units={'metric':True},
        selected_defaults={'finish':{'GetChamferLength':.2},'level_state':{'machining_depth_native':.5}},
        catalogue=[{'native_id':i} for i in range(18)],selected_feature={'id':264,'depth':.2})
    return loaded,before


class Journal:
    def __init__(self):
        self.report=dict(initial_source_sha256='a'*64,recipe_pin={'sha256':'c'*64})
    def persist(self):pass
    def pending(self,label):
        assert label not in self.report['actions']
        self.report['actions'][label]=dict(attempted=True,returned=False,pending=True)
        self.report.update(phase=label,mutation_attempted=True)
    def returned(self,label,value):
        self.report['actions'][label].update(returned=True,pending=False,native_return_type=type(value).__name__,native_return_value=value)


class Backend:
    def __init__(self,loaded,before,journal,fault=None):
        self.loaded=loaded;self.value=deepcopy(before);self.r=journal.report;self.calls=[];self.fault=fault
    def start(self):self.calls.append('start')
    def close(self):self.calls.append('close')
    def finish(self):self.calls.append('finish')
    def boundary(self):pass
    def refresh_dirty(self):pass
    def capture_full(self,label):
        self.calls.append('full:'+label)
        if label=='saved' and self.fault=='save_side_effect':self.value['catalogue'][0]['native_id']=999
        return deepcopy(self.value)
    def capture_narrow(self,label):
        self.calls.append('narrow:'+label)
        if label=='configured' and self.fault=='old_operation':self.value['state']['operations'][0]['assigned_tool']['native_id']=100
        value=deepcopy(self.value);value.pop('catalogue');value.pop('selected_feature');return value
    def read_change(self,change):
        return deepcopy(m.at(self.value['approach'],m.field_path(change)))
    def write_change(self,change,pending):
        self.calls.append('write:'+change['key']);pending()
        if self.fault=='setter_raises':raise RuntimeError('uncertain setter')
        if self.fault=='bool_hresult':return False
        if self.fault!='readback':
            m.put(self.value['approach'],m.field_path(change),change['after'])
        self.value['state']['document']['needs_save']=True
        self.value['state']['operations'][-1].update(toolpath_generated=False,toolpath_record_counts=[])
        return None if m.SPECS[change['key']][4]=='property' else 0
    def generate(self,pending):
        self.calls.append('gtp');pending()
        if self.fault=='gtp_false':return False
        self.value['state']['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[31]);return 0
    def save(self):
        self.calls.append('save')
        return 1 if self.fault=='save_return' else 0
    def saved_hash(self,save):
        self.value['state']['document']['needs_save']=False
        self.value['state']['saved_file_sha256']='b'*64
        self.r['source_transition']=dict(source_before_sha256='a'*64,source_after_sha256='b'*64,
            strict_save_return=0,document=deepcopy(self.value['state']['document']))
        return 'b'*64


def run(monkeypatch,fault=None):
    loaded,before=fixture();j=Journal();b=Backend(loaded,before,j,fault)
    # Existing export verifier is independently tested. This seam tests the new
    # write/GTP/save state machine without constructing a native catalogue.
    monkeypatch.setattr(m.exports,'verify_observed',lambda l,v:None)
    return m.run_backend(b,j,loaded),b,loaded,before


def test_success_one_group_two_full_captures_one_gtp_save(monkeypatch):
    r,b,_,_=run(monkeypatch)
    assert r['status']=='review_required' and r['readback_verified']
    assert r['full_capture_count']==2
    assert b.calls.count('gtp')==b.calls.count('save')==1
    assert sum(x.startswith('full:') for x in b.calls)==2
    assert r['generated_record_counts']==[31]
    assert r['final']['approach']['leads']['lead_out']['GetIsSameLeadinout'] is False
    assert r['final']['approach']['leads']['lead_in']['GetFeedRate']==[100.,True]


@pytest.mark.parametrize('fault',['setter_raises','bool_hresult','readback','old_operation'])
def test_failed_write_or_protected_change_prevents_generation(monkeypatch,fault):
    r,b,_,_=run(monkeypatch,fault)
    assert not r['readback_verified'] and r['status']=='uncertain'
    assert 'gtp' not in b.calls and 'save' not in b.calls


@pytest.mark.parametrize('fault',['gtp_false','save_return','save_side_effect'])
def test_no_retry_after_failed_generate_or_save(monkeypatch,fault):
    r,b,_,_=run(monkeypatch,fault)
    assert not r['readback_verified'] and r['status']=='uncertain'
    assert b.calls.count('gtp')==1
    assert b.calls.count('save')==(0 if fault=='gtp_false' else 1)


@pytest.mark.parametrize('field,value',[('after',[1.,True,0.]),('after',[float('nan'),False,0.]),('before',[0.,1,0.])])
def test_reject_unaccepted_percent_nonfinite_or_bool_shape(field,value):
    loaded,_=fixture();plan=loaded['approach_plan'];plan['changes'][4][field]=value
    with pytest.raises(ValueError):m.planned_states(plan)


def test_shared_lead_must_be_detached_first():
    loaded,_=fixture();plan=loaded['approach_plan'];plan['changes'].pop(0)
    with pytest.raises(ValueError):m.planned_states(plan)


def test_no_enum_or_rapid_plane_setter_available():
    loaded,_=fixture();plan=loaded['approach_plan'];plan['changes'][0]['key']='RapidPlaneDistance'
    with pytest.raises(ValueError):m.planned_states(plan)


def test_clearance_basis_cannot_be_changed():
    loaded,_=fixture();plan=loaded['approach_plan'];plan['changes'][2]['after'][1]=1
    with pytest.raises(ValueError):m.planned_states(plan)


def test_current_depth_distance_rejected_when_semantic_false():
    loaded,_=fixture();plan=loaded['approach_plan']
    plan['changes']=[dict(key='feed_plane_distance',side=None,before=0.,after=.5)]
    with pytest.raises(ValueError):m.planned_states(plan)


def test_recipe_must_match_actual_target():
    loaded,before=fixture();loaded['approach_plan']['target']['feature_native_id']=265
    with pytest.raises(ValueError):m.validate_plan(loaded['approach_plan'],loaded,before['approach'])


def test_old_generated_path_count_is_protected():
    loaded,before=fixture();changed=deepcopy(before['state'])
    changed['operations'][4]['toolpath_record_counts']=[759]
    with pytest.raises(ValueError):m.verify_route(before['state'],changed,271,'generated')


def test_target_path_may_invalidate_but_not_silently_change_after_setter():
    loaded,before=fixture();changed=deepcopy(before['state'])
    changed['operations'][-1].update(toolpath_generated=False,toolpath_record_counts=[])
    m.verify_route(before['state'],changed,271,'configured')
    changed['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[23])
    with pytest.raises(ValueError):m.verify_route(before['state'],changed,271,'configured')


def test_save_projection_preserves_actual_approach_and_all_headers():
    _,before=fixture();projection=m.save_projection(before)
    assert projection['approach']==before['approach']
    assert projection['state']['operations']==before['state']['operations']
    assert 'saved_file_sha256' not in projection['state']
    assert 'needs_save' not in projection['state']['document']


def terminal_fixture(monkeypatch):
    r,b,loaded,before=run(monkeypatch)
    context={k:{} for k in m.group.CURRENT_KEYS};context.update(deepcopy(loaded))
    context['configured_contour'].update(defaults=deepcopy(before['selected_defaults']),generated=True,record_counts=[22])
    r.update(scope=m.SCOPE,phase_proofs_verified=True,plan=deepcopy(loaded['approach_plan']),
        loaded_context_before=context,setter_interface_audit={'all_resolved':True,'native_calls':0},
        messages={'subscribed':True,'disconnected':True,'active':False},**{k:False for k in m.FORBIDDEN})
    return r


def test_terminal_flat_checkpoint_uses_saved_source_and_real_generated_count(monkeypatch):
    r=terminal_fixture(monkeypatch);cp=m.validate_terminal(r)
    assert cp['source_sha256']=='b'*64
    assert cp['context']['source_sha256']=='b'*64
    assert cp['context']['configured_contour']['record_counts']==[31]
    assert cp['context']['approach_settings']['nc']['GetClrPlaneUseSetupStatus'] is False
    assert 'nc' not in cp['context']['configured_contour']['defaults']
    assert cp['context']['approach_settings']==r['final']['approach']
    assert cp['context']['operation_checkpoint']['final_observation']['tools']==r['final']['catalogue']
    assert cp['context']['authority_kind']=='saved_contour_approach_geometry_review_pending'
    assert cp['context']['current_context_sha256']==m._digest(cp['current'])


@pytest.mark.parametrize('fault',['pending_setter','missing_audit','wrong_saved_source','accepted_geometry','phase_proofs','shared_side_effect'])
def test_terminal_rejects_incomplete_or_unapproved_result(monkeypatch,fault):
    r=terminal_fixture(monkeypatch)
    if fault=='pending_setter':r['actions']['field:lead_out:same']['pending']=True
    elif fault=='missing_audit':r['setter_interface_audit']['all_resolved']=False
    elif fault=='wrong_saved_source':r['final']['state']['saved_file_sha256']='d'*64
    elif fault=='accepted_geometry':r['geometry_acceptance_complete']=True
    elif fault=='phase_proofs':r['phase_proofs_verified']=False
    else:r['final']['approach']['leads']['lead_in']['GetFeedRate']=[99.,True]
    with pytest.raises(ValueError):m.validate_terminal(r)


def test_actual_native_schema_regression_has_no_nc_in_selected_defaults():
    v=json.loads((STAGE/'testdata/approach_configured_actual.json').read_text(encoding='utf8'))
    assert 'nc' not in v['before']['selected_defaults']
    assert v['before']['selected_defaults']==v['configured']['selected_defaults']
    m.verify_capture(v['loaded'],v['before'],v['configured'],phase='configured',expected_approach=v['expected'])


def test_actual_native_schema_still_protects_chamfer_depth():
    v=json.loads((STAGE/'testdata/approach_configured_actual.json').read_text(encoding='utf8'))
    v['configured']['selected_defaults']['finish']['GetChamferLength']=.3
    with pytest.raises(ValueError):
        m.verify_capture(v['loaded'],v['before'],v['configured'],phase='configured',expected_approach=v['expected'])


def continuation_fixture(monkeypatch,drift=False):
    loaded,before=fixture();j=Journal();b=Backend(loaded,before,j)
    configured=deepcopy(before)
    configured['approach']=deepcopy(loaded['approach_plan']['expected'])
    b.value=deepcopy(configured)
    if drift:b.value['approach']['local_planes']['GetRpdPlnPrms'][0]=49.
    b.capture_reconcile=lambda label: b.capture_narrow(label)
    # Archived narrow configured projection has no repeated catalogue/geometry.
    narrow=deepcopy(configured);narrow.pop('catalogue');narrow.pop('selected_feature')
    j.report.update(before=deepcopy(before),inherited_configured=narrow,
        loaded_context_before=deepcopy(loaded),plan=deepcopy(loaded['approach_plan']),continuation={'unit_test':True})
    def forbidden(*args,**kwargs):raise AssertionError('SETTER REPLAY IS FORBIDDEN')
    b.write_change=forbidden;b.read_change=forbidden
    return m.run_continuation(b,j,loaded),b


def test_continuation_reuses_baseline_without_any_setter_calls(monkeypatch):
    r,b=continuation_fixture(monkeypatch)
    assert r['status']=='review_required' and r['readback_verified']
    assert b.calls.count('gtp')==b.calls.count('save')==1
    assert [v for v in b.calls if v.startswith('full:')]==['full:saved']
    assert r['reused_full_capture_count']==r['actual_full_capture_count']==1
    assert r['full_capture_count']==2
    assert set(r['actions'])=={'GenerateToolpath','SaveActiveDocument'}


def test_continuation_drift_prevents_generation_and_save(monkeypatch):
    r,b=continuation_fixture(monkeypatch,drift=True)
    assert r['status']=='error' and not r['readback_verified']
    assert 'gtp' not in b.calls and 'save' not in b.calls


def test_continuation_terminal_separates_inherited_and_new_actions(monkeypatch):
    r=terminal_fixture(monkeypatch)
    inherited={k:v for k,v in r['actions'].items() if k.startswith('field:')}
    failed=dict(actions=deepcopy(inherited),before=deepcopy(r['before']),
        configured=deepcopy(r['configured']),loaded_context_before=deepcopy(r['loaded_context_before']))
    r.update(continuation={'test':True},inherited_actions=inherited,
        actions={k:v for k,v in r['actions'].items() if not k.startswith('field:')},
        inherited_configured=deepcopy(r['configured']),reconciled=deepcopy(r['configured']),
        reused_full_capture_count=1,actual_full_capture_count=1)
    monkeypatch.setattr(m,'read_continuation_evidence',lambda c:failed)
    cp=m.validate_terminal(r)
    assert cp['context']['configured_contour']['record_counts']==[31]
    assert len(r['inherited_actions'])==9 and len(r['actions'])==2
    first=next(iter(inherited));r['actions'][first]=deepcopy(inherited[first])
    with pytest.raises(ValueError):m.validate_terminal(r)