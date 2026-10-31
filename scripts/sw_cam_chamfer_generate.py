"""Configure and generate one saved Contour operation using an existing tool.

The saved eight-operation context remains explicit. No feature geometry, tool
profile, prior operation, operation insertion, or global generation is changed.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
from scripts import sw_cam_chamfer_insert_defaults as prior
from scripts import sw_cam_chamfer_saved_parent as history
from scripts import sw_cam_chamfer_defaults as defaults
from scripts import sw_cam_taper_tool_candidate as tools
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events

group, exports = prior.group, prior.exports
SCOPE = 'SAVED_CONTOUR_CHAMFER_GENERATE_V1'
# One reviewed spelling for each write; no alternative setters or retries.
FIELDS = (
 ('chamfer_mode','ICWFinishMillOp3','GetIsChamferMachining','SetIsChamferMachining','method',True),
 ('geometry_mode','ICWFinishMillOp3','GetChamferType','SetChamferType','method',1),
 ('chamfer_length','ICWFinishMillOp3','GetChamferLength','SetChamferLength','method',.2),
 ('side_allowance','ICWFinishMillOp','SideAllow','SideAllow','property',0.),
 ('depth_allowance','ICWFinishMillOp','DepthAllow','DepthAllow','property',0.),
 ('spring_passes','ICWFinishMillOp','SpringPass','SpringPass','property',0),
 ('depth_override','ICWMillOperation3','GetOverrideMachiningDepth','SetOverrideMachiningDepth','feature',True),
 ('machining_depth','ICWMillOperation3','GetMachiningDepthValue','SetMachiningDepthValue','feature',.5),
 ('chamfer_clearance','ICWFinishMillOp3','GetChamferClearance','SetChamferClearance','method',.3),
)


def target_row(loaded):
    new = loaded['inserted_contour']
    oid, fid = new['native_id'], new['feature_native_id']
    rows = [v for v in loaded['state']['operations'] if v['native_id'] == oid]
    require(len(rows) == 1 and len(loaded['state']['operations']) == 8
        and loaded['state']['operation_count'] == 8, 'Exact saved eight-operation context required')
    row = rows[0]
    require(row['mill_operation_type'] == 1 and row['linked_feature_ids'] == [fid]
        and row['suppressed'] is False and row['toolpath_generated'] is False
        and row['toolpath_record_counts'] == [], 'Existing ungenerated linked Contour required')
    return row


def expected_tool(loaded):
    candidate = loaded['local_tool_candidate']
    require(candidate['tool_type_raw'] == 8 and candidate['native_id'] > 0,
            'Qualified existing tapered tool required')
    p = candidate['parameters']
    require(p['CutDiameter'] == .6 and p['EndDia'] == .6 and tools.scalar_equal(p['MaxDia'],2.)
        and p['Protrusion'] == 20., 'Saved qualified flat/max diameter or protrusion differs')
    return dict(native_id=candidate['native_id'],is_mill_tool=True,native_read_complete=True,
        units_verified=False,holder_geometry_verified=False,tool_type_raw=8,
        cut_diameter_native=p['CutDiameter'],protrusion_native=p['Protrusion'])


def verify_observation(loaded, baseline, observed, *, assigned, generated):
    a, b = baseline['route'], deepcopy(observed['route'])
    oid = loaded['inserted_contour']['native_id']
    before = next(x for x in a['operations'] if x['native_id'] == oid)
    rows = [x for x in b['operations'] if x['native_id'] == oid]
    require(len(rows) == 1, 'Unique current target required')
    row = rows[0]
    wanted = expected_tool(loaded) if assigned else before['assigned_tool']
    require(group.exact(row['assigned_tool'],wanted), 'Exact target tool binding differs')
    require(row['toolpath_generated'] is generated, 'Target generation flag differs')
    counts = row['toolpath_record_counts']
    require(type(counts) is list and all(type(x) is int and x > 0 for x in counts)
        and (bool(counts) is generated), 'Actual positive generated records or exact empty definition required')
    for key in ('assigned_tool','toolpath_generated','toolpath_record_counts'):
        row[key] = deepcopy(before[key])
    require(group.exact(a,b), 'Protected route, prior counts, settings, bindings or units changed')
    require(group.exact(baseline['tools'],observed['tools']), 'Local tool catalogue changed')
    require(group.exact(baseline['feature'],observed['feature']), 'Feature geometry header/taper changed')
    return deepcopy(counts)


def expected_settings(initial, *, raw_tool_angle):
    result = deepcopy(initial)
    f = result['finish']
    f.update(GetIsChamferMachining=True,GetChamferType=1,GetChamferLength=.2,
             GetChamferClearance=.3,SideAllow=0.,DepthAllow=0.,SpringPass=0,GetChamferAngle=raw_tool_angle)
    result['level_state']['levels'].update(
        machining_depth_native=.5,override_machining_depth=True,machining_depth_value_native=.5)
    return result


class Journal(tools.Journal):
    def marker_state(self):
        r = self.report
        return dict(scope=SCOPE,receipt_path=str(self.receipt),source_path=r['source_path'],
            initial_source_sha256=r['initial_source_sha256'],phase=r['phase'],
            operation_native_id=r['operation_native_id'],feature_native_id=r['feature_native_id'],
            tool_native_id=r['tool_native_id'],actions=deepcopy(r['actions']),
            readback_verified=r.get('readback_verified',False),
            saved_source_sha256=r.get('saved_source_sha256'),automatic_replay=False)


def marker_path(source,source_sha256,operation_id):
    key = _digest(dict(scope=SCOPE,source=exports._key(source),source_sha256=source_sha256,
                       operation_native_id=operation_id))
    return exports.local_evidence_root()/('chamfer_generate_'+key+'.json')


def audit_recipe_interfaces(typelib_path,generated_pin):
    from ctypes import HRESULT, c_double, c_long, POINTER
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class
    names={x[1] for x in FIELDS}|{'ICWMillOperation'}
    prior.audit_interfaces(names,typelib_path,generated_pin=generated_pin)
    rows=[]
    specs=[(s[1],s[3],s[4],s[-1]) for s in FIELDS]
    specs += [('ICWMillOperation','SetTool','dispatch',None),
              ('ICWMillOperation','GenerateToolpath','noargs',None)]
    for interface,name,kind,value in specs:
        cls=_interface_class(interface,typelib_path)
        declared_name=('_set_'+name) if kind=='property' else name
        found=[x for x in cls._methods_ if x.name==declared_name
               and ('propput' in x.idlflags if kind=='property' else 'propput' not in x.idlflags)]
        require(len(found)==1,'One exact native setter declaration required: '+name)
        declared=found[0]
        if kind=='dispatch':types=(POINTER(IDispatch),)
        elif kind=='noargs':types=()
        else:
            scalar=VARIANT_BOOL if type(value) is bool else c_long if type(value) is int else c_double
            types=((POINTER(IDispatch),) if kind=='feature' else ())+ (scalar,)
        require(declared.restype is HRESULT and declared.argtypes==types
            and len(declared.paramflags)==len(types)
            and all(x[0]==1 for x in declared.paramflags),'Exact native write ABI differs: '+name)
        rows.append(dict(interface=interface,member=name,kind=kind,dispid=int(declared.idlflags[0])))
    return dict(all_resolved=True,native_calls=0,generated_pin=deepcopy(generated_pin),members=rows)


class NativeBackend(prior.NativeBackend):
    def start(self):
        self.report['recipe_interface_audit']=audit_recipe_interfaces(
            self.typelib_path,self.loaded['generated_pin'])
        self.persist()
        super().start()

    def target(self,g):
        fid, oid = self.args['feature_native_id'], self.args['operation_native_id']
        found = g.read(self.native['doc'],'GetCWObjectFromID',3,oid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,
                'Exact current target lookup required')
        raw = found[0]; op = g.typed(raw,'ICWOperation')
        require(_object_id(self.native['doc'],op,g.read)==oid, 'Target operation identity changed')
        links = [_object_id(self.native['doc'],v,g.read)
                 for v in _items(g.read(op,'IGetAllFeatures'),g.typed,g.read,2)]
        mill = g.typed(raw,'ICWMillOperation')
        require(links==[fid] and g.read(mill,'OpernType')==1
                and g.read(op,'Suppressed') is False, 'Current target linkage/type changed')
        found = g.read(self.native['doc'],'GetCWObjectFromID',1,fid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,
                'Exact target feature lookup required')
        feature = g.typed(found[0],'ICWFeature')
        require(_object_id(self.native['doc'],feature,g.read)==fid, 'Target feature identity changed')
        self.native['operations'][oid] = raw
        return raw, feature

    def feature_dispatch(self,g,feature):
        from comtypes.automation import IDispatch
        result = g.read(feature,'QueryInterface',IDispatch)
        require(_object_id(self.native['doc'],result,g.read)==self.args['feature_native_id'],
                'Feature dispatch identity differs')
        return result

    def current_tool(self):
        with self.ctx.guard() as g:
            raw,_ = self.target(g)
            row,_ = read_generic_tool(raw,self.native['doc'],g.read,g.typed)
        return row

    def assign(self,pending):
        from comtypes.automation import IDispatch
        tid = self.args['tool_native_id']
        batch = self.batch(max_native_calls=tools.CATALOGUE_BATCH_CALLS)
        selected = None; ids = []
        try:
            with batch:
                for raw in _items(batch.read(self.crib,'GetAllTools'),batch.typed,batch.read,tools.MAX_TOOLS):
                    tool = batch.typed(raw,'ICWTool')
                    ident = _object_id(self.native['doc'],tool,batch.read);ids.append(ident)
                    if ident == tid:
                        require(selected is None,'Duplicate selected tool identity')
                        require(batch.read(tool,'ToolType')==8 and batch.read(tool,'IsMillTool') is True
                            and batch.read(tool,'CutDiameter')==self.loaded['local_tool_candidate']['parameters']['CutDiameter']
                            and batch.read(tool,'Protrusion')==self.loaded['local_tool_candidate']['parameters']['Protrusion'],
                            'Qualified selected tool scalar fields changed')
                        selected = tool
            batch.require_complete()
        finally:
            self.report['assignment_catalogue_batch'] = batch.summary();self.persist()
        require(ids==[x['native_id'] for x in self.loaded['operation_checkpoint']['final_observation']['tools']]
                and selected is not None,'Exact current catalogue and selected existing tool required')
        with self.ctx.guard() as g:
            raw,_ = self.target(g)
            require(_object_id(self.native['doc'],selected,g.read)==tid,'Assignment tool identity changed')
            dispatch = g.read(selected,'QueryInterface',IDispatch)
            require(_object_id(self.native['doc'],dispatch,g.read)==tid,'Assignment dispatch identity changed')
            op = g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(op,'SetTool',dispatch),persist_pending=pending)

    def angle(self):
        with self.ctx.guard() as g:
            raw,_ = self.target(g)
            result = g.read(g.typed(raw,'ICWFinishMillOp3'),'GetChamferAngle')
        return defaults.scalar('GetChamferAngle',result)

    def field(self,spec):
        _, interface, getter, _, kind, wanted = spec
        with self.ctx.guard() as g:
            raw,feature = self.target(g)
            obj = g.typed(raw,interface)
            args = [self.feature_dispatch(g,feature)] if kind=='feature' else []
            value = g.read(obj,getter,*args)
        require(type(value) is type(wanted),'Strict affected getter type differs')
        return value

    def write_field(self,spec,value,pending):
        _,interface,_,setter,kind,_ = spec
        with self.ctx.guard() as g:
            raw,feature = self.target(g)
            obj = g.typed(raw,interface)
            args = [self.feature_dispatch(g,feature)] if kind=='feature' else []
            return g.dispatch_once(
                (lambda:setattr(obj,setter,value)) if kind=='property'
                else (lambda:_member(obj,setter,*args,value)),persist_pending=pending)

    def depth_readback(self):
        with self.ctx.guard() as g:
            raw,feature = self.target(g);dispatch = self.feature_dispatch(g,feature)
            op = g.typed(raw,'ICWMillOperation');op3=g.typed(raw,'ICWMillOperation3')
            return dict(machining_depth=g.read(op,'GetMachiningDepth',dispatch),
                override=g.read(op3,'GetOverrideMachiningDepth',dispatch),
                stored_depth=g.read(op3,'GetMachiningDepthValue',dispatch))

    def generate(self,pending):
        with self.ctx.guard() as g:
            raw,_=self.target(g);op=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(op,'GenerateToolpath'),persist_pending=pending)


def run_backend(backend,journal,loaded):
    r=journal.report;persist=journal.persist
    oid=loaded['inserted_contour']['native_id']
    try:
        backend.start()
        before=backend.snapshot('before');r['before']=before
        require(group.exact(before['route'],tools.expected_route(loaded))
            and group.exact(before['tools'],loaded['operation_checkpoint']['final_observation']['tools'])
            and group.exact(before['feature'],loaded['cone_observation']['feature']),
            'Fresh current state differs from saved eight-operation authority')
        settings=backend.operation_defaults(oid,'before_configuration')
        require(group.exact(settings,loaded['inserted_contour']['defaults']),'Saved target defaults changed')
        r['defaults_before']=settings;persist()
        desired=expected_tool(loaded)
        old=next(x['assigned_tool'] for x in before['route']['operations'] if x['native_id']==oid)
        r['assignment_before']=deepcopy(old)
        if not group.exact(old,desired):
            value=backend.assign(lambda:journal.pending('SetTool'))
            journal.returned('SetTool',value)
            require(type(value) is int and value==0,'Strict SetTool HRESULT zero required')
            backend.refresh_dirty()
        r['assignment_after']=backend.current_tool()
        require(group.exact(r['assignment_after'],desired),'Immediate assignment readback differs')
        r['assigned_tool_angle_raw']=backend.angle()
        r['angle_readback_is_not_physical_qualification']=True
        persist()
        for spec in FIELDS:
            key,_,_,_,kind,wanted=spec
            actual=backend.field(spec)
            record=dict(field=key,before=actual,requested=wanted,attempted=False)
            r.setdefault('field_readbacks',[]).append(record);persist()
            if not tools.scalar_equal(actual,wanted):
                label='field:'+key
                value=backend.write_field(spec,wanted,lambda label=label:journal.pending(label))
                journal.returned(label,value)
                require((value is None) if kind=='property' else (type(value) is int and value==0),
                        'Exact property/HRESULT outcome required')
                record['attempted']=True
                backend.refresh_dirty()
                actual=backend.field(spec)
            record['actual']=actual;persist()
            require(tools.scalar_equal(actual,wanted),'Immediate parameter readback differs: '+key)
            if key=='machining_depth':
                r['depth_readback']=backend.depth_readback();persist()
                require(group.exact(r['depth_readback'],dict(machining_depth=.5,override=True,stored_depth=.5)),
                        'Both depth getters must confirm selected machining boundary')
        configured=backend.snapshot('configured')
        verify_observation(loaded,before,configured,assigned=True,generated=False)
        cfg=backend.operation_defaults(oid,'configured');defaults.validate_defaults(cfg)
        require(group.exact(cfg,expected_settings(settings,raw_tool_angle=cfg['finish']['GetChamferAngle'])),
                'Configured target differs beyond reviewed parameters and derived angle')
        r.update(configured_observation=configured,configured_defaults=cfg);persist()
        value=backend.generate(lambda:journal.pending('GenerateToolpath'))
        journal.returned('GenerateToolpath',value)
        require(type(value) is int and value==0,'Strict target GTP HRESULT zero required')
        backend.refresh_dirty()
        generated=backend.snapshot('generated')
        r['generated_record_counts']=verify_observation(loaded,before,generated,assigned=True,generated=True)
        generated_defaults=backend.operation_defaults(oid,'generated')
        require(group.exact(cfg,generated_defaults),'GTP changed accepted target parameters')
        r.update(generated_observation=generated,generated_defaults=generated_defaults);persist()
        expected=dict(observation=generated,defaults=generated_defaults)
        def capture(label):
            if label=='before':
                backend.boundary();return deepcopy(expected)
            observed=backend.snapshot('saved')
            counts=verify_observation(loaded,before,observed,assigned=True,generated=True)
            require(group.exact(counts,r['generated_record_counts']),'Save changed target record counts')
            values=backend.operation_defaults(oid,'saved')
            r.update(final_observation=observed,final_defaults=values,final_state=deepcopy(backend.current_state))
            persist();return dict(observation=observed,defaults=values)
        def verify(observed):
            require(group.exact(expected,observed),'Save changed route, catalogue or target settings')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            digest=backend.saved_hash(r['save_stage'])
            require(digest!=r['initial_source_sha256'],'Changed generated definition must change saved source')
            r['saved_source_sha256']=digest;persist();return digest
        r['save_stage']={}
        run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        backend.finish()
        r.update(phase='finished',status='review_required',readback_verified=True,model_saved=True,
                 target_generated=True)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',
                 failed_phase=r['phase'],readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        persist()
    return r


def derive_closure(loaded,recipe_pin):
    # No taper-profile/interface reader runs in this operation-only phase.
    # The exact extension remains an immutable before/after historical proof.
    retired=[p for p in loaded['pins'] if Path(p['path']).name=='sw_cam_taper_interfaces.py']
    require(len(retired)==1,'Exact completed taper-interface phase proof required')
    live=exports._merge([p for p in loaded['pins'] if p!=retired[0]],[exports._pin(__file__)])
    offline=exports._merge(loaded['offline_export_proof_pins'],retired,
        [exports._pin(history.__file__),loaded['insertion_source_archive_pin'],recipe_pin])
    require(len(live)<=64,'Complete live dependency limit exceeded')
    exports._check(live);exports._check(offline)
    return live,offline,retired


def validate_recipe(recipe):
    require(type(recipe) is dict and set(recipe)=={'fields','physical_target','angle_policy','preserved_defaults','source_pins'},
            'Exact reviewed recipe shape required')
    require(group.exact(recipe['fields'],[dict(field=s[0],target=s[-1]) for s in FIELDS]),
            'Only reviewed fixed target values supported')
    require(group.exact(recipe['physical_target'],dict(chamfer_width_mm=.2,flank_degrees=45.,
        tool_tip_world_z_mm=25.5,tool_axis_radius_mm=22.75,profile='accepted_existing_tool')),
        'Reviewed nominal physical target differs')
    require(recipe['angle_policy']=='raw_getter_preserved_physical_acceptance_requires_CL',
        'Do not infer physical qualification from one getter')
    require(group.exact(recipe['preserved_defaults'],
        dict(OverridePrevAllow=False,GetPreviousAllowance=1.,GetContainType=0,GetContainAllowance=2.54)),
        'Reviewed inherited cut/containment settings differ')
    require(type(recipe['source_pins']) is list and 1<=len(recipe['source_pins'])<=8,
            'Bounded immutable source proof required')
    exports._check(recipe['source_pins'])


def load_inputs(params,*,check_current=True):
    identity={k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    loaded=history.load_historical_chamfer_parent(params['checkpoint_receipt_path'],
        params['checkpoint_receipt_sha256'],historical_source_path=params['insertion_source_archive_path'],**identity)
    if check_current:
        require(_file_hash(params['expected_document_path'])==params['expected_source_sha256'],
                'Current source differs from saved insertion')
    row=target_row(loaded)
    require(row['native_id']==params['operation_native_id']
        and row['linked_feature_ids']==[params['feature_native_id']]
        and loaded['local_tool_candidate']['native_id']==params['tool_native_id'],
        'Exact saved target/feature/tool identities required')
    expected_tool(loaded)
    recipe,recipepin=read_pin(params['recipe_path'],params['recipe_sha256']);validate_recipe(recipe)
    for field,value in recipe['preserved_defaults'].items():
        require(group.exact(loaded['inserted_contour']['defaults']['finish'][field],value),
                'Saved default differs from reviewed preservation decision')
    live,offline,retired=derive_closure(loaded,recipepin)
    offline=exports._merge(offline,recipe['source_pins'])
    exports._check(offline)
    return dict(loaded,pins=live,offline_export_proof_pins=offline,
                recipe=recipe,recipe_pin=recipepin,generation_phase_retired_pins=retired)


def prepare(params):
    loaded=load_inputs(params)
    marker=marker_path(params['expected_document_path'],params['expected_source_sha256'],params['operation_native_id'])
    exports._local_receipt(params['receipt_path'])
    protected={exports._key(x['path']) for x in loaded['pins']+loaded['offline_export_proof_pins']}
    protected.add(exports._key(params['expected_document_path']))
    require(not Path(params['receipt_path']).exists() and not Path(params['receipt_path']).is_symlink()
        and not marker.exists() and not marker.is_symlink()
        and exports._key(params['receipt_path']) not in protected and exports._key(marker) not in protected
        and exports._key(params['receipt_path'])!=exports._key(marker),'Fresh local evidence and stable once-marker required')
    r=dict(schema_version=1,scope=SCOPE,status='running',phase='prepared',actions={},
        process_id=params['process_id'],source_path=params['expected_document_path'],
        initial_source_sha256=params['expected_source_sha256'],receipt_path=params['receipt_path'],
        module_pin=exports._pin(__file__),parent_pin=deepcopy(loaded['parent_pin']),
        insertion_source_archive_pin=deepcopy(loaded['insertion_source_archive_pin']),
        operation_native_id=params['operation_native_id'],feature_native_id=params['feature_native_id'],
        tool_native_id=params['tool_native_id'],recipe=deepcopy(loaded['recipe']),recipe_pin=deepcopy(loaded['recipe_pin']),
        current_before=group.current_projection(loaded),current_before_sha256=loaded['current_context_sha256'],
        settings_before=deepcopy(loaded['settings']),generated_face_operation_id=loaded['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(loaded['toolpath_record_counts']),
        local_tool_candidate=deepcopy(loaded['local_tool_candidate']),profile_contract=deepcopy(loaded['profile_contract']),
        candidate_qualification=deepcopy(loaded['candidate_qualification']),insertion_provenance=deepcopy(loaded['inserted_contour']),
        live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        phase_retired_pins=deepcopy(loaded['generation_phase_retired_pins']),
        mutation_attempted=False,readback_verified=False,model_saved=False,
        operation_creation_attempted=False,tool_creation_attempted=False,tool_edit_attempted=False,
        feature_edit_attempted=False,GOP_attempted=False,global_generation_attempted=False,
        automatic_retry=False,automatic_replay=False,production_qualified=False,
        geometry_acceptance_complete=False,phase_proofs_verified_after_native=False,full_tool_profile_capture_count=0)
    return loaded,r,marker


def make_checkpoint(r):
    current=deepcopy(r['current_before'])
    current.update(state=deepcopy(r['final_state']),source_sha256=r['saved_source_sha256'])
    return dict(current=current,settings=deepcopy(r['settings_before']),
        generated_face_operation_id=r['generated_face_operation_id'],toolpath_record_counts=deepcopy(r['toolpath_record_counts']),
        local_tool_candidate=deepcopy(r['local_tool_candidate']),profile_contract=deepcopy(r['profile_contract']),
        candidate_qualification=deepcopy(r['candidate_qualification']),
        insertion_provenance=deepcopy(r['insertion_provenance']),
        configured_contour=dict(native_id=r['operation_native_id'],feature_native_id=r['feature_native_id'],
            tool_native_id=r['tool_native_id'],operation_type=1,defaults=deepcopy(r['final_defaults']),
            generated=True,record_counts=deepcopy(r['generated_record_counts']),
            physical_target=deepcopy(r['recipe']['physical_target']),geometry_acceptance_complete=False))


def validate_terminal(r,loaded):
    require(r['scope']==SCOPE and r['status']=='review_required' and r['phase']=='finished'
        and r['readback_verified'] is True and r['model_saved'] is True and r['target_generated'] is True
        and r['phase_proofs_verified_after_native'] is True,'Completed saved single-target generation required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error','receipt_write_error')),
            'Uncertain result cannot become checkpoint')
    for key in ('operation_creation_attempted','tool_creation_attempted','tool_edit_attempted','feature_edit_attempted',
        'GOP_attempted','global_generation_attempted','automatic_retry','automatic_replay',
        'production_qualified','geometry_acceptance_complete'):
        require(r[key] is False,'Forbidden generation claim or action: '+key)
    require(type(r['full_tool_profile_capture_count']) is int and r['full_tool_profile_capture_count']==0,
            'Tool profiles must be reused, not requalified')
    require(group.exact(group.current_projection(loaded),r['current_before'])
        and r['current_before_sha256']==_digest(r['current_before'])
        and all(group.exact(loaded[k],r[k]) for k in ('recipe','settings_before') if k in loaded),
        'Exact current authority required')
    for source,dest in (('settings','settings_before'),('inserted_contour','insertion_provenance'),
        ('generated_face_operation_id','generated_face_operation_id'),('toolpath_record_counts','toolpath_record_counts'),
        ('local_tool_candidate','local_tool_candidate'),('profile_contract','profile_contract'),
        ('candidate_qualification','candidate_qualification')):
        require(group.exact(loaded[source],r[dest]),'Inherited authority differs: '+source)
    require(r['operation_native_id']==loaded['inserted_contour']['native_id']
        and r['feature_native_id']==loaded['inserted_contour']['feature_native_id']
        and r['tool_native_id']==loaded['local_tool_candidate']['native_id'],'Target identity differs')
    audit=r['recipe_interface_audit']
    require(audit['all_resolved'] is True and type(audit['native_calls']) is int
        and audit['native_calls']==0,'Completed offline setter ABI audit required')
    before=r['before']
    require(group.exact(before['route'],tools.expected_route(loaded))
        and group.exact(before['tools'],loaded['operation_checkpoint']['final_observation']['tools'])
        and group.exact(before['feature'],loaded['cone_observation']['feature']),'Baseline differs')
    require(group.exact(r['defaults_before'],loaded['inserted_contour']['defaults']),'Initial settings differ')
    verify_observation(loaded,before,r['configured_observation'],assigned=True,generated=False)
    for name in ('generated_observation','final_observation'):
        counts=verify_observation(loaded,before,r[name],assigned=True,generated=True)
        require(group.exact(counts,r['generated_record_counts']),'Generated counts differ')
    require(group.exact(r['assignment_after'],expected_tool(loaded)),'Assigned tool differs')
    defaults.scalar('GetChamferAngle',r['assigned_tool_angle_raw'])
    cfg=r['configured_defaults'];defaults.validate_defaults(cfg)
    require(group.exact(cfg,expected_settings(r['defaults_before'],raw_tool_angle=cfg['finish']['GetChamferAngle']))
        and group.exact(cfg,r['generated_defaults']) and group.exact(cfg,r['final_defaults']),
        'Configured/generated/saved settings differ')
    require(group.exact(r['depth_readback'],dict(machining_depth=.5,override=True,stored_depth=.5)),
        'Native depth boundary proof differs')
    require([x['field'] for x in r['field_readbacks']]==[x[0] for x in FIELDS],'Exact ordered field sequence required')
    expected_actions={'GenerateToolpath','SaveActiveDocument'}
    if not group.exact(r['assignment_before'],expected_tool(loaded)):expected_actions.add('SetTool')
    for row,spec in zip(r['field_readbacks'],FIELDS):
        require(type(row['attempted']) is bool and tools.scalar_equal(row['requested'],spec[-1])
            and tools.scalar_equal(row['actual'],spec[-1]),'Affected field proof differs')
        attempted=not tools.scalar_equal(row['before'],spec[-1])
        require(row['attempted'] is attempted,'Field attempt provenance differs')
        if attempted:expected_actions.add('field:'+spec[0])
    require(set(r['actions'])==expected_actions,'Exact native action inventory required')
    for name,a in r['actions'].items():
        require(a['attempted'] is True and a['returned'] is True and a['pending'] is False,'Pending native action')
        prop=name.startswith('field:') and next(s[4] for s in FIELDS if 'field:'+s[0]==name)=='property'
        require((a['native_return_type']=='NoneType' and a['native_return_value'] is None) if prop else
            (a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0),
            'Exact native action return required')
    save,transition,sha=r['save_stage'],r['source_transition'],r['saved_source_sha256']
    require(save['save_readback_verified'] is True and save['native_call_returned'] is True
        and save['save_pending'] is False and save['native_return_type']=='int'
        and type(save['native_return_value']) is int and save['native_return_value']==0
        and type(transition['strict_save_return']) is int and transition['strict_save_return']==0
        and sha==save['saved_file_sha256']==transition['source_after_sha256']
        and transition['source_before_sha256']==r['initial_source_sha256']==loaded['source_sha256']
        and sha!=r['initial_source_sha256'],'Changed-source strict Save proof required')
    projection=dict(observation=r['final_observation'],defaults=r['final_defaults'])
    require(group.exact(save['before'],projection) and group.exact(save['after'],projection),'Save projection differs')
    reference=deepcopy(loaded['state'])
    reference['saved_file_sha256']=sha;reference['document']['needs_save']=False
    reference['operations']=deepcopy(r['final_observation']['route']['operations'])
    require(group.exact(reference,r['final_state']) and group.exact(transition['document'],reference['document']),
            'Final state contains an unpermitted change')
    cp=make_checkpoint(r)
    require(group.exact(cp,r['checkpoint']) and _digest(cp)==r['checkpoint_sha256'],'Flat eight-operation checkpoint differs')
    clean_events(r)
    return cp


def execute(sw,clsid,typelib,*,params,loaded,report,marker):
    journal=Journal(report,params['receipt_path'],marker)
    _write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist)
    result=run_backend(backend,journal,loaded)
    try:
        exports._check(loaded['offline_export_proof_pins']);exports._check(loaded['bootstrap_export_pins'])
        result['phase_proofs_verified_after_native']=True
        if result.get('readback_verified') is True:
            result['checkpoint']=make_checkpoint(result);result['checkpoint_sha256']=_digest(result['checkpoint'])
            validate_terminal(result,loaded);journal.persist()
            result['marker_pin']=exports._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Completed marker changed')
    except Exception as exc:
        result.update(status='uncertain',readback_verified=False,phase_proofs_verified_after_native=False,
                      phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==exports._pin(__file__) and r['process_id']==process_id
        and exports._key(r['source_path'])==exports._key(expected_document_path)
        and exports._key(r['receipt_path'])==exports._key(path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),
        'Current saved generation source/runtime/process differs')
    params=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=r['initial_source_sha256'],
        checkpoint_receipt_path=r['parent_pin']['path'],checkpoint_receipt_sha256=r['parent_pin']['sha256'],
        insertion_source_archive_path=r['insertion_source_archive_pin']['path'],
        recipe_path=r['recipe_pin']['path'],recipe_sha256=r['recipe_pin']['sha256'],
        operation_native_id=r['operation_native_id'],feature_native_id=r['feature_native_id'],tool_native_id=r['tool_native_id'])
    loaded=load_inputs(params,check_current=False)
    for source,dest in (('pins','live_pins'),('offline_export_proof_pins','offline_proof_pins'),
        ('generation_phase_retired_pins','phase_retired_pins'),('parent_pin','parent_pin'),
        ('recipe_pin','recipe_pin'),('insertion_source_archive_pin','insertion_source_archive_pin')):
        require(group.exact(loaded[source],r[dest]),'Exact historical authority/closure differs: '+source)
    cp=validate_terminal(r,loaded)
    marker=marker_path(r['source_path'],r['initial_source_sha256'],r['operation_native_id'])
    mark,markerpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(exports._key(marker)==exports._key(r['marker_pin']['path'])
        and group.exact(mark,Journal(r,path,marker).marker_state()),'Stable completed generation marker differs')
    live=exports._merge([p for p in loaded['pins'] if exports._key(p['path'])!=exports._key(r['parent_pin']['path'])],[pin])
    offline=exports._merge(loaded['offline_export_proof_pins'],[r['parent_pin'],markerpin])
    result=dict(cp['current'],pins=live,parent_pin=pin,group_marker_pin=markerpin,
        current_context_sha256=_digest(cp['current']),generated_pin=deepcopy(loaded['generated_pin']),
        settings=deepcopy(cp['settings']),generated_face_operation_id=cp['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        local_tool_candidate=deepcopy(cp['local_tool_candidate']),profile_contract=deepcopy(cp['profile_contract']),
        candidate_qualification=deepcopy(cp['candidate_qualification']),configured_contour=deepcopy(cp['configured_contour']),
        insertion_provenance=deepcopy(cp['insertion_provenance']),tool_checkpoint=loaded['tool_checkpoint'],
        insertion_checkpoint=loaded['operation_checkpoint'],operation_checkpoint=r,
        offline_export_proof_pins=offline,bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),
        authority_kind='saved_generated_contour_geometry_review_pending')
    exports._check(live);exports._check(offline)
    return result


PARAMS=frozenset({'process_id','expected_document_path','expected_source_sha256','checkpoint_receipt_path',
    'checkpoint_receipt_sha256','insertion_source_archive_path','recipe_path','recipe_sha256',
    'module_sha256','addin_clsid','feature_native_id','operation_native_id','tool_native_id',
    'qualification_only','acknowledge_disposable_copy','acknowledge_machine_scope','message_policy','receipt_path'})


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action']=='configure_generate_chamfer','Exact existing-operation generation action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact bounded request fields required')
    for key in ('process_id','feature_native_id','operation_native_id','tool_native_id'):
        require(type(p[key]) is int and 0<p[key]<2**31,'Strict positive identity required')
    for key,value in p.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if key.endswith('path'):
            require(type(value) is str and Path(value).is_absolute(),'Absolute request path required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy']=='vendor_default','Explicit bounded qualification scope required')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact CAM CLSID required')
    return deepcopy(p)


def dispatch_request(request,*,validate_only=False):
    params=validate_request(request);loaded,report,marker=prepare(params)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=params['process_id']):
        exports._check(loaded['pins']);exports._check(loaded['offline_export_proof_pins'])
        registration=exports.discover_export_registration(loaded,params['addin_clsid'])
        typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
        audit=audit_recipe_interfaces(typelib,loaded['generated_pin'])
        if validate_only:
            return dict(status='validated_offline',readback_verified=True,native_called=False,
                        recipe_interface_audit=audit,live_pin_count=len(loaded['pins']))
        sw,_=connect_solidworks(process_id=params['process_id'],launch_new_instance=False,wait_seconds=1)
        report['bootstrap_validation']=deepcopy(loaded['bootstrap_validation'])
        return execute(sw,registration['clsid'],typelib,params=params,loaded=loaded,report=report,marker=marker)


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True)
    p.add_argument('--validate-only',action='store_true');args=p.parse_args(argv)
    result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','operation_native_id',
        'saved_source_sha256','issue')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1


if __name__=='__main__':raise SystemExit(main())
