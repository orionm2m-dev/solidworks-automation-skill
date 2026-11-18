"""Bounded current circular-operation cutting context; getters only, no COM on import."""
from copy import deepcopy
from ctypes import byref,c_double,c_short,c_long,POINTER,HRESULT
from ctypes.wintypes import VARIANT_BOOL
from pathlib import Path
import math,re,sys
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_comtypes import _interface_class,_load_type_library
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_current_circular_authority import circular_state_equal
from scripts.sw_cam_chamfer_clearance_read import pointer_value as plane_pointer_value
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path,check_document_target,solidworks_operation_lock

SCOPE='CURRENT_CIRCULAR_CUTTING_CONTEXT_READ_V1'
MAX_READS=1024
INTERFACES=('ICWApp4','ICWDoc3','ICWPartDoc','ICWMachine','ICWBaseOpSetup','ICWOperation','ICWMillOperation','ICWTool','ICWToolpath','ICWDispatchCollection','ICWNCParam','ICWNCParam2','ICWNCParam4')
GETTERS={'IGetActiveDoc','IGetMachine','MachType','IGetEnumOpSetups','IGetEnumOperations','Count','Item','GetCWObjectID','Suppressed','GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','IGetAllFeatures','IGetTool','IGetNCParam','GetSpndlSpeed','XYFeed','GetCNCComp','GetTlpComp','GetSpeedFeedMethod','LinkToTool','GetIsLockSpindleSpeed','GetZFeedrate2','GetLeadinFeedratePercent','GetClrPlaneUseSetupStatus','GetRpdPlaneUseSetupStatus','GetRetractType','CutDiameter','Protrusion','IsMillTool','ToolType'}
EVENT_ERRORS=('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','reconciliation_path','reconciliation_sha256','operation_native_id','receipt_path','qualification_only','message_policy'}


def require(ok,message):
    if not ok:raise ValueError(message)


def finite(value):
    require(type(value) in (int,float) and math.isfinite(value),'Finite numeric observation required');return float(value)


def inventory_projection(state):
    return [{k:deepcopy(r[k]) for k in ('native_id','setup_native_id','suppressed','toolpath_generated','toolpath_record_counts')} for r in state['operations']]


def validate(v):
    require(set(v)==KEYS,'Exact read-only fields required')
    require(type(v['process_id']) is int and v['process_id']>0 and type(v['operation_native_id']) is int and v['operation_native_id']>0,'Strict PID/operation required')
    require(finite(v['expected_process_create_time'])>0 and v['qualification_only'] is True and v['message_policy']=='vendor_default','Explicit qualified current owner required')
    for k in ('expected_source_sha256','reconciliation_sha256'):require(type(v[k]) is str and re.fullmatch('[0-9a-f]{64}',v[k]),'Exact SHA required')
    require(absolute_document_path(v['expected_document_path']) and Path(v['expected_document_path']).suffix.casefold()=='.sldprt','Exact saved part required')
    require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Current source changed')
    review,rpin=read_pin(v['reconciliation_path'],v['reconciliation_sha256'])
    require(review.get('status')=='PASS_SCOPED_SAVE_CL_MAPPING_REVIEW' and review.get('save_once_verified') is True and review.get('capture_readback_verified') is True,'Completed pinned save/CL review required')
    require(review['new_operation']['operation_native_id']==v['operation_native_id'] and review['pins']['saved_part']['sha256']==v['expected_source_sha256'] and Path(review['pins']['saved_part']['path']).resolve()==Path(v['expected_document_path']).resolve(),'Reviewed source/operation differs')
    rp=review['pins']['save_receipt'];receipt,pin=read_pin(rp['path'],rp['sha256']);state=receipt['confirm_saved'];prior=receipt['request']
    require(prior['process_id']==v['process_id'] and prior['expected_process_create_time']==v['expected_process_create_time'],'Saved owner/lifetime differs')
    require(receipt['source_after_sha256']==v['expected_source_sha256'] and circular_state_equal(state,receipt['postCL']['after']) and state['document']['needs_save'] is False,'Exact saved after-export state required')
    selected=[r for r in state['operations'] if r['native_id']==v['operation_native_id']]
    require(len(selected)==1 and selected[0]['suppressed'] is False and selected[0]['toolpath_generated'] is True and len(selected[0]['linked_feature_ids'])==1,'One existing generated target required')
    out=Path(v['receipt_path']);require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh absolute receipt required')
    pins=[rpin,pin,dict(path=__file__,sha256=_file_hash(__file__))]
    require(str(out.resolve()).casefold() not in {str(Path(x['path']).resolve()).casefold() for x in pins+[dict(path=v['expected_document_path'])]},'Receipt aliases protected source')
    return dict(state=state,target=selected[0],pins=pins,receipt=out)


def class_for(name,tlb):
    require(name in INTERFACES,'Fixed interface scope required')
    if name!='ICWNCParam4':return _interface_class(name,tlb)
    cls=getattr(_load_type_library(str(tlb)),name);require(str(cls._iid_).upper()=='{3DC6FB05-9C9F-42A4-8532-F1B7892CF3AA}','Exact NC4 IID required');return cls


def preflight(tlb):
    classes={n:class_for(n,tlb) for n in INTERFACES};cls=classes['ICWNCParam'];found=[m for m in cls._methods_ if m.name=='GetLeadinFeedrate'];require(len(found)==1,'One declared lead getter required');m=found[0]
    require(m.restype is HRESULT and m.idlflags[0]==3 and m.argtypes==(POINTER(c_double),POINTER(VARIANT_BOOL)) and tuple(x[0] for x in m.paramflags)==(0,0) and callable(getattr(cls,'_ICWNCParam__com_GetLeadinFeedrate',None)),'Exact owned-pointer lead getter ABI required')
    for name,dispid in (('GetRpdPlnPrms',9),('GetClrPlanePrms',11)):
        methods=[x for x in cls._methods_ if x.name==name];require(len(methods)==1,'One plane getter required');spec=methods[0]
        require(spec.restype is HRESULT and spec.idlflags[0]==dispid and spec.argtypes==(POINTER(c_double),POINTER(c_long)) and tuple(x[0] for x in spec.paramflags)==(0,0),'Exact existing plane pointer ABI required')
    return classes,dict(native_calls=0,lead_getter_dispid=3,plane_getter_dispids=[9,11],owned_output_storage=True,automatic_interface_discovery=False)


def lead_pointer_value(owner,diagnostic):
    require(type(diagnostic) is dict and not diagnostic,'Fresh lead diagnostic required')
    value=c_double(float('nan'));flag=VARIANT_BOOL();c_short.from_buffer(flag).value=12345
    diagnostic.update(attempted=True,returned=False,owned_output_storage=True)
    result=getattr(owner,'_ICWNCParam__com_GetLeadinFeedrate')(byref(value),byref(flag))
    rawflag=c_short.from_buffer(flag).value;diagnostic.update(returned=True,hresult_type=type(result).__name__,hresult=result if type(result) is int else None,value_raw=value.value if math.isfinite(value.value) else None,percent_bool_storage=rawflag)
    require(type(result) is int and result==0 and math.isfinite(value.value) and rawflag in (0,-1),'Populated finite DOUBLE/strict VARIANT_BOOL and HRESULT0 required')
    diagnostic['outputs_validated']=True
    return dict(value_native=value.value,is_percent=rawflag==-1,physical_units_verified=False)


def capture(app,loaded,v,read,typed,pointer,boundary):
    boundary();doc=typed(read(app,'IGetActiveDoc'),'ICWDoc3');part=typed(doc,'ICWPartDoc');machine=typed(read(part,'IGetMachine'),'ICWMachine');require(read(machine,'MachType')==1,'Current MILL required')
    rows=[];chosen=None
    for rawsetup in _items(read(machine,'IGetEnumOpSetups'),typed,read,8):
        setup=typed(rawsetup,'ICWBaseOpSetup');sid=_object_id(doc,rawsetup,read)
        for raw in _items(read(setup,'IGetEnumOperations'),typed,read,32):
            require(len(rows)<32,'At most32 total operations');op=typed(raw,'ICWOperation');oid=_object_id(doc,raw,read);suppressed=read(op,'Suppressed');generated=read(op,'GetIsToolpathGenerated');require(type(suppressed) is bool and type(generated) is bool,'Strict flags required')
            counts=[]
            for path in _items(read(op,'IGetEnumToolpaths'),typed,read,1):
                count=read(typed(path,'ICWToolpath'),'RecordCount');require(type(count) is int and 0<count<=100000,'Positive bounded native count required');counts.append(count)
            require(generated is bool(counts),'Generated/count mismatch');rows.append(dict(native_id=oid,setup_native_id=sid,suppressed=suppressed,toolpath_generated=generated,toolpath_record_counts=counts))
            if oid==v['operation_native_id']:require(chosen is None,'Unique target required');chosen=op
    require(rows==inventory_projection(loaded['state']) and chosen is not None,'Current cheap full inventory changed')
    target=loaded['target'];links=[_object_id(doc,x,read) for x in _items(read(chosen,'IGetAllFeatures'),typed,read,2)];require(links==target['linked_feature_ids'],'Target feature link changed')
    tool=typed(read(chosen,'IGetTool'),'ICWTool');tid=_object_id(doc,tool,read);require(tid==target['assigned_tool']['native_id'],'Target assigned tool changed')
    raw=read(typed(chosen,'ICWMillOperation'),'IGetNCParam');nc=typed(raw,'ICWNCParam');nc2=typed(raw,'ICWNCParam2');nc4=typed(raw,'ICWNCParam4')
    values={k:read(nc,k) for k in ('GetSpndlSpeed','GetCNCComp','GetTlpComp','GetClrPlaneUseSetupStatus','GetRpdPlaneUseSetupStatus','GetRetractType')};values['XYFeed']=read(nc2,'XYFeed')
    for k in ('GetSpeedFeedMethod','LinkToTool','GetIsLockSpindleSpeed','GetZFeedrate2','GetLeadinFeedratePercent'):values[k]=read(nc4,k)
    for k in ('GetSpndlSpeed','XYFeed','GetLeadinFeedratePercent'):values[k]=finite(values[k])
    for k in ('GetCNCComp','GetTlpComp','GetRetractType','GetSpeedFeedMethod'):require(type(values[k]) is int,'Strict NC enum required')
    require(values['GetSpeedFeedMethod'] in (0,1,2),'Only declared operation/library/tool feed methods admitted')
    for k in ('GetClrPlaneUseSetupStatus','GetRpdPlaneUseSetupStatus','LinkToTool','GetIsLockSpindleSpeed'):require(type(values[k]) is bool,'Strict NC flag required')
    z=values['GetZFeedrate2'];require(type(z) in (tuple,list) and len(z)==2 and type(z[1]) is bool,'Exact Z feed DOUBLE/BOOL pair required');values['GetZFeedrate2']=[finite(z[0]),z[1]]
    diagnostic={};values['leadin_feed']=pointer(nc,'leadin',diagnostic)
    planes={}
    for name in ('GetRpdPlnPrms','GetClrPlanePrms'):
        item={};planes[name]=dict(value=pointer(nc,name,item),diagnostic=item)
    boundary();return dict(inventory=rows,operation_native_id=v['operation_native_id'],feature_ids=links,tool_native_id=tid,nc=values,leadin_pointer_diagnostic=diagnostic,local_planes=planes,capture_complete=True,units_verified=False,feed_to_CL_binding_verified=False)


def run_read(sw,clsid,tlb,*,runtime_check,**v):
    loaded=validate(v);classes,abi=preflight(tlb);session=None
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),receipt_path=v['receipt_path'],evidence_pins=deepcopy(loaded['pins']),abi=abi,native_read_count=0,native_read_limit=MAX_READS,read_only=True,mutation_attempted=False,save_attempted=False,GTP_attempted=False,parameter_setter_attempted=False,readback_verified=False,source_unchanged=False,runtime_unchanged=False,production_qualified=False)
    def persist():_write_receipt(loaded['receipt'],r)
    _write_receipt(loaded['receipt'],r,create=True)
    try:
        def identity():
            runtime_check();p=_process_identity(v['process_id']);require(p.get('alive') is True and p.get('process_id')==v['process_id'] and p.get('create_time')==v['expected_process_create_time'] and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact owned process lifetime required');pid=_member(sw,'GetProcessID');require(type(pid) is int and pid==v['process_id'],'Selected PID changed');d=document_snapshot(sw);require(type(d) is dict and d.get('type')==1 and d.get('needs_save') is False,'Clean saved part required');check_document_target(d['path'],d['title'],expected_path=v['expected_document_path'],required=True);require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Saved source changed')
            for pin in loaded['pins']:require(_file_hash(pin['path'])==pin['sha256'],'Read authority changed')
            return d
        with solidworks_operation_lock(timeout_seconds=1,process_id=v['process_id']):
            initial=identity();require(initial==loaded['state']['document'],'Document identity differs from saved state');addin=_member(sw,'GetAddInObject',clsid);require(addin is not None,'CAM must already be loaded');app=_typed(_member(addin,'GetCWApp'),'ICWApp4',tlb);require(identity()==initial,'Identity changed in bootstrap');session=CamMessageSession(app,tlb)
            def check():
                m=session.summary();r['messages']=m;require(m.get('active') is True and m.get('subscribed') is True and not any(m.get(x) for x in EVENT_ERRORS),'CAM event requires stop')
            def boundary():check();require(identity()==initial,'Current document changed');check()
            def admission(name):check();require(r['native_read_count']<MAX_READS,'Read budget exhausted');r['native_read_count']+=1;r['phase']=name
            def read(obj,name,*args):
                require(name in GETTERS,'Getter outside fixed scope');admission(name);value=_member(obj,name,*args);check();return value
            def typed(obj,name):
                require(name in classes,'Interface outside fixed scope');admission('QI '+name);value=obj.QueryInterface(classes[name]);require(value is not None and bool(value) and isinstance(value,POINTER(classes[name])),'Exact typed pointer required');check();return value
            def pointer(obj,name,item):
                require(name in ('leadin','GetRpdPlnPrms','GetClrPlanePrms'),'Only three owned pointer getters allowed');admission(name);r.setdefault('pointer_attempts',[]).append(item);persist()
                try:return lead_pointer_value(obj,item) if name=='leadin' else plane_pointer_value(obj,name,item)
                finally:check();persist()
            with session:
                for label in ('before','after'):
                    r['phase']=label;persist();r[label]=capture(app,loaded,v,read,typed,pointer,boundary);persist()
                require(r['before']==r['after'],'Two complete targeted observations differ');boundary()
            r['messages']=session.summary();clean_events(r);require(identity()==initial,'Document changed after cleanup');runtime_check();r.update(status='review_required',phase='finished',readback_verified=True,source_unchanged=True,runtime_unchanged=True,source_sha256=v['expected_source_sha256'],reason='CURRENT_CIRCULAR_NC_VALUES_OBSERVED_NO_SETTER_OR_RECALCULATION')
    except Exception as error:r.update(status='error',phase='finished',issue=_error(error),readback_verified=False,source_unchanged=False,runtime_unchanged=False)
    finally:
        if session is not None:r['messages']=session.summary()
        persist()
    return r
