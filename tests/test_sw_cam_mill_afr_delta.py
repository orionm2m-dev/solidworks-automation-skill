"""Pure before/after AFR validation; no CAM mocks needed and no native calls."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import sys
import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
D = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('afr_delta_stage', D/'scripts/sw_cam_mill_afr_delta.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)


def setup(native_id, count=0):
    return dict(native_id=native_id, name='Setup '+str(native_id), feature_count=count,
        axis_native=[0., 0., -1.], origin_native=[0., 0., 0.], origin_type_raw=6)


def op_setup(native_id, index):
    return dict(index=index, native_id=native_id, operation_count=0)


def feature(native_id, si, fi, setup_id):
    return dict(setup_index=si, feature_index=fi, setup_native_id=setup_id,
        geometry=dict(native_id=native_id, volume_type=2, depth_native=4.1,
            contours={'top': {'status':'observed', 'chains':[]}}, islands={'items':[]}))


@pytest.fixture
def states():
    before = dict(document=dict(path='C:/part.sldprt', title='part.sldprt', type=1, needs_save=False),
        saved_file_sha256='a'*64, current_machine=dict(machine_type=1, name='Mill'),
        mill_catalogue=[dict(machine_type=1, name='Mill')], material_raw='304L',
        stock=dict(type_raw=1, dimensions=[65., 60.]),
        recognition_options=dict(GetEMFFeatTypeOptions=[dict(enum_value=0, enabled=True)], EMFHoleMaxDiameter=12.),
        recognition_method=dict(value=None, status='unknown'),
        feature_setups=[setup(10), setup(12)], features=[], operation_counts=[0,0],
        operation_setups=[op_setup(20,0), op_setup(22,1)], operation_count=0,
        operation_inventory_scope='zero_operations_and_empty_setup_ids_verified',
        sw_reference=dict(feature_tree=[dict(name='Core', type='BaseBody')],
            solids=[dict(box_m=[0.,0.,0.,1.,1.,1.], mass_raw=[0.,0.,0.,1.,2.])]),
        visible_solid_body_count=1, all_solid_body_count=1, untouched_extra=dict(raw=1))
    after = deepcopy(before)
    after['feature_setups'] = [setup(10,1), setup(11,1), setup(12)]
    after['features'] = [feature(100,0,0,10), feature(101,1,0,11)]
    after['operation_setups'] = [op_setup(20,0), op_setup(21,1), op_setup(22,2)]
    after['operation_counts'] = [0,0,0]
    after['document']['needs_save'] = True
    return before,after


def test_only_new_features_and_setups_accepted_with_existing_relative_order(states):
    before,after = states; original = deepcopy(states)
    result = g.verify_afr_delta(before,after,2)
    assert result == dict(new_feature_native_ids=[100,101], new_setup_native_ids=[11],
        new_operation_setup_native_ids=[21], native_return_feature_count=2)
    assert states == original


def test_empty_machine_can_receive_first_feature_and_empty_operation_setup(states):
    before,after = states
    before.update(feature_setups=[],operation_setups=[],operation_counts=[])
    after.update(feature_setups=[setup(11,1)], features=[feature(100,0,0,11)],
        operation_setups=[op_setup(21,0)], operation_counts=[0])
    out=g.verify_afr_delta(before,after,1)
    assert out['new_setup_native_ids']==[11] and out['new_operation_setup_native_ids']==[21]


def test_existing_mass_tolerance_preserves_raw_snapshots(states):
    before,after = states
    after['sw_reference']['solids'][0]['mass_raw'][3] *= 1+5e-14
    original = deepcopy(states)
    g.verify_afr_delta(before,after,2)
    assert states == original
    assert before['sw_reference']['solids'] != after['sw_reference']['solids']


@pytest.mark.parametrize('value',[True,False,0,-1,2.,'2',None,1,3,65])
def test_return_requires_exact_positive_new_feature_count(states,value):
    with pytest.raises(ValueError):g.verify_afr_delta(*states,value)


@pytest.mark.parametrize('case',['material','stock','options','source','machine','catalogue','method',
    'tree','mass','box','body_count','path','title','extra','extra_type','new_unapproved_key','missing_context'])
def test_unapproved_context_or_source_changes_stop(states,case):
    before,after=states
    if case=='material':after['material_raw']='6061-T6'
    if case=='stock':after['stock']['dimensions'][0]=66.
    if case=='options':after['recognition_options']['GetEMFFeatTypeOptions'][0]['enabled']=1
    if case=='source':after['saved_file_sha256']='b'*64
    if case=='machine':after['current_machine']['name']='Other'
    if case=='catalogue':after['mill_catalogue'].append(dict(machine_type=1,name='Other'))
    if case=='method':after['recognition_method']['value']='AFR'
    if case=='tree':after['sw_reference']['feature_tree'].append(dict(name='Cut',type='Cut'))
    if case=='mass':after['sw_reference']['solids'][0]['mass_raw'][3]+=1e-5
    if case=='box':after['sw_reference']['solids'][0]['box_m'][0]+=1e-15
    if case=='body_count':after['sw_reference']['solids'].append(deepcopy(after['sw_reference']['solids'][0]))
    if case=='path':after['document']['path']='C:/other.sldprt'
    if case=='title':after['document']['title']='other.sldprt'
    if case=='extra':after['untouched_extra']['raw']=2
    if case=='extra_type':after['untouched_extra']['raw']=1.
    if case=='new_unapproved_key':after['hidden_delta']=True
    if case=='missing_context':after.pop('stock')
    with pytest.raises(ValueError):g.verify_afr_delta(before,after,2)


@pytest.mark.parametrize('case',['setup_axis','setup_origin','setup_name','setup_removed','setup_reordered',
    'setup_duplicate','setup_missing_geometry','feature_duplicate','feature_membership','feature_index',
    'setup_index_bool','feature_count','extra_feature','cross_kind_id','op_count','op_total','op_row_count',
    'op_removed','op_reordered','op_duplicate','op_index','op_count_list_bool'])
def test_exact_membership_setup_geometry_and_zero_operations(states,case):
    before,after=states
    if case=='setup_axis':after['feature_setups'][0]['axis_native']=[1.,0.,0.]
    if case=='setup_origin':after['feature_setups'][0]['origin_native']=[0.,0.,1.]
    if case=='setup_name':after['feature_setups'][0]['name']='renamed'
    if case=='setup_removed':after['feature_setups'].pop()
    if case=='setup_reordered':after['feature_setups'][0],after['feature_setups'][-1]=after['feature_setups'][-1],after['feature_setups'][0]
    if case=='setup_duplicate':after['feature_setups'][-1]['native_id']=10
    if case=='setup_missing_geometry':after['feature_setups'][1].pop('axis_native')
    if case=='feature_duplicate':after['features'][1]['geometry']['native_id']=100
    if case=='feature_membership':after['features'][0]['setup_native_id']=11
    if case=='feature_index':after['features'][0]['feature_index']=1
    if case=='setup_index_bool':after['features'][0]['setup_index']=False
    if case=='feature_count':after['feature_setups'][0]['feature_count']=2
    if case=='extra_feature':after['features'].append(feature(102,1,1,11))
    if case=='cross_kind_id':after['features'][0]['geometry']['native_id']=20
    if case=='op_count':after['operation_counts'][0]=1
    if case=='op_total':after['operation_count']=1
    if case=='op_row_count':after['operation_setups'][0]['operation_count']=1
    if case=='op_removed':after['operation_setups'].pop();after['operation_counts'].pop()
    if case=='op_reordered':
        after['operation_setups'][0]['native_id']=22;after['operation_setups'][-1]['native_id']=20
    if case=='op_duplicate':after['operation_setups'][1]['native_id']=20
    if case=='op_index':after['operation_setups'][0]['index']=1
    if case=='op_count_list_bool':after['operation_counts'][0]=False
    with pytest.raises(ValueError):g.verify_afr_delta(before,after,2)


@pytest.mark.parametrize('case',['dirty','existing_feature','hidden_body','missing_visibility','bool_visibility',
    'nan_mass','bool_mass','short_mass','non_mill','bool_doc_type','too_many_setups','too_many_features'])
def test_invalid_empty_baseline_cannot_authorize_afr(states,case):
    before,_=states
    if case=='dirty':before['document']['needs_save']=True
    if case=='existing_feature':before['feature_setups'][0]['feature_count']=1;before['features']=[feature(100,0,0,10)]
    if case=='hidden_body':before['visible_solid_body_count']=0
    if case=='missing_visibility':before.pop('visible_solid_body_count')
    if case=='bool_visibility':before['visible_solid_body_count']=True
    if case=='nan_mass':before['sw_reference']['solids'][0]['mass_raw'][0]=float('nan')
    if case=='bool_mass':before['sw_reference']['solids'][0]['mass_raw'][0]=False
    if case=='short_mass':before['sw_reference']['solids'][0]['mass_raw']=[1.,2.,3.]
    if case=='non_mill':before['current_machine']['machine_type']=3
    if case=='bool_doc_type':before['document']['type']=True
    if case=='too_many_setups':before['feature_setups']=[setup(100+i) for i in range(9)]
    if case=='too_many_features':before['feature_setups'][0]['feature_count']=65
    with pytest.raises(ValueError):g.validate_empty_afr_baseline(before)


def test_op_empty_count_inventory_mismatch_stops(states):
    before,after=states;after['operation_counts'].pop()
    with pytest.raises(ValueError):g.verify_afr_delta(before,after,2)


def test_strict_dirty_flag_cannot_be_coerced(states):
    before,after=states;after['document']['needs_save']=1
    with pytest.raises(ValueError):g.verify_afr_delta(before,after,2)
