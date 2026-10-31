"""Owned-pointer clearance/rapid reads for one saved Contour and its setup.

The generated typed COM vtable getters have pointer parameters without direction
flags. Their exact raw wrappers receive locally owned initialized ctypes values;
strict S_OK and both populated outputs are required. No pointer arithmetic,
interface fabrication, IDispatch invocation, setters, save, or generation.
"""
from copy import deepcopy
from ctypes import byref, c_double, c_long
from pathlib import Path
from time import monotonic
import json
import math
from scripts import sw_cam_chamfer_nc_planes as nc
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_face_interfaces import _verify_generated_class
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_rough_firstcut import require

common,group=nc.common,nc.group
SCOPE='SAVED_CONTOUR_CLEARANCE_POINTER_READ_V1'
SETUP_IID='{CE864DCA-ED48-41B7-B38D-3E56D63B372F}'
POINTER_FIELDS={'GetClrPlanePrms':11,'GetRpdPlnPrms':9}
SETUP_FIELDS={'ClearancePlaneType':('long',14),'ClearancePlaneDistance':('double',15),
              'RapidPlaneType':('long',12),'RapidPlaneDistance':('double',13)}
USE_SETUP=('GetClrPlaneUseSetupStatus','GetRpdPlaneUseSetupStatus')
GETTERS=(nc.GETTERS-frozenset(nc.leads.LEAD_FIELDS)-{v[1] for v in nc.FIELDS}
         -{'IGetLeadin','IGetLeadout'}) | set(SETUP_FIELDS) | set(USE_SETUP) | {
    'IGetMachine','MachType','IGetEnumOpSetups','IGetEnumOperations'}
INTERFACES=(nc.INTERFACES-{'ICWFinishMillOp','ICWLeadInOut','ICWNCParam3','ICWNCParam4'}) | {
    'ICWPartDoc','ICWMachine','ICWBaseOpSetup','ICWOpSetup3'}
PARAMS=nc.PARAMS|{'nc_observation_path','nc_observation_sha256'}
SENTINEL_LONG=-(2**31)
MAX_CALLS=250


def interface_class(name,typelib_path,generated_pin):
    from scripts.sw_cam_comtypes import _load_type_library,_interface_class,_INTERFACES
    require(name in INTERFACES|{'ICWDoc3'},'Exact clearance reader interface required')
    if name=='ICWOpSetup3':
        cls=getattr(_load_type_library(str(typelib_path)),name);iid=SETUP_IID
    else:
        cls=_interface_class(name,str(typelib_path));iid=_INTERFACES[name]
    return _verify_generated_class(cls,iid,generated_pin)


def audit_interfaces(typelib_path,generated_pin):
    from ctypes import HRESULT,POINTER
    from ctypes.wintypes import VARIANT_BOOL
    classes={n:interface_class(n,typelib_path,generated_pin) for n in sorted(INTERFACES|{'ICWDoc3'})}
    rows=[]
    for name,dispid in POINTER_FIELDS.items():
        cls=classes['ICWNCParam'];found=[v for v in cls._methods_ if v.name==name]
        require(len(found)==1,'One exact pointer getter declaration required')
        spec=found[0];raw='_ICWNCParam__com_'+name
        require(spec.restype is HRESULT and spec.argtypes==(POINTER(c_double),POINTER(c_long))
            and tuple(v[0] for v in spec.paramflags)==(0,0) and int(spec.idlflags[0])==dispid
            and callable(getattr(cls,raw,None)),'Exact generated raw pointer getter ABI required')
        rows.append(dict(interface='ICWNCParam',member=name,raw_wrapper=raw,dispid=dispid,
                         paramflags=[0,0],storage=['DOUBLE*','LONG*']))
    for name,(kind,dispid) in SETUP_FIELDS.items():
        spec=next(v for v in classes['ICWOpSetup3']._methods_ if v.name=='_get_'+name)
        require(spec.restype is HRESULT and spec.argtypes==(POINTER(c_long if kind=='long' else c_double),)
            and tuple(v[0] for v in spec.paramflags)==(10,) and int(spec.idlflags[0])==dispid
            and 'propget' in spec.idlflags,'Exact setup scalar getter ABI required')
        rows.append(dict(interface='ICWOpSetup3',member=name,dispid=dispid,paramflags=[10]))
    for name,dispid in zip(USE_SETUP,(13,15)):
        spec=next(v for v in classes['ICWNCParam']._methods_ if v.name==name)
        require(spec.restype is HRESULT and spec.argtypes==(POINTER(VARIANT_BOOL),)
            and tuple(v[0] for v in spec.paramflags)==(10,) and int(spec.idlflags[0])==dispid,
            'Exact setup-use flag ABI required')
    return dict(all_resolved=True,type_library_pin=common._pin(typelib_path),
        generated_pin=deepcopy(generated_pin),members=rows,application_connections=0,
        native_getters_called=0,runtime_pointer_support_qualified=False)


def pointer_value(obj,name,diagnostic):
    """Invoke one reviewed generated raw wrapper with owned output storage."""
    require(name in POINTER_FIELDS and type(diagnostic) is dict and not diagnostic,
            'One fixed pointer getter and fresh diagnostic required')
    distance=c_double(float('nan'));basis=c_long(SENTINEL_LONG)
    diagnostic.update(member=name,attempted=True,returned=False,outputs_validated=False,
                      storage_owned=True,automatic_retry=False)
    value=getattr(obj,'_ICWNCParam__com_'+name)(byref(distance),byref(basis))
    diagnostic.update(returned=True,hresult_type=type(value).__name__)
    require(type(value) is int and value==0,'Strict pointer-getter S_OK required')
    diagnostic['hresult']=value
    require(math.isfinite(distance.value) and basis.value!=SENTINEL_LONG,
            'Both initialized pointer outputs must be populated')
    result=dict(distance_native=distance.value,basis_raw=basis.value,hresult=value,
                unit_binding_verified=False,enum_binding_verified=False,conversion_performed=False)
    diagnostic.update(outputs_validated=True,values=deepcopy(result))
    return result


def read_plane_parameters(operation,setup,*,read,typed,pointer_read,diagnostic,persist=lambda:None):
    """Reusable callbacks over already bound operation/setup; no target discovery."""
    require(type(diagnostic) is dict and not diagnostic,'Fresh plane-parameter diagnostic required')
    diagnostic.update(complete=False,pointer_fields={},partial={})
    result=diagnostic['partial']
    mill=typed(operation,'ICWMillOperation')
    owner=typed(read(mill,'IGetNCParam'),'ICWNCParam')
    result['setup_use']={name:nc.scalar('bool',read(owner,name)) for name in USE_SETUP}
    result['local_planes']={}
    for name in POINTER_FIELDS:
        item={};diagnostic['pointer_fields'][name]=item;persist()
        result['local_planes'][name]=pointer_read(owner,name,item);persist()
    setup3=typed(setup,'ICWOpSetup3')
    result['setup_planes']={name:nc.scalar(kind,read(setup3,name)) for name,(kind,_) in SETUP_FIELDS.items()}
    result['effective_selection']={
        'clearance':'setup' if result['setup_use']['GetClrPlaneUseSetupStatus'] else 'operation',
        'rapid':'setup' if result['setup_use']['GetRpdPlaneUseSetupStatus'] else 'operation'}
    result['effective_world_plane_computed']=False
    diagnostic['complete']=True;persist()
    return deepcopy(result)


class ReadBatch(nc.PlaneReadBatch):
    def read(self,obj,name,*args):
        try:
            require(name in GETTERS,'Getter outside clearance/target/setup scope')
            for value in args:
                require(type(value) is int or id(value) in self._known_objects,'Read argument outside retained graph')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            cls=interface_class(name,self.typelib_path,self.generated_pin)
            def query():
                from scripts.sw_cam_comtypes import _is_comtypes_pointer
                require(_is_comtypes_pointer(obj) and bool(obj),'Native retained pointer required')
                value=obj.QueryInterface(cls)
                require(_is_comtypes_pointer(value) and bool(value) and isinstance(value,cls),'Exact typed result required')
                return value
            return self._observe_read(obj,'qi',query)
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def plane(self,obj,name,diagnostic):
        try:
            require(name in POINTER_FIELDS,'Only reviewed raw pointer getters allowed')
            return self._observe_read(obj,'getter',lambda:pointer_value(obj,name,diagnostic))
        except BaseException:
            self._invalid=True;self._completed=False;raise


def read_setup_binding(doc,loaded,*,read,typed):
    part=typed(doc,'ICWPartDoc');machine=typed(read(part,'IGetMachine'),'ICWMachine')
    require(read(machine,'MachType')==1,'Saved MILL machine required')
    setups=_items(read(machine,'IGetEnumOpSetups'),typed,read,8)
    ids=[_object_id(doc,s,read) for s in setups]
    expected=loaded['state']['operation_setups']
    require(ids==[v['native_id'] for v in expected],'Exact saved setup identities and order required')
    target=next(v for v in loaded['state']['operations'] if v['native_id']==loaded['configured_contour']['native_id'])
    raw=setups[target['setup_index']]
    require(ids[target['setup_index']]==target['setup_native_id'],'Target setup identity changed')
    base=typed(raw,'ICWBaseOpSetup')
    ops=_items(read(base,'IGetEnumOperations'),typed,read,32)
    actual=[_object_id(doc,v,read) for v in ops]
    wanted=[v['native_id'] for v in loaded['state']['operations'] if v['setup_native_id']==target['setup_native_id']]
    require(actual==wanted,'Selected setup membership or operation order changed')
    return dict(setup_native_id=target['setup_native_id'],setup_ids=ids,operation_ids=actual),raw


class NativeBackend(nc.NativeBackend):
    def observe(self):
        r=self.report;handles={}
        def binding():
            self.events();require(_member(self.doc,'GetDocType')==1,'Retained CAM part changed')
            for name,ident in (('operation',r['operation_native_id']),('feature',r['feature_native_id']),
                               ('tool',r['tool_native_id']),('setup',r['setup_native_id'])):
                if name in handles:require(_object_id(self.doc,handles[name],_member)==ident,'Retained identity changed')
            self.events()
        b=ReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),
            source_sha256=self.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,
            retained_objects=(self.doc,),verify_retained_binding=binding,max_native_calls=MAX_CALLS)
        try:
            with b:
                r['before_target'],h=nc.read_target(self.doc,self.loaded,read=b.read,typed=b.typed);handles.update(h)
                r['before_setup'],setup=read_setup_binding(self.doc,self.loaded,read=b.read,typed=b.typed)
                handles['setup']=setup
                r['phase']='pointer_fields';self.persist()
                r['plane_diagnostic']={}
                r.update(read_plane_parameters(handles['operation'],setup,read=b.read,typed=b.typed,
                    pointer_read=b.plane,diagnostic=r['plane_diagnostic'],persist=self.persist))
                require(r['setup_use']['GetClrPlaneUseSetupStatus']==
                    self.loaded['nc_observation']['planes']['values']['GetClrPlaneUseSetupStatus'],
                    'Previously observed clearance setup-use flag changed')
                r['phase']='after_binding';self.persist()
                r['after_setup'],_=read_setup_binding(self.doc,self.loaded,read=b.read,typed=b.typed)
                r['after_target'],_=nc.read_target(self.doc,self.loaded,read=b.read,typed=b.typed)
                require(group.exact(r['before_setup'],r['after_setup']) and group.exact(r['before_target'],r['after_target']),
                        'Setup or target binding changed during pointer read')
            b.require_complete()
        finally:r['read_batch']=b.summary();self.persist()


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and
        request['action']=='read_clearance_planes','Exact clearance reader action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact pointer reader fields required')
    # Reuse the scalar reader shape validator with its own pinned module value.
    base={k:v for k,v in p.items() if k in nc.PARAMS};base['module_sha256']=_file_hash(nc.__file__)
    nc.validate_request(dict(action='read_nc_planes_and_leads',params=base))
    require(p['module_sha256']==_file_hash(__file__) and type(p['nc_observation_path']) is str
        and Path(p['nc_observation_path']).is_absolute() and type(p['nc_observation_sha256']) is str
        and nc.re.fullmatch('[0-9a-f]{64}',p['nc_observation_sha256']),'Exact sibling module and NC receipt pins required')
    return deepcopy(p)


def load_inputs(p):
    identity={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    loaded=nc.load_checkpoint(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**identity)
    obs,pin=read_pin(p['nc_observation_path'],p['nc_observation_sha256'])
    require(obs.get('scope')==nc.SCOPE and obs.get('status')=='observed' and obs.get('phase')=='finished'
        and obs.get('readback_verified') is True and obs.get('phase_proofs_verified_after_read') is True
        and obs.get('read_only') is True and not any(obs.get(k) for k in ('mutation_attempted','save_attempted',
            'model_saved','GTP_attempted','export_attempted','issue','cleanup_issue','receipt_write_error')),
        'Completed unchanged scalar NC observation required')
    target=nc.target_projection(loaded)
    require(obs['process_id']==p['process_id'] and obs['expected_source_sha256']==p['expected_source_sha256']
        and common._key(obs['expected_document_path'])==common._key(p['expected_document_path'])
        and obs['before_target']==obs['after_target']==target
        and obs['before_document']==obs['after_document']==loaded['state']['document']
        and obs['checkpoint_pin']['sha256']==loaded['parent_pin']['sha256'],
        'Exact NC observation checkpoint/target/source differs')
    clean_events(obs)
    live=common._merge(loaded['pins'],[common._pin(__file__)])
    offline=common._merge(loaded['offline_export_proof_pins'],[pin])
    require(len(live)<=64,'Bounded pointer reader closure required')
    common._check(live);common._check(offline)
    return dict(loaded,pins=live,offline_export_proof_pins=offline,nc_observation=obs,nc_observation_pin=pin)


def run(sw,clsid,typelib,*,loaded,args,audit):
    receipt=common._local_receipt(args['receipt_path']);target=loaded['configured_contour']
    r=dict(schema_version=1,scope=SCOPE,status='reading',phase='preflight',read_only=True,
        process_id=args['process_id'],process_ownership=deepcopy(loaded['ownership']),
        expected_document_path=args['expected_document_path'],expected_source_sha256=args['expected_source_sha256'],
        checkpoint_pin=loaded['parent_pin'],nc_observation_pin=loaded['nc_observation_pin'],
        operation_native_id=target['native_id'],feature_native_id=target['feature_native_id'],
        tool_native_id=target['tool_native_id'],setup_native_id=loaded['state']['operations'][-1]['setup_native_id'],
        interface_audit=audit,evidence_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],
        readback_verified=False,mutation_attempted=False,save_attempted=False,model_saved=False,
        GTP_attempted=False,export_attempted=False,full_CAD_stock_capture=False,leads_reread=False,
        numeric_units_verified=False,enum_binding_verified=False,production_qualified=False,automatic_retry=False)
    started=monotonic();backend=None
    def persist():r['elapsed_seconds']=monotonic()-started;_write_receipt(receipt,r)
    _write_receipt(receipt,r,create=True)
    try:
        backend=NativeBackend(loaded,args,sw,clsid,typelib,r,persist)
        backend.start();r['before_document']=backend.ctx.identity();persist()
        backend.observe();backend.finish();r['after_document']=backend.ctx.identity()
        require(r['before_document']==r['after_document']==loaded['state']['document'],'Document or dirty state changed')
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins'])
        r.update(status='observed',phase='finished',readback_verified=True,phase_proofs_verified_after_read=True)
    except Exception as exc:
        r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        if backend:
            try:backend.close()
            except Exception as exc:r.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    registration=common.discover_export_registration(loaded,p['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_interfaces(typelib,loaded['generated_pin'])
    loaded['pins']=common._merge(loaded['pins'],[audit['type_library_pin']])
    require(len(loaded['pins'])<=64,'TLB-pinned closure exceeds bound')
    receipt=common._local_receipt(p['receipt_path'])
    protected=[p['expected_document_path']]+[v['path'] for v in loaded['pins']+loaded['offline_export_proof_pins']]
    require(common._key(receipt) not in {common._key(v) for v in protected},'Receipt aliases protected proof')
    if validate_only:return dict(status='validated_offline',native_called=False,interface_audit=audit,
        selected=nc.target_projection(loaded),live_pin_count=len(loaded['pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return run(sw,registration['clsid'],typelib,loaded=loaded,args=p,audit=audit)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true');opts=parser.parse_args(argv)
    result=dispatch_request(json.loads(Path(opts.request).read_text(encoding='utf-8-sig')),validate_only=opts.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
