"""Current saved18 authority and explicit owned-process transition; no CAD calls."""
from copy import deepcopy
from pathlib import Path
from scripts import saved_generation_engagement as authority
from scripts import sw_cam_guide_group_reopen as reopen
from scripts import sw_cam_mill_packet_projection as projection
from scripts import sw_cam_inprocess_reader as host
require=reopen.require
common,group=reopen.common,reopen.group
SCOPE='SAVED_EIGHTEEN_CURRENT_CHECKPOINT_V1'
AUTHORITY_SHA='5880baae836dafda003d6d84b9b9ee12caa7931f9cde8f3f72e707a24f078c1b'

def project(q,r,c,serial,serial_pin,authority_pin):
    require(q['status']=='qualified_saved_input'and q['original_receipt_status']=='uncertain'and q['original_receipt_modified']is False,'Explicit qualified offline authority required')
    require(q['source_sha256']==r['saved_source_sha256']and q['receipt_pin']['sha256']==q['generation_receipt_pin']['sha256'],'Current source/receipt lineage differs')
    require(r['cleanup_session_active']is False and r['messages']['active']is False and r['messages']['disconnected']is True,'Historical writer must be disconnected')
    saved=deepcopy(r['saved']);binding=saved['binding'];ops=binding['operations']
    require(len(ops)==21 and len(saved['parameters'])==12 and len(binding['features'])==6,'Exact saved21/12/6 required')
    rows=[dict(operation_native_id=o['native_id'],toolpath_record_counts=o['toolpath_record_counts'])for o in ops if o['toolpath_generated']is True]
    require(len(rows)==18 and rows==q['saved_cl']['expected_generated_operations'],'Exact saved18 native stream counts required')
    cp=c['saved_checkpoint'];require(c['saved_source_sha256']==r['source_sha256']and r['configuration_receipt_pin']['sha256']==q['configuration_receipt_pin']['sha256'],'Historical configuration link differs')
    require(group.exact(r['before'],cp['snapshot']),'Pre-generation snapshot differs from saved configuration')
    sc=serial['checkpoint'];owners={str(v['geometry']['native_id']):v['setup_native_id']for v in sc['state']['features']if str(v['geometry']['native_id'])in binding['features']}
    require(set(owners)==set(binding['features'])and all(type(v)is int and v>0 for v in owners.values()),'Actual saved feature owners required')
    protected=deepcopy(saved);protected['binding']['operations']=protected['binding']['operations'][:17];protected['parameters']=protected['parameters'][:8]
    for setup in protected['binding']['operation_setups']:setup['operation_count']=sum(o['setup_native_id']==setup['native_id']for o in protected['binding']['operations'])
    doc=deepcopy(r['source_transition']['document']);require(doc['needs_save']is False and doc['type']==1,'Clean saved current document required')
    pins=deepcopy(r['live_pins']);generated=[p for p in pins if Path(p['path']).name.startswith('_FE488661_0BD8_11D6_2012_2018CE99E55F_')and Path(p['path']).suffix=='.py']
    require(len(generated)==1,'Exact generated CAM declarations required')
    loaded=dict(pins=pins,ownership=deepcopy(r['ownership']),source_sha256=q['source_sha256'],generated_pin=generated[0],
        guide_parameters=dict(document=doc,configuration=deepcopy(cp['configuration']),baseline=deepcopy(binding),expected_parameters=protected,targets=[]),
        current_snapshot=saved,deep_targets=deepcopy(r['learned_targets']),local_feature_owners=owners,
        configuration_tool=deepcopy(r['learned_targets'][0]['assigned_tool']),serial_flat_catalogue=deepcopy(cp['tool_catalogue']),
        tool_dimensions=deepcopy(r['tool_dimensions']),generated=dict(saved_cl=deepcopy(q['saved_cl'])),
        checkpoint_pins=common._merge(q['direct_dependency_pins'],[authority_pin,serial_pin,common._pin(__file__)]),
        bootstrap_export_pins=deepcopy(serial['bootstrap_export_pins']),qualified_authority_pin=deepcopy(authority_pin),
        registration=deepcopy(sc['registration']),configuration_pins=[deepcopy(q['configuration_receipt_pin'])])
    loaded['local_tool_dimensions']=deepcopy(loaded['tool_dimensions'])
    loaded['state']=dict(document=deepcopy(doc),saved_file_sha256=q['source_sha256'])
    loaded['phase_proof_pins']=deepcopy(loaded['checkpoint_pins'])
    loaded['pin_partition']=dict(scope='QUALIFIED_DIRECT_SAVED18_AUTHORITY',recursive_ancestry_repeated=False,full_ancestry_previously_verified=True)
    return loaded

def load_current(path,digest):
    require(authority.pin(authority.__file__)['sha256']==AUTHORITY_SHA,'Frozen qualification implementation differs')
    q=authority.load_qualified(path,digest);r=authority.read(q['receipt_pin']['path'],q['receipt_pin']['sha256'])
    c=authority.read(q['configuration_receipt_pin']['path'],q['configuration_receipt_pin']['sha256'])
    candidates=[p for p in r['phase_proof_pins']if Path(p['path']).name=='ACTUAL_ROOT_SERIAL_TOOL_SAVED_NATIVE.json']
    require(len(candidates)==1,'Unique historical actual serial-tool checkpoint required')
    serial_pin=candidates[0];serial=authority.read(serial_pin['path'],serial_pin['sha256'])
    result=project(q,r,c,serial,serial_pin,authority.pin(path))
    common._check(result['checkpoint_pins']);return result,q

def host_reference(loaded):
    snap=deepcopy(loaded['current_snapshot']);snap['parameters']=[projection.config.parameter_projection(v)for v in snap['parameters']]
    conf=loaded['guide_parameters']['configuration'];doc=deepcopy(loaded['guide_parameters']['document']);doc['configuration']=conf['sw_configuration_name']
    require(conf['names_consistent']is True and conf['associated_sw_configuration_matches']is True,'Exact saved configuration required')
    ops=snap['binding']['operations'];opmap={o['native_id']:o for o in ops};targets=[]
    for row in snap['parameters']:
        o=opmap[row['operation_native_id']];require(o['linked_feature_ids']==[row['feature_native_id']]and row['read_complete']is True,'Complete actual parameter binding required')
        require(group.exact(row['tool']['generic'],o['assigned_tool']),'Actual parameter tool differs')
        targets.append(dict(operation_native_id=o['native_id'],feature_native_id=row['feature_native_id'],operation_type=o['mill_operation_type'],tool_native_id=o['assigned_tool']['native_id'],setup_native_id=o['setup_native_id']))
    owners=loaded['local_feature_owners'];require(len(set(owners.values()))==1,'One actual feature setup required')
    tlb=Path(loaded['registration']['addin_path']).parent/'camworks.tlb';matching=[p for p in loaded['pins']if common._key(p['path'])==common._key(tlb)]
    require(len(matching)==1,'Pinned CAM type library required')
    req=dict(schema_version=2,profile='mill_snapshot',expected_process_id=loaded['ownership']['process_id'],expected_document_path=doc['path'],cam_addin_clsid=host.CAM_CLSID,
        expected_sw_configuration=conf['sw_configuration_name'],expected_cam_configuration=conf['cam_configuration_name'],expected_operation_ids=[o['native_id']for o in ops],
        feature_ids=[int(k)for k in snap['binding']['features']],feature_setup_id=next(iter(owners.values())),parameter_targets=targets)
    require(len(targets)==12 and len(req['expected_operation_ids'])==21 and len(req['feature_ids'])==6,'Bounded21/12/6 host request required')
    return dict(scope=SCOPE,verified_current_checkpoint=True,source_sha256=loaded['source_sha256'],ownership=deepcopy(loaded['ownership']),document=doc,
        mill_request=req,expected_snapshot=snap,cam_typelib_pin=deepcopy(matching[0]),authority_pin=deepcopy(loaded['qualified_authority_pin']),
        live_pins=deepcopy(loaded['pins']),pins=deepcopy(loaded['checkpoint_pins']),counts=dict(operations=21,parameters=12,features=6,paths=18),
        host_activation_qualified=False,host_native_compatibility_qualified=False,production_qualified=False)


def verify_transition(loaded,closed,exited,startup):
    """Adopt a different PID only after proved close, empty exit and new launch."""
    old=loaded['ownership'];sha=loaded['source_sha256'];path=loaded['guide_parameters']['document']['path']
    require(closed.get('scope')=='SAVED_EIGHTEEN_CLOSE_FOR_OWNED_RESTART_V1'and closed.get('status')=='saved_part_closed'and closed.get('phase')=='finished'and closed.get('readback_verified')is True and closed.get('close_verified')is True,'Completed saved18 close required')
    require(closed.get('authority_pin')==loaded['qualified_authority_pin']and group.exact(closed['ownership'],old)and closed['source_sha256']==sha and common._key(closed['source_path'])==common._key(path),'Close authority/owner/source differs')
    require(closed.get('open_documents_after_close')==[]and closed.get('messages',{}).get('active')is False and closed.get('messages',{}).get('disconnected')is True,'Closed process/event session must be empty and disconnected')
    require(closed.get('cleanup_session_active')is False and not any(k in closed for k in ('issue','cleanup_issue','failed_phase')),'Closed event session required')
    require(group.exact(closed['before_close_binding'],loaded['current_snapshot']['binding']),'Close route differs')
    require(set(closed['actions'])=={'CloseActiveDocument'},'Exactly one close action required')
    action=closed['actions']['CloseActiveDocument'];require(action.get('attempted')is True and action.get('returned')is True and action.get('status')=='verified'and action.get('readback_verified')is True and action.get('native_dispatch_pending')is False,'Single close outcome unverified')
    ret=action.get('native_return',{});require(ret.get('python_type')=='int'and ret.get('value_recorded')is True and type(ret.get('value'))is int and ret['value']==0,'Strict native close S_OK required')
    require(all(closed.get(k)is False for k in ('save_attempted','GTP_attempted','exit_attempted','launch_attempted','automatic_retry')),'Unexpected close side effect')
    require(exited.get('scope')=='OWNED_VERIFIED_EMPTY_SESSION_EXIT_V1'and exited.get('status')=='exited'and exited.get('phase')=='finished','Verified empty-session exit required')
    require(all(exited.get(k)is True for k in ('readback_verified','process_exit_verified','empty_session_verified','saved_files_preserved','exit_attempted','exit_returned'))and exited.get('exit_call_count')==1,'Single graceful exit must be observed')
    require(all(exited.get(k)is False for k in ('terminate_rights_requested','termination_attempted','save_attempted','close_document_attempted','launch_attempted','automatic_retry','native_dispatch_pending')),'Unexpected exit side effect')
    require(not any(k in exited for k in ('issue','cleanup_issue','exit_error'))and exited.get('open_documents_before')==[]and exited.get('open_documents_final')==[],'Exit must preserve empty owned process')
    ep=exited['request'];require(ep['process_id']==old['process_id']and ep['expected_source_sha256']==sha and common._key(ep['expected_document_path'])==common._key(path),'Exit source/old PID differs')
    handle=closed['owner_handle_before_close'];require(handle==closed['owner_handle_before']and exited['owner_before']==handle and ep['expected_creation_filetime']==handle['creation_filetime'],'Close/exit exact process handle lifetime differs')
    require(common._key(ep['expected_executable_path'])==common._key(old['executable']),'Exit executable differs')
    require(startup.get('status')=='ok'and startup.get('phase')=='connected'and startup.get('launch_mode')=='executable'and startup.get('launch_attempted')is True and startup.get('new_process_verified')is True,'New owned executable launch required')
    new=deepcopy(startup['process_identity']);pid=startup['process_id']
    require(type(pid)is int and pid>0 and pid!=old['process_id']and new['process_id']==pid and new['alive']is True,'Distinct new live PID required')
    require(type(startup['known_process_ids_before'])is list and pid not in startup['known_process_ids_before']and old['process_id']not in startup['known_process_ids_before'],'Old PID must be absent and new PID unowned before launch')
    require(common._key(new['executable'])==common._key(old['executable'])==common._key(startup['executable']),'New executable differs')
    require(type(new['create_time'])in(int,float)and type(startup['launch_intent_time'])in(int,float)and 0<=new['create_time']-startup['launch_intent_time']<=120 and new['create_time']>old['create_time'],'New owned process timing differs')
    result=deepcopy(loaded);result['historical_ownership']=deepcopy(old);result['ownership']=new
    result['ownership_transition']=dict(scope='VERIFIED_EMPTY_EXIT_TO_NEW_EXECUTABLE_V1',old_process_id=old['process_id'],new_process_id=pid,source_sha256=sha,source_unchanged=True)
    return result
