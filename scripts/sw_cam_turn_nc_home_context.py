"""One public TURN NC-object -> NC4 QI and optional Home getter qualification."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from comtypes import COMError
from scripts import sw_cam_turn_entry_context as core
from scripts.sw_cam import _member, _error
from scripts.sw_cam_comtypes import _load_type_library
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash

SCOPE='TURN_NC4_HOME_SINGLE_QI_READ_V1'
NC4='ICWNCParam4'
IIDS={'ICWTurnOperation':'{4EDDCA75-325A-11D6-A9A7-00062999E55F}',
      NC4:'{3DC6FB05-9C9F-42A4-8532-F1B7892CF3AA}'}
E_NOINTERFACE=-2147467262
SHARED_READS={'IGetActiveDoc','GetDocType','IGetMachine','MachType','IGetEnumSetups',
              'IGetEnumFeatures','Count','Item','IGetEnumOpSetups','IGetEnumOperations',
              'GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','OpernType',
              'IGetWorkpiece','GetTurnWorkpieceType','GetCWObjectID','IGetAllFeatures'}
EXTRA_READS={'IGetTurnNCParam','QueryInterface','GetHomePosition'}
FIELDS=(core.FIELDS-{'post_parameter_index_policy'})|{'acknowledge_public_interface_qualification'}
require=core.require


def validate(v):
    require(type(v) is dict and set(v)==FIELDS,'Exact NC4 read qualification fields required')
    require(v['acknowledge_public_interface_qualification'] is True,'Explicit single public-QI qualification required')
    require(type(v['targets']) is list and len(v['targets'])==1,'One selected FACE operation required')
    inherited={k:x for k,x in v.items() if k!='acknowledge_public_interface_qualification'}
    inherited['post_parameter_index_policy']='probe_zero_through_count_inclusive'
    return core.validate(inherited)


def preflight(tlb):
    from ctypes import HRESULT, POINTER, c_double
    from comtypes.automation import IDispatch
    library=_load_type_library(str(tlb));classes={n:getattr(library,n) for n in IIDS}
    for name,iid in IIDS.items():require(str(classes[name]._iid_).upper()==iid,'Exact public interface IID required')
    specs=[('ICWTurnOperation','IGetTurnNCParam',4,(POINTER(POINTER(IDispatch)),),(10,)),
           (NC4,'GetHomePosition',37,(POINTER(c_double),)*3,(2,2,2))]
    for owner,name,dispid,args,flags in specs:
        found=[m for m in classes[owner]._methods_ if m.name==name]
        require(len(found)==1,'Unique public getter required')
        m=found[0]
        require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args
                and tuple(x[0] for x in m.paramflags)==flags
                and not any(x in m.idlflags for x in ('propget','propput','propputref')),
                'Public NC4 getter ABI mismatch: '+owner+'.'+name)
    return classes,dict(interfaces=IIDS,getter_count=2,native_calls=0,application_connections=0,
                        TURN_NC_object_support_verified=False)


def observe_home(turn,*,read,query,progress):
    """Only native COM E_NOINTERFACE from this exact QI is an unsupported observation."""
    row=dict(qi_attempted=False,qi_returned=False,nc4_qi_attempt_count=0,
             nc4_supported=False,home_getter_attempted=False,home_value_read=False,
             capability_outcome='pending',home_position_semantics_verified=False,
             units_verified=False,coordinate_frame_verified=False,
             editable_home_contract_verified=False,complete=False)
    progress(row)
    owner=read(turn,'IGetTurnNCParam')
    require(owner is not None and bool(owner),'Exact returned TURN NC owner must be non-null')
    row['TURN_NC_owner_returned']=True;row['qi_attempted']=True;row['nc4_qi_attempt_count']=1;progress(row)
    try:
        nc4=query(owner)
    except COMError as exc:
        hr=getattr(exc,'hresult',None)
        if type(hr) is not int or hr not in (E_NOINTERFACE,0x80004002):
            raise
        row.update(qi_issue=_error(exc),native_hresult_raw=hr,native_hresult_signed=E_NOINTERFACE,
                   capability_outcome='unsupported_pending_context_verification',complete=True)
        progress(row);return row
    row.update(qi_returned=True,nc4_supported=True);progress(row)
    row['home_getter_attempted']=True;progress(row)
    raw=read(nc4,'GetHomePosition')
    require(type(raw) in (tuple,list) and len(raw)==3,'Exactly three Home DOUBLE outputs required')
    xyz=[core.number(x) for x in raw]
    row.update(home_raw_xyz=dict(zip(('X','Y','Z'),xyz)),home_value_read=True,
               capability_outcome='readable_pending_context_verification',complete=True)
    progress(row);return row


class NativeHome(core.NativeRead):
    def read(self,obj,name,*args):
        if name in SHARED_READS:return super().read(obj,name,*args)
        require(name in EXTRA_READS,'NC4 read allowlist violation: '+str(name))
        if name=='QueryInterface':
            require(len(args)==1 and args[0] is self.classes[NC4],'Only exact public NC4 QI allowed')
        self.check();self.report['phase']=name;self.report['native_read_count']+=1
        require(self.report['native_read_count']<=4096,'Native read bound exceeded')
        value=_member(obj,name,*args);self.check();return value

    def query_nc4(self,owner):
        value=self.read(owner,'QueryInterface',self.classes[NC4])
        require(value is not None and bool(value) and isinstance(value,self.classes[NC4]),
                'NC4 QI must return exact non-null public interface')
        return value

    def selected(self,target,progress):
        self.boundary();operation=self.handles[target['operation_native_id']]
        turn=_typed(operation,'ICWTurnOperation',self.tlb)
        result=observe_home(turn,read=self.read,query=self.query_nc4,progress=progress)
        self.boundary();return result


def classify_after_guards(report):
    """Promote capability observation only after inherited after-capture/cleanup succeeds."""
    report['native_capability_verified']=False
    if report.get('status')=='error':return report
    require(all(report.get(key) is True for key in core.SUCCESS_FLAGS),
            'Complete unchanged source/runtime/inventory and cleanup required')
    require(len(report['observations'])==1 and report['observations'][0].get('complete') is True,
            'One completed capability observation required')
    row=report['observations'][0]
    if row['capability_outcome']=='unsupported_pending_context_verification':
        require(row['nc4_qi_attempt_count']==1 and row['qi_attempted'] is True and row['qi_returned'] is False
                and row['native_hresult_signed']==E_NOINTERFACE and row['nc4_supported'] is False
                and row['home_getter_attempted'] is False and row['home_value_read'] is False,'Exact unsupported QI only')
        report.update(status='observed_unsupported',capability_status='observed_unsupported',
                      reason='EXACT_RETAINED_TURN_NC_OBJECT_REJECTED_PUBLIC_NC4_INTERFACE')
    else:
        require(row['capability_outcome']=='readable_pending_context_verification'
                and row['nc4_supported'] is True and row['home_value_read'] is True,'Readable raw XYZ required')
        report.update(status='review_required',capability_status='observed_readable',
                      reason='RAW_HOME_XYZ_REQUIRES_UNITS_FRAME_AND_EFFECTIVE_CL_MAPPING')
    report['native_capability_verified']=True
    return report


def inspect_turn_nc_home(sw,clsid,typelib_path,values,*,runtime_check):
    v=deepcopy(values);source,out=validate(v);classes,abi=preflight(typelib_path)
    pins=[dict(path=str(Path(p).resolve()),sha256=_file_hash(p)) for p in
          (str(source),str(typelib_path),__file__,core.__file__)]
    report=dict(scope=SCOPE,status='started',phase='preflight',request=v,read_only=True,may_continue=False,
                mutation_attempted=False,parameter_setter_attempted=False,GTP_attempted=False,GOP_attempted=False,
                save_attempted=False,model_saved=False,export_attempted=False,readback_verified=False,
                observation_verified=False,native_capability_verified=False,home_point_verified=False,
                units_verified=False,coordinate_frame_verified=False,production_qualified=False,
                editable_home_contract_verified=False,previous_scalar_parameters_reread=False,
                native_read_count=0,observations=[],pins=pins,getter_abi=abi,
                automatic_retry_permitted=False,alternate_interface_queries_permitted=False,
                bootstrap_scope='GetAddInObject/GetCWApp only before events')
    backend=NativeHome(sw,clsid,typelib_path,v,report,classes,pins,runtime_check)
    _write_receipt(out,report,create=True)
    result=core.run_read(v,report,backend,lambda:_write_receipt(out,report))
    try:classify_after_guards(result)
    except Exception as exc:
        result.update(status='error',issue=_error(exc),native_capability_verified=False)
        result.update({key:False for key in core.SUCCESS_FLAGS})
    _write_receipt(out,result)
    return result