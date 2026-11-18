"""File-only successful selected GOP evidence for the existing Save lifecycle.

The caller supplies the already-validated recovered/saved definition context.
No application access or source transition is performed by this verifier.
"""
from copy import deepcopy
from scripts import sw_cam_pocket_definition_context as definition
from scripts import sw_cam_autodetected_pocket as creator
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_process_import import require,event_health

def expected_before(context):
    state=deepcopy(context['expected_inventory'])
    state.pop('sw_reference');state.pop('all_solid_body_count')
    state.update(document=deepcopy(context['saved_transition']['document']),
        saved_file_sha256=context['expected_source_sha256'],selected_feature=deepcopy(context['recovered']['header']),
        operation_setup_count=len(state['operation_setups']),operation_counts=[x['operation_count']for x in state['operation_setups']],
        definition_authority=dict(scope=definition.SCOPE,recovery_receipt_sha256=context['evidence']['sha256'],
            save_receipt_sha256=context['save_pin']['sha256'],raw_creator_status=context['creator']['status'],
            saved_definition_binding_verified=True,persistence_verified=False,analytic_sketch_and_body_invariants_verified=True,
            island_geometry_verified=False,physical_depth_verified=False))
    if creator.saved_caps(context.get('request',{})) or context.get('origin_kind')=='creator':
        state['definition_authority']['origin_kind']=context['origin_kind']
    return state

def read_gop_receipt(path,sha,context,expected_operation_native_ids):
    """Verify one completed RETAIN1 GOP and its consumed marker; never retry it."""
    ids=expected_operation_native_ids
    require(type(ids)is list and 1<=len(ids)<=32 and all(type(x)is int and 0<x<2**31 for x in ids)
            and len(ids)==len(set(ids)),'Exact ordered nonempty operation IDs required')
    require(context.get('scope')==definition.SCOPE,'Recovered/saved definition context required')
    r,rp=read_pin(path,sha)
    require(r.get('feature_authority')=='autodetected_pocket_definition' and r.get('action')=='apply'
            and r.get('status')=='review_required' and r.get('phase')=='finished','Successful selected definition GOP required')
    require(type(r.get('gop_preference'))is int and r['gop_preference']==1,'Exact RETAIN1 preference required')
    require(type(r.get('process_id'))is int and r['process_id']==context['process_id'],'Exact owned GOP process required')
    for key in ('readback_verified','insertion_delta_verified','mutation_attempted','native_call_attempted','native_call_returned','apply_eligible','geometry_unqualified'):
        require(r.get(key)is True,'Missing verified GOP fact '+key)
    for key in ('native_dispatch_pending','model_saved','AFR_attempted','GTP_attempted','simulation_attempted','stock_edit_attempted',
                'units_verified','physical_depth_verified','tool_or_material_process_qualified','production_qualified','post_cleanup_CAM_getters','island_geometry_verified','may_continue'):
        require(r.get(key)is False,'Unexpected GOP action/qualification '+key)
    require(r.get('native_return_type')=='int' and type(r.get('native_hresult'))is int and r['native_hresult']==0,'Exact native GOP HRESULT0 required')
    require(not any(k in r for k in ('issue','cleanup_error','runtime_error','receipt_write_error','failed_phase')),'Unresolved GOP issue')
    require(event_health(r['messages'],active=False)==0,'GOP events/cleanup must be clean')
    for prefix,pin in [('definition_recovery_receipt',context['evidence']),('definition_save_receipt',context['save_pin'])]:
        require(creator.same_path(r[prefix+'_path'],pin['path'])and r[prefix+'_sha256']==pin['sha256'],'Exact recovery/save authority required')
    before,after=r['before'],r['after'];require(before==expected_before(context),'GOP did not start from exact recovered/saved definition')
    fid=context['expected_feature_native_id'];ops=definition.verify_delta(before,after,fid)
    require(r['new_operations']==ops and [x['native_id']for x in ops]==ids,'Exact ordered generated definitions required')
    require(r['state_sha256']==_digest(dict(snapshot=before,process_id=context['process_id'],expected_feature_native_id=fid,scope='MILL_SINGLE_FEATURE_GOP_RETAIN1')),'GOP prepared state binding differs')
    require(before['saved_file_sha256']==after['saved_file_sha256']==context['expected_source_sha256']
            and before['document']['needs_save']is False and type(after['document']['needs_save'])is bool,'GOP source/dirty transition differs')
    require(r['after_cleanup_SW_file']==dict(document=after['document'],saved_file_sha256=context['expected_source_sha256']),'Exact post-cleanup GOP identity required')
    diagnostics=r['snapshot_diagnostics'];require(type(diagnostics)is list and len(diagnostics)==3,'Three complete GOP boundary captures required')
    for row,label,state in zip(diagnostics,('initial_capture','before_mutation_capture','after_mutation_capture'),(before,before,after)):
        require(row.get('phase')==label and row.get('capture_complete')is True and row.get('state')==state,'Complete recorded GOP capture differs')
    marker=context['marker'];require(creator.same_path(r['definition_gop_marker_path'],str(marker)),'Exact consumed GOP marker path required')
    mark,mp=read_pin(str(marker),_file_hash(marker))
    require(mark==dict(scope=definition.SCOPE,creator_receipt_sha256=context['evidence']['sha256'],feature_native_id=fid,
                receipt_path=mark.get('receipt_path'),state_sha256=r['state_sha256'],automatic_replay=False)
            and creator.same_path(mark.get('receipt_path'),str(path)),'Exact consumed GOP marker content required')
    return dict(gop=r,gop_pin=rp,marker_pin=mp,operation_ids=list(ids),after=deepcopy(after))
