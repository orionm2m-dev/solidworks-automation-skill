"""Export a corrected saved Contour from its current flat checkpoint.

Only the scoped completed-receipt loader establishes current authority. Historical T5 source
bytes are not reopened as the current model. Existing CL/WIP export cores own
native calls, guarded captures, durable once markers, and output verification.
"""
from copy import deepcopy
from pathlib import Path
import importlib
import json
import re
from scripts import sw_cam_chamfer_exports as cl
from scripts import sw_cam_chamfer_wip as wip
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require

common,group=cl.common,cl.group
AUTHORITY='saved_contour_approach_geometry_review_pending'
RETIRED_ROLES=frozenset({'sw_cam_chamfer_approach_correction.py','sw_cam_chamfer_generate.py',
    'sw_cam_ud14_save.py','sw_cam_chamfer_nc_planes.py','sw_cam_chamfer_clearance_read.py'})


def load_checkpoint(path,digest,*,action,process_id,expected_document_path,expected_source_sha256):
    require(action in ('export_cl','export_wip'),'Only existing route exports allowed')
    correction=importlib.import_module('scripts.sw_cam_chamfer_approach_correction')
    receipt_loader=importlib.import_module('scripts.sw_cam_chamfer_receipt')
    loaded=receipt_loader.load_completed(path,digest,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    require(loaded['authority_kind']==AUTHORITY,'Completed corrected flat authority required')
    require(loaded['source_sha256']==loaded['state']['saved_file_sha256']==expected_source_sha256
        and _file_hash(expected_document_path)==expected_source_sha256
        and loaded['state']['document']['needs_save'] is False
        and common._key(loaded['state']['document']['path'])==common._key(expected_document_path),
        'Current saved source/clean document differs')
    require(_digest(group.current_projection(loaded))==loaded['current_context_sha256'],
            'Flat current-context digest differs')
    cl.operation_contract(loaded);cl.validate_catalogue_authority(loaded)
    cl.defaults.validate_defaults(loaded['configured_contour']['defaults'])
    require(type(loaded['approach_settings']) is dict and loaded['approach_settings'],
            'Completed approach observation required')
    retired=[p for p in loaded['pins'] if Path(p['path']).name in RETIRED_ROLES]
    require(any(common._key(p['path'])==common._key(correction.__file__) for p in retired),
            'Exact completed correction implementation must be retired as offline proof')
    active=[p for p in loaded['pins'] if p not in retired]
    names=['sw_cam_chamfer_exports','sw_cam_cl_inventory','sw_cam_chamfer_receipt']
    if action=='export_cl':names+=['sw_cam_mill_generic_cl','sw_cam_thread_postprocess','sw_cam_operation_profile']
    else:names+=['sw_cam_chamfer_wip','sw_cam_completed_gtp_wip']
    added=[common._pin(__file__)]+[common._pin(importlib.import_module('scripts.'+n).__file__) for n in names]
    live=common._merge(active,added)
    offline=common._merge(loaded['offline_export_proof_pins'],retired)
    require(len(live)<=64,'Corrected export live dependency bound exceeded')
    require(any(common._key(p['path'])==common._key(loaded['parent_pin']['path']) for p in live),
            'Current completed receipt must remain live')
    common._check(live);common._check(offline);common._check(loaded['bootstrap_export_pins'])
    result=dict(loaded,pins=live,offline_export_proof_pins=offline,
        export_phase_retired_pins=deepcopy(retired),export_parent_pins=deepcopy(loaded['pins']),
        corrected_export_action=action)
    if action=='export_wip':result['wip_phase_retired_pins']=deepcopy(retired)
    return result


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action'] in ('export_cl','export_wip'),'Exact corrected export action required')
    action=request['action'];p=request['params']
    wanted=common.COMMON|({'output_path'} if action=='export_cl' else {'output_dir','project_root'})
    require(type(p) is dict and set(p)==wanted,'Exact corrected export request fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Strict owned process required')
    for key,value in p.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if key.endswith('path') or key in ('output_dir','project_root'):
            require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy']=='vendor_default','Exact qualified export scope required')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']), 'Exact CAM CLSID required')
    return action,deepcopy(p)


def prepare(request):
    action,p=validate_request(request)
    identity={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    loaded=load_checkpoint(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],action=action,**identity)
    args={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy')}
    common._local_receipt(args['receipt_path'])
    if action=='export_cl':
        cl.fresh_paths(loaded,args)
        from scripts.sw_cam_mill_generic_cl import validate_mill_cl_request
        target=loaded['configured_contour']
        validate_mill_cl_request(**{k:args[k] for k in ('process_id','expected_document_path',
            'expected_source_sha256','qualification_only','acknowledge_disposable_copy','message_policy')},
            expected_feature_native_id=target['feature_native_id'],expected_operation_native_id=target['native_id'],
            expected_mill_operation_type=1,expected_toolpath_record_counts=target['record_counts'],
            expected_ungenerated_operation_ids=cl.UNGENERATED,expected_generated_operations=cl.operation_contract(loaded),
            action='prepare',acknowledge_machine_scope=True,output_path=p['output_path'])
    else:
        marker,_=wip.fresh_paths(loaded,args)
        wip.core.output_plan(p['output_dir'],p['project_root'],p['receipt_path'],p['expected_document_path'],loaded['pins'],marker)
    return action,p,args,loaded


def dispatch_request(request,*,validate_only=False):
    action,p,args,loaded=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,
        authority_kind=loaded['authority_kind'],live_pin_count=len(loaded['pins']),
        generated_operation_contract=cl.operation_contract(loaded),
        approach_settings_reused=True,approach_settings_reread=False)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=args['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        registration=common.discover_export_registration(loaded,p['addin_clsid'])
        sw,_=connect_solidworks(process_id=args['process_id'],launch_new_instance=False,wait_seconds=1)
        typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
        if action=='export_cl':
            return cl.export_cl(sw,registration['clsid'],typelib,loaded=loaded,args=args,output_path=p['output_path'])
        return wip.export_wip(sw,registration['clsid'],typelib,loaded=loaded,args=args,
                              project_root=p['project_root'],output_dir=p['output_dir'])


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true');opts=parser.parse_args(argv)
    result=dispatch_request(json.loads(Path(opts.request).read_text(encoding='utf-8-sig')),validate_only=opts.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
