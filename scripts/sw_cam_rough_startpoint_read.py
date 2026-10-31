"""Read a saved pocket operation's existing native start-point list.

The returned collection interface is qualified by exact QI, never inferred from
an IDispatch return declaration. This module cannot create or change points.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts import sw_cam_pocket_pair_read as pocket
from scripts import sw_cam_chamfer_nc_planes as nc
from scripts import sw_cam_read_progress_journal as journal
from scripts.sw_cam_comtypes import _load_type_library
from scripts.sw_cam_face_interfaces import _verify_generated_class
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_rough_firstcut import require

common, group = nc.common, nc.group
SCOPE = 'SAVED_ROUGH_STARTPOINT_LIST_READ_V1'
PARAMS = pocket.PARAMS | {'pocket_receipt_path', 'pocket_receipt_sha256'}
COLLECTION_IID = '{670DD771-2C33-11D6-A9A1-00062999E55F}'
START_IID = '{8C4F59A9-624F-4D23-9D0E-A0051C1EC5A6}'
MAX_POINTS = 8
MAX_CALLS = 400
GETTERS = pocket.CAM_GETTERS | {'GetStartPointList', 'StartPointType', 'Position'}
INTERFACES = pocket.CAM_INTERFACES | {'ICWStartPoint'}
TYPE_NAMES = {0:'CW_DEFAULT_STARTPOINT',1:'CW_USERDEFINED',2:'CW_ENTRYDRILLASSOCIATED',3:'CW_HOLECENTER',4:'CW_ARCCENTER'}


def interface_class(name, typelib, generated):
    require(name in INTERFACES, 'Interface outside start-point reader')
    if name == 'ICWStartPoint':
        return _verify_generated_class(getattr(_load_type_library(str(typelib)), name), START_IID, generated)
    return pocket.cam_class(name, typelib, generated)


def audit_interfaces(typelib, generated):
    from ctypes import HRESULT, POINTER, c_double, c_int
    from comtypes.automation import IDispatch
    contracts = [
        ('ICWRghMillOp','GetStartPointList',95,(POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10),None),
        ('ICWStartPoint','StartPointType',1,(POINTER(c_int),),(10,),'propget'),
        ('ICWStartPoint','Position',2,(POINTER(POINTER(IDispatch)),),(10,),'propget'),
        ('ICWDispatchCollection','Count',1,(POINTER(c_int),),(10,),'propget'),
        ('ICWDispatchCollection','Item',0,(c_int,POINTER(POINTER(IDispatch))),(1,10),None),
        ('ICWPosition','GetCoordinates',1,(POINTER(c_double),)*3,(2,2,2),None),
    ]
    rows=[]
    for owner,name,dispid,args,flags,property_kind in contracts:
        cls=interface_class(owner,typelib,generated)
        declared_name='_get_'+name if property_kind=='propget' else name
        found=[v for v in cls._methods_ if v.name==declared_name]
        require(len(found)==1, 'Unique exact getter ABI required: '+owner+'.'+name)
        m=found[0]
        require(m.restype is HRESULT and int(m.idlflags[0])==dispid and m.argtypes==args
            and tuple(v[0] for v in m.paramflags)==flags, 'Exact getter ABI differs: '+owner+'.'+name)
        rows.append(dict(interface=owner,member=name,dispid=dispid,paramflags=list(flags),iid=str(cls._iid_).upper()))
    return dict(getters=rows,collection_type_native_qualified=False,application_connections=0,native_calls=0)


def read_startpoints(operation, feature, *, read, typed, metadata, diagnostic):
    owner=typed(operation,'ICWRghMillOp')
    result=dict(hole_center_entry=nc.scalar('bool',read(owner,'GetHoleCentreEntry',feature)),
        entry_type=nc.scalar('long',read(owner,'GetEntryExitType',feature)),rows=[],
        collection_interface_verified=False,position_frame_qualified=False,coordinate_frame='unknown_native')
    diagnostic['observation']=result
    raw=read(owner,'GetStartPointList',feature)
    diagnostic['list_returned']=True
    if raw is None or not bool(raw):
        result.update(list_is_null=True,count=0,read_complete=True)
        return result
    result['list_is_null']=False
    diagnostic['stage']='collection_type_info'
    result['collection_type_info']=metadata(raw)
    require(result['collection_type_info']['guid']==COLLECTION_IID, 'Returned collection metadata is not ICWDispatchCollection')
    diagnostic['stage']='QI ICWDispatchCollection'
    collection=typed(raw,'ICWDispatchCollection')
    result['collection_interface_verified']=True
    count=read(collection,'Count')
    require(type(count) is int and 0<=count<=MAX_POINTS,'Bounded exact start-point count required')
    result['count']=count
    for index in range(count):
        diagnostic.update(stage='startpoint',index=index)
        point=typed(read(collection,'Item',index),'ICWStartPoint')
        kind=read(point,'StartPointType')
        require(type(kind) is int and kind in TYPE_NAMES,'Known exact start-point type required')
        row=dict(index=index,type_raw=kind,type_name=TYPE_NAMES[kind],position_native=None)
        result['rows'].append(row)
        position=read(point,'Position')
        row['position_is_null']=position is None or not bool(position)
        if not row['position_is_null']:
            row['position_native']=pocket.vector(read(typed(position,'ICWPosition'),'GetCoordinates'),3)
    require(read(collection,'Count')==count,'Start-point collection size changed while reading')
    result['read_complete']=True
    return result


class StartPointReadBatch(pocket.PocketReadBatch):
    def read(self,obj,name,*args):
        self.reject(name in GETTERS,'Getter outside exact start-point read scope')
        for arg in args:self.reject(type(arg) is int or (type(arg) is str and len(arg)<=128) or id(arg) in self._known_objects,
            'Argument outside retained graph')
        return self.observed(obj,'getter',name,lambda:_member(obj,name,*args))
    def metadata(self,obj):
        info=self.observed(obj,'getter','IDispatch.GetTypeInfo',lambda:obj.GetTypeInfo(0))
        require(info is not None and bool(info),'Non-null collection type information required')
        def attribute():
            attr=info.GetTypeAttr()
            return dict(guid=str(attr.guid).upper(),typekind=int(attr.typekind),member_count=int(attr.cFuncs))
        result=self.observed(info,'getter','ITypeInfo.GetTypeAttr',attribute)
        docs=self.observed(info,'getter','ITypeInfo.GetDocumentation',lambda:info.GetDocumentation(-1))
        require(type(docs) in (tuple,list) and len(docs)==4 and type(docs[0]) is str and 0<len(docs[0])<=128,
            'Bounded collection type name required')
        result['name']=docs[0]
        return result
    def typed(self,obj,name):
        self.reject(name in INTERFACES,'Interface outside exact start-point read scope')
        cls=interface_class(name,self.typelib_path,self.generated_pin)
        def query():
            value=obj.QueryInterface(cls)
            require(value is not None and bool(value) and isinstance(value,cls),'Exact non-null native interface required')
            return value
        return self.observed(obj,'qi',name,query)


class NativeBackend(nc.NativeBackend):
    def observe(self):
        r=self.report;handles={};state=dict(member='',returned=False,read_index=0)
        def binding():
            self.events();require(_member(self.doc,'GetDocType')==1,'Retained CAM part changed')
            if 143 in handles:require(_object_id(self.doc,handles[143],_member)==143,'Retained rough operation changed')
            self.events()
        protected=[self.args['expected_document_path'],self.args['receipt_path']]+[v['path'] for v in self.loaded['pins']]
        with journal.ReadProgressJournal(full_persist=self.persist,progress_path=self.args['progress_path'],
            describe=lambda:dict(state,phase=r['phase']),max_updates=900,protected_paths=protected) as progress:
            b=StartPointReadBatch(self.sw,self.typelib_path,generated_pin=self.loaded['generated_pin'],
                process_id=self.args['process_id'],expected_document=self.ctx.identity(),source_sha256=self.args['expected_source_sha256'],
                evidence_pins=self.loaded['pins'],verify_evidence=self.ctx.files,verify_owned_process=self.ctx.owned,
                check_events=self.events,retained_objects=(self.doc,),verify_retained_binding=binding,
                max_native_calls=MAX_CALLS,progress=progress.read,progress_state=state)
            try:
                with b:
                    r['before_binding'],h=pocket.read_binding(self.doc,self.loaded,read=b.read,typed=b.typed);handles.update(h)
                    require(group.exact(r['before_binding'],self.loaded['pocket_saved_binding']),'Completed pocket read binding differs')
                    r['phase']='startpoint_list';r['startpoint_diagnostic']={}
                    r['startpoints']=read_startpoints(handles[143],handles['feature_dispatch'],read=b.read,typed=b.typed,
                        metadata=b.metadata,diagnostic=r['startpoint_diagnostic'])
                    r['phase']='after_binding'
                    r['after_binding'],_=pocket.read_binding(self.doc,self.loaded,read=b.read,typed=b.typed)
                    require(group.exact(r['before_binding'],r['after_binding']),'Route binding changed during reading')
                b.require_complete();progress.complete()
            finally:r['read_batch']=b.summary()


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_rough_startpoints',
        'Exact read-only start-point action required')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact start-point request fields required')
    base={k:v for k,v in p.items() if k in pocket.PARAMS};base['module_sha256']=_file_hash(pocket.__file__)
    pocket.validate_request(dict(action='read_pocket_pair',params=base))
    require(p['module_sha256']==_file_hash(__file__),'Exact start-point reader module required')
    require(type(p['pocket_receipt_path']) is str and Path(p['pocket_receipt_path']).is_absolute(),'Absolute completed pocket receipt required')
    require(type(p['pocket_receipt_sha256']) is str and nc.re.fullmatch('[0-9a-f]{64}',p['pocket_receipt_sha256']),
        'Exact completed pocket receipt SHA required')
    return deepcopy(p)


def load_inputs(p):
    loaded=pocket.load_inputs(p)
    prior,pin=read_pin(p['pocket_receipt_path'],p['pocket_receipt_sha256'])
    require(prior.get('scope')==pocket.SCOPE and prior.get('status')=='observed' and prior.get('readback_verified') is True
        and prior.get('parameter_read_complete') is True and prior.get('phase_proofs_verified_after_read') is True,
        'Completed pocket parameter read required')
    require(all(prior.get(k) is False for k in ('mutation_attempted','save_attempted','GTP_attempted','export_attempted')),
        'Pocket parent must be read-only')
    require(prior['expected_source_sha256']==p['expected_source_sha256'] and prior['process_id']==p['process_id']
        and common._key(prior['expected_document_path'])==common._key(p['expected_document_path']), 'Exact saved pocket source required')
    require(group.exact(prior['before_binding'],prior['after_binding']) and
        prior['before_document']==prior['after_document']==loaded['state']['document'], 'Completed pocket binding differs')
    clean_events(prior)
    common._check(prior['evidence_pins']);common._check(prior['offline_proof_pins'])
    live=common._merge(loaded['pins'],[common._pin(__file__),common._pin(pocket.__file__)])
    offline=common._merge(loaded['offline_export_proof_pins'],[pin])
    require(len(live)<=64,'Bounded start-point dependency closure required')
    return dict(loaded,pins=live,offline_export_proof_pins=offline,pocket_read_pin=pin,
        pocket_saved_binding=deepcopy(prior['before_binding']))


def run(sw,clsid,typelib,*,loaded,args,audit):
    receipt=common._local_receipt(args['receipt_path'])
    r=dict(schema_version=1,scope=SCOPE,status='reading',phase='preflight',read_only=True,
        process_id=args['process_id'],process_ownership=deepcopy(loaded['ownership']),expected_document_path=args['expected_document_path'],
        expected_source_sha256=args['expected_source_sha256'],checkpoint_pin=loaded['parent_pin'],pocket_read_pin=loaded['pocket_read_pin'],
        startpoint_interface_audit=audit,evidence_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],
        feature_native_id=79,operation_native_id=143,tool_native_id=145,readback_verified=False,
        mutation_attempted=False,save_attempted=False,GTP_attempted=False,export_attempted=False,model_saved=False,
        full_CAD_stock_capture=False,full_parameters_reread=False,full_tool_profile_reread=False,indexed_chains_reread=False,
        automatic_retry=False,production_qualified=False)
    start=monotonic();backend=None
    def persist():r['elapsed_seconds']=monotonic()-start;_write_receipt(receipt,r)
    _write_receipt(receipt,r,create=True)
    try:
        backend=NativeBackend(loaded,args,sw,clsid,typelib,r,persist);backend.start()
        r['before_document']=backend.ctx.identity();persist()
        backend.observe();backend.finish();r['after_document']=backend.ctx.identity()
        require(r['before_document']==r['after_document']==loaded['state']['document'],'Document or saved state changed')
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins'])
        r.update(status='observed',phase='finished',readback_verified=True,phase_proofs_verified_after_read=True)
    except Exception as exc:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
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
    loaded['pins']=common._merge(loaded['pins'],[common._pin(typelib)])
    require(len(loaded['pins'])<=64,'Bounded TLB-pinned dependency closure required')
    receipt=common._local_receipt(p['receipt_path']);progress=Path(p['progress_path'])
    keys={common._key(v) for v in [p['expected_document_path']]+[r['path'] for r in loaded['pins']+loaded['offline_export_proof_pins']]}
    require(common._key(receipt) not in keys and common._key(progress) not in keys and common._key(receipt)!=common._key(progress)
        and progress.suffix.lower()=='.json' and progress.parent.is_dir() and not progress.exists() and not progress.is_symlink(),
        'Fresh distinct outputs outside protected inputs required')
    if validate_only:return dict(status='validated_offline',native_called=False,interface_audit=audit,
        live_pin_count=len(loaded['pins']),operation_native_id=143,max_native_calls=MAX_CALLS)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return run(sw,registration['clsid'],typelib,loaded=loaded,args=p,audit=audit)
