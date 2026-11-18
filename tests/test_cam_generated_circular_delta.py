"""Generated-operation delta checks with independent observed-state fixtures."""
from copy import deepcopy
import pytest
from scripts import sw_cam_circular_reconfigure as m
from test_current_saved_parameter_fields import fixture as parameter_fixture, actual_change


def state_recipe():
    b, _, _ = parameter_fixture()
    row = deepcopy(b['operation_parameters'][0])
    row.update(operation_native_id=361, feature_native_id=359)
    row['tool']['generic']['native_id'] = 249
    for key, value in [('entry_type',4), ('spiral_radius',3.), ('spiral_pitch',.1),
                       ('first_depth',[False,.3]), ('subsequent_depth',[False,.3])]:
        actual_change(row,key,value)
    b['operation_parameters'] = [row]
    b['operations'] = []
    for i in range(26):
        oid = 361 if i==25 else 100+i
        generated = i<18 or i==25
        b['operations'].append(dict(native_id=oid,mill_operation_type=0,
            linked_feature_ids=[359 if i==25 else 1000+i],suppressed=False,
            toolpath_generated=generated,toolpath_record_counts=[11158 if i==25 else 10+i] if generated else [],
            assigned_tool=deepcopy(row['tool']['generic']),setup_native_id=94))
    b.update(capture_complete=True,extended_capture_complete=True,operation_count=26,operation_counts=[26],
             sketch_state=dict(pid=123,needs_save=False,saved_file_sha256='a'*64,
                               solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])]))
    nc=dict(GetSpndlSpeed=200.,XYFeed=1000.,GetSpeedFeedMethod=0,LinkToTool=True,
            GetIsLockSpindleSpeed=False,GetZFeedrate2=[2.,False],GetLeadinFeedratePercent=30.,
            GetCNCComp=0,GetTlpComp=1,
            leadin_feed=dict(value_native=2.,is_percent=False,physical_units_verified=False))
    b['cutting_context']=dict(nc=nc,local_planes=dict(clearance=5.,rapid=2.))
    b['parameter_batch']['target_nc']={}
    b['parameter_batch']['candidate_consumers']={}
    for family in ('target_nc','candidate_consumers'):
        for oid in (100,361):
            b['parameter_batch'][family][str(oid)] = dict(operation_native_id=oid,read_complete=True,
                feeds_compensation=dict(GetSpndlSpeed=200.,XYFeed=1000.,GetCNCComp=0,GetTlpComp=1))
    r=dict(operation_native_id=361,feature_native_id=359,expected_tool_native_id=249,qualification_only=True,
        rough=[dict(field='first_depth',expected=[False,.3],new=[False,7.4]),
               dict(field='subsequent_depth',expected=[False,.3],new=[False,7.4]),
               dict(field='spiral_pitch',expected=.1,new=.6)],
        nc=[dict(field='LinkToTool',expected=True,new=False),
            dict(field='GetSpndlSpeed',expected=200.,new=2000.),
            dict(field='XYFeed',expected=1000.,new=150.),
            dict(field='leadin_feed',expected=deepcopy(nc['leadin_feed']),
                 new=dict(value_native=75.,is_percent=False,physical_units_verified=False))])
    return b,r


def independently_configured(b,r):
    a=deepcopy(b)
    for change in r['rough']: actual_change(a['operation_parameters'][0],change['field'],change['new'])
    for change in r['nc']: a['cutting_context']['nc'][change['field']]=deepcopy(change['new'])
    for family in ('target_nc','candidate_consumers'):
        a['parameter_batch'][family]['361']['feeds_compensation'].update(GetSpndlSpeed=2000.,XYFeed=150.)
    a['document']['needs_save']=True
    a['sketch_state']['needs_save']=True
    return a


def test_independent_configured_state_preserves_all_25_others_and_shared_tool():
    b,r=state_recipe();original=deepcopy(b);assert m.validate_recipe(r,b)==r
    a=independently_configured(b,r)
    proof=m.verify_configuration(b,a,r)
    assert proof['protected_operation_count']==25 and proof['shared_tool_unchanged']
    assert proof['selected_cached_path_is_stale'] and b==original
    assert a['operations'][:-1]==b['operations'][:-1]
    assert a['operation_parameters'][0]['tool']==b['operation_parameters'][0]['tool']


@pytest.mark.parametrize('cached',[True,False])
def test_only_selected_cached_path_can_be_cleared_or_retained(cached):
    b,r=state_recipe();a=independently_configured(b,r)
    a['operations'][-1].update(toolpath_generated=cached,toolpath_record_counts=[11158] if cached else [])
    assert m.verify_configuration(b,a,r)['parameter_delta_verified']


def corrupt(state, defect):
    if defect=='other_count': state['operations'][0]['toolpath_record_counts']=[999]
    elif defect=='other_generated': state['operations'][0].update(toolpath_generated=False,toolpath_record_counts=[])
    elif defect=='other_suppression': state['operations'][18]['suppressed']=True
    elif defect=='order': state['operations'][0],state['operations'][1]=state['operations'][1],state['operations'][0]
    elif defect=='tool_identity': state['operations'][-1]['assigned_tool']['native_id']=250
    elif defect=='tool_dimensions': state['operation_parameters'][0]['tool']['mill']['length']+=.01
    elif defect=='holder': state['operation_parameters'][0]['tool']['holder']['length']+=1.
    elif defect=='protected_feed': state['parameter_batch']['target_nc']['100']['feeds_compensation']['XYFeed']=150.
    elif defect=='one_echo': state['parameter_batch']['candidate_consumers']['361']['feeds_compensation']['XYFeed']=151.
    elif defect=='source': state['sketch_state']['saved_file_sha256']='b'*64
    elif defect=='profile': state['profile']['depth']+=.01
    elif defect=='radius': actual_change(state['operation_parameters'][0],'spiral_radius',3.1)
    elif defect=='stock': actual_change(state['operation_parameters'][0],'side_allowance',.1)
    elif defect=='Z_feed': state['cutting_context']['nc']['GetZFeedrate2']=[75.,False]
    elif defect=='inactive_percent': state['cutting_context']['nc']['GetLeadinFeedratePercent']=75.
    elif defect=='method': state['cutting_context']['nc']['GetSpeedFeedMethod']=1
    elif defect=='planes': state['cutting_context']['local_planes']['rapid']=1.
    elif defect=='feed_type': state['cutting_context']['nc']['XYFeed']=150
    elif defect=='dirty_type': state['document']['needs_save']=1
    elif defect=='sketch_dirty_type': state['sketch_state']['needs_save']=1
    else: raise AssertionError(defect)


DEFECTS=['other_count','other_generated','other_suppression','order','tool_identity','tool_dimensions',
         'holder','protected_feed','one_echo','source','profile','radius','stock','Z_feed',
         'inactive_percent','method','planes','feed_type','dirty_type','sketch_dirty_type']


@pytest.mark.parametrize('defect',DEFECTS)
def test_unrequested_configuration_delta_rejected(defect):
    b,r=state_recipe();a=independently_configured(b,r);corrupt(a,defect)
    with pytest.raises(ValueError): m.verify_configuration(b,a,r)


def test_generation_only_replaces_selected_count_and_keeps_configured_values():
    b,r=state_recipe();a=independently_configured(b,r);new=deepcopy(a)
    new['operations'][-1].update(toolpath_generated=True,toolpath_record_counts=[731])
    proof=m.verify_generation(a,new,361)
    assert proof['selected_generated_record_count']==731 and proof['protected_operation_count']==25


@pytest.mark.parametrize('defect',DEFECTS)
def test_generation_rejects_protected_or_configured_delta(defect):
    b,r=state_recipe();a=independently_configured(b,r);new=deepcopy(a)
    new['operations'][-1]['toolpath_record_counts']=[731];corrupt(new,defect)
    with pytest.raises(ValueError): m.verify_generation(a,new,361)


@pytest.mark.parametrize('counts',[[],[False],[0],[-1],[100001],[1,2]])
def test_generated_replacement_requires_positive_bounded_single_count(counts):
    b,r=state_recipe();a=independently_configured(b,r);new=deepcopy(a)
    new['operations'][-1]['toolpath_record_counts']=counts
    with pytest.raises(ValueError):m.verify_generation(a,new,361)


@pytest.mark.parametrize('defect',['percent_depth','unequal_depth','bad_pitch','percent_lead','spindle_nan',
    'bad_expected','link_true','extra_setter','bool_oid','method','locked','wrong_feature','wrong_tool'])
def test_recipe_rejects_mode_identity_scope_and_stale_values(defect):
    b,r=state_recipe()
    if defect=='percent_depth':r['rough'][0]['new']=[True,7.4]
    elif defect=='unequal_depth':r['rough'][1]['new']=[False,7.3]
    elif defect=='bad_pitch':r['rough'][2]['new']=1.1
    elif defect=='percent_lead':r['nc'][3]['new']['is_percent']=True
    elif defect=='spindle_nan':r['nc'][1]['new']=float('nan')
    elif defect=='bad_expected':r['nc'][2]['expected']=500.
    elif defect=='link_true':r['nc'][0]['new']=True
    elif defect=='extra_setter':r['nc'].append(dict(field='GetZFeedrate2',expected=[2.,False],new=[75.,False]))
    elif defect=='bool_oid':r['operation_native_id']=True
    elif defect=='method':b['cutting_context']['nc']['GetSpeedFeedMethod']=1
    elif defect=='locked':b['cutting_context']['nc']['GetIsLockSpindleSpeed']=True
    elif defect=='wrong_feature':r['feature_native_id']=358
    elif defect=='wrong_tool':r['expected_tool_native_id']=248
    with pytest.raises(ValueError):m.validate_recipe(r,b)
