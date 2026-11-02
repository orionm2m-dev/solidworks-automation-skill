"""Adopt exact completed GTP4 and save/export once; no setters, GTP or NC writes.

Only eight NC floats may be one adjacent IEEE754 value from fixed 7100/35
anchors. Raw observations remain unchanged; a separate comparison projection
is passed to the existing exact one-save engine. No cumulative tolerance.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,math
from scripts import sw_cam_local_serial_optimization as opt
from scripts import sw_cam_saved18_serial_completed as completed
from scripts.sw_cam import _error
common,group,require=opt.common,opt.group,opt.require
SCOPE='GENERATED_LOCAL_FOUR_ONE_ULP_SAVE_CL_V1'
ACTION='save_generated_local_ulp'
ACK='adopt_verified_gtp4_nc8_one_ulp_save1_export18_no_setter_no_gtp_no_nc_restore'
OPT_SHA='c3a16727d9734c79d3caf00d86e381c9706cd2507a13155c0f4e0c8bee0d7593'
PRIOR_SHA='9c9cf9dc5dbc792ec64e1f8ffc34f6c6f512f7916404d89a25acf91922612fc3'
IDS=(344,346,348,350)
COUNTS={344:[2341],346:[46],348:[2218],350:[46]}
ANCHORS={'GetSpndlSpeed':7100.0,'XYFeed':35.0}
PARAMS={'process_id','expected_document_path','expected_source_sha256','optimizer_receipt_path','optimizer_receipt_sha256','optimizer_request_path','optimizer_request_sha256','module_sha256','receipt_path','saved_cl_path','acknowledgement'}

def forbidden(*args,**kwargs):raise ValueError('Only Save1 and CL1; setters/GTP/NC mutation forbidden')

class NativeBackend(opt.native.NativeBackend):
    insert=assign=set_field=set_nc=generate=forbidden

class Journal(opt.Journal):
    def entry(self,name):
        require(name=='SaveActiveDocument','Only one Save action allowed')
        return super().entry(name)
    def _marker_state(self):
        value=super()._marker_state();value.update(scope=SCOPE,optimizer_receipt_pin=self.report['optimizer_receipt_pin']);return value

def marker_path(p):
    identity='\0'.join((SCOPE,common._key(p['expected_document_path']),p['expected_source_sha256'],p['optimizer_receipt_sha256']))
    return common.local_evidence_root()/('generated_local_ulp_save_'+hashlib.sha256(identity.encode()).hexdigest()+'.json')

def projection(snapshot,reference=None,*,initial=False):
    """Return only a comparison copy; raw snapshots are never modified."""
    value=deepcopy(snapshot);rows={r['operation_native_id']:r for r in value['parameters']}
    require(len(rows)==len(value['parameters'])==12 and set(IDS)<=set(rows),'Exact12 unique parameter groups required')
    changes=[]
    for oid in IDS:
        nc=rows[oid]['nc']['feeds_compensation']
        for key,anchor in ANCHORS.items():
            raw=nc[key]
            require(type(raw)is float and math.isfinite(raw),'Finite strict float NC value required')
            wanted=math.nextafter(anchor,math.inf)
            require(raw==wanted if initial else raw in (math.nextafter(anchor,-math.inf),anchor,wanted),'NC must remain at fixed nominal anchor or one adjacent float; no cumulative drift')
            changes.append(dict(operation_native_id=oid,field=key,anchor=anchor,raw=raw,raw_hex=raw.hex(),anchor_hex=anchor.hex(),ULP_distance=0 if raw==anchor else 1))
            nc[key]=anchor
    if reference is not None:require(group.exact(value,reference),'A non-whitelisted field, operation or path changed')
    return value,dict(scope='EIGHT_NC_FIXED_ANCHOR_ONE_ULP_COMPARISON',raw_preserved=True,projection_only=True,anchor_policy='fixed nominal 7100 and35, at most one nextafter step in either direction',fields=changes)

def adopt(r,loaded,recipe):
    require(r.get('scope')==opt.SCOPE and r.get('status')=='uncertain'and r.get('phase')=='finished','Exact finished optimizer stop required')
    require(r['module_pin']==common._pin(opt.__file__)and r['module_pin']['sha256']==OPT_SHA,'Executed optimizer producer must remain unchanged')
    require(r['native_dispatch_pending']is False and r['model_saved']is False and r['readback_verified']is False and r['cleanup_session_active']is False,'No pending dispatch or Save may be adopted')
    for key in ('save_stage','saved','saved_cl','source_transition','saved_checkpoint','cleanup_issue','terminal_issue'):
        require(key not in r,'Optimizer reached Save/export or unresolved cleanup')
    for key in ('operation_creation_attempted','tool_assignment_attempted','automatic_retry','automatic_rollback','physical_cutting_conditions_qualified','production_qualified','geometry_accepted','persistence_after_reopen_verified'):
        require(r[key]is False,'Forbidden prior action or qualification')
    require(r['GTP_attempted']is True and r['parameter_setter_attempted']is True,'Completed original settings/GTP required')
    opt.prior.clean_events(r)
    require(group.exact(r['ownership'],loaded['ownership'])and r['source_sha256']==loaded['source_sha256']and common._key(r['source_path'])==common._key(loaded['guide_parameters']['document']['path']),'Original owner/source/document differs')
    require(group.exact(r['before'],loaded['current_snapshot'])and group.exact(r['plan'],recipe)and group.exact(r['learned_targets'],loaded['deep_targets'])and r['actual_new_ids']==list(IDS),'Exact saved baseline/plan/targets required')
    targets=loaded['deep_targets'];opt.fields.validate_plan(recipe,targets,r['before'])
    require(group.exact(opt.fields.verify_configured(r['before'],r['configured'],recipe),r['configuration_verification']),'Original configured proof differs')
    require(list(r['actions'])==opt.fields.action_names(targets)[:-1]and len(r['actions'])==16,'Exactly12 settings and4GTP, no Save required')
    for action in r['actions'].values():
        opt.configured.verified_action(action)
        require(action['attempted']is True and action['returned']is True and action['native_return']==dict(python_type='int',value_recorded=True,value=0),'Actual strict0 action required')
    plans={v['operation_native_id']:v for v in recipe['rows']}
    for target in targets:
        oid=target['operation_native_id'];wanted=opt.fields.desired_values(plans[oid])
        for spec in opt.fields.specs(target):require(group.exact(r['actions'][str(oid)+':'+spec[0]]['observed'],wanted[spec[0]]),'Original setter readback differs')
        outcome=r['actions']['GTP:'+str(oid)]['observed'];opt.generation.status_contract(outcome,target,True)
        require(outcome['record_counts']==COUNTS[oid],'Exact completed GTP count differs')
    require({int(k):v for k,v in r['completed_gtp_counts'].items()}==COUNTS,'All4 completed native counts required')
    require(group.exact(r['feed_policy'],{t['key']:[]for t in targets}),'Original NC policy changed')
    canonical,proof=projection(r['generated'],initial=True)
    for row in r['configured']['parameters']:
        if row['operation_native_id']in IDS:
            for key,anchor in ANCHORS.items():require(type(row['nc']['feeds_compensation'][key])is float and row['nc']['feeds_compensation'][key]==anchor,'Configured nominal anchor differs')
    generation_proof=opt.fields.verify_regenerated(r['configured'],canonical,targets,COUNTS)
    require(group.exact(opt.describe_nc_drift(r['configured'],r['generated'],targets,COUNTS),r['nc_restore_candidate']),'Original diagnostic must contain only these8 differences')
    require(len(r['nc_restore_candidate']['changes'])==8,'Exactly8 original changes required')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start']and r['phase_proof_checks'][0]['verified']is True,'Original stop must precede Save')
    return dict(canonical_generated=canonical,original_raw_generated=deepcopy(r['generated']),original_roundoff=proof,generation_verification=generation_proof,counts=deepcopy(COUNTS))

def prepare(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact save continuation action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS and p['acknowledgement']==ACK,'Exact bounded save continuation fields required')
    require(type(p['process_id'])is int and p['process_id']>0,'Strict owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):opt.prior._sha(value)
    require(p['module_sha256']==opt.prior._file_hash(__file__)and common._pin(opt.__file__)['sha256']==OPT_SHA and p['optimizer_receipt_sha256']==PRIOR_SHA,'Exact new packet and immutable executed authority required')
    r,rpin=opt.prior.read_json_pin(p['optimizer_receipt_path'],p['optimizer_receipt_sha256'],limit=4*1024*1024)
    original,requestpin=opt.prior.read_json_pin(p['optimizer_request_path'],p['optimizer_request_sha256'])
    require(original['action']==opt.ACTION and set(original['params'])==opt.PARAMS,'Exact original sealed optimizer request required')
    oldp=deepcopy(r['request']);oldp.pop('expected_configuration')
    require(group.exact(original['params'],oldp),'Original request changed')
    l,q,_,extra=completed.load_completed_rebind(oldp['rebind_receipt_path'],oldp['rebind_receipt_sha256'],check_current=True)
    require(p['process_id']==l['ownership']['process_id']and p['expected_source_sha256']==l['source_sha256']and common._key(p['expected_document_path'])==common._key(l['guide_parameters']['document']['path'])and l['guide_parameters']['document']['needs_save']is True,'Exact observed dirty owner/source required')
    recipe,recipepin=opt.prior.read_json_pin(oldp['recipe_path'],oldp['recipe_sha256'])
    qpin=common._pin(oldp['qualified_receipt_path']);require(qpin['sha256']==oldp['qualified_receipt_sha256']==l['qualified_authority_pin']['sha256']and common._key(qpin['path'])==common._key(l['qualified_authority_pin']['path']),'Original saved authority differs')
    rebindpin=common._pin(oldp['rebind_receipt_path']);require(rebindpin['sha256']==oldp['rebind_receipt_sha256'],'Rebind receipt changed')
    for key,value in [('qualified_receipt_pin',qpin),('rebind_receipt_pin',rebindpin),('recipe_pin',recipepin)]:require(group.exact(r[key],value),'Original pinned input differs')
    proof=adopt(r,l,recipe)
    oldmark=opt.marker_path(oldp);markpin=common._pin(oldmark);marker=opt.prior.read_json_pin(str(oldmark),markpin['sha256'])[0]
    expected=opt.Journal(deepcopy(r),Path(r['request']['receipt_path']),oldmark)._marker_state();require(group.exact(marker,expected),'Original terminal marker differs')
    common._check(r['live_pins']);common._check(r['phase_proof_pins'])
    l.update(optimization=dict(snapshot=deepcopy(r['generated']),targets=deepcopy(l['deep_targets']),prior_cl=deepcopy(q['prior_cl'])),optimization_plan=recipe,qualified_receipt_pin=qpin,rebind_receipt_pin=rebindpin,recipe_pin=recipepin,ulp_continuation=proof,optimizer_receipt_pin=rpin)
    extras=common._merge(extra,[rpin,requestpin,recipepin,qpin,rebindpin,markpin,common._pin(completed.__file__),common._pin(__file__)],r['live_pins'],r['phase_proof_pins'])
    opt.partition_pins(l,extras)
    own=common._pin(__file__);l['pins']=common._merge(l['pins'],[own]);l['phase_proof_pins']=[v for v in l['phase_proof_pins']if common._key(v['path'])!=common._key(own['path'])]
    require(len(l['pins'])<=63,'Save continuation live closure plus source exceeds64')
    l['pin_partition'].update(live_file_count=len(l['pins']),maximum_with_source=len(l['pins'])+1,phase_proof_count=len(l['phase_proof_pins']),save_only_continuation=True)
    registration=common.discover_export_registration(l,l['registration']['clsid']);require(group.exact(registration,l['registration']),'CAM registration changed')
    tlb=str(Path(registration['addin_path']).parent/'camworks.tlb');p['expected_configuration']=l['guide_parameters']['configuration']['sw_configuration_name']
    l['native_guard_preflight']=opt.prior.guard_reuse.guard_constructor_preflight(p,l,tlb)
    out=common._local_receipt(p['receipt_path']);mark=marker_path(p);cl=opt.cl._fresh_path(p['saved_cl_path'])
    protected={common._key(v['path'])for v in l['pins']+l['phase_proof_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in (out,mark,cl)})==3,'Distinct continuation outputs required')
    for value in (out,mark,cl):require(not value.exists()and not value.is_symlink()and common._key(value)not in protected,'Existing output/marker or evidence alias forbids replay')
    common._check(l['pins']);common._check(l['phase_proof_pins'])
    return p,l,registration,tlb,out,mark

def run_once(backend,journal,loaded):
    require(not journal.created and not journal.claimed and not journal.receipt.exists()and not journal.marker.exists(),'Fresh unclaimed continuation required')
    r=journal.report;expected=loaded['ulp_continuation']['canonical_generated'];backend.learned=deepcopy(loaded['optimization']['targets'])
    r.update(status='error',phase='preflight',actions={},learned_targets=deepcopy(backend.learned),actual_new_ids=list(IDS),mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,GTP_attempted=False,model_saved=False,readback_verified=False,automatic_retry=False,automatic_rollback=False,operation_creation_attempted=False,tool_assignment_attempted=False,parameter_setter_attempted=False,NC_restore_attempted=False,production_qualified=False,geometry_accepted=False,persistence_after_reopen_verified=False,continuation_ready=False,adopted_GTP_complete=True,raw_NC_values_preserved=True)
    try:
        journal.create();backend.start();r['before']=backend.capture_snapshot('before_save_existing_generated',full=True)
        projected,r['before_roundoff']=projection(r['before'],expected);journal.persist()
        r['save_stage']={'comparison_projection_only':True,'raw_snapshots_keys':['before','saved']};journal.entry('SaveActiveDocument')
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(projected)
            r['saved']=backend.capture_snapshot('saved_existing_generated',full=True)
            value,r['saved_roundoff']=projection(r['saved'],expected);journal.persist();return value
        def verify(value):require(group.exact(value,expected),'Projected complete21/12 changed')
        def save():
            value=backend.save();a=r['actions']['SaveActiveDocument'];require(a['attempted']is True,'Save bypassed pending')
            a.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Saved source did not advance');r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        opt.config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['saved_cl_verification']=opt.cl.verify_saved(loaded['optimization']['prior_cl'],r['saved_cl'],backend.learned,r['saved'])
        backend.finish();r.update(status='saved_generated_local_ulp_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False,continuation_ready=False)
    finally:
        try:opt.generation.close_checked(backend,r)
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        journal.persist()
    return r

def validate_completed(r,l):
    require(r['scope']==SCOPE and r['status']=='saved_generated_local_ulp_review_required'and r['phase']=='finished','Completed save-only receipt required')
    require(r['readback_verified']is True and r['model_saved']is True and r['continuation_ready']is True and r['native_dispatch_pending']is False,'Successful nonpending Save/CL required')
    require(not any(r.get(k)for k in ('issue','cleanup_issue','terminal_issue')),'Unresolved continuation state')
    opt.prior.clean_events(r)
    for key in ('GTP_attempted','parameter_setter_attempted','NC_restore_attempted','operation_creation_attempted','tool_assignment_attempted','automatic_retry','automatic_rollback','production_qualified','geometry_accepted','persistence_after_reopen_verified'):require(r[key]is False,'Forbidden continuation action or claim')
    require(group.exact(r['optimizer_receipt_pin'],l['optimizer_receipt_pin'])and group.exact(r['ownership'],l['ownership'])and r['source_sha256']==l['source_sha256']and group.exact(r['learned_targets'],l['optimization']['targets']),'Continuation authority differs')
    require(list(r['actions'])==['SaveActiveDocument'],'Exactly one Save and no other action required')
    action=r['actions']['SaveActiveDocument'];opt.configured.verified_action(action)
    require(action['attempted']is True and action['native_return']==dict(python_type='int',value_recorded=True,value=0),'One actual strict0 Save required')
    reference=l['ulp_continuation']['canonical_generated']
    for key in ('before','saved'):
        projected,proof=projection(r[key],reference);require(group.exact(proof,r[key+'_roundoff']),'Raw bounded roundoff evidence changed')
        require(group.exact(projected,r['save_stage']['before'if key=='before'else'after']),'Save comparison projection differs')
    stage=r['save_stage'];require(stage['save_readback_verified']is True and stage['save_pending']is False and stage['native_return_type']=='int'and type(stage['native_return_value'])is int and stage['native_return_value']==0 and stage['comparison_projection_only']is True,'Exact checked one-Save engine required')
    new=opt.prior._sha(r['saved_source_sha256']);require(new!=r['source_sha256']and action['observed']==new and stage['saved_file_sha256']==new,'Changed saved source required')
    transition=r['source_transition'];document=deepcopy(l['guide_parameters']['document']);require(document['needs_save']is True,'Explicit dirty input required');document['needs_save']=False
    require(transition['source_before_sha256']==r['source_sha256']and transition['source_after_sha256']==new and type(transition['strict_save_return'])is int and transition['strict_save_return']==0 and group.exact(transition['document'],document),'Only verified Save may change dirty to clean')
    proof=opt.cl.verify_saved(l['optimization']['prior_cl'],r['saved_cl'],r['learned_targets'],r['saved']);require(group.exact(proof,r['saved_cl_verification'])and r['saved_cl']['source_sha256']==new,'Saved18 export/protected14 differs')
    require([v['phase']for v in r['phase_proof_checks']]==['before_native_start','before_save','after_export_and_cleanup']and all(v['verified']is True for v in r['phase_proof_checks']),'Required save phase proofs missing')
    return dict(status='saved_generated_local_ulp_authority_verified',operations=21,parameters=12,paths=18,adopted_generated_paths=4,new_GTP_calls=0,Save=1,protected_prior_paths=14,source_sha256=new,raw_NC_values_preserved=True,geometry_accepted=False,production_qualified=False)

def dispatch_request(request,*,validate_only=False):
    p,l,registration,tlb,out,mark=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,allowed_actions='Save1+CL18; no settings/GTP/NC',native_guard_preflight=l['native_guard_preflight'],original_roundoff=l['ulp_continuation']['original_roundoff'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=2,process_id=p['process_id']):
        common._check(l['pins']);common._check(l['phase_proof_pins']);sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,request=deepcopy(p),module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=deepcopy(l['ownership']),live_pins=deepcopy(l['pins']),phase_proof_pins=deepcopy(l['phase_proof_pins']),pin_partition=deepcopy(l['pin_partition']),tool_dimensions=deepcopy(l['local_tool_dimensions']),qualified_receipt_pin=deepcopy(l['qualified_receipt_pin']),rebind_receipt_pin=deepcopy(l['rebind_receipt_pin']),recipe_pin=deepcopy(l['recipe_pin']),optimizer_receipt_pin=deepcopy(l['optimizer_receipt_pin']),adopted_proof=deepcopy(l['ulp_continuation']))
        j=Journal(r,out,mark);b=NativeBackend(l,p,sw,registration['clsid'],tlb,r,j.persist,before_generate=forbidden,exporter=opt.cl.export_saved)
        run_once(b,j,l)
        if r['readback_verified']is True:
            try:
                r['terminal_verification']=validate_completed(r,l)
                r['saved_checkpoint']=dict(source_path=p['expected_document_path'],source_sha256=r['saved_source_sha256'],document=deepcopy(r['source_transition']['document']),configuration=deepcopy(l['guide_parameters']['configuration']),snapshot=deepcopy(r['saved']),saved_cl=deepcopy(r['saved_cl']),learned_targets=deepcopy(r['learned_targets']),tool_catalogue=deepcopy(l['serial_flat_catalogue']),tool_dimensions=deepcopy(l['local_tool_dimensions']),current_counts=dict(operations=21,parameters=12,paths=18,tools=21),GTP_complete=True,nominal_geometry_accepted=False,production_qualified=False)
            except Exception as exc:r.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc))
            j.persist()
        return r
