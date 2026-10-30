"""Configure one existing standard finish cutter on a pinned saved route.

No operation creation, tool assignment, generation, implicit save or export.
The existing scalar writer and custom-holder writer remain unchanged.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_route_manifest import load_saved_route_manifest
from scripts.sw_cam_route_checkpoint import RouteCheckpointContext, capture_route_checkpoint
from scripts.sw_cam_route_entry_continuation import _events
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_mill_levels import read_mill_level_values
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_finish_observation import read_finish_details
from scripts.sw_cam_finish_lead_observation import read_lead_details, query_lead_interface
from scripts.sw_cam_shared_cutter_config import apply_property_batch
from scripts.sw_cam_shared_cutter_geometry import FIELDS, values
from scripts.sw_cam_shared_holder_geometry import read_holder_recipe, check_holder_pins, apply_holder_reference
from scripts.sw_cam_straight_cutter_geometry import validate_target, verify_full_delta
from scripts.sw_cam_rough_firstcut import require

SCOPE = 'SAVED_ROUTE_FINISH_RECIPE_V1'
EXTRA_MODULES = ('sw_cam_finish_recipe.py', 'sw_cam_straight_cutter_geometry.py',
    'sw_cam_shared_cutter_config.py', 'sw_cam_shared_cutter_geometry.py',
    'sw_cam_shared_holder_geometry.py', 'sw_cam_mill_tool_geometry.py',
    'sw_cam_mill_inventory_geometry.py')


def extra_runtime_paths():
    return [str(Path(__file__).resolve().with_name(n)) for n in EXTRA_MODULES]


def selected_finish(state, args):
    require(len(state['features']) == 19 and len(state['feature_setups']) == 3
        and len(state['operation_setups']) == 3 and len(state['operations']) == state['operation_count'] == 6,
        'Exact saved route inventory required')
    rows = [r for r in state['operations'] if r['native_id'] == args['finish_operation_native_id']]
    require(len(rows) == 1, 'Unique finish operation required')
    row = rows[0]; tool = row['assigned_tool']
    require(type(row['native_id']) is int and row['native_id'] != args['target_operation_native_id']
        and row['linked_feature_ids'] == [args['target_feature_native_id']]
        and row['setup_native_id'] == args['target_operation_setup_native_id']
        and type(row['mill_operation_type']) is int and row['mill_operation_type'] == 1
        and row['suppressed'] is False and type(row['toolpath_generated']) is bool,
        'Exact unsuppressed finish definition required')
    require(type(tool['native_id']) is int and tool['native_id'] == args['finish_tool_native_id']
        and tool['is_mill_tool'] is True and tool['native_read_complete'] is True
        and type(tool['tool_type_raw']) is int and tool['tool_type_raw'] == 1,
        'Existing standard cutter identity required')
    require([r['native_id'] for r in state['operations'] if r['assigned_tool']['native_id'] == tool['native_id']]
        == [row['native_id']], 'Finish cutter must not be shared by another operation')
    return row


def capture_finish_recipe(ctx, reference_state, *, holder_recipe, diagnostic):
    """Fresh route/rough settings and finish definition; no full model geometry reread.

    Generated and ungenerated finish states are accepted here. The caller must
    validate the permitted change against its previous checkpoint.
    """
    result = capture_route_checkpoint(ctx, reference_state, diagnostic.setdefault('route', {}))
    state, native, levels, _, entry, candidate = result
    selected = selected_finish(state, ctx.args)
    with ctx.guard() as guard:
        raw = native['operations'][ctx.args['finish_operation_native_id']]
        require(_object_id(native['doc'], raw, guard.read) == ctx.args['finish_operation_native_id'], 'Finish operation changed')
        generic, tool = read_generic_tool(raw, native['doc'], guard.read, guard.typed)
        require(generic == selected['assigned_tool'], 'Assigned finish tool changed')
        found = guard.read(native['doc'], 'GetCWObjectFromID', 1, ctx.args['target_feature_native_id'])
        require(type(found) in (list, tuple) and len(found) == 2 and found[1] is True, 'Exact feature lookup required')
        feature = guard.typed(found[0], 'ICWFeature')
        require(_object_id(native['doc'], feature, guard.read) == ctx.args['target_feature_native_id'], 'Feature ID changed')
        def native_read(label, invoke, decoder=None, interface=False, validator=None):
            value = guard._observe(invoke) if label == 'QueryInterface.IDispatch.feature' else invoke()
            if interface: require(value is not None and bool(value), 'Non-null level interface required')
            if validator: validator(value)
            return decoder(value) if decoder else value
        def getter(obj, interface_name, name, *params, **kw):
            return native_read(interface_name+'.'+name, lambda:guard.read(obj, name, *params), **kw)
        finish_levels = {}
        read_mill_level_values(feature, raw, native_read=native_read, typed=guard.typed, getter=getter, report=finish_levels)
        details = read_finish_details(raw, found[0], tool, read=guard.read, typed=guard.typed,
            diagnostic=diagnostic.setdefault('finish_details', {}))
        leads = read_lead_details(raw, found[0], read=guard.read, typed=guard.typed,
            lead_typed=lambda pointer:guard._observe(lambda:query_lead_interface(pointer, ctx.typelib_path)))
        full = read_full_mill_tool(tool, generic=generic, read=guard.read, typed=guard.typed,
            diagnostic=diagnostic.setdefault('full_tool', {}))
        units = read_document_cam_unit_scope(guard.read(ctx.sw, 'ActiveDoc'), ctx.app,
            sw_read=lambda obj,name:guard.read(obj,name), cam_read=guard.read)
    diagnostic['finish_guard'] = guard.summary()
    check_holder_pins(holder_recipe)
    require(state['document'] == ctx.identity(), 'Document changed during finish capture')
    diagnostic['capture_complete'] = True
    return dict(state=state, native=native,
        rough_payload=dict(candidate=candidate, levels=levels, entry=entry),
        finish_payload=dict(details=details, levels=finish_levels, leads=leads, full_tool=full, unit_record=units))


def public_checkpoint(capture):
    return {k:deepcopy(capture[k]) for k in ('state', 'rough_payload', 'finish_payload')}


def verify_repeated_tool_observations(payload):
    """Require repeated scalar captures to agree before any write."""
    aliases = {prop:key for prop, section, key in FIELDS if section}
    aliases.update(MillToolType='type_raw', MillToolSubType='subtype_raw', EndRadius='end_radius_native')
    for prop, key in aliases.items():
        require(payload['details']['tool'][prop]['raw'] == payload['full_tool']['mill_tool'][key],
            'Repeated cutter observations disagree')
    holder = payload['full_tool']['holder']
    holder_aliases = {'GetHolderShape':'shape', 'GetHolderId':'holder_id_raw', 'GetHolderNumber':'number',
        'GetName':'name', 'GetHolderTopDia':'top_diameter_native', 'GetHolderBottomDia':'bottom_diameter_native',
        'GetHolderOverallLength':'overall_length_native','GetHolderBottomLength':'bottom_length_native','GetProtrusion':'holder_protrusion_native'}
    for prop,key in holder_aliases.items():
        require(payload['details']['holder'][prop]['raw'] == holder[key], 'Repeated holder observations disagree')


def verify_initial_capture(before, loaded, args):
    require(before['state'] == loaded['state'] and before['rough_payload'] == loaded['payload'],
        'Current rough route differs from saved manifest')
    row = selected_finish(before['state'], args)
    require(row['toolpath_generated'] is False and row['toolpath_record_counts'] == [], 'Fresh ungenerated finish required')
    finish = before['finish_payload']; previous = loaded['finish']
    verify_repeated_tool_observations(finish)
    full = finish['full_tool']; mill = full['mill_tool']
    require(full['tool_native_id'] == args['finish_tool_native_id']
        and full['tool_type_raw'] == mill['type_raw'] == 1 and mill['subtype_raw'] == 3
        and mill['shank_type_raw'] == 0 and mill['end_radius_native'] == 0,
        'Current standard straight flat-end identity required before writing')
    for key in ('details', 'levels', 'leads', 'unit_record'):
        require(finish[key] == previous[key], 'Saved finish definition changed: '+key)
    require(row['assigned_tool'] == previous['tool_summary'], 'Saved generic finish cutter changed')
    require(finish['full_tool']['geometry_read_complete'] is True and finish['full_tool']['profile_complete'] is True,
        'Complete current tool profile required')


def verify_recipe_context(before, after, target, args, holder_recipe):
    validate_target(target)
    old, new = before['state'], after['state']
    selected_finish(old, args); new_row = selected_finish(new, args)
    require(new_row['toolpath_generated'] is False and new_row['toolpath_record_counts'] == [], 'Configuration cannot generate finish')
    expected = deepcopy(old)
    require(type(new['document'].get('needs_save')) is bool, 'Strict dirty flag required')
    expected['document']['needs_save'] = new['document']['needs_save']
    for row in expected['operations']:
        if row['native_id'] == args['finish_operation_native_id']:
            row['assigned_tool']['cut_diameter_native'] = target['CutDiameter']
            row['assigned_tool']['protrusion_native'] = target['Protrusion']
    require(expected == new, 'Undeclared route, source, sibling or assignment change')
    require(before['rough_payload'] == after['rough_payload'], 'Protected rough recipe changed')
    a, b = before['finish_payload'], after['finish_payload']
    for key in ('levels', 'leads', 'unit_record'):
        require(a[key] == b[key], 'Protected finish definition changed: '+key)
    require(a['details']['finish'] == b['details']['finish'], 'Finish cutting settings changed')
    verify_repeated_tool_observations(a); verify_repeated_tool_observations(b)
    return verify_full_delta(a['full_tool'], b['full_tool'], target, holder_recipe)


def recipe_marker(source, source_sha256, tool_id, target):
    normalized = validate_target(target)
    normalized = {k:int(v) if k in ('NoOfFlutes','MillToolShankType') else float(v) for k,v in normalized.items()}
    key = _digest(dict(scope=SCOPE, source=str(Path(source).resolve()).casefold(),
        source_sha256=source_sha256, tool_id=tool_id, target=normalized))
    return Path(source).resolve().parent / ('finish_recipe_'+key+'.json')


def marker_state(report):
    return {k:deepcopy(report[k]) for k in ('scope','status','phase','manifest_pin','receipt_path',
        'marker_path','expected_document_path','expected_source_sha256','finish_tool_native_id',
        'mutation_attempted','native_dispatch_pending','readback_verified')}


def configure_finish_recipe(sw, clsid, typelib_path, *, manifest_path, manifest_sha256,
        runtime_pins, generated_typelib_path, holder_file_path, holder_file_sha256,
        holder_recipe_path, holder_recipe_sha256, target_geometry,
        recipe_provenance_path, recipe_provenance_sha256, **args):
    from scripts.sw_cam_events import CamMessageSession
    validate_inventory_request(**{k:args[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'qualification_only','acknowledge_disposable_copy','receipt_path','message_policy')})
    require(args.get('software_only_experiment') is True, 'Explicit software-only experiment required')
    target = validate_target(target_geometry)
    loaded = load_saved_route_manifest(manifest_path,manifest_sha256,runtime_pins=runtime_pins,
        generated_typelib_path=generated_typelib_path,extra_runtime_paths=extra_runtime_paths(), **args)
    holder_recipe = read_holder_recipe(holder_file_path,holder_file_sha256,holder_recipe_path,holder_recipe_sha256)
    provenance, provenance_pin = read_pin(recipe_provenance_path,recipe_provenance_sha256)
    loaded['pins'] = canonical_evidence_pins(loaded['pins'],holder_recipe['pins'],[provenance_pin])
    receipt = Path(args['receipt_path']); marker = recipe_marker(args['expected_document_path'],args['expected_source_sha256'],args['finish_tool_native_id'],target)
    require(receipt.is_absolute() and receipt.suffix.lower()=='.json' and receipt.parent.is_dir()
        and not receipt.exists() and not receipt.is_symlink() and not marker.exists() and not marker.is_symlink(), 'Fresh recipe receipt/attempt marker required')
    blocked = {str(Path(p['path']).resolve()).casefold() for p in loaded['pins']}
    outputs = [str(Path(p).resolve()).casefold() for p in (receipt,marker,args['expected_document_path'])]
    require(len(set(outputs))==3 and not blocked.intersection(outputs), 'Recipe outputs overlap source/evidence')
    report = dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',
        process_id=args['process_id'],expected_document_path=args['expected_document_path'],expected_source_sha256=args['expected_source_sha256'],
        finish_tool_native_id=args['finish_tool_native_id'],finish_operation_native_id=args['finish_operation_native_id'],
        manifest_pin=loaded['pin'],original_manifest_args=deepcopy(args),runtime_pins=deepcopy(runtime_pins),generated_typelib_path=generated_typelib_path,
        holder_recipe=deepcopy(holder_recipe),recipe_provenance_pin=provenance_pin,target_geometry=target,
        evidence_pins=deepcopy(loaded['pins']),receipt_path=str(receipt),marker_path=str(marker),
        mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,
        native_hresult_observable=False,property_assignment=True,readback_verified=False,
        save_attempted=False,model_saved=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,
        tool_assignment_attempted=False,export_attempted=False,simulation_attempted=False,
        automatic_retry=False,automatic_replay=False,automatic_rollback=False,production_qualified=False,
        may_continue=False,field_attempts=[],snapshot_diagnostics=[],metadata_write_attempted=False)
    started=monotonic(); created=False; marker_created=False; session=ctx=None
    def persist():
        report['elapsed_seconds']=monotonic()-started
        if created: _write_receipt(receipt,report)
        if marker_created: _write_receipt(marker,marker_state(report))
    def events(): _events(session,report)
    try:
        _write_receipt(receipt,report,create=True); created=True
        ctx=RouteCheckpointContext(loaded,dict(args),sw,typelib_path,None,events)
        ctx.files(); require(ctx.identity()['needs_save'] is False,'Clean saved starting document required')
        ctx.app=_bootstrap(sw,clsid,typelib_path,args['expected_document_path']);ctx.identity()
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            report['phase']='before_capture';persist()
            before=capture_finish_recipe(ctx,loaded['state'],holder_recipe=holder_recipe,diagnostic=report.setdefault('before_diagnostic',{}))
            report['before']=public_checkpoint(before);verify_initial_capture(before,loaded,args);persist()
            old=values(before['finish_payload']['full_tool'])
            require(old!=target,'Recipe already at target; no replay')
            native=before['native']
            def fresh_targets():
                with ctx.guard() as guard:
                    operation=guard.typed(native['operations'][args['finish_operation_native_id']],'ICWOperation')
                    require(_object_id(native['doc'],operation,guard.read)==args['finish_operation_native_id'],'Operation ID changed')
                    tool=guard.typed(guard.read(operation,'IGetTool'),'ICWTool')
                    require(_object_id(native['doc'],tool,guard.read)==args['finish_tool_native_id'] and guard.read(tool,'IsMillTool') is True,'Assigned cutter changed')
                    return dict(ICWTool=tool,ICWMillTool=guard.typed(tool,'ICWMillTool'))
            targets=fresh_targets()
            ctx.allow_dirty_transition=True
            def field_guard():
                events();ctx.files();ctx.identity();check_holder_pins(holder_recipe)
                fresh_targets();events()
            def read(obj,name,*params):
                with ctx.guard() as guard: return guard.read(obj,name,*params)
            report['phase']='configure';_write_receipt(marker,marker_state(report),create=True);marker_created=True;persist()
            apply_property_batch(targets=targets,old_values=old,target=target,read=read,guard=field_guard,persist=persist,report=report)
            with ctx.guard() as guard:
                holder=guard.typed(guard.read(targets['ICWTool'],'IGetMillToolHolder'),'ICWMillToolHolder')
            if str(Path(read(holder,'GetName'))).casefold()!=str(Path(holder_recipe['file_path'])).casefold():
                apply_holder_reference(holder,holder_recipe,read=read,invoke=_member,guard=field_guard,persist=persist,report=report)
            else:
                report['holder_reference_already_at_target']=True;persist()
            report['phase']='after_capture';persist()
            after=capture_finish_recipe(ctx,before['state'],holder_recipe=holder_recipe,diagnostic=report.setdefault('after_diagnostic',{}))
            report['profile_comparison']=verify_recipe_context(before,after,target,args,holder_recipe)
            checkpoint=public_checkpoint(after)
            report.update(checkpoint=checkpoint,checkpoint_sha256=_digest(checkpoint),after_context=checkpoint['state'],
                source_after_sha256=args['expected_source_sha256'],protected_operations_verified=True)
            ctx.identity();events();persist()
        _events(session,report,active=False)
        require(ctx.identity()==report['checkpoint']['state']['document'],'Cleanup changed document')
        report.update(status='review_required',phase='finished',readback_verified=True,recipe_configuration_verified=True,
            nominal_profile_verified=True,working_progress_saved=False)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',
            issue=_error(exc),readback_verified=False,recipe_configuration_verified=False)
    finally:
        if session is not None: report['messages']=session.summary()
        try: persist()
        except Exception as exc: report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False)
    return report


def load_completed_finish_recipe(path, sha256, *, check_current_source=True, **args):
    data,pin=read_pin(path,sha256)
    require(data.get('scope')==SCOPE and data.get('phase')=='finished' and data.get('status')=='review_required', 'Completed recipe required')
    for key in ('mutation_attempted','readback_verified','recipe_configuration_verified','nominal_profile_verified','protected_operations_verified'):
        require(data.get(key) is True,'Incomplete recipe flag: '+key)
    for key in ('native_dispatch_pending','save_attempted','model_saved','GTP_attempted','GOP_attempted','AFR_attempted',
        'tool_assignment_attempted','export_attempted','simulation_attempted','automatic_retry','automatic_replay','automatic_rollback',
        'production_qualified','may_continue','metadata_write_attempted','working_progress_saved'):
        require(data.get(key) is False,'Unexpected recipe flag: '+key)
    require(not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Failed configuration cannot continue')
    clean_events(data)
    original=data['original_manifest_args']
    for key in ('process_id','expected_document_path','target_feature_native_id','target_operation_native_id',
        'target_operation_setup_native_id','expected_candidate_tool_native_id','finish_operation_native_id','finish_tool_native_id'):
        require(type(original[key]) is type(args[key]) and original[key]==args[key],'Configuration binding differs: '+key)
    manifest=data['manifest_pin']
    loaded=load_saved_route_manifest(manifest['path'],manifest['sha256'],runtime_pins=data['runtime_pins'],
        generated_typelib_path=data['generated_typelib_path'],extra_runtime_paths=extra_runtime_paths(),
        check_current_source=check_current_source,**original)
    recipe=data['holder_recipe'];check_holder_pins(recipe)
    checked=read_holder_recipe(recipe['pins'][0]['path'],recipe['pins'][0]['sha256'],recipe['pins'][1]['path'],recipe['pins'][1]['sha256'])
    require(recipe==checked,'Holder recipe copy differs')
    verify_initial_capture(data['before'],loaded,original)
    verify_recipe_context(data['before'],data['checkpoint'],data['target_geometry'],original,recipe)
    require(data['checkpoint_sha256']==_digest(data['checkpoint']) and data['after_context']==data['checkpoint']['state'], 'Checkpoint digest/state differs')
    marker=recipe_marker(original['expected_document_path'],data['expected_source_sha256'],original['finish_tool_native_id'],data['target_geometry'])
    require(str(marker)==data['marker_path'],'Attempt marker path differs')
    marker_data,marker_pin=read_pin(str(marker),_file_hash(marker))
    require(marker_data==marker_state(data),'Completed attempt marker differs')
    if check_current_source:
        require(args['expected_source_sha256']==data['expected_source_sha256']==_file_hash(args['expected_document_path']), 'Current recipe source differs')
    _,provenance_pin=read_pin(data['recipe_provenance_pin']['path'],data['recipe_provenance_pin']['sha256'])
    loaded['pins']=canonical_evidence_pins(loaded['pins'],recipe['pins'],[pin,marker_pin,provenance_pin])
    loaded.update(state=deepcopy(data['checkpoint']['state']),payload=deepcopy(data['checkpoint']['rough_payload']),
        finish_payload=deepcopy(data['checkpoint']['finish_payload']),holder_recipe=recipe,config_receipt=data,
        parent_pin=pin,pin=pin,historical_only=not check_current_source,source_sha256=data['expected_source_sha256'])
    return loaded

