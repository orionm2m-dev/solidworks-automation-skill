"""Save/export only the positively generated part of a sealed failed pair packet."""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_saved_floor_wall_generation as generation
from scripts import sw_cam_saved_floor_wall_generation_delta as mixed
from scripts import sw_cam_current_saved_generation_delta as legacy
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_ud14_save import run_one_existing_save
require=legacy.require;exact=mixed.exact
SCOPE='PARTIAL_MILL_PAIR_SAVED_RESULT_RECOVERY_V1'
ACTION='save_partial_generated_mill_pair'
ACK='save_observed_partial_pair_once_export_existing_paths_no_gtp'
PARAMS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','failure_receipt_path','failure_receipt_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}

def completed(a):return a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0

def verify_raw_rows(reference,actual,data,allow_cleanup=False):
    require(type(reference)is list and type(actual)is list and len(reference)==len(actual),'Complete equal-sized route required')
    require([x['native_id']for x in actual]==[x['native_id']for x in reference]and len({x['native_id']for x in actual})==len(actual),'Exact unique ordered operation prefix required')
    floor,wall=data['selected_ids'];count=data['floor_count']
    expected=deepcopy(reference)
    for old,new,out in zip(reference,actual,expected):
        if old['native_id']==floor:
            require(type(old['mill_operation_type'])is int and old['mill_operation_type']==0 and old['suppressed']is False,'Exact unsuppressed Rough required')
            out.update(toolpath_generated=True,toolpath_record_counts=[count])
        elif old['native_id']==wall:
            require(type(old['mill_operation_type'])is int and old['mill_operation_type']==1 and old['suppressed']is False,'Exact unsuppressed Finish required')
            counts=new['toolpath_record_counts'];require(exact(counts,[0])or(allow_cleanup and exact(counts,[])),'Only observed zero-data wall object or postSave removal allowed')
            out.update(toolpath_generated=False,toolpath_record_counts=deepcopy(counts))
        require(exact(out,new),'Unexpected operation flag/count/type/link/tool or protected row change')
    return expected

def project_empty_wall(state,data,allow_cleanup=False):
    out=deepcopy(state);verify_raw_rows(data['configured_state']['operations'],out['operations'],data,allow_cleanup)
    wall=next(x for x in out['operations']if x['native_id']==data['selected_ids'][1]);wall['toolpath_record_counts']=[]
    return out

def verify_full_state(data,state,source_sha,allow_cleanup=False):
    require(state.get('capture_complete')is True and state.get('extended_capture_complete')is True and state.get('parameter_capture_complete')is True and state.get('parameter_batch',{}).get('read_complete')is True,'Fresh complete extended selected/draft state required')
    actual=project_empty_wall(state,data,allow_cleanup);expected=deepcopy(data['reference_state'])
    for key in('document','sketch_state'):
        require(type(actual[key]['needs_save'])is bool,'Strict dirty metadata required');expected[key]['needs_save']=actual[key]['needs_save']
    require(actual['sketch_state']['saved_file_sha256']==source_sha,'Exact current source in snapshot required');expected['sketch_state']['saved_file_sha256']=source_sha
    require(mixed.same(expected,actual),'Full selected/draft, parameters, geometry, tool, protected paths or source changed')
    info=legacy.inventory(actual);require(len(info['generated'])==data['old_generated_count']+1 and info['total_record_count']==data['old_record_count']+data['floor_count'],'Only positive floor added to generated inventory')
    return dict(full_captured_state_verified=True,positive_generated_count=len(info['generated']),positive_record_count=info['total_record_count'],wall_native_raw_counts=deepcopy(next(x['toolpath_record_counts']for x in state['operations']if x['native_id']==data['selected_ids'][1])),wall_generation_succeeded=False,wall_zero_object_projected_only_for_inventory=True,raw_observation_preserved=True,production_qualified=False)

def _filepin(p):
    p=Path(p)
    if p.suffix.lower()=='.json':return read_pin(str(p),_file_hash(p))[1]
    return dict(path=str(p),sha256=_file_hash(p))

def marker_path(v):return Path(v['expected_document_path']).parent/('partial_mill_save_'+_digest(dict(scope=SCOPE,source=str(Path(v['expected_document_path']).resolve()).casefold(),sha=v['expected_source_sha256'],failure=v['failure_receipt_sha256']))+'.json')

def _outputs(v,pins):
    marker=marker_path(v);outputs=[Path(v[k])for k in('receipt_path','progress_path','saved_cl_path')]+[marker]
    require(all(x.is_absolute()and not x.exists()and not x.is_symlink()for x in outputs),'Fresh explicit recovery outputs and marker required')
    require(all(Path(v[k]).parent.is_dir()for k in('receipt_path','progress_path'))and not Path(v['saved_cl_path']).parent.exists(),'Receipt parents must exist and CL directory must be fresh')
    resolved=[str(x.resolve()).casefold()for x in outputs];require(len(set(resolved))==len(resolved),'Distinct output paths required')
    protected={str(Path(x['path']).resolve()).casefold()for x in pins}|{str(Path(v['expected_document_path']).resolve()).casefold()};require(not set(resolved)&protected,'Outputs alias protected input')
    return marker

def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Explicit partial Save-only action required')
    v=deepcopy(request['params']);require(type(v)is dict and set(v)==PARAMS and v['acknowledgement']==ACK,'Exact recovery packet fields and acknowledgement required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owner lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact lowercase SHA required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute path required')
    require(v['module_sha256']==_file_hash(__file__),'Exact installed recovery module required')
    source=Path(v['expected_document_path']);require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==v['expected_source_sha256'],'Exact unchanged saved source required')
    failed,fp=read_pin(v['failure_receipt_path'],v['failure_receipt_sha256']);require(failed.get('scope')==generation.SCOPE and failed.get('status')=='uncertain'and failed.get('phase')=='finished','Terminal failed pair generation required')
    require(failed.get('reason')=='Positive bounded actual generated count required'and failed.get('native_dispatch_pending')is False and not any(k in failed for k in('runtime_error','cleanup_error','receipt_write_error')),'Only completed empty-wall failure without unresolved native/runtime dispatch supported');clean_events(failed)
    for k in('save_attempted','model_saved','parameter_setter_attempted','tool_assignment_attempted','operation_creation_attempted','GOP_attempted','AFR_attempted','automatic_replay','automatic_rollback'):require(failed.get(k)is False,'Unexpected failed-packet action: '+k)
    require(failed.get('GTP_attempted')is True and failed.get('marker_created')is True,'Both attempted generation and once marker required')
    old=failed['request'];require(old['action']=='generate_configured_local_group'and _digest(old)==failed['request_sha256'],'Exact sealed historical request required');args=old['params']
    for k in('process_id','expected_process_create_time','expected_source_sha256'):require(exact(args[k],v[k]),'Historical owner/source differs: '+k)
    require(Path(args['expected_document_path']).resolve()==source.resolve()and failed['source_before_sha256']==v['expected_source_sha256'],'Historical source path/hash differs')
    ids=args['selected_operation_native_ids'];require(type(ids)is list and len(ids)==2 and all(type(x)is int for x in ids)and exact(ids,failed['selected_operation_native_ids']),'Exact historical pair required')
    loaded=generation.authority.load_completed(args['configuration_receipt_path'],args['configuration_receipt_sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'],selected_ids=ids)
    require(exact(loaded['pin'],failed['configuration_receipt_pin']),'Historical configuration pin differs')
    require(list(failed['actions'])==['preCL','GTP:'+str(ids[0]),'GTP:'+str(ids[1])]and all(completed(x)for x in failed['actions'].values()),'Exactly preCL and two returned GTP0, no Save or replay required')
    reference=failed['before_GTP_'+str(ids[1])];proof=mixed.verify_generation(loaded['state'],reference,ids,[ids[0]])
    for k in('after_GTP_'+str(ids[0]),'confirm_GTP_'+str(ids[0])):require(mixed.same(failed[k],reference),'Two confirmed positive floor snapshots and pre-wall snapshot required')
    oldinfo=legacy.inventory(loaded['state']);floorcount=next(x['toolpath_record_counts'][0]for x in reference['operations']if x['native_id']==ids[0]);data=dict(selected_ids=ids,floor_count=floorcount,old_generated_count=len(oldinfo['generated']),old_record_count=oldinfo['total_record_count'],configured_state=loaded['state'],reference_state=deepcopy(reference))
    first=failed['after_GTP_'+str(ids[1])];last=failed['failure_actual'];verify_raw_rows(loaded['state']['operations'],first['operations'],data);verify_raw_rows(loaded['state']['operations'],last['operations'],data);require(exact(first['operations'],last['operations']),'Two observed basic failure routes differ')
    marker,mp=read_pin(failed['dispatch_marker_path'],_file_hash(failed['dispatch_marker_path']));wanted=dict(scope=generation.SCOPE,receipt_path=fp['path'],receipt_sha256=fp['sha256'],configuration_receipt_pin=loaded['pin'],selected_operation_native_ids=ids,status='uncertain',phase='finished',automatic_replay=False);observed=deepcopy(marker);require(Path(observed['receipt_path']).resolve()==Path(fp['path']).resolve(),'Original consumed marker path differs');observed['receipt_path']=fp['path'];require(exact(observed,wanted),'Original consumed marker differs')
    pre=failed['preCL'];require(pre.get('output_verified')is True and pre.get('readback_verified')is True and exact(pre['expected_generated_operations'],oldinfo['generated']),'Complete protected preCL required');clpin=_filepin(pre['output']['path']);require(clpin['sha256']==pre['output']['sha256']and Path(clpin['path']).stat().st_size==pre['output']['bytes'],'Historical preCL bytes differ')
    require(mixed.same(pre['before'],loaded['state'])and mixed.same(pre['after'],loaded['state']),'PreCL changed full saved configuration')
    expected=deepcopy(reference);next(x for x in expected['operations']if x['native_id']==ids[1])['toolpath_record_counts']=[0]
    expected['document']=deepcopy(last['document']);require(type(expected['document']['needs_save'])is bool,'Observed strict current dirty state required')
    pins=list(loaded['pins'])+[fp,mp,clpin]
    for x in failed['evidence_pins']:
        require(_file_hash(x['path'])==x['sha256'],'Failed generation immutable code/evidence changed');pins.append(x)
    for q in(__file__,Path(__file__).with_name('sw_cam_partial_floor_wall_generation_context.py')):pins.append(_filepin(q))
    unique={}
    for x in pins:
        key=str(Path(x['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==x['sha256'],'Conflicting immutable recovery pins');unique[key]=_filepin(x['path'])
    pins=list(unique.values());loaded['pins']=deepcopy(pins);loaded['context_data']['pins']=deepcopy(pins)
    data.update(loaded=loaded,failed=failed,failure_pin=fp,old_marker_pin=mp,preCL=pre,preCL_pin=clpin,pins=pins,expected_state=expected,failed_request=args,addin_clsid=loaded['addin_clsid'],original_floor_generation_proof=proof)
    marker=_outputs(v,pins);return v,data,marker

def _observed_pin(pin):
    from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes
    from scripts.sw_cam_stock_mesh_compare import _signature
    p=Path(pin['path']);require(p.is_file()and not p.is_symlink(),'Regular pinned evidence required')
    if p.suffix.lower()=='.json':_,actual=_receipt_bytes(str(p))
    else:
        canonical=p.resolve(strict=True);identity=list(_signature(p.stat()));digest=_file_hash(p)
        require(p.resolve(strict=True)==canonical and list(_signature(p.stat()))==identity,'Evidence changed while hashing')
        actual=dict(path=str(p),canonical_path=str(canonical),bytes=identity[2],sha256=digest,identity=identity)
    require(all(k in actual and actual[k]==v for k,v in pin.items()),'Prepared evidence pin changed');return actual

_ISSUER=object()
class _Prepared:
    def __init__(self,request,v,data,marker,pins):self.issuer=_ISSUER;self.request=deepcopy(request);self.v=deepcopy(v);self.data=deepcopy(data);self.marker=marker;self.pins=pins;self.used=False;self.digest=self.fingerprint()
    def fingerprint(self):return _digest(dict(request=self.request,v=self.v,data=self.data,marker=str(self.marker),pins=self.pins))

def _prepare_invocation(request,*,runtime_check):
    runtime_check();v,data,marker=prepare_request(request)
    pins=[_observed_pin(x)for x in data['pins']]+[_observed_pin(dict(path=v['expected_document_path'],sha256=v['expected_source_sha256']))];runtime_check();return _Prepared(request,v,data,marker,pins)

def _consume(bundle,request,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused recovery preparation required');bundle.used=True
    require(exact(bundle.request,request)and bundle.fingerprint()==bundle.digest,'Prepared authority/request changed');runtime_check()
    for x in bundle.pins:_observed_pin(x)
    require(_outputs(bundle.v,bundle.data['pins'])==bundle.marker,'Recovery output marker changed');runtime_check();return bundle.v,bundle.data,bundle.marker

class Journal(generation.Journal):
    def marker_state(self):return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),failure_receipt_pin=self.report['failure_receipt_pin'],status=self.report['status'],phase=self.report['phase'],automatic_replay=False)
    def pending(self,name):require(name in('SaveActiveDocument','postCL'),'Only Save and CL export permitted');super().pending(name)


def run_once(backend,journal,data,v):
    r=journal.report;initial=data['reference_state'];saved=None
    def observe(label):
        row=dict(label=label,capture_complete=False,state={});r['captures'].append(row);r['phase']=label;journal.persist();value=backend.capture(label,row['state']);r[label]=deepcopy(value);row.update(state=deepcopy(value),capture_complete=value.get('extended_capture_complete')is True);journal.persist();return value
    def normalized(state):
        out=project_empty_wall(state,data,allow_cleanup=backend.saved_phase);out=mixed.circular.align_circular_mass(initial,out)
        out['document']['needs_save']=False;out['sketch_state']['needs_save']=False;out['sketch_state']['saved_file_sha256']='verified-source-transition';return out
    expected=normalized(dict(initial,operations=deepcopy(data['expected_state']['operations'])))
    try:
        journal.create();backend.start();backend.boundary();journal.claim();journal.action('SaveActiveDocument');r['save_stage']={}
        def capture(label):
            state=observe('before_save'if label=='before'else'saved');proof=verify_full_state(data,state,backend.source,allow_cleanup=label!='before');r[label+'_proof']=proof
            if label!='before':require(state['document']['needs_save']is False and state['sketch_state']['needs_save']is False,'Clean postSave snapshot required')
            journal.persist();return normalized(state)
        def verify(value):require(mixed.same(value,expected),'Protected complete Save comparison differs')
        def returned(value):journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value)in(bool,int,float,str)else None);journal.persist()
        def saved_hash():
            sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha,save_returned_zero=True);journal.persist();return sha
        run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=lambda:backend.save(returned=returned),saved_hash=saved_hash)
        saved=r['saved'];r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);r['wall_postSave_transition']=dict(before=next(x['toolpath_record_counts']for x in r['before_save']['operations']if x['native_id']==data['selected_ids'][1]),after=next(x['toolpath_record_counts']for x in saved['operations']if x['native_id']==data['selected_ids'][1]),raw_preserved=True);journal.persist()
        rows=legacy.inventory(project_empty_wall(saved,data,allow_cleanup=True))['generated'];a=journal.action('postCL');detail=dict(expected_generated_operations=deepcopy(rows),output_verified=False);r['postCL']=detail;journal.persist()
        post=backend.export_cl('postCL',saved,rows,detail,pending=lambda:journal.pending('postCL'),returned=lambda x:journal.returned('postCL',x));r['postCL']=deepcopy(post);journal.persist();require(completed(a)and post.get('output_verified')is True and post.get('readback_verified')is True,'Complete single CL export required')
        for label in('before','after'):
            verify_full_state(data,post[label],backend.source,allow_cleanup=True);require(mixed.same(post[label],saved),'PostCL changed exact saved raw state')
        r['CL_preservation']=legacy.compare_cl(backend.parse_cl(data['preCL']),backend.parse_cl(post),data['preCL']['expected_generated_operations'],rows,[data['selected_ids'][0]])
        r['final_capture_source']='postCL.after';backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,partial_result_saved_verified=True,wall_generation_succeeded=False,reason='POSITIVE_FLOOR_SAVED_AND_OLD_CL_PRESERVED_WALL_EMPTY_NO_REPLAY');journal.persist()
    except Exception as exc:
        r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,partial_result_saved_verified=False,runtime_unchanged=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_error=_error(exc),readback_verified=False,partial_result_saved_verified=False,runtime_unchanged=False)
        journal.persist()
    return r

def revoke_runtime(r,error):
    # Preserve successful Save facts; revoke only overall verification.
    import json
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,partial_result_saved_verified=False)
    owned=False
    try:
        path=Path(r['receipt_path']);prior=json.loads(path.read_text(encoding='utf8'))
        require(prior.get('scope')==SCOPE and exact(prior.get('failure_receipt_pin'),r['failure_receipt_pin']),'Only owned partial recovery receipt may be revoked');owned=True
        marker=None
        if r.get('marker_created')is True:
            marker_path=Path(r['dispatch_marker_path']);marker=json.loads(marker_path.read_text(encoding='utf8'))
            require(marker.get('scope')==SCOPE and exact(marker.get('failure_receipt_pin'),r['failure_receipt_pin'])and Path(marker.get('receipt_path','')).resolve()==path.resolve(),'Only owned partial recovery marker may be updated')
        _write_receipt(path,r)
        if marker is not None:
            marker.update(status=r['status'],phase=r['phase'],receipt_sha256=_file_hash(path));_write_receipt(marker_path,marker)
    except Exception as exc:
        r['runtime_receipt_update_error']=_error(exc)
        if owned:_write_receipt(Path(r['receipt_path']),r)
    return r

def dispatch(sw,clsid,tlb,request,*,runtime_check,_prepared=None,_backend_factory=None):
    prepared=_prepare_invocation(request,runtime_check=runtime_check)if _prepared is None else _prepared;v,data,marker=_consume(prepared,request,runtime_check)
    require(data['addin_clsid'].casefold()==clsid.casefold(),'Exact inherited CAM registration required');generation.legacy.preflight(tlb);generation.authority.config.reader.preflight(tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',request=deepcopy(request),receipt_path=v['receipt_path'],dispatch_marker_path=str(marker),failure_receipt_pin=data['failure_pin'],historical_marker_pin=data['old_marker_pin'],configuration_receipt_pin=data['loaded']['pin'],evidence_pins=data['pins'],source_before_sha256=v['expected_source_sha256'],selected_operation_native_ids=data['selected_ids'],positive_generated_operation_native_ids=[data['selected_ids'][0]],failed_empty_operation_native_id=data['selected_ids'][1],target_observations={},draft_observations={},native_read_count=0,actions={},captures=[],receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,GTP_attempted=False,GTP_replayed=False,GOP_attempted=False,AFR_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,operation_creation_attempted=False,save_attempted=False,CL_export_attempted=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,partial_result_saved_verified=False,runtime_unchanged=False,automatic_replay=False,automatic_rollback=False,world_geometry_verified=False,production_qualified=False,reopen_persistence_verified=False)
    class ProgressJournal(Journal):
        progress_created=False
        def persist(self):
            super().persist()
            if self.created:_write_receipt(Path(v['progress_path']),dict(scope=SCOPE,status=r.get('status'),phase=r.get('phase'),receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),native_dispatch_pending=r.get('native_dispatch_pending',False)),create=not self.progress_created);self.progress_created=True
    journal=ProgressJournal(v['receipt_path'],marker,r)
    if _backend_factory is None:
        from scripts.sw_cam_partial_floor_wall_generation_context import Context
        _backend_factory=Context
    backend=_backend_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);result=run_once(backend,journal,data,v)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result
