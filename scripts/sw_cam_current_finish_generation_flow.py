"""Single Finish GTP, checked Save, one CL export; existing durable once journal."""
from copy import deepcopy
from scripts import sw_cam_current_finish_generation_delta as delta
from scripts.sw_cam_current_saved_generation import Journal as BaseJournal
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash
require=delta.require;exact=delta.exact
SCOPE='CURRENT_ORDINARY_CIRCULAR_FINISH_GENERATION_V1'
class Journal(BaseJournal):
    def marker_state(self):return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),configuration_receipt_pin=deepcopy(self.report['configuration_receipt_pin']),selected_operation_native_ids=list(self.report['selected_operation_native_ids']),status=self.report['status'],phase=self.report['phase'],automatic_replay=False)
def completed(a):return a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0

def run_once(backend,journal,data):
    r=journal.report;oid=data['operation_id'];fid=data['feature_id'];reference=data['state']
    def capture(label):
        detail=dict(label=label,state={},capture_complete=False);r['captures'].append(detail);r['phase']=label;journal.persist();state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'Complete full snapshot required');detail.update(state=deepcopy(state),capture_complete=True);r[label]=deepcopy(state);journal.persist();return state
    try:
        journal.create();backend.start();before=capture('before');require(delta.configuration.circular.circular_state_equal(before,reference),'Fresh full state differs from saved configuration');delta.select(before,oid,fid);require(exact(r['plane_observations']['before'],data['planes']),'Fresh planes differ');backend.boundary();journal.claim()
        name='GTP:'+str(oid);action=journal.action(name);backend.generate(oid,before,pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value));require(completed(action),'Exact returned GenerateToolpath int0 required; no replay')
        generated=capture('generated');r['generation_proof']=delta.verify_generation(before,generated,oid,fid);require(exact(r['plane_observations']['generated'],data['planes']),'GTP changed floor/wall planes');r['generation_verified']=True;journal.persist();backend.boundary()
        action=journal.action('SaveActiveDocument');r['save_stage']={}
        def returned(value):
            journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value)in(int,bool,float,str)else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);require(completed(action),'Exact returned Save int0 required');sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha,save_returned_zero=True);journal.persist()
        saved=capture('saved');r['saved_proof']=delta.verify_saved(generated,saved,oid,fid,sha);require(exact(r['plane_observations']['saved'],data['planes']),'Save changed planes');r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        action=journal.action('postCL');detail={};r['postCL']=detail;journal.persist();result=backend.export_cl('postCL',saved,delta.positive_rows(saved),detail,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value));require(completed(action)and result.get('output_verified')is True and result.get('readback_verified')is True,'Verified CL export required');r['postCL']=deepcopy(result);r['CL_preservation']=deepcopy(result['comparison_proof']['CL_preservation']);journal.persist();backend.finish()
        r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,generation_saved=True,reason='ONE_ORDINARY_CIRCLE_FINISH_GENERATED_SAVED_CL_VERIFIED')
    except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,runtime_unchanged=False,generation_saved=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,generation_saved=False)
        journal.persist()
    return r
