"""Current saved mixed-pocket authority for the fixed host read qualification."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_mixed_root_finish as authority
from scripts import sw_cam_mill_packet_projection as projection
from scripts import sw_cam_inprocess_reader as reader

def reference_from_loaded(loaded,authority_pin):
    """Project actual native inventory and current parameter rows, not old plans."""
    gp=loaded['guide_parameters'];document=deepcopy(gp['document']);conf=gp['configuration']
    require=reader.require
    require(conf['names_consistent']is True and conf['associated_sw_configuration_matches']is True and
        conf['cam_configuration_name']==conf['configuration_object_name'] and
        conf['associated_sw_configuration_name']==conf['sw_configuration_name'],'Current configuration binding required')
    document['configuration']=conf['sw_configuration_name']
    snapshot=deepcopy(gp['expected_parameters'])
    snapshot['parameters']=[projection.config.parameter_projection(row)for row in snapshot['parameters']]
    binding=snapshot['binding'];operations=binding['operations'];opmap={row['native_id']:row for row in operations}
    inventory={row['header']['native_id']:row for row in loaded['root_pocket_native_inventory']}
    feature_ids=[int(key)for key in binding['features']]
    owners=set()
    for fid in feature_ids:
        require(fid in inventory and projection.reader.group.exact(inventory[fid]['header'],binding['features'][str(fid)]),
            'Actual saved native feature inventory differs from baseline')
        owners.add(inventory[fid]['owner_setup_native_id'])
    require(len(owners)==1 and type(next(iter(owners)))is int,'Single actual feature setup owner required')
    targets=[]
    for row in snapshot['parameters']:
        op=opmap[row['operation_native_id']]
        require(op['linked_feature_ids']==[row['feature_native_id']] and row['read_complete']is True,
            'Current parameter linkage differs')
        targets.append(dict(operation_native_id=op['native_id'],feature_native_id=row['feature_native_id'],
            operation_type=op['mill_operation_type'],tool_native_id=op['assigned_tool']['native_id'],
            setup_native_id=op['setup_native_id']))
    require(len(operations)==17 and len(targets)==8,'Current qualification is exactly seventeen/eight')
    ownership=loaded['ownership']
    request=dict(schema_version=2,profile='mill_snapshot',expected_process_id=ownership['process_id'],
        expected_document_path=document['path'],cam_addin_clsid=reader.CAM_CLSID,
        expected_sw_configuration=conf['sw_configuration_name'],expected_cam_configuration=conf['cam_configuration_name'],
        expected_operation_ids=[row['native_id']for row in operations],feature_ids=feature_ids,
        feature_setup_id=next(iter(owners)),parameter_targets=targets)
    registration=loaded['root_pocket_registration']
    require(registration['clsid']==reader.CAM_CLSID,'Fixed installed CAM registration required')
    typelib=Path(registration['addin_path']).parent/'camworks.tlb'
    candidates=[p for p in loaded['pins']if reader.key(p['path'])==reader.key(typelib)]
    require(len(candidates)==1,'Current actual CAM typelib pin required')
    return dict(verified_current_checkpoint=True,authority_pin=deepcopy(authority_pin),
        source_sha256=loaded['source_sha256'],ownership=deepcopy(ownership),document=document,mill_request=request,
        expected_snapshot=snapshot,cam_typelib_pin=deepcopy(candidates[0]),
        live_pins=deepcopy(loaded['pins']),pins=deepcopy(loaded['pins']+loaded['checkpoint_pins']))

def provide_reference(authority_pin):
    require=reader.require
    require(type(authority_pin)is dict and set(authority_pin)=={'path','sha256','bytes'},'Exact completed checkpoint pin required')
    loaded=authority.load_completed(authority_pin['path'],authority_pin['sha256'],check_current=True)
    actual=loaded['root_pocket_checkpoint_pin']
    require(type(actual)is dict and set(actual)=={'path','sha256'} and
        actual['sha256']==authority_pin['sha256'] and reader.key(actual['path'])==reader.key(authority_pin['path']),
        'Loaded current checkpoint identity differs')
    require(type(authority_pin['bytes'])is int and authority_pin['bytes']>0 and
        Path(authority_pin['path']).stat().st_size==authority_pin['bytes'],'Sealed checkpoint byte size differs')
    reference=reference_from_loaded(loaded,authority_pin)
    reference['provider_pin']=authority.common._pin(__file__)
    reference['pins'] += [authority.common._pin(__file__),authority.common._pin(authority.__file__)]
    return reference

