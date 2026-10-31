"""Guarded creation and qualification of one separate relieved-neck end mill.

The entrypoint requires the saved checkpoint, exact PID, pinned recipe,
fresh receipt and a source-bound once marker. No assignment, generation or TechDB edit.
A failed or partial attempt is evidence for a separate continuation, never a replay.
"""
from copy import deepcopy
from pathlib import Path
import json, re, importlib
from scripts import sw_cam_taper_tool_candidate as prior
from scripts import sw_cam_neck_cutter_geometry as geometry
from scripts import sw_cam_pocket_rough_exports as rough
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_shared_holder_geometry import check_holder_pins
from scripts.sw_cam_rough_firstcut import require

common,group=rough.common,rough.group
SCOPE='SAVED_LOCAL_NECK_TOOL_CANDIDATE_V1'
DB_TYPE,TOOL_TYPE=3,1
# All writes address only the newly created object. Native template/coupling is
# never assumed: each field is reread and the final complete profile must match.
FIELD_ORDER=('OverallLen','EffCutlength','NoOfFlutes','CutDiameter','ShankDia',
    'MillToolShankType','ShoulderDia','ShoulderLength','ShankLength',
    'ToolIdentifier','ToolVendor','ToolDescription','Protrusion')
TEXT_FIELDS={'ToolIdentifier','ToolVendor','ToolDescription'}
TOOL_FIELDS={'CutDiameter','Protrusion'}|TEXT_FIELDS


def validate_recipe(recipe):
    require(type(recipe) is dict and set(recipe)=={'target','identity','profile_basis','source_pins'},
        'Exact reviewed neck recipe required')
    geometry.validate_target(recipe['target'])
    require(type(recipe['identity']) is dict and set(recipe['identity'])==TEXT_FIELDS,
        'Explicit bounded new tool identity required')
    require(all(type(v) is str and 0<len(v)<=1000 and '\x00' not in v for v in recipe['identity'].values()),
        'Bounded identity text required')
    require(recipe['profile_basis']=='declared_conservative_envelope_requires_native_readback',
        'Conservative proposal must remain explicit')
    require(type(recipe['source_pins']) is list and 1<=len(recipe['source_pins'])<=8,
        'Pinned manufacturer and envelope evidence required')
    common._check(recipe['source_pins'])
    return dict(recipe['target'],**recipe['identity'])


def verify_catalogue(before,after,new_id):
    require(type(new_id) is int and new_id>0,'Actual new native ID required')
    old={v['native_id']:v for v in before};now={v['native_id']:v for v in after}
    require(len(old)==len(before) and len(now)==len(after) and new_id not in old,
        'Unique separate tool required')
    require(set(now)==set(old)|{new_id} and all(group.exact(now[k],v) for k,v in old.items()),
        'Exactly one added tool and unchanged prior scalar catalogue required')
    require([v['native_id'] for v in after if v['native_id']!=new_id]==[v['native_id'] for v in before],
        'Prior tool order changed')
    require(type(now[new_id]['tool_type_raw']) is int and now[new_id]['tool_type_raw']==TOOL_TYPE,
        'Actual flat type1 required; factory database enum3 is different')


def verify_protected(initial,observed,new_id):
    require(group.exact(initial['route'],observed['route']), 'Protected eight-operation route or FACE settings changed')
    verify_catalogue(initial['tools'],observed['tools'],new_id)


class Journal(prior.Journal):
    def marker_state(self):
        return dict(super().marker_state(),scope=SCOPE)


class NativeBackend(prior.NativeBackend):
    """Existing guarded lifecycle; full profiles only for the new candidate."""
    def snapshot(self,label):
        route=self.read_narrow(label)
        result=dict(route=group.NativeBackend.save_projection(self,route),tools=self.catalogue())
        if self.new_id is None:
            batch=self.batch(max_native_calls=prior.CATALOGUE_BATCH_CALLS)
            try:
                with batch:
                    handles=prior._items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,prior.MAX_TOOLS)
                    holders={}
                    for raw in handles:
                        tool=batch.typed(raw,'ICWTool');tid=_object_id(self.native['doc'],tool,batch.read)
                        require(tid not in holders,'Duplicate prior tool handle')
                        holders[tid]=batch.typed(batch.read(tool,'IGetMillToolHolder'),'ICWMillToolHolder')
                    require(list(holders)==[v['native_id'] for v in result['tools']], 'Prior holder binding order changed')
                batch.require_complete();self.old_holders=holders
            finally:
                self.report.setdefault('prior_holder_identity_batches',[]).append(batch.summary());self.persist()
        return result
    def create(self,pending,returned):
        require(self.new_id is None and self.new_tool is None,'Candidate already exists; no replay')
        with self.ctx.guard() as g:
            result=g.dispatch_once(lambda:_member(self.crib,'AddNewTool3',DB_TYPE),persist_pending=pending)
        returned(result)
        from scripts.sw_cam_comtypes import _is_comtypes_pointer
        require(_is_comtypes_pointer(result) and bool(result),'Creator must return a native interface')
        self.refresh_dirty()
        with self.ctx.guard() as g:
            tool=g.typed(result,'ICWTool');ident=_object_id(self.native['doc'],tool,g.read)
            require(type(ident) is int and ident>0 and ident not in self.old_holders,'New tool must be separate')
            self.new_tool,self.new_id=tool,ident
            self.report['new_tool_native_id']=ident;self.persist()
            kind=g.read(tool,'ToolType')
            require(type(kind) is int and kind==TOOL_TYPE
                and g.read(tool,'IsMillTool') is True,'Created tool is not flat MILL type1')
        return ident
    def created_classification(self):
        with self.ctx.guard() as g:
            require(_object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,'Factory object identity changed')
            mill=g.typed(self.new_tool,'ICWMillTool')
            return {name:g.read(mill,name) for name in ('MillToolType','MillToolSubType','EndRadius')}
    def field(self,name):
        require(name in FIELD_ORDER,'Field outside bounded candidate scope')
        with self.ctx.guard() as g:
            require(_object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,'Candidate identity changed')
            owner=self.new_tool if name in TOOL_FIELDS else g.typed(self.new_tool,'ICWMillTool')
            return g.read(owner,name)
    def property(self,name,value,pending):
        require(name in FIELD_ORDER,'Setter outside bounded candidate scope')
        with self.ctx.guard() as g:
            require(self.new_id not in self.old_holders and _object_id(self.native['doc'],self.new_tool,g.read)==self.new_id,
                'Only the exact new tool may change')
            owner=self.new_tool if name in TOOL_FIELDS else g.typed(self.new_tool,'ICWMillTool')
            return g.dispatch_once(lambda:setattr(owner,name,value),persist_pending=pending)
    def candidate(self,label):
        diagnostic=dict(label=label);self.report.setdefault('candidate_reads',[]).append(diagnostic);self.persist()
        batch=self.batch(self.new_tool)
        try:
            with batch:
                require(_object_id(self.native['doc'],self.new_tool,batch.read)==self.new_id,'Candidate identity changed')
                require(batch.read(self.new_tool,'IsMillTool') is True,'MILL candidate required')
                generic=dict(native_id=self.new_id,is_mill_tool=True,native_read_complete=True,
                    tool_type_raw=batch.read(self.new_tool,'ToolType'),
                    cut_diameter_native=batch.read(self.new_tool,'CutDiameter'),
                    protrusion_native=batch.read(self.new_tool,'Protrusion'))
                full=read_full_mill_tool(self.new_tool,generic=generic,read=batch.read,typed=batch.typed,diagnostic=diagnostic)
                identity={name:batch.read(self.new_tool,name) for name in sorted(TEXT_FIELDS)}
            batch.require_complete()
            return dict(full_tool=full,identity=identity)
        finally:
            diagnostic['batch']=batch.summary();self.persist()


def verify_candidate(observed,recipe,holder_recipe):
    require(group.exact(observed['identity'],recipe['identity']),'New tool identity text differs')
    return geometry.verify_candidate(observed['full_tool'],recipe['target'],holder_recipe)


def run_backend(backend,journal,loaded,recipe,holder_recipe):
    """One creation/configuration/save attempt; never assign or regenerate.

    Caller must have checked source/PID/pins and a fresh receipt/marker before
    constructing the backend. This entry also rejects any prior attempted action.
    """
    r=journal.report;persist=journal.persist
    require(r.get('scope')==SCOPE and r.get('actions')=={} and not journal.claimed
        and not journal.marker.exists(), 'Fresh exact attempt required')
    proposed=validate_recipe(recipe);check_holder_pins(holder_recipe)
    rough.operation_contract(loaded)
    require(len(rough.cl.validate_catalogue_authority(loaded))==18,'Exact saved eighteen-tool catalogue required')
    try:
        backend.start();initial=backend.snapshot('initial');r['initial_observation']=initial;persist()
        require(group.exact(initial['route'],prior.expected_route(loaded)),'Actual initial route differs from saved authority')
        require(group.exact(initial['tools'],rough.cl.validate_catalogue_authority(loaded)), 'Actual prior catalogue changed')
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



def audit_interfaces(typelib_path,generated_pin):
    """Exact installed declarations only; no application or native QI calls."""
    from ctypes import HRESULT, POINTER, c_long, c_double
    from comtypes import BSTR
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class, _load_type_library
    from scripts.sw_cam_face_interfaces import _verify_generated_class
    common._check([generated_pin]);module=_load_type_library(typelib_path)
    require(module.CW_DB_TOOL_TYPE_FLAT_MILL==3 and module.CW_MILL_TOOL_SHANK_TYPE_NECK==2,
        'Reviewed factory and neck enum values required')
    classes={name:_interface_class(name,typelib_path) for name in ('ICWTool','ICWMillTool','ICWToolcrib4','ICWMillToolHolder','ICWApp')}
    for cls in classes.values():_verify_generated_class(cls,str(cls._iid_),generated_pin)
    rows=[]
    for name in FIELD_ORDER:
        cls=classes['ICWTool' if name in TOOL_FIELDS else 'ICWMillTool']
        typ=BSTR if name in TEXT_FIELDS else c_long if name in geometry.INTEGER_FIELDS else c_double
        for prefix,arg,direction,access in (('_get_',POINTER(typ),10,'propget'),('_set_',typ,1,'propput')):
            methods=[v for v in cls._methods_ if v.name==prefix+name]
            require(len(methods)==1,'Exact candidate field declaration required: '+name)
            method=methods[0]
            require(method.restype is HRESULT and method.argtypes==(arg,) and len(method.paramflags)==1
                and method.paramflags[0][0]==direction and access in method.idlflags,'Candidate property ABI differs: '+name)
        rows.append(dict(interface=cls.__name__,member=name,read=True,write=True))
    for name,typ in (('MillToolType',c_long),('MillToolSubType',c_long),('EndRadius',c_double)):
        methods=[v for v in classes['ICWMillTool']._methods_ if v.name=='_get_'+name]
        require(len(methods)==1 and methods[0].restype is HRESULT and methods[0].argtypes==(POINTER(typ),)
            and len(methods[0].paramflags)==1 and methods[0].paramflags[0][0]==10,'Exact factory classification getter required')
        rows.append(dict(interface='ICWMillTool',member=name,read=True,write=False))
    for owner,name,types,flags in (
        ('ICWToolcrib4','AddNewTool3',(c_long,POINTER(POINTER(IDispatch))),(1,10)),
        ('ICWMillToolHolder','SetFilePathForUserDefinedHolder',(BSTR,),(1,)),
        ('ICWApp','SaveActiveDocument',(),())):
        methods=[v for v in classes[owner]._methods_ if v.name==name]
        require(len(methods)==1 and methods[0].restype is HRESULT and methods[0].argtypes==types
            and tuple(v[0] for v in methods[0].paramflags)==flags,'Exact native action ABI differs: '+name)
        rows.append(dict(interface=owner,member=name,signature_verified=True))
    return dict(all_resolved=True,application_connections=0,native_calls=0,generated_pin=deepcopy(generated_pin),members=rows,
        actual_neck_mapping_qualified=False,flat_factory_variant_qualified=False)


INACTIVE={'sw_cam_mill_generic_cl.py','sw_cam_thread_postprocess.py','sw_cam_operation_profile.py',
    'sw_cam_generic_cl_reader.py','sw_cam_chamfer_cl_review.py','sw_cam_chamfer_receipt.py',
    'sw_cam_raw_mill_face_move.py','sw_cam_chamfer_insert_defaults.py'}
PARAMS=(common.COMMON-{'acknowledge_machine_scope'})|{'recipe_path','recipe_sha256',
    'protected_cl_receipt_path','protected_cl_receipt_sha256','protected_cl_path'}
AUTHORITY='saved_neck_tool_candidate_unassigned'


def marker_path(source,sha):
    from scripts.sw_cam_turn_tool import _digest
    return common.local_evidence_root()/('neck_tool_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha))+'.json')


def load_inputs(p):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    loaded=rough.load_checkpoint(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**{k:p[k] for k in
        ('process_id','expected_document_path','expected_source_sha256','protected_cl_receipt_path','protected_cl_receipt_sha256','protected_cl_path')})
    recipe,recipepin=read_pin(p['recipe_path'],p['recipe_sha256']);validate_recipe(recipe)
    holder=deepcopy(loaded['holder_recipe']);check_holder_pins(holder)
    require(loaded['generated_face_operation_id']==267,'Current FACE anchor required')
    retired=[v for v in loaded['pins'] if Path(v['path']).name in INACTIVE]
    require({Path(v['path']).name for v in retired}==INACTIVE,'Exact inactive prior phase roles required')
    names=('sw_cam_shared_cutter_geometry','sw_cam_shared_holder_geometry','sw_cam_ud14_save','sw_cam_ud14_qualification')
    added=[common._pin(__file__),common._pin(geometry.__file__)]+[common._pin(importlib.import_module('scripts.'+n).__file__) for n in names]
    pins=common._merge([v for v in loaded['pins'] if v not in retired],added,holder['pins'])
    offline=common._merge(loaded['offline_export_proof_pins'],retired,[recipepin],recipe['source_pins'])
    require(len(pins)<=64,'Bounded neck tool live closure required')
    common._check(pins);common._check(offline);common._check(loaded['bootstrap_export_pins'])
    registration=common.discover_export_registration(loaded,p['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_interfaces(typelib,loaded['generated_pin'])
    return dict(loaded,pins=pins,offline_export_proof_pins=offline,neck_phase_retired_pins=retired),recipe,recipepin,registration,typelib,audit


def prepare(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='create_neck_tool',
        'Only one tool-only creation/configuration/save action allowed')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact neck candidate request required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Positive owned PID required')
    for name,value in p.items():
        if name.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if name.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute input/output path required')
    require(p['module_sha256']==prior._file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['message_policy']=='vendor_default','Exact qualified one-tool request required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']), 'Exact CAM registration required')
    loaded,recipe,recipepin,registration,typelib,audit=load_inputs(p)
    receipt=Path(p['receipt_path']);common._local_receipt(receipt)
    marker=marker_path(p['expected_document_path'],p['expected_source_sha256'])
    context_path=receipt.with_suffix('.context.json')
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']}
    protected.add(common._key(p['expected_document_path']))
    require(all(v.is_absolute() and v.suffix.casefold()=='.json' and v.parent.is_dir() and not v.exists() and not v.is_symlink()
        for v in (receipt,marker,context_path)),'Fresh receipt and source-bound once marker required; no replay')
    require(len(set(map(common._key,(receipt,marker,context_path))))==3
        and not protected.intersection(map(common._key,(receipt,marker,context_path))), 'Output aliases protected input')
    return deepcopy(p),loaded,recipe,recipepin,registration,typelib,audit,marker


def make_checkpoint(r,loaded,recipe):
    context=deepcopy(loaded)
    context.update(state=deepcopy(r['final_state']),source_sha256=r['saved_source_sha256'])
    context['state']['saved_file_sha256']=r['saved_source_sha256']
    context['state']['document']['needs_save']=False
    context['neck_tool_candidate']=dict(native_id=r['new_tool_native_id'],**deepcopy(r['final_candidate']))
    context['neck_tool_checkpoint']=dict(catalogue=deepcopy(r['final_observation']['tools']),
        profile_qualification=deepcopy(r['candidate_qualification']),recipe=deepcopy(recipe),parent_saved_pin=deepcopy(loaded['parent_pin']))
    context['current_context_sha256']=prior._digest(group.current_projection(context))
    return dict(context=context,source_sha256=r['saved_source_sha256'])


def validate_terminal(r):
    require(r.get('scope')==SCOPE and r.get('status')=='review_required' and r.get('phase')=='finished'
        and r.get('readback_verified') is True and r.get('model_saved') is True and r.get('exact_one_tool_created') is True
        and r.get('phase_proofs_verified') is True,'Completed saved candidate receipt required')
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
    verify_protected(r['initial_observation'],r['final_observation'],r['new_tool_native_id'])
    require(type(r['new_tool_native_id']) is int and r['final_candidate']['full_tool']['tool_native_id']==r['new_tool_native_id'],
        'Final complete profile must belong to the actual created tool')
    verify_candidate(r['final_candidate'],r['recipe'],r['holder_recipe'])
    require(prior._digest(r['checkpoint'])==r['checkpoint_digest'],'Saved checkpoint digest differs')
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    initial,_=read_pin(r['loaded_context_pin']['path'],r['loaded_context_pin']['sha256'])
    require(group.exact(r['checkpoint'],make_checkpoint(r,initial,r['recipe'])),
        'Saved flat checkpoint differs from terminal evidence')


def execute(sw,clsid,typelib,*,p,loaded,recipe,recipepin,audit,marker):
    args={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256','qualification_only','acknowledge_disposable_copy','message_policy')}
    context_path=Path(p['receipt_path']).with_suffix('.context.json')
    _write_receipt(context_path,loaded,create=True);context_pin=common._pin(context_path)
    r=dict(schema_version=1,scope=SCOPE,status='error',phase='prepared',source_path=p['expected_document_path'],
        initial_source_sha256=p['expected_source_sha256'],process_id=p['process_id'],receipt_path=p['receipt_path'],
        module_pin=common._pin(__file__),parent_pin=deepcopy(loaded['parent_pin']),recipe_pin=recipepin,recipe=deepcopy(recipe),
        holder_recipe=deepcopy(loaded['holder_recipe']),loaded_context_pin=context_pin,
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),interface_audit=audit,
        actions={},mutation_attempted=False,readback_verified=False,model_saved=False,phase_proofs_verified=False,
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
    require(len(context['pins'])<=64,'Bounded current candidate context required')
    common._check(context['pins']);common._check(context['offline_export_proof_pins'])
    return context


def dispatch_request(request,*,validate_only=False):
    p,loaded,recipe,recipepin,registration,typelib,audit,marker=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),
        prior_tool_count=18,generated_operation_contract=rough.operation_contract(loaded),interface_audit=audit,
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
