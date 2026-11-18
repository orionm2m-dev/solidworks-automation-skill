"""One CAM process import into an already-open isolated copy; no Save or replay."""
from copy import deepcopy
from pathlib import Path
from contextlib import ExitStack
import math,re,os
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_comtypes import _interface_class,_INTERFACES
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_inventory import _same_bodies,_same_inventory,_items
from scripts.sw_cam_mill_route_context import read_generic_tool,integer
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_qualification import _vector
from scripts.sw_cam_mill_qualification import _snapshot as capture_empty_snapshot
from scripts.sw_cam_mill_units_qualification import _features as cad_features,_bodies as cad_bodies
from scripts.sw_cam_mill_route_context import read_route_operations
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import solidworks_operation_lock,check_document_target

SCOPE='MILL_ISOLATED_PROCESS_IMPORT_OBSERVATION_V1'
EXPORT_SCOPE='MILL_CURRENT_SAVED_PROCESS_EXPORT_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
 'original_document_path','original_source_sha256','export_receipt_path','export_receipt_sha256',
 'receipt_path','qualification_only','message_policy','acknowledge_isolated_copy','allow_vendor_default_import_rebuild'}
MAX_ARCHIVE_BYTES=128*1024*1024
def require(value,message):
    if not value:raise ValueError(message)

def file_pin(path,sha):
    p=Path(path);require(p.is_absolute()and p.is_file()and not p.is_symlink(),'Direct absolute existing file required')
    require(_file_hash(p)==sha,'Exact immutable file SHA required');return dict(path=str(p),sha256=sha)

def marker_path(v,archive_sha):
    # Target path is the attempt identity; archive/source changes do not authorize replay.
    return Path(v['expected_document_path']).parent/('process_import_'+_digest(dict(scope=SCOPE,copy=str(Path(v['expected_document_path']).resolve()).casefold(),))+'.json')

def local_archive_path(archive):
    return bool(archive.drive and not archive.drive.startswith('\\')and not str(archive.resolve()).startswith('\\\\'))

def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact isolated import request required')
    require(all(v[k]is True for k in('qualification_only','acknowledge_isolated_copy','allow_vendor_default_import_rebuild'))and v['message_policy']=='vendor_default','Explicit isolated qualification admitting vendor-default import/rebuild effects required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact process lifetime required')
    for k,value in v.items():
        if k.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
        if k.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Explicit absolute path required')
    copy=Path(v['expected_document_path']);original=Path(v['original_document_path'])
    require(copy.suffix.lower()==original.suffix.lower()=='.sldprt'and v['expected_source_sha256']==v['original_source_sha256'],'Exact byte-copy of pinned original part required')
    pins=[file_pin(copy,v['expected_source_sha256']),file_pin(original,v['original_source_sha256'])]
    require(copy.resolve()!=original.resolve()and copy.parent.resolve()!=original.parent.resolve()and not os.path.samefile(copy,original),'Separate isolated directory and physical file required')
    export,ep=read_pin(v['export_receipt_path'],v['export_receipt_sha256'])
    require(export.get('scope')==EXPORT_SCOPE and export.get('status')=='review_required'and export.get('phase')=='finished','Completed process export required')
    for k in('export_verified','readback_verified','runtime_unchanged','source_unchanged','native_call_returned'):require(export.get(k)is True,'Missing export fact: '+k)
    require(export.get('native_return_type')=='int'and type(export.get('native_return_value'))is int and export['native_return_value']==0,'Exact native export HRESULT0 required')
    require(not any(k in export for k in('issue','runtime_error','cleanup_error'))and export.get('native_dispatch_pending')is False,'Unresolved export result');clean_events(export)
    require(export['before'].get('capture_complete')is True and export['before']==export['after'],'Complete unchanged exported inventory required')
    cam_source=Path(export['request']['expected_document_path']);cam_sha=export['request']['expected_source_sha256']
    require(export['source_before_sha256']==export['source_after_sha256']==cam_sha,'Exact exported source transition required')
    pins.append(file_pin(cam_source,cam_sha));require(not os.path.samefile(copy,cam_source)and copy.resolve()!=cam_source.resolve(),'Import cannot target archived CAM source')
    out=export['output'];archive=Path(out['path'])
    require(archive.suffix.lower()=='.prtcam'and local_archive_path(archive)and type(out['bytes'])is int and 0<out['bytes']<=MAX_ARCHIVE_BYTES,'Bounded local native process archive required')
    pins.append(file_pin(archive,out['sha256']));require(archive.stat().st_size==out['bytes'],'Archive byte size changed')
    archived=export['before']['operations'];require(type(archived)is list and 1<=len(archived)<=32 and len({r['native_id']for r in archived})==len(archived),'Bounded complete archived operation table required')
    pins.extend([ep,dict(path=__file__,sha256=_file_hash(__file__))])
    receipt=Path(v['receipt_path']);marker=marker_path(v,out['sha256'])
    require(receipt.suffix.lower()=='.json'and receipt.parent.is_dir()and not receipt.exists()and not receipt.is_symlink()and not marker.exists()and not marker.is_symlink(),'Fresh receipt and unused copy-specific marker required')
    protected={Path(p['path']).resolve()for p in pins}
    require(receipt.resolve()!=marker.resolve()and receipt.resolve()not in protected and marker.resolve()not in protected,'Output aliases protected evidence')
    return dict(copy=copy,original=original,archive=archive,archive_pin=deepcopy(out),export=export,export_pin=ep,archived_operations=deepcopy(archived),pins=pins,receipt=receipt,marker=marker)

_ISSUER=object()
class _Prepared:
    __slots__=('issuer','v','data','digest','pins','used')
    def __init__(self,issuer,v,data,pins):
        require(issuer is _ISSUER,'Private preparation issuer required')
        self.issuer=_ISSUER;self.v=deepcopy(v);self.data=deepcopy(data);self.pins=deepcopy(pins);self.used=False;self.digest=self.fingerprint()
    def fingerprint(self):return _digest(dict(v=self.v,data={k:str(x)if isinstance(x,Path)else x for k,x in self.data.items()},pins=self.pins))

def _observed_pin(pin):
    from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes
    from scripts.sw_cam_stock_mesh_compare import _signature
    p=Path(pin['path']);require(p.is_file()and not p.is_symlink(),'Regular prepared evidence required')
    if p.suffix.lower()=='.json':_,actual=_receipt_bytes(str(p))
    else:
        canonical=p.resolve(strict=True);identity=list(_signature(p.stat()));digest=_file_hash(p)
        require(p.resolve(strict=True)==canonical and list(_signature(p.stat()))==identity,'Evidence changed while hashing')
        actual=dict(path=str(p),canonical_path=str(canonical),bytes=identity[2],sha256=digest,identity=identity)
    require(all(k in actual and actual[k]==v for k,v in pin.items()),'Prepared pin changed');return actual

def prepare(v,*,runtime_check,_validate=validate):
    require(callable(runtime_check),'Runtime guard required');runtime_check();data=_validate(v)
    pins=[_observed_pin(p)for p in data['pins']];runtime_check();return _Prepared(_ISSUER,v,data,pins)

def _consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Unused invocation-local import preparation required');bundle.used=True
    require(_digest(bundle.v)==_digest(v)and bundle.fingerprint()==bundle.digest,'Prepared request or authority changed');runtime_check()
    for p in bundle.pins:_observed_pin(p)
    d=bundle.data;require(not d['receipt'].exists()and not d['receipt'].is_symlink()and not d['marker'].exists()and not d['marker'].is_symlink(),'Fresh import outputs required')
    require(not os.path.samefile(d['copy'],d['original'])and d['copy'].parent.resolve()!=d['original'].parent.resolve(),'Isolated target changed')
    runtime_check();return d

def preflight(tlb):
    from ctypes import HRESULT,c_int
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes import BSTR
    cls=_interface_class('ICWApp4',tlb);require(str(cls._iid_).upper()==_INTERFACES['ICWApp4'].upper(),'Exact ICWApp4 IID required');methods=[m for m in cls._methods_ if m.name=='ImportCAMData'];require(len(methods)==1,'One native ImportCAMData declaration required');m=methods[0]
    require(m.restype is HRESULT and m.idlflags[0]==45 and m.argtypes==(BSTR,c_int,VARIANT_BOOL)and tuple(p[0]for p in m.paramflags)==(1,1,1)and not any(x in m.idlflags for x in('propget','propput','propputref')),'Exact HRESULT ImportCAMData(BSTR,enum,VARIANT_BOOL) ABI required')
    return dict(interface='ICWApp4',method='ImportCAMData',dispid=45,existing_data=0,merge_setup=False,native_calls=0)

def event_health(summary,*,active):
    require(summary.get('subscribed')is True and summary.get('active')is active and not any(summary.get(k)for k in('overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event transport error')
    n=summary.get('event_count');require(type(n)is int and 0<=n<=100 and type(summary.get('events'))is list and len(summary['events'])==n,'Complete bounded CAM messages required')
    if not active:require(summary.get('disconnected')is True,'CAM subscription must be closed')
    return n

def compare_archive(archived,observed):
    require(type(observed)is list and 1<=len(observed)<=32,'Nonempty bounded imported operation table required')
    fields=('mill_operation_type','suppressed')
    rows=[]
    for index,(a,b)in enumerate(zip(archived,observed)):
        descriptors=all(a[k]==b[k]for k in fields)and len(a['linked_feature_ids'])==len(b['linked_feature_ids'])
        toolkeys=('tool_type_raw','cut_diameter_native','protrusion_native')
        descriptors=descriptors and all(a['assigned_tool'][k]==b['assigned_tool'][k]for k in toolkeys)
        rows.append(dict(index=index,historical_operation_native_id=a['native_id'],observed_operation_native_id=b['native_id'],ordered_descriptor_match=descriptors,cached_count_match=a['toolpath_record_counts']==b['toolpath_record_counts'],historical_record_counts=a['toolpath_record_counts'],observed_record_counts=b['toolpath_record_counts']))
    return dict(archived_operation_count=len(archived),observed_operation_count=len(observed),definition_count_matches=len(archived)==len(observed),ordered_observations=rows,native_identity_mapping_verified=False,feature_association_verified=False,cached_CL_preservation_verified=False,tool_holder_geometry_verified=False,stock_transfer_verified=False)


def capture_import_inventory(app,tlb,guard,diagnostic,progress):
    """Generic bounded identities/links/flags/counts after import; no contour or CL record reads."""
    state=dict(capture_complete=False,feature_setups=[],features=[],operation_setups=[],operations=[])
    diagnostic.update(capture_complete=False,native_read_count=0,state=state)
    def read(obj,name,*args):
        diagnostic['native_read_count']+=1;require(diagnostic['native_read_count']<=4096,'Imported inventory read limit')
        diagnostic['last_native_method']=name
        value=guard.read(obj,name,*args);return value
    def typed(raw,name):require(raw is not None,'Missing public '+name);return guard.typed(raw,name)
    active=read(app,'IGetActiveDoc');doc=typed(active,'ICWDoc3');require(integer(read(doc,'GetDocType'),'CAM document type')==1,'Imported CAM part required')
    state['cam_configuration_name']=read(doc,'GetActiveConfigurationName')
    conf=typed(read(doc,'GetActiveConfiguration'),'ICWConfiguration')
    state['associated_sw_configuration']=read(conf,'SWConfigurationName');state['configuration_name']=read(conf,'ConfigurationName')
    require(type(state['cam_configuration_name'])is str and state['cam_configuration_name']==state['configuration_name'],'CAM configuration object mismatch')
    machine=typed(read(typed(active,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    state['machine_type']=integer(read(machine,'MachType'),'machine type');require(state['machine_type']==1,'Imported archive must produce MILL')
    native_ids=set();feature_ids=set();tool_ids=set()
    def identity(raw):
        value=integer(_object_id(doc,raw,read),'native ID',1);require(value not in native_ids,'Duplicate or cross-kind native identity');native_ids.add(value);return value
    for si,raw in enumerate(_items(read(machine,'IGetEnumSetups'),typed,read,8)):
        setup=typed(raw,'ICWBaseSetup');sid=identity(setup);mill=typed(raw,'ICWSetup')
        members=_items(read(setup,'IGetEnumFeatures'),typed,read,64-len(state['features']))
        row=dict(index=si,native_id=sid,axis_native=_vector(read(setup,'Axis')),origin_native=_vector(read(mill,'GetReferencePosition')),feature_ids=[]);state['feature_setups'].append(row)
        for fi,item in enumerate(members):
            feat=typed(item,'ICWFeature');fid=identity(feat);feature_ids.add(fid);row['feature_ids'].append(fid)
            header=typed(item,'ICWMillFeature');suppressed=read(feat,'Suppressed');name=read(feat,'FeatureName')
            require(type(suppressed)is bool and type(name)is str and len(name)<=1024,'Bounded raw feature header required')
            state['features'].append(dict(setup_index=si,feature_index=fi,setup_native_id=sid,native_id=fid,volume_type=integer(read(header,'VolumeType'),'feature type'),subtype_raw=integer(read(header,'SubType'),'feature subtype'),name=name,suppressed=suppressed))
        progress(diagnostic)
    total_records=0
    for si,raw in enumerate(_items(read(machine,'IGetEnumOpSetups'),typed,read,8)):
        setup=typed(raw,'ICWBaseOpSetup');sid=identity(setup)
        members=_items(read(setup,'IGetEnumOperations'),typed,read,32-len(state['operations']))
        state['operation_setups'].append(dict(index=si,native_id=sid,operation_count=len(members)))
        for oi,item in enumerate(members):
            op=typed(item,'ICWOperation');mill=typed(item,'ICWMillOperation');oid=identity(op)
            row=dict(setup_index=si,operation_index=oi,setup_native_id=sid,native_id=oid,mill_operation_type=integer(read(mill,'OpernType'),'MILL type'),base_operation_type=integer(read(op,'OpernType'),'base type'),suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'))
            state['operations'].append(row)
            require(type(row['suppressed'])is bool and type(row['toolpath_generated'])is bool,'Strict imported flags required')
            links=[integer(_object_id(doc,x,read),'linked feature ID',1)for x in _items(read(op,'IGetAllFeatures'),typed,read,64)]
            require(len(links)==len(set(links)),'Duplicate feature links');row['linked_feature_ids']=links;row['all_linked_features_observed']=bool(links)and set(links)<=feature_ids
            counts=[]
            for path in _items(read(op,'IGetEnumToolpaths'),typed,read,32):counts.append(integer(read(typed(path,'ICWToolpath'),'RecordCount'),'record count',0,100000))
            total_records+=sum(counts);require(total_records<=100000,'Imported aggregate record limit');row['toolpath_record_counts']=counts
            row['assigned_tool'],_=read_generic_tool(item,doc,read,typed);tid=row['assigned_tool']['native_id'];require(tid not in native_ids,'Tool collides with definition identity');tool_ids.add(tid);require(len(tool_ids)<=32,'Imported tool bound')
            progress(diagnostic)
    require(not native_ids&tool_ids,'Cross-kind native identity collision')
    state.update(feature_count=len(state['features']),operation_count=len(state['operations']),generated_operation_count=sum(x['toolpath_generated']for x in state['operations']),total_record_count=total_records,unique_tool_count=len(tool_ids),capture_complete=True,inventory_scope='bounded_generic_ids_setup_vectors_links_flags_path_counts_generic_tools',feature_association_verified=False,units_verified=False)
    diagnostic['capture_complete']=True;progress(diagnostic);return state

class ImportContext:
    def __init__(self,sw,clsid,tlb,v,data,r,persist,runtime_check):
        self.sw,self.clsid,self.tlb=sw,clsid,tlb;self.v,self.data,self.r=v,data,r;self.persist,self.runtime_check=persist,runtime_check;self.stack=ExitStack();self.session=None;self.expected=None;self.baseline=0;self.closed=False;self.sw_configuration=None
    def verify_files(self):
        self.runtime_check()
        for p in self.data['pins']:require(_file_hash(p['path'])==p['sha256'],'Protected source/archive/evidence changed')
    def identity(self):
        self.runtime_check();v=self.v;p=_process_identity(v['process_id'])
        require(p.get('alive')is True and p.get('process_id')==v['process_id']and p.get('create_time')==v['expected_process_create_time']and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact owned process lifetime required')
        pid=_member(self.sw,'GetProcessID');require(type(pid)is int and pid==v['process_id'],'Native process differs')
        doc=document_snapshot(self.sw);require(type(doc)is dict and type(doc.get('type'))is int and doc['type']==1 and type(doc.get('needs_save'))is bool,'Strict part identity required')
        check_document_target(doc['path'],doc['title'],expected_path=v['expected_document_path'],required=True)
        model=_member(self.sw,'ActiveDoc');configuration=_member(_member(_member(model,'ConfigurationManager'),'ActiveConfiguration'),'Name')
        require(type(configuration)is str and 0<len(configuration)<=4096,'Bounded active CAD configuration required')
        if self.sw_configuration is None:self.sw_configuration=configuration
        require(configuration==self.sw_configuration,'Active CAD configuration changed');return doc
    def check_events(self):
        s=self.session.summary();self.r['messages']=s;require(event_health(s,active=True)==self.baseline,'Unexpected event during read-only/pre-dispatch phase')
    def verify_owned(self):
        require(self.identity()==self.expected,'Owned isolated document changed');self.check_events()
    def start(self):
        self.stack.enter_context(solidworks_operation_lock(timeout_seconds=1,process_id=self.v['process_id']))
        self.verify_files();self.expected=self.identity();require(self.expected['needs_save']is False,'Clean isolated disk copy required before import');self.r['document_before']=deepcopy(self.expected)
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded');self.app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb)
        require(self.identity()==self.expected,'Bootstrap changed document');self.session=CamMessageSession(self.app,self.tlb);self.stack.enter_context(self.session);self.check_events()
    def guard(self):
        return ScopedCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=self.expected,source_sha256=self.v['expected_source_sha256'],evidence_pins=self.data['pins'],verify_evidence=self.verify_files,verify_owned_process=self.verify_owned,check_events=self.check_events)
    def capture(self,label,*,empty):
        diagnostic={};self.r[label+'_diagnostic']=diagnostic;self.r['phase']=label;self.persist()
        def progress(value):self.r[label+'_diagnostic']=deepcopy(value);self.persist()
        with self.guard()as guard:
            if empty:
                state,_=capture_empty_snapshot(self.sw,self.clsid,self.tlb,self.v['expected_document_path'],check=guard._fast,diagnostic=diagnostic,required_machine_type=None)
                require(all(type(x)is int and x==0 for x in state['operation_counts'])and all(type(x['feature_count'])is int and x['feature_count']==0 for x in state['feature_setups']),'Isolated copy contains CAM data')
                diagnostic['capture_complete']=False
                model=guard.read(self.sw,'ActiveDoc');tree,_=guard._observe(lambda:cad_features(model));solids=guard._observe(lambda:cad_bodies(model))
                state.update(features=[],operation_count=0,operations=[],sw_reference=dict(feature_tree=tree,solids=solids),all_solid_body_count=len(solids),empty_inventory_scope='existing_UNKNOWN_MILL_TURN_snapshot_zero_features_operations_nullable_workpiece')
                diagnostic['capture_complete']=True
            else:
                state=capture_import_inventory(self.app,self.tlb,guard,diagnostic,progress)
                if getattr(self,'sw_configuration',None)is not None:require(state['associated_sw_configuration']==self.sw_configuration,'Imported CAM points to another CAD configuration')
                model=guard.read(self.sw,'ActiveDoc');tree,_=guard._observe(lambda:cad_features(model));solids=guard._observe(lambda:cad_bodies(model))
                state.update(sw_reference=dict(feature_tree=tree,solids=solids),all_solid_body_count=len(solids))
            guard._boundary()
        self.r[label]=deepcopy(state);self.persist();require(diagnostic.get('capture_complete')is True,'Complete native inventory required')
        if empty:require(state['operation_count']==0 and not state['features'],'Copy must contain zero CAM operations and features')
        return state
    def adopt_post_import_baseline(self):
        # The consumed mutation guard is already closed. Never clear recorded messages.
        s=self.session.summary();self.baseline=event_health(s,active=True);self.r['import_event_baseline']=deepcopy(s);self.r['import_events_require_review']=self.baseline>0
        actual=self.identity();require(actual['title']==self.expected['title'],'Import changed document title');self.expected=actual;self.r['post_import_document']=deepcopy(actual);self.verify_files();self.check_events();self.persist()
    def close(self):
        if self.closed:return
        self.closed=True;self.stack.close()
        if self.session is not None:
            self.r['messages']=self.session.summary();event_health(self.r['messages'],active=False)

def revoke_runtime(r,error):
    r.update(status='uncertain'if r.get('dispatch_claimed')else'error',phase='finished',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,import_observed=False);_write_receipt(Path(r['receipt_path']),r);return r

def run_import(sw,clsid,tlb,*,runtime_check,_prepared=None,_context_factory=ImportContext,_validate=validate,_preflight=preflight,**v):
    bundle=prepare(v,runtime_check=runtime_check,_validate=_validate)if _prepared is None else _prepared
    data=_consume(bundle,v,runtime_check);abi=_preflight(tlb)
    if Path(tlb).is_file():data['pins'].append(file_pin(tlb,_file_hash(tlb)))
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),receipt_path=str(data['receipt']),marker_path=str(data['marker']),export_receipt_pin=data['export_pin'],archive_pin=data['archive_pin'],evidence_pins=deepcopy(data['pins']),abi=abi,dispatch_claimed=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,mutation_attempted=False,Save_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,explicit_rebuild_attempted=False,TechDB_write_attempted=False,automatic_replay=False,model_saved=False,import_observed=False,readback_verified=False,runtime_unchanged=False,originals_unchanged=False,copy_disk_unchanged=False,vendor_default_import_rebuild_allowed=True,vendor_default_internal_effects_qualified=False,CAM_migration_verified=False,full_BRep_preservation_verified=False,production_qualified=False,stock_parameters_exported=False,feature_association_verified=False)
    def persist():_write_receipt(data['receipt'],r)
    _write_receipt(data['receipt'],r,create=True);ctx=None;guard=None
    try:
        ctx=_context_factory(sw,clsid,tlb,v,data,r,persist,runtime_check);ctx.start();before=ctx.capture('before',empty=True)
        confirmed=ctx.capture('before_confirmation',empty=True);require(_same_inventory(before,confirmed),'Empty target state changed before import')
        with ctx.guard()as guard:
            app=guard.typed(ctx.app,'ICWApp4')
            def pending():
                r.update(dispatch_claimed=True,mutation_attempted=True,native_dispatch_pending=True,phase='ImportCAMData_pending')
                _write_receipt(data['marker'],dict(scope=SCOPE,receipt_path=str(data['receipt']),copy_path=str(data['copy']),copy_sha256=v['expected_source_sha256'],archive_sha256=data['archive_pin']['sha256'],automatic_replay=False),create=True);persist()
            def invoke():
                r.update(native_call_attempted=True,phase='ImportCAMData');persist()
                value=_member(app,'ImportCAMData',str(data['archive']),0,False)
                r.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(value).__name__,native_return_value=value if value is None or type(value)in(bool,int,float,str)else None,phase='ImportCAMData_returned');persist();return value
            value=guard.dispatch_once(invoke,persist_pending=pending)
        r['dispatch_guard']=guard.summary();require(type(value)is int and value==0,'Exact ImportCAMData HRESULT0 required; no retry')
        ctx.adopt_post_import_baseline();after=ctx.capture('after',empty=False)
        require(_same_bodies(before['sw_reference']['solids'],after['sw_reference']['solids'])and before['all_solid_body_count']==after['all_solid_body_count'],'Native CAD body fingerprint changed')
        r['archive_comparison']=compare_archive(data['archived_operations'],after['operations'])
        require(r['archive_comparison']['definition_count_matches'],'Imported definition count differs from verified archive')
        ctx.verify_owned();ctx.verify_files();ctx.close();runtime_check()
        require(ctx.identity()==ctx.expected,'Owned isolated document changed during cleanup')
        for p in data['pins']:require(_file_hash(p['path'])==p['sha256'],'Protected file changed after cleanup')
        require(event_health(r['messages'],active=False)==0,'Import emitted CAM messages; captured RAM state requires review, no acceptance or retry')
        r.update(status='review_required',phase='finished',import_observed=True,readback_verified=True,runtime_unchanged=True,originals_unchanged=True,copy_disk_unchanged=True,CAD_body_fingerprint_unchanged=True,reason='UNSAVED_IMPORT_AND_VENDOR_DEFAULT_EFFECTS_OBSERVED_MAPPING_AND_MACHINING_NOT_QUALIFIED')
    except Exception as error:
        if guard is not None:r['dispatch_guard']=guard.summary()
        r.update(status='uncertain'if r['dispatch_claimed']else'error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),readback_verified=False,import_observed=False)
    finally:
        if ctx is not None:
            try:ctx.close()
            except Exception as error:r.update(cleanup_error=_error(error),readback_verified=False,import_observed=False,status='uncertain'if r['dispatch_claimed']else'error')
        r['phase']='finished';persist()
    return r

