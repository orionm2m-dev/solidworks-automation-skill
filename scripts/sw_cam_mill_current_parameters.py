"""Read two saved selected MILL definitions through existing bounded getters only."""
from copy import deepcopy
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_append_delta import _inventory
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_guide_group_reader import read_catalogues
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts import sw_cam_pocket_pair_read as pocket
from scripts.sw_cam_guide_group_parameters import read_tool_dimensions
from scripts import sw_cam_guide_group_definitions as definitions

FIELDS=('parameters_authority_receipt_path','parameters_authority_receipt_sha256','parameter_operation_native_ids')

def require(ok,message):
    if not ok:raise ValueError(message)

def validate(v):
    if v['observation']!='operation_parameters':
        require(all(v.get(k) is None for k in FIELDS),'Parameter authority requires explicit operation_parameters observation')
        return
    ids=v.get('parameter_operation_native_ids')
    require(type(ids) is list and len(ids)==2 and all(type(i) is int and 0<i<2**32 for i in ids) and len(set(ids))==2,'Exactly two strict ordered parameter operation IDs required')
    require(all(i in v['expected_operation_native_ids'] for i in ids),'Parameter targets must be in the pinned route')
    require(all(type(v.get(k)) is str and v[k] for k in FIELDS[:2]),'Pinned actual saved authority required')

def preflight(tlb,definition_mode):
    """Metadata admission only; detect an unmapped reused interface before bootstrap."""
    from scripts.sw_cam_comtypes import _interface_class
    names=('ICWRghMillOp','ICWMillOperation','ICWMillOperation3','ICWToolpathParam','ICWPosition','ICWUnitVector','ICWNCParam','ICWFinishMillOp','ICWFinishMillOp2','ICWFinishMillOp3','ICWMillTool','ICWMillToolHolder')
    if definition_mode=='selected_continue':names+=('ICWNCParam2',)
    for name in names:_interface_class(name,tlb)
    return dict(registered_interfaces=list(names),native_calls=0)

def load_authority(v):
    d,pin=read_pin(v[FIELDS[0]],v[FIELDS[1]])
    require(d.get('scope')=='MILL_CURRENT_SAVED_APPEND_V1' and d.get('status')=='review_required' and d.get('phase')=='finished' and d.get('action')=='apply','Completed current saved append authority required')
    for key in ('readback_verified','runtime_unchanged','operation_delta_verified','save_readback_verified','model_saved','source_update_verified','save_call_returned'):
        require(d.get(key) is True,'Unverified saved authority: '+key)
    require(d.get('GTP_attempted') is False and d.get('GOP_attempted') is False and d.get('native_dispatch_pending') is False and type(d.get('save_hresult')) is int and d['save_hresult']==0,'Completed selected-definition Save required')
    require(not any(k in d for k in ('issue','failed_phase','runtime_error','receipt_write_error')),'Failed authority rejected')
    clean_events(d)
    require(d.get('saved_file_sha256')==d.get('source_after_sha256')==v['expected_source_sha256'],'Saved source transition differs')
    binding=d['binding'];require(binding.get('definition_mode') in ('selected_insert','selected_continue'),'Completed selected insertion/recovery authority required')
    for key in ('process_id','expected_process_create_time','expected_document_path','expected_feature_native_id','expected_feature_setup_native_id','expected_operation_setup_native_id'):
        require(type(binding.get(key)) is type(v[key]) and binding[key]==v[key],'Saved authority identity differs: '+key)
    state=d.get('saved');require(type(state) is dict and state==d.get('confirm_saved') and state.get('capture_complete') is True and state['document']['needs_save'] is False,'Two equal complete clean saved captures required')
    rows,_=_inventory(state)
    require([x['native_id'] for x in rows]==v['expected_operation_native_ids'],'Saved operation order differs')
    require(sum(x['toolpath_generated'] is True for x in rows)==v['expected_generated_operation_count'] and sum(sum(x['toolpath_record_counts']) for x in rows)==v['expected_total_record_count'],'Saved toolpath counts differ')
    completed=completed_targets(d,v,state)
    require([x['native_id'] for x in completed]==v['parameter_operation_native_ids'],'Targets must be the actual completed rough/finish pair')
    selected_rows=[]
    for kind,oid in enumerate(v['parameter_operation_native_ids']):
        matches=[x for x in rows if x['native_id']==oid];require(len(matches)==1,'Unique parameter operation required');row=matches[0]
        require(row==completed[kind] and row['mill_operation_type']==kind and row['setup_native_id']==v['expected_operation_setup_native_id'] and row['linked_feature_ids']==[v['expected_feature_native_id']] and row['suppressed'] is False and row['toolpath_generated'] is False and row['toolpath_record_counts']==[],'Exact ungenerated own rough/finish pair required')
        selected_rows.append(deepcopy(row))
    require(state['target_header']['native_id']==v['expected_feature_native_id'] and state['number_of_steps_raw']==3 and state['profile']['complete_step_coverage'] is True,'Exact three-step target required')
    require(state['selected_operation_setup']['native_id']==v['expected_operation_setup_native_id'] and state['selected_operation_setup']['feature_setup_native_id']==v['expected_feature_setup_native_id'],'Exact operation setup ownership required')
    return dict(pin=pin,state=deepcopy(state),targets=selected_rows,definition_mode=binding['definition_mode'])

def completed_targets(d,v,state):
    """Pure selector for two successful saved receipt shapes; no partial-authority relaxation."""
    if d['binding']['definition_mode']=='selected_insert':
        require(type(d.get('new_operations')) is list and len(d['new_operations'])==2,'Two completed inserted definitions required')
        return deepcopy(d['new_operations'])
    require(d.get('continuation_recovery_verified') is True,'Completed continuation must retain verified recovery')
    retained=d.get('retained_operations');added=d.get('new_operations');actions=d.get('definition_actions')
    require(type(retained) is list and len(retained)==1 and type(added) is list and len(added)==1 and type(actions) is list and len(actions)==1,'Exactly one retained rough and one new Finish required')
    oid=retained[0]['native_id'];require(type(oid) is int and oid==v['parameter_operation_native_ids'][0] and oid==d.get('continuation_retained_operation_native_id')==d['binding'].get('retained_operation_native_id'),'Exact retained rough identity required')
    a=actions[0];choice=a.get('choice',{})
    require(a.get('kind')=='insert' and type(a.get('anchor_native_id')) is int and a['anchor_native_id']==oid and a.get('actual_native_id')==added[0]['native_id'] and choice.get('operation_type')==1 and choice.get('feature_native_id')==v['expected_feature_native_id'] and choice.get('operation_setup_native_id')==v['expected_operation_setup_native_id'],'Exact Finish-only continuation action required')
    require(all(a.get(k) is True for k in ('attempted','returned','readback_verified')) and a.get('native_dispatch_pending') is False,'Completed Finish action required')
    before_save=d.get('after');require(type(before_save) is dict and before_save==d.get('confirm_after'),'Two verified completed continuation captures required')
    expected=deepcopy(before_save);expected['document']['needs_save']=False
    require(expected==state,'Saved continuation differs beyond dirty flag')
    nc=state.get('retained_operation_nc',{})
    require(nc.get('operation_native_id')==oid and nc.get('read_complete') is True and nc.get('nc',{}).get('read_complete') is True,'Saved retained own NC evidence required')
    return deepcopy(retained+added)


def capture(state,native,v,authority,*,document,read,typed,boundary):
    """Fresh exact authority comparison, then own-operation scalar reads; no writer path."""
    state['document']=deepcopy(document)
    strategy_state=deepcopy(state)
    for row in strategy_state['features']:
        if row['geometry']['native_id']==v['expected_feature_native_id']:row['geometry']=deepcopy(state['target_header'])
    details={};state['strategy_diagnostics']=details
    read_compound_strategy(strategy_state,native,read,typed,details,feature_id=v['expected_feature_native_id'],owner_id=v['expected_feature_setup_native_id'],step_count=3,expected_header=state['target_header'],boundary=boundary,observation='strategy')
    state['default_operation_catalogues']=read_catalogues(native['selected_feature'],read=read,typed=typed)
    if authority['definition_mode']=='selected_continue':
        oid=authority['targets'][0]['native_id'];raw=native['operations'][oid]
        retained=dict(operation_native_id=oid,read_complete=False);state['retained_operation_nc']=retained
        retained['nc']=definitions.read_own_nc(raw,read=read,typed=typed);retained['read_complete']=True
    require(state==authority['state'],'Fresh full captured state differs from saved authority')
    capture_rows(state,native,authority['targets'],feature_id=v['expected_feature_native_id'],read=read,typed=typed,boundary=boundary)

def capture_rows(state,native,targets,*,feature_id,read,typed,boundary,generation_observations=None):
    """Own scalar observations from explicit fresh inventory rows; no authority adapter."""
    observations={} if generation_observations is None else deepcopy(generation_observations)
    require(type(observations) is dict and all(type(k) is int and k>0 and type(v) is list and len(v)==1 and type(v[0]) is int and 0<v[0]<=100000 for k,v in observations.items()),'Exact observed generated-count map required')
    require(set(observations)<={r['native_id'] for r in targets},'Generated observations outside explicit parameter targets')
    for row in targets:
        wanted=observations.get(row['native_id'],[])
        require(row['toolpath_generated'] is bool(wanted) and row['toolpath_record_counts']==wanted,'Explicit parameter generation state differs')
    class Batch:
        def read(self,*a):return read(*a)
        def typed(self,*a):return typed(*a)
        def feature_dispatch(self,raw):
            from comtypes.automation import IDispatch
            return read(raw,'QueryInterface',IDispatch)
    batch=Batch();feature=batch.feature_dispatch(native['selected_feature']);doc=native['doc'];cache={}
    state['operation_parameters']=[];state['parameter_capture_complete']=False
    for row in targets:
        boundary();oid=row['native_id'];raw=native['operations'][oid]
        found=read(doc,'GetCWObjectFromID',3,oid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact operation lookup required')
        for candidate in (raw,found[0]):
            op=typed(candidate,'ICWOperation');mill=typed(candidate,'ICWMillOperation')
            require(_object_id(doc,op,read)==oid and read(mill,'OpernType')==row['mill_operation_type'] and read(op,'Suppressed') is False and read(op,'GetIsToolpathGenerated') is bool(observations.get(oid,[])),'Enumerated/lookup operation identity differs')
            links=[_object_id(doc,x,read) for x in _items(read(op,'IGetAllFeatures'),typed,read,4)]
            require(links==row['linked_feature_ids'],'Own feature links differ')
            generic,tool=read_generic_tool(op,doc,read,typed)
            require(generic==row['assigned_tool'],'Own assigned tool changed')
        out=dict(operation_native_id=oid,operation_type=row['mill_operation_type'],feature_native_id=feature_id,read_complete=False)
        state['operation_parameters'].append(out)
        out['levels']=pocket.read_levels(raw,feature,read=read,typed=typed,feature_dispatch=batch.feature_dispatch)
        if row['mill_operation_type']==0:
            out['rough']=pocket.rough.read_rough_entry_parameters(raw,feature,read=read,typed=typed,diagnostic=out.setdefault('rough_diagnostic',{}))
        else:out['finish']=pocket.read_finish_parameters(raw,feature,read=read,typed=typed)
        generic,tool=read_generic_tool(raw,doc,read,typed);require(generic==row['assigned_tool'],'Own tool changed during parameter reads')
        tid=generic['native_id']
        if tid not in cache:cache[tid]=read_tool_dimensions(tool,generic,batch)
        require(cache[tid]['generic']==generic,'Shared assigned tool differs')
        out['tool']=deepcopy(cache[tid]);out['read_complete']=True;boundary()
    require(len(state['operation_parameters'])==2 and all(r['read_complete'] for r in state['operation_parameters']),'Two complete parameter observations required')
    state['parameter_capture_complete']=True
