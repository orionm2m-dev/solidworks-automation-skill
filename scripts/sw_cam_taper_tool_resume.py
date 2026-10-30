"""Configure and save one exactly identified previously created taper tool.

No creator is reachable through the resume action. Prior baseline and creator
evidence remain immutable; current native reads and writes are counted separately.
"""
from copy import deepcopy
from pathlib import Path
import json
import math
from scripts import sw_cam_taper_tool_candidate as base
from scripts import sw_cam_taper_interfaces as taper
from scripts import sw_cam_taper_resume_evidence as evidence
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_mill_inventory import _items

group, exports = base.group, base.exports
FIELD_ORDER, STAGES = base.FIELD_ORDER, base.STAGES
verify_new_catalogue, verify_protected = base.verify_new_catalogue, base.verify_protected
scalar_equal, validate_candidate = base.scalar_equal, base.validate_candidate
SCOPE='RESUME_CREATED_TAPER_TOOL_V1'


class TaperReadBatch(base.ToolReadBatch):
    def __init__(self,*args,generated_pin,**kwargs):
        super().__init__(*args,**kwargs);self.generated_pin=generated_pin
    def typed(self,obj,name):
        if name!='ICWTaperTool':return super().typed(obj,name)
        try:
            return self._observe_read(obj,'qi',lambda:taper.query_taper_interface(
                obj,name,self.typelib_path,generated_pin=self.generated_pin))
        except BaseException:
            self._invalid=True;self._completed=False;raise


class NativeBackend(base.NativeBackend):
    def audit(self):
        value=taper.audit_taper_interface(self.typelib_path,generated_pin=self.loaded['generated_pin'])
        require(value.get('all_resolved') is True,'Exact taper interface preflight required')
        self.report['interface_audit']=value;self.interface_preflight_passed=True;self.persist()
    def start(self):
        self.interface_preflight_passed=False
        self.audit()
        super().start()
    def exact_typed(self,g,obj,name):
        if name!='ICWTaperTool':return g.typed(obj,name)
        require(self.interface_preflight_passed is True,'Interface must be audited before native QI')
        g._fast()
        result=taper.query_taper_interface(obj,name,self.typelib_path,generated_pin=self.loaded['generated_pin'])
        g._fast();return result
    def batch(self,*extra,max_native_calls=base.PROFILE_BATCH_CALLS):
        def binding():
            self.events()
            require(_member(self.native['doc'],'GetDocType')==1 and _member(self.native['machine'],'MachType')==1,
                    'Retained tool context changed')
            if self.new_tool is not None:
                require(_object_id(self.native['doc'],self.new_tool,_member)==self.new_id,'Resumed tool identity changed')
            self.events()
        return TaperReadBatch(self.sw,self.typelib_path,process_id=self.args['process_id'],
            expected_document=self.ctx.identity(),source_sha256=self.ctx.args['expected_source_sha256'],
            evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,
            check_events=self.events,retained_objects=(self.native['doc'],self.native['machine'],self.crib)+tuple(extra),
            verify_retained_binding=binding,max_native_calls=max_native_calls,generated_pin=self.loaded['generated_pin'])
    def bind_created(self,native_id):
        require(self.interface_preflight_passed is True,'Interface audit must precede resume')
        rows=self.catalogue();holders={};found=None
        batch=self.batch(max_native_calls=base.CATALOGUE_BATCH_CALLS)
        try:
            with batch:
                raw_tools=_items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,base.MAX_TOOLS)
                ids=[]
                for raw in raw_tools:
                    tool=batch.typed(raw,'ICWTool');tid=_object_id(self.native['doc'],tool,batch.read);ids.append(tid)
                    if tid==native_id:
                        require(found is None and batch.read(tool,'ToolType')==base.TOOL_TYPE,'Unique existing taper tool required')
                        found=tool
                    else:
                        holders[tid]=batch.typed(batch.read(tool,'IGetMillToolHolder'),'ICWMillToolHolder')
                require(ids==[v['native_id'] for v in rows] and found is not None,'Exact complete existing-tool binding required')
            batch.require_complete()
        finally:
            self.report['resume_binding_batch']=batch.summary();self.persist()
        self.new_id,self.new_tool,self.old_holders=native_id,found,holders
        return rows
    def create(self,*args,**kwargs):
        raise ValueError('Resume cannot create another tool')
    def fields(self):
        with self.ctx.guard() as g:
            result=base.read_taper(self.new_tool,self.native['doc'],g.read,
                lambda obj,name:self.exact_typed(g,obj,name),{},profiles=False)
        require(result['native_id']==self.new_id,'Resumed scalar readback target changed')
        return result
    def field(self,name):
        require(name in FIELD_ORDER,'Bounded property required')
        with self.ctx.guard() as g:
            require(_object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,'Scalar target changed')
            target=self.new_tool if name in base.TOOL_FIELDS else self.exact_typed(g,self.new_tool,'ICWTaperTool')
            return g.read(target,name)
    def property(self,name,value,pending):
        require(name in FIELD_ORDER and self.interface_preflight_passed is True,'Audited bounded property required')
        with self.ctx.guard() as g:
            require(self.new_id not in self.old_holders and _object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,
                    'Setter must target exact previously created tool')
            target=self.new_tool if name in base.TOOL_FIELDS else self.exact_typed(g,self.new_tool,'ICWTaperTool')
            return g.dispatch_once(lambda:setattr(target,name,value),persist_pending=pending)



def infer_default_angle_units(parameters):
    names=('EndDia','MaxDia','TaperLength','TaperAngle')
    raw={k:parameters.get(k) for k in names}
    result=dict(raw=raw,formula='atan((MaxDia-EndDia)/(2*TaperLength))',
        numeric_guard=1e-7,units_inferred_from_default_cone=True,
        degrees_match=False,radians_match=False,degree_compatible=False,
        status='unknown_default_cone')
    if not all(type(v) in (int,float) and math.isfinite(v) for v in raw.values()):
        result['reason']='nonfinite_or_nonnumeric_default';return result
    if raw['EndDia']<0 or raw['TaperLength']<=0 or raw['MaxDia']<=raw['EndDia'] or raw['TaperAngle']<=0:
        result['reason']='zero_or_invalid_default_cone';return result
    radians=math.atan((raw['MaxDia']-raw['EndDia'])/(2*raw['TaperLength']))
    degrees=math.degrees(radians)
    result.update(computed_radians=radians,computed_degrees=degrees,
        degrees_match=math.isclose(raw['TaperAngle'],degrees,rel_tol=1e-7,abs_tol=1e-7),
        radians_match=math.isclose(raw['TaperAngle'],radians,rel_tol=1e-7,abs_tol=1e-7))
    result['degree_compatible']=result['degrees_match'] and not result['radians_match']
    result['status']=('degrees' if result['degree_compatible'] else 'radians'
        if result['radians_match'] and not result['degrees_match'] else 'ambiguous'
        if result['radians_match'] and result['degrees_match'] else 'inconsistent')
    return result

def run_backend(backend,journal,loaded,recipe):
    r=journal.report;persist=journal.persist
    try:
        backend.start()
        initial=deepcopy(r['initial_observation'])
        new_id=r['new_tool_native_id']
        actual=backend.bind_created(new_id)
        require(group.exact(actual,r['inherited_created_catalogue']),'Created-tool catalogue changed before resume')
        verify_new_catalogue(initial['tools'],actual,new_id)
        current=backend.read_narrow('resume_before')
        require(group.exact(backend.save_projection(current),initial['route']),'Protected route changed before resume')
        r['resume_before_route']=deepcopy(current);persist()
        row=backend.fields()
        r['resumed_candidate_fields']=deepcopy(row)
        r['angle_unit_gate']=infer_default_angle_units(row['parameters']);persist()
        require(r['angle_unit_gate']['degree_compatible'] is True,
                'Default cone does not uniquely establish degrees; stop before setters')
        for name in FIELD_ORDER:
            if name=='Protrusion':
                result=backend.attach_holder(recipe['holder_file_pin']['path'],
                    lambda:journal.pending('SetFilePathForUserDefinedHolder'))
                journal.returned('SetFilePathForUserDefinedHolder',result)
                require(type(result) is int and result==0,'Strict successful holder-reference HRESULT required')
                backend.refresh_dirty()
                # The holder loader may set its own protrusion. Read its result
                # before the sole requested P20 assignment.
                row['parameters'][name]=backend.field(name)
            wanted=recipe['proposed_fields'][name];before=row['parameters'][name]
            label='property:'+name
            r.setdefault('field_readbacks',[]).append(dict(property=name,before=before,requested=wanted))
            if not scalar_equal(before,wanted):
                result=backend.property(name,wanted,lambda label=label:journal.pending(label))
                journal.returned(label,result)
                require(result is None,'Property dispatch must return PythonNone; readback proves value')
                backend.refresh_dirty()
            actual=backend.field(name)
            require(scalar_equal(actual,wanted),'Immediate property readback differs: '+name)
            row['parameters'][name]=actual
            r['field_readbacks'][-1].update(actual=actual)
            # Unknown template geometry is not used. All three proposed cone
            # fields are set and reread before one physical-profile proof.
            if name=='TaperAngle':
                cone=backend.candidate('cone_proof')
                r['cone_qualification']=validate_candidate(cone,recipe,loaded['holder_recipe'],stage='after_taper_angle')
                r['cone_candidate']=cone
            persist()
        candidate=backend.candidate('configured')
        r['candidate_qualification']=validate_candidate(candidate,recipe,loaded['holder_recipe'])
        r['configured_candidate']=candidate
        configured=backend.snapshot('configured');verify_protected(initial,configured,new_id)
        r['configured_observation']=configured;persist()
        def capture(label):
            if label=='before':
                backend.boundary()
                return dict(observation=configured,candidate=candidate)
            observation=backend.snapshot('save_'+label);verify_protected(initial,observation,new_id)
            tool=backend.candidate('save_'+label)
            validate_candidate(tool,recipe,loaded['holder_recipe'])
            require(group.exact(candidate,tool),'Candidate changed around Save')
            r['final_candidate']=tool;r['final_observation']=observation
            r['final_state']=deepcopy(backend.current_state);persist()
            return dict(observation=observation,candidate=tool)
        def verify(value):
            require(group.exact(value,dict(observation=configured,candidate=candidate)),'Save projection differs')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            digest=backend.saved_hash(r['save_stage'])
            require(digest!=r['initial_source_sha256'],'Changed tool must change saved source hash')
            r['saved_source_sha256']=digest;persist();return digest
        r['save_stage']={}
        run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        backend.finish()
        r.update(phase='finished',status='review_required',readback_verified=True,model_saved=True,
            exact_one_tool_created=False,existing_created_tool_resumed=True,assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,
            operation_creation_attempted=False,production_qualified=False)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',
            failed_phase=r['phase'],readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        persist()
    return r



def marker_path(source,source_sha256,created_id,creation_marker_sha256):
    key=_digest(dict(scope=SCOPE,source=exports._key(source),source_sha256=source_sha256,
        created_tool_native_id=created_id,creation_marker_sha256=creation_marker_sha256))
    return exports.local_evidence_root()/('taper_resume_'+key+'.json')


class Journal(base.Journal):
    def marker_state(self):
        value=super().marker_state()
        value.update(scope=SCOPE,failure_receipt_sha256=self.report['failure_pin']['sha256'],
            creation_marker_sha256=self.report['creation_marker_pin']['sha256'],
            new_tool_native_id=self.report['new_tool_native_id'])
        return value


def composite_validation_view(data,failed):
    require(data['scope']==SCOPE and data['existing_created_tool_resumed'] is True
        and data['exact_one_tool_created'] is False and data['creation_attempted'] is False
        and type(data['full_tool_snapshot_count']) is int and data['full_tool_snapshot_count']==2
        and type(data['inherited_full_tool_snapshot_count']) is int
        and data['inherited_full_tool_snapshot_count']==1
        and data['baseline_origin']=='inherited_failed_attempt_before_creation',
        'Exact inherited/current native work split required')
    require(group.exact(data['initial_observation'],failed['initial_observation'])
        and group.exact(data['inherited_created_catalogue'],failed['scalar_catalogue_reads'][-1]['rows'])
        and group.exact(data['inherited_creation_action'],failed['actions']['AddNewTool3'])
        and data['new_tool_native_id']==failed['new_tool_native_id']
        and 'AddNewTool3' not in data['actions'],'Creator evidence must remain historical')
    require(data['interface_audit'].get('all_resolved') is True
        and data['interface_audit'].get('property_signatures_verified') is True
        and type(data['interface_audit']['native_query_interface_calls']) is int
        and data['interface_audit']['native_query_interface_calls']==0,
        'Exact interface metadata preflight required')
    gate=infer_default_angle_units(data['resumed_candidate_fields']['parameters'])
    require(group.exact(gate,data['angle_unit_gate']) and gate['degree_compatible'] is True,
            'Before-setters default angle unit proof differs')
    view=deepcopy(data)
    view.update(scope=base.SCOPE,full_tool_snapshot_count=3)
    view['actions']={'AddNewTool3':deepcopy(data['inherited_creation_action']),**deepcopy(data['actions'])}
    return view


def validate_terminal(data,failed):
    view=composite_validation_view(data,failed)
    return base.validate_terminal(view)


def derive_closure(parent,failurepin,creationpin):
    root=Path(base.__file__).resolve().parent
    wanted={exports._key(root/'sw_cam_checkpoint_reconfigure.py'),
        exports._key(root/'sw_cam_raw_mill_face_feature.py'),
        exports._key(parent['parent_pin']['path']),exports._key(parent['group_marker_pin']['path'])}
    retired=[p for p in parent['pins'] if exports._key(p['path']) in wanted]
    require(len(retired)==4,'Exactly four proven historical phase dependencies required')
    live=exports._merge([p for p in parent['pins'] if exports._key(p['path']) not in wanted],
        [exports._pin(__file__),exports._pin(taper.__file__),failurepin,creationpin])
    require(len(live)==64,'Exact 64 live dependency boundary required')
    require(any(Path(p['path']).name=='sw_cam_face_interfaces.py' for p in live)
        and all(any(exports._key(p['path'])==exports._key(v['path']) for p in live)
                for v in (failurepin,creationpin)),'Native QI helper and unresolved creator evidence must remain live')
    offline=exports._merge(parent['offline_export_proof_pins'],retired,[exports._pin(evidence.__file__)])
    return live,offline,retired


def load_inputs(params,*,check_current=True):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    parent=base.load_inputs(params,check_current=check_current)
    failed,failurepin=read_pin(params['failed_receipt_path'],params['failed_receipt_sha256'])
    actual_marker=base.marker_path(params['expected_document_path'],params['expected_source_sha256'])
    require(exports._key(params['creation_marker_path'])==exports._key(actual_marker),
            'Original source-bound creator marker required')
    mark,creationpin=read_pin(params['creation_marker_path'],params['creation_marker_sha256'])
    verified=evidence.validate_resume_evidence(failed,parent,mark)
    require(verified['new_tool_native_id']==params['expected_created_tool_native_id'],'Exact requested existing tool ID differs')
    live,offline,retired=derive_closure(parent,failurepin,creationpin)
    exports._check(live);exports._check(offline)
    return dict(parent,pins=live,offline_export_proof_pins=offline,resume_retired_pins=retired,
        failure_pin=failurepin,creation_marker_pin=creationpin,failed_attempt=failed,
        resume_evidence=verified)


def prepare(params):
    loaded=load_inputs(params)
    verified=loaded['resume_evidence'];failed=loaded['failed_attempt']
    marker=marker_path(params['expected_document_path'],params['expected_source_sha256'],
        verified['new_tool_native_id'],params['creation_marker_sha256'])
    exports._local_receipt(params['receipt_path'])
    require(not Path(params['receipt_path']).exists() and not Path(params['receipt_path']).is_symlink()
        and not marker.exists() and not marker.is_symlink(),'Fresh resume receipt and stable once-marker required')
    protected={exports._key(p['path']) for p in loaded['pins']+loaded['offline_export_proof_pins']}
    protected.add(exports._key(params['expected_document_path']))
    require(exports._key(params['receipt_path']) not in protected and exports._key(marker) not in protected
        and exports._key(params['receipt_path'])!=exports._key(marker),'Resume evidence alias forbidden')
    report=dict(schema_version=1,scope=SCOPE,status='running',phase='prepared',actions={},
        module_pin=exports._pin(__file__),process_id=params['process_id'],source_path=params['expected_document_path'],
        initial_source_sha256=params['expected_source_sha256'],receipt_path=params['receipt_path'],
        parent_pin=deepcopy(loaded['parent_pin']),historical_source_pin=deepcopy(loaded['historical_source_pin']),
        failure_pin=deepcopy(loaded['failure_pin']),creation_marker_pin=deepcopy(loaded['creation_marker_pin']),
        inherited_creation_action=deepcopy(failed['actions']['AddNewTool3']),
        inherited_created_catalogue=deepcopy(verified['catalogue_after_creation']),
        initial_observation=deepcopy(verified['baseline']),new_tool_native_id=verified['new_tool_native_id'],
        baseline_origin='inherited_failed_attempt_before_creation',inherited_full_tool_snapshot_count=1,
        previous_event_cleanup_observed=False,requires_fresh_event_scope=True,
        recipe=deepcopy(loaded['recipe']),recipe_pin=deepcopy(loaded['recipe_pin']),catalogue_pin=deepcopy(loaded['catalogue_pin']),
        current_before=group.current_projection(loaded),current_before_sha256=loaded['current_context_sha256'],
        settings_before=deepcopy(loaded['settings']),generated_face_operation_id=loaded['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(loaded['toolpath_record_counts']),
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        phase_retired_pins=deepcopy(loaded['resume_retired_pins']),
        mutation_attempted=False,creation_attempted=False,readback_verified=False,model_saved=False,
        automatic_retry=False,automatic_replay=False,phase_proofs_verified_after_native=False,
        full_tool_snapshot_count=0,candidate_profile_capture_count=0,assignment_attempted=False,GTP_attempted=False,
        GOP_attempted=False,operation_creation_attempted=False,production_qualified=False)
    return loaded,report,marker


def execute(sw,clsid,typelib,*,params,loaded,report,marker):
    journal=Journal(report,params['receipt_path'],marker)
    _write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist)
    result=run_backend(backend,journal,loaded,loaded['recipe'])
    try:
        exports._check(loaded['offline_export_proof_pins']);exports._check(loaded['bootstrap_export_pins'])
        result['phase_proofs_verified_after_native']=True
        if result.get('readback_verified') is True:
            result['checkpoint']=base.make_checkpoint(result);result['checkpoint_sha256']=_digest(result['checkpoint'])
            validate_terminal(result,loaded['failed_attempt']);journal.persist()
            result['marker_pin']=exports._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable resume marker changed')
    except Exception as exc:
        result.update(status='uncertain',readback_verified=False,phase_proofs_verified_after_native=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    data,receiptpin=read_pin(path,digest)
    require(data['module_pin']==exports._pin(__file__) and data['process_id']==process_id
        and exports._key(data['source_path'])==exports._key(expected_document_path)
        and exports._key(data['receipt_path'])==exports._key(path)
        and data['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),
        'Current resumed source/process/runtime differs')
    params=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=data['initial_source_sha256'],
        checkpoint_receipt_path=data['parent_pin']['path'],checkpoint_receipt_sha256=data['parent_pin']['sha256'],
        historical_source_path=data['historical_source_pin']['path'],
        recipe_path=data['recipe_pin']['path'],recipe_sha256=data['recipe_pin']['sha256'],
        catalogue_receipt_path=data['catalogue_pin']['path'],catalogue_receipt_sha256=data['catalogue_pin']['sha256'],
        failed_receipt_path=data['failure_pin']['path'],failed_receipt_sha256=data['failure_pin']['sha256'],
        creation_marker_path=data['creation_marker_pin']['path'],creation_marker_sha256=data['creation_marker_pin']['sha256'],
        expected_created_tool_native_id=data['new_tool_native_id'])
    parent=load_inputs(params,check_current=False)
    cp=validate_terminal(data,parent['failed_attempt'])
    require(group.exact(group.current_projection(parent),data['current_before'])
        and group.exact(parent['settings'],data['settings_before'])
        and group.exact(parent['pins'],data['live_pins'])
        and group.exact(parent['offline_export_proof_pins'],data['offline_proof_pins'])
        and group.exact(parent['resume_retired_pins'],data['phase_retired_pins'])
        and group.exact(parent['generated_face_operation_id'],data['generated_face_operation_id'])
        and group.exact(parent['toolpath_record_counts'],data['toolpath_record_counts'])
        and group.exact(parent['recipe'],data['recipe'])
        and group.exact(parent['historical_source_pin'],data['historical_source_pin']),
        'Exact inherited authority and current derivation required')
    marker=marker_path(data['source_path'],data['initial_source_sha256'],data['new_tool_native_id'],
                       data['creation_marker_pin']['sha256'])
    mark,markpin=read_pin(str(marker),data['marker_pin']['sha256'])
    require(exports._key(data['marker_pin']['path'])==exports._key(marker)
        and group.exact(mark,Journal(data,path,marker).marker_state()),'Stable completed resume marker differs')
    # The previously unresolved creator becomes fully reconciled only through
    # this strict completed resume. Preserve both original receipt and marker
    # as exact offline history; the new current authority remains live.
    retired_current={exports._key(data['failure_pin']['path']),exports._key(data['creation_marker_pin']['path'])}
    live=exports._merge([p for p in parent['pins'] if exports._key(p['path']) not in retired_current],[receiptpin])
    offline=exports._merge(parent['offline_export_proof_pins'],[data['failure_pin'],data['creation_marker_pin'],markpin])
    result=dict(cp['current'],pins=live,current_context_sha256=_digest(cp['current']),
        parent_pin=receiptpin,group_marker_pin=markpin,generated_pin=deepcopy(parent['generated_pin']),
        settings=deepcopy(cp['settings']),generated_face_operation_id=cp['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        local_tool_candidate=deepcopy(cp['local_tool_candidate']),profile_contract=deepcopy(cp['profile_contract']),
        candidate_qualification=deepcopy(cp['candidate_qualification']),tool_checkpoint=data,
        bootstrap_export_pins=deepcopy(parent['bootstrap_export_pins']),offline_export_proof_pins=offline,
        authority_kind='resumed_saved_taper_candidate')
    exports._check(live);exports._check(offline);exports.operation_contract(result);return result


PARAMS=base.PARAMS|{'failed_receipt_path','failed_receipt_sha256','creation_marker_path',
                    'creation_marker_sha256','expected_created_tool_native_id'}


def validate_request(request):
    import re
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action']=='resume_created_tool','Only address-specific resume allowed')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact resume request fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32
        and type(p['expected_created_tool_native_id']) is int and 0<p['expected_created_tool_native_id']<2**32,
        'Strict owned process and existing tool IDs required')
    for name,value in p.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if name.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy']=='vendor_default','Explicit bounded resume required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),
            'Exact CAM CLSID required')
    return dict(p)


def dispatch_request(request,*,validate_only=False):
    params=validate_request(request);loaded,report,marker=prepare(params)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=params['process_id']):
        exports._check(loaded['pins']);exports._check(loaded['offline_export_proof_pins'])
        registration=exports.discover_export_registration(loaded,params['addin_clsid'])
        typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
        audit=taper.audit_taper_interface(typelib,generated_pin=loaded['generated_pin'])
        if validate_only:
            return dict(status='validated_offline',readback_verified=True,native_called=False,
                interface_audit=audit,live_pin_count=len(loaded['pins']),created_tool_native_id=report['new_tool_native_id'])
        sw,_=connect_solidworks(process_id=params['process_id'],launch_new_instance=False,wait_seconds=1)
        report['bootstrap_validation']=deepcopy(loaded['bootstrap_validation'])
        return execute(sw,registration['clsid'],typelib,params=params,loaded=loaded,report=report,marker=marker)


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True)
    p.add_argument('--validate-only',action='store_true');o=p.parse_args(argv)
    result=dispatch_request(json.loads(Path(o.request).read_text(encoding='utf-8-sig')),validate_only=o.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','new_tool_native_id','saved_source_sha256','issue')},
        ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1


if __name__=='__main__':raise SystemExit(main())
