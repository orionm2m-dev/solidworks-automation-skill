"""Read only one newly inserted FACE operation from a completed read-only recovery checkpoint.

Prior CAD/route/tool geometry is reused evidence. This observer does not
revalidate the complete route and cannot authorize any mutation or generation.
"""
from copy import deepcopy
from pathlib import Path
import json,math,re
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_comtypes import _is_comtypes_pointer
from scripts.sw_cam_face_interfaces import FACE_IIDS,query_face_interface,audit_interfaces
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool,integer
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_executable_launch import _process_identity,_same_path
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins

SCOPE='READ_ONLY_NEW_FACE_PARAMETERS_V2'
PROPERTIES={'CutMethod':'int','NumberOfCuts':'int','EqualizeToolLoading':'bool','MachiningExtent':'int',
 'ShapeExtent':'int','IslandXYAllowance':'float','IslandCleanupPass':'bool','CutAngle':'float',
 'AutoAngle':'bool','MillingType':'int','ZigZagType':'bool','CutOrder':'int'}
SCALARS={'GetBottomAllowance':'float','GetFinalCutAmount':'float','GetAvoidAllowance':'float',
 'GetContainAllowance':'float','GetContainType':'int'}
PAIRS=('GetMaxStepOver','GetMinSideOffset','GetMaxSideOffset','GetFirstCutAmount','GetMaxCutAmount')
FEATURE_PAIRS=('GetLeadInClearance','GetLeadOutClearance','GetPassClearance',
 'GetLinkThresholdAlongCut','GetLinkThresholdBetweenCuts')
FEATURE_INTS=('GetLinkTypeAlongCutUptoThreshold','GetLinkTypeAlongCutAboveThreshold',
 'GetLinkTypeBetweenCutsUptoThreshold','GetLinkTypeBetweenCutsAboveThreshold')
NC_FIELDS={'GetSpndlSpeed':'float','GetTlpComp':'int','GetCNCComp':'int','GetRetractType':'int',
 'GetClrPlaneUseSetupStatus':'bool','GetRpdPlaneUseSetupStatus':'bool'}
READ_MEMBERS=frozenset(PROPERTIES)|frozenset(SCALARS)|frozenset(PAIRS)|frozenset(FEATURE_PAIRS)|frozenset(FEATURE_INTS)|frozenset(NC_FIELDS)|{
 'GetCWObjectFromID','GetCWObjectID','Count','Item','OpernType','Suppressed','GetIsToolpathGenerated',
 'IGetAllFeatures','IGetTool','IGetEnumToolpaths','RecordCount','IsMillTool','ToolType','CutDiameter','Protrusion',
 'GetMachiningDepth','GetOverrideMachiningDepth','IGetNCParam','XYFeed'}
READ_INTERFACES=frozenset({'ICWOperation','ICWMillOperation','ICWMillOperation3','ICWFeature',
 'ICWTool','ICWToolpath','ICWDispatchCollection','ICWFaceMillOp','ICWNCParam','ICWNCParam2'})
RUNTIME_NAMES=('sw_cam.py','sw_cam_thread.py','sw_cam_turn_tool.py','sw_cam_generation.py','sw_cam_comtypes.py',
 'sw_cam_rough_firstcut.py','sw_cam_dispatch_guard.py','sw_cam_read_batch_guard.py','sw_cam_route_read_batch.py',
 'sw_cam_mill_qualification.py','sw_cam_mill_inventory.py','sw_cam_mill_route_context.py',
 'sw_cam_document_unit_scope.py','sw_cam_circle_lifecycle_evidence.py','sw_executable_launch.py',
 'sw_cam_mill_feature_context.py','sw_cam_mill_selected_plan_evidence.py','sw_cam_route_batch_qualified_capture.py',
 'sw_operation_guard.py','sw_connect.py','sw_cam_installation.py','sw_cam_events.py','sw_cam_face_interfaces.py')
ALL_OBSERVER_INTERFACES=READ_INTERFACES|{'ICWApp4','ICWDoc3','ICWPartDoc','ICWMachine'}


def _key(path):return str(Path(path).resolve()).casefold()
def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)


def decode(value,kind):
    if kind=='pair':
        require(type(value) in (list,tuple) and len(value)==2,'Exact value/percentage pair required')
        decode(value[0],'float');decode(value[1],'bool')
        return dict(raw=list(value),value=value[0],percentage=value[1],output_order='DOUBLE,VARIANT_BOOL')
    cls={'int':int,'float':float,'bool':bool}[kind]
    require(type(value) is cls,'Strict documented getter type required: '+kind)
    if cls is float:require(math.isfinite(value),'Finite native scalar required')
    return dict(raw=value,python_type=kind)


def read_parameters(raw_operation,raw_feature,*,read,typed,feature_dispatch,report,persist):
    """Documented value/retval getters only; retain every raw result before decoding."""
    face=typed(raw_operation,'ICWFaceMillOp');feat=feature_dispatch(typed(raw_feature,'ICWFeature'))
    out=report.setdefault('face_parameters',{})
    def get(interface,obj,name,kind,*args):
        row={'interface':interface,'member':name,'read_complete':False};out[name]=row;persist()
        value=read(obj,name,*args);row['raw']=list(value) if type(value) is tuple else value;persist()
        row.update(decode(value,kind),read_complete=True);persist()
    for name,kind in list(PROPERTIES.items())+list(SCALARS.items()):get('ICWFaceMillOp',face,name,kind)
    for name in PAIRS:get('ICWFaceMillOp',face,name,'pair')
    for name in FEATURE_PAIRS:get('ICWFaceMillOp',face,name,'pair',feat)
    for name in FEATURE_INTS:get('ICWFaceMillOp',face,name,'int',feat)
    mill=typed(raw_operation,'ICWMillOperation');mill3=typed(raw_operation,'ICWMillOperation3')
    get('ICWMillOperation',mill,'GetMachiningDepth','float',feat)
    get('ICWMillOperation3',mill3,'GetOverrideMachiningDepth','bool',feat)
    raw=read(mill,'IGetNCParam')
    if raw is None or (_is_comtypes_pointer(raw) and not bool(raw)):
        report['nc_parameters']={'available':False,'reason':'native_null_IGetNCParam'};persist();return
    require(_is_comtypes_pointer(raw) and bool(raw),'NC object must be real native pointer or null')
    nc=typed(raw,'ICWNCParam');nc2=typed(raw,'ICWNCParam2')
    nc_out=report.setdefault('nc_parameters',dict(available=True,fields={}))['fields']
    for name,kind in dict(NC_FIELDS,XYFeed='float').items():
        iface='ICWNCParam2' if name=='XYFeed' else 'ICWNCParam';obj=nc2 if name=='XYFeed' else nc
        row={'interface':iface,'member':name,'read_complete':False};nc_out[name]=row;persist()
        value=read(obj,name);row['raw']=value;persist();row.update(decode(value,kind),read_complete=True);persist()


def load_recovered_face_checkpoint(path,digest,*,failed_observation_receipt_path,failed_observation_receipt_sha256,process_id,expected_document_path,expected_source_sha256,
        expected_operation_native_id,expected_feature_native_id):
    """Verify the completed recovery once offline, then bind a narrow read scope."""
    from scripts import sw_cam_raw_mill_face_operation_append_recovery as recovery
    loaded=recovery.load_completed_face_operation_recovery(path,digest,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        expected_feature_native_id=expected_feature_native_id,expected_operation_native_id=expected_operation_native_id)
    require(loaded.get('failure_resolved') is True and loaded.get('full_creator_proof_verified') is True,
        'Completed recovered insertion required')
    checkpoint=loaded['checkpoint']
    from scripts import sw_cam
    runtime=Path(sw_cam.__file__).resolve().parent
    pins=[_self_pin(),loaded['recovery_pin'],loaded['failed_marker_pin'],_pin(recovery.__file__)]+[_pin(runtime/name) for name in RUNTIME_NAMES]
    generated=[v for v in loaded['pins'] if Path(v['path']).name.startswith('_FE488661_') and Path(v['path']).suffix=='.py']
    ownership_pins=[v for v in loaded['pins'] if Path(v['path']).name.endswith('_start_receipt.json')]
    require(len(generated)==1 and len(ownership_pins)==1,'Exact qualified generated library and owned startup receipt required')
    pins=canonical_evidence_pins(pins,generated,ownership_pins);require(len(pins)<=64,'Unchanged read-scope pin cap required')
    for value in pins:require(_file_hash(value['path'])==value['sha256'],'Read-scope dependency changed')
    failed,failed_pin=read_pin(failed_observation_receipt_path,failed_observation_receipt_sha256)
    require(failed.get('scope')=='READ_ONLY_NEW_FACE_PARAMETERS_V1' and failed.get('status')=='error' and failed.get('phase')=='finished'
      and failed.get('failed_phase')=='selected_parameters' and failed.get('read_only') is True and failed.get('read_complete') is False
      and failed.get('mutation_attempted') is False and failed.get('model_saved') is False and failed.get('GTP_attempted') is False,
      'Exact completed read-only interface-resolution failure required')
    require(failed['process_id']==process_id and _key(failed['source_path'])==_key(expected_document_path)
      and failed['source_sha256']==expected_source_sha256 and failed['recovery_pin']['sha256']==digest
      and _key(failed['recovery_pin']['path'])==_key(path) and not failed.get('face_parameters'),'Earlier observation identity or phase differs')
    require(failed['issue']['type']=='ValueError' and failed['issue']['locations'][-1]==dict(file='sw_cam_comtypes.py',function='_interface_class',line=109),
      'Unexpected prior observation failure')
    clean_events(failed)
    old_pin=next(v for v in failed['read_scope_pins'] if Path(v['path']).name=='sw_cam_raw_mill_face_observation.py')
    require(old_pin['sha256']=='f9cb4aeded08fc7c47b2ed6d77af7320742184e08efa7709091452f9fcc8a7bc'
      and _file_hash(old_pin['path'])==old_pin['sha256'],'Original observer implementation must remain immutable')
    expected=loaded['expected_operation']
    require(all(failed['fresh_target_binding'][key]==expected[key] for key in failed['fresh_target_binding'])
      and failed['units_before']==checkpoint['payload']['finish']['unit_record'],'Prior read-only binding or units differ')
    return dict(history_pins=[failed_pin],previous_read_failure_pin=failed_pin,generated_pin=generated[0],
        recovery_pin=loaded['recovery_pin'],original_creator_pin=loaded['failed_pin'],
        creator_marker_pin=loaded['failed_marker_pin'],parent_pin=loaded['recovery_pin'],checkpoint_sha256=loaded['checkpoint_sha256'],
        reused_checkpoint=deepcopy(checkpoint),document=deepcopy(checkpoint['state']['document']),
        expected_operation=deepcopy(loaded['expected_operation']),ownership=deepcopy(loaded['ownership']),pins=pins,
        units=deepcopy(checkpoint['payload']['finish']['unit_record']),full_creator_proof_verified=True,
        original_failure_resolved=True,current_protected_route_revalidated=False)


class FaceReadBatch(ScopedCamRouteReadBatch):
    def read(self,obj,name,*args):
        try:
            require(name in READ_MEMBERS,'Getter outside single-FACE observation scope')
            for value in args:
                require(type(value) in (bool,int,float,str,bytes) or id(value) in self._known_objects,'Argument outside retained native graph')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(name in READ_INTERFACES,'Interface outside single-FACE scope')
            return self._observe_read(obj,'qi',lambda:query_face_interface(obj,name,self.typelib_path,generated_pin=self.generated_pin)
              if name in FACE_IIDS else _typed(obj,name,self.typelib_path))
        except BaseException:self._invalid=True;self._completed=False;raise


def inspect_face_parameters(sw,clsid,typelib_path,*,loaded,process_id,expected_document_path,expected_source_sha256,
        expected_operation_native_id,expected_feature_native_id,receipt_path):
    from scripts.sw_cam_events import CamMessageSession
    receipt=Path(receipt_path);protected={_key(p['path']) for p in loaded['pins']+loaded['history_pins']}|{_key(expected_document_path)}
    require(loaded.get('full_creator_proof_verified') is True and receipt.is_absolute() and receipt.parent.is_dir()
        and receipt.suffix.casefold()=='.json' and not receipt.exists() and not receipt.is_symlink() and _key(receipt) not in protected,
        'Verified terminal context and fresh read output required')
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,
        source_path=expected_document_path,source_sha256=expected_source_sha256,recovery_pin=loaded['recovery_pin'],original_creator_pin=loaded['original_creator_pin'],
        reused_checkpoint_sha256=loaded['checkpoint_sha256'],reused_checkpoint=deepcopy(loaded['reused_checkpoint']),
        read_scope_pins=deepcopy(loaded['pins']),history_pins=deepcopy(loaded['history_pins']),interface_compatibility_audit=deepcopy(loaded['interface_audit']),read_only=True,mutation_attempted=False,model_saved=False,
        GTP_attempted=False,full_route_revalidated=False,tool_or_holder_geometry_revalidated=False,
        recipe_qualified=False,may_mutate=False,may_generate=False,read_complete=False,receipt_path=str(receipt))
    created=False;session=batch=None
    def persist():
        if created:_write_receipt(receipt,report)
    def files():
        for pin in loaded['pins']+loaded['history_pins']:require(_file_hash(pin['path'])==pin['sha256'],'Readonly scope dependency changed')
    def owned():
        got=_process_identity(process_id);want=loaded['ownership']
        require(got.get('process_id')==process_id and got.get('alive') is True and got.get('create_time')==want['create_time']
            and _same_path(got.get('executable',''),want['executable']),'Owned process exited or reused')
    def identity():
        got_pid=_member(sw,'GetProcessID');require(type(got_pid) is int and got_pid==process_id,'Exact owned PID required')
        owned();doc=raw_part_identity(sw)
        require(doc==loaded['document'] and _file_hash(expected_document_path)==expected_source_sha256,'Readonly current document/source changed')
        return doc
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),
            'CAM events require stop')
    def guard():
        return ScopedCamDispatchGuard(sw,typelib_path,process_id=process_id,expected_document=identity(),
            source_sha256=expected_source_sha256,evidence_pins=loaded['pins'],verify_evidence=files,
            verify_owned_process=owned,check_events=events)
    def units(app):
        with guard() as g:return read_document_cam_unit_scope(g.read(sw,'ActiveDoc'),app,sw_read=g.read,cam_read=g.read)
    try:
        _write_receipt(receipt,report,create=True);created=True;files();report['document_before']=identity();persist()
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path);identity();session=CamMessageSession(app,typelib_path)
        with session:
            report['phase']='resolve_selected';persist()
            with guard() as g:
                active=g.read(app,'IGetActiveDoc');doc=g.typed(active,'ICWDoc3');require(g.read(doc,'GetDocType')==1,'CAM part required')
                machine=g.typed(g.read(g.typed(active,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
                require(g.read(machine,'MachType')==1,'Current MILL machine required')
                found=g.read(doc,'GetCWObjectFromID',3,expected_operation_native_id)
                require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact new operation lookup failed')
                operation=g.typed(found[0],'ICWOperation');require(_object_id(doc,operation,g.read)==expected_operation_native_id,'New operation ID differs')
            before_units=units(app);report['units_before']=before_units;persist()
            require(before_units==loaded['units'] and before_units['metric_document_scope_observed'] is True,'Metric document scope changed')
            native=dict(doc=doc,machine=machine,operations={expected_operation_native_id:operation})
            batch=FaceReadBatch(sw,typelib_path,native_context=native,reference_state={'operations':[loaded['expected_operation']]},
                process_id=process_id,expected_document=identity(),source_sha256=expected_source_sha256,evidence_pins=loaded['pins'],
                verify_evidence=files,verify_owned_process=owned,check_events=events,max_native_calls=150)
            batch.generated_pin=loaded['generated_pin']
            with batch:
                report['phase']='selected_parameters';persist();mill=batch.typed(operation,'ICWMillOperation')
                binding=dict(native_id=_object_id(doc,operation,batch.read),base_operation_type=batch.read(operation,'OpernType'),
                    mill_operation_type=batch.read(mill,'OpernType'),suppressed=batch.read(operation,'Suppressed'),
                    toolpath_generated=batch.read(operation,'GetIsToolpathGenerated'))
                links=[_object_id(doc,v,batch.read) for v in _items(batch.read(operation,'IGetAllFeatures'),batch.typed,batch.read,2)]
                binding['linked_feature_ids']=links;rawtool=batch.read(operation,'IGetTool')
                if rawtool is None or (_is_comtypes_pointer(rawtool) and not bool(rawtool)):binding['assigned_tool']=None
                else:
                    require(_is_comtypes_pointer(rawtool) and bool(rawtool),'Assigned tool must be native COM or null')
                    binding['assigned_tool'],_=read_generic_tool(operation,doc,batch.read,batch.typed)
                report['fresh_target_binding']=deepcopy(binding);persist()
                expected=loaded['expected_operation']
                require(all(binding[k]==expected[k] and type(binding[k]) is type(expected[k]) for k in binding),'Selected operation binding changed')
                found=batch.read(doc,'GetCWObjectFromID',1,expected_feature_native_id)
                require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact FACE feature lookup failed')
                feat=batch.typed(found[0],'ICWFeature');require(_object_id(doc,feat,batch.read)==expected_feature_native_id,'Selected FACE ID differs')
                read_parameters(operation,feat,read=batch.read,typed=batch.typed,feature_dispatch=batch.feature_dispatch,
                    report=report,persist=persist)
                require(_object_id(doc,operation,batch.read)==expected_operation_native_id and _object_id(doc,feat,batch.read)==expected_feature_native_id,
                    'Retained selected identities changed')
            batch.require_complete();after_units=units(app);report['units_after']=after_units;persist()
            require(after_units==before_units,'Units changed during read')
            report['document_after']=identity();persist()
        events(False);files();require(identity()==report['document_before'],'Document changed during read cleanup')
        report.update(status='observed',phase='finished',read_complete=True,atomic_snapshot=False,
            reused_fields=['complete21/7route','protected247/248payload','CAD/stock/featuregeometry','fulltool/holderprofiles'],
            fresh_fields=['ownedPID/source/document','selectedop/feature/toolbinding','units','FACEparameters','basicNCvalues'],
            excluded_getters=['GetClrPlanePrms','GetRpdPlnPrms'],reason='READONLY_SELECTED_PARAMETERS_NOT_A_MUTATION_OR_ROUTE_AUTHORIZATION')
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),read_complete=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if batch is not None:report['read_batch']=batch.summary()
        try:persist()
        except Exception as exc:report.update(status='error',read_complete=False,receipt_write_error=_error(exc))
    return report


PARAMS={'failed_observation_receipt_path','failed_observation_receipt_sha256','recovery_receipt_path','recovery_receipt_sha256','process_id','expected_document_path','expected_source_sha256',
 'expected_operation_native_id','expected_feature_native_id','receipt_path','addin_clsid','module_sha256'}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='inspect_new_face_parameters','Only selected readonly FACE observation supported')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact readonly fields required')
    for k in ('process_id','expected_operation_native_id','expected_feature_native_id'):integer(p[k],k,1)
    for k,v in p.items():
        if k.endswith('sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact SHA256 required')
        if k.endswith('path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'],'Exact observer implementation required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact CLSID required')
    return dict(p)


def dispatch_request(request):
    p=validate_request(request)
    loaded=load_recovered_face_checkpoint(p.pop('recovery_receipt_path'),p.pop('recovery_receipt_sha256'),
        failed_observation_receipt_path=p.pop('failed_observation_receipt_path'),failed_observation_receipt_sha256=p.pop('failed_observation_receipt_sha256'),**{k:p[k] for k in
        ('process_id','expected_document_path','expected_source_sha256','expected_operation_native_id','expected_feature_native_id')})
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
        loaded['interface_audit']=audit_interfaces(ALL_OBSERVER_INTERFACES,typelib,generated_pin=loaded['generated_pin'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return inspect_face_parameters(sw,registration['clsid'],typelib,loaded=loaded,**p)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    args=parser.parse_args(argv);result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:result.get(k) for k in ('scope','status','phase','read_complete','issue','receipt_path')},ensure_ascii=False))
    return 0 if result.get('read_complete') is True else 1


if __name__=='__main__':raise SystemExit(main())
