"""当前保存圆形口袋的显式几何与增量验证；不执行 COM。"""
from copy import deepcopy
import math
from scripts.sw_cam_profile_sketch import _input,_same_bodies
from scripts.sw_cam_current_saved_parameter_fields import equal
from scripts.sw_cam_mill_circle_geometry import prove_mill_circle_geometry

EXTRAS=('target_header','target_geometry','target_catalogues','operation_parameters','parameter_capture_complete','parameter_batch')

class CircularGuardError(ValueError):
    code='CURRENT_CIRCULAR_GUARD_REJECTED'
    def __init__(self,message):super().__init__(message);self.guard_reason=message

def require(v,message):
    if not v:raise CircularGuardError(message)

def align_circular_mass(reference,observed):
    """只对已验证的 SW 质量数组生成比较副本；原始观察保持不变。"""
    require(type(reference) is dict and type(observed) is dict,'Circular state mappings required')
    a=reference.get('sketch_state');b=observed.get('sketch_state')
    require(type(a) is dict and type(b) is dict,'Circular sketch state required')
    left=a.get('solids');right=b.get('solids')
    require(type(left) is list and type(right) is list and 1<=len(left)<=64 and len(left)==len(right),'Exact bounded SW body count required')
    for x,y in zip(left,right):
        require(type(x) is dict and type(y) is dict,'SW body records required')
        for row in (x,y):
            box=row.get('box_m');mass=row.get('mass_raw')
            require(type(box) is list and len(box)==6 and all(type(v) is float and math.isfinite(v) for v in box),'Six finite raw SW bound scalars required')
            require(type(mass) is list and len(mass)>=4 and all(type(v) is float and math.isfinite(v) for v in mass),'Finite raw SW mass scalars required')
        require(len(x['mass_raw'])==len(y['mass_raw']) and equal(x['box_m'],y['box_m']),'Exact mass arity and SW bounds required')
    require(_same_bodies(left,right),'SW mass exceeds existing relative tolerance')
    out=deepcopy(observed)
    for x,y in zip(left,out['sketch_state']['solids']):y['mass_raw']=deepcopy(x['mass_raw'])
    return out


def circular_state_equal(reference,observed):
    """圆形路径仅允许 mass_raw 数值噪声；其他数据沿用严格比较。"""
    if not (type(reference) is dict and 'sketch_state' in reference) and not (type(observed) is dict and 'sketch_state' in observed):return equal(reference,observed)
    try:return equal(reference,align_circular_mass(reference,observed))
    except CircularGuardError:return False


def close(a,b):return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<=1e-7

def vector(a,b):return type(a) is list and type(b) is list and len(a)==len(b)==3 and all(close(x,y) for x,y in zip(a,b))

def geometry_spec(v):
    spec=_input(v['sketch_spec']);require(spec['plane_axis']=='Z' and spec['profile']['kind']=='circle','One XY circular sketch required')
    axis=v['expected_setup_axis'];require(type(axis) is list and len(axis)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in axis) and axis in ([0,0,1],[0,0,-1]),'Explicit signed Z setup direction required')
    require(type(v['depth_native']) is float and math.isfinite(v['depth_native']) and 0<v['depth_native']<=1000,'Finite bounded depth required')
    require(v['reverse_direction'] is False,'Only explicit top-sketch, setup-direction depth supported')
    return spec

def verify_geometry(state,v,new_id):
    h=state['target_header'];g=state['target_geometry'];spec=geometry_spec(v);p=spec['profile'];depth=v['depth_native'];axis=v['expected_setup_axis'];diam=2*p['radius_mm']
    require(h['native_id']==g['native_id']==new_id and h['volume_type']==g['volume_type']==2 and h['suppressed'] is False and g['suppressed'] is False,'Exact active closed pocket required')
    for row in (h,g):
        require(vector(row['axis_native'],axis) and vector(row['start_native'],p['center_model_mm']) and vector(row['bounds_native'],[diam,diam,depth]) and close(row['depth_native'],depth),'Pocket axis/start/radius/depth readback differs')
    require(h['subtype_raw']==0,'Simple closed pocket required')
    measured=state['measured_circle'];proof=prove_mill_circle_geometry(measured,g['top_curves_native'],g['bottom_curves_native'],depth,axis)
    require(proof['contour_verified'] is True and close(proof['native_units_per_mm'],1.) and proof['relation'] in ('coplanar','depth_separated'),'Measured circular contour and native radial scale required')
    require(vector(proof['top_circle_native']['center'],p['center_model_mm']),'Native top circle differs from explicit model-space center')
    if proof['relation']=='depth_separated':
        end=[p['center_model_mm'][i]+axis[i]*depth for i in range(3)]
        require(close(proof['signed_separation_along_feature_axis_native'],depth) and vector(proof['bottom_circle_native']['center'],end),'Bottom contour is on wrong side of the requested pocket')
    proof['nominal_end_from_header_and_owner_direction']=[p['center_model_mm'][i]+axis[i]*depth for i in range(3)]
    proof['nominal_end_is_measured_bottom']=proof['relation']=='depth_separated'
    return proof

def cam_view(state):
    out=deepcopy(state)
    for k in ('sketch_state','measured_sketch','measured_circle',*EXTRAS):out.pop(k,None)
    out['document']['needs_save']=False
    return out

def verify_sw(before,after,created=()):
    a=deepcopy(before['sketch_state']);b=deepcopy(after['sketch_state'])
    b=align_circular_mass({'sketch_state':a},{'sketch_state':b})['sketch_state']
    require(equal(a['solids'],b['solids']),'Existing solids changed')
    a.pop('solids');b.pop('solids')
    require([x for x in b['features'] if x['name'] not in created]==a['features'],'Existing SW tree changed')
    added=[x for x in b['features'] if x['name'] in created]
    require(len(added)==len(created) and {x['name'] for x in added}==set(created),'Exact created SW feature names required')
    for x in added:require(x['type'] in ('RefPlane','ProfileFeature'),'Unexpected SW feature kind')
    b['features']=a['features']
    require([x for x in b['planes'] if x['name'] not in created]==a['planes'],'Existing reference planes changed');b['planes']=a['planes']
    for x in (a,b):x['needs_save']=False;x['saved_file_sha256']='saved-source-transition'
    require(equal(a,b),'Unrequested SW document metadata changed')

def verify_sketch(before,after,names):
    require(equal(cam_view(before),cam_view(after)),'Sketch creation changed protected CAM state')
    verify_sw(before,after,names)
    require('measured_circle' in after and 'measured_sketch' in after,'Actual created circle readback required')

def verify_feature(before,after,v,new_id):
    expected=cam_view(before);actual=cam_view(after)
    added=[x for x in actual['features'] if x['geometry']['native_id']==new_id]
    require(len(added)==1 and added[0]['setup_native_id']==v['owner_setup_native_id'],'One feature in exact owner required')
    require(new_id not in {x['geometry']['native_id'] for x in expected['features']},'New feature ID already exists')
    actual['features']=[x for x in actual['features'] if x['geometry']['native_id']!=new_id]
    owners=[x for x in actual['feature_setups'] if x['native_id']==v['owner_setup_native_id']]
    require(len(owners)==1 and owners[0]['feature_ids'].count(new_id)==1,'Exact new setup membership required');owners[0]['feature_ids'].remove(new_id)
    require(equal(actual,expected),'Pocket creation changed protected state')
    verify_sw(before,after);verify_geometry(after,v,new_id)
    require(after['measured_sketch']==before['measured_sketch'],'Created sketch changed')

def verify_insert(before,after,v,new_id,new_feature_id):
    expected=cam_view(before);actual=cam_view(after);rows=actual['operations']
    require(rows[-1]['native_id']==new_id and len(rows)==len(expected['operations'])+1,'One appended operation required');row=rows.pop()
    require(row['mill_operation_type']==0 and row['suppressed'] is False and row['toolpath_generated'] is False and row['toolpath_record_counts']==[] and row['linked_feature_ids']==[new_feature_id] and row['setup_native_id']==v['operation_setup_native_id'] and row['assigned_tool']['is_mill_tool'] is True and all(equal(row['assigned_tool'].get(k),value) for k,value in v['expected_default_tool'].items()),'Exact chosen rough/default-tool binding required')
    si=row['setup_index'];require(row['operation_index']==expected['operation_setups'][si]['operation_count'],'Exact insertion order required')
    actual['operation_setups'][si]['operation_count']-=1;actual['operation_counts'][si]-=1;actual['operation_count']-=1;actual['selected_operation_setup']['operation_count']-=1
    # InsertOperation 可重用旧刀具或新增一个真实 crib 条目；旧条目不得改变。
    oldcrib=expected['reference_parameter_observation']['parameter_batch']['toolcrib_catalogue'];nowcrib=actual['reference_parameter_observation']['parameter_batch']['toolcrib_catalogue']
    tool_id=row['assigned_tool']['native_id'];oldids={x['native_id'] for x in oldcrib}
    if tool_id not in oldids:
        extra=[x for x in nowcrib if x['native_id'] not in oldids]
        require(len(extra)==1 and equal(extra[0],row['assigned_tool']),'At most the exact newly observed own-tool crib entry may be added')
        actual['reference_parameter_observation']['parameter_batch']['toolcrib_catalogue']=[x for x in nowcrib if x['native_id'] in oldids]
    require(equal(actual,expected),'Insertion changed protected operations, parameters, tools or geometry')
    for key in ('target_header','target_geometry','measured_sketch','target_catalogues'):require(after[key]==before[key],'Pocket geometry/catalogue changed during insertion')
    verify_sw(before,after);verify_geometry(after,v,new_feature_id)
    require(after['parameter_capture_complete'] is True and after['parameter_batch']['read_complete'] is True and len(after['operation_parameters'])==1 and after['operation_parameters'][0]['operation_native_id']==new_id and after['operation_parameters'][0]['feature_native_id']==new_feature_id and after['operation_parameters'][0]['read_complete'] is True,'Actual new rough parameters required')
    return row

def verify_saved(before,after,new_source):
    expected=deepcopy(before);expected['document']['needs_save']=False;expected['sketch_state']['needs_save']=False;expected['sketch_state']['saved_file_sha256']=new_source
    require(circular_state_equal(expected,after),'Save changed captured state or left dirty state')
