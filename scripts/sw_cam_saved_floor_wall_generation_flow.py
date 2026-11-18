"""Selected pair flow reused from the bounded generation engine.
The legacy module remains unchanged. Only the explicit proof adapter differs;
coalesced preCL snapshots retain actual before/after and a fresh preGTP capture.
"""
from copy import deepcopy
from scripts import sw_cam_saved_floor_wall_generation_delta as mixed
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam import _error
require=delta.require
SCOPE='MILL_SAVED_PAIR_SELECTED_GENERATION_V1'

def run_once(backend,journal,loaded):
    """preCL→明确目标 GTP→checked Save→postCL；所有失败保留实际结果而不重试。"""
    r=journal.report;reference=loaded['state'];ids=loaded['selected_ids'];completed=[]
    proof=mixed.Proof(backend,reference);circular=True
    r.update(scope=SCOPE,status='error',phase='preflight',configuration_receipt_pin=deepcopy(loaded['pin']),selected_operation_native_ids=list(ids),actions={},captures=[],receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,CL_export_attempted=False,model_saved=False,save_readback_verified=False,readback_verified=False,source_update_verified=False,operation_creation_attempted=False,tool_assignment_attempted=False,parameter_setter_attempted=False,automatic_replay=False,automatic_rollback=False,world_geometry_verified=False,production_qualified=False,reopen_persistence_verified=False,runtime_unchanged=False,source_before_sha256=loaded['source_sha256'])
    def observe(label):
        row=dict(label=label,capture_complete=False,state={});r['captures'].append(row);r['phase']=label;journal.persist()
        value=backend.capture(label,row['state']);row['state']=deepcopy(value);row['capture_complete']=value.get('capture_complete') is True and value.get('parameter_capture_complete') is True and value.get('parameter_batch',{}).get('read_complete') is True;r[label]=deepcopy(value);journal.persist();return value
    def one_export(label,state):
        action=journal.action(label)
        expected=proof.cl_rows(reference,state,ids,completed_ids=completed or None)
        detail=dict(expected_generated_operations=deepcopy(expected),output_verified=False);r[label]=detail;journal.persist()
        value=backend.export_cl(label,state,expected,detail,pending=lambda:journal.pending(label),returned=lambda x:journal.returned(label,x))
        require(action['attempted'] is True and action['returned'] is True and action['native_return_type']=='int' and type(action['native_return_value']) is int and action['native_return_value']==0,'Exact completed SaveCLFile int0 required')
        r[label]=deepcopy(value);journal.persist();require(value.get('output_verified') is True and value.get('readback_verified') is True,'Verified native CL output required')
        return value
    try:
        proof.select(reference,ids);journal.create();backend.start();backend.boundary()
        backend.boundary();journal.claim();backend.boundary()
        # The export already captures the full state before and after SaveCL.
        # Bind those actual observations instead of reading them three more times.
        pre=one_export('preCL',reference)
        before=pre.get('before');current=pre.get('after')
        require(type(before) is dict and type(current) is dict,'Complete native preCL captures required')
        require(proof.equal(before,reference) and proof.equal(current,before),'preCL full captures differ from completed configuration')
        r['before']=deepcopy(before);r['after_preCL']=deepcopy(current)
        r['capture_policy']='coalesced_pre_gtp_v1'
        r['reused_capture_sources']={'before':'preCL.before','after_preCL':'preCL.after'}
        journal.persist()
        for oid in ids:
            fresh=observe('before_GTP_'+str(oid));require(proof.equal(fresh,current),'State changed immediately before selected GTP')
            name='GTP:'+str(oid);a=journal.action(name);backend.boundary()
            backend.generate(oid,fresh,pending=lambda:journal.pending(name),returned=lambda x:journal.returned(name,x))
            require(a['attempted'] is True and a['returned'] is True and a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0,'Exact GenerateToolpath int0 required; no replay')
            completed.append(oid)
            actual=observe('after_GTP_'+str(oid));r['generation_verification']=proof.verify_generation(reference,actual,ids,completed);journal.persist()
            confirm=observe('confirm_GTP_'+str(oid));require(proof.equal(actual,confirm),'Two complete postgeneration captures differ');current=confirm
        r['generated']=deepcopy(current);r['save_stage']={};journal.action('SaveActiveDocument')
        def save_capture(label):
            actual=observe('before_save'if label=='before'else'saved')
            if label=='before':require(proof.equal(actual,current),'Current CAM parameters changed before Save')
            else:proof.verify_saved(current,actual)
            normalized=deepcopy(actual);normalized['document']['needs_save']=False
            return proof.save_comparison_state(actual) if circular else normalized
        expected=deepcopy(current);expected['document']['needs_save']=False
        if circular:expected=proof.save_comparison_state(current)
        def verify(value):require(proof.equal(value,expected),'Save altered captured CAM context')
        def save_returned(value):
            journal.returned('SaveActiveDocument',value)
            r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value) in(bool,int,float,str)else None);journal.persist()
        def native_save():return backend.save(returned=save_returned)
        def saved_hash():
            value=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=value,saved_file_sha256=value);journal.persist();return value
        run_one_existing_save(r['save_stage'],capture=save_capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=native_save,saved_hash=saved_hash)
        confirm_saved=observe('confirm_saved');proof.verify_saved(current,confirm_saved);require(proof.equal(confirm_saved,r['saved']),'Two complete saved captures differ')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        post=one_export('postCL',confirm_saved)
        r['CL_preservation']=delta.compare_cl(backend.parse_cl(pre),backend.parse_cl(post),pre['expected_generated_operations'],post['expected_generated_operations'],ids);journal.persist()
        last=observe('after_postCL');require(proof.equal(last,confirm_saved),'Post-save CL export changed captured current state')
        backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True)
    except Exception as exc:
        r.update(status='uncertain'if r['mutation_attempted']or r['CL_export_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),reason=str(exc)if type(exc) is ValueError else 'NATIVE_OR_CAPTURE_FAILURE',readback_verified=False,model_saved=False,save_readback_verified=False,source_update_verified=False,runtime_unchanged=False)
        try:
            if r['mutation_attempted'] and backend.may_capture_failure():observe('failure_actual')
        except Exception as capture_error:r['failure_capture_issue']=_error(capture_error)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']or r['CL_export_attempted']else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,model_saved=False,save_readback_verified=False,source_update_verified=False)
        r['phase']='finished'
        try:journal.persist()
        except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']or r['CL_export_attempted']else'error',receipt_write_error=_error(exc),readback_verified=False,runtime_unchanged=False,model_saved=False,save_readback_verified=False,source_update_verified=False)
    return r
