"""Explicit definition-only authority for the existing selected MILL GOP lifecycle.
No geometry promotion, new framework, generation dispatch or persistence here.
"""
from copy import deepcopy
import json,os,re
from pathlib import Path
from scripts import sw_cam_process_import as inventory
from scripts import sw_cam_autodetected_pocket as creator
from scripts.sw_cam import _member
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_profile_sketch import _snapshot, _read_sketch
from scripts.sw_cam_mill_inventory import _same_bodies
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_executable_launch import _process_identity

SCOPE='AUTODETECTED_POCKET_RECOVERED_SAVED_GOP_AUTHORITY_V1'
require=inventory.require
OP_KEYS=('operation_setups','operations','operation_count','generated_operation_count','total_record_count','unique_tool_count')

def validate_request(*,feature_kind,definition_recovery_receipt_path=None,definition_recovery_receipt_sha256=None,definition_save_receipt_path=None,definition_save_receipt_sha256=None,circle_creation_receipt_path=None,circle_creation_receipt_sha256=None):
    values=(definition_recovery_receipt_path,definition_recovery_receipt_sha256,definition_save_receipt_path,definition_save_receipt_sha256)
    if feature_kind!='autodetected_pocket':
        require(all(x is None for x in values),'Recovery/save authority is only valid for autodetected_pocket GOP')
        return
    require(circle_creation_receipt_path is None and circle_creation_receipt_sha256 is None,'Recovered definition must not impersonate circle contour evidence')
    for path,sha in ((definition_recovery_receipt_path,definition_recovery_receipt_sha256),(definition_save_receipt_path,definition_save_receipt_sha256)):
        p=Path(path) if type(path)is str else None
        require(p is not None and p.is_absolute() and p.suffix.lower()=='.json','Pinned recovery and Save JSON paths required')
        require(type(sha)is str and re.fullmatch('[0-9a-f]{64}',sha),'Pinned recovery and Save SHA required')

def verify_files(context):
    for pin in context['pins']:require(_file_hash(pin['path'])==pin['sha256'],'Recovered/saved definition evidence changed')

def verify_saved_transition(recovered,saved,*,process_id,expected_document_path,expected_source_sha256,expected_feature_native_id):
    """Existing zero-operation Save envelope, not a persistence/reopen claim."""
    from scripts.sw_cam_lifecycle import _verify_save
    old=recovered['old'];v=old['request'];header=recovered['header']
    require(type(process_id)is int and process_id==v['process_id'] and type(expected_feature_native_id)is int and expected_feature_native_id>0 and expected_feature_native_id==header['native_id'],'Exact recovered process and feature identities required')
    require(creator.same_path(expected_document_path,v['expected_document_path']),'Recovered target path differs')
    require(saved.get('status')=='review_required' and saved.get('phase')=='finished' and saved.get('action')=='save' and saved.get('machine_kind')=='mill_qualification' and saved.get('process_id')==process_id,'Completed existing MILL qualification Save required')
    creator.clean(saved)
    require(saved.get('message_policy')=='vendor_default','Exact default message policy required')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','native_save_call_returned','save_readback_verified','saved_file_changed'):
        require(saved.get(key)is True,'Verified native Save fact required: '+key)
    for key in ('native_dispatch_pending','native_close_call_returned','close_verified','persistence_verified','generation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','post_cleanup_CAM_getters'):
        require(saved.get(key)is False,'Save-only scope required: '+key)
    require(saved.get('native_return_type')=='int' and type(saved.get('native_return_value'))is int and saved['native_return_value']==0 and type(saved.get('native_hresult'))is int and saved['native_hresult']==0,'Strict native Save int0 required')
    require(saved.get('native_outcome')=='save_returned_readback_verified','Save readback outcome required')
    before,after=saved['before'],saved['after'];require(after==saved['final_state'],'Exact final Save snapshot required');_verify_save(before,after)
    require(saved['state_sha256']==_digest(after),'Saved state digest differs')
    require(before['saved_file_sha256']==v['expected_source_sha256'] and after['saved_file_sha256']==expected_source_sha256 and before['saved_file_sha256']!=after['saved_file_sha256'],'Explicit changed target source transition required')
    for state in (before,after):
        require(state['machine_kind']=='mill_qualification' and type(state['process_id'])is int and state['process_id']==process_id and state['current_machine']['machine_type']==1,'Exact MILL/PID saved scope required')
        doc=state['document'];require(type(doc['type'])is int and doc['type']==1 and creator.same_path(doc['path'],expected_document_path),'Exact saved part required')
        require(type(state['operation_counts'])is list and len(state['operation_counts'])<=1 and all(type(x)is int and x==0 for x in state['operation_counts']),'Save must preserve zero operations')
        setups=state['feature_setups'];require(len(setups)==1,'One feature setup required')
        owner=setups[0];require(type(owner['native_id'])is int and owner['native_id']==header['owner_setup_native_id'] and type(owner['feature_count'])is int and owner['feature_count']==1 and owner['axis_native']==v['expected_axis_native'] and owner['origin_native']==v['expected_origin_native'],'Exact saved owner/frame and one-feature count required')
    if creator.saved_caps(v):
        from scripts.sw_cam_autodetected_pocket_recovery import post_create_document
        actual_dirty=post_create_document(old)['needs_save']
        require(type(actual_dirty)is bool and before['document']['needs_save']is actual_dirty and after['document']['needs_save']is False,
                'Exact observed CAM-only dirty state to clean Save required')
        expected=deepcopy(post_create_document(old))
    else:
        require(before['document']['needs_save']is True and after['document']['needs_save']is False,'Known definition-dirty to clean saved transition required')
        expected=deepcopy(old['document_before'])
    expected['path']=before['document']['path']
    require(before['document']==expected,'Save did not begin from recovered definition document')
    require(saved['after_cleanup_sw_file']==dict(document=after['document'],saved_file_sha256=expected_source_sha256),'Clean post-cleanup Save identity required')
    return dict(document=deepcopy(after['document']),source_before_sha256=before['saved_file_sha256'],source_after_sha256=after['saved_file_sha256'],save_state_sha256=saved['state_sha256'],persistence_verified=False)

def _read_recovery(path,sha):
    from scripts.sw_cam_autodetected_pocket_recovery import verify_recovery_receipt
    raw,_=read_pin(path,sha)
    if raw.get('scope')==creator.SCOPE:return read_creator_receipt(path,sha)
    out=verify_recovery_receipt(path,sha);out['origin_kind']='recovery';return out

def load(*,process_id,expected_document_path,expected_source_sha256,expected_feature_native_id,definition_recovery_receipt_path,definition_recovery_receipt_sha256,definition_save_receipt_path,definition_save_receipt_sha256):
    validate_request(feature_kind='autodetected_pocket',definition_recovery_receipt_path=definition_recovery_receipt_path,definition_recovery_receipt_sha256=definition_recovery_receipt_sha256,definition_save_receipt_path=definition_save_receipt_path,definition_save_receipt_sha256=definition_save_receipt_sha256)
    recovered=_read_recovery(definition_recovery_receipt_path,definition_recovery_receipt_sha256)
    saved,save_pin=read_pin(definition_save_receipt_path,definition_save_receipt_sha256)
    transition=verify_saved_transition(recovered,saved,process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    old=recovered['old'];v=old['request'];pins=[];historical_targets=[]
    for pin in recovered['pins']+[recovered['creator_pin'],recovered['marker_pin'],recovered['receipt_pin']]:
        if creator.canonical(pin['path'])==creator.canonical(expected_document_path):
            require(pin['sha256']==v['expected_source_sha256'],'Historical target pin differs from creator source');historical_targets.append(deepcopy(pin))
        else:pins.append(deepcopy(pin))
    require(historical_targets,'Recovery must retain the historical target source pin')
    pins.extend([save_pin,inventory.file_pin(expected_document_path,expected_source_sha256)])
    require(1<=len(pins)<=64,'Bounded complete recovered evidence pin list required')
    expected_sketch=definition_sketch_baseline(recovered)
    expected_sketch.update(features=deepcopy(recovered['expected_inventory']['sw_reference']['feature_tree']),saved_file_sha256=expected_source_sha256,needs_save=False)
    marker=Path(expected_document_path).parent/('feature_gop_'+_digest(dict(scope=SCOPE,target=creator.canonical(expected_document_path),creator_sha256=recovered['creator_pin']['sha256'],feature_id=expected_feature_native_id))+'.json')
    out=dict(scope=SCOPE,process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id,origin_kind=recovered.get('origin_kind','recovery'),evidence=recovered['receipt_pin'],pins=pins,creator=old,recovered=recovered,save_pin=save_pin,saved_transition=transition,historical_target_pins=historical_targets,expected_inventory=recovered['expected_inventory'],sketch=recovered['sketch'],current_sketch_baseline=expected_sketch,spec=recovered['spec'],request=v,marker=marker)
    verify_files(out);return out

def identity(sw,context):
    v=context['request'];p=_process_identity(v['process_id'])
    require(p.get('alive')is True and p.get('process_id')==v['process_id'] and p.get('create_time')==v['expected_process_create_time'] and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact creator process lifetime required')
    require(type(_member(sw,'GetProcessID'))is int and _member(sw,'GetProcessID')==v['process_id'],'Selected native process differs')
    doc=raw_part_identity(sw)
    expected=deepcopy(context['saved_transition']['document']);expected['needs_save']=doc['needs_save']
    require(type(doc['needs_save'])is bool and doc==expected,'Exact saved definition document differs')
    configuration=_member(_member(_member(_member(sw,'ActiveDoc'),'ConfigurationManager'),'ActiveConfiguration'),'Name')
    require(configuration==v['expected_sw_configuration'],'CAD configuration differs')
    source=context['expected_source_sha256']
    require(_file_hash(v['expected_document_path'])==source,'Saved definition source changed')
    verify_files(context);return dict(document=doc,saved_file_sha256=source)

def _feature_header(guard,doc,raw):
    feat=guard.typed(raw,'ICWFeature');mill=guard.typed(raw,'ICWMillFeature')
    h=dict(native_id=_object_id(doc,feat,guard.read),owner_setup_native_id=_object_id(doc,guard.read(feat,'GetOwner'),guard.read),suppressed=guard.read(feat,'Suppressed'),axis_native=inventory._vector(guard.read(feat,'Axis')))
    for name,key in [('VolumeType','volume_type'),('IGetIslandCount','island_count')]:
        value=guard.read(mill,name);require(type(value)is int,'Strict native header integer required');h[key]=value
    for name,key in [('Depth','depth_native'),('IGetTaperAngle','taper_angle_native')]:h[key]=creator.number(guard.read(mill,name))
    return h,feat

def capture(sw,clsid,tlb,context,check,diagnostic):
    """Generic full inventory plus exact basic feature/analytic sketch readback."""
    diagnostic={} if diagnostic is None else diagnostic
    observed=identity(sw,context);v=context['request'];r=context['creator'];check()
    def owned():require(identity(sw,context)==observed,'Definition context changed during capture')
    with ScopedCamDispatchGuard(sw,tlb,process_id=v['process_id'],expected_document=observed['document'],source_sha256=context['expected_source_sha256'],evidence_pins=context['pins'],verify_evidence=lambda:verify_files(context),verify_owned_process=owned,check_events=check) as guard:
        addin=guard.read(sw,'GetAddInObject',clsid);app=guard.typed(guard.read(addin,'GetCWApp'),'ICWApp4')
        state=inventory.capture_import_inventory(app,tlb,guard,diagnostic,lambda d:None)
        require(state['cam_configuration_name']==v['expected_cam_configuration'] and state['associated_sw_configuration']==v['expected_sw_configuration'],'Exact CAM/CAD configuration binding required')
        baseline=deepcopy(context['expected_inventory']);baseline.pop('sw_reference');baseline.pop('all_solid_body_count')
        for key in OP_KEYS:baseline.pop(key)
        current={k:deepcopy(value)for k,value in state.items()if k not in OP_KEYS}
        require(current==baseline,'Feature/setup/configuration definition differs from creator')
        doc=guard.typed(guard.read(app,'IGetActiveDoc'),'ICWDoc3');machine=guard.typed(guard.read(guard.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
        setups=inventory._items(guard.read(machine,'IGetEnumSetups'),guard.typed,guard.read,1)
        require(len(setups)==1 and _object_id(doc,setups[0],guard.read)==v['owner_setup_native_id'],'Exact feature owner required')
        features=inventory._items(guard.read(guard.typed(setups[0],'ICWBaseSetup'),'IGetEnumFeatures'),guard.typed,guard.read,1)
        require(len(features)==1,'Exactly one native feature required')
        header,feature=_feature_header(guard,doc,features[0]);require(header==r['feature_header'],'Feature header differs from definition receipt')
        actual,model,_=guard._observe(lambda:_snapshot(sw,v['process_id'],v['expected_document_path'],context['spec']))
        expected=deepcopy(context['current_sketch_baseline']);expected['needs_save']=observed['document']['needs_save'];a,b=deepcopy(actual),deepcopy(expected);sa,sb=a.pop('solids'),b.pop('solids')
        require(a==b and _same_bodies(sa,sb),'CAD/sketch snapshot differs from immutable creator baseline')
        diagnostic['actual_sketch_snapshot']=actual
        sketch_feature=guard.read(model,'FeatureByName',context['spec']['sketch_name'])
        require(guard.read(sketch_feature,'GetTypeName2')=='ProfileFeature','Exact analytic sketch required')
        sketch=guard.read(sketch_feature,'GetSpecificFeature2');profile=guard._observe(lambda:_read_sketch(sw,sketch,context['spec']))
        require(profile==(context['creator']['circle_readback'] if creator.saved_caps(v) else context['sketch']['sketch_readback']),'Native sketch circle differs')
        guard._boundary()
    state.update(document=observed['document'],saved_file_sha256=context['expected_source_sha256'],selected_feature=header,operation_setup_count=len(state['operation_setups']),operation_counts=[x['operation_count']for x in state['operation_setups']],definition_authority=dict(scope=SCOPE,recovery_receipt_sha256=context['evidence']['sha256'],save_receipt_sha256=context['save_pin']['sha256'],raw_creator_status=context['creator']['status'],saved_definition_binding_verified=True,persistence_verified=False,analytic_sketch_and_body_invariants_verified=True,island_geometry_verified=False,physical_depth_verified=False))
    if creator.saved_caps(v) or context.get('origin_kind')=='creator':
        state['definition_authority']['origin_kind']=context['origin_kind']
    diagnostic.update(capture_complete=True,stage='complete',state=deepcopy(state))
    return state,dict(app=app,doc=doc,machine=machine,selected_feature=feature)

def eligible(context,state):
    return state['document']==context['saved_transition']['document'] and state['document']['needs_save']is False and not state['operations'] and not any(state['operation_counts']) and not context['marker'].exists()

def claim(context,receipt_path,state_sha256):
    """One durable selected-feature attempt, independent of new receipt filenames."""
    marker=context['marker'];require(not marker.exists(),'Definition GOP attempt already consumed; no replay')
    require(creator.canonical(receipt_path)not in {creator.canonical(p['path'])for p in context['pins']}|{creator.canonical(marker)},'GOP output aliases protected evidence')
    value=dict(scope=SCOPE,creator_receipt_sha256=context['evidence']['sha256'],feature_native_id=context['expected_feature_native_id'],receipt_path=str(receipt_path),state_sha256=state_sha256,automatic_replay=False)
    with marker.open('x',encoding='utf-8')as stream:
        json.dump(value,stream,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    return str(marker)

def verify_delta(before,after,feature_id):
    require(not before['operations'] and before['operation_count']==0 and not any(before['operation_counts']),'GOP must begin with zero operations')
    ops=after['operations'];require(1<=len(ops)<=32 and len(after['operation_setups'])==1 and after['operation_counts']==[len(ops)],'Bounded nonempty one-setup draft operation plan required')
    ids=[x['native_id']for x in ops];require(all(type(x)is int and x>0 for x in ids)and len(ids)==len(set(ids)),'Unique actual operation IDs required')
    old_setups=before['operation_setups'];require(len(old_setups)<=1,'GOP cannot remove pre-existing operation setups')
    if old_setups:
        expected_setup=deepcopy(old_setups[0]);expected_setup['operation_count']=len(ops)
        require(expected_setup==after['operation_setups'][0],'Existing operation setup identity/metadata changed')
    sid=after['operation_setups'][0]['native_id'];tools=set()
    for i,row in enumerate(ops):
        require(row['setup_index']==0 and row['operation_index']==i and row['setup_native_id']==sid and row['linked_feature_ids']==[feature_id] and row['all_linked_features_observed']is True and row['suppressed']is False and row['toolpath_generated']is False and not any(row['toolpath_record_counts']),'Every draft operation must solely link the selected feature with zero path records')
        tool=row['assigned_tool'];require(tool['native_read_complete']is True and tool['is_mill_tool']is True and type(tool['native_id'])is int and tool['native_id']>0,'Observed actual generic tool identity required');tools.add(tool['native_id'])
    require(after['operation_count']==len(ops) and after['generated_operation_count']==after['total_record_count']==0 and after['unique_tool_count']==len(tools),'Aggregate draft counts differ')
    expected=deepcopy(before)
    for key in OP_KEYS+('operation_setup_count','operation_counts'):expected[key]=deepcopy(after[key])
    expected['document']['needs_save']=after['document']['needs_save']
    require(type(after['document']['needs_save'])is bool and expected==after,'GOP changed protected feature/setup/CAD/source authority')
    return deepcopy(ops)


def after_native_save_source(context,new_source_sha256,*,native_return_value):
    """Derive a current capture context only after this owner's explicit Save int0.

Historical recovery/Save evidence stays unchanged. The caller persists the raw
return and observed new SHA before invoking this helper and owns full readback.
"""
    require(type(native_return_value)is int and native_return_value==0,'This explicit native Save must have returned int0')
    require(type(new_source_sha256)is str and re.fullmatch('[0-9a-f]{64}',new_source_sha256) and new_source_sha256!=context['expected_source_sha256'],'Observed changed current target SHA required')
    out=deepcopy(context);target=context['expected_document_path'];pins=[];replaced=[]
    for pin in context['pins']:
        if creator.same_path(pin['path'],target):
            require(pin['sha256']==context['expected_source_sha256'],'Current target preimage pin differs');replaced.append(deepcopy(pin))
        else:pins.append(deepcopy(pin))
    require(replaced,'Explicit current target pin required before Save')
    pins.append(inventory.file_pin(target,new_source_sha256))
    out.update(pins=pins,expected_source_sha256=new_source_sha256,native_save_target_transition=dict(before_sha256=context['expected_source_sha256'],after_sha256=new_source_sha256,native_return_value=native_return_value,historical_current_target_pins=replaced))
    out['current_sketch_baseline']['saved_file_sha256']=new_source_sha256
    verify_files(out);return out


def _verify_saved_plan_transition(context,plan,saved,expected_source_sha256):
    """Durable post-GOP Save proof; no historical target-file read or promotion."""
    from scripts.sw_cam_lifecycle import _verify_save
    require(saved.get('status')=='review_required' and saved.get('phase')=='finished' and saved.get('action')=='save'
            and saved.get('machine_kind')=='mill_single_feature_qualification' and saved.get('feature_kind')=='autodetected_pocket','Completed recovered-plan Save required')
    require(type(saved.get('process_id'))is int and saved['process_id']==context['process_id']
            and type(saved.get('expected_feature_native_id'))is int and saved['expected_feature_native_id']==context['expected_feature_native_id']
            and saved.get('expected_operation_native_ids')==plan['operation_ids'],'Exact Save process/feature/operation binding required')
    creator.clean(saved)
    require(saved.get('message_policy')=='vendor_default','Exact default message policy required')
    for key in ('mutation_attempted','native_call_attempted','native_call_returned','native_save_call_returned','save_readback_verified','saved_file_changed','geometry_unqualified'):
        require(saved.get(key)is True,'Verified plan Save fact required: '+key)
    for key in ('native_dispatch_pending','native_close_call_returned','close_verified','persistence_verified','generation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','post_cleanup_CAM_getters','physical_depth_verified','production_qualified','may_continue'):
        require(saved.get(key)is False,'Save-only unqualified scope required: '+key)
    require(saved.get('native_return_type')=='int' and type(saved.get('native_return_value'))is int and saved['native_return_value']==0
            and type(saved.get('native_hresult'))is int and saved['native_hresult']==0 and saved.get('native_outcome')=='save_returned_readback_verified','Strict Save int0/readback required')
    for key,pin in (('definition_gop_receipt_pin',plan['gop_pin']),('definition_gop_marker_pin',plan['marker_pin'])):
        actual=saved[key]
        require(creator.same_path(actual['path'],pin['path']) and actual['sha256']==pin['sha256'],'Exact saved GOP receipt/marker binding required')
    metadata=dict(machine_kind='mill_single_feature_qualification',process_id=context['process_id'],expected_feature_native_id=context['expected_feature_native_id'],expected_operation_native_ids=plan['operation_ids'])
    expected_before=deepcopy(plan['after']);expected_before.update(metadata)
    before,after=saved['before'],saved['after']
    require(before==expected_before and after==saved['final_state'],'Exact GOP-to-Save boundary and final snapshot required')
    _verify_save(before,after)
    require(type(expected_source_sha256)is str and re.fullmatch('[0-9a-f]{64}',expected_source_sha256)
            and after['saved_file_sha256']==saved['saved_file_sha256_after_native_return']==expected_source_sha256
            and expected_source_sha256!=context['expected_source_sha256'],'Explicit changed target SHA after native Save required')
    require(type(before['document']['needs_save'])is bool and after['document']['needs_save']is False,'Observed CAM-only dirty-unknown to clean document required')
    require(saved['state_sha256']==_digest(after) and saved['after_cleanup_sw_file']==dict(document=after['document'],saved_file_sha256=expected_source_sha256),'Exact saved digest and cleanup identity required')
    diagnostics=saved['snapshot_diagnostics'];require(type(diagnostics)is list and len(diagnostics)==3,'Three complete Save boundary captures required')
    for row,label,state in zip(diagnostics,('initial_capture','before_native_action','after_native_save'),(before,before,after)):
        captured=deepcopy(state)
        for key in metadata:captured.pop(key)
        require(row.get('phase')==label and row.get('capture_complete')is True and row.get('state')==captured,'Complete Save diagnostic boundary differs')
        actual=deepcopy(row['actual_sketch_snapshot']);expected=deepcopy(context['current_sketch_baseline'])
        expected.update(saved_file_sha256=state['saved_file_sha256'],needs_save=state['document']['needs_save'])
        sa,sb=actual.pop('solids'),expected.pop('solids')
        require(actual==expected and _same_bodies(sa,sb),'Save CAD/sketch invariants differ')
    current=deepcopy(after)
    for key in metadata:current.pop(key)
    return dict(before_sha256=context['expected_source_sha256'],after_sha256=expected_source_sha256,native_return_value=0,
                save_state_sha256=saved['state_sha256'],saved_plan_inventory=current,persistence_verified=False)


def load_saved_plan(v):
    """Read-only authority for the exact saved draft plan; no replay eligibility.

    Consumes recovery, zero-operation Save, selected GOP and post-GOP Save pins.
    Historical target SHAs are checked as receipt facts only; every immutable
    evidence file and the single current target SHA are verified freshly.
    Callers must compare fresh capture() output with saved_plan_inventory.
    """
    from scripts.sw_cam_pocket_gop_evidence import read_gop_receipt
    require(type(v)is dict,'Saved plan request object required')
    for prefix in ('definition_recovery_receipt','definition_save_receipt','definition_gop_receipt','definition_gop_save_receipt'):
        path,sha=v[prefix+'_path'],v[prefix+'_sha256']
        require(type(path)is str and Path(path).is_absolute() and Path(path).suffix.lower()=='.json'
                and type(sha)is str and re.fullmatch('[0-9a-f]{64}',sha),'Four exact absolute receipt paths and SHAs required')
    recovered=_read_recovery(v['definition_recovery_receipt_path'],v['definition_recovery_receipt_sha256'])
    saved,save_pin=read_pin(v['definition_save_receipt_path'],v['definition_save_receipt_sha256'])
    prior_source=saved['after']['saved_file_sha256']
    transition=verify_saved_transition(recovered,saved,process_id=v['process_id'],expected_document_path=v['expected_document_path'],
        expected_source_sha256=prior_source,expected_feature_native_id=v['expected_feature_native_id'])
    old=recovered['old'];request=old['request'];target=v['expected_document_path'];fid=v['expected_feature_native_id'];pins=[];historical=[]
    if 'expected_process_create_time'in v:require(v['expected_process_create_time']==request['expected_process_create_time'],'Exact owned lifetime required')
    for pin in recovered['pins']+[recovered['creator_pin'],recovered['marker_pin'],recovered['receipt_pin']]:
        if creator.same_path(pin['path'],target):
            require(pin['sha256']==request['expected_source_sha256'],'Historical creator target pin differs');historical.append(deepcopy(pin))
        else:pins.append(deepcopy(pin))
    require(historical,'Original recovered target pin required')
    historical.append(dict(path=target,sha256=prior_source,proof_receipt_sha256=save_pin['sha256']))
    sketch=definition_sketch_baseline(recovered);sketch.update(features=deepcopy(recovered['expected_inventory']['sw_reference']['feature_tree']),saved_file_sha256=prior_source,needs_save=False)
    marker=Path(target).parent/('feature_gop_'+_digest(dict(scope=SCOPE,target=creator.canonical(target),creator_sha256=recovered['creator_pin']['sha256'],feature_id=fid))+'.json')
    context=dict(scope=SCOPE,process_id=v['process_id'],expected_document_path=target,expected_source_sha256=prior_source,expected_feature_native_id=fid,
        origin_kind=recovered.get('origin_kind','recovery'),evidence=recovered['receipt_pin'],pins=pins,creator=old,recovered=recovered,save_pin=save_pin,saved_transition=transition,historical_target_pins=historical,
        expected_inventory=recovered['expected_inventory'],sketch=recovered['sketch'],current_sketch_baseline=sketch,spec=recovered['spec'],request=request,marker=marker)
    plan=read_gop_receipt(v['definition_gop_receipt_path'],v['definition_gop_receipt_sha256'],context,v['expected_operation_native_ids'])
    post,post_pin=read_pin(v['definition_gop_save_receipt_path'],v['definition_gop_save_receipt_sha256'])
    verified=_verify_saved_plan_transition(context,plan,post,v['expected_source_sha256'])
    pins.extend([save_pin,plan['gop_pin'],plan['marker_pin'],post_pin,inventory.file_pin(target,v['expected_source_sha256'])])
    require(1<=len(pins)<=64,'Bounded complete saved-plan evidence pins required')
    context.update(authority_scope='AUTODETECTED_POCKET_SAVED_PLAN_AUTHORITY_V1',expected_source_sha256=v['expected_source_sha256'],pins=pins,
        expected_operation_native_ids=deepcopy(plan['operation_ids']),saved_plan_inventory=verified['saved_plan_inventory'],
        gop_receipt_pin=plan['gop_pin'],gop_marker_pin=plan['marker_pin'],post_gop_save_pin=post_pin,verified_saved_plan_transition=verified)
    context['current_sketch_baseline']['saved_file_sha256']=v['expected_source_sha256']
    verify_files(context);return context


def definition_sketch_baseline(definition):
    """Use the actual current-source read, while retaining historical sketch evidence."""
    raw=definition['old']
    if creator.saved_caps(raw['request']):
        checks=raw.get('saved_caps_sketch_checks',[])
        require(checks and checks[0].get('readback_verified') is True,'Actual inline saved-circle baseline required')
        require(creator.same_saved_sketch_capture(checks[0]['before'],checks[0]['after']),
                'Actual inline saved-circle paired capture differs')
        return deepcopy(checks[0]['after']['snapshot'])
    return deepcopy(definition['sketch']['after'])


def read_creator_receipt(path,sha):
    """Read genuine successful creation; never synthesize a recovery receipt."""
    from scripts.sw_cam_autodetected_pocket_recovery import post_create_document
    raw,rp=read_pin(path,sha);v=raw['request'];creator.shape(v)
    require(raw.get('scope')==creator.SCOPE and raw.get('status')=='definition_only' and raw.get('phase')=='finished' and
            all(raw.get(k)is True for k in creator.FLAGS),'Successful native creator required')
    creator.clean(raw)
    for k in ('dispatch_claimed','native_call_attempted','native_call_returned','native_return_nonnull','auto_detect_islands_requested'):
        require(raw.get(k)is True,'Missing actual completed creation fact: '+k)
    for k in ('native_dispatch_pending','Save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','Import_attempted','model_saved',
              'island_geometry_getter_attempted','automatic_replay','production_qualified','island_geometry_verified','physical_depth_verified','feature_association_verified','machining_eligible'):
        require(raw.get(k)is False,'Unexpected creation action/claim: '+k)
    for label in ('before','before_confirmation','after','after_confirmation'):
        require(raw[label+'_diagnostic'].get('capture_complete')is True and raw[label].get('capture_complete')is True,
                'Four complete creator captures required')
    require(creator.same_inventory(raw['before'],raw['before_confirmation']) and
            creator.same_inventory(raw['after'],raw['after_confirmation']),'Creator paired inventory differs')
    header=raw['feature_header']
    require(type(header['native_id'])is int and header['native_id']==raw['new_feature_native_id'] and header['taper_angle_native']==0.,
            'Exact created feature/header required')
    proof=creator.verify_delta(raw['before'],raw['after'],header,v)
    require(raw['definition_proof']==proof,'Actual creator definition proof differs')
    creator.verify_delta(raw['before'],raw['after_confirmation'],header,v)
    require(creator.same_path(path,raw['receipt_path']),'Creator receipt path binding differs')
    marker=Path(v['expected_document_path']).parent/('pocket_definition_'+_digest(dict(scope=creator.SCOPE,target=creator.canonical(v['expected_document_path']),sketch=v['sketch_spec']['sketch_name']))+'.json')
    require(creator.same_path(str(marker),raw['marker_path']),'Exact consumed creator marker required')
    mark,mp=read_pin(str(marker),_file_hash(marker))
    require(mark==dict(scope=creator.SCOPE,request_digest=_digest(v),receipt_path=raw['receipt_path'],source_sha256=v['expected_source_sha256'],automatic_replay=False),
            'Consumed creator marker binding differs')
    pins=deepcopy(raw['evidence_pins']);require(type(pins)is list and 1<=len(pins)<=40,'Bounded complete creator pins required')
    needed=[(v[a],v[b])for a,b in [('expected_document_path','expected_source_sha256'),('original_document_path','original_source_sha256'),('native_geometry_path','native_geometry_sha256'),('setup_receipt_path','setup_receipt_sha256'),('setup_save_receipt_path','setup_save_receipt_sha256'),('sketch_receipt_path','sketch_receipt_sha256')]]
    needed.append((creator.__file__,_file_hash(creator.__file__)))
    sketch,_=read_pin(v['sketch_receipt_path'],v['sketch_receipt_sha256'])
    caps_data=None
    if creator.saved_caps(v):
        extra=[];caps_data=creator.validate_saved_caps(v,creator._input(v['sketch_spec']),sketch,extra)
        needed.extend((p['path'],p['sha256'])for p in extra)
        transition=raw['post_create_document_observation']
        require(transition['before']==raw['document_before'] and transition['before']['needs_save']is False and
                type(transition['after']['needs_save'])is bool and transition['after']==dict(transition['before'],needs_save=transition['after']['needs_save']),
                'Exact observed created-document transition required')
    for p,digest in needed:
        require(any(creator.same_path(pin['path'],p)and pin['sha256']==digest for pin in pins),'Missing original creator evidence pin')
    for pin in pins:
        if creator.same_path(pin['path'],v['expected_document_path']):
            require(pin['sha256']==v['expected_source_sha256'],'Historical target SHA differs')
        else:require(_file_hash(pin['path'])==pin['sha256'],'Immutable creator evidence changed')
    definition=dict(old=raw,header=deepcopy(header),expected_inventory=deepcopy(raw['after']),creator_pin=rp,marker_pin=mp,
                    receipt_pin=rp,receipt=raw,pins=pins+[rp,mp],sketch=sketch,spec=creator._input(v['sketch_spec']),
                    origin_kind='creator',caps_data=caps_data,definition_proof=proof)
    baseline=definition_sketch_baseline(definition)
    require(baseline['features']==raw['before']['sw_reference']['feature_tree'] and
            _same_bodies(baseline['solids'],raw['before']['sw_reference']['solids']) and
            baseline['pid']==v['process_id'] and creator.same_path(baseline['path'],v['expected_document_path']) and
            baseline['saved_file_sha256']==v['expected_source_sha256'],'Current creator sketch/CAD binding differs')
    expected_circle=raw['saved_caps_sketch_checks'][0]['after']['circle_readback'] if creator.saved_caps(v) else sketch['sketch_readback']
    require(raw['circle_readback']==expected_circle,'Actual creator circle readback differs')
    require(type(post_create_document(raw)['needs_save'])is bool,'Strict observed created dirty state required')
    return definition
