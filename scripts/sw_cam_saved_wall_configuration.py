"""Load a saved wall configuration without inventing a generated toolpath."""
from copy import deepcopy
from scripts import sw_cam_wall_configuration_save as writer
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
parent,common,group=writer.parent,writer.common,writer.group


def validate_saved(r):
    require(r['scope']==writer.SCOPE and r['status']=='saved_configuration_no_toolpath' and r['phase']=='finished'
        and r['model_saved'] is True and r['readback_verified'] is True and r['phase_proofs_verified'] is True,'Completed saved configuration required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')),'Uncertain configuration cannot become authority')
    require(set(r['actions'])=={'SaveActiveDocument'} and all(r[k] is False for k in ('setter_attempted','assignment_attempted','GTP_attempted','automatic_replay','geometry_acceptance_complete','production_qualified')),'Only configuration save is allowed')
    parent.wall.history.verified_action(r['actions']['SaveActiveDocument'])
    require(r['generated_record_counts']==[],'Configuration cannot claim a wall path')
    loaded=deepcopy(r['loaded_context_before']);parent.qualify_scope(loaded)
    parent.no_output(r['latest_status'])
    parent.verify_capture(loaded,r['before'],corrected=True,generated=False)
    parent.verify_capture(loaded,r['final'],corrected=True,generated=False,saved_sha=r['saved_source_sha256'])
    parent.wall.equivalent_projection(parent.wall.save_projection(r['before']),parent.wall.save_projection(r['final']))
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save stage incomplete')
    transition=r['source_transition']
    require(type(transition['strict_save_return']) is int and transition['strict_save_return']==0
        and transition['source_before_sha256']==r['initial_source_sha256'] and transition['source_after_sha256']==r['saved_source_sha256']
        and r['initial_source_sha256']!=r['saved_source_sha256'],'Strict changed saved transition required')
    clean_events(r)
    loaded.update(state=deepcopy(r['final']['state']),source_sha256=r['saved_source_sha256'],
        pocket_parameters=parent.original.projected(r['final']['parameters']),pocket_startpoints=deepcopy(r['final']['startpoints']),
        authority_kind='saved_wall_configuration_no_toolpath')
    loaded['neck_tool_checkpoint']=dict(loaded['neck_tool_checkpoint'],catalogue=deepcopy(r['final']['catalogue']))
    loaded.pop('generated_pocket_finish',None)
    loaded['current_context_sha256']=_digest(group.current_projection(loaded))
    return loaded


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(writer.__file__) and r['process_id']==process_id
        and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved configuration source, process or writer changed')
    for key in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[key])
    loaded=validate_saved(r);pins=common._merge(r['live_pins'],[pin,common._pin(__file__)])
    require(len(pins)<=64,'Bounded saved configuration closure required')
    loaded.update(pins=pins,offline_export_proof_pins=deepcopy(r['offline_proof_pins']),bootstrap_export_pins=deepcopy(r['bootstrap_export_pins']),parent_pin=pin)
    return loaded
