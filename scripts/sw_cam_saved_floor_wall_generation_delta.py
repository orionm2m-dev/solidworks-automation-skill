"""Explicit mixed selected-generation deltas; no native calls or global guard changes."""
from copy import deepcopy
from scripts import sw_cam_current_saved_generation_delta as legacy
from scripts import sw_cam_current_circular_authority as circular
from scripts.sw_cam_current_saved_parameter_fields import equal as exact
require=legacy.require
PAIR_KEY='selected_pair_observations'


def observed_rows(reference,actual,selected_ids,attempted_ids):
    require(type(selected_ids)is list and len(selected_ids)==2 and len(set(selected_ids))==2 and all(type(x)is int and x>0 for x in selected_ids),'Exactly two explicit selected identities required')
    require(type(attempted_ids)is list and attempted_ids==selected_ids[:len(attempted_ids)],'Only ordered selected attempts may generate')
    require(type(reference)is list and type(actual)is list and len(reference)==len(actual),'Complete operation table required')
    require([r['native_id']for r in reference]==[r['native_id']for r in actual]and len({r['native_id']for r in actual})==len(actual),'Exact unique operation order required')
    selected=[next(r for r in reference if r['native_id']==oid)for oid in selected_ids]
    require([r['mill_operation_type']for r in selected]==[0,1]and all(type(r['mill_operation_type'])is int for r in selected),'Explicit Rough then Finish only')
    projected=deepcopy(reference)
    for old,new,out in zip(reference,actual,projected):
        if old['native_id']in attempted_ids:
            require(old['suppressed']is False and old['toolpath_generated']is False and old['toolpath_record_counts']==[],'Only an originally empty selected operation may generate')
            counts=new['toolpath_record_counts'];require(new['toolpath_generated']is True and type(counts)is list and len(counts)==1 and type(counts[0])is int and 0<counts[0]<=legacy.MAX_RECORDS,'Positive bounded actual generated count required')
            out['toolpath_generated']=True;out['toolpath_record_counts']=deepcopy(counts)
        require(exact(out,new),'An unselected row, type, binding, tool or path changed')
    return projected


def select(state,ids,*,generated=False):
    info=legacy.inventory(state)
    require(type(ids)is list and len(ids)==2 and len(set(ids))==2 and all(type(x)is int and x>0 for x in ids),'Exactly two selected IDs required')
    require(set(ids)<=set(info['ids']),'Selected member absent')
    pair=state[PAIR_KEY];targets=pair['targets'];draft=pair['draft']
    require(type(targets)is list and len(targets)==2 and [t['operation_native_id']for t in targets]==ids,'Two exact selected observations required')
    rows=[next(r for r in info['rows']if r['native_id']==oid)for oid in ids]
    for kind,row,target in zip((0,1),rows,targets):
        require(type(row['mill_operation_type'])is int and row['mill_operation_type']==kind and target['modes']['operation_kind']==kind and type(target['modes']['operation_kind'])is int,'Exact selected kind required')
        require(row['suppressed']is False and row['toolpath_generated']is generated and row['linked_feature_ids']==[target['feature_native_id']]and row['assigned_tool']['native_id']==target['tool_native_id'],'Selected state/feature/tool differs')
        require(target['modes']['capture_complete']is True,'Complete selected parameter observation required')
    require(type(draft['operation_native_id'])is int and draft['operation_native_id']not in ids and draft['operation_native_id']in info['ids'],'Exact unselected draft required')
    return deepcopy(rows)


def same(a,b):return circular.circular_state_equal(a,b)


def verify_generation(before,after,ids,completed):
    select(before,ids);legacy.inventory(after)
    expected=deepcopy(before);expected['operations']=observed_rows(before['operations'],after['operations'],ids,completed)
    for key in('document','sketch_state'):
        require(type(after[key]['needs_save'])is bool,'Strict dirty state required');expected[key]['needs_save']=after[key]['needs_save']
    require(same(expected,after),'Generation changed protected parameters, draft, geometry, source or path')
    return dict(selected_generated_counts={str(x):next(r['toolpath_record_counts']for r in after['operations']if r['native_id']==x)for x in completed},protected_operation_count=len(before['operations'])-2,protected_generated_operation_count=len(legacy.inventory(before)['generated']),complete_captured_delta_verified=True,physical_toolpath_qualified=False)


class Proof:
    equal=staticmethod(same);select=staticmethod(select)
    def __init__(self,backend,reference):self.backend=backend;self.reference=deepcopy(reference)
    def verify_generation(self,before,after,ids,completed):return verify_generation(before,after,ids,completed)
    def verify_saved(self,before,after):
        require(after['document']['needs_save']is False and after['sketch_state']['needs_save']is False,'Clean saved state required')
        require(after['sketch_state']['saved_file_sha256']==self.backend.source,'Actual adopted saved source required')
        expected=deepcopy(before);expected['document']['needs_save']=False;expected['sketch_state']['needs_save']=False;expected['sketch_state']['saved_file_sha256']=self.backend.source
        require(same(expected,after),'Save changed protected state');return dict(saved_capture_preserved=True,clean_document=True,reopen_persistence_verified=False)
    def save_comparison_state(self,state):
        out=circular.align_circular_mass(self.reference,state)
        require(type(out['document']['needs_save'])is bool and type(out['sketch_state']['needs_save'])is bool,'Strict dirty flags required')
        out['document']['needs_save']=False;out['sketch_state']['needs_save']=False;out['sketch_state']['saved_file_sha256']='verified-source-transition';return out
    def cl_rows(self,before,after,ids,*,completed_ids=None):
        legacy.inventory(before);actual=legacy.inventory(after)
        if completed_ids:
            require(after['sketch_state']['saved_file_sha256']==self.backend.source,'Current saved source differs')
            normalized=deepcopy(after);normalized['sketch_state']['saved_file_sha256']=before['sketch_state']['saved_file_sha256'];verify_generation(before,normalized,ids,completed_ids)
        else:require(same(before,after),'PreCL configuration differs')
        require(actual['generated'],'Existing generated paths required');return deepcopy(actual['generated'])
