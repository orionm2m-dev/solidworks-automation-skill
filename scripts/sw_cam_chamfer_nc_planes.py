"""Read four NC-plane scalars and existing lead definitions of one saved Contour.

No setters, generation, export, save, stock read, or CAD traversal. The exact
completed checkpoint owns the target; native target binding is read before and
after the single bounded field pass. Raw values do not qualify machining.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import json
import math
import re
from scripts import sw_cam_chamfer_exports as parent
from scripts import sw_cam_finish_lead_observation as leads
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_face_interfaces import _verify_generated_class
from scripts.sw_cam_rough_firstcut import require

common, group = parent.common, parent.group
SCOPE = 'SAVED_CONTOUR_NC_PLANES_AND_LEADS_READ_V1'
EXTENSION_IIDS = {
    'ICWNCParam3':'{32880B43-2E9A-4143-9C71-8053A1336CA5}',
    'ICWNCParam4':'{3DC6FB05-9C9F-42A4-8532-F1B7892CF3AA}',
    'ICWLeadInOut':leads.LEAD_IID,
}
FIELDS = (
    ('ICWNCParam3','FeedPlaneType','long',24,'property'),
    ('ICWNCParam3','FeedPlaneDistance','double',25,'property'),
    ('ICWNCParam4','GetUseCurrentMachiningDepthForFeedPlane','bool',41,'method'),
    ('ICWNCParam','GetClrPlaneUseSetupStatus','bool',13,'method'),
)
GETTERS = frozenset(v[1] for v in FIELDS) | frozenset(leads.LEAD_FIELDS) | {
    'GetCWObjectFromID','GetCWObjectID','GetDocType','Count','Item',
    'IGetAllFeatures','OpernType','Suppressed','GetIsToolpathGenerated',
    'IGetEnumToolpaths','RecordCount','IGetTool','IsMillTool','ToolType',
    'CutDiameter','Protrusion','IGetNCParam','IGetLeadin','IGetLeadout',
}
INTERFACES = frozenset({'ICWOperation','ICWMillOperation','ICWFeature','ICWTool',
    'ICWDispatchCollection','ICWToolpath','ICWFinishMillOp','ICWNCParam'}) | frozenset(EXTENSION_IIDS)
TARGET_KEYS = ('native_id','linked_feature_ids','mill_operation_type','base_operation_type',
               'suppressed','toolpath_generated','toolpath_record_counts','assigned_tool')
PARAMS = common.COMMON - {'acknowledge_machine_scope'}
MAX_CALLS = 180


def interface_class(name, typelib_path, generated_pin):
    from scripts.sw_cam_comtypes import _load_type_library, _interface_class, _INTERFACES
    if name in EXTENSION_IIDS:
        cls = getattr(_load_type_library(str(typelib_path)), name)
        iid = EXTENSION_IIDS[name]
    else:
        require(name in INTERFACES | {'ICWDoc3'}, 'Interface outside exact reader scope')
        cls = _interface_class(name, str(typelib_path)); iid = _INTERFACES[name]
    return _verify_generated_class(cls, iid, generated_pin)


def query_interface(obj, name, typelib_path, generated_pin):
    from scripts.sw_cam_comtypes import _is_comtypes_pointer
    cls = interface_class(name, typelib_path, generated_pin)
    require(_is_comtypes_pointer(obj) and bool(obj), 'Existing native interface required')
    value = obj.QueryInterface(cls)
    require(_is_comtypes_pointer(value) and bool(value) and isinstance(value, cls),
            'Exact non-null native interface required')
    return value


def audit_interfaces(typelib_path, generated_pin):
    """Installed TLB and generated resolver audit; no application connection."""
    from ctypes import HRESULT, POINTER, c_double, c_long
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    classes = {name:interface_class(name,typelib_path,generated_pin)
               for name in sorted(INTERFACES | {'ICWDoc3'})}
    scalar = {'long':c_long,'double':c_double,'bool':VARIANT_BOOL}
    specs = [('ICWMillOperation','IGetNCParam','method',7,(POINTER(POINTER(IDispatch)),),(10,))]
    specs += [(i,n,k,dispid,(POINTER(scalar[t]),),(10,)) for i,n,t,dispid,k in FIELDS]
    # Existing lead reader is reused. Assert every exact getter's declared output
    # shape and feature-pointer input before its first call in this adapter.
    specs += [('ICWFinishMillOp',n,'method',None,
               (POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10))
              for n in ('IGetLeadin','IGetLeadout')]
    for n,kind in leads.LEAD_FIELDS.items():
        types = ((POINTER(c_long),) if kind=='int' else
                 (POINTER(VARIANT_BOOL),) if kind=='bool' else
                 (POINTER(c_double),) if kind=='number' else
                 (POINTER(c_double),POINTER(VARIANT_BOOL),POINTER(c_double))
                    if kind=='number_bool_number' else (POINTER(c_double),POINTER(VARIANT_BOOL)))
        prop = n in ('LeadType','LeadAngle','ArcAngle','SidePassType','CutDepthType','StartAngle')
        flags = (10,) if prop else (2,)*len(types)
        specs.append(('ICWLeadInOut',n,'property' if prop else 'method',None,types,flags))
    rows = []
    for interface,name,kind,dispid,types,flags in specs:
        declared_name = '_get_'+name if kind=='property' else name
        found = [m for m in classes[interface]._methods_ if m.name==declared_name]
        require(len(found)==1, 'One exact native getter declaration required: '+name)
        m=found[0]
        require(m.restype is HRESULT and m.argtypes==types
                and tuple(v[0] for v in m.paramflags)==flags
                and ('propget' in m.idlflags)==(kind=='property')
                and (dispid is None or int(m.idlflags[0])==dispid),
                'Native getter ABI differs: '+interface+'.'+name)
        rows.append(dict(interface=interface,member=name,dispid=int(m.idlflags[0]),
                         kind=kind,paramflags=list(flags)))
    return dict(all_resolved=True,application_connections=0,native_getters_called=0,
        runtime_support_qualified=False,type_library_pin=common._pin(typelib_path),
        generated_pin=deepcopy(generated_pin),members=rows,
        interface_iids={n:str(c._iid_).upper() for n,c in classes.items()})


def scalar(kind, value):
    require((type(value) is int and -(2**31)<=value<2**31) if kind=='long' else
            (type(value) is float and math.isfinite(value)) if kind=='double' else
            type(value) is bool, 'Strict native NC scalar type differs')
    return value


def read_planes(operation, *, read, typed, diagnostic):
    require(type(diagnostic) is dict and not diagnostic, 'Fresh plane diagnostic required')
    diagnostic.update(complete=False,fields=[])
    mill=typed(operation,'ICWMillOperation')
    raw=read(mill,'IGetNCParam')
    require(raw is not None and bool(raw), 'Non-null operation-owned NC parameter object required')
    values={}; interfaces={}
    for interface,name,kind,_,_ in FIELDS:
        if interface not in interfaces: interfaces[interface]=typed(raw,interface)
        row=dict(member=name,attempted=True,returned=False,validated=False)
        diagnostic['fields'].append(row)
        value=read(interfaces[interface],name)
        row.update(returned=True,return_type=type(value).__name__)
        values[name]=scalar(kind,value);row.update(validated=True,value=value)
    diagnostic['complete']=True
    return dict(values=values,numeric_units_verified=False,enum_binding_verified=False,
        conversion_performed=False,pointer_plane_getters_called=False,
        model_updated=False,production_qualified=False)


def target_projection(loaded):
    parent.operation_contract(loaded)
    row=next(r for r in loaded['state']['operations']
             if r['native_id']==loaded['configured_contour']['native_id'])
    return {k:deepcopy(row[k]) for k in TARGET_KEYS}


def read_target(doc, loaded, *, read, typed):
    expected=target_projection(loaded)
    oid=expected['native_id']; fid=expected['linked_feature_ids'][0]
    def lookup(kind, ident, interface):
        found=read(doc,'GetCWObjectFromID',kind,ident)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,
                'Exact native target lookup required')
        value=typed(found[0],interface)
        require(_object_id(doc,value,read)==ident, 'Native target identity changed')
        return value,found[0]
    op,raw=lookup(3,oid,'ICWOperation')
    feature,feature_raw=lookup(1,fid,'ICWFeature')
    mill=typed(raw,'ICWMillOperation')
    links=[_object_id(doc,f,read) for f in _items(read(op,'IGetAllFeatures'),typed,read,2)]
    tool,tool_raw=read_generic_tool(raw,doc,read,typed)
    counts=[read(typed(p,'ICWToolpath'),'RecordCount')
            for p in _items(read(op,'IGetEnumToolpaths'),typed,read,2)]
    require(all(type(v) is int and 0<v<=100000 for v in counts), 'Strict generated record counts required')
    result=dict(native_id=oid,linked_feature_ids=links,assigned_tool=tool,
        mill_operation_type=read(mill,'OpernType'),base_operation_type=read(op,'OpernType'),
        suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'),
        toolpath_record_counts=counts)
    require(type(result['mill_operation_type']) is int and type(result['base_operation_type']) is int
            and type(result['suppressed']) is bool and type(result['toolpath_generated']) is bool,
            'Strict target types required')
    require(group.exact(result,expected) and read(feature,'Suppressed') is False,
            'Saved operation, feature, tool, or generated record binding changed')
    return result,dict(operation=raw,feature=feature,feature_dispatch=feature_raw,tool=tool_raw)


class PlaneReadBatch(ScopedCamReadBatch):
    def __init__(self,*args,generated_pin,**kwargs):
        self.generated_pin=generated_pin
        super().__init__(*args,**kwargs)
    def read(self,obj,name,*args):
        try:
            require(name in GETTERS,'Getter outside NC/lead/target read scope')
            for value in args:
                require(type(value) is int or id(value) in self._known_objects,
                        'Read argument is outside retained graph')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(name in INTERFACES,'Interface outside NC/lead/target scope')
            return self._observe_read(obj,'qi',lambda:query_interface(
                obj,name,self.typelib_path,self.generated_pin))
        except BaseException:
            self._invalid=True;self._completed=False;raise


class NativeBackend(group.NativeBackend):
    def start(self):
        super().start()
        with self.ctx.guard() as g:
            self.doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3')
            require(g.read(self.doc,'GetDocType')==1,'Current CAM part required')
    def observe(self):
        handles={};r=self.report
        def binding():
            self.events()
            require(_member(self.doc,'GetDocType')==1,'Retained CAM document type changed')
            target=self.loaded['configured_contour']
            for key,expected in (('operation',target['native_id']),('feature',target['feature_native_id']),
                                 ('tool',target['tool_native_id'])):
                if key in handles:
                    require(_object_id(self.doc,handles[key],_member)==expected,'Retained target changed')
            self.events()
        batch=PlaneReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
            process_id=self.args['process_id'],expected_document=self.ctx.identity(),
            source_sha256=self.args['expected_source_sha256'],evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,check_events=self.events,
            retained_objects=(self.doc,),verify_retained_binding=binding,max_native_calls=MAX_CALLS)
        try:
            with batch:
                r['before_target'],bound=read_target(self.doc,self.loaded,read=batch.read,typed=batch.typed)
                handles.update(bound);r['phase']='plane_and_lead_fields';self.persist()
                r['plane_diagnostic']={}
                r['planes']=read_planes(handles['operation'],read=batch.read,typed=batch.typed,
                                        diagnostic=r['plane_diagnostic'])
                r['leads']=leads.read_lead_details(handles['operation'],handles['feature_dispatch'],
                    read=batch.read,typed=batch.typed,lead_typed=lambda obj:batch.typed(obj,'ICWLeadInOut'))
                r['phase']='after_binding';self.persist()
                r['after_target'],_=read_target(self.doc,self.loaded,read=batch.read,typed=batch.typed)
                require(group.exact(r['before_target'],r['after_target']),'Target changed during reading')
            batch.require_complete()
        finally:
            r['read_batch']=batch.summary();self.persist()


def load_checkpoint(path,sha256,*,typelib_path=None,**identity):
    loaded=parent.load_checkpoint(path,sha256,**identity)
    retired_names={'sw_cam_mill_generic_cl.py','sw_cam_thread_postprocess.py','sw_cam_operation_profile.py'}
    retired=[p for p in loaded['pins'] if Path(p['path']).name in retired_names]
    require({Path(p['path']).name for p in retired}==retired_names,'Exact offline export roles required')
    added=[common._pin(__file__),common._pin(leads.__file__)]
    if typelib_path:added.append(common._pin(typelib_path))
    live=common._merge([p for p in loaded['pins'] if p not in retired],added)
    offline=common._merge(loaded['offline_export_proof_pins'],retired)
    require(len(live)<=64,'Bounded reader dependency limit exceeded')
    common._check(live);common._check(offline)
    return dict(loaded,pins=live,offline_export_proof_pins=offline,nc_phase_retired_pins=retired)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'}
            and request['action']=='read_nc_planes_and_leads','Exact read-only action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact reader fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**32,'Strict positive owned PID required')
    for key,value in p.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True
            and p['acknowledge_disposable_copy'] is True and p['message_policy']=='vendor_default',
            'Explicit exact qualification read required')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']), 'Exact CAM CLSID required')
    return deepcopy(p)


def run(sw,clsid,typelib_path,*,loaded,args,audit):
    receipt=common._local_receipt(args['receipt_path']);target=loaded['configured_contour']
    r=dict(schema_version=1,scope=SCOPE,status='reading',phase='preflight',read_only=True,
        process_id=args['process_id'],process_ownership=deepcopy(loaded['ownership']),
        expected_document_path=args['expected_document_path'],expected_source_sha256=args['expected_source_sha256'],
        checkpoint_pin=deepcopy(loaded['parent_pin']),operation_native_id=target['native_id'],
        feature_native_id=target['feature_native_id'],tool_native_id=target['tool_native_id'],
        interface_audit=audit,evidence_pins=deepcopy(loaded['pins']),
        offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        readback_verified=False,mutation_attempted=False,save_attempted=False,model_saved=False,
        GTP_attempted=False,export_attempted=False,full_CAD_stock_capture=False,
        units_reread=False,full_catalogue_reread=False,production_qualified=False,automatic_retry=False)
    started=monotonic();backend=None
    def persist():
        r['elapsed_seconds']=monotonic()-started;_write_receipt(receipt,r)
    _write_receipt(receipt,r,create=True)
    try:
        backend=NativeBackend(loaded,args,sw,clsid,typelib_path,r,persist)
        backend.start();r['before_document']=backend.ctx.identity();persist()
        backend.observe();backend.finish()
        r['after_document']=backend.ctx.identity()
        require(r['before_document']==r['after_document']==loaded['state']['document'],
                'Document identity or dirty state changed')
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins'])
        r.update(status='observed',phase='finished',readback_verified=True,
                 phase_proofs_verified_after_read=True)
    except Exception as exc:
        r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        if backend:
            try:backend.close()
            except Exception as exc:r.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request)
    identity={k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    loaded=load_checkpoint(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],**identity)
    registration=common.discover_export_registration(loaded,p['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=audit_interfaces(typelib,loaded['generated_pin'])
    loaded['pins']=common._merge(loaded['pins'],[audit['type_library_pin']])
    require(len(loaded['pins'])<=64,'Bounded TLB-pinned reader closure required')
    receipt=common._local_receipt(p['receipt_path'])
    protected=[p['expected_document_path']]+[v['path'] for v in loaded['pins']+loaded['offline_export_proof_pins']]
    require(common._key(receipt) not in {common._key(v) for v in protected},'Receipt aliases protected input')
    if validate_only:
        return dict(status='validated_offline',native_called=False,interface_audit=audit,
            selected=target_projection(loaded),live_pin_count=len(loaded['pins']))
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return run(sw,registration['clsid'],typelib,loaded=loaded,args=p,audit=audit)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true')
    options=parser.parse_args(argv)
    result=dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')),
                            validate_only=options.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
