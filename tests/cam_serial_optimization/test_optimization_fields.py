from copy import deepcopy
import pytest
from optimization_fixture import fixture
from scripts import sw_cam_local_optimization_fields as m

def test_exact_alias_projection():
    _,old,targets,plan=fixture();frozen=deepcopy(old);assert m.validate_plan(plan,targets,old)==plan
    new=m.project_parameters(old,plan);assert old==frozen
    assert m.verify_configured(old,new,plan)['selected_parameter_delta_verified']
    assert new['parameters'][8]['rough']['depth']['GetStartDepth']['raw']==[False,3.4]
    assert new['parameters'][9]['finish_fields']['max_depth']==[3.4,False]
    assert new['parameters'][:8]==old['parameters'][:8]
    assert len(m.action_names(targets))==17

@pytest.mark.parametrize('field,value',[('depth_mm',3.4001),('depth_mm',True),('depth_mm',float('nan')),('depth_mm',4.1),('spiral_pitch_mm',4.),('spiral_pitch_mm',.02)])
def test_bad_plan(field,value):
    _,old,targets,plan=fixture();plan['rows'][0][field]=value
    with pytest.raises(ValueError):m.validate_plan(plan,targets,old)

@pytest.mark.parametrize('kind',['NC','protected','alias','point','final','tool'])
def test_other_parameter_changes_fail(kind):
    _,old,targets,plan=fixture();new=m.project_parameters(old,plan)
    if kind=='NC':new['parameters'][8]['nc']['feeds_compensation']['XYFeed']=70.
    elif kind=='protected':new['parameters'][0]['sentinel']=999
    elif kind=='alias':new['parameters'][8]['rough']['depth']['FirstDepthAmt']['raw']=.3
    elif kind=='point':new['parameters'][8]['startpoints']['points'][0]['x']=4.
    elif kind=='final':new['parameters'][9]['finish']['FinalDepthCut']['raw']=.1
    else:new['parameters'][8]['tool']['generic']['native_id']=99
    with pytest.raises(ValueError):m.verify_configured(old,new,plan)

def test_invalidated_selected_paths_allowed_but_not_unknown_new_counts():
    _,old,targets,plan=fixture();new=m.project_parameters(old,plan)
    for op in new['binding']['operations'][-4:]:op.update(toolpath_generated=False,toolpath_record_counts=[])
    assert m.verify_configured(old,new,plan)
    new['binding']['operations'][-1]['toolpath_record_counts']=[999]
    with pytest.raises(ValueError):m.verify_configured(old,new,plan)

def test_existing_paths_explicit_regeneration():
    _,old,targets,plan=fixture();configured=m.project_parameters(old,plan);new=deepcopy(configured);counts={t['operation_native_id']:[70]for t in targets}
    for o in new['binding']['operations'][-4:]:o['toolpath_record_counts']=[70]
    assert m.verify_regenerated(configured,new,targets,counts)['regenerated_selected_operations']==4
    new['parameters'][9]['nc']['feeds_compensation']['XYFeed']=70.
    with pytest.raises(ValueError):m.verify_regenerated(configured,new,targets,counts)
