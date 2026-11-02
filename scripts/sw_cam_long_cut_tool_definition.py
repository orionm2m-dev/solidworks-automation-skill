"""Create one unassigned OSG3130520 LOC6 cutter from a saved current MILL route.

Uses the existing native flat-tool factory, full tool/holder reader and one
Save pipeline. Existing tools and all operations remain protected. No GTP.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_neck_tool_candidate as factory
from scripts import sw_cam_neck_tool_continuation as corrected
from scripts import sw_cam_fresh_finish_recipe as saved
from scripts import sw_cam_deep_guide_checkpoint as deep
from scripts import sw_cam_long_cut_cutter_geometry as geometry
from scripts import sw_cam_exact_cutter_reuse as reuse
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_shared_holder_geometry import check_holder_pins
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error
from scripts.sw_cam_read_progress_journal import ReadProgressJournal
common,group,prior=factory.common,factory.group,factory.prior
FIELD_ORDER,TEXT_FIELDS=factory.FIELD_ORDER,factory.TEXT_FIELDS
REUSE_POLICY_PIN=common._pin(reuse.__file__)
SCOPE='SAVED_DEEP_LONG_CUT_TOOL_DEFINITION_V1'
AUTHORITY='saved_long_cut_tool_candidate_unassigned'
PARAMS=(common.COMMON-{'acknowledge_machine_scope'})|{'recipe_path','recipe_sha256',
 'geometry_acceptance_path','geometry_acceptance_sha256',
 'deep_receipt_path','deep_receipt_sha256','source_backup_path','source_backup_sha256','saved_cl_path'}
# Completed phase implementations are still hash checked before/after, but are
# not native readers or mutators in this tool-only phase.
RETIRED={'sw_cam_fresh_finish_insert.py','sw_cam_fresh_finish_recipe.py',
 'sw_cam_finish_defaults_progress.py','sw_cam_fresh_finish_field_batch.py',
 'sw_cam_wall_outcome.py','sw_cam_wall_perimeter_first.py'}



# Historical writers, rebind evidence and full-CAD capture are not invoked in
# the retained route/tool phase. Their hashes remain checked before and after.
PROOF_ONLY_NATIVE_PHASE = frozenset({
 'sw_cam_completed_sandvik_assignment.py','sw_cam_exact_cutter_reuse.py',
 'sw_cam_mill_profile_headers.py','sw_cam_turn_feature_attribute.py','sw_cam_mill_stock.py',
 'sw_cam_chamfer_defaults.py','sw_cam_chamfer_exports.py','sw_cam_pocket_rough_apply.py',
 'sw_cam_pocket_wall_continue.py','sw_cam_wall_configuration_save.py',
 'sw_cam_saved_wall_configuration.py','sw_cam_chamfer_insert_defaults.py',
 'fresh_finish_definition.json','fresh_finish_recipe_v2.json','235_owned_restart_startup.json',
 'sw_cam_mill_saved_plan_rebind.py','sw_cam_fresh_finish_rebind.py',
 'guide_rebind_new_session.json','guide_four_definitions_ctor_fixed.json',
 'sw_cam_neck_tool_continuation.py','sw_cam_neck_cutter_geometry.py',
 'sw_cam_pocket_rough_exports.py','installed_profile_nominal.json'})


def partition_native_pins(pins, offline):
    retired=[v for v in pins if Path(v['path']).name in PROOF_ONLY_NATIVE_PHASE]
    names=[Path(v['path']).name for v in retired]
    require(len(names)==len(set(names)) and set(names)==PROOF_ONLY_NATIVE_PHASE,
        'Exact reviewed historical-only dependency roles required')
    live=[v for v in pins if Path(v['path']).name not in PROOF_ONLY_NATIVE_PHASE]
    require(1<=len(live)<=64, 'Native dispatch guard supports at most64 active evidence pins')
    proof=common._merge(offline,retired)
    require(len(proof)<=320, 'Bounded full historical proof closure required')
    common._check(live);common._check(proof)
    return live,proof,dict(scope='LONG_CUT_NATIVE_PHASE_DEPENDENCY_PARTITION_V1',
        input_count=len(pins),live_count=len(live),proof_count=len(proof),
        shared_guard_maximum=64,shared_guard_modified=False,
        proof_checks='full content hashes before and after native phase',retired=deepcopy(retired))


def guard_constructor_preflight(p,loaded,typelib):
    from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
    expected=deepcopy(loaded['state']['document'])
    require(common._key(expected['path'])==common._key(p['expected_document_path']),
        'Offline guard document must match the exact request')
    guard=ScopedCamDispatchGuard(None,typelib,process_id=p['process_id'],
        expected_document=expected,source_sha256=p['expected_source_sha256'],
        evidence_pins=loaded['pins'],verify_evidence=lambda:None,
        verify_owned_process=lambda:None,check_events=lambda:None)
    result=dict(scope='REAL_SHARED_GUARD_CONSTRUCTOR_PREFLIGHT_V1',
        guard_type=type(guard).__name__,native_calls=0,entered=False,
        live_pin_count=len(loaded['pins']),source_and_unique_files=len(guard._rows),
        constructor_verified=True)
    guard.__exit__(None,None,None)
    return result

def catalogue_authority(loaded):
    rows=loaded['long_cut_initial_catalogue']
    require(type(rows) is list and 1<=len(rows)<=prior.MAX_TOOLS,'Bounded saved actual catalogue required')
    ids=[r['native_id'] for r in rows]
    require(all(type(v) is int and v>0 for v in ids) and len(set(ids))==len(ids),'Unique native tool IDs required')
    binding=loaded['fresh_finish_result']
    require(binding['generated'] is True and binding['tool_native_id'] in ids,
            'Saved generated finish tool must remain present')
    require(loaded['long_cut_requested_diameter']==2.0,'Exact reviewed long-cut diameter required')
    return deepcopy(rows)


def verify_protected(initial,observed,new_id):
    require(group.exact(initial['route'],observed['route']),'Protected route or FACE settings changed')
    require(group.exact(initial['guide_snapshot'],observed['guide_snapshot']),'Protected eight guide parameter groups changed')
    factory.verify_catalogue(initial['tools'],observed['tools'],new_id)


verify_catalogue=factory.verify_catalogue
verify_candidate=geometry.verify_candidate


class Journal(prior.Journal):
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE)


class NativeBackend(factory.NativeBackend):
    """Existing tool factory plus shared-session deep17/8 readback and CL14 proof."""
    def __init__(self,*args):
        super().__init__(*args)
        self.guide_reader=None

    def start(self):
        super().start()
        view=deep.ParameterBackend(self.loaded['deep_loaded'],self.args,self.sw,self.clsid,
            self.typelib_path,self.report,self.persist)
        # The view must not bootstrap, subscribe, close or own a second session.
        view.ctx=self.ctx;view.session=self.session;view.session_active=self.session_active
        self.guide_reader=view

    def snapshot(self,label):
        result=super().snapshot(label)
        require(self.guide_reader is not None and self.guide_reader.ctx is self.ctx
            and self.guide_reader.session is self.session,'Original shared context required')
        result['guide_snapshot']=self.guide_reader.capture_parameters('long_cut_'+label)
        require(group.exact(result['guide_snapshot'],self.loaded['deep_loaded']['guide_parameters']['expected_parameters']),
            'Seventeen bindings and eight guide groups must remain unchanged')
        return result

    def duplicate_candidates(self,recipe):
        from scripts.sw_cam_thread import _object_id
        from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
        batch=self.batch(max_native_calls=prior.PROFILE_BATCH_CALLS)
        rows=[];diagnostic={};self.report['same_diameter_read']=diagnostic;self.persist()
        try:
            with batch:
                handles=prior._items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,prior.MAX_TOOLS)
                actual=[_object_id(self.native['doc'],raw,batch.read)for raw in handles]
                require(actual==[r['native_id']for r in self.loaded['long_cut_initial_catalogue']],
                    'Catalogue identity changed before duplicate check')
                for raw,tid in zip(handles,actual):
                    generic=next(r for r in self.loaded['long_cut_initial_catalogue']if r['native_id']==tid)
                    if generic['tool_type_raw']!=1 or not prior.scalar_equal(generic['CutDiameter'],recipe['target']['CutDiameter']):continue
                    tool=batch.typed(raw,'ICWTool')
                    observed=dict(native_id=tid,is_mill_tool=batch.read(tool,'IsMillTool'),native_read_complete=True,
                        tool_type_raw=batch.read(tool,'ToolType'),cut_diameter_native=batch.read(tool,'CutDiameter'),
                        protrusion_native=batch.read(tool,'Protrusion'))
                    require(observed['is_mill_tool']is True and observed['tool_type_raw']==1
                        and prior.scalar_equal(observed['cut_diameter_native'],generic['CutDiameter'])
                        and prior.scalar_equal(observed['protrusion_native'],generic['Protrusion']),'Same-diameter tool binding changed')
                    full=read_full_mill_tool(tool,generic=observed,read=batch.read,typed=batch.typed,diagnostic={})
                    identity={name:batch.read(tool,name)for name in sorted(TEXT_FIELDS)}
                    rows.append(dict(native_id=tid,identity=identity,full_tool=full))
            batch.require_complete();diagnostic.update(complete=True,rows=deepcopy(rows))
            return rows
        finally:diagnostic['batch']=batch.summary();self.persist()

    def finish(self):
        diagnostic={};self.report['saved_cl']=diagnostic;self.persist()
        deep.cl.export_current_cl(self.guide_reader,'long_cut_saved',
            self.report['final_observation']['guide_snapshot']['binding'],self.loaded['saved_cl_path'],diagnostic)
        self.report['saved_cl_comparison']=deep.cl.verify_all(self.loaded['deep_loaded']['generated']['saved_cl'],diagnostic)
        self.report['protected_fourteen_cl_verified']=True;self.persist()
        super().finish()
        self.guide_reader.session_active=False

    def read_settings(self,label):
        full=self.persist
        actions=deepcopy(self.report['actions'])
        index=len(self.report.setdefault('long_cut_read_progress',[]))
        path=Path(self.report['receipt_path']).with_suffix('.read'+str(index)+'.json')
        protected=[self.report['receipt_path'],self.report['source_path']]+[p['path'] for p in self.loaded['pins']]
        self.report['long_cut_read_progress'].append(str(path))
        with ReadProgressJournal(full_persist=full,progress_path=path,
                describe=lambda:dict(phase=label,reader='existing_face_parameters'),
                max_updates=512,protected_paths=protected) as progress:
            try:
                self.persist=progress.read
                value=super().read_settings(label)
                require(group.exact(actions,self.report['actions']),'Mutation inside read-only progress phase')
                progress.complete()
                return value
            finally:self.persist=full


def marker_path(source,sha):
    return common.local_evidence_root()/('long_cut_tool_'+prior._digest(
        dict(scope=SCOPE,source=common._key(source),source_sha256=sha))+'.json')


def compatible_context(legacy,receipt,current,deep_receipt):
    """Pure transition; the old source hash remains historical, never current."""
    snapshot=current['guide_parameters']['expected_parameters'];binding=snapshot['binding']
    deep.cl.contract(binding)
    require(len(binding['operations'])==17 and len(snapshot['parameters'])==8,
        'Complete current seventeen/eight authority required')
    old=legacy['state']['operations'];new=binding['operations']
    require(len(old)==9 and group.exact(old,new[:9]),'Original nine operation definitions or paths changed')
    catalogue=deepcopy(receipt['final']['tools'])
    require([v['native_id']for v in catalogue]==deep_receipt['tool_catalogue_ids'],
        'Saved nineteen-tool catalogue identity changed')
    require(len(catalogue)==19 and sum(v['native_id']==273 for v in catalogue)==1,
        'Existing separate tool273 catalogue required')
    require(common._key(receipt['source_path'])==common._key(current['guide_parameters']['document']['path']),
        'Historical/current document differs')
    context=deepcopy(legacy);state=context['state']
    state.update(operations=deepcopy(new),operation_count=17,
        operation_setups=deepcopy(binding['operation_setups']),
        operation_counts=[v['operation_count']for v in binding['operation_setups']],
        operation_setup_count=len(binding['operation_setups']),
        document=deepcopy(current['guide_parameters']['document']),
        saved_file_sha256=deep_receipt['saved_source_sha256'])
    require(set(binding['features'])=={'80','81','82','83'}
        and all(int(fid)in{v['geometry']['native_id']for v in state['features']}for fid in binding['features']),
        'Existing four guide features must be in complete historical inventory')
    context.update(source_sha256=deep_receipt['saved_source_sha256'],ownership=deepcopy(current['ownership']),
        long_cut_initial_catalogue=catalogue,deep_loaded=deepcopy(current))
    return context


def load_inputs(p):
    current,registration,typelib,deep_audit,deep_pin=deep.load_checkpoint(p)
    require(p['addin_clsid'].casefold()==registration['clsid'].casefold(),'Exact checkpoint CAM registration required')
    receipt,parent=read_pin(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'])
    require(receipt['module_pin']==common._pin(saved.__file__),'Historical completed writer changed')
    legacy=saved.validate_terminal(receipt)
    require(receipt['checkpoint_digest']==prior._digest(group.current_projection(legacy)),
        'Historical completed context digest differs')
    mark,markerpin=read_pin(receipt['marker_pin']['path'],receipt['marker_pin']['sha256'])
    require(group.exact(mark,saved.Journal(receipt,parent['path'],markerpin['path']).marker_state()),
        'Historical completed once marker changed')
    deep_receipt=current['generated'];loaded=compatible_context(legacy,receipt,current,deep_receipt)
    recipe,recipepin=read_pin(p['recipe_path'],p['recipe_sha256']);validate_recipe(recipe)
    acceptance,acceptancepin=read_pin(p['geometry_acceptance_path'],p['geometry_acceptance_sha256'])
    require(acceptance['status']=='GEOMETRY_CHECKED_FOR_BOUNDED_DIAMETER2_WALL_SCOPE'
        and acceptance['source_saved_sha256']==receipt['saved_source_sha256']
        and acceptance['operation_native_id']==loaded['fresh_finish_result']['native_id']==320
        and acceptance['tool_native_id']==loaded['fresh_finish_result']['tool_native_id']==273,
        'Historical accepted320/273 geometry linkage required')
    loaded['long_cut_requested_diameter']=recipe['target']['CutDiameter'];catalogue_authority(loaded)
    holder=deepcopy(loaded['holder_recipe']);check_holder_pins(holder)
    backup=common._pin(p['source_backup_path'])
    require(backup['sha256']==p['source_backup_sha256']==p['expected_source_sha256']
        and common._key(backup['path'])!=common._key(p['expected_document_path']),
        'Independent current source backup required')
    retired=[v for v in receipt['live_pins']if Path(v['path']).name in RETIRED]
    require({Path(v['path']).name for v in retired}==RETIRED,'Exact completed phase pin roles required')
    added=[common._pin(v)for v in (__file__,factory.__file__,corrected.__file__,factory.geometry.__file__,factory.rough.__file__,deep.__file__,geometry.__file__,reuse.__file__)]
    pins=common._merge([v for v in receipt['live_pins']if v not in retired],current['pins'],added,holder['pins'])
    offline=common._merge(receipt['offline_proof_pins'],retired,current['checkpoint_pins'],
        [parent,markerpin,recipepin,acceptancepin,deep_pin,backup],recipe['source_pins'])
    pins,offline,partition=partition_native_pins(pins,offline)
    common._check(pins);common._check(offline);common._check(loaded['bootstrap_export_pins'])
    audit=factory.audit_interfaces(typelib,loaded['generated_pin'])
    loaded.update(pins=pins,offline_export_proof_pins=offline,long_cut_retired_pins=retired,
        parent_pin=deep_pin,group_marker_pin=markerpin,source_backup_pin=backup,
        saved_cl_path=p['saved_cl_path'],deep_interface_audit=deep_audit,long_cut_registration=deepcopy(registration),
        native_pin_partition=partition)
    loaded['current_context_sha256']=prior._digest(group.current_projection(loaded))
    return loaded,recipe,recipepin,registration,typelib,audit

def validate_recipe(recipe):
    require(type(recipe) is dict and set(recipe)=={'target','identity','profile_basis','source_pins'},
        'Exact reviewed long-cut recipe required')
    geometry.validate_target(recipe['target'])
    require(type(recipe['identity']) is dict and set(recipe['identity'])==TEXT_FIELDS,
        'Explicit bounded new tool identity required')
    require(all(type(v) is str and 0<len(v)<=1000 and '\x00' not in v for v in recipe['identity'].values()),
        'Bounded identity text required')
    require(recipe['profile_basis']=='nominal_manufacturer_body_requires_native_readback',
        'Manufacturer body and required native verification must remain explicit')
    require(type(recipe['source_pins']) is list and 1<=len(recipe['source_pins'])<=8,
        'Pinned manufacturer and envelope evidence required')
    common._check(recipe['source_pins'])
    return dict(recipe['target'],**recipe['identity'])


def run_backend(backend,journal,loaded,recipe,holder_recipe):
    """One creation/configuration/save attempt; never assign or regenerate.

    Caller must have checked source/PID/pins and a fresh receipt/marker before
    constructing the backend. This entry also rejects any prior attempted action.
    """
    r=journal.report;persist=journal.persist
    require(r.get('scope')==SCOPE and r.get('actions')=={} and not journal.claimed
        and not journal.marker.exists(), 'Fresh exact attempt required')
    proposed=validate_recipe(recipe);check_holder_pins(holder_recipe)
    initial_catalogue=catalogue_authority(loaded)
    try:
        backend.start();initial=backend.snapshot('initial');r['initial_observation']=initial;persist()
        require(group.exact(initial['route'],prior.expected_route(loaded)),'Actual initial route differs from saved authority')
        require(group.exact(initial['tools'],initial_catalogue), 'Actual prior catalogue changed')
        require(group.exact(initial['guide_snapshot'],loaded['deep_loaded']['guide_parameters']['expected_parameters']),
            'Actual current guide snapshot differs')
        candidates=backend.duplicate_candidates(recipe)
        common._check([REUSE_POLICY_PIN])
        r['duplicate_policy']=reuse.require_new_exact_cutter(initial_catalogue,candidates,recipe['identity'],recipe['target'],
            accepted_identity_aliases=[{'ToolVendor':'OSG','ToolIdentifier':'3130520'},{'ToolVendor':'OSG','ToolIdentifier':'WXL-EMS 3130520'}]);persist()
        common._check([REUSE_POLICY_PIN])
        new_id=backend.create(lambda:journal.pending('AddNewTool3'),
            lambda v:journal.returned('AddNewTool3',v,pointer=True))
        forbidden={v['geometry']['native_id'] for v in loaded['state']['features']}
        forbidden|={v['native_id'] for v in loaded['state']['operations']+loaded['state']['feature_setups']+loaded['state']['operation_setups']}
        require(new_id not in forbidden,'Created tool ID collides with protected CAM object')
        r['new_tool_native_id']=new_id;persist()
        classification=backend.created_classification();r['created_classification']=deepcopy(classification);persist()
        require(type(classification['MillToolType']) is int and classification['MillToolType']==1
            and type(classification['MillToolSubType']) is int and classification['MillToolSubType']==3
            and prior.scalar_equal(classification['EndRadius'],0.),'Factory must already be flat/BOTH/zero-radius before configuration')
        verify_catalogue(initial['tools'],backend.catalogue(),new_id)
        for name in FIELD_ORDER:
            if name=='Protrusion':
                result=backend.attach_holder(holder_recipe['file_path'],lambda:journal.pending('SetFilePathForUserDefinedHolder'))
                journal.returned('SetFilePathForUserDefinedHolder',result)
                require(type(result) is int and result==0,'Strict holder reference HRESULT0 required')
                backend.refresh_dirty()
            before=backend.field(name);wanted=proposed[name];label='property:'+name
            row=dict(property=name,before=before,requested=wanted,readback_verified=False)
            r.setdefault('field_readbacks',[]).append(row);persist()
            if not prior.scalar_equal(before,wanted):
                result=backend.property(name,wanted,lambda label=label:journal.pending(label))
                journal.returned(label,result)
                require(result is None,'Property return must be None; actual readback proves value')
                backend.refresh_dirty()
            actual=backend.field(name);row['actual']=actual
            require(prior.scalar_equal(actual,wanted),'Immediate candidate readback differs: '+name)
            row['readback_verified']=True;persist()
        candidate=backend.candidate('configured');proof=verify_candidate(candidate,recipe,holder_recipe)
        configured=backend.snapshot('configured');verify_protected(initial,configured,new_id)
        r.update(configured_candidate=candidate,candidate_qualification=proof,configured_observation=configured);persist()
        def capture(label):
            if label=='before':backend.boundary();return dict(observation=configured,candidate=candidate)
            observation=backend.snapshot('save_'+label);verify_protected(initial,observation,new_id)
            actual=backend.candidate('save_'+label);verify_candidate(actual,recipe,holder_recipe)
            require(group.exact(candidate,actual),'Candidate changed during Save')
            r.update(final_candidate=actual,final_observation=observation,final_state=deepcopy(backend.current_state));persist()
            return dict(observation=observation,candidate=actual)
        def verify(value):require(group.exact(value,dict(observation=configured,candidate=candidate)),'Save projection changed')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage'])
            require(value!=r['initial_source_sha256'],'New tool must produce new saved bytes')
            r['saved_source_sha256']=value;persist();return value
        r['save_stage']={}
        prior.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        backend.finish()
        r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True,
            exact_one_tool_created=True,assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,
            TechDB_write_attempted=False,prior_full_profiles_reused=True,prior_full_profiles_freshly_reverified=False,
            manufacturing_qualified=False,physical_collet_seating_verified=False,production_qualified=False)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r.get('phase'),
            readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        persist()
    return r


def prepare(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='create_long_cut_tool_definition',
        'Only one tool-only creation/configuration/save action allowed')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact long-cut candidate request required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Positive owned PID required')
    for name,value in p.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if name.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute input/output path required')
    require(p['module_sha256']==prior._file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['message_policy']=='vendor_default','Exact qualified one-tool request required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']), 'Exact CAM registration required')
    loaded,recipe,recipepin,registration,typelib,audit=load_inputs(p)
    loaded['native_guard_preflight']=guard_constructor_preflight(p,loaded,typelib)
    output=deep.cl._fresh_path(p['saved_cl_path'])
    require(output.parent.parent.is_dir(),'Existing CL evidence parent required')
    receipt=Path(p['receipt_path']);common._local_receipt(receipt)
    marker=marker_path(p['expected_document_path'],p['expected_source_sha256'])
    context_path=receipt.with_suffix('.context.json')
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']}
    protected.add(common._key(p['expected_document_path']))
    require(all(v.is_absolute() and v.suffix.casefold()=='.json' and v.parent.is_dir() and not v.exists() and not v.is_symlink()
        for v in (receipt,marker,context_path)),'Fresh receipt and source-bound once marker required; no replay')
    require(len(set(map(common._key,(receipt,marker,context_path))))==3
        and not protected.intersection(map(common._key,(receipt,marker,context_path))), 'Output aliases protected input')
    require(common._key(output) not in protected and common._key(output) not in set(map(common._key,(receipt,marker,context_path))), 'CL output aliases protected input')
    return deepcopy(p),loaded,recipe,recipepin,registration,typelib,audit,marker


def make_checkpoint(r,loaded,recipe):
    context=deepcopy(loaded)
    context.update(state=deepcopy(r['final_state']),source_sha256=r['saved_source_sha256'])
    context['state']['saved_file_sha256']=r['saved_source_sha256']
    context['state']['document']['needs_save']=False
    context['long_cut_tool_candidate']=dict(native_id=r['new_tool_native_id'],**deepcopy(r['final_candidate']))
    context['long_cut_tool_checkpoint']=dict(catalogue=deepcopy(r['final_observation']['tools']),
        profile_qualification=deepcopy(r['candidate_qualification']),recipe=deepcopy(recipe),parent_saved_pin=deepcopy(loaded['parent_pin']),registration=deepcopy(loaded['long_cut_registration']))
    context['deep_loaded']['guide_parameters']['document']=deepcopy(r['source_transition']['document'])
    context['long_cut_tool_checkpoint']['saved_cl']=deepcopy(r['saved_cl'])
    context['deep_loaded']['generated']['saved_cl']=deepcopy(r['saved_cl'])
    context['long_cut_tool_checkpoint']['generic']=dict(native_id=r['new_tool_native_id'],is_mill_tool=True,native_read_complete=True,tool_type_raw=1,cut_diameter_native=recipe['target']['CutDiameter'],protrusion_native=recipe['target']['Protrusion'])
    context['current_context_sha256']=prior._digest(group.current_projection(context))
    return dict(context=context,source_sha256=r['saved_source_sha256'])


def validate_terminal(r):
    require(r.get('scope')==SCOPE and r.get('status')=='review_required' and r.get('phase')=='finished'
        and r.get('readback_verified') is True and r.get('model_saved') is True and r.get('exact_one_tool_created') is True
        and r.get('phase_proofs_verified') is True,'Completed saved candidate receipt required')
    require(r.get('protected_fourteen_cl_verified')is True,'Saved fourteen CL preservation required')
    require(all(r.get(k) is False for k in ('assignment_attempted','GTP_attempted','GOP_attempted','TechDB_write_attempted')),
        'Tool-only scope required')
    creation=r['actions']['AddNewTool3'];save=r['actions']['SaveActiveDocument']
    require(creation.get('returned') is True and creation.get('returned_interface_pointer') is True
        and creation.get('pending') is False,'Completed unique factory action required')
    require(save.get('returned') is True and save.get('pending') is False
        and save.get('native_return_type')=='int' and type(save.get('native_return_value')) is int
        and save['native_return_value']==0,'Strict completed Save0 required')
    allowed={'AddNewTool3','SetFilePathForUserDefinedHolder','SaveActiveDocument'}|{'property:'+v for v in FIELD_ORDER}
    require(set(r['actions'])<=allowed and all(v.get('returned') is True and v.get('pending') is False for v in r['actions'].values()),
        'No unknown or pending action permitted')
    require([v['property'] for v in r['field_readbacks']]==list(FIELD_ORDER)
        and all(v['readback_verified'] is True for v in r['field_readbacks']),'All requested fields need actual readback')
    require(group.exact(r['initial_observation']['tools'],r['initial_catalogue']), 'Initial actual catalogue authority differs')
    wanted=validate_recipe(r['recipe'])
    require(all(prior.scalar_equal(v['requested'],wanted[v['property']])
        and prior.scalar_equal(v['actual'],wanted[v['property']]) for v in r['field_readbacks']),
        'Terminal field values differ from pinned recipe')
    holder=r['actions']['SetFilePathForUserDefinedHolder']
    require(holder.get('native_return_type')=='int' and type(holder.get('native_return_value')) is int
        and holder['native_return_value']==0,'Completed strict holder HRESULT0 required')
    verify_protected(r['initial_observation'],r['final_observation'],r['new_tool_native_id'])
    require(type(r['new_tool_native_id']) is int and r['final_candidate']['full_tool']['tool_native_id']==r['new_tool_native_id'],
        'Final complete profile must belong to the actual created tool')
    verify_candidate(r['final_candidate'],r['recipe'],r['holder_recipe'])
    require(prior._digest(r['checkpoint'])==r['checkpoint_digest'],'Saved checkpoint digest differs')
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    initial,_=read_pin(r['loaded_context_pin']['path'],r['loaded_context_pin']['sha256'])
    require(group.exact(r['initial_observation']['guide_snapshot'],initial['deep_loaded']['guide_parameters']['expected_parameters']),
        'Pinned initial eight-group snapshot differs')
    require(group.exact(r['saved_cl_comparison'],deep.cl.verify_all(initial['deep_loaded']['generated']['saved_cl'],r['saved_cl'])),
        'Completed fourteen-stream comparison differs')
    require(group.exact(r['initial_catalogue'],catalogue_authority(initial))
        and group.exact(r['initial_observation']['route'],prior.expected_route(initial)),
        'Initial observation must match the pinned current source context')
    require(group.exact(r['checkpoint'],make_checkpoint(r,initial,r['recipe'])),
        'Saved flat checkpoint differs from terminal evidence')


def execute(sw,clsid,typelib,*,p,loaded,recipe,recipepin,audit,marker):
    args={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256','qualification_only','acknowledge_disposable_copy','message_policy','expected_configuration')}
    context_path=Path(p['receipt_path']).with_suffix('.context.json')
    _write_receipt(context_path,loaded,create=True);context_pin=common._pin(context_path)
    r=dict(schema_version=1,scope=SCOPE,status='error',phase='prepared',request=deepcopy(p),source_path=p['expected_document_path'],
        initial_source_sha256=p['expected_source_sha256'],process_id=p['process_id'],receipt_path=p['receipt_path'],
        source_backup_pin=deepcopy(loaded['source_backup_pin']),protected_fourteen_cl_verified=False,
        module_pin=common._pin(__file__),parent_pin=deepcopy(loaded['parent_pin']),recipe_pin=recipepin,recipe=deepcopy(recipe),
        holder_recipe=deepcopy(loaded['holder_recipe']),loaded_context_pin=context_pin,
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),interface_audit=audit,
        native_pin_partition=deepcopy(loaded['native_pin_partition']),native_guard_preflight=deepcopy(loaded['native_guard_preflight']),
        initial_catalogue=catalogue_authority(loaded),actions={},mutation_attempted=False,readback_verified=False,model_saved=False,phase_proofs_verified=False,
        assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,TechDB_write_attempted=False,
        automatic_replay=False,automatic_rollback=False,production_qualified=False)
    _write_receipt(p['receipt_path'],r,create=True);journal=Journal(r,p['receipt_path'],marker)
    backend=NativeBackend(loaded,args,sw,clsid,typelib,r,journal.persist)
    run_backend(backend,journal,loaded,recipe,loaded['holder_recipe'])
    try:
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);common._check([context_pin])
        if r['readback_verified'] is True:
            r['phase_proofs_verified']=True;r['checkpoint']=make_checkpoint(r,loaded,recipe)
            r['checkpoint_digest']=prior._digest(r['checkpoint']);validate_terminal(r)
    except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proofs_verified=False,terminal_issue=_error(exc))
    journal.persist()
    if journal.claimed:r['marker_pin']=common._pin(marker);journal.persist()
    return r


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    r,pin=read_pin(path,digest);validate_terminal(r)
    require(type(process_id) is int and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==prior._file_hash(expected_document_path),'Exact current saved candidate required')
    require(common._key(r['module_pin']['path'])==common._key(__file__) and r['module_pin']['sha256']==prior._file_hash(__file__),
        'Frozen writer implementation differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins']);common._check([r['marker_pin']])
    mark=json.loads(Path(r['marker_pin']['path']).read_text(encoding='utf-8'))
    require(mark['scope']==SCOPE and mark['readback_verified'] is True and mark['saved_source_sha256']==expected_source_sha256
        and group.exact(mark['actions'],r['actions']),'Exact completed once marker required')
    context=deepcopy(r['checkpoint']['context']);oldparent=context['parent_pin'];oldmarker=context['group_marker_pin']
    context['pins']=common._merge([v for v in context['pins'] if common._key(v['path'])!=common._key(oldparent['path'])],[pin])
    context['offline_export_proof_pins']=common._merge(context['offline_export_proof_pins'],[oldparent,oldmarker,r['marker_pin'],r['loaded_context_pin']])
    context.update(parent_pin=pin,group_marker_pin=deepcopy(r['marker_pin']),authority_kind=AUTHORITY)
    require(len(context['pins'])<=128,'Bounded current candidate context required')
    common._check(context['pins']);common._check(context['offline_export_proof_pins'])
    return context


def dispatch_request(request,*,validate_only=False):
    p,loaded,recipe,recipepin,registration,typelib,audit,marker=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),
        native_guard_preflight=deepcopy(loaded['native_guard_preflight']),native_pin_partition=deepcopy(loaded['native_pin_partition']),
        prior_tool_count=len(catalogue_authority(loaded)),protected_operation_ids=[v['native_id'] for v in loaded['state']['operations']],interface_audit=audit,
        profile_proposal=deepcopy(recipe['target']),factory_native_qualified=False,neck_mapping_native_qualified=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,p=p,loaded=loaded,recipe=recipe,recipepin=recipepin,audit=audit,marker=marker)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1

if __name__=='__main__':raise SystemExit(main())
