"""Historical configuration authority and current-source projection, offline only."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_local_configuration_resume as configured
from scripts.sw_cam_rough_firstcut import require
prior=configured.prior;common=prior.common;group=prior.group
CONFIGURATION_PRODUCER_SHA='bd1a2feab057222eeef36a28b1bb8d7b3ed1c0a750a6ce19173984a12903ea56'

def historical_tool_context(r,pin):
    serial=prior.serial;initial=serial.validate_terminal(r)
    require(group.exact(r['module_pin'],common._pin(serial.__file__))and group.exact(r['profile_module_pin'],common._pin(serial.geometry.__file__)),'Historical factory implementation differs')
    for key in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[key])
    mark,_=prior.read_json_pin(r['marker_pin']['path'],r['marker_pin']['sha256'],limit=32*1024*1024)
    require(mark['scope']==serial.SCOPE and mark['readback_verified']is True and mark['saved_source_sha256']==r['saved_source_sha256']and group.exact(mark['actions'],r['actions']),'Historical factory marker differs')
    c=deepcopy(initial);s=r['checkpoint'];sha=r['saved_source_sha256']
    c.update(state=deepcopy(s['state']),source_sha256=sha,serial_flat_catalogue=deepcopy(s['catalogue']),long_cut_initial_catalogue=deepcopy(s['catalogue']),serial_flat_tool=deepcopy(s['new_tool']),serial_flat_tool_native_id=s['new_tool_native_id'],registration=deepcopy(s['registration']))
    c['state']['saved_file_sha256']=sha;c['state']['document']=deepcopy(s['document'])
    c['deep_loaded']['guide_parameters']['document']=deepcopy(s['document'])
    c['deep_loaded']['guide_parameters']['expected_parameters']=deepcopy(s['guide_snapshot'])
    c['deep_loaded']['generated']['saved_cl']=deepcopy(s['saved_cl'])
    oldparent=c['parent_pin'];oldmarker=c['group_marker_pin']
    c['pins']=common._merge([v for v in c['pins']if common._key(v['path'])!=common._key(oldparent['path'])],[pin])
    c['offline_export_proof_pins']=common._merge(c['offline_export_proof_pins'],[oldparent,oldmarker,r['marker_pin'],r['loaded_context_pin']])
    c.update(parent_pin=pin,group_marker_pin=deepcopy(r['marker_pin']),authority_kind='saved_serial_flat_tool_unassigned')
    c['current_context_sha256']=serial.prior._digest(group.current_projection(c))
    return c

def reconstruct_configuration(r):
    """Revalidate immutable ancestors without requiring their old SHA on current disk."""
    require(r['module_pin']['sha256']==CONFIGURATION_PRODUCER_SHA and group.exact(r['module_pin'],common._pin(configured.__file__)),'Exact configuration checkpoint producer required')
    partial,ppin=prior.read_json_pin(r['adopted_receipt_pin']['path'],r['adopted_receipt_pin']['sha256'],limit=32*1024*1024)
    pmark,pmpin=prior.read_json_pin(r['adopted_marker_pin']['path'],r['adopted_marker_pin']['sha256'],limit=8*1024*1024)
    original=partial['request']
    require(common._key(pmpin['path'])==common._key(configured.parent.marker_path(original))and group.exact(pmark,configured.parent.Journal(partial,original['receipt_path'],pmpin['path'])._marker_state()),'Interrupted prefix marker differs')
    failed,fpin=prior.read_json_pin(original['failed_receipt_path'],original['failed_receipt_sha256'],limit=32*1024*1024)
    fmark,fmpin=prior.read_json_pin(original['failed_marker_path'],original['failed_marker_sha256'])
    old=failed['request']
    require(common._key(fmpin['path'])==common._key(prior.marker_path(old))and group.exact(fmark,configured.assembly.Journal(failed,old['receipt_path'],fmpin['path'])._marker_state()),'Definition marker differs')
    tool,tpin=prior.read_json_pin(old['tool_receipt_path'],old['tool_receipt_sha256'],limit=32*1024*1024)
    recipe,recipepin=prior.read_json_pin(old['recipe_path'],old['recipe_sha256'])
    outer=historical_tool_context(tool,tpin)
    backup=common._pin(old['source_backup_path']);require(backup['sha256']==outer['source_sha256']==partial['source_sha256']==r['source_sha256'],'Immutable pre-configuration backup differs')
    loaded=prior.projection.project_context(outer,recipe,None,old['choices'],verify_feature=prior.mixed.verify_pocket,feed_policy=old['feed_policy'])
    loaded.update(source_sha256=outer['source_sha256'],local_verified_context=deepcopy(outer),local_recipe=deepcopy(recipe),sealed_choices=deepcopy(old['choices']),sealed_feed_policy=deepcopy(old['feed_policy']))
    adopted=configured.parent.partial_contract(failed,loaded)
    loaded.update(local_plan=adopted['plan'],adopted_definition_context=adopted,adopted_receipt_pin=fpin,adopted_marker_pin=fmpin)
    context=configured.partial_contract(partial,loaded)
    stop,spin=prior.read_json_pin(r['writer_stop_pin']['path'],r['writer_stop_pin']['sha256'])
    stoppins=configured.writer_stop_contract(stop,r['request'],ppin)
    loaded.update(configuration_resume_context=context,configuration_resume_partial=partial,configuration_resume_pin=ppin,configuration_resume_marker_pin=pmpin,writer_stop_pin=spin)
    verification=configured.validate_completed(r,loaded)
    markpath=configured.marker_path(r['request']);mark,markpin=prior.read_json_pin(str(markpath),prior._file_hash(markpath),limit=8*1024*1024)
    require(group.exact(mark,configured.Journal(r,r['request']['receipt_path'],str(markpath))._marker_state()),'Saved configuration source marker differs')
    require(group.exact(partial['tool_receipt_pin'],tpin)and group.exact(partial['recipe_pin'],recipepin),'Exact tool and recipe ancestry required')
    extras=common._merge([ppin,pmpin,fpin,fmpin,tpin,recipepin,backup,spin,markpin,r['module_pin']],stoppins,r['live_pins'],r['phase_proof_pins'])
    return loaded,outer,verification,extras

def project_current(r,loaded,outer,p):
    require(r['request']['process_id']==p['process_id']and common._key(r['source_path'])==common._key(p['expected_document_path'])and r['saved_source_sha256']==p['expected_source_sha256'],'Exact saved configuration source/PID/document required')
    require(group.exact(r['ownership'],loaded['ownership']),'Saved process lifetime differs')
    s=r['saved_checkpoint'];snapshot=r['saved'];targets=r['learned_targets']
    require(group.exact(s['snapshot'],snapshot)and group.exact(s['document'],r['source_transition']['document'])and s['source_sha256']==r['saved_source_sha256'],'Configuration checkpoint snapshot/source differs')
    require(group.exact(s['saved_cl'],r['saved_cl'])and group.exact(s['learned_targets'],targets)and group.exact(s['current_counts'],dict(operations=21,parameters=12,paths=14,tools=21))and s['GTP_complete']is False,'Exact configured21/12/14 checkpoint required')
    require(group.exact(s['tool_catalogue'],loaded['serial_flat_catalogue'])and group.exact(s['tool_dimensions'],loaded['local_tool_dimensions']),'Saved tool catalogue/profile differs')
    require(len(targets)==4 and len({t['operation_native_id']for t in targets})==4 and [t['operation_type']for t in targets]==[0,1,0,1],'Exactly the learned four rough/finish targets required')
    configured.cl.contract(snapshot['binding'],loaded['guide_parameters']['expected_parameters']['binding'],targets)
    own={v['operation_native_id']:v for v in snapshot['parameters']}
    for target in targets:
        oid=target['operation_native_id'];prior.micro.verify_final(own[oid]['nc']['feeds_compensation'])
        require(group.exact(r['nc_readbacks'][str(oid)]['values'],own[oid]['nc']['feeds_compensation']),'Saved NC readback differs from complete snapshot')
    doc=deepcopy(s['document']);require(doc['needs_save']is False,'Saved clean document required')
    current=deepcopy(loaded)
    # The protected17/8 baseline is retained for the established native adapter;
    # the fresh first capture must additionally equal this complete saved21/12.
    current['guide_parameters']['document']=doc
    current['generated']['saved_cl']=deepcopy(r['saved_cl'])
    current['source_sha256']=r['saved_source_sha256']
    current['state']=dict(document=deepcopy(doc),saved_file_sha256=r['saved_source_sha256'])
    current['configuration_generation']=dict(snapshot=deepcopy(snapshot),targets=deepcopy(targets),nc_readbacks=deepcopy(r['nc_readbacks']))
    current['configuration_receipt']=deepcopy(r)
    outer_current=deepcopy(outer);outer_current['source_sha256']=r['saved_source_sha256']
    return current,outer_current

def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256,check_current=True):
    """Pure receipt authority for generation or read-only clients; no COM/Open/Save."""
    require(type(check_current)is bool,'Explicit current-file checking flag required')
    require(type(process_id)is int and 0<process_id<2**31 and type(expected_document_path)is str and Path(expected_document_path).is_absolute(),'Exact process and absolute document required')
    prior._sha(expected_source_sha256)
    r,pin=prior.read_json_pin(path,digest,limit=32*1024*1024)
    historical,outer,verification,extra=reconstruct_configuration(r)
    p=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    loaded,outer_current=project_current(r,historical,outer,p)
    if check_current:require(prior._file_hash(expected_document_path)==expected_source_sha256,'Current saved configuration file differs')
    loaded['configuration_receipt_pin']=pin
    proofs=common._merge(extra,[pin,common._pin(__file__)])
    common._check(proofs)
    return loaded,outer_current,verification,proofs
