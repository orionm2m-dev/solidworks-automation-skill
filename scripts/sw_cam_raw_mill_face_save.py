"""Save an existing verified RAW MILL SLAB once and publish a finite checkpoint.

The completed checkpoint is sufficient for a later bounded operation step;
its loader does not replay or recursively load the earlier research chain.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import json,re,math
from scripts import sw_cam_upper_cone_feature as cone
from scripts import sw_cam_raw_mill_face_feature as face
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity

SCOPE='RAW_MILL_FACE_SAVE_EXISTING_V1'
CHECKPOINT_SCOPE='RAW_MILL_SAVED_FACE_OPERATION_PARENT_V1'
RECOVERY_SCOPE='RAW_MILL_FACE_READONLY_RECOVERY_V1'
RECOVERY_CHECKPOINT='RAW_MILL_RECOVERED_FACE_CONTEXT_V1'
BINDINGS=('ownership','ids','qualification','observation_pin','read_mode','base_saved_pin','holder_recipe')

def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)
def _key(path):return str(Path(path).resolve()).casefold()
def _payload(loaded):return dict(rough=deepcopy(loaded['payload']),finish=deepcopy(loaded['finish_payload']))
def _check_pins(pins):
    for pin in pins:require(_file_hash(pin['path'])==pin['sha256'],'Pinned FACE Save evidence changed')
def _pin_map(pins):return {_key(p['path']):p['sha256'] for p in canonical_evidence_pins(pins)}
def _same_pins(a,b):require(_pin_map(a)==_pin_map(b),'Dependency set/path/hash differs')

def save_marker(source,source_sha256,new_id,original_face_sha256):
    value=_digest(dict(scope=SCOPE,source=_key(source),source_sha256=source_sha256,face_native_id=new_id,original_face_sha256=original_face_sha256))
    return Path(source).resolve().parent/('raw_face_save_'+value+'.json')

def _retire(live,history,completed):
    out=canonical_evidence_pins(live);past=canonical_evidence_pins(history)
    for old in completed:
        key=_key(old['path']);matches=[p for p in out if _key(p['path'])==key]
        require(len(matches)==1 and matches[0]['sha256']==old['sha256'],'Only exact validated completed pin may retire')
        past=canonical_evidence_pins(past,[matches[0]]);out=[p for p in out if _key(p['path'])!=key]
    require(len(past)<=16,'Bounded checked history required')
    return out,past

def verify_recovered_face_geometry(observed,circle,new_id):
    close=lambda a,b:type(a) in (int,float) and math.isfinite(a) and abs(a-b)<=1e-6
    vec=lambda a,b:type(a) in (list,tuple) and len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    require(type(new_id) is int and new_id>0 and type(observed['native_id']) is int and observed['native_id']==new_id
        and type(observed['volume_type']) is int and observed['volume_type']==5 and observed['suppressed'] is False,'Exact unsuppressed SLAB identity required')
    require(close(observed['depth_native'],2) and vec(observed['axis_native'],[0,0,-1])
        and vec(observed['bounds_native'],[65,65,2]),'Face header differs')
    require(observed['taper_enabled'] is False and type(observed['island_count']) is int and observed['island_count']==0,'Untapered face without islands required')
    require(vec([v*1000 for v in circle['center_model_m']],[0,0,28]) and close(circle['radius_m']*1000,32.5),'Measured sketch differs')
    top=face._circle_chain(observed['top_curves_native'],1e-8,1e-8,1e-7,'face_top')
    bottom=face._circle_chain(observed['bottom_curves_native'],1e-8,1e-8,1e-7,'face_bottom')
    require(vec(top['center'],[0,0,28]) and close(top['radius'],32.5) and close(bottom['radius'],32.5),'Full D65 profiles required')
    start=observed['start_native']
    require(type(start) in (list,tuple) and len(start)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in start),'Finite native start point required')
    radial=math.hypot(start[0]-top['center'][0],start[1]-top['center'][1])
    require(close(start[2],top['center'][2]) and close(radial,top['radius']),'Observed start must lie on independently validated full top circle')
    coplanar=vec(bottom['center'],top['center']);distinct=vec(bottom['center'],[0,0,26])
    require(coplanar or distinct,'Unexpected raw lower profile plane')
    for row in (top,bottom):require(abs(row['normal'][0])<1e-7 and abs(row['normal'][1])<1e-7 and close(abs(row['normal'][2]),1),'XY contours required')
    return dict(native_configuration_verified=True,complete_circular_profiles_verified=True,
        raw_top_center_native=top['center'],raw_bottom_center_native=bottom['center'],raw_radius_native=top['radius'],
        raw_start_native=deepcopy(start),start_on_top_contour_observed=True,start_coordinate_semantics_qualified=False,
        raw_profiles_coplanar=coplanar,distinct_native_planes_observed=distinct,raw_header_depth_native=observed['depth_native'],
        coordinate_frame_qualified=False,geometric_depth_verified=False,physical_stock_removal_proved=False,
        lower_world_boundary_synthesized=False,target_only=deepcopy(face.TARGET),production_route_changed=False,
        limit='Current observation only: SDK GetStartPosition does not define centre/frame. Raw start belongs to the independently validated top circle. Physical removal requires later CL/WIP; production TURN is separate.')

def _failed_feature_fields(data,*,process_id,expected_document_path,source_sha256,new_id):
    require(type(process_id) is int and process_id>0 and type(new_id) is int and new_id>0,'Strict owned PID and face ID required')
    require(data.get('scope')==face.SCOPE and data.get('route_scope')==face.ROUTE_SCOPE and data.get('status')=='uncertain'
        and data.get('phase')=='finished' and data.get('process_id')==process_id and data.get('new_feature_native_id')==new_id
        and _key(data['expected_document_path'])==_key(expected_document_path) and data.get('expected_source_sha256')==source_sha256
        and data['before']['saved_file_sha256']==data['after']['saved_file_sha256']==source_sha256,'Exact completed RAW face receipt required')
    require(data.get('face_module_pin')==_pin(face.__file__),'FACE implementation changed')
    require(all(data.get(k) is True for k in ('mutation_attempted','native_call_attempted','native_call_returned'))
        and type(data.get('creator_call_count')) is int and data['creator_call_count']==1,'Complete one-creator result required')
    require(all(data.get(k) is False for k in ('native_dispatch_pending','GOP_attempted','GTP_attempted','save_attempted','model_saved',
        'sketch_edit_attempted','CAD_solid_edit_attempted','automatic_retry','automatic_replay','automatic_rollback','production_route_changed'))
        and 'receipt_write_error' not in data,'Uncertain or broadened feature receipt forbidden')
    require(data.get('readback_verified') is False and data.get('failed_phase')=='after' and data.get('issue',{}).get('type')=='ValueError'
        and any(p.get('file')=='sw_cam_raw_mill_face_feature.py' and p.get('function')=='verify_face_geometry' for p in data['issue'].get('locations',[])),
        'Only terminal face geometry assertion failure may be recovered')
    clean_events(data);spec=face.validate_face_spec(data['sketch_spec'],data['route_scope'])
    added=face.verify_face_delta(data['before'],data['after'],new_id,69)
    require(data['new_feature']==added,'Recorded new feature differs')
    require(data['before_payload']==data['after_payload'],'Feature payload changed')
    require(data['before_cone_observation']==data['after_cone_observation'],'Existing cone changed')
    obs=data['face_observation'];circle=face._circle_sketch(obs['sketch'],spec)
    require(all(obs['feature'].get(k)==v for k,v in added['geometry'].items()),'Face header and contour observation differ')
    require(circle==obs['sketch_circle_m'] and data['face_sketch_before']==dict(sketch=obs['sketch'],sketch_circle_m=circle),'Face sketch observation differs')
    verify_recovered_face_geometry(obs['feature'],circle,new_id)
    require('geometry_acceptance' not in data,'Original failed assertion receipt must remain unchanged')
    return spec

def _failed_feature_marker(data,path,digest):
    marker=face.face_marker(data['expected_document_path'],data['expected_source_sha256'])
    mark,pin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==face.SCOPE and mark.get('status')=='uncertain'
        and _key(mark['source'])==_key(data['expected_document_path']) and mark.get('source_sha256')==data['expected_source_sha256']
        and _key(mark['receipt_path'])==_key(path) and mark.get('receipt_sha256')==digest
        and mark.get('native_call_attempted') is True and mark.get('native_call_returned') is True
        and mark.get('readback_verified') is False and mark.get('automatic_replay') is False,'Completed face marker differs')
    return pin

def load_failed_face(path,digest,*,process_id,expected_document_path,expected_source_sha256,expected_feature_native_id):
    data,pin=read_pin(path,digest);new_id=expected_feature_native_id
    spec=_failed_feature_fields(data,process_id=process_id,expected_document_path=expected_document_path,source_sha256=expected_source_sha256,new_id=new_id)
    parent=data['parent_pin'];cone_id=data['parent_cone_feature_native_id']
    loaded=face.load_face_parent(parent['path'],parent['sha256'],process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,expected_feature_native_id=cone_id)
    sketch=data['sketch_receipt_pin'];_,sketch_pin,expected=cone.load_sketch_prerequisite(sketch['path'],sketch['sha256'],loaded,spec,process_id)
    cone.require_state_equivalent(expected,data['before'])
    require(data['before_payload']==_payload(loaded) and data['before_cone_observation']==loaded['cone_observation'],'Face parent payload/cone differs')
    original_live=canonical_evidence_pins(loaded['pins'],[sketch_pin]);_same_pins(original_live,data['evidence_pins'])
    _same_pins(loaded.get('lineage_pins',[]),data['lineage_pins'])
    markerpin=_failed_feature_marker(data,path,digest)
    baseline_pin=loaded['pin'];baseline,_=cone._json_pin(baseline_pin['path'],baseline_pin['sha256'])
    require(baseline.get('scope')==cone.BASELINE_SCOPE and baseline.get('status')=='verified_offline_terminal_branch'
        and baseline.get('old_loader_verified') is True and baseline.get('runtime_rebind_explicit') is True,'Completed exact branch baseline required')
    oldsave=loaded['save_receipt'];oldmarkpath=oldsave['marker_path'];_,oldmark=read_pin(oldmarkpath,_file_hash(oldmarkpath))
    # Both old Save20 artifacts and the now-completed face sketch are fully
    # validated above. Current face receipt/marker remain live before Save21.
    live,past=_retire(original_live,loaded.get('lineage_pins',[]),[parent,oldmark,sketch_pin])
    live=canonical_evidence_pins(live,[pin,markerpin,_self_pin()]);_check_pins(live);_check_pins(past)
    loaded.update(state=deepcopy(data['after']),reference20=deepcopy(data['before']),pins=live,lineage_pins=past,
        source_sha256=expected_source_sha256,cone_sketch_spec=deepcopy(loaded['sketch_spec']),cone_feature_native_id=cone_id,
        face_sketch_spec=spec,face_observation=deepcopy(data['face_observation']),face_feature_native_id=new_id,
        face_receipt=data,face_receipt_pin=pin,face_marker_pin=markerpin,parent_pin=pin,completed_baseline_pin=baseline_pin,baseline_verified=True)
    require(_file_hash(expected_document_path)==expected_source_sha256,'Current saved source changed')
    return loaded

class FaceSaveContext(cone.UpperConeContext):
    def files(self):super().files();_check_pins(self.loaded.get('lineage_pins',[]))

def verify_save_delta(before,after,source_after,*,diagnostic=None):
    require(len(before['features'])==21 and len(before['operations'])==6 and before['document']['needs_save'] is True,'Exact dirty21/6 before Save required')
    expected=deepcopy(before);expected['document']['needs_save']=False;expected['saved_file_sha256']=source_after
    return cone.require_state_equivalent(expected,after,diagnostic=diagnostic)

def _pack_context(loaded,state,payload,cone_observation,face_observation,source_sha256,*,scope,fixed,past):
    return dict(scope=scope,route_scope=face.ROUTE_SCOPE,native_configuration_only=True,physical_removal_verified=False,production_qualified=False,
        source_sha256=source_sha256,state=deepcopy(state),payload=deepcopy(payload),reference20=deepcopy(loaded['reference20']),
        bindings={k:deepcopy(loaded[k]) for k in BINDINGS},cone_sketch_spec=deepcopy(loaded['cone_sketch_spec']),
        cone_feature_native_id=loaded['cone_feature_native_id'],cone_observation=deepcopy(cone_observation),
        face_sketch_spec=deepcopy(loaded['face_sketch_spec']),face_feature_native_id=loaded['face_feature_native_id'],face_observation=deepcopy(face_observation),
        fixed_live_pins=fixed,lineage_pins=past,original_face_pin=deepcopy(loaded['face_receipt_pin']),original_face_marker_pin=deepcopy(loaded['face_marker_pin']),
        completed_baseline_pin=deepcopy(loaded['completed_baseline_pin']),baseline_verified=loaded['baseline_verified'],
        runtime_face_pin=_pin(face.__file__),runtime_save_pin=_self_pin(),prior_receipts_embedded=False,recursive_legacy_loader_required=False)

def _unpack_context(checkpoint,pins,past):
    loaded=deepcopy(checkpoint['bindings']);loaded.update(state=deepcopy(checkpoint['state']),payload=deepcopy(checkpoint['payload']['rough']),
        finish_payload=deepcopy(checkpoint['payload']['finish']),source_sha256=checkpoint['source_sha256'],pins=pins,lineage_pins=past,
        reference20=deepcopy(checkpoint['reference20']),cone_observation=deepcopy(checkpoint['cone_observation']),
        cone_sketch_spec=deepcopy(checkpoint['cone_sketch_spec']),cone_feature_native_id=checkpoint['cone_feature_native_id'],
        face_observation=deepcopy(checkpoint['face_observation']),face_sketch_spec=deepcopy(checkpoint['face_sketch_spec']),face_feature_native_id=checkpoint['face_feature_native_id'],
        face_receipt_pin=deepcopy(checkpoint['original_face_pin']),face_marker_pin=deepcopy(checkpoint['original_face_marker_pin']),
        completed_baseline_pin=deepcopy(checkpoint['completed_baseline_pin']),baseline_verified=checkpoint['baseline_verified'],checkpoint=deepcopy(checkpoint))
    return loaded

def recover_existing_face_readonly(sw,clsid,typelib_path,*,face_receipt_path,face_receipt_sha256,process_id,
        expected_document_path,expected_source_sha256,expected_feature_native_id,receipt_path,
        qualification_only,acknowledge_disposable_copy,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True and message_policy=='vendor_default','Explicit disposable readback required')
    args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    loaded=load_failed_face(face_receipt_path,face_receipt_sha256,**args);target=Path(receipt_path)
    protected={_key(p['path']) for p in loaded['pins']+loaded['lineage_pins']}
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.lower()=='.json' and not target.exists() and not target.is_symlink()
        and _key(target) not in protected and _key(target)!=_key(expected_document_path),'Fresh recovery receipt required')
    report=dict(schema_version=1,scope=RECOVERY_SCOPE,status='error',phase='preflight',process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,new_feature_native_id=expected_feature_native_id,original_face_pin=loaded['face_receipt_pin'],
        original_face_marker_pin=loaded['face_marker_pin'],implementation_pin=_self_pin(),face_module_pin=_pin(face.__file__),
        evidence_pins=deepcopy(loaded['pins']),lineage_pins=deepcopy(loaded['lineage_pins']),receipt_path=str(target),
        mutation_attempted=False,creator_attempted=False,GOP_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,
        original_receipt_changed=False,original_marker_changed=False,CAD_solid_edit_attempted=False,production_route_changed=False,automatic_replay=False,
        readback_verified=False,native_configuration_only=True,full_capture_count=0,snapshot_diagnostics=[])
    created=False;ctx=session=None
    def persist():
        if created:_write_receipt(target,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event/transport requires stop')
    try:
        _write_receipt(target,report,create=True);created=True
        ctx=FaceSaveContext(loaded,dict(args,**loaded['ids']),sw,typelib_path,None,events,loaded['state']);ctx.files();ctx.identity()
        ctx.app=cone._bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity();session=CamMessageSession(ctx.app,typelib_path)
        with session:
            report.update(phase='fresh_readonly_capture',full_capture_count=1);diag={};report['snapshot_diagnostics'].append(diag);persist()
            state,native=face._capture_headers(ctx,clsid,loaded['reference20'],21,diag);report['observed_context']=deepcopy(state);persist()
            try:payload=cone._capture_payload(ctx,state,native,diag)
            finally:persist()
            report['observed_payload']=deepcopy(payload);persist()
            observation=cone._read_sketch_and_cone(ctx,native,loaded['cone_sketch_spec'],loaded['cone_feature_native_id'])
            report['observed_cone']=observation;persist()
            report['observed_face']={};obs=face._read_face(ctx,native,loaded['face_sketch_spec'],expected_feature_native_id,diagnostic=report['observed_face'],persist=persist)
            cone.require_state_equivalent(loaded['state'],state,diagnostic=diag.setdefault('state_comparison',{}))
            require(payload==_payload(loaded) and observation==loaded['cone_observation'] and obs==loaded['face_observation'],'Fresh payload/cone/face must match original observation exactly')
            accepted=verify_recovered_face_geometry(obs['feature'],obs['sketch_circle_m'],expected_feature_native_id);report['geometry_acceptance']=accepted;persist()
        events(False);ctx.files();require(ctx.identity()==state['document'],'Recovery cleanup identity changed')
        fixed,past=_retire(loaded['pins'],loaded['lineage_pins'],[loaded['face_receipt_pin']])
        checkpoint=_pack_context(loaded,state,payload,observation,obs,expected_source_sha256,scope=RECOVERY_CHECKPOINT,fixed=fixed,past=past)
        checkpoint['resolved_uncertainty']=dict(original_face_pin=loaded['face_receipt_pin'],kind='START_CENTER_ASSUMPTION_ONLY',fresh_state_verified=True,original_marker_remains_live=True)
        report.update(status='review_required',phase='finished',readback_verified=True,source_after_sha256=_file_hash(expected_document_path),
            checkpoint=checkpoint,checkpoint_sha256=_digest(checkpoint),reason='FRESH_READONLY_OBSERVATION_VALIDATED_NO_NATIVE_MUTATION')
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        persist()
    return report

def _validate_checkpoint_header(checkpoint,scope):
    require(checkpoint['scope']==scope and checkpoint['route_scope']==face.ROUTE_SCOPE and checkpoint['native_configuration_only'] is True
        and checkpoint['physical_removal_verified'] is False and checkpoint['production_qualified'] is False
        and checkpoint['prior_receipts_embedded'] is False and checkpoint['recursive_legacy_loader_required'] is False,'Finite qualification checkpoint required')
    require(checkpoint['runtime_save_pin']==_self_pin() and checkpoint['runtime_face_pin']==_pin(face.__file__)
        and checkpoint['baseline_verified'] is True and set(checkpoint['bindings'])==set(BINDINGS),'Immutable checkpoint runtime/bindings required')

def load_completed_face_recovery(path,digest,*,process_id,expected_document_path,expected_source_sha256,expected_feature_native_id,check_current_source=True):
    data,pin=read_pin(path,digest);new_id=expected_feature_native_id
    require(data.get('scope')==RECOVERY_SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
        and data.get('readback_verified') is True and type(data.get('full_capture_count')) is int and data['full_capture_count']==1
        and data.get('process_id')==process_id and data.get('new_feature_native_id')==new_id
        and _key(data['expected_document_path'])==_key(expected_document_path)
        and data.get('expected_source_sha256')==data.get('source_after_sha256')==expected_source_sha256,'Completed exact readonly recovery required')
    require(all(data.get(k) is False for k in ('mutation_attempted','creator_attempted','GOP_attempted','GTP_attempted','save_attempted','model_saved',
        'original_receipt_changed','original_marker_changed','CAD_solid_edit_attempted','production_route_changed','automatic_replay'))
        and not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Recovery mutation/failure forbidden')
    require(data['implementation_pin']==_self_pin() and data['face_module_pin']==_pin(face.__file__),'Recovery runtime changed');clean_events(data)
    parent=data['original_face_pin'];prior,priorpin=read_pin(parent['path'],parent['sha256'])
    _failed_feature_fields(prior,process_id=process_id,expected_document_path=expected_document_path,source_sha256=expected_source_sha256,new_id=new_id)
    markerpin=_failed_feature_marker(prior,parent['path'],parent['sha256']);_same_pins([markerpin],[data['original_face_marker_pin']])
    cone.require_state_equivalent(prior['after'],data['observed_context'])
    require(data['observed_payload']==prior['after_payload'] and data['observed_cone']==prior['after_cone_observation']
        and data['observed_face']==prior['face_observation'],'Fresh recovered observation differs')
    require(data['geometry_acceptance']==verify_recovered_face_geometry(data['observed_face']['feature'],data['observed_face']['sketch_circle_m'],new_id),'Recovery geometry check differs')
    cp=data['checkpoint'];_validate_checkpoint_header(cp,RECOVERY_CHECKPOINT);require(data['checkpoint_sha256']==_digest(cp),'Recovery checkpoint digest differs')
    require(cp['source_sha256']==expected_source_sha256 and cp['state']==data['observed_context'] and cp['payload']==data['observed_payload']
        and cp['cone_observation']==data['observed_cone'] and cp['face_observation']==data['observed_face']
        and cp['reference20']==prior['before'] and cp['face_feature_native_id']==new_id and cp['cone_feature_native_id']==prior['parent_cone_feature_native_id']
        and cp['face_sketch_spec']==prior['sketch_spec'],'Recovery checkpoint contents differ')
    require(cp['resolved_uncertainty']==dict(original_face_pin=parent,kind='START_CENTER_ASSUMPTION_ONLY',fresh_state_verified=True,original_marker_remains_live=True),'Explicit uncertainty resolution required')
    fixed,past=_retire(data['evidence_pins'],data['lineage_pins'],[priorpin]);_same_pins(fixed,cp['fixed_live_pins']);_same_pins(past,cp['lineage_pins'])
    _same_pins([priorpin],[cp['original_face_pin']]);_same_pins([markerpin],[cp['original_face_marker_pin']])
    fixed_map=_pin_map(fixed)
    require(fixed_map.get(_key(cp['completed_baseline_pin']['path']))==cp['completed_baseline_pin']['sha256']
        and fixed_map.get(_key(markerpin['path']))==markerpin['sha256'],'Exact baseline and original uncertain marker remain live')
    live=canonical_evidence_pins(fixed,[pin]);_check_pins(live);_check_pins(past)
    if check_current_source:require(_file_hash(expected_document_path)==expected_source_sha256,'Current source changed')
    loaded=_unpack_context(cp,live,past);loaded.update(parent_pin=pin,recovery_receipt_pin=pin,recovery_receipt=data,historical_only=not check_current_source)
    return loaded

def _checkpoint(loaded,state,payload,cone_observation,face_observation,source_sha256):
    require(loaded['baseline_verified'] is True,'Completed original baseline must have been validated')
    fixed,past=_retire(loaded['pins'],loaded['lineage_pins'],[loaded['recovery_receipt_pin'],loaded['completed_baseline_pin']])
    cp=_pack_context(loaded,state,payload,cone_observation,face_observation,source_sha256,scope=CHECKPOINT_SCOPE,fixed=fixed,past=past)
    cp['parent_recovery_pin']=deepcopy(loaded['recovery_receipt_pin'])
    return cp

def load_completed_face_save(path,digest,*,process_id,expected_document_path,expected_source_sha256,
        expected_feature_native_id,check_current_source=True):
    """Read a finite recovered Save checkpoint; no earlier research loaders."""
    data,pin=read_pin(path,digest);new_id=expected_feature_native_id
    require(data.get('scope')==SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
        and data.get('process_id')==process_id and data.get('new_feature_native_id')==new_id
        and _key(data['expected_document_path'])==_key(expected_document_path),'Exact completed FACE Save required')
    require(all(data.get(k) is True for k in ('save_attempted','mutation_attempted','native_call_attempted','native_call_returned',
        'model_saved','readback_verified','save_readback_verified')) and data.get('save_pending') is False
        and data.get('native_return_type')=='int' and type(data.get('native_return_value')) is int and data['native_return_value']==0,'Strict complete native Save required')
    require(all(data.get(k) is False for k in ('GOP_attempted','GTP_attempted','creator_attempted','CAD_solid_edit_attempted','automatic_replay','production_route_changed'))
        and not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Uncertain Save forbidden')
    require(data['save_module_pin']==_self_pin(),'Save implementation changed');clean_events(data)
    source_before=data['source_before_sha256'];source_after=data['saved_file_sha256'];parent=data['parent_pin']
    require(source_after==expected_source_sha256,'Saved source binding differs')
    loaded=load_completed_face_recovery(parent['path'],parent['sha256'],process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=source_before,expected_feature_native_id=new_id,check_current_source=False)
    _same_pins([loaded['face_receipt_pin']],[data['original_face_pin']]);_same_pins([loaded['face_marker_pin']],[data['original_face_marker_pin']])
    _same_pins(loaded['pins'],data['evidence_pins']);_same_pins(loaded['lineage_pins'],data['lineage_pins'])
    cone.require_state_equivalent(loaded['state'],data['before_context']);verify_save_delta(data['before_context'],data['after_context'],source_after)
    require(data['before_payload']==data['after_payload']==_payload(loaded) and data['before_cone']==data['after_cone']==loaded['cone_observation']
        and data['before_face']==data['after_face']==loaded['face_observation'],'Saved payload/cone/face differs')
    normalized=dict(state=loaded['state'],payload=_payload(loaded),cone_observation=loaded['cone_observation'],face_observation=loaded['face_observation'])
    require(data['before']==data['after']==normalized,'Save normalized snapshots differ')
    require(data['source_transition']==dict(source_before_sha256=source_before,source_after_sha256=source_after,
        clean_document=data['after_context']['document'],strict_native_save_return=0),'Saved source transition differs')
    cp=data['checkpoint'];_validate_checkpoint_header(cp,CHECKPOINT_SCOPE)
    require(data['checkpoint_sha256']==_digest(cp) and cp==_checkpoint(loaded,data['after_context'],data['after_payload'],data['after_cone'],data['after_face'],source_after),'Terminal checkpoint differs')
    marker=save_marker(expected_document_path,source_before,new_id,loaded['face_receipt_pin']['sha256']);mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==SCOPE and mark.get('status')=='review_required'
        and mark.get('save_pending') is False and mark.get('model_saved') is True and mark.get('source_before_sha256')==source_before
        and mark.get('new_feature_native_id')==new_id and mark.get('original_face_sha256')==loaded['face_receipt_pin']['sha256']
        and mark.get('receipt_sha256')==digest and _key(mark['receipt_path'])==_key(path) and mark.get('automatic_replay') is False,'Completed Save marker differs')
    live=canonical_evidence_pins(cp['fixed_live_pins'],[pin,markpin]);past=cp['lineage_pins'];_check_pins(live);_check_pins(past)
    if check_current_source:require(_file_hash(expected_document_path)==source_after,'Current source changed')
    out=_unpack_context(cp,live,past);out.update(parent_pin=pin,save_marker_pin=markpin,save_receipt=data,historical_only=not check_current_source)
    return out

def save_existing_raw_face(sw,clsid,typelib_path,*,recovery_receipt_path,recovery_receipt_sha256,process_id,
        expected_document_path,expected_source_sha256,expected_feature_native_id,receipt_path,
        qualification_only,acknowledge_disposable_copy,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True and message_policy=='vendor_default','Explicit disposable qualification required')
    identity=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    loaded=load_completed_face_recovery(recovery_receipt_path,recovery_receipt_sha256,**identity)
    target=Path(receipt_path);marker=save_marker(expected_document_path,expected_source_sha256,expected_feature_native_id,loaded['face_receipt_pin']['sha256'])
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.lower()=='.json' and not target.exists() and not target.is_symlink()
        and not marker.exists() and not marker.is_symlink(),'Fresh receipt and never-attempted Save required')
    protected={_key(p['path']) for p in loaded['pins']+loaded['lineage_pins']}|{_key(expected_document_path)}
    require(_key(target) not in protected and _key(marker) not in protected and _key(marker)!=_key(target),'Save outputs alias source/evidence')
    args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,expected_document_path=expected_document_path,
        source_before_sha256=expected_source_sha256,new_feature_native_id=expected_feature_native_id,parent_pin=loaded['recovery_receipt_pin'],
        save_module_pin=_self_pin(),evidence_pins=deepcopy(loaded['pins']),lineage_pins=deepcopy(loaded['lineage_pins']),
        original_face_pin=loaded['face_receipt_pin'],original_face_marker_pin=loaded['face_marker_pin'],marker_path=str(marker),receipt_path=str(target),
        save_attempted=False,save_pending=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        model_saved=False,readback_verified=False,save_readback_verified=False,GOP_attempted=False,GTP_attempted=False,
        creator_attempted=False,CAD_solid_edit_attempted=False,automatic_replay=False,production_route_changed=False,production_qualified=False,snapshot_diagnostics=[])
    created=claimed=False;session=ctx=save_app=None;started=monotonic()
    def marker_state():
        return dict(scope=SCOPE,status=report['status'],save_pending=report['save_pending'],model_saved=report['model_saved'],
            receipt_path=str(target),receipt_sha256=_file_hash(target),source_before_sha256=expected_source_sha256,
            new_feature_native_id=expected_feature_native_id,original_face_sha256=loaded['face_receipt_pin']['sha256'],automatic_replay=False)
    def persist():
        report['elapsed_seconds']=monotonic()-started
        if created:
            _write_receipt(target,report)
            if claimed:_write_receipt(marker,marker_state())
    def claim():
        nonlocal claimed
        _write_receipt(marker,marker_state(),create=True);claimed=True
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event/transport requires stop')
    def boundary():ctx.files();events();ctx.identity()
    def capture(label):
        nonlocal save_app
        boundary();diag=dict(phase=label);report['snapshot_diagnostics'].append(diag);persist()
        state,native=face._capture_headers(ctx,clsid,loaded['reference20'],21,diag)
        report[label+'_context']=deepcopy(state);diag['observed_state']=deepcopy(state);persist()
        try:payload=cone._capture_payload(ctx,state,native,diag)
        finally:persist()
        report[label+'_payload']=deepcopy(payload);persist()
        observation=cone._read_sketch_and_cone(ctx,native,loaded['cone_sketch_spec'],loaded['cone_feature_native_id'])
        report[label+'_cone']=deepcopy(observation);persist()
        require(observation==loaded['cone_observation'],'Existing cone/sketch observation changed')
        report[label+'_face']={}
        face_observation=face._read_face(ctx,native,loaded['face_sketch_spec'],expected_feature_native_id,diagnostic=report[label+'_face'],persist=persist)
        require(face_observation==loaded['face_observation'],'Existing face/sketch observation changed')
        if label=='before':cone.require_state_equivalent(loaded['state'],state,diagnostic=diag.setdefault('state_comparison',{}))
        else:verify_save_delta(loaded['state'],state,report['saved_file_sha256'],diagnostic=diag.setdefault('state_comparison',{}))
        with ctx.guard() as g:save_app=g.typed(ctx.app,'ICWApp')
        normalized=deepcopy(state);normalized['document']['needs_save']=True;normalized['saved_file_sha256']=expected_source_sha256
        normalized=cone.require_state_equivalent(loaded['state'],normalized,diagnostic=diag.setdefault('core_state_normalization',{}));persist()
        return dict(state=normalized,payload=payload,cone_observation=observation,face_observation=face_observation)
    def saved_hash():
        require(report.get('native_call_returned') is True and report.get('save_pending') is False
            and report.get('native_return_type')=='int' and type(report.get('native_return_value')) is int and report['native_return_value']==0,'Strict Save return required')
        events();ctx.files();ctx.owned();doc=raw_part_identity(sw);expected=deepcopy(ctx.expected_document);expected['needs_save']=False
        require(doc==expected,'Save must leave exact clean document')
        digest=_file_hash(expected_document_path)
        ctx.args=dict(ctx.args,expected_source_sha256=digest);ctx.expected_document=deepcopy(doc)
        report['source_transition']=dict(source_before_sha256=expected_source_sha256,source_after_sha256=digest,clean_document=doc,strict_native_save_return=0)
        ctx.identity();return digest
    try:
        _write_receipt(target,report,create=True);created=True
        ctx=FaceSaveContext(loaded,args,sw,typelib_path,None,events,loaded['state']);ctx.files();ctx.identity()
        ctx.app=cone._bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity();session=CamMessageSession(ctx.app,typelib_path)
        with session:
            expected=dict(state=loaded['state'],payload=_payload(loaded),cone_observation=loaded['cone_observation'],face_observation=loaded['face_observation'])
            def verify(value):require(value==expected,'Normalized Save capture changed')
            def native_save():boundary();return _member(save_app,'SaveActiveDocument')
            run_one_existing_save(report,capture=capture,verify=verify,guard=boundary,claim=claim,persist=persist,save=native_save,saved_hash=saved_hash)
        events(False);ctx.files();require(ctx.identity()==report['after_context']['document'],'Save cleanup identity changed')
        checkpoint=_checkpoint(loaded,report['after_context'],report['after_payload'],report['after_cone'],report['after_face'],report['saved_file_sha256'])
        report.update(status='review_required',phase='finished',readback_verified=True,model_saved=True,
            checkpoint=checkpoint,checkpoint_sha256=_digest(checkpoint),reopen_persistence_verified=False)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,model_saved=False)
    finally:
        if session is not None:report['messages']=session.summary()
        persist()
    return report

COMMON_PARAMS={'process_id','expected_document_path','expected_source_sha256','expected_feature_native_id','receipt_path',
    'qualification_only','acknowledge_disposable_copy','message_policy','addin_clsid','module_sha256'}
INPUT_FIELDS={'recover_readonly':('face_receipt_path','face_receipt_sha256'),
              'save_existing_raw_face':('recovery_receipt_path','recovery_receipt_sha256')}

def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action'] in INPUT_FIELDS,'Exact recovery or Save action required')
    action=request['action'];p=request['params'];require(type(p) is dict and set(p)==COMMON_PARAMS|set(INPUT_FIELDS[action]),'Exact action fields required')
    require(type(p['process_id']) is int and p['process_id']>0 and type(p['expected_feature_native_id']) is int and p['expected_feature_native_id']>0,'Strict PID/face ID required')
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'] and p['qualification_only'] is True and p['acknowledge_disposable_copy'] is True
        and p['message_policy']=='vendor_default','Exact runtime/qualification required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact add-in CLSID required')
    return dict(p)

def dispatch_request(request):
    p=validate_request(request);action=request['action'];pathkey,shakey=INPUT_FIELDS[action]
    loader=load_failed_face if action=='recover_readonly' else load_completed_face_recovery
    loader(p[pathkey],p[shakey],**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256','expected_feature_native_id')})
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        require(type(_member(sw,'GetProcessID')) is int and _member(sw,'GetProcessID')==p['process_id'],'Connected PID differs')
        run=recover_existing_face_readonly if action=='recover_readonly' else save_existing_raw_face
        return run(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),**p)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--result',required=True)
    a=parser.parse_args(argv);source,target=Path(a.request),Path(a.result)
    require(source.is_absolute() and source.is_file() and source.stat().st_size<=65536,'Bounded request required')
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.lower()=='.json' and not target.exists() and not target.is_symlink(),'Fresh result path required')
    try:
        request=json.loads(source.read_text(encoding='utf-8'));p=validate_request(request)
        require(_key(target)!=_key(source) and _key(target) not in {_key(v) for k,v in p.items() if k.endswith('path')},'Output aliases request/input')
        result=dispatch_request(request)
    except Exception as exc:result=dict(status='error',issue=_error(exc),automatic_replay=False)
    _write_receipt(target,result,create=True)
    print(json.dumps(dict(status=result.get('status'),readback_verified=result.get('readback_verified'),result_path=str(target))))
    return 0 if result.get('readback_verified') is True else 2

if __name__=='__main__':raise SystemExit(main())
