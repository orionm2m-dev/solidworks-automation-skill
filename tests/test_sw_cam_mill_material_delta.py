"""Pure material delta tests, with no CAD calls and unchanged raw evidence."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import pytest

D = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mill_material_delta_stage', D/'scripts/sw_cam_mill_material_delta.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def setup(native_id):
    return dict(native_id=native_id, name='Setup', feature_count=0,
        axis_native=[0.,0.,-1.], origin_native=[0.,0.,0.], origin_type_raw=6)


@pytest.fixture
def states():
    before = dict(document=dict(path='C:/part.sldprt', title='part.sldprt', type=1, needs_save=False),
        saved_file_sha256='a'*64, current_machine=dict(machine_type=1, name='Mill'),
        mill_catalogue=[dict(machine_type=1, name='Mill')], material_raw='6061-T6',
        stock=dict(type_raw=1, bounds=[-32.5,-32.5,-32.,32.5,32.5,28.]),
        recognition_options=dict(hole=True, diameter=12.), recognition_method=dict(status='unknown', value=None),
        feature_setups=[setup(10),setup(12)], features=[], operation_counts=[0],
        operation_setups=[dict(index=0,native_id=20,operation_count=0)], operation_count=0,
        operation_inventory_scope='zero_operations_and_empty_setup_ids_verified',
        sw_reference=dict(feature_tree=[dict(name='Core',type='BaseBody')],
            solids=[dict(box_m=[0.,0.,0.,1.,1.,1.], mass_raw=[0.,0.,0.,1.,2.])]),
        visible_solid_body_count=1, all_solid_body_count=1, extra=dict(number=1))
    after = deepcopy(before); after['material_raw']='304L'; after['document']['needs_save']=True
    return before,after


def verify(states):
    return g.verify_mill_material_delta(*states,'6061-T6','304L')


@pytest.mark.parametrize('dirty',[False,True])
def test_only_material_and_boolean_dirty_delta_is_accepted(states,dirty):
    before,after=states;after['document']['needs_save']=dirty;original=deepcopy(states)
    result=verify(states)
    assert result == dict(material_before='6061-T6',material_after='304L',
        material_readback_verified=True,stock_grade_qualified=False,cutting_recipe_qualified=False)
    assert states == original


def test_no_setups_is_valid_empty_scope(states):
    for state in states:
        state.update(feature_setups=[],operation_setups=[],operation_counts=[])
    assert verify(states)['material_readback_verified'] is True


def test_existing_mass_roundoff_passes_without_rewriting_raw_snapshots(states):
    states[1]['sw_reference']['solids'][0]['mass_raw'][3] *= 1+5e-14
    original=deepcopy(states);verify(states)
    assert states == original
    assert states[0]['sw_reference']['solids'] != states[1]['sw_reference']['solids']


@pytest.mark.parametrize('value',[False,True,None,304,'',' ','unknown','unavailable','304L\x00','x'*513])
@pytest.mark.parametrize('position',['old','new'])
def test_exact_known_material_arguments_required(states,value,position):
    old,new='6061-T6','304L'
    if position=='old':old=value
    else:new=value
    with pytest.raises(ValueError):g.verify_mill_material_delta(*states,old,new)


@pytest.mark.parametrize('case',['old_mismatch','new_mismatch','no_op','new_bool','old_unknown'])
def test_material_readback_and_change_required(states,case):
    before,after=states
    if case=='old_mismatch':before['material_raw']='304'
    if case=='new_mismatch':after['material_raw']='304'
    if case=='new_bool':after['material_raw']=True
    if case=='old_unknown':before['material_raw']=None
    if case=='no_op':
        with pytest.raises(ValueError):g.verify_mill_material_delta(before,after,'6061-T6','6061-T6')
    else:
        with pytest.raises(ValueError):verify(states)


@pytest.mark.parametrize('case',['source','path','title','stock','options','option_bool_type','catalogue','machine',
    'method','tree','mass','zero_mass','box','box_numeric_type','body_count','setup_name','setup_order',
    'new_setup','removed_setup','new_op_setup','op_total','op_count','op_row_count','op_bool','new_feature',
    'extra','extra_numeric_type','extra_missing','extra_added','visibility'])
def test_every_unapproved_context_change_stops(states,case):
    before,after=states
    if case=='source':after['saved_file_sha256']='b'*64
    if case=='path':after['document']['path']='C:/other.sldprt'
    if case=='title':after['document']['title']='other.sldprt'
    if case=='stock':after['stock']['bounds'][0]-=1
    if case=='options':after['recognition_options']['diameter']=13.
    if case=='option_bool_type':after['recognition_options']['hole']=1
    if case=='catalogue':after['mill_catalogue'].append(dict(machine_type=1,name='Other'))
    if case=='machine':after['current_machine']['name']='Other'
    if case=='method':after['recognition_method']['value']='AFR'
    if case=='tree':after['sw_reference']['feature_tree'].append(dict(name='Cut',type='Cut'))
    if case=='mass':after['sw_reference']['solids'][0]['mass_raw'][3]+=1e-6
    if case=='zero_mass':after['sw_reference']['solids'][0]['mass_raw'][0]=1e-15
    if case=='box':after['sw_reference']['solids'][0]['box_m'][0]=1e-15
    if case=='box_numeric_type':after['sw_reference']['solids'][0]['box_m'][0]=0
    if case=='body_count':after['sw_reference']['solids'].append(deepcopy(after['sw_reference']['solids'][0]))
    if case=='setup_name':after['feature_setups'][0]['name']='Changed'
    if case=='setup_order':after['feature_setups'].reverse()
    if case=='new_setup':after['feature_setups'].append(setup(14))
    if case=='removed_setup':after['feature_setups'].pop()
    if case=='new_op_setup':after['operation_setups'].append(dict(index=1,native_id=22,operation_count=0));after['operation_counts'].append(0)
    if case=='op_total':after['operation_count']=1
    if case=='op_count':after['operation_counts'][0]=1
    if case=='op_row_count':after['operation_setups'][0]['operation_count']=1
    if case=='op_bool':after['operation_counts'][0]=False
    if case=='new_feature':
        after['feature_setups'][0]['feature_count']=1
        after['features']=[dict(setup_index=0,feature_index=0,setup_native_id=10,geometry=dict(native_id=30))]
    if case=='extra':after['extra']['number']=2
    if case=='extra_numeric_type':after['extra']['number']=1.
    if case=='extra_missing':after.pop('extra')
    if case=='extra_added':after['undocumented']=True
    if case=='visibility':after['visible_solid_body_count']=0
    with pytest.raises(ValueError):verify(states)


@pytest.mark.parametrize('value',[0,1,None,'false'])
def test_dirty_flag_must_be_strict_boolean(states,value):
    states[1]['document']['needs_save']=value
    with pytest.raises(ValueError):verify(states)


@pytest.mark.parametrize('case',['dirty','nonmill','unknownmaterial','missingcontext','nonfinite','boolmass',
    'hidden','missingvisibility','boolvisibility','malformedsha','duplicateids','nonzeroops'])
def test_invalid_baseline_is_rejected_before_material_write(states,case):
    before,_=states
    if case=='dirty':before['document']['needs_save']=True
    if case=='nonmill':before['current_machine']['machine_type']=3
    if case=='unknownmaterial':before['material_raw']='unknown'
    if case=='missingcontext':before.pop('stock')
    if case=='nonfinite':before['sw_reference']['solids'][0]['mass_raw'][1]=float('nan')
    if case=='boolmass':before['sw_reference']['solids'][0]['mass_raw'][1]=False
    if case=='hidden':before['visible_solid_body_count']=0
    if case=='missingvisibility':before.pop('all_solid_body_count')
    if case=='boolvisibility':before['visible_solid_body_count']=True
    if case=='malformedsha':before['saved_file_sha256']='unknown'
    if case=='duplicateids':before['feature_setups'][1]['native_id']=10
    if case=='nonzeroops':before['operation_count']=1
    with pytest.raises(ValueError):g.validate_empty_mill_material_baseline(before)
