"""One ordinary circular Finish definition: strict saved-prefix delta, no native calls."""
from copy import deepcopy
import math
from scripts import sw_cam_current_circular_delta as circle
from scripts import sw_cam_saved_floor_wall_generation_delta as mixed
require=circle.require;exact=mixed.exact
EXTRA='new_finish_circle'

def geometry_spec(v):
    spec=circle.geometry_spec(v)
    require(spec['profile']['radius_mm']==9.0 and spec['profile']['center_model_mm']==[0.0,0.0,-12.6] and v['depth_native']==7.1 and v['expected_setup_axis']==[0.0,0.0,1.0],'Only explicit nominal lower R9 / depth7.1 / +Z wall envelope supported')
    require(type(v['depth_native'])is float and type(spec['profile']['radius_mm'])is float,'Strict nominal DOUBLE geometry required')
    return spec

def validate_baseline(state):
    rows=state['operations'];require(type(rows)is list and len(rows)==29 and len({r['native_id']for r in rows})==29,'Exact complete unique 29-operation baseline required')
    positive=[]
    for r in rows:
        require(type(r['toolpath_generated'])is bool and type(r['toolpath_record_counts'])is list,'Strict native path observation required')
        counts=r['toolpath_record_counts'];require(all(type(x)is int and x>=0 for x in counts),'Strict nonnegative native counts required')
        if r['toolpath_generated']:
            require(len(counts)==1 and counts[0]>0,'One positive generated path required');positive.append(r)
        else:require(counts==[]or(r['native_id']==368 and counts==[0]),'Only retained empty368 zero object admitted')
    require(len(positive)==20 and sum(sum(r['toolpath_record_counts'])for r in positive)==83961,'Exact preserved 20 positive paths /83961 records required')
    require(next(r for r in rows if r['native_id']==366)['toolpath_record_counts']==[398],'Saved floor398 required')
    require(rows[-1]['native_id']==368 and rows[-1]['mill_operation_type']==1 and rows[-1]['linked_feature_ids']==[70]and rows[-1]['toolpath_generated']is False,'Exact retained empty wall tail required')
    require(state['parameter_batch']['candidate_tool']['generic']['native_id']==249,'Existing shared candidate249 required')
    require(state['document']['needs_save']is False and state['sketch_state']['needs_save']is False,'Saved clean baseline required')
    require(all(state.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'Complete baseline required')
    return dict(operation_count=29,positive_paths=20,records=83961)

def protected_cam(state):
    out=deepcopy(state);out.pop(EXTRA,None);out.pop('sketch_state',None);require(type(out['document']['needs_save'])is bool,'Strict dirty flag required');out['document']['needs_save']=False
    return out

def geometry_view(state):
    out=deepcopy(state);extra=out.pop(EXTRA)
    for k in('target_header','target_geometry','target_catalogues','measured_sketch','measured_circle'):out[k]=deepcopy(extra[k])
    return out

def verify_geometry(state,v,fid):
    x=state[EXTRA];require(x['target_geometry']['island_count']==0,'No islands permitted')
    return circle.verify_geometry(geometry_view(state),v,fid)

def verify_sketch(before,after,names):
    require(exact(protected_cam(before),protected_cam(after)),'Sketch changed protected CAM fields')
    circle.verify_sw(before,after,names)
    x=after[EXTRA];require('measured_circle'in x and 'measured_sketch'in x,'New circle readback required')

def verify_feature(before,after,v,fid):
    expected=protected_cam(before);actual=protected_cam(after)
    require(type(fid)is int and fid>0 and fid not in{r['geometry']['native_id']for r in expected['features']},'Actual new feature ID required')
    added=[r for r in actual['features']if r['geometry']['native_id']==fid];require(len(added)==1 and added[0]['setup_native_id']==v['owner_setup_native_id'],'One feature in explicit owner required')
    actual['features']=[r for r in actual['features']if r['geometry']['native_id']!=fid]
    owner=[r for r in actual['feature_setups']if r['native_id']==v['owner_setup_native_id']];require(len(owner)==1 and owner[0]['feature_ids'].count(fid)==1,'One owner membership required');owner[0]['feature_ids'].remove(fid)
    require(exact(expected,actual),'Feature creation changed protected route/geometry/parameters')
    circle.verify_sw(before,after);require(exact(before[EXTRA]['measured_sketch'],after[EXTRA]['measured_sketch']),'New sketch changed');return verify_geometry(after,v,fid)

def verify_catalogue(state,v):
    chosen=v['finish_definition'];rows=[r for r in state[EXTRA]['target_catalogues']if r['operation_type']==1]
    require(len(rows)==1 and sum(e['name']==chosen['default_operation_name']and type(e['default_operation_id'])is int and e['default_operation_id']==chosen['default_operation_id']for e in rows[0]['entries'])==1,'Exact Finish choice must exist in actual new feature catalogue')

def verify_insert(before,after,v,oid,fid):
    expected=protected_cam(before);actual=protected_cam(after);rows=actual['operations'];require(type(oid)is int and oid>0 and len(rows)==len(expected['operations'])+1 and rows[-1]['native_id']==oid and oid not in{r['native_id']for r in expected['operations']},'Exactly one appended actual operation required');row=rows.pop()
    require(type(row['mill_operation_type'])is int and row['mill_operation_type']==1 and row['suppressed']is False and row['toolpath_generated']is False and exact(row['toolpath_record_counts'],[])and row['linked_feature_ids']==[fid]and row['setup_native_id']==v['operation_setup_native_id'],'Exact empty Finish on new circle required')
    tool=row['assigned_tool'];require(tool['is_mill_tool']is True and all(exact(tool.get(k),value)for k,value in v['expected_default_tool'].items()),'Actual default tool differs from explicit expected profile')
    si=row['setup_index'];require(type(si)is int and 0<=si<len(expected['operation_setups'])and expected['operation_setups'][si]['native_id']==v['operation_setup_native_id']and row['operation_index']==expected['operation_setups'][si]['operation_count'],'Exact setup tail position required')
    actual['operation_setups'][si]['operation_count']-=1;actual['operation_counts'][si]-=1;actual['operation_count']-=1;actual['selected_operation_setup']['operation_count']-=1
    for root in('reference_parameter_observation',None):
        oldpb=(expected[root]if root else expected)['parameter_batch'];newpb=(actual[root]if root else actual)['parameter_batch']
        oldcrib=oldpb['toolcrib_catalogue'];oldids={t['native_id']for t in oldcrib};newcrib=newpb['toolcrib_catalogue']
        if tool['native_id']not in oldids:
            added=[t for t in newcrib if t['native_id']not in oldids];require(len(added)==1 and exact(added[0],tool),'At most exact default-tool crib entry may be added');newpb['toolcrib_catalogue']=[t for t in newcrib if t['native_id']in oldids]
        if oid in newpb['candidate_consumer_ids']:
            require(tool['native_id']==v['candidate_tool_native_id']and newpb['candidate_consumer_ids'][-1]==oid,'Only newly appended own candidate consumer permitted')
            newpb['candidate_consumer_ids'].remove(oid);entry=newpb['candidate_consumers'].pop(str(oid));obs=after[EXTRA]['operation_observation']['modes']['nc']
            require(entry['assigned_tool_native_id']==v['candidate_tool_native_id']and exact(entry['feeds_compensation'],{k:obs[k]for k in('GetSpndlSpeed','XYFeed','GetCNCComp','GetTlpComp')}),'New candidate consumer NC differs from actual own readback')
    require(exact(expected,actual),'Insertion changed protected29/20paths, shared tool, NC, draft, geometry or parameters')
    for key in('target_header','target_geometry','target_catalogues','measured_sketch','measured_circle'):require(exact(before[EXTRA][key],after[EXTRA][key]),'New circle changed during insertion')
    obs=after[EXTRA]['operation_observation'];require(obs['operation_native_id']==oid and obs['feature_native_id']==fid and obs['tool_native_id']==tool['native_id']and obs['modes']['operation_kind']==1 and obs['modes']['capture_complete']is True and obs['defaults']['complete']is True,'Actual own Finish defaults/modes/NC required')
    circle.verify_sw(before,after);verify_geometry(after,v,fid);return deepcopy(row)

def verify_saved(before,after,sha):
    circle.verify_saved(before,after,sha)
    require(exact(before[EXTRA],after[EXTRA]),'Save changed new circle/Finish observation')
