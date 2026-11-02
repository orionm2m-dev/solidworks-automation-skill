"""Complete the remaining mixed pocket after exact read-only adoption of feature339.

Keep both observed CAM contours in their actual construction plane. Header depth
and axis imply a nominal floor; only later actual CL may qualify cutting depth.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_mixed_root_resume as previous
from scripts import sw_cam_mixed_feature_diagnostic as diagnostic
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error

common,group,cl=previous.common,previous.group,previous.cl
authority,base=previous.authority,previous.base
config,generation=previous.config,previous.generation
_file_hash=previous._file_hash
mixed=previous.mixed
verify_headers,verify_cad=previous.verify_headers,previous.verify_cad
SCOPE='EXISTING_FIRST_NATIVE_POCKET_REMAINING_MIXED_POCKET_V1'
ACTION='finish_remaining_mixed_root_pocket'


def verify_pocket(observed,spec,*,native_id,owner=69):
    h=observed['header']
    require(type(native_id)is int and native_id>0 and h['native_id']==native_id and observed['owner_setup_native_id']==owner,'Exact pocket identity/owner required')
    require(h['volume_type']==2 and h['suppressed']is False and abs(h['depth_native']-3.4)<=1e-8,'Active pocket depth3.4 required')
    require(math.dist(h['axis_native'],[0,0,-1])<=1e-8 and abs(h['start_native'][2]-10.9)<=1e-5,'Actual construction plane and axis differ')
    require(type(h['bounds_native'])is list and len(h['bounds_native'])==3 and abs(h['bounds_native'][2]-3.4)<=1e-8,'Independent native depth extent differs')
    require(type(observed['island_count'])is int and observed['island_count']==0,'No islands allowed')
    mapping={}
    for label in ('top','bottom'):
        mapping[label]=mixed.match_rows(spec['profile']['segments'],previous.contour_rows(observed['contours'][label]),1e-8)
    return dict(native_id=native_id,owner_setup_native_id=owner,construction_plane_world_z_mm=10.9,
      native_top_contour_world_z_mm=10.9,native_bottom_contour_world_z_mm=10.9,
      native_planar_top_bottom_curves_verified=True,native_depth_scalar_mm=3.4,native_depth_bounds_mm=3.4,
      native_axis=[0,0,-1],derived_nominal_floor_world_z_mm=7.5,
      physical_floor_verified=False,actual_CL_depth_verification_required=True,segment_mapping=mapping)


def diagnostic_contract(raw,failed):
    diagnostic.failed_contract(failed,339)
    require(raw.get('scope')==diagnostic.SCOPE and raw.get('module_pin')==common._pin(diagnostic.__file__),'Exact raw diagnostic producer required')
    require(raw.get('status')=='raw_feature_observed'and raw.get('phase')=='finished'and raw.get('cleanup_session_active')is False,'Completed disconnected raw diagnostic required')
    require(raw.get('raw_feature_read_complete')is True and raw.get('readback_verified')is True and raw.get('feature_geometry_accepted')is False,'Complete raw read without prior geometric acceptance required')
    require(raw.get('actions')=={} and all(raw.get(k)is False for k in ('mutation_attempted','save_attempted','GTP_attempted','GOP_attempted')),'Read-only diagnostic required')
    require(group.exact(raw['ownership'],failed['ownership'])and raw['source_sha256']==failed['source_sha256']and common._key(raw['source_path'])==common._key(failed['source_path']),'Diagnostic source/owner differs')
    require(group.exact(raw['before_binding'],failed['before']['binding'])and group.exact(raw['after_binding'],raw['before_binding']),'Diagnostic protected route differs')
    verify_cad(failed['before_cad'],raw['before_cad'],[]);verify_cad(raw['before_cad'],raw['after_cad'],[])
    verify_headers(failed['before_features'],raw['headers'],[339])
    require(raw['before_cad']['needs_save']is True and raw['after_cad']['needs_save']is True,'Proved dirty first feature state required')
    return verify_pocket(raw['raw_feature'],failed['profile_specs'][0],native_id=339)


class Journal(group.GroupJournal):
    def _marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],source_sha256=r['source_sha256'],receipt_path=str(self.receipt),status=r['status'],phase=r['phase'],actions=deepcopy(r['actions']),new_feature_ids=r.get('new_feature_ids',[]),native_dispatch_pending=r.get('native_dispatch_pending',False),automatic_replay=False)


class NativeBackend(previous.NativeBackend):
    def create_sketch(self,spec,pending):
        require(group.exact(spec,self.loaded['root_pocket_specs'][1]),'Only the remaining second sketch may be created')
        return super().create_sketch(spec,pending)
    def create_pocket(self,spec,pending):
        require(group.exact(spec,self.loaded['root_pocket_specs'][1]),'Existing first native pocket must never be recreated')
        return super().create_pocket(spec,pending)
    def adopt_first_sketch(self,*a):raise ValueError('The proved existing sketch must not be reconstructed or re-adopted')
    def feature(self,native_id):
        self.boundary()
        with self.ctx.guard()as g:
            doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');found=g.read(doc,'GetCWObjectFromID',1,native_id)
            require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Exact feature lookup required')
            header,raw=previous.read_header(found[0],doc,g.read,g.typed,69);mill=g.typed(raw,'ICWMillFeature');count=g.read(mill,'IGetIslandCount')
            result=dict(owner_setup_native_id=69,header=header,island_count=count,contours={})
            self.report.setdefault('feature_observations',[]).append(result);self.persist()
            require(header['native_id']==native_id,'Exact actual feature ID differs')
            budget=dict(curves=0,chains=0,islands=0)
            for name,method in(('top','IGetTopSegChain'),('bottom','IGetBottomSegChain')):
                partial={};result['contours'][name]=partial;self.persist()
                try:previous.inventory.read_segment_chains(mill,method,read=g.read,typed=g.typed,diagnostic={'state':partial},budget=budget)
                finally:self.persist()
        return result


_returned=previous._returned


def run_backend(backend,journal,loaded,specs):
    r=journal.report;r.update(status='error',phase='preflight',actions={},new_feature_ids=[],mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,save_attempted=False,model_saved=False,readback_verified=False,continuation_ready=False,GOP_attempted=False,GTP_attempted=False,SetTool_attempted=False,operation_creation_attempted=False,tool_creation_attempted=False,automatic_retry=False,automatic_rollback=False,production_qualified=False,persistence_after_reopen_verified=False)
    try:
        journal.create();backend.start();backend.proof_boundary()
        failed=loaded['first_native_pocket_failure'];raw=loaded['first_native_pocket_diagnostic']
        r['before']=deepcopy(failed['before']);r['baseline_reused_from_failure_pin']=deepcopy(loaded['first_native_pocket_failure_pin'])
        r['before_binding']=backend.capture_binding('before_remaining');journal.persist()
        require(group.exact(r['before_binding'],r['before']['binding']),'Known protected route changed')
        r['before_tool_ids']=backend.catalogue();require(r['before_tool_ids']==loaded['tool_catalogue_ids'],'Saved tool catalogue changed')
        r['before_features']=deepcopy(failed['before_features']);r['adoption_headers']=backend.headers();journal.persist()
        require(group.exact(r['adoption_headers'],raw['headers']),'Proved feature339 inventory changed')
        r['before_cad']=backend.cad(specs[0])[0];journal.persist();verify_cad(raw['after_cad'],r['before_cad'],[])
        require(r['before_cad']['needs_save']is True,'Exact existing dirty first feature required')
        r['created_cad_features']=[];r['new_feature_ids']=[339];r['new_features']=[deepcopy(raw['raw_feature'])]
        r['adopted_first_sketch']=deepcopy(failed['adopted_first_sketch'])
        r['adopted_first_pocket']=dict(native_id=339,read_only=True,recreated=False,raw_diagnostic_pin=deepcopy(loaded['first_native_pocket_diagnostic_pin']),observed=verify_pocket(raw['raw_feature'],specs[0],native_id=339));journal.persist()
        spec=specs[1];name='CreateSketch:1';journal.entry(name)
        result=backend.create_sketch(spec,lambda:journal.pending(name));r['created_cad_features']+=result['created_features'];_returned(journal,name,result)
        name='CreatePocket:1';journal.entry(name)
        native_id=backend.create_pocket(spec,lambda:journal.pending(name))
        require(native_id not in [x['header']['native_id']for x in raw['headers']],'Returned duplicate feature ID')
        r['new_feature_ids'].append(native_id);journal.persist()
        observed=backend.feature(native_id);r['new_features'].append(observed);journal.persist()
        checked=verify_pocket(observed,spec,native_id=native_id);_returned(journal,name,checked)
        require(group.exact(backend.capture_binding('after_remaining_pocket'),r['before']['binding']),'Remaining pocket changed protected route')
        r['after_features']=backend.headers();r['after_cad']=backend.cad(specs[0])[0]
        verify_headers(r['before_features'],r['after_features'],r['new_feature_ids']);verify_cad(r['before_cad'],r['after_cad'],r['created_cad_features'])
        r['configured']=backend.capture_snapshot('configured',full=True);require(group.exact(r['configured'],r['before']),'Feature creation changed old seventeen/eight state')
        backend.proof_boundary();r['save_stage']={};journal.entry('SaveActiveDocument');r['save_attempted']=True
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(r['configured'])
            r['saved']=backend.capture_snapshot('saved',full=True);return r['saved']
        def verify(value):require(group.exact(value,r['configured']),'Save changed protected parameters/bindings')
        def save():
            value=backend.save();row=r['actions']['SaveActiveDocument'];require(row['attempted']is True,'Save pending marker missing')
            row.update(returned=True,native_dispatch_pending=False,native_return=group.return_observation(value));r.update(native_call_returned=True,native_dispatch_pending=False);journal.persist();return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['source_sha256'],'Save did not advance source')
            r.update(saved_source_sha256=value,model_saved=True);journal.persist();return value
        config.save_core.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        journal.verified('SaveActiveDocument',r['saved_source_sha256'])
        r['saved_features']=backend.headers();require(group.exact(r['saved_features'],r['after_features']),'Save changed feature headers')
        r['saved_new_features']=[backend.feature(i)for i in r['new_feature_ids']]
        require(group.exact(r['saved_new_features'],r['new_features']),'Save changed full native contours')
        r['saved_cad']=backend.cad(specs[0])[0];verify_cad(r['before_cad'],r['saved_cad'],r['created_cad_features'])
        r['saved_tool_ids']=backend.catalogue();require(r['saved_tool_ids']==r['before_tool_ids'],'Feature-only packet changed tool catalogue')
        r['saved_cl']=backend.export('saved',r['saved']['binding']);r['protected_cl']=cl.verify_all(loaded['generated']['saved_cl'],r['saved_cl'])
        backend.proof_boundary();backend.finish()
        r.update(status='saved_remaining_mixed_pocket_review_required',phase='finished',readback_verified=True,continuation_ready=True)
    except Exception as exc:r.update(status='uncertain'if r['mutation_attempted']else'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False,continuation_ready=False)
    finally:
        try:generation.close_checked(backend,r)
        except Exception as exc:r.update(cleanup_issue=_error(exc),readback_verified=False,continuation_ready=False)
        try:journal.persist()
        except Exception as exc:r.update(receipt_write_error=_error(exc),continuation_ready=False)
    return r

PARAMS={'process_id','expected_document_path','expected_source_sha256','failed_receipt_path','failed_receipt_sha256','diagnostic_receipt_path','diagnostic_receipt_sha256','module_sha256','receipt_path','progress_path','saved_cl_path','acknowledgement'}
FAILURE_FIELDS=('before','before_features','adopted_first_sketch')
RAW_FIELDS=('raw_feature','headers','after_cad')


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']==ACTION,'Exact remaining-pocket action required')
    p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact bounded remaining-pocket fields required')
    require(type(p['process_id'])is int and p['process_id']>0 and p['acknowledgement']=='adopt_first_native_pocket_create_remaining_sketch_pocket_save_once_preserve17_14','Explicit remaining-only scope required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v)is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v)is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Remaining-pocket implementation changed')
    failed,fp=authority.reconciliation.read_pin(p['failed_receipt_path'],p['failed_receipt_sha256'])
    raw,rp=authority.reconciliation.read_pin(p['diagnostic_receipt_path'],p['diagnostic_receipt_sha256']);diagnostic_contract(raw,failed)
    require(raw['failed_receipt_pin']==fp,'Raw diagnostic refers to another failure')
    require(failed['ownership']['process_id']==p['process_id'] and failed['source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path'])and common._key(failed['source_path'])==common._key(p['expected_document_path']),'Exact retained owner and unchanged source required')
    loaded=deepcopy(failed['initial_context']);require(group.exact(loaded['guide_parameters']['document'],failed['current_document'])and failed['current_document']['needs_save']is True,'Proved RAM dirty document required')
    canonical=common._pin(failed['request']['receipt_path']);require(canonical['sha256']==fp['sha256'],'Failed canonical receipt changed')
    canonical_raw=common._pin(raw['request']['receipt_path']);require(canonical_raw['sha256']==rp['sha256'],'Diagnostic canonical receipt changed')
    marker0=common.local_evidence_root()/('two_mixed_root_pockets_'+group._digest(dict(scope=previous.SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.once.json')
    mp=common._pin(marker0);mv,_=authority.reconciliation.read_pin(str(marker0),mp['sha256'])
    require(group.exact(mv,previous.Journal(failed,failed['request']['receipt_path'],marker0)._marker_state()),'Old first-pocket pending marker changed')
    retired=[v for v in loaded['pins']if Path(v['path']).name=='c40-16erp412.mh'];require(len(retired)==1,'Exact external holder-file phase role required')
    # No tool/holder creation or attachment occurs; live holder getters remain pinned.
    loaded['pins']=common._merge([v for v in loaded['pins']if v not in retired],[common._pin(__file__)])
    loaded['checkpoint_pins']=common._merge(loaded['checkpoint_pins'],retired,[fp,rp,mp,canonical,canonical_raw,common._pin(diagnostic.__file__),common._pin(__file__)])
    require(len(loaded['pins'])<=63 and len(loaded['checkpoint_pins'])<=360,'Bounded active and immutable proof closures required')
    loaded['first_native_pocket_failure']={k:deepcopy(failed[k])for k in FAILURE_FIELDS}
    loaded['first_native_pocket_diagnostic']={k:deepcopy(raw[k])for k in RAW_FIELDS}
    loaded['first_native_pocket_failure_pin']=fp;loaded['first_native_pocket_diagnostic_pin']=rp
    loaded['configuration_pins']=deepcopy(loaded['checkpoint_pins'])
    require(group.exact(failed['profile_specs'],loaded['root_pocket_specs']),'Approved profile specifications changed')
    common._check(loaded['pins']);common._check(loaded['checkpoint_pins'])
    registration=loaded['root_pocket_registration'];typelib=str(Path(registration['addin_path']).parent/'camworks.tlb');require(common._pin(typelib)in loaded['pins'],'Actual native typelib differs')
    p['expected_configuration']=failed['request']['expected_configuration'];guard=base.guard_constructor_preflight(p,loaded,typelib)
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path']);output=cl._fresh_path(p['saved_cl_path'])
    marker=common.local_evidence_root()/('two_mixed_root_pockets_'+group._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha=p['expected_source_sha256']))+'.once.json')
    outputs=(receipt,progress,output,marker);protected={common._key(v['path'])for v in loaded['checkpoint_pins']}|{common._key(p['expected_document_path'])}
    require(len({common._key(v)for v in outputs})==4,'Distinct output files required')
    for path in outputs:require(not path.exists()and not path.is_symlink()and common._key(path)not in protected,'Fresh nonaliased outputs/no previous attempt required')
    for path in(receipt,progress,marker):require(path.parent.is_dir(),'Existing output parent required')
    return p,loaded,registration,typelib,failed['interface_audit'],receipt,marker,guard


def validate_terminal(r):
    require(r.get('scope')==SCOPE and r.get('module_pin')==common._pin(__file__),'Exact remaining-pocket producer required')
    require(r.get('status')=='saved_remaining_mixed_pocket_review_required'and r.get('phase')=='finished','Successful remaining-pocket terminal required')
    require(all(r.get(k)is True for k in('model_saved','readback_verified','continuation_ready'))and r.get('cleanup_session_active')is False,'Saved disconnected state required')
    require(all(r.get(k)is False for k in('GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted','automatic_retry','automatic_rollback','production_qualified')),'Feature-only scope required')
    names=['CreateSketch:1','CreatePocket:1','SaveActiveDocument'];require(list(r['actions'])==names,'Only remaining sketch, pocket and one save permitted')
    for name in names:
        v=r['actions'][name];require(v.get('attempted')is True and v.get('returned')is True and v.get('readback_verified')is True and v.get('native_dispatch_pending')is False,'Every action must be verified')
    loaded=r['initial_context'];fp=loaded['first_native_pocket_failure_pin'];rp=loaded['first_native_pocket_diagnostic_pin']
    failed,_=authority.reconciliation.read_pin(fp['path'],fp['sha256']);raw,_=authority.reconciliation.read_pin(rp['path'],rp['sha256']);first=diagnostic_contract(raw,failed)
    require(group.exact(loaded['first_native_pocket_failure'],{k:failed[k]for k in FAILURE_FIELDS})and group.exact(loaded['first_native_pocket_diagnostic'],{k:raw[k]for k in RAW_FIELDS}),'Projected adoption evidence changed')
    require(group.exact(r['ownership'],failed['ownership'])and r['source_sha256']==failed['source_sha256']and common._key(r['source_path'])==common._key(failed['source_path']),'Adopted owner/source differs')
    require(group.exact(r['profile_specs'],failed['profile_specs'])and group.exact(r['profile_specs'],loaded['root_pocket_specs']),'Approved profiles differ')
    require(r['new_feature_ids'][0]==339 and len(r['new_feature_ids'])==2 and len(set(r['new_feature_ids']))==2 and all(type(v)is int and v>0 for v in r['new_feature_ids']),'Exactly existing339 and one real new ID required')
    require(group.exact(r['adopted_first_pocket'],dict(native_id=339,read_only=True,recreated=False,raw_diagnostic_pin=rp,observed=first))and group.exact(r['adopted_first_sketch'],failed['adopted_first_sketch']),'Existing first feature/sketch adoption changed')
    require(r['baseline_reused_from_failure_pin']==fp and group.exact(r['before'],failed['before'])and group.exact(r['before'],loaded['guide_parameters']['expected_parameters']),'Reused full baseline differs')
    require(group.exact(r['before_binding'],r['before']['binding'])and group.exact(r['before'],r['configured'])and group.exact(r['configured'],r['saved']),'Protected seventeen/eight changed')
    require([x['native_id']for x in r['saved']['binding']['operations']]==list(base.OLD+base.IDS)and [x['operation_native_id']for x in r['saved']['parameters']]==[322,324,326,328,*base.IDS],'Exact seventeen/eight order required')
    require(group.exact(r['adoption_headers'],raw['headers'])and group.exact(r['before_features'],failed['before_features']),'Initial feature inventory differs')
    verify_headers(r['before_features'],r['after_features'],r['new_feature_ids']);require(group.exact(r['after_features'],r['saved_features']),'Save changed feature headers')
    require(len(r['new_features'])==2 and group.exact(r['new_features'][0],raw['raw_feature'])and group.exact(r['saved_new_features'],r['new_features']),'Saved full contours differ')
    for row,spec,nid in zip(r['saved_new_features'],r['profile_specs'],r['new_feature_ids']):verify_pocket(row,spec,native_id=nid)
    require(group.exact(r['actions']['CreatePocket:1']['observed'],verify_pocket(r['new_features'][1],r['profile_specs'][1],native_id=r['new_feature_ids'][1])),'New feature action readback differs')
    created=r['actions']['CreateSketch:1']['observed']['created_features'];require(group.exact(created,r['created_cad_features']),'CAD additions differ from action')
    spec=r['profile_specs'][1];expected_sketch=dict(name=spec['sketch_name'],type='ProfileFeature');expected_plane=dict(name=spec['plane_name'],type='RefPlane')
    require(created==[expected_sketch]or created==[expected_plane,expected_sketch],'Only remaining sketch/optional plane may be created')
    observed=r['actions']['CreateSketch:1']['observed']['readback']
    require(observed.get('arc_interval_midpoint_verified')is True and observed.get('native_rotation_direction_assumed')is False and observed.get('native_rotation_direction_qualified')is True and observed.get('underlying_curve_trim_used')is False and observed.get('native_arc_trim_basis')=='native_endpoints_rotation_and_independent_length','Actual second sketch signed arc readback required')
    mixed.match_rows(spec['profile']['segments'],observed['entities'],1e-8)
    verify_cad(raw['after_cad'],r['before_cad'],[]);verify_cad(r['before_cad'],r['after_cad'],created);verify_cad(r['before_cad'],r['saved_cad'],created)
    require(r['saved_tool_ids']==r['before_tool_ids']==loaded['tool_catalogue_ids'],'Catalogue changed')
    require(r['protected_cl']['all_fourteen_complete_streams_unchanged']is True,'Protected14CL changed')
    tr=r['source_transition'];require(tr['source_before_sha256']==r['source_sha256']and tr['source_after_sha256']==r['saved_source_sha256']and tr['strict_save_return']==0 and r['saved_source_sha256']!=r['source_sha256'],'Exact one-save source transition required')
    require(r['source_sha256']==loaded['source_sha256']and group.exact(tr['document'],loaded['root_pocket_saved_document']),'Source/document authority changed')
    require(tr['document']['needs_save']is False and r['saved_cad']['needs_save']is False,'Clean saved document required')
    from scripts.sw_cam_mill_selected_plan_evidence import clean_events
    clean_events(r)
    return r


def load_completed(path,sha,*,check_current=True):
    r,pin=authority.reconciliation.read_pin(path,sha);validate_terminal(r)
    loaded=deepcopy(r['initial_context']);common._check(loaded['checkpoint_pins']);common._check(loaded['pins'])
    require(_file_hash(loaded['root_pocket_backup_pin']['path'])==r['source_sha256'],'Historical source backup changed')
    before=loaded['guide_parameters']['expected_parameters'];require(group.exact(before,r['before']),'Terminal baseline differs from trusted initial context')
    loaded['guide_parameters'].update(document=deepcopy(r['source_transition']['document']),baseline=deepcopy(r['saved']['binding']),expected_parameters=deepcopy(r['saved']))
    loaded['source_sha256']=r['saved_source_sha256'];loaded['generated']={'saved_cl':deepcopy(r['saved_cl'])};loaded['root_pocket_native_inventory']=deepcopy(r['saved_features']);loaded['root_pocket_full_features']=deepcopy(r['saved_new_features']);loaded['root_pocket_cad']=deepcopy(r['saved_cad']);loaded['root_pocket_checkpoint_pin']=pin
    if check_current:require(_file_hash(r['source_path'])==r['saved_source_sha256'],'Current saved source changed')
    cl.verify_all(r['initial_context']['generated']['saved_cl'],r['saved_cl'])
    return loaded


def dispatch_request(request,*,validate_only=False):
    p,loaded,registration,typelib,abi,receipt,marker,guard=prepare_request(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE,live_pin_count=len(loaded['pins']),proof_pin_count=len(loaded['checkpoint_pins']),guard_constructor=guard,profile_count=2,protected_operation_count=17,protected_path_count=14,actions=['AdoptExistingPocket:339(read-only)','CreateSketch:1','CreatePocket:1','SaveActiveDocument'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts import sw_connect
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=sw_connect.connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,request=p,module_pin=common._pin(__file__),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],ownership=loaded['ownership'],profile_specs=deepcopy(loaded['root_pocket_specs']),initial_context=deepcopy(loaded),interface_audit=abi,native_guard_preflight=guard)
        journal=Journal(report,receipt,marker);backend=NativeBackend(loaded,p,sw,registration['clsid'],typelib,report,journal.persist)
        result=run_backend(backend,journal,loaded,loaded['root_pocket_specs'])
        if result.get('continuation_ready')is True:
            try:validate_terminal(result)
            except Exception as exc:result.update(status='uncertain',readback_verified=False,continuation_ready=False,terminal_issue=_error(exc));journal.persist()
        return result