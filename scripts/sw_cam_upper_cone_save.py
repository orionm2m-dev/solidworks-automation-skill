"""One native save of the verified existing upper-cone feature and sketch.

No creator, GOP, GTP, assignment or geometry setter. The original feature
receipt is checked before connection; successful save only rebinds source/dirty.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import base64,json,re
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts import sw_cam_upper_cone_feature as cone

SCOPE='MILL_UPPER_CONE_SAVE_EXISTING_V1'

def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)
def _key(path):return str(Path(path).resolve()).casefold()
def _check_pins(pins):
    for pin in pins:require(_file_hash(pin['path'])==pin['sha256'],'Pinned save evidence changed')
def _payload(loaded):return dict(rough=deepcopy(loaded['payload']),finish=deepcopy(loaded['finish_payload']))

def save_marker(source,source_sha256,new_id):
    value=_digest(dict(scope=SCOPE,source=_key(source),source_sha256=source_sha256,new_feature_native_id=new_id))
    return Path(source).resolve().parent/('upper_cone_save_'+value+'.json')

def _historical_baseline(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Same archived checkpoint checks; saved source was intentionally superseded."""
    data,pin=cone._json_pin(path,digest)
    require(data.get('scope')==cone.BASELINE_SCOPE and data.get('status')=='verified_offline_terminal_branch'
        and data.get('old_loader_verified') is True and data.get('runtime_rebind_explicit') is True,'Verified branch baseline required')
    require(type(process_id) is int and data['process_id']==process_id and data['source_sha256']==expected_source_sha256
        and _key(data['source_path'])==_key(expected_document_path),'Exact original process/source required')
    cone._verify_archive(data['archived_inputs'])
    rows=[v for v in data['archived_inputs'] if _key(v['pin']['path'])==_key(data['terminal_pin']['path'])]
    require(len(rows)==1 and rows[0]['pin']['sha256']==data['terminal_pin']['sha256'],'Archived terminal receipt binding differs')
    terminal=json.loads(base64.b64decode(rows[0]['base64'],validate=True).decode('utf-8-sig'))
    ctx=data['context'];checkpoint=data['terminal_checkpoint']
    require(terminal['checkpoint']==checkpoint and data['context_sha256']==_digest(ctx),'Archived terminal/context differs')
    require(checkpoint['state']==ctx['state'] and checkpoint['payload']==_payload(ctx)
        and checkpoint['source_sha256']==expected_source_sha256,'Original checkpoint source/payload differs')
    require(ctx['state']['document']['needs_save'] is False and len(ctx['state']['features'])==19
        and len(ctx['state']['operations'])==6,'Exact saved19/6 baseline required')
    require(_key(data['candidate_pin']['path'])==_key(cone.__file__) and data['candidate_pin']['sha256']==_file_hash(cone.__file__)
        and _key(data['new_server_pin']['path'])==_key(cone.runtime_root().parent/'mcp-server/server.py'),'Cone runtime/server binding differs')
    pins=canonical_evidence_pins(data['live_pins'],[pin]);_check_pins(pins)
    result=deepcopy(ctx);result.update(pin=pin,pins=pins,ids=deepcopy(data['ids']),baseline=data,historical_only=True)
    return result

def load_completed_upper_cone_feature(path,digest,*,process_id,expected_document_path,expected_source_sha256,
        expected_feature_native_id,check_current_source=True):
    data,pin=read_pin(path,digest)
    require(data.get('scope')==cone.SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
        and data.get('process_id')==process_id and data.get('expected_source_sha256')==expected_source_sha256
        and data.get('source_after_sha256')==expected_source_sha256 and _key(data['expected_document_path'])==_key(expected_document_path),
        'Exact completed cone receipt/source required')
    require(type(expected_feature_native_id) is int and expected_feature_native_id>0 and data['new_feature_native_id']==expected_feature_native_id,'Exact new feature ID required')
    for name in ('native_call_attempted','native_call_returned','readback_verified','feature_delta_verified','native_configuration_captured'):
        require(data.get(name) is True,'Incomplete cone creation: '+name)
    for name in ('native_dispatch_pending','GOP_attempted','GTP_attempted','save_attempted','model_saved','sketch_edit_attempted','CAD_solid_edit_attempted'):
        require(data.get(name) is False,'Unexpected cone creation action: '+name)
    require(type(data.get('creator_call_count')) is int and data['creator_call_count']==1
        and not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Uncertain cone cannot be saved')
    clean_events(data)
    identity=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    baseline=data['baseline_pin']
    loaded=(cone.load_upper_cone_baseline if check_current_source else _historical_baseline)(baseline['path'],baseline['sha256'],**identity)
    sketch_pin=data['sketch_receipt_pin'];sketch,_=read_pin(sketch_pin['path'],sketch_pin['sha256']);spec=sketch['before']['spec']
    cone.validate_cone_request(sketch_spec=spec,taper_angle_native=data['requested_taper']['value'],taper_type=data['requested_taper']['type'],acknowledge_unqualified_taper=True)
    _,_,expected=cone.load_sketch_prerequisite(sketch_pin['path'],sketch_pin['sha256'],loaded,spec,process_id)
    mass_comparisons={}
    cone.require_state_equivalent(expected,data['before'],diagnostic=mass_comparisons.setdefault('feature_prestate',{}))
    require(data['before_payload']==data['after_payload']==_payload(loaded),'Cone protected payload differs')
    require(cone.verify_feature_delta(data['before'],data['after'],expected_feature_native_id,69,diagnostic=mass_comparisons.setdefault('feature_delta',{}))==data['new_feature'],'Cone inventory delta differs')
    observation=data['cone_observation']
    require(cone.verify_cone_geometry(observation['feature'],observation['sketch_circle_m'],expected_feature_native_id,
        expected_taper_angle_native=data['requested_taper']['value'])==data['geometry_acceptance'],'Cone observation differs')
    require(len(data['after']['operations'])==6 and data['after']['document']['needs_save'] is True,'Exact unsaved20/6 required')
    marker=cone.cone_marker(expected_document_path,expected_source_sha256);mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==cone.SCOPE and mark.get('status')=='review_required'
        and mark.get('readback_verified') is True and mark.get('native_call_returned') is True
        and _key(mark['receipt_path'])==_key(path) and mark['receipt_sha256']==digest,'Completed cone marker differs')
    import scripts.sw_cam_ud14_save as save_core
    pins=canonical_evidence_pins(loaded['pins'],[sketch_pin,pin,markpin,_self_pin(),_pin(save_core.__file__)])
    _check_pins(pins)
    loaded.update(state=deepcopy(data['after']),reference19=deepcopy(data['before']),cone_receipt=data,cone_receipt_pin=pin,
        cone_marker_pin=markpin,sketch_receipt_pin=deepcopy(sketch_pin),cone_observation=deepcopy(observation),sketch_spec=deepcopy(spec),
        new_feature_native_id=expected_feature_native_id,pins=pins,lineage_pins=[],parent_pin=pin,historical_only=not check_current_source,
        numerical_comparisons=mass_comparisons)
    return loaded

def verify_save_delta(before,after,source_after,*,diagnostic=None):
    require(len(before['features'])==20 and len(before['operations'])==6 and before['document']['needs_save'] is True,'Exact dirty20/6 before Save required')
    expected=deepcopy(before);expected['document']['needs_save']=False;expected['saved_file_sha256']=source_after
    return cone.require_state_equivalent(expected,after,diagnostic=diagnostic)

class UpperConeSaveContext(cone.UpperConeContext):
    def files(self):
        super().files();_check_pins(self.loaded.get('lineage_pins',[]))


def load_completed_upper_cone_save(path,digest,*,process_id,expected_document_path,expected_source_sha256,
        expected_feature_native_id,check_current_source=True):
    data,pin=read_pin(path,digest)
    require(data.get('scope')==SCOPE and data.get('status')=='review_required' and data.get('phase')=='finished'
        and data.get('process_id')==process_id and _key(data['expected_document_path'])==_key(expected_document_path)
        and data.get('new_feature_native_id')==expected_feature_native_id,'Exact completed cone Save required')
    require(data.get('save_attempted') is True and data.get('native_call_attempted') is True and data.get('mutation_attempted') is True
        and data.get('native_call_returned') is True and data.get('save_pending') is False
        and data.get('model_saved') is True and data.get('save_readback_verified') is True and data.get('readback_verified') is True
        and data.get('native_return_type')=='int' and type(data.get('native_return_value')) is int and data['native_return_value']==0,
        'Incomplete/uncertain native cone Save')
    require(not any(k in data for k in ('issue','failed_phase','receipt_write_error'))
        and all(data.get(k) is False for k in ('GOP_attempted','GTP_attempted','creator_attempted','CAD_solid_edit_attempted')),'Save scope/failure differs')
    require(data['save_module_pin']==_self_pin(),'Save implementation changed');clean_events(data)
    source_before=data['source_before_sha256'];parent=data['parent_pin']
    loaded=load_completed_upper_cone_feature(parent['path'],parent['sha256'],process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=source_before,expected_feature_native_id=expected_feature_native_id,check_current_source=False)
    source_after=data['saved_file_sha256'];require(source_after==expected_source_sha256,'Saved source binding differs')
    cone.require_state_equivalent(loaded['state'],data['before_context'],diagnostic=loaded['numerical_comparisons'].setdefault('save_prestate',{}))
    require(data['before_payload']==data['after_payload']==_payload(loaded),'Saved cone payload differs')
    verify_save_delta(loaded['state'],data['after_context'],source_after,diagnostic=loaded['numerical_comparisons'].setdefault('save_delta',{}))
    require(data['before_cone']==data['after_cone']==loaded['cone_observation'],'Saved cone/sketch geometry differs')
    normalized=dict(state=loaded['state'],payload=_payload(loaded),cone_observation=loaded['cone_observation'])
    require(data['before']==data['after']==normalized,'Save-core normalized snapshots differ')
    require(data['source_transition']==dict(source_before_sha256=source_before,source_after_sha256=source_after,
        clean_document=data['after_context']['document'],strict_native_save_return=0),'Saved source transition differs')
    checkpoint=dict(state=data['after_context'],payload=data['after_payload'],cone_observation=data['after_cone'],
        sketch_spec=loaded['sketch_spec'],new_feature_native_id=expected_feature_native_id,source_sha256=source_after)
    require(data['checkpoint']==checkpoint and data['checkpoint_sha256']==_digest(checkpoint),'Saved cone checkpoint differs')
    marker=save_marker(expected_document_path,source_before,expected_feature_native_id);mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==SCOPE and mark.get('status')=='review_required'
        and mark.get('save_pending') is False and mark.get('model_saved') is True and mark.get('receipt_sha256')==digest
        and _key(mark['receipt_path'])==_key(path),'Completed cone Save marker differs')
    retired=[loaded['cone_receipt_pin'],loaded['cone_marker_pin']];keys={_key(p['path']) for p in retired}
    live=[p for p in loaded['pins'] if _key(p['path']) not in keys]
    loaded.update(state=deepcopy(checkpoint['state']),source_sha256=source_after,
        pins=canonical_evidence_pins(live,[pin,markpin]),lineage_pins=retired,
        save_receipt=data,save_receipt_pin=pin,parent_pin=pin,checkpoint=deepcopy(checkpoint),historical_only=not check_current_source)
    _check_pins(loaded['pins']);_check_pins(retired)
    if check_current_source:require(_file_hash(expected_document_path)==source_after,'Current saved document changed')
    return loaded


def save_existing_upper_cone(sw,clsid,typelib_path,*,cone_receipt_path,cone_receipt_sha256,process_id,
        expected_document_path,expected_source_sha256,expected_feature_native_id,receipt_path,
        qualification_only,acknowledge_disposable_copy,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True and message_policy=='vendor_default','Explicit disposable qualification required')
    identity=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    loaded=load_completed_upper_cone_feature(cone_receipt_path,cone_receipt_sha256,**identity)
    target=Path(receipt_path);marker=save_marker(expected_document_path,expected_source_sha256,expected_feature_native_id)
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.lower()=='.json' and not target.exists() and not target.is_symlink()
        and not marker.exists() and not marker.is_symlink(),'Fresh receipt and never-attempted Save required')
    protected={_key(p['path']) for p in loaded['pins']}|{_key(expected_document_path)}
    require(_key(target) not in protected and _key(marker) not in protected and _key(marker)!=_key(target),'Save outputs alias source/evidence')
    args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,expected_document_path=expected_document_path,
        source_before_sha256=expected_source_sha256,new_feature_native_id=expected_feature_native_id,parent_pin=loaded['cone_receipt_pin'],
        save_module_pin=_self_pin(),evidence_pins=deepcopy(loaded['pins']),marker_path=str(marker),receipt_path=str(target),
        save_attempted=False,save_pending=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        model_saved=False,readback_verified=False,save_readback_verified=False,GOP_attempted=False,GTP_attempted=False,
        creator_attempted=False,CAD_solid_edit_attempted=False,automatic_replay=False,production_qualified=False,snapshot_diagnostics=[])
    created=claimed=False;session=ctx=save_app=None;started=monotonic()
    def marker_state():
        return dict(scope=SCOPE,status=report['status'],save_pending=report['save_pending'],model_saved=report['model_saved'],
            receipt_path=str(target),receipt_sha256=_file_hash(target),source_before_sha256=expected_source_sha256,
            new_feature_native_id=expected_feature_native_id,automatic_replay=False)
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
        state,native=cone._capture_headers(ctx,clsid,loaded['reference19'],20,diag)
        report[label+'_context']=deepcopy(state);diag['observed_state']=deepcopy(state);persist()
        try:payload=cone._capture_payload(ctx,state,native,diag)
        finally:persist()
        report[label+'_payload']=deepcopy(payload);persist()
        observation=cone._read_sketch_and_cone(ctx,native,loaded['sketch_spec'],expected_feature_native_id)
        report[label+'_cone']=deepcopy(observation);persist()
        require(observation==loaded['cone_observation'],'Existing cone/sketch observation changed')
        if label=='before':cone.require_state_equivalent(loaded['state'],state,diagnostic=diag.setdefault('state_comparison',{}))
        else:verify_save_delta(loaded['state'],state,report['saved_file_sha256'],diagnostic=diag.setdefault('state_comparison',{}))
        with ctx.guard() as g:save_app=g.typed(ctx.app,'ICWApp')
        normalized=deepcopy(state);normalized['document']['needs_save']=True;normalized['saved_file_sha256']=expected_source_sha256
        normalized=cone.require_state_equivalent(loaded['state'],normalized,diagnostic=diag.setdefault('core_state_normalization',{}));persist()
        return dict(state=normalized,payload=payload,cone_observation=observation)
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
        ctx=UpperConeSaveContext(loaded,args,sw,typelib_path,None,events,loaded['state']);ctx.files();ctx.identity()
        ctx.app=_bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity();session=CamMessageSession(ctx.app,typelib_path)
        with session:
            expected=dict(state=loaded['state'],payload=_payload(loaded),cone_observation=loaded['cone_observation'])
            def verify(value):require(value==expected,'Normalized Save capture changed')
            def native_save():boundary();return _member(save_app,'SaveActiveDocument')
            run_one_existing_save(report,capture=capture,verify=verify,guard=boundary,claim=claim,persist=persist,save=native_save,saved_hash=saved_hash)
        events(False);ctx.files();require(ctx.identity()==report['after_context']['document'],'Save cleanup identity changed')
        checkpoint=dict(state=report['after_context'],payload=report['after_payload'],cone_observation=report['after_cone'],
            sketch_spec=loaded['sketch_spec'],new_feature_native_id=expected_feature_native_id,source_sha256=report['saved_file_sha256'])
        report.update(status='review_required',phase='finished',readback_verified=True,model_saved=True,
            checkpoint=checkpoint,checkpoint_sha256=_digest(checkpoint),reopen_persistence_verified=False)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,model_saved=False)
    finally:
        if session is not None:report['messages']=session.summary()
        persist()
    return report

PARAMS={'cone_receipt_path','cone_receipt_sha256','process_id','expected_document_path','expected_source_sha256','expected_feature_native_id',
        'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy','addin_clsid','module_sha256'}
def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='save_existing_upper_cone','Only save-existing action supported')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact Save request fields required')
    require(type(p['process_id']) is int and p['process_id']>0 and type(p['expected_feature_native_id']) is int and p['expected_feature_native_id']>0,'Exact PID and feature ID required')
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'] and p['qualification_only'] is True and p['acknowledge_disposable_copy'] is True
        and p['message_policy']=='vendor_default','Exact module and qualification required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact add-in CLSID required')
    return dict(p)

def dispatch_request(request):
    p=validate_request(request)
    load_completed_upper_cone_feature(p['cone_receipt_path'],p['cone_receipt_sha256'],**{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256','expected_feature_native_id')})
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        require(type(_member(sw,'GetProcessID')) is int and _member(sw,'GetProcessID')==p['process_id'],'Connected PID differs')
        return save_existing_upper_cone(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),**p)

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
