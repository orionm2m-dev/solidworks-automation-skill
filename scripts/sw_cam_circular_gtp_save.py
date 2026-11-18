"""Preserve an explicitly observed circular GTP result; no generation or setters."""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts import sw_cam_current_circular_authority as authority
from scripts.sw_cam_current_circular_continuation import CircularGenerationContext,CircularGenerationProof
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error

SCOPE='MILL_CIRCULAR_COMPLETED_GTP_SAVE_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
      'failed_receipt_path','failed_receipt_sha256','old_marker_path','old_marker_sha256',
      'operation_native_id','expected_xy_feed_before','expected_xy_feed_after','expected_generated_record_count',
      'receipt_path','saved_cl_path','qualification_only','message_policy'}
require=delta.require
same=authority.circular_state_equal


def verify_feed_delta(before,after,oid,old_feed,new_feed,record_count):
    """Only a requested positive feed refresh in two echoes, plus one GTP result."""
    require(type(oid) is int and oid>0,'Strict selected operation required')
    require(all(type(x) is float and math.isfinite(x) and x>0 for x in (old_feed,new_feed)) and old_feed!=new_feed,'Explicit distinct positive DOUBLE feed pair required')
    require(type(record_count) is int and 0<record_count<=delta.MAX_RECORDS,'Explicit positive generated record count required')
    adjusted=authority.normalized(authority.align_circular_mass(before,after));base=authority.normalized(before)
    key=str(oid)
    for family in ('candidate_consumers','target_nc'):
        for state,expected in ((base,old_feed),(adjusted,new_feed)):
            row=state['parameter_batch'][family][key]
            require(row.get('operation_native_id')==oid and row.get('read_complete') is True,'Exact own complete feed echo required')
            value=row['feeds_compensation']['XYFeed']
            require(type(value) is float and value==expected,'Feed echo differs from explicit transition')
        adjusted['parameter_batch'][family][key]['feeds_compensation']['XYFeed']=old_feed
    selected=next(r for r in adjusted['operations'] if r['native_id']==oid)
    require(selected['toolpath_record_counts']==[record_count],'Observed generated count differs')
    proof=delta.verify_generation(base,adjusted,[oid],[oid])
    proof.update(feed_refresh=dict(operation_native_id=oid,old=old_feed,new=new_feed,echoes=['candidate_consumers','target_nc']),cutting_conditions_qualified=False)
    return proof


def completed_action(action):
    return (type(action) is dict and set(action)=={'attempted','returned','native_dispatch_pending','native_return_type','native_return_value'}
        and action['attempted'] is True and action['returned'] is True and action['native_dispatch_pending'] is False
        and action['native_return_type']=='int' and type(action['native_return_value']) is int and action['native_return_value']==0)


def validate_history(partial,old_marker,v,loaded,partial_pin,marker_pin):
    oid=v['operation_native_id'];ids=[oid];request=partial.get('request',{});p=request.get('params',{})
    require(partial.get('scope')==engine.SCOPE and partial.get('status')=='uncertain' and partial.get('phase')=='finished','Exact finished stopped generation receipt required')
    require(request.get('action')=='generate_configured_local_group' and p.get('generation_mode')=='current_saved_circular'
        and partial.get('request_sha256')==_digest(request),'Exact historical circular generation packet required')
    for key in ('process_id','expected_process_create_time','expected_document_path','expected_source_sha256'):
        require(type(p.get(key)) is type(v[key]) and p[key]==v[key],'Original generation target/lifetime/source differs: '+key)
    require(partial.get('selected_operation_native_ids')==p.get('selected_operation_native_ids')==ids,'One exact historical selected operation required')
    require(partial.get('source_before_sha256')==v['expected_source_sha256'],'Historical source differs')
    require(partial.get('reason')=='GTP changed protected operation, suppression, tool, parameter, feature/setup or source fields','Only exact local generation-delta stop allowed')
    issue=partial.get('issue',{})
    require(issue.get('type')=='ValueError' and issue.get('hresult') is None and any(x.get('function')=='verify_generation' for x in issue.get('locations',[])),'Exact local verifier failure required')
    require(not any(k in partial for k in ('runtime_error','receipt_write_error','cleanup_error','source_after_sha256','saved_file_sha256','saved','postCL')),'Historical runtime/cleanup/save failure is outside continuation')
    for k in ('save_attempted','model_saved','native_dispatch_pending','GOP_attempted','AFR_attempted','operation_creation_attempted','tool_assignment_attempted','parameter_setter_attempted','automatic_replay','automatic_rollback'):
        require(partial.get(k) is False,'Unexpected historical action: '+k)
    for k in ('GTP_attempted','native_call_attempted','native_call_returned','marker_created','receipt_created'):
        require(partial.get(k) is True,'Missing completed generation evidence: '+k)
    actions=partial.get('actions',{})
    require(set(actions)=={'preCL','GTP:'+str(oid)} and all(completed_action(a) for a in actions.values()),'One returned GTP and one preCL only required')
    clean_events(partial)
    require(partial.get('configuration_receipt_pin')==loaded['pin'],'Historical configuration authority differs')
    for name in ('before','confirm_before','preCL_before','preCL_after','after_preCL','before_GTP_'+str(oid)):
        require(same(partial.get(name),loaded['state']),'Historical pre-GTP complete capture differs: '+name)
    after=partial.get('after_GTP_'+str(oid));proof=verify_feed_delta(loaded['state'],after,oid,v['expected_xy_feed_before'],v['expected_xy_feed_after'],v['expected_generated_record_count'])
    require(same(after,partial.get('failure_actual')),'Repeated postfailure capture differs from generated state')
    for state in (after,partial['failure_actual']):
        require(state['sketch_state']['pid']==v['process_id'] and state['sketch_state']['saved_file_sha256']==v['expected_source_sha256'],'Generated sketch PID/source differs')
    require(Path(partial.get('receipt_path','')).resolve()==Path(partial_pin['path']).resolve()
        and Path(partial.get('dispatch_marker_path','')).resolve()==Path(marker_pin['path']).resolve(),'Historical receipt/marker paths differ')
    require(old_marker.get('scope')==engine.SCOPE and old_marker.get('status')=='uncertain' and old_marker.get('phase')=='finished'
        and old_marker.get('automatic_replay') is False and old_marker.get('receipt_sha256')==partial_pin['sha256']
        and Path(old_marker.get('receipt_path','')).resolve()==Path(partial_pin['path']).resolve()
        and old_marker.get('configuration_receipt_pin')==loaded['pin'] and old_marker.get('selected_operation_native_ids')==ids,'Original consumed marker does not identify exact failed receipt')
    pre=partial.get('preCL',{})
    require(pre.get('output_verified') is True and pre.get('readback_verified') is True and pre.get('source_sha256')==v['expected_source_sha256']
        and pre.get('expected_generated_operations')==delta.inventory(loaded['state'])['generated'],'Verified historical preCL/context required')
    return dict(expected_state=deepcopy(after),proof=proof,preCL=deepcopy(pre))


def validate(v):
    require(type(v) is dict and set(v)==KEYS,'Exact save-only fields required')
    require(type(v['process_id']) is int and 0<v['process_id']<2**31,'Strict positive PID required')
    t=v['expected_process_create_time'];require(type(t) in (int,float) and math.isfinite(t) and t>0,'Exact process lifetime required')
    require(v['qualification_only'] is True and v['message_policy']=='vendor_default','Explicit qualification-only/default-event policy required')
    for key in ('expected_source_sha256','failed_receipt_sha256','old_marker_sha256'):require(type(v[key]) is str and re.fullmatch('[0-9a-f]{64}',v[key]),'Exact file SHA required')
    source=Path(v['expected_document_path']);require(source.is_absolute() and source.suffix.lower()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact current saved source required')
    partial,pp=read_pin(v['failed_receipt_path'],v['failed_receipt_sha256']);old_marker,mp=read_pin(v['old_marker_path'],v['old_marker_sha256'])
    p=partial.get('request',{}).get('params',{})
    require(p.get('module_sha256')==_file_hash(engine.__file__),'Original generation engine changed; explicit compatibility review needed')
    loaded=engine.load_completed_configuration(p['configuration_receipt_path'],p['configuration_receipt_sha256'],process_id=v['process_id'],source_path=str(source),source_sha256=v['expected_source_sha256'],selected_ids=[v['operation_native_id']])
    require(loaded.get('mode')=='current_saved_circular' and loaded['binding']['expected_process_create_time']==t,'Circular authority/lifetime required')
    history=validate_history(partial,old_marker,v,loaded,pp,mp)
    cl=history['preCL']['output'];cp=Path(cl['path']);require(cp.is_file() and not cp.is_symlink() and 0<cp.stat().st_size==cl['bytes']<=64*1024*1024 and _file_hash(cp)==cl['sha256'],'Historical preCL bytes changed')
    from scripts.sw_cam_deep_guide_cl import _fresh_path
    output=_fresh_path(v['saved_cl_path']);receipt=Path(v['receipt_path'])
    require(receipt.is_absolute() and receipt.suffix.lower()=='.json' and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink(),'Fresh absolute receipt required')
    marker=Path(mp['path']).parent/('circular_gtp_save_'+_digest(dict(scope=SCOPE,partial_sha256=pp['sha256'],source=str(source.resolve()).casefold(),source_sha256=v['expected_source_sha256']))+'.json')
    require(not marker.exists() and not marker.is_symlink(),'Prior save continuation attempt exists; no replay')
    protected={source.resolve(),cp.resolve(),Path(pp['path']).resolve(),Path(mp['path']).resolve(),Path(loaded['pin']['path']).resolve(),Path(__file__).resolve()}
    protected.update(Path(pin['path']).resolve() for pin in loaded['pins'].values())
    outputs=[output,receipt,marker];require(len({x.resolve() for x in outputs})==3 and not protected.intersection(x.resolve() for x in outputs),'Outputs alias protected evidence/source')
    require(all(x.resolve().parent!=output.parent.resolve() for x in (receipt,marker)),'CL directory must contain only CL output')
    return dict(loaded=loaded,history=history,partial=partial,partial_pin=pp,old_marker_pin=mp,cl_pin=deepcopy(cl),marker=marker,receipt=receipt,module_sha256=_file_hash(__file__))


class ContinuationContext(CircularGenerationContext):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        self.continuation_data=data
        args=deepcopy(data['partial']['request']['params']);args['saved_cl_path']=v['saved_cl_path']
        super().__init__(sw,clsid,tlb,args,data['loaded'],report,persist,runtime_check)
        self.attempted=[v['operation_native_id']]
        self.pins.extend([data['partial_pin'],data['old_marker_pin']])
        self.data=deepcopy(self.data);self.data['recovery']={'expected_state':deepcopy(data['history']['expected_state'])}
    def verify_files(self):
        super().verify_files()
        if getattr(self,'_capture_pin_scope',False):return
        d=self.continuation_data
        require(_file_hash(d['cl_pin']['path'])==d['cl_pin']['sha256'] and _file_hash(__file__)==d['module_sha256'],'Historical CL or continuation implementation changed')
    def generate(self,*args,**kwargs):raise ValueError('GTP prohibited in save-only continuation')
    def set_tool(self,*args,**kwargs):raise ValueError('Tool setters prohibited in save-only continuation')
    def set_field(self,*args,**kwargs):raise ValueError('Parameter setters prohibited in save-only continuation')


class ContinuationJournal(engine.Journal):
    def marker_state(self):
        return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),historical_generation_pin=self.report['historical_generation_pin'],status=self.report['status'],phase=self.report['phase'],automatic_replay=False)
    def pending(self,name):
        require(name in ('SaveActiveDocument','postCL'),'Only Save or CL dispatch allowed')
        super().pending(name)


def run_once(backend,journal,data,v):
    r=journal.report;current=data['history']['expected_state'];oid=v['operation_native_id'];proof=CircularGenerationProof(backend,reference=current)
    def observe(label):
        row=dict(label=label,capture_complete=False,state={});r['captures'].append(row);r['phase']=label;journal.persist()
        actual=backend.capture(label,row['state']);row.update(state=deepcopy(actual),capture_complete=actual.get('capture_complete') is True and actual.get('parameter_capture_complete') is True and actual.get('parameter_batch',{}).get('read_complete') is True);r[label]=deepcopy(actual);journal.persist();require(row['capture_complete'],'Complete current capture required');return actual
    try:
        journal.create();backend.start();backend.boundary()
        before=observe('before');confirm=observe('confirm_before');require(same(before,current) and same(before,confirm),'Fresh current state differs from exact observed GTP result')
        verify_feed_delta(data['loaded']['state'],before,oid,v['expected_xy_feed_before'],v['expected_xy_feed_after'],v['expected_generated_record_count'])
        backend.boundary();journal.claim();backend.boundary();r['generated']=deepcopy(before);r['save_stage']={};journal.action('SaveActiveDocument')
        def save_capture(label):
            actual=observe('before_save' if label=='before' else 'saved')
            if label=='before':require(same(actual,current),'State changed before Save')
            else:proof.verify_saved(current,actual)
            return proof.save_comparison_state(actual)
        expected=proof.save_comparison_state(current)
        def verify(state):require(same(state,expected),'Save changed captured state')
        def returned(value):
            journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value) in (bool,int,float,str) else None);journal.persist()
        def saved_hash():
            value=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=value,saved_file_sha256=value);journal.persist();return value
        run_one_existing_save(r['save_stage'],capture=save_capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=lambda:backend.save(returned=returned),saved_hash=saved_hash)
        saved=observe('confirm_saved');proof.verify_saved(current,saved);require(same(saved,r['saved']),'Two saved captures differ')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist()
        a=journal.action('postCL');rows=delta.inventory(saved)['generated'];detail=dict(expected_generated_operations=deepcopy(rows),output_verified=False);r['postCL']=detail;journal.persist()
        post=backend.export_cl('postCL',saved,rows,detail,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value));r['postCL']=deepcopy(post);journal.persist()
        require(completed_action(a) and post.get('output_verified') is True and post.get('readback_verified') is True,'One successful fullCL export required')
        r['CL_preservation']=delta.compare_cl(backend.parse_cl(data['history']['preCL']),backend.parse_cl(post),data['history']['preCL']['expected_generated_operations'],rows,[oid]);journal.persist()
        last=observe('after_postCL');require(same(last,saved),'CL export changed saved state');backend.boundary();backend.finish()
        r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,continuation_verified=True,reason='ALREADY_GENERATED_RESULT_SAVED_ONCE_CL_COMPARED_NO_GTP_REPLAY')
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') or r.get('CL_export_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,continuation_verified=False,model_saved=False,save_readback_verified=False,source_update_verified=False,runtime_unchanged=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',cleanup_error=_error(exc),continuation_verified=False,readback_verified=False,runtime_unchanged=False,model_saved=False,save_readback_verified=False)
        journal.persist()
    return r


def dispatch(sw,clsid,tlb,*,runtime_check,_context_factory=ContinuationContext,**v):
    data=validate(v);require(data['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Pinned CAM add-in differs')
    engine.preflight(tlb)
    from scripts import sw_cam_mill_current_compound_read as current
    from scripts import sw_cam_mill_current_parameters as parameters
    from scripts import sw_cam_current_parameter_capture as captures
    from scripts.sw_cam_comtypes import _interface_class
    current._abi(tlb);parameters.preflight(tlb,'selected_continue')
    for name in captures.PREFLIGHT_INTERFACES:_interface_class(name,tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',receipt_path=v['receipt_path'],dispatch_marker_path=str(data['marker']),request=deepcopy(v),historical_generation_pin=data['partial_pin'],historical_marker_pin=data['old_marker_pin'],historical_preCL_pin=data['cl_pin'],configuration_receipt_pin=data['loaded']['pin'],selected_operation_native_ids=[v['operation_native_id']],feed_refresh_review=deepcopy(data['history']['proof']),source_before_sha256=v['expected_source_sha256'],actions={},captures=[],native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,GTP_attempted=False,GTP_replayed=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,CL_export_attempted=False,tool_assignment_attempted=False,parameter_setter_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,continuation_verified=False,runtime_unchanged=False,cutting_conditions_qualified=False,world_geometry_verified=False,production_qualified=False,reopen_persistence_verified=False)
    journal=ContinuationJournal(v['receipt_path'],data['marker'],r)
    backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check)
    runtime_check();result=run_once(backend,journal,data,v)
    try:runtime_check()
    except Exception as exc:
        result.update(status='uncertain' if result['mutation_attempted'] else 'error',runtime_error=_error(exc),runtime_unchanged=False,readback_verified=False,continuation_verified=False,model_saved=False,save_readback_verified=False);journal.persist()
    return result
