"""Pure saved18 binding plus a thin adapter to the existing WIP export core.

This module does not bootstrap COM, load ancestry or dispatch a standalone native
request. The native owner must first validate the new completed Save receipt,
then supply its canonical saved_checkpoint and the existing guarded callbacks.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json

SCOPE='SAVED_EIGHTEEN_WHOLE_MACHINE_WIP_V1'

def require(ok,message):
    if not ok:raise ValueError(message)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def same_path(a,b):
    return str(Path(a).resolve()).casefold()==str(Path(b).resolve()).casefold()

def generated_streams(snapshot,targets):
    require(type(snapshot)is dict and set(snapshot)=={'binding','parameters'},'Exact saved route snapshot required')
    ops=snapshot['binding']['operations'];params=snapshot['parameters']
    require(len(ops)==21 and len(params)==12,'Exact21 operations and12 parameter groups required')
    ids=[v['native_id']for v in ops]
    require(all(type(v)is int and v>0 for v in ids)and len(set(ids))==21,'Distinct native operation IDs required')
    require(len({v['operation_native_id']for v in params})==12,'Distinct parameter operation IDs required')
    require(len(targets)==4 and [t['operation_type']for t in targets]==[0,1,0,1], 'Two saved Rough/Finish pairs required')
    selected=[t['operation_native_id']for t in targets]
    require(len(set(selected))==4 and ids[-4:]==selected,'Saved selected-four order differs')
    rows=[]
    for row in ops:
        flag=row['toolpath_generated'];require(type(flag)is bool,'Strict generation flag required')
        counts=row['toolpath_record_counts']
        if flag:
            require(row['suppressed']is False and type(counts)is list and len(counts)==1
                and type(counts[0])is int and counts[0]>0,'One positive unsuppressed stream required')
            rows.append(dict(operation_native_id=row['native_id'],toolpath_record_counts=deepcopy(counts)))
    require(len(rows)==18 and [r['operation_native_id']for r in rows[-4:]]==selected,'Exact protected14 plus new4 streams required')
    for row,t in zip(ops[-4:],targets):
        require(row['linked_feature_ids']==[t['feature_native_id']]and row['mill_operation_type']==t['operation_type']
            and row['assigned_tool']==t['assigned_tool'],'Saved selected feature/type/tool binding differs')
    return rows

def bind_verified_checkpoint(checkpoint,*,receipt_pin,terminal_proof,expected_source_sha256,expected_document_path,process_id,verify_direct_pin):
    """Bind an ALREADY independently verified producer terminal; no ancestry walk.

The exact new continuation validator is deliberately outside this reusable layer.
Its caller must check successful terminal semantics before passing terminal_proof.
A native entry point may not use this function alone as receipt validation.
"""
    require(type(process_id)is int and process_id>0,'Explicit owned PID required')
    require(type(terminal_proof)is dict and terminal_proof.get('verified')is True
        and terminal_proof.get('receipt_sha256')==receipt_pin['sha256']
        and terminal_proof.get('source_sha256')==expected_source_sha256
        and terminal_proof.get('process_id')==process_id,'Bound parent terminal-verifier result required')
    require(checkpoint['source_sha256']==expected_source_sha256 and same_path(checkpoint['source_path'],expected_document_path), 'Saved source differs')
    document=checkpoint['document'];require(document['needs_save']is False and same_path(document['path'],expected_document_path),'Exact clean saved document required')
    require(checkpoint['current_counts']==dict(operations=21,parameters=12,paths=18,tools=21),'Saved18 counts differ')
    require(checkpoint['GTP_complete']is True and checkpoint['nominal_geometry_accepted']is False and checkpoint['production_qualified']is False,'Saved scope differs')
    rows=generated_streams(checkpoint['snapshot'],checkpoint['learned_targets']);cl=checkpoint['saved_cl']
    require(cl['status']=='export_verified'and cl['output_verified']is True and cl['readback_verified']is True
        and cl['source_sha256']==expected_source_sha256 and cl['expected_generated_operations']==rows,'Current saved CL binding differs')
    verify_direct_pin(receipt_pin);verify_direct_pin(cl['output'])
    verify_direct_pin(dict(path=checkpoint['source_path'],sha256=expected_source_sha256))
    result=dict(scope=SCOPE,process_id=process_id,receipt_pin=deepcopy(receipt_pin),terminal_proof=deepcopy(terminal_proof),
        source_path=checkpoint['source_path'],source_sha256=expected_source_sha256,document=deepcopy(document),
        configuration=deepcopy(checkpoint['configuration']),snapshot=deepcopy(checkpoint['snapshot']),
        saved_cl=deepcopy(cl),learned_targets=deepcopy(checkpoint['learned_targets']),
        expected_generated_operations=rows,tool_catalogue=deepcopy(checkpoint['tool_catalogue']),
        tool_dimensions=deepcopy(checkpoint['tool_dimensions']),cumulative_ancestry_replayed=False)
    result['binding_sha256']=digest(result);return result

def validate_capture(bound,document,snapshot,*,verify_direct_pin):
    copy=deepcopy(bound);recorded=copy.pop('binding_sha256');require(digest(copy)==recorded,'In-memory bound authority changed')
    require(document==bound['document']and document['needs_save']is False,'WIP changed clean saved document')
    require(snapshot==bound['snapshot'],'WIP changed saved route, parameters, tools or path records')
    require(generated_streams(snapshot,bound['learned_targets'])==bound['expected_generated_operations'],'WIP stream identity changed')
    verify_direct_pin(dict(path=bound['source_path'],sha256=bound['source_sha256']))
    return dict(document=deepcopy(document),saved_file_sha256=bound['source_sha256'],snapshot=deepcopy(snapshot))

def new_report(bound,*,output_dir,implementation_pin):
    return dict(scope=SCOPE,status='prepared',phase='prepared',process_id=bound['process_id'],
        source_path=bound['source_path'],source_sha256=bound['source_sha256'],saved_checkpoint_pin=bound['receipt_pin'],
        terminal_proof=bound['terminal_proof'],binding_sha256=bound['binding_sha256'],module_pin=implementation_pin,
        expected_generated_operations=bound['expected_generated_operations'],native_scope='all_wip_parts_all_setups',
        single_operation_scope_claimed=False,native_method='ICWMachine5.CreateSTLOfWIPs2',
        native_parameters=[str(output_dir).rstrip('/\\')+'\\','wip.stl','',0,0],export_quality_raw=0,export_quality_label='FINE',
        native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,native_call_count=0,mutation_attempted=False,
        readback_verified=False,export_files_verified=False,files=[],GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,
        model_saved=False,setter_attempted=False,assignment_attempted=False,simulation_attempted=False,
        automatic_replay=False,automatic_retry=False,geometry_verified=False,geometry_acceptance_complete=False,
        mesh_error_bound_qualified=False,temporal_collision_verified=False,production_qualified=False)

def run_existing_core(core,bound,report,*,capture_existing,guard_factory,persist,claim,invoke,collect,verify_direct_pin):
    """Reuse core.run_one_wip_export exactly once; outer owner manages events/cleanup.

capture_existing(label) returns (document, complete saved snapshot, native handles).
All callbacks come from the existing guarded native adapter, never serialized code.
Fresh-directory/marker planning, bootstrap and cleanup remain with that adapter.
"""
    require(report['scope']==SCOPE and report['binding_sha256']==bound['binding_sha256']
        and report['native_call_count']==0 and report['native_call_attempted']is False,'Fresh bound WIP report required')
    def capture(label):
        document,snapshot,native=capture_existing(label)
        return validate_capture(bound,document,snapshot,verify_direct_pin=verify_direct_pin),native
    core.run_one_wip_export(report,capture=capture,guard_factory=guard_factory,persist=persist,claim=claim,invoke=invoke,collect=collect)
    require(report['readback_verified']is True and report['export_files_verified']is True
        and report['native_call_count']==1 and report['native_dispatch_pending']is False,'Existing export core did not complete')
    # Complete native receipt status is set only AFTER outer event cleanup verification.
    report['binding_readback_verified']=True;report['outer_cleanup_still_required']=True;persist()
    return report
