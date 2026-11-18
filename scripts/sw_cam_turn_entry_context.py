"""Bounded TURN FACE entry observation; public getters only, never a home setter."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math
import re

from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_comtypes import _load_type_library
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _items, _inventory
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path, check_document_target

SCOPE = 'TURN_FACE_ENTRY_CONTEXT_READ_V1'
EVENT_ERRORS = ('event_count', 'overflow', 'callback_errors', 'callback_error_count', 'subscription_error', 'disconnect_errors')
FACE = {7: 'ICWTurnFaceRoughOp', 8: 'ICWTurnFaceFinishOp'}
IIDS = {'ICWOperation': '{4EDDCA73-325A-11D6-A9A7-00062999E55F}',
        'ICWTurnOperation': '{4EDDCA75-325A-11D6-A9A7-00062999E55F}',
        'ICWTurnNCParam': '{908023A2-B845-4C64-A395-5EF667E7DE68}',
        FACE[7]: '{F718FA09-51FB-4DEF-B34E-4273BB67D826}',
        FACE[8]: '{ECD5B894-DBDD-4D36-AC63-C1A49554A4F8}'}
DOUBLE_PROPS = {7: {'FirstCutAmt':13, 'MaxCutAmt':14, 'FinalCutAmt':15, 'StepInAngle':16,
                   'StepInAmt':17, 'StepOutAngle':18, 'StepOutAmt':19, 'RadialStockAmt':29, 'AxialStockAmt':30},
                8: {'PrevAllowance':13, 'FirstCutAmt':14, 'MaxCutAmt':15, 'FinalCutAmt':16,
                    'StepInAngle':17, 'StepInAmt':18, 'StepOutAngle':19, 'StepOutAmt':20,
                    'RadialStockAmt':31, 'AxialStockAmt':32}}
BOOL_PROPS = {7: {'ProgramPoint_FeatureGeometry':27},
              8: {'ProgramPoint_FeatureGeometry':29, 'ProgramPoint_FeatureGeometry_GougeCheck':30}}
READ_MEMBERS = {'IGetActiveDoc','GetDocType','IGetMachine','MachType','IGetEnumSetups',
                'IGetEnumFeatures','Count','Item','IGetEnumOpSetups','IGetEnumOperations',
                'GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','OpernType',
                'IGetWorkpiece','GetTurnWorkpieceType','GetCWObjectID','IGetAllFeatures',
                'QueryInterface','GetNumPostParam','GetPostParam','GetCannedCycleOutput',
                'GetCannedCycleStartPoint','IGetTurnNCParam','GetSpndlSpeed','GetFeedRateIPM'}
READ_MEMBERS |= set().union(*(set(x) for x in DOUBLE_PROPS.values()), *(set(x) for x in BOOL_PROPS.values()))
SUCCESS_FLAGS = ('readback_verified','observation_verified','saved_source_unchanged','runtime_unchanged','inventory_unchanged')
FIELDS = {'process_id','expected_process_create_time','expected_document_path','expected_source_sha256',
          'expected_feature_count','expected_operation_count','expected_operation_setup_count',
          'expected_generated_operation_count','expected_total_record_count','targets','receipt_path',
          'qualification_only','message_policy','post_parameter_index_policy'}
TARGET_FIELDS = {'operation_native_id','feature_native_id','setup_index','operation_index','operation_type'}


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, 'Invalid strict integer: '+label)
    return value


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite native DOUBLE required')
    return float(value)


def boolean(value):
    require(type(value) is bool, 'Strict native Boolean required')
    return value


def validate(v):
    require(type(v) is dict and set(v) == FIELDS, 'Exact read-only request fields required')
    for key, lo, hi in [('process_id',1,2**32-1),('expected_feature_count',1,64),
                       ('expected_operation_count',1,64),('expected_operation_setup_count',1,8),
                       ('expected_generated_operation_count',0,64),('expected_total_record_count',0,1000000)]:
        integer(v[key],lo,hi,key)
    require(number(v['expected_process_create_time'])>0, 'Positive exact process lifetime required')
    require(v['expected_generated_operation_count']<=v['expected_operation_count'], 'Generated count exceeds operation count')
    require(v['qualification_only'] is True and v['message_policy']=='vendor_default', 'Qualification vendor_default policy required')
    require(v['post_parameter_index_policy']=='probe_zero_through_count_inclusive', 'Explicit bounded index probes required')
    require(type(v['expected_source_sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['expected_source_sha256']), 'Exact source SHA required')
    source=Path(v['expected_document_path'])
    require(absolute_document_path(str(source)) and source.suffix.lower()=='.sldprt' and source.is_file()
            and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'], 'Current saved source differs')
    targets=v['targets']
    require(type(targets) is list and 1<=len(targets)<=2, 'One or two FACE targets required')
    ids=[]; positions=[]
    for target in targets:
        require(type(target) is dict and set(target)==TARGET_FIELDS, 'Exact FACE selector fields required')
        for k in ('operation_native_id','feature_native_id'):integer(target[k],1,2**32-1,k)
        integer(target['setup_index'],0,v['expected_operation_setup_count']-1,'setup_index')
        integer(target['operation_index'],0,63,'operation_index')
        require(type(target['operation_type']) is int and target['operation_type'] in FACE,'Only FACE7/8 supported')
        ids.append(target['operation_native_id']);positions.append((target['setup_index'],target['operation_index']))
    require(len(set(ids))==len(ids) and len(set(positions))==len(positions), 'Unique target IDs/positions required')
    out=Path(v['receipt_path'])
    require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir()
            and not out.exists() and not out.is_symlink() and out.resolve()!=source.resolve(), 'Fresh absolute receipt required')
    return source, out


def preflight(typelib_path):
    """Exact public typelib ABI only; no application, activation or native getter."""
    from ctypes import HRESULT, POINTER, c_int, c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes import BSTR
    from comtypes.automation import IDispatch
    lib=_load_type_library(str(typelib_path))
    classes={name:getattr(lib,name) for name in IIDS}
    for name,iid in IIDS.items():require(str(classes[name]._iid_).upper()==iid,'Interface IID mismatch: '+name)
    specs=[('ICWOperation','GetNumPostParam',20,(POINTER(c_int),),(10,),False),
           ('ICWOperation','GetPostParam',21,(c_int,POINTER(BSTR),POINTER(BSTR),POINTER(VARIANT_BOOL)),(1,2,2,10),False),
           ('ICWTurnOperation','IGetTurnNCParam',4,(POINTER(POINTER(IDispatch)),),(10,),False),
           ('ICWTurnOperation','GetCannedCycleOutput',10,(POINTER(VARIANT_BOOL),),(10,),False),
           ('ICWTurnOperation','GetCannedCycleStartPoint',12,(POINTER(c_int),POINTER(c_double),POINTER(c_double)),(2,2,2),False),
           ('ICWTurnNCParam','GetSpndlSpeed',1,(POINTER(c_double),),(10,),False),
           ('ICWTurnNCParam','GetFeedRateIPM',3,(POINTER(c_double),),(10,),False)]
    for kind, owner in FACE.items():
        for name,disp in DOUBLE_PROPS[kind].items():specs.append((owner,'_get_'+name,disp,(POINTER(c_double),),(10,),True))
        for name,disp in BOOL_PROPS[kind].items():specs.append((owner,'_get_'+name,disp,(POINTER(VARIANT_BOOL),),(10,),True))
    for owner,name,disp,args,flags,prop in specs:
        methods=[m for m in classes[owner]._methods_ if m.name==name]
        require(len(methods)==1,'Unique getter required: '+owner+'.'+name)
        m=methods[0]
        require(m.restype is HRESULT and m.idlflags[0]==disp and m.argtypes==args
                and tuple(x[0] for x in m.paramflags)==flags and ('propget'in m.idlflags)==prop
                and 'propput'not in m.idlflags and 'propputref'not in m.idlflags,'Getter ABI mismatch: '+owner+'.'+name)
    return classes,dict(interfaces=IIDS,getter_count=len(specs),native_calls=0,application_connections=0)


def post_parameter(raw,index):
    require(type(raw) in (tuple,list) and len(raw)==3 and type(raw[2]) is bool,
            'GetPostParam requires name/value/strict found Boolean')
    require(all(x is None or type(x) is str and len(x)<=4096 for x in raw[:2]),'Bounded BSTR OUTs required')
    row=dict(index=index,found=raw[2],name_raw=raw[0],value_raw=raw[1])
    if raw[2]:require(type(raw[0]) is str and bool(raw[0].strip()) and type(raw[1]) is str,'Found parameter must have actual nonempty name and BSTR value')
    return row


def observe(op,turn,face,nc,kind,read,progress):
    """Explicit count-bounded probes; no index-base, parameter-name or home inference."""
    row=dict(post_parameter_probes=[],catalog_complete=False,index_base_verified=False,
             home_point_verified=False,preset_values_verified=False,units_verified=False,
             canned_cycle_is_general_home=False,face_interface=FACE[kind],face_parameters={})
    progress(row)
    count=integer(read(op,'GetNumPostParam'),0,32,'post parameter count')
    row['post_parameter_count_native']=count;progress(row)
    # Count zero needs no probe; positive counts request both possible end boundaries.
    for index in range(count+1 if count else 0):
        row['post_parameter_probes'].append(post_parameter(read(op,'GetPostParam',index),index));progress(row)
    row['actual_named_parameters']=[deepcopy(x) for x in row['post_parameter_probes'] if x['found']]
    row['canned_cycle_output_raw']=boolean(read(turn,'GetCannedCycleOutput'));progress(row)
    value=read(turn,'GetCannedCycleStartPoint')
    require(type(value) in (tuple,list) and len(value)==3,'Canned-cycle enum/X/Z triple required')
    row['canned_cycle_start_raw']=dict(method=integer(value[0],-2**31,2**31-1,'canned-cycle enum'),X=number(value[1]),Z=number(value[2]));progress(row)
    for name in DOUBLE_PROPS[kind]:row['face_parameters'][name]=number(read(face,name));progress(row)
    for name in BOOL_PROPS[kind]:row['face_parameters'][name]=boolean(read(face,name));progress(row)
    row['turn_nc_raw']={'GetSpndlSpeed':number(read(nc,'GetSpndlSpeed')),'GetFeedRateIPM':number(read(nc,'GetFeedRateIPM'))}
    row['cutting_mode_semantics_verified']=False;row['complete']=True;progress(row)
    return row


class NativeRead:
    def __init__(self,sw,clsid,tlb,v,report,classes,pins,runtime_check):
        self.sw,self.clsid,self.tlb,self.v,self.report=sw,clsid,tlb,v,report
        self.classes,self.pins,self.runtime_check=classes,pins,runtime_check
        self.session=None;self.closed=False;self.initial=None

    def boundary(self):
        self.runtime_check()
        for pin in self.pins:require(_file_hash(pin['path'])==pin['sha256'],'Pinned source/runtime changed: '+pin['path'])
        p=_process_identity(self.v['process_id'])
        require(p.get('alive') is True and p.get('process_id')==self.v['process_id']
                and p.get('create_time')==self.v['expected_process_create_time']
                and Path(p.get('executable','')).name.casefold()=='sldworks.exe','Owned SOLIDWORKS lifetime changed')
        pid=_member(self.sw,'GetProcessID')
        require(type(pid) is int and pid==self.v['process_id'],'Owned application PID differs')
        d=document_snapshot(self.sw)
        require(isinstance(d,dict) and d.get('type')==1 and d.get('needs_save') is False,'Clean saved part required')
        check_document_target(d['path'],d['title'],expected_path=self.v['expected_document_path'],required=True)
        require(self.initial is None or d==self.initial,'Active document state changed')
        return d

    def check(self):
        m=self.session.summary();self.report['messages']=m
        require(m.get('active') and m.get('subscribed') and not any(m.get(k) for k in EVENT_ERRORS),'CAM events require review')

    def read(self,obj,name,*args):
        require(name in READ_MEMBERS,'Getter allowlist violation: '+str(name))
        if name=='QueryInterface':
            require(len(args)==1 and any(args[0] is self.classes[x] for x in FACE.values()),'Only preflighted FACE QI allowed')
        self.check();self.report['phase']=name;self.report['native_read_count']+=1
        require(self.report['native_read_count']<=4096,'Native read bound exceeded')
        value=_member(obj,name,*args);self.check();return value

    def start(self):
        self.initial=self.boundary()
        addin=_member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM already loaded required')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.tlb)
        self.session=CamMessageSession(app,self.tlb);self.session.__enter__();self.check()
        active=self.read(app,'IGetActiveDoc');self.doc=_typed(active,'ICWDoc3',self.tlb)
        require(self.read(self.doc,'GetDocType')==1,'CAM part required')
        part=_typed(active,'ICWPartDoc',self.tlb);self.machine=_typed(self.read(part,'IGetMachine'),'ICWMachine',self.tlb)
        require(self.read(self.machine,'MachType')==3,'TURN machine required')
        self.boundary()

    def capture(self):
        self.boundary();self.check()
        inv=_inventory(self.machine,self.tlb,self.read,max_features=64,max_operations=64,max_setups=8)
        for key in ('feature_count','operation_count','operation_setup_count'):require(inv[key]==self.v['expected_'+key],'Inventory count differs: '+key)
        ops=inv['operations'];require(sum(x['toolpath_generated'] is True for x in ops)==self.v['expected_generated_operation_count'],'Generated count changed')
        require(sum(sum(x['toolpath_record_counts']) for x in ops)==self.v['expected_total_record_count'],'Record count changed')
        identities=[];handles={}
        for si,rawsetup in enumerate(_items(self.read(self.machine,'IGetEnumOpSetups'),self.tlb,self.read,limit=8)):
            setup=_typed(rawsetup,'ICWBaseOpSetup',self.tlb)
            for oi,raw in enumerate(_items(self.read(setup,'IGetEnumOperations'),self.tlb,self.read,limit=64-len(identities))):
                op=_typed(raw,'ICWOperation',self.tlb);oid=_object_id(self.doc,op,self.read)
                links=[_object_id(self.doc,x,self.read) for x in _items(self.read(op,'IGetAllFeatures'),self.tlb,self.read,limit=64)]
                identities.append(dict(setup_index=si,operation_index=oi,native_id=oid,linked_feature_ids=links))
                handles[oid]=op
        require(len(identities)==len(ops) and len(handles)==len(ops),'Unique complete native inventory required')
        for a,b in zip(identities,ops):require((a['setup_index'],a['operation_index'])==(b['setup_index'],b['operation_index']),'Native traversal order differs')
        for target in self.v['targets']:
            matches=[(a,b) for a,b in zip(identities,ops) if a['native_id']==target['operation_native_id']]
            require(len(matches)==1,'Selected native ID missing')
            a,b=matches[0]
            require(a['setup_index']==target['setup_index'] and a['operation_index']==target['operation_index']
                    and a['linked_feature_ids']==[target['feature_native_id']] and b['turn_operation_type']==target['operation_type'],'Selected FACE identity/type/feature differs')
        self.handles=handles;self.boundary();self.check()
        return dict(document=deepcopy(self.initial),source_sha256=self.v['expected_source_sha256'],inventory=inv,operation_identities=identities)

    def selected(self,target,progress):
        self.boundary();op=self.handles[target['operation_native_id']]
        turn=_typed(op,'ICWTurnOperation',self.tlb)
        face=self.read(op,'QueryInterface',self.classes[FACE[target['operation_type']]])
        nc=_typed(self.read(turn,'IGetTurnNCParam'),'ICWTurnNCParam',self.tlb)
        result=observe(op,turn,face,nc,target['operation_type'],self.read,progress)
        self.boundary();return result

    def finish(self):
        if self.session is not None and not self.closed:
            self.closed=True;self.session.__exit__(None,None,None)
        if self.session is not None:
            m=self.session.summary();self.report['messages']=m
            require(m.get('disconnected') is True and not m.get('active') and not any(m.get(k) for k in EVENT_ERRORS),'Clean event disconnect required')


def run_read(v,report,backend,publish):
    """Single context, complete before/after inventory, terminal read-only failure receipts."""
    try:
        backend.start();report['before']=backend.capture();publish()
        for target in v['targets']:
            observation={'target':deepcopy(target),'complete':False};report['observations'].append(observation)
            def progress(values):observation.update(deepcopy(values));publish()
            backend.selected(target,progress)
        report['after']=backend.capture()
        require(report['before']==report['after'],'Before/after full inventory or identities changed')
        backend.finish();backend.boundary()
        report.update(status='review_required',phase='finished',readback_verified=True,observation_verified=True,
                      saved_source_unchanged=True,runtime_unchanged=True,inventory_unchanged=True,
                      reason='RAW_FACE_ENTRY_CONTEXT_REQUIRES_SEMANTIC_REVIEW')
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,observation_verified=False)
    finally:
        try:backend.finish()
        except Exception as exc:report.update(status='error',phase='finished',cleanup_issue=_error(exc),readback_verified=False,observation_verified=False)
        if report['status']=='error':
            report.update({key:False for key in SUCCESS_FLAGS})
        publish()
    return report


def inspect_turn_entry_context(sw,clsid,typelib_path,values,*,runtime_check=lambda:None):
    """Caller owns the existing selected-PID lock; no connection, load, save or generation."""
    v=deepcopy(values);source,out=validate(v);classes,abi=preflight(typelib_path)
    import scripts.sw_cam_comtypes as comtypes_helper
    import scripts.sw_cam_turn_feature_attribute as inventory_helper
    import scripts.sw_cam_events as events_helper
    files=[str(source),str(Path(typelib_path)),__file__,comtypes_helper.__file__,inventory_helper.__file__,events_helper.__file__]
    pins=[dict(path=str(Path(p).resolve()),sha256=_file_hash(p)) for p in files]
    report=dict(scope=SCOPE,status='started',phase='preflight',request=v,read_only=True,may_continue=False,
                mutation_attempted=False,parameter_setter_attempted=False,GTP_attempted=False,GOP_attempted=False,
                save_attempted=False,model_saved=False,export_attempted=False,readback_verified=False,
                observation_verified=False,catalog_complete=False,home_point_verified=False,
                units_verified=False,coordinate_frame_verified=False,production_qualified=False,
                native_read_count=0,observations=[],pins=pins,getter_abi=abi,
                automatic_retry_permitted=False,bootstrap_scope='GetAddInObject/GetCWApp only before events')
    backend=NativeRead(sw,clsid,typelib_path,v,report,classes,pins,runtime_check)
    _write_receipt(out,report,create=True)
    return run_read(v,report,backend,lambda:_write_receipt(out,report))