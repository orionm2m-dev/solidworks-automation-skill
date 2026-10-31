"""Export one saved finish-pocket route through the existing guarded CL core.

The current flat checkpoint owns the exact operation order and generated counts.
The five earlier complete CL streams must survive unchanged. No generation,
setter, assignment, model save, WIP export or postprocessor is performed.
"""
from copy import deepcopy
from pathlib import Path
import importlib
import json
import math
import re
from scripts import sw_cam_chamfer_exports as cl
from scripts.sw_cam_cl_inventory import verify_export_operation_inventory
from scripts.sw_cam_generic_cl_reader import parse_generic_cl_bytes
from scripts.sw_cam_chamfer_cl_review import block_signature
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_upper_cone_feature import require_state_equivalent
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require

common, group = cl.common, cl.group
SCOPE = 'SAVED_FINISH_POCKET_CL_EXPORT_V1'
AUTHORITY = 'saved_pocket_finish_geometry_review_pending'
ORDER = [195, 196, 267, 247, 248, 271, 143, 144]
UNGENERATED = [195, 196]
PROTECTED_IDS = [267, 247, 248, 271, 143]
# These completed writers and inactive readers are checked at phase boundaries.
PARENT_LOADERS={
    'SAVED_POCKET_FINISH_GENERATE_V1':'scripts.sw_cam_pocket_finish_apply',
    'PARTIAL_POCKET_FINISH_CONTINUATION_V1':'scripts.sw_cam_pocket_finish_continuation',
    'REOPENED_POCKET_WALL_CONTINUATION_V1':'scripts.sw_cam_pocket_wall_continue',
}

RETIRED = {'sw_cam_pocket_finish_apply.py', 'sw_cam_pocket_rough_apply.py',
    'sw_cam_shared_cutter_geometry.py', 'sw_cam_shared_holder_geometry.py',
    'sw_cam_ud14_save.py', 'sw_cam_read_progress_journal.py'}


def validate_catalogue_authority(loaded):
    historical=cl.validate_catalogue_authority(loaded)
    current=loaded['neck_tool_checkpoint']['catalogue'];candidate=loaded['neck_tool_candidate']
    tid=candidate['native_id'];full=candidate['full_tool']
    require(type(tid) is int and tid>0 and len(current)==19 and len({r['native_id'] for r in current})==19
        and tid not in {r['native_id'] for r in historical}
        and group.exact([r for r in current if r['native_id']!=tid],historical),'Exact saved19 with protected18 required')
    selected=next(r for r in current if r['native_id']==tid)
    require(type(selected['tool_type_raw']) is int and type(full['tool_type_raw']) is int and selected['tool_type_raw']==full['tool_type_raw']==1 and full['tool_native_id']==tid
        and group.exact(selected['CutDiameter'],full['cut_diameter_native'])
        and group.exact(selected['Protrusion'],full['tool_protrusion_native'])
        and full.get('geometry_read_complete') is True and full.get('profile_complete') is True,
        'Current additional tool differs from its saved full profile')
    require(loaded['neck_tool_checkpoint']['profile_qualification']['profile_verified'] is True,
        'Saved full candidate profile qualification required')
    return deepcopy(current)


def assignment_from_catalogue(row):
    """Map the observed scalar catalogue to the separate operation-reader schema.

    Station number belongs to the catalogue. The operation reader reports
    native_cut/protrusion names and explicit read/qualification flags instead.
    Preserve the exact returned float values; do not nominalize protrusion.
    """
    require(set(row)=={'native_id','tool_type_raw','CutDiameter','Protrusion','StnNo'}
        and type(row['native_id']) is int and row['native_id']>0
        and type(row['tool_type_raw']) is int and row['tool_type_raw']==1,
        'Exact separate flat-tool scalar catalogue schema required')
    require(all(type(row[k]) in (int,float) and math.isfinite(row[k]) and row[k]>0
        for k in ('CutDiameter','Protrusion')), 'Actual finite cutter/protrusion required')
    return dict(native_id=row['native_id'],is_mill_tool=True,native_read_complete=True,
        units_verified=False,holder_geometry_verified=False,tool_type_raw=row['tool_type_raw'],
        cut_diameter_native=row['CutDiameter'],protrusion_native=row['Protrusion'])


def operation_contract(loaded):
    state,target=loaded['state'],loaded['generated_pocket_finish']
    require(loaded['authority_kind']==AUTHORITY and target['geometry_acceptance_complete'] is False,
        'Saved finish-pocket authority with geometry review pending required')
    tid=loaded['neck_tool_candidate']['native_id']
    require((target['native_id'],target['feature_native_id'],target['tool_native_id'])==(144,79,tid),
        'Exact current finish feature/tool identity required')
    require(len(state['features'])==21 and state['operation_count']==8 and [r['native_id'] for r in state['operations']]==ORDER
        and state['document']['needs_save'] is False,'Exact current saved eight-operation order required')
    for index,row in enumerate(state['operations']):
        require(row['operation_index']==index and row['setup_native_id']==93 and row['setup_index']==0,'Operation/setup position differs')
    byid={r['native_id']:r for r in state['operations']}
    for oid,fid,typ,tool,tooltyp in ((267,265,20,249,1),(247,244,0,263,14),(248,244,1,249,1),(271,264,1,269,8),(143,79,0,145,1),(144,79,1,tid,1)):
        row=byid[oid]
        require(row['linked_feature_ids']==[fid] and row['mill_operation_type']==typ
            and row['assigned_tool']['native_id']==tool and row['assigned_tool']['tool_type_raw']==tooltyp,'Current operation binding differs')
    require(byid[267]['toolpath_record_counts']==loaded['toolpath_record_counts']
        and byid[271]['toolpath_record_counts']==loaded['configured_contour']['record_counts']
        and byid[143]['toolpath_record_counts']==loaded['generated_pocket']['record_counts'],'Protected generated counts differ')
    catalogue=validate_catalogue_authority(loaded);selected=next(r for r in catalogue if r['native_id']==tid)
    require(group.exact(byid[144]['assigned_tool'],assignment_from_catalogue(selected)),'Actual finish assigned scalar tool differs from saved19 catalogue')
    contract=[dict(operation_native_id=oid,toolpath_record_counts=deepcopy(byid[oid]['toolpath_record_counts'])) for oid in PROTECTED_IDS+[144]]
    verify_export_operation_inventory(state['operations'],144,target['record_counts'],UNGENERATED,contract)
    return contract


def protected_reference(recovery_path,recovery_sha256,loaded):
    recovery,recoverypin=read_pin(recovery_path,recovery_sha256)
    require(recovery.get('scope')=='SAVED_ROUGH_CL_OFFLINE_EXPORT_RECONCILIATION_V1'
        and recovery.get('status')=='export_reconciled_geometry_review_pending'
        and type(recovery.get('native_calls')) is int and recovery['native_calls']==0
        and all(recovery.get(k) is True for k in ('saved_checkpoint_readback_verified','output_verified','protected_streams_verified','parse_complete','native_count_matches'))
        and all(recovery.get(k) is False for k in ('original_receipt_rewritten','original_marker_rewritten','reexport_attempted','generation_attempted','model_saved','automatic_replay')),
        'Completed immutable offline rough export reconciliation required')
    pins=[recoverypin]+[recovery[k] for k in ('original_export_receipt_pin','original_export_marker_pin','saved_checkpoint_pin','CL_pin','parser_pin','recovery_module_pin')]
    pins.append(recovery['historical_parser']['historical_parser_archive_pin']);common._check(pins)
    require(recovery['historical_parser']['original_parser_pin']['sha256']==pins[-1]['sha256'],'Historical parser archive differs')
    parser=importlib.import_module('scripts.sw_cam_generic_cl_reader')
    require(recovery['parser_pin']['sha256']==_file_hash(parser.__file__),'Qualified parsing implementation differs')
    receipt,pin=read_pin(recovery['original_export_receipt_pin']['path'],recovery['original_export_receipt_pin']['sha256'])
    require(receipt.get('scope')=='SAVED_ROUGH_POCKET_CL_EXPORT_V1' and receipt.get('phase')=='finished'
        and receipt.get('native_call_attempted') is True and receipt.get('native_call_returned') is True
        and receipt.get('native_dispatch_pending') is False and type(receipt.get('native_hresult')) is int and receipt['native_hresult']==0
        and receipt.get('post_cleanup_document_file_verified') is True and group.exact(receipt['before'],receipt['after']),
        'Original completed native export and unchanged snapshot required')
    old=receipt['before']['expected_generated_operations']
    require(group.exact(old,recovery['expected_generated_operations']) and group.exact(old,operation_contract(loaded)[:5]),
        'Exact five saved prior operation counts required')
    require(receipt['saved_checkpoint_pin']['sha256']==recovery['saved_checkpoint_pin']['sha256'],'Recovery checkpoint binding differs')
    previous={r['native_id']:r for r in receipt['before']['mill_state']['operations']};current={r['native_id']:r for r in loaded['state']['operations']}
    require(all(group.exact(previous[oid],current[oid]) for oid in PROTECTED_IDS),'One of five protected operations changed')
    clpin=recovery['CL_pin']
    require(clpin['sha256']==receipt['output']['sha256'] and Path(clpin['path']).stat().st_size==receipt['output']['bytes'],'Original exported CL bytes differ')
    parsed=parse_generic_cl_bytes(Path(clpin['path']).read_bytes(),expected_block_record_counts=[v['toolpath_record_counts'][0] for v in old])
    require(parsed['parse_complete'] is True and parsed['native_count_matches'] is True and len(parsed['operation_blocks'])==5,'Complete prior five-stream CL required')
    return dict(protected_cl_receipt_pin=pin,protected_cl_pin=deepcopy(clpin),protected_cl_contract=deepcopy(old),
        protected_cl_recovery_pin=recoverypin,protected_reference_pins=pins)


def preserved_streams(raw,loaded):
    common._check([loaded['protected_cl_pin'],loaded['protected_cl_receipt_pin'],loaded['protected_cl_recovery_pin']])
    contract=operation_contract(loaded)
    baseline=parse_generic_cl_bytes(Path(loaded['protected_cl_pin']['path']).read_bytes(),
        expected_block_record_counts=[r['toolpath_record_counts'][0] for r in contract[:5]])
    parsed=parse_generic_cl_bytes(raw,expected_block_record_counts=[r['toolpath_record_counts'][0] for r in contract])
    require(all(p['parse_complete'] is True and p['native_count_matches'] is True for p in (baseline,parsed))
        and len(baseline['operation_blocks']) == 5 and len(parsed['operation_blocks']) == 6,
        'Complete native-count-matched six/five CL streams required')
    require(parsed['declared_units'] == baseline['declared_units'] == ['MM'], 'Protected metric CL declaration changed')
    require([c['raw'] for c in parsed['commands'] if c['name']=='BOX'] ==
        [c['raw'] for c in baseline['commands'] if c['name']=='BOX'], 'Protected CL stock declaration changed')
    signatures=[block_signature(parsed,i) for i in range(6)];matches=[]
    for old in range(5):
        hits=[i for i,sig in enumerate(signatures) if sig == block_signature(baseline,old)]
        require(len(hits)==1,'Prior complete CL stream changed or is ambiguous')
        matches.append(hits[0])
    require(matches == [0,1,2,3,4], 'Protected CL stream order differs from saved route')
    return dict(prior_five_complete_streams_unchanged=True,added_block=5,added_operation_native_id=144,
        unchanged=[dict(native_id=oid,old_block=i,new_block=i) for i,oid in enumerate(PROTECTED_IDS)],
        basis='Unique complete command/motion/circle matches; labels are not native IDs',
        new_finish_geometry_verified=False)


def load_checkpoint(path,digest,*,process_id,expected_document_path,expected_source_sha256,
                    protected_cl_recovery_path,protected_cl_recovery_sha256):
    parent,parentpin=read_pin(path,digest)
    scope=parent.get('scope')
    require(type(scope) is str and scope in PARENT_LOADERS,'Unsupported completed finish parent scope')
    loader=importlib.import_module(PARENT_LOADERS[scope])
    require(loader.SCOPE==scope,'Exact scoped finished writer required')
    loaded=loader.load_completed(path,digest,process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256)
    require(common._key(loaded['parent_pin']['path'])==common._key(parentpin['path'])
        and loaded['parent_pin']['sha256']==parentpin['sha256'],'Loader must retain the exact requested completed parent')
    operation_contract(loaded);validate_catalogue_authority(loaded)
    require(loaded['source_sha256'] == loaded['state']['saved_file_sha256'] == expected_source_sha256
        == _file_hash(expected_document_path) and _digest(group.current_projection(loaded)) == loaded['current_context_sha256'],
        'Exact current saved flat checkpoint required')
    require(set(loaded['pocket_parameters']) == {'143','144'} and type(loaded['pocket_startpoints']) is dict,
            'Final saved pocket pair parameters and startpoints required')
    reference=protected_reference(protected_cl_recovery_path,protected_cl_recovery_sha256,loaded)
    retired_names=set(RETIRED)
    if scope in ('PARTIAL_POCKET_FINISH_CONTINUATION_V1','REOPENED_POCKET_WALL_CONTINUATION_V1'):retired_names.add(Path(loader.__file__).name)
    retired=[p for p in loaded['pins'] if Path(p['path']).name in retired_names]
    require({Path(p['path']).name for p in retired}==retired_names and any(common._key(p['path']) == common._key(loader.__file__) for p in retired),
            'Completed finish writer must remain an explicit offline proof')
    names=('sw_cam_chamfer_exports','sw_cam_cl_inventory','sw_cam_mill_generic_cl',
        'sw_cam_thread_postprocess','sw_cam_operation_profile','sw_cam_generic_cl_reader','sw_cam_chamfer_cl_review')
    added=[common._pin(__file__)]+[common._pin(importlib.import_module('scripts.'+n).__file__) for n in names]
    live=common._merge([p for p in loaded['pins'] if p not in retired],added)
    offline=common._merge(loaded['offline_export_proof_pins'],retired,
        reference['protected_reference_pins'])
    require(len(live)<=64,'Bounded export live closure required')
    common._check(live);common._check(offline);common._check(loaded['bootstrap_export_pins'])
    return dict(loaded,pins=live,offline_export_proof_pins=offline,export_phase_retired_pins=retired,
        export_parent_pins=deepcopy(loaded['pins']),export_parent_scope=scope,**reference)


def marker_path(source,sha):
    return common.local_evidence_root()/('pocket_finish_cl_'+_digest(dict(scope=SCOPE,source=common._key(source),
        source_sha256=sha,operation_native_id=144))+'.json')


def fresh_paths(loaded,args):
    marker=marker_path(args['expected_document_path'],args['expected_source_sha256'])
    receipt=Path(args['receipt_path']);observation=receipt.with_suffix('.observations.json')
    paths=(marker,receipt,observation)
    protected={common._key(p['path']) for p in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']}
    protected.add(common._key(args['expected_document_path']))
    require(all(p.is_absolute() and p.suffix.casefold()=='.json' and p.parent.is_dir()
        and not p.exists() and not p.is_symlink() for p in paths),'Fresh evidence and once marker required')
    require(len({common._key(p) for p in paths})==3 and not protected.intersection(common._key(p) for p in paths),
        'Export evidence aliases protected input')
    return marker,observation


class Evidence(cl.Evidence):
    def __init__(self,loaded,args):
        self.loaded,self.args=loaded,dict(args);self.marker,self.observation=fresh_paths(loaded,args)
        self.created=self.claimed=False;self.marker_signature=None
        self.details=dict(scope=SCOPE,parent_pin=deepcopy(loaded['parent_pin']),
            generated_marker_pin=deepcopy(loaded['group_marker_pin']),source_sha256=args['expected_source_sha256'],
            live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
            fresh_fields=cl.FRESH_SCOPE,reused_fields=cl.REUSED_SCOPE+['saved_finish144_parameters_and_startpoints','saved_neck_tool_full_profile','protected_five_stream_recovery'],observations=[])
    def marker_state(self,report):
        return dict(super().marker_state(report),scope=SCOPE,operation_native_id=144)
    def fields(self):
        return dict(super().fields(),scope=SCOPE,checkpoint_export_scope=SCOPE,
            protected_cl_pin=deepcopy(self.loaded['protected_cl_pin']),
            protected_cl_receipt_pin=deepcopy(self.loaded['protected_cl_receipt_pin']),
            protected_cl_recovery_pin=deepcopy(self.loaded['protected_cl_recovery_pin']),
            reused_fields=self.details['reused_fields'],protected_streams_verified=False)


def verify_observed(loaded,observed):
    diagnostic={};normalized=require_state_equivalent(loaded['state'],observed['state'],diagnostic=diagnostic)
    operation_contract(dict(loaded,state=normalized))
    require(group.exact(observed['catalogue'],validate_catalogue_authority(loaded)),'Current scalar catalogue differs')
    require(group.exact(observed['selected_defaults'],loaded['configured_contour']['defaults']), 'Protected chamfer settings changed')
    cl.defaults.validate_defaults(observed['selected_defaults'])
    require(group.exact(observed['settings'],loaded['settings'])
        and group.exact(observed['units'],loaded['finish_payload']['unit_record'])
        and group.exact(observed['binding'],next(r['assigned_tool'] for r in loaded['state']['operations'] if r['native_id']==267)),
        'Protected FACE parameters, tool binding or units changed')
    require(group.exact(observed['selected_feature'],loaded['cone_observation']['feature']), 'Protected chamfer feature changed')
    return normalized,diagnostic


class CLContext(cl.CLContext):
    def __init__(self,loaded,args,sw,clsid,typelib_path):
        self.loaded,self.args=loaded,dict(args);self.evidence=Evidence(loaded,args);self.check=None
        # Existing bounded reader deliberately still checks the protected chamfer.
        reader_args=dict(args,feature_native_id=loaded['configured_contour']['feature_native_id'])
        self.backend=cl.ReadBackend(loaded,reader_args,sw,clsid,typelib_path,self.evidence.details,
            self.evidence.persist_observations,external_events=lambda active:self.check(active=active))
    def validate(self,**request):
        from scripts.sw_cam_mill_generic_cl import validate_mill_cl_request
        require(request['action']=='apply' and request['acknowledge_machine_scope'] is True,'Explicit machine scope required')
        validate_mill_cl_request(**dict(request,action='prepare',expected_state_sha256=None,receipt_path=None,
            expected_generated_operations=operation_contract(self.loaded)))
    def selected(self,state,feature_id,operation_id,operation_type):
        require((feature_id,operation_id,operation_type)==(79,144,1),'Selected finish identity differs')
        operation_contract(dict(self.loaded,state=state))
        return next(r for r in state['operations'] if r['native_id']==144)
    def capture(self,sw,clsid,typelib_path,app,check,diagnostic):
        self.check=check;self.backend.ctx.app=app
        observed=self.backend.capture_export(diagnostic['phase'])
        self.evidence.details['observations'].append(deepcopy(observed));self.evidence.persist_observations()
        normalized,comparison=verify_observed(self.loaded,observed)
        diagnostic.update(saved_checkpoint_match_verified=True,comparison=comparison,raw_observation=deepcopy(observed))
        return normalized,self.backend.native


def export_cl(sw,clsid,typelib_path,*,loaded,args,output_path):
    from scripts.sw_cam_mill_generic_cl import export_mill_generic_cl
    context=CLContext(loaded,args,sw,clsid,typelib_path)
    result=export_mill_generic_cl(sw,clsid,typelib_path,
        **{k:args[k] for k in ('process_id','expected_document_path','expected_source_sha256',
            'qualification_only','acknowledge_disposable_copy','message_policy','receipt_path')},
        expected_feature_native_id=79,expected_operation_native_id=144,expected_mill_operation_type=1,
        expected_toolpath_record_counts=loaded['generated_pocket_finish']['record_counts'],
        expected_ungenerated_operation_ids=UNGENERATED,expected_generated_operations=operation_contract(loaded),
        acknowledge_machine_scope=True,action='apply',output_path=output_path,_context_adapter=context)
    if context.evidence.created:
        bounded=group.return_observation(result.get('native_hresult'))
        context.evidence.details['core_return_observation']=bounded;result['bounded_native_hresult']=deepcopy(bounded)
        if not bounded['value_recorded']:result['native_hresult']=None
        context.evidence.persist_observations()
    try:
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);context.backend.ctx.files()
        result['phase_proofs_verified_after_export']=True
        if result.get('phase')=='finished' and result.get('readback_verified') is True and result.get('output_verified') is True:
            require(context.evidence.claimed,'Successful export requires consumed marker')
            require(context.backend.ctx.identity()==loaded['state']['document'],'Export cleanup changed document')
            output=result['output'];require(_file_hash(output['path'])==output['sha256'],'CL bytes changed before preservation check')
            result['protected_stream_association']=preserved_streams(Path(output['path']).read_bytes(),loaded)
            result['protected_streams_verified']=True;result['checkpoint_export_readback_verified']=True
    except Exception as exc:
        from scripts.sw_cam import _error
        result.update(status='uncertain',phase_proofs_verified_after_export=False,checkpoint_export_readback_verified=False,
            protected_streams_verified=False,readback_verified=False,output_verified=False,phase_proof_error=_error(exc))
    if context.evidence.claimed:context.persist(result)
    if Path(args['receipt_path']).is_file():_write_receipt(args['receipt_path'],result)
    return result


PARAMS=common.COMMON|{'output_path','protected_cl_recovery_path','protected_cl_recovery_sha256'}


def prepare(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='export_cl','Only saved finish-route CL export allowed')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact finish export fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Strict owned process required')
    for k,v in p.items():
        if k.endswith('sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Strict SHA required')
        if k.endswith('path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy']=='vendor_default','Exact qualified CL export scope required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']), 'Exact CAM CLSID required')
    loaded=load_checkpoint(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],
        **{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256',
            'protected_cl_recovery_path','protected_cl_recovery_sha256')})
    args={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy')}
    common._local_receipt(args['receipt_path']);fresh_paths(loaded,args)
    from scripts.sw_cam_mill_generic_cl import validate_mill_cl_request
    validate_mill_cl_request(**{k:args[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'qualification_only','acknowledge_disposable_copy','message_policy')},expected_feature_native_id=79,
        expected_operation_native_id=144,expected_mill_operation_type=1,
        expected_toolpath_record_counts=loaded['generated_pocket_finish']['record_counts'],
        expected_ungenerated_operation_ids=UNGENERATED,expected_generated_operations=operation_contract(loaded),
        action='prepare',acknowledge_machine_scope=True,output_path=p['output_path'])
    return p,args,loaded


def dispatch_request(request,*,validate_only=False):
    p,args,loaded=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,authority_kind=loaded['authority_kind'],
        live_pin_count=len(loaded['pins']),generated_operation_contract=operation_contract(loaded),
        protected_cl_pin=loaded['protected_cl_pin'])
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=args['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        registration=common.discover_export_registration(loaded,p['addin_clsid'])
        sw,_=connect_solidworks(process_id=args['process_id'],launch_new_instance=False,wait_seconds=1)
        return export_cl(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),
            loaded=loaded,args=args,output_path=p['output_path'])


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--validate-only',action='store_true')
    o=p.parse_args(argv);r=dispatch_request(json.loads(Path(o.request).read_text(encoding='utf-8-sig')),validate_only=o.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1

if __name__=='__main__':raise SystemExit(main())
