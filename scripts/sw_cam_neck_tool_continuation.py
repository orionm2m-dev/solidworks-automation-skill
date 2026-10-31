"""Continue a fully recorded local neck-tool attempt with two length corrections.

The existing tool is rebound by its recorded native ID. No factory, holder
assignment, operation assignment or generation is available in this entrypoint.
Type2 is an observed stepped profile, not an implicit shoulder taper.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_neck_tool_candidate as original
from scripts.sw_cam_shared_cutter_geometry import FIELDS,INTEGER_FIELDS,values,close,number,TOL,_point
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile,check_holder_pins
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam import _error
from scripts.sw_cam_rough_firstcut import require

common,group,prior,rough=original.common,original.group,original.prior,original.rough
SCOPE='SAVED_LOCAL_NECK_TOOL_TWO_LENGTH_CONTINUATION_V1'
AUTHORITY=original.AUTHORITY
FIELD_ORDER=('ShoulderLength','ShankLength')
BASIS='native_type2_step_conservative_envelope'
FORBIDDEN=('factory_attempted','holder_assignment_attempted','assignment_attempted','GTP_attempted','GOP_attempted','TechDB_write_attempted')


def validate_target(target):
    require(type(target) is dict and set(target)=={v[0] for v in FIELDS},'Exact ten cutter fields required')
    for name,value in target.items():
        if name in INTEGER_FIELDS:require(type(value) is int,'Strict integer cutter field required')
        else:require(number(value)>0,'Positive finite cutter dimension required')
    require(target['MillToolShankType']==2 and 1<=target['NoOfFlutes']<=32,'Observed neck type2 required')
    require(0<target['ShoulderDia']<target['CutDiameter']<=target['ShankDia']
        and 0<target['EffCutlength']<=target['ShoulderLength']<target['ShankLength']<target['Protrusion']<target['OverallLen'],
        'Cutting extension, neck, full shank and seating must remain separate')
    return dict(target)


def expected_segments(target,*,shank_only=False):
    validate_target(target)
    r,n,s=target['CutDiameter']/2,target['ShoulderDia']/2,target['ShankDia']/2
    a,b,l=target['ShoulderLength'],target['ShankLength'],target['OverallLen']
    segments=[((r,0.),(r,a)),((n,a),(n,b)),((s,b),(s,l))]
    return segments[1:] if shank_only else segments


def verify_profile(profile,target,*,shank_only=False):
    segments=expected_segments(target,shank_only=shank_only)
    chains=profile.get('chains')
    require(profile.get('status')=='observed' and type(chains) is list and 1<=len(chains)<=16
        and profile.get('declared_chain_count')==len(chains),'Complete bounded native chains required')
    a,b,l,e=target['ShoulderLength'],target['ShankLength'],target['OverallLen'],target['EffCutlength']
    minimum=a if shank_only else 0.;caps=[a,b,l] if shank_only else [0.,e,a,b,l]
    coverage=[[] for _ in segments];count=0
    for chain in chains:
        curves=chain.get('curves')
        require(chain.get('read_complete') is True and type(curves) is list and chain.get('declared_curve_count')==len(curves),'Complete exact curves required')
        for curve in curves:
            count+=1
            require(count<=256 and curve.get('read_complete') is True and type(curve.get('curve_type')) is int and curve['curve_type']==0,'Only complete bounded line profiles supported')
            p,q=_point(curve['start_native']),_point(curve['end_native'])
            require(all(minimum-TOL<=z<=l+TOL for _,z in (p,q)),'Profile exceeds axial extent')
            if close(p[1],q[1]):
                z=(p[1]+q[1])/2
                require(any(close(z,c) for c in caps),'Unexpected radial edge')
                radius=target['ShankDia']/2 if z>=b-TOL else target['CutDiameter']/2 if z<=a+TOL else target['ShoulderDia']/2
                require(max(p[0],q[0])<=radius+TOL,'Radial seam exceeds stepped envelope')
                continue
            found=False
            for index,((radius,lo),(_,hi)) in enumerate(segments):
                if all(lo-TOL<=z<=hi+TOL and close(x,radius) for x,z in (p,q)):
                    coverage[index].append((max(lo,min(p[1],q[1])),min(hi,max(p[1],q[1]))));found=True;break
            require(found,'Native longitudinal profile differs from observed stepped envelope')
    for intervals,((_,lo),(_,hi)) in zip(coverage,segments):
        cursor=lo
        for start,end in sorted(intervals):
            require(start<=cursor+TOL,'Gap in native stepped silhouette');cursor=max(cursor,end)
        require(cursor>=hi-TOL,'Incomplete native stepped silhouette')
    return dict(status='PASS',raw_tolerance=TOL,curve_count=count,shank_only=shank_only,
        geometry_basis='observed_type2_step',physical_tool_identity_verified=False)


def verify_candidate(observed,recipe,holder_recipe):
    target=validate_target(recipe['target']);full=observed['full_tool'];mill=full['mill_tool']
    require(group.exact(observed['identity'],recipe['identity']),'Candidate identity differs')
    require(full.get('geometry_read_complete') is True and full.get('profile_complete') is True,'Complete tool/shank/holder required')
    require(type(full['tool_type_raw']) is int and full['tool_type_raw']==1 and type(mill['type_raw']) is int
        and mill['type_raw']==1 and type(mill['subtype_raw']) is int and mill['subtype_raw']==3 and close(mill['end_radius_native'],0.),'Flat BOTH zero-radius cutter required')
    actual=values(full)
    for name,wanted in target.items():
        require(type(actual[name]) is int and actual[name]==wanted if name in INTEGER_FIELDS else close(actual[name],wanted),'Candidate scalar differs: '+name)
    require(close(full['holder']['holder_protrusion_native'],target['Protrusion']) and
        str(Path(full['holder']['name'])).casefold()==str(Path(holder_recipe['file_path'])).casefold(),'Existing holder reference/protrusion differs')
    return dict(profile_verified=True,tool=verify_profile(full['profiles']['tool'],target),
        shank=verify_profile(full['profiles']['shank'],target,shank_only=True),
        holder=verify_holder_profile(full['profiles']['holder'],holder_recipe,target['Protrusion']),
        conservative_envelope_only=True,manufacturer_microgeometry_verified=False,
        physical_tool_identity_verified=False,physical_collet_seating_verified=False,production_qualified=False)


def failed_candidate(failed):
    reads=failed['candidate_reads']
    require(len(reads)==1 and reads[0].get('capture_complete') is True and reads[0].get('stage')=='complete'
        and reads[0]['batch'].get('read_scope_complete') is True,'One fully captured failed candidate required')
    fields={v['property']:v['actual'] for v in failed['field_readbacks']}
    return dict(full_tool=deepcopy(reads[0]['state']),identity={name:fields[name] for name in original.TEXT_FIELDS})


def validate_failed(failed):
    require(failed.get('scope')==original.SCOPE and failed.get('status')=='uncertain'
        and failed.get('readback_verified') is False and failed.get('model_saved') is False,'Recorded unsaved partial candidate required')
    require(not any(k in failed for k in ('save_stage','saved_source_sha256','cleanup_issue','terminal_issue')),'Save or unresolved cleanup cannot be inherited')
    require(all(failed.get(k) is False for k in ('assignment_attempted','GTP_attempted','GOP_attempted','TechDB_write_attempted')),'Historical tool-only scope required')
    require(type(failed['new_tool_native_id']) is int and failed['new_tool_native_id']>0,'Recorded actual candidate ID required')
    issue=failed.get('issue',{});require(issue.get('type')=='ValueError' and any(v.get('function')=='verify_profile' for v in issue.get('locations',[])), 'Expected profile mismatch required')
    m=failed['messages'];require(m.get('subscribed') is True and not any(m.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'Historical event errors forbid continuation')
    require([v['property'] for v in failed['field_readbacks']]==list(original.FIELD_ORDER)
        and all(v.get('readback_verified') is True for v in failed['field_readbacks']),'All original fields need completed direct readback')
    actions=failed['actions'];allowed={'AddNewTool3','SetFilePathForUserDefinedHolder'}|{'property:'+v for v in original.FIELD_ORDER}
    require({'AddNewTool3','SetFilePathForUserDefinedHolder'}<=set(actions)<=allowed,'Unexpected historical mutation')
    for name,row in actions.items():
        require(row.get('attempted') is True and row.get('returned') is True and row.get('pending') is False,'Unknown historical outcome cannot resume')
        if name=='AddNewTool3':require(row.get('returned_interface_pointer') is True,'Historical unique factory pointer required')
        elif name=='SetFilePathForUserDefinedHolder':require(row.get('native_return_type')=='int' and type(row.get('native_return_value')) is int and row['native_return_value']==0,'Historical holder HRESULT0 required')
        else:require(row.get('native_return_type')=='NoneType' and row.get('native_return_value') is None,'Historical property return differs')
    original.validate_recipe(failed['recipe']);check_holder_pins(failed['holder_recipe'])
    for row in failed['field_readbacks']:
        wanted=dict(failed['recipe']['target'],**failed['recipe']['identity'])[row['property']]
        require(prior.scalar_equal(row['requested'],wanted) and prior.scalar_equal(row['actual'],wanted),'Historical field readback differs')
    candidate=failed_candidate(failed)
    require(candidate['full_tool']['tool_native_id']==failed['new_tool_native_id'],'Actual complete profile belongs to another tool')
    verify_candidate(candidate,failed['recipe'],failed['holder_recipe'])
    return failed


def validate_recipe(recipe,failed):
    require(type(recipe) is dict and set(recipe)=={'target','identity','profile_basis','source_pins'} and recipe['profile_basis']==BASIS,'Exact stepped envelope proposal required')
    validate_target(recipe['target'])
    expected=deepcopy(failed['recipe']);expected['target'].update(ShoulderLength=3.,ShankLength=19.75)
    require(group.exact(recipe['identity'],expected['identity']) and group.exact(recipe['target'],expected['target']), 'Only two reviewed native lengths may change')
    require(recipe['target']['EffCutlength']==recipe['target']['ShoulderLength']==3.
        and recipe['target']['ShoulderDia']==1.95 and recipe['target']['CutDiameter']==2. and recipe['target']['ShankDia']==4.,'Reviewed serial D2 neck dimensions required')
    require(type(recipe['source_pins']) is list and 1<=len(recipe['source_pins'])<=8,'Pinned conservative enclosure evidence required')
    common._check(recipe['source_pins']);return recipe


class Journal(prior.Journal):
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE,failed_receipt_sha256=self.report['failed_receipt_pin']['sha256'])


class NativeBackend(original.NativeBackend):
    def bind_candidate(self,new_id):
        require(self.new_id is None and self.new_tool is None,'Candidate already bound')
        batch=self.batch(max_native_calls=prior.CATALOGUE_BATCH_CALLS)
        try:
            with batch:
                handles=prior._items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,prior.MAX_TOOLS)
                found={}
                for raw in handles:
                    tool=batch.typed(raw,'ICWTool');tid=_object_id(self.native['doc'],tool,batch.read)
                    require(tid not in found,'Duplicate native tool ID');found[tid]=tool
                require(new_id in found and set(found)=={v['native_id'] for v in self.report['historical_initial_observation']['tools']}|{new_id},'Exact prior18 plus recorded candidate required')
            batch.require_complete()
            self.new_id,self.new_tool=new_id,found[new_id];self.old_holders={tid:None for tid in found if tid!=new_id}
        finally:self.report['candidate_binding_batch']=batch.summary();self.persist()
    def create(self,*args):raise ValueError('Factory forbidden in continuation')
    def attach_holder(self,*args):raise ValueError('Holder assignment forbidden in continuation')
    def property(self,name,value,pending):
        require(name in FIELD_ORDER,'Only two recorded lengths may change')
        return super().property(name,value,pending)


def run_backend(backend,journal,loaded,failed,recipe,holder_recipe):
    r=journal.report;persist=journal.persist
    require(r.get('scope')==SCOPE and r.get('actions')=={} and not journal.claimed and not journal.marker.exists(),'Fresh continuation only; no replay')
    validate_failed(failed);validate_recipe(recipe,failed)
    try:
        backend.start();backend.bind_candidate(failed['new_tool_native_id'])
        initial=backend.snapshot('reconcile');r['initial_observation']=initial;persist()
        original.verify_protected(failed['initial_observation'],initial,failed['new_tool_native_id'])
        candidate=backend.candidate('reconcile');r['reconciled_candidate']=candidate;persist()
        require(group.exact(candidate,failed_candidate(failed)),'Actual candidate differs from recorded partial result')
        for name in FIELD_ORDER:
            before=backend.field(name);wanted=recipe['target'][name]
            require(prior.scalar_equal(before,failed['recipe']['target'][name]),'Exact original length required before continuation')
            row=dict(property=name,before=before,requested=wanted,readback_verified=False);r.setdefault('field_readbacks',[]).append(row);persist()
            result=backend.property(name,wanted,lambda name=name:journal.pending('property:'+name))
            journal.returned('property:'+name,result);require(result is None,'Property HRESULT wrapper result must be None')
            backend.refresh_dirty();row['actual']=backend.field(name)
            require(prior.scalar_equal(row['actual'],wanted),'Immediate corrected length readback differs')
            row['readback_verified']=True;persist()
        candidate=backend.candidate('corrected');r['configured_candidate']=candidate;persist()
        proof=verify_candidate(candidate,recipe,holder_recipe)
        configured=backend.snapshot('corrected');original.verify_protected(failed['initial_observation'],configured,failed['new_tool_native_id'])
        require(group.exact(initial['tools'],configured['tools']),'Scalar catalogue changed during length-only correction')
        r.update(candidate_qualification=proof,configured_observation=configured);persist()
        def capture(label):
            if label=='before':backend.boundary();return dict(observation=configured,candidate=candidate)
            observed=backend.snapshot('save_'+label);original.verify_protected(failed['initial_observation'],observed,failed['new_tool_native_id'])
            actual=backend.candidate('save_'+label);verify_candidate(actual,recipe,holder_recipe)
            require(group.exact(actual,candidate),'Candidate changed during Save')
            r.update(final_candidate=actual,final_observation=observed,final_state=deepcopy(backend.current_state));persist()
            return dict(observation=observed,candidate=actual)
        def verify(value):require(group.exact(value,dict(observation=configured,candidate=candidate)),'Save projection changed')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['initial_source_sha256'],'Saved tool requires new source bytes')
            r['saved_source_sha256']=value;persist();return value
        r['save_stage']={}
        prior.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        backend.finish()
        r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True,
            prior_full_profiles_reused=True,prior_full_profiles_freshly_reverified=False,
            physical_collet_seating_verified=False,production_qualified=False)
    except Exception as exc:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r.get('phase'),readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        persist()
    return r


def marker_path(source,sha,failedsha):
    return common.local_evidence_root()/('neck_tool_continue_'+prior._digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,failed_sha256=failedsha))+'.json')


PARAMS=(common.COMMON-{'acknowledge_machine_scope','checkpoint_receipt_path','checkpoint_receipt_sha256'})|{
    'failed_receipt_path','failed_receipt_sha256','recipe_path','recipe_sha256'}


def load_inputs(p):
    failed,failedpin=read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);validate_failed(failed)
    require(failed['process_id']==p['process_id'] and common._key(failed['source_path'])==common._key(p['expected_document_path'])
        and failed['initial_source_sha256']==p['expected_source_sha256']==prior._file_hash(p['expected_document_path']),'Exact same owned process and saved source required')
    common._check(failed['live_pins']);common._check(failed['offline_proof_pins']);common._check(failed['bootstrap_export_pins'])
    require(failed['module_pin']==common._pin(original.__file__),'Frozen original writer differs')
    mark,markpin=read_pin(failed['marker_pin']['path'],failed['marker_pin']['sha256'])
    require(group.exact(mark,original.Journal(failed,failed['receipt_path'],Path(markpin['path'])).marker_state()),'Exact immutable failed marker required')
    loaded,_=read_pin(failed['loaded_context_pin']['path'],failed['loaded_context_pin']['sha256'])
    require(group.exact(loaded['pins'],failed['live_pins']) and group.exact(loaded['offline_export_proof_pins'],failed['offline_proof_pins'])
        and group.exact(loaded['bootstrap_export_pins'],failed['bootstrap_export_pins']),'Original flat context closure differs')
    rough.operation_contract(loaded)
    require(group.exact(failed['initial_observation']['route'],prior.expected_route(loaded))
        and group.exact(failed['initial_observation']['tools'],rough.cl.validate_catalogue_authority(loaded)),'Original prior18/route authority differs')
    recipe,recipepin=read_pin(p['recipe_path'],p['recipe_sha256']);validate_recipe(recipe,failed)
    retired=[v for v in loaded['pins'] if Path(v['path']).name=='sw_cam_neck_cutter_geometry.py']
    require(len(retired)==1,'Exact retired implicit-taper verifier role required')
    loaded=deepcopy(loaded)
    loaded['pins']=common._merge([v for v in loaded['pins'] if v not in retired],[common._pin(__file__)])
    loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],retired,
        [failedpin,markpin,failed['loaded_context_pin'],recipepin],recipe['source_pins'])
    require(len(loaded['pins'])<=64,'Bounded continuation closure required')
    loaded['state']['document']=deepcopy(failed['current_document'])
    require(type(loaded['state']['document']['needs_save']) is bool,'Exact observed document save flag required')
    expected=deepcopy(failed['current_document']);expected['needs_save']=False
    original_context,_=read_pin(failed['loaded_context_pin']['path'],failed['loaded_context_pin']['sha256'])
    require(group.exact(expected,original_context['state']['document']),'Historical document identity changed')
    loaded['current_context_sha256']=prior._digest(group.current_projection(loaded))
    common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
    registration=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=original.audit_interfaces(typelib,loaded['generated_pin'])
    return loaded,failed,failedpin,recipe,recipepin,registration,typelib,audit


def prepare(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='continue_neck_tool','Only explicit two-length continuation allowed')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact continuation parameters required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Exact owned PID required')
    for name,value in p.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if name.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==prior._file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['message_policy']=='vendor_default','Explicit qualification request required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact CAM CLSID required')
    loaded,failed,failedpin,recipe,recipepin,registration,typelib,audit=load_inputs(p)
    marker=marker_path(p['expected_document_path'],p['expected_source_sha256'],failedpin['sha256'])
    receipt=Path(p['receipt_path']);common._local_receipt(receipt);sidecar=receipt.with_suffix('.context.json')
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']}
    protected.add(common._key(p['expected_document_path']))
    outputs=(receipt,marker,sidecar)
    require(all(v.is_absolute() and v.suffix.casefold()=='.json' and v.parent.is_dir() and not v.exists() and not v.is_symlink() for v in outputs),'Fresh continuation outputs required; no replay')
    require(len({common._key(v) for v in outputs})==3 and not protected.intersection(map(common._key,outputs)),'Protected path alias forbidden')
    return deepcopy(p),loaded,failed,failedpin,recipe,recipepin,registration,typelib,audit,marker


def make_checkpoint(r,loaded,recipe):
    return original.make_checkpoint(r,loaded,recipe)


def validate_terminal(r):
    require(r.get('scope')==SCOPE and r.get('status')=='review_required' and r.get('phase')=='finished'
        and r.get('readback_verified') is True and r.get('model_saved') is True and r.get('phase_proofs_verified') is True,'Completed continuation required')
    require(all(r.get(k) is False for k in FORBIDDEN),'Continuation exceeded two-length/save scope')
    failed,_=read_pin(r['failed_receipt_pin']['path'],r['failed_receipt_pin']['sha256']);validate_failed(failed)
    require(group.exact(r['inherited_actions'],failed['actions']) and r['new_tool_native_id']==failed['new_tool_native_id'],'Inherited tool/actions differ')
    require(set(r['actions'])=={'property:ShoulderLength','property:ShankLength','SaveActiveDocument'} and
        all(v.get('attempted') is True and v.get('returned') is True and v.get('pending') is False for v in r['actions'].values()),'Exactly two finished setters and Save required')
    for name in FIELD_ORDER:
        action=r['actions']['property:'+name];require(action['native_return_type']=='NoneType' and action['native_return_value'] is None,'Setter return differs')
    action=r['actions']['SaveActiveDocument'];require(action['native_return_type']=='int' and type(action['native_return_value']) is int and action['native_return_value']==0,'Strict Save0 required')
    require([v['property'] for v in r['field_readbacks']]==list(FIELD_ORDER) and all(v['readback_verified'] is True for v in r['field_readbacks']),'Both corrected lengths require direct readback')
    require(group.exact(r['reconciled_candidate'],failed_candidate(failed)),'Initial full profile reconciliation differs')
    validate_recipe(r['recipe'],failed)
    for row in r['field_readbacks']:
        require(prior.scalar_equal(row['before'],failed['recipe']['target'][row['property']]) and
            prior.scalar_equal(row['actual'],r['recipe']['target'][row['property']]) and prior.scalar_equal(row['requested'],row['actual']),'Correction readback differs')
    original.verify_protected(failed['initial_observation'],r['final_observation'],r['new_tool_native_id'])
    require(group.exact(r['initial_observation'],r['configured_observation']) and group.exact(r['configured_observation'],r['final_observation']),'Protected route/catalogue changed')
    require(group.exact(r['configured_candidate'],r['final_candidate']),'Corrected candidate changed at Save')
    verify_candidate(r['final_candidate'],r['recipe'],r['holder_recipe'])
    require(r['final_candidate']['full_tool']['tool_native_id']==r['new_tool_native_id'],'Final candidate ID differs')
    require(r['final_state']['document']['needs_save'] is False and r['final_state']['saved_file_sha256']==r['saved_source_sha256']
        and common._key(r['final_state']['document']['path'])==common._key(r['source_path']),'Final clean saved source binding differs')
    require(prior._digest(r['checkpoint'])==r['checkpoint_digest'],'Checkpoint digest differs')
    initial,_=read_pin(r['loaded_context_pin']['path'],r['loaded_context_pin']['sha256'])
    require(group.exact(r['checkpoint'],make_checkpoint(r,initial,r['recipe'])),'Flat checkpoint differs from terminal observations')


def execute(sw,clsid,typelib,*,p,loaded,failed,failedpin,recipe,recipepin,audit,marker):
    args={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256','qualification_only','acknowledge_disposable_copy','message_policy')}
    sidecar=Path(p['receipt_path']).with_suffix('.context.json');_write_receipt(sidecar,loaded,create=True);contextpin=common._pin(sidecar)
    r=dict(schema_version=1,scope=SCOPE,status='error',phase='prepared',source_path=p['expected_document_path'],
        initial_source_sha256=p['expected_source_sha256'],process_id=p['process_id'],receipt_path=p['receipt_path'],module_pin=common._pin(__file__),
        parent_pin=deepcopy(loaded['parent_pin']),failed_receipt_pin=failedpin,inherited_actions=deepcopy(failed['actions']),
        historical_initial_observation=deepcopy(failed['initial_observation']),new_tool_native_id=failed['new_tool_native_id'],
        recipe_pin=recipepin,recipe=deepcopy(recipe),holder_recipe=deepcopy(loaded['holder_recipe']),loaded_context_pin=contextpin,
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),
        interface_audit=audit,actions={},mutation_attempted=False,readback_verified=False,model_saved=False,phase_proofs_verified=False,
        automatic_replay=False,automatic_rollback=False,production_qualified=False,**{k:False for k in FORBIDDEN})
    _write_receipt(p['receipt_path'],r,create=True);journal=Journal(r,p['receipt_path'],marker)
    backend=NativeBackend(loaded,args,sw,clsid,typelib,r,journal.persist)
    run_backend(backend,journal,loaded,failed,recipe,loaded['holder_recipe'])
    try:
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);common._check([contextpin])
        if r['readback_verified'] is True:
            r['phase_proofs_verified']=True;r['checkpoint']=make_checkpoint(r,loaded,recipe);r['checkpoint_digest']=prior._digest(r['checkpoint']);validate_terminal(r)
    except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proofs_verified=False,terminal_issue=_error(exc))
    journal.persist()
    if journal.claimed:r['marker_pin']=common._pin(marker);journal.persist()
    return r


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest);validate_terminal(r)
    require(type(process_id) is int and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==prior._file_hash(expected_document_path),'Exact current saved continuation required')
    require(r['module_pin']==common._pin(__file__),'Frozen continuation writer differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    mark,_=read_pin(r['marker_pin']['path'],r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,r['receipt_path'],Path(r['marker_pin']['path'])).marker_state()),'Completed continuation once marker differs')
    context=deepcopy(r['checkpoint']['context']);oldparent=context['parent_pin'];oldmarker=context['group_marker_pin']
    context['pins']=common._merge([v for v in context['pins'] if common._key(v['path'])!=common._key(oldparent['path'])],[pin])
    context['offline_export_proof_pins']=common._merge(context['offline_export_proof_pins'],[oldparent,oldmarker,r['marker_pin'],r['loaded_context_pin']])
    context.update(parent_pin=pin,group_marker_pin=deepcopy(r['marker_pin']),authority_kind=AUTHORITY)
    require(len(context['pins'])<=64,'Bounded current continuation context required')
    common._check(context['pins']);common._check(context['offline_export_proof_pins']);return context


def dispatch_request(request,*,validate_only=False):
    p,loaded,failed,failedpin,recipe,recipepin,registration,typelib,audit,marker=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),
        existing_candidate_id=failed['new_tool_native_id'],new_actions=['property:ShoulderLength','property:ShankLength','SaveActiveDocument'],
        interface_audit=audit,proposal=deepcopy(recipe['target']),prior_tool_count=18)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,p=p,loaded=loaded,failed=failed,failedpin=failedpin,recipe=recipe,recipepin=recipepin,audit=audit,marker=marker)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args(argv);r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
