"""Bind a completed circular Save/CL result to the existing whole-machine WIP core.

Offline authority plus callback adapter only. No application startup, connection,
new simulation engine, schema registration or native dispatch entry point here.
The outer native owner supplies the existing guarded capture/cleanup lifecycle.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,math,re
from scripts import sw_cam_current_saved_generation as generation
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts import sw_cam_current_circular_authority as authority
from scripts.sw_cam_circular_gtp_save import completed_action,clean_events
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
from scripts.sw_cam_turn_tool import _digest

SCOPE='CURRENT_SAVED_CIRCULAR_WHOLE_MACHINE_WIP_BINDING_V1'
require=delta.require


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def same_path(a,b):
    return str(Path(a).resolve()).casefold()==str(Path(b).resolve()).casefold()


def strict_sha(value):
    require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')


def direct(pin):
    p=Path(pin['path']);strict_sha(pin['sha256'])
    require(p.is_absolute() and p.is_file() and not p.is_symlink(),'Direct regular evidence file required')
    raw=p.read_bytes();require(hashlib.sha256(raw).hexdigest()==pin['sha256'],'Pinned evidence changed')
    if 'bytes' in pin:require(len(raw)==pin['bytes'],'Pinned evidence length changed')
    return raw


def complete_state(state,pid,sha):
    require(type(state)is dict and state.get('parameter_capture_complete')is True
        and state.get('parameter_batch',{}).get('read_complete')is True,'Complete circular parameter capture required')
    info=delta.inventory(state)
    sketch=state.get('sketch_state',{})
    require(sketch.get('pid')==pid and type(sketch.get('pid'))is int
        and sketch.get('saved_file_sha256')==sha,'Captured owner/source differs')
    return info


def validate_terminal(r,receipt_pin,*,process_id,process_create_time,source_path,source_sha256,
                      selected_operation_ids,protected_operation_ids,expected_generated_operations,marker_pin,
                      read_pin=direct,parser=parse_generic_cl_bytes):
    """Recheck exact terminal facts; arbitrary `verified:true` is not authority.

    Only the successful existing circular generator terminal is supported.
    Uncertain/reconciled or another producer requires a separate explicit adapter.
    Counts/IDs/paths come from pinned evidence plus explicit expected context.
    """
    strict_sha(source_sha256);strict_sha(receipt_pin['sha256'])
    require(type(process_id)is int and process_id>0 and type(process_create_time)in(int,float)
        and math.isfinite(process_create_time) and process_create_time>0,'Explicit live owner/lifetime required')
    require(type(selected_operation_ids)is list and len(selected_operation_ids)==1
        and type(selected_operation_ids[0])is int and selected_operation_ids[0]>0,'One explicit circular target required')
    oid=selected_operation_ids[0]
    require(type(expected_generated_operations)is list and 1<=len(expected_generated_operations)<=delta.MAX_OPERATIONS
        and all(type(x)is dict and set(x)=={'operation_native_id','toolpath_record_counts'}
            and type(x['operation_native_id'])is int and x['operation_native_id']>0
            and type(x['toolpath_record_counts'])is list and len(x['toolpath_record_counts'])==1
            and type(x['toolpath_record_counts'][0])is int and x['toolpath_record_counts'][0]>0
            for x in expected_generated_operations),'Strict explicit generated mapping required')
    require(r.get('scope')==generation.SCOPE and r.get('status')=='review_required'
        and r.get('phase')=='finished','Successful completed circular generation receipt required')
    require(not any(k in r for k in ('issue','reason','runtime_error','cleanup_error','receipt_write_error','failure_capture_issue')),'Terminal contains an unresolved failure')
    clean_events(r)
    for key in ('model_saved','save_readback_verified','source_update_verified','readback_verified','runtime_unchanged',
                'GTP_attempted','save_attempted','CL_export_attempted','receipt_created','marker_created'):
        require(r.get(key)is True,'Missing successful terminal fact: '+key)
    for key in ('GOP_attempted','AFR_attempted','operation_creation_attempted','tool_assignment_attempted',
                'parameter_setter_attempted','automatic_replay','automatic_rollback','native_dispatch_pending'):
        require(r.get(key)is False,'Unexpected terminal action: '+key)
    req=r.get('request',{});p=req.get('params',{})
    require(req.get('action')=='generate_configured_local_group' and p.get('generation_mode')=='current_saved_circular'
        and r.get('request_sha256')==_digest(req),'Exact circular generation request required')
    require(p.get('process_id')==process_id and type(p.get('process_id'))is int
        and type(p.get('expected_process_create_time'))is type(process_create_time)
        and p.get('expected_process_create_time')==process_create_time,'Receipt owner/lifetime differs')
    require(same_path(p['expected_document_path'],source_path)
        and r.get('source_after_sha256')==r.get('saved_file_sha256')==source_sha256,'Saved source transition differs')
    require(p.get('selected_operation_native_ids')==r.get('selected_operation_native_ids')==selected_operation_ids,'Selected target mapping differs')
    require(same_path(p['receipt_path'],receipt_pin['path']),'Receipt path differs')
    require(same_path(r['dispatch_marker_path'],marker_pin['path'])
        and same_path(p['attempt_registry_path'],marker_pin['path']),'Consumed generation marker path differs')
    marker=json.loads(read_pin(marker_pin))
    expected_marker=dict(scope=generation.SCOPE,receipt_path=receipt_pin['path'],receipt_sha256=receipt_pin['sha256'],
        configuration_receipt_pin=r['configuration_receipt_pin'],selected_operation_native_ids=selected_operation_ids,
        status='review_required',phase='finished',automatic_replay=False)
    require(set(marker)==set(expected_marker) and same_path(marker['receipt_path'],receipt_pin['path']),
        'Consumed generation marker fields/path differ')
    compared_marker=deepcopy(marker);compared_marker['receipt_path']=expected_marker['receipt_path']
    require(compared_marker==expected_marker,'Consumed successful generation marker differs')
    actions=r.get('actions',{})
    require(set(actions)=={'preCL','GTP:'+str(oid),'SaveActiveDocument','postCL'}
        and all(completed_action(v)for v in actions.values()),'Exactly one successful GTP, Save and two CL exports required')
    stage=r.get('save_stage',{})
    require(stage.get('save_readback_verified')is True and stage.get('native_return_type')=='int'
        and type(stage.get('native_return_value'))is int and stage['native_return_value']==0,'Durable successful Save readback required')
    before,generated,saved=r['before'],r['generated'],r['saved']
    old_sha=r['source_before_sha256'];require(p.get('expected_source_sha256')==old_sha,'Pre-save source mismatch')
    old=complete_state(before,process_id,old_sha);new=complete_state(saved,process_id,source_sha256)
    require(saved['document']['needs_save']is False and saved['sketch_state']['needs_save']is False
        and same_path(saved['document']['path'],source_path),'Exact clean saved document required')
    for key in ('confirm_before','after_preCL','before_GTP_'+str(oid)):
        require(authority.circular_state_equal(before,r[key]),'Pre-generation capture differs: '+key)
    require(authority.circular_state_equal(generated,r['after_GTP_'+str(oid)])
        and authority.circular_state_equal(generated,r['confirm_GTP_'+str(oid)])
        and authority.circular_state_equal(generated,r['before_save']),'Generated/read-before-save captures differ')
    complete_state(generated,process_id,old_sha)
    delta.verify_generation(authority.normalized(before),authority.normalized(authority.align_circular_mass(before,generated)),selected_operation_ids,selected_operation_ids)
    authority.pocket.verify_saved(generated,saved,source_sha256)
    for key in ('confirm_saved','after_postCL'):
        require(authority.circular_state_equal(saved,r[key]),'Saved complete capture differs: '+key)
    require(type(protected_operation_ids)is list and protected_operation_ids==[x['operation_native_id']for x in old['generated']]
        and all(type(v)is int for v in protected_operation_ids),'Protected generated IDs differ')
    require(new['generated']==expected_generated_operations,'Explicit ordered generated count mapping differs')
    require(set(x['operation_native_id']for x in new['generated'])==set(protected_operation_ids)|{oid}
        and oid not in protected_operation_ids,'Only one newly generated target permitted')
    parsed=[];pins=[deepcopy(receipt_pin),deepcopy(marker_pin),deepcopy(r['configuration_receipt_pin']),dict(path=source_path,sha256=source_sha256)]
    for key,state,sha,rows in [('preCL',before,old_sha,old['generated']),('postCL',saved,source_sha256,new['generated'])]:
        cl=r[key]
        require(cl.get('output_verified')is True and cl.get('readback_verified')is True
            and cl.get('source_sha256')==sha and cl.get('expected_generated_operations')==rows,'Verified CL output/context differs: '+key)
        require(authority.circular_state_equal(cl['before'],state) and authority.circular_state_equal(cl['after'],state),'CL export capture differs: '+key)
        pin=deepcopy(cl['output']);raw=read_pin(pin);pins.append(pin)
        parsed.append(parser(raw,expected_block_record_counts=[x['toolpath_record_counts'][0]for x in rows]))
    preservation=delta.compare_cl(parsed[0],parsed[1],old['generated'],new['generated'],selected_operation_ids)
    require(preservation==r['CL_preservation'],'Recorded protected full-stream proof differs')
    for item in pins:read_pin(item)
    return dict(scope=SCOPE,process_id=process_id,process_create_time=process_create_time,
        source_path=source_path,source_sha256=source_sha256,receipt_pin=deepcopy(receipt_pin),
        pins=pins,document=deepcopy(saved['document']),snapshot=deepcopy(saved),
        selected_operation_ids=deepcopy(selected_operation_ids),protected_operation_ids=deepcopy(protected_operation_ids),
        expected_generated_operations=deepcopy(new['generated']),total_native_records=new['total_record_count'],
        operation_count=len(new['rows']),protected_complete_streams=preservation,
        saved_CL=deepcopy(r['postCL']['output']),producer_terminal_revalidated=True)


def bind_completed_receipt(receipt_pin,**kwargs):
    reader=kwargs.get('read_pin',direct)
    r=json.loads(reader(receipt_pin))
    bound=validate_terminal(r,receipt_pin,**kwargs)
    bound['binding_sha256']=digest(bound)
    return bound


def validate_capture(bound,document,snapshot,*,verify_direct_pin=direct):
    value=deepcopy(bound);expected=value.pop('binding_sha256')
    require(digest(value)==expected,'Bound authority changed')
    require(document==bound['document'] and document['needs_save']is False,'Clean saved identity changed')
    complete_state(snapshot,bound['process_id'],bound['source_sha256'])
    require(authority.circular_state_equal(snapshot,bound['snapshot']),'Complete saved CAM state changed')
    require(delta.inventory(snapshot)['generated']==bound['expected_generated_operations'],'Generated records changed')
    for p in bound['pins']:verify_direct_pin(p)
    # Existing circular mass normalization only. Canonical return lets the
    # unchanged core compare captures exactly, without inventing a fresh read.
    return dict(document=deepcopy(document),source_sha256=bound['source_sha256'],
        snapshot=authority.normalized(authority.align_circular_mass(bound['snapshot'],snapshot)))


def new_report(bound,*,output_dir,implementation_pin):
    return dict(scope=SCOPE,status='prepared',phase='prepared',process_id=bound['process_id'],
        source_path=bound['source_path'],source_sha256=bound['source_sha256'],binding_sha256=bound['binding_sha256'],
        saved_receipt_pin=bound['receipt_pin'],module_pin=implementation_pin,
        expected_generated_operations=deepcopy(bound['expected_generated_operations']),
        native_scope='all_wip_parts_all_setups',single_operation_scope_claimed=False,
        native_method='ICWMachine5.CreateSTLOfWIPs2',native_parameters=[str(output_dir).rstrip('/\\')+'\\','wip.stl','',0,0],
        native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,native_call_count=0,
        mutation_attempted=False,readback_verified=False,export_files_verified=False,files=[],
        GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,model_saved=False,setter_attempted=False,
        assignment_attempted=False,simulation_attempted=False,automatic_replay=False,automatic_retry=False,
        geometry_verified=False,whole_R25_geometry_verified=False,mesh_error_bound_qualified=False,
        temporal_collision_verified=False,production_qualified=False)


def run_existing_core(core,bound,report,*,capture_existing,guard_factory,persist,claim,invoke,collect,verify_direct_pin=direct):
    """Outer native owner supplies existing guard/marker/output/cleanup callbacks."""
    require(report['scope']==SCOPE and report['binding_sha256']==bound['binding_sha256']
        and report['native_call_count']==0 and report['native_call_attempted']is False,'Fresh bound WIP report required')
    def capture(label):
        document,snapshot,native=capture_existing(label)
        report.setdefault('raw_captures',[]).append(dict(label=label,document=deepcopy(document),snapshot=deepcopy(snapshot)));persist()
        return validate_capture(bound,document,snapshot,verify_direct_pin=verify_direct_pin),native
    core.run_one_wip_export(report,capture=capture,guard_factory=guard_factory,persist=persist,claim=claim,invoke=invoke,collect=collect)
    require(report['readback_verified']is True and report['export_files_verified']is True
        and report['native_call_count']==1 and report['native_dispatch_pending']is False,'Existing WIP core did not complete')
    require([x['label']for x in report['raw_captures']]==['before','after'],'Two actual complete captures required')
    report.update(binding_readback_verified=True,outer_cleanup_still_required=True)
    persist();return report
