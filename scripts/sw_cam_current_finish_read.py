"""Read missing Finish modes and leads from a current completed circular revision."""
from copy import deepcopy
from pathlib import Path
from ctypes import HRESULT,POINTER,c_double,c_int
from ctypes.wintypes import VARIANT_BOOL
from comtypes.automation import IDispatch
import math,re
from scripts import sw_cam_circular_nc_read as nc
from scripts import sw_cam_circular_reconfigure as writer
from scripts import sw_cam_reconfigured_circular_wip_binding as revision
from scripts import sw_cam_finish_lead_observation as leads
from scripts import sw_cam_finish_diagnostics as diagnostics
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_comtypes import _load_type_library
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import absolute_document_path,check_document_target,solidworks_operation_lock

SCOPE='CURRENT_FINISH_MISSING_CONTEXT_READ_V1'
MAX_READS=1536
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','revision_receipt_path','revision_receipt_sha256','revision_marker_path','revision_marker_sha256','operation_native_id','expected_feature_native_id','expected_tool_native_id','receipt_path','qualification_only','message_policy'}
OPTIONAL_KEYS={'read_scope','prior_read_receipt_path','prior_read_receipt_sha256'}
PAIRS=('GetFirstDepthCut','GetMaxDepthCut','GetSideCutAmt')
SCOPE_FLAGS=('GougeCheck','GetIsSingleCutDepth','GetToolRadiusLeadInLeadOut','LeadInOutApplyToAll')
EXTRA_IIDS={'ICWFinishMillOp':diagnostics.IIDS['ICWFinishMillOp'],'ICWFinishMillOp3':diagnostics.IIDS['ICWFinishMillOp3'],'ICWFeature':diagnostics.IIDS['ICWFeature'],'ICWLeadInOut':leads.LEAD_IID}
GETTERS=nc.GETTERS|set(PAIRS)|set(SCOPE_FLAGS)|set(leads.LEAD_FIELDS)|{'GetCWObjectFromID','OpernType','DepthProcessOpt','IGetLeadin','IGetLeadout','QueryInterface'}
require=nc.require


def inventory_projection(state):
    return [dict(native_id=r['native_id'],setup_native_id=r['setup_native_id'],mill_operation_type=r['mill_operation_type'],suppressed=r['suppressed'],toolpath_generated=r['toolpath_generated'],toolpath_record_counts=deepcopy(r['toolpath_record_counts']),tool_native_id=r['assigned_tool']['native_id']) for r in state['operations']]


def validate(v):
    require(type(v) is dict and KEYS<=set(v)<=KEYS|OPTIONAL_KEYS,'Exact current Finish read fields required')
    read_scope=v.get('read_scope','full');require(read_scope in ('full','modes_nc_only'),'Declared Finish read scope required')
    prior_path=v.get('prior_read_receipt_path');prior_sha=v.get('prior_read_receipt_sha256')
    require((prior_path is None)==(prior_sha is None),'Paired prior read receipt required')
    require(read_scope!='modes_nc_only' or prior_path is not None,'Modes-only scope requires the pinned failed lead observation')
    for key in ('process_id','operation_native_id','expected_feature_native_id','expected_tool_native_id'):require(type(v[key]) is int and 0<v[key]<2**31,'Strict explicit native identity required')
    require(type(v['expected_process_create_time']) in (int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact process lifetime required')
    require(v['qualification_only'] is True and v['message_policy']=='vendor_default','Explicit read-only qualification policy required')
    for key in ('expected_source_sha256','revision_receipt_sha256','revision_marker_sha256'):require(type(v[key]) is str and re.fullmatch('[0-9a-f]{64}',v[key]),'Exact SHA required')
    source=Path(v['expected_document_path']);require(absolute_document_path(str(source)) and source.suffix.lower()=='.sldprt' and source.is_file() and not source.is_symlink() and _file_hash(source)==v['expected_source_sha256'],'Exact current saved part required')
    r,rp=read_pin(v['revision_receipt_path'],v['revision_receipt_sha256']);mp={'path':v['revision_marker_path'],'sha256':v['revision_marker_sha256']}
    require(r.get('scope')==writer.SCOPE and r.get('status')=='review_required' and r.get('phase')=='finished','Completed current circular revision required')
    oid=r['operation_native_id'];rows=r['postCL']['expected_generated_operations'];writerpin=dict(path=writer.__file__,sha256=_file_hash(writer.__file__))
    bound=revision.bind_completed_revision(rp,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=str(source),source_sha256=v['expected_source_sha256'],selected_operation_ids=[oid],protected_operation_ids=[x['operation_native_id'] for x in rows if x['operation_native_id']!=oid],expected_generated_operations=rows,marker_pin=mp,writer_pin=writerpin)
    state=bound['snapshot'];selected=[x for x in state['operations'] if x['native_id']==v['operation_native_id']]
    require(len(selected)==1 and selected[0]['mill_operation_type']==1 and selected[0]['suppressed'] is False and selected[0]['linked_feature_ids']==[v['expected_feature_native_id']] and selected[0]['assigned_tool']['native_id']==v['expected_tool_native_id'],'Explicit saved Finish/feature/tool binding differs')
    require(len(state['operations'])<=32,'Bounded current operation table required')
    out=Path(v['receipt_path']);require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh absolute read receipt required')
    pins=deepcopy(bound['pins']);prior=None
    if prior_path is not None:
        require(read_scope=='modes_nc_only' and type(prior_sha) is str and re.fullmatch('[0-9a-f]{64}',prior_sha),'Prior limitation only accepted for modes-only read')
        prior,pp=read_pin(prior_path,prior_sha)
        require(prior.get('scope')==SCOPE and prior.get('status')=='error' and prior.get('phase')=='finished' and prior.get('read_only') is True,'Finished read-only limitation required')
        require(all(prior.get(k) is False for k in ('mutation_attempted','save_attempted','GTP_attempted','GOP_attempted','parameter_setter_attempted')),'Prior read must have no mutations')
        for key in KEYS-{'receipt_path'}:require(prior.get('request',{}).get(key)==v[key],'Prior failed read belongs to another saved authority')
        issue=prior.get('issue',{});require(issue.get('hresult')==-2147220990 and any(x.get('file')=='sw_cam_finish_lead_observation.py' and x.get('function')=='read_lead_details' for x in issue.get('locations',[])),'Exact observed lead-object limitation required')
        clean_events(prior);pins.append(pp)
    pins.extend(dict(path=p,sha256=_file_hash(p)) for p in (__file__,revision.__file__,revision.common.__file__,nc.__file__,leads.__file__,diagnostics.__file__))
    unique={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==pin['sha256'],'Conflicting evidence pins');unique[key]=pin
    pins=list(unique.values());require(len(pins)<=48 and str(out.resolve()).casefold() not in unique,'Bounded nonaliased receipt/evidence required')
    return dict(state=state,target=selected[0],pins=pins,receipt=out,bound=bound,prior_limitation=prior)


def preflight(tlb):
    classes,_=nc.preflight(tlb);library=_load_type_library(str(tlb))
    for name,iid in EXTRA_IIDS.items():
        cls=getattr(library,name);require(str(cls._iid_).upper()==iid,'Exact declared Finish/lead IID required');classes[name]=cls
    specs=[]
    for name,dispid in zip(PAIRS,(94,96,80)):specs.append(('ICWFinishMillOp3',name,dispid,(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,2)))
    for name,dispid,flags in (('GougeCheck',130,(10,)),('GetIsSingleCutDepth',104,(2,)),('GetToolRadiusLeadInLeadOut',125,(10,)),('LeadInOutApplyToAll',129,(10,))):specs.append(('ICWFinishMillOp3',('_get_'+name if name in ('GougeCheck','LeadInOutApplyToAll') else name),dispid,(POINTER(VARIANT_BOOL),),flags))
    specs.append(('ICWFinishMillOp','_get_DepthProcessOpt',19,(POINTER(c_int),),(10,)))
    for name,dispid in (('IGetLeadin',28),('IGetLeadout',29)):specs.append(('ICWFinishMillOp',name,dispid,(POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10)))
    for name,dispid,kind in (('LeadType',1,c_int),('LeadAngle',3,c_double),('ArcAngle',6,c_double),('SidePassType',7,c_int),('CutDepthType',8,c_int),('StartAngle',26,c_double)):specs.append(('ICWLeadInOut','_get_'+name,dispid,(POINTER(kind),),(10,)))
    specs.extend([('ICWLeadInOut','GetIsSameLeadinout',16,(POINTER(VARIANT_BOOL),),(2,)),('ICWLeadInOut','GetFeedRate',18,(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,2))])
    for name,dispid in (('GetArcRadius2',20),('GetLeadOverlap2',22),('GetLeadAmt2',24)):specs.append(('ICWLeadInOut',name,dispid,(POINTER(c_double),POINTER(VARIANT_BOOL),POINTER(c_double)),(2,2,2)))
    for owner,name,dispid,args,flags in specs:
        methods=[m for m in classes[owner]._methods_ if m.name==name];require(len(methods)==1,'Unique exact Finish getter required');m=methods[0];require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args and tuple(x[0] for x in m.paramflags)==flags,'Finish getter ABI differs')
    return classes,dict(native_calls=0,application_connections=0,finish_lead_getter_count=len(specs),getters_only=True)


def capture(app,loaded,v,read,typed,pointer,boundary,progress=None):
    observation=dict(operation_native_id=v['operation_native_id'],feature_native_id=v['expected_feature_native_id'],tool_native_id=v['expected_tool_native_id'],read_scope=v.get('read_scope','full'),capture_complete=False,observation_groups=[],leads=dict(status='not_observed',reason='NOT_REQUESTED_IN_MODES_NC_ONLY' if v.get('read_scope')=='modes_nc_only' else 'PENDING_FULL_SCOPE_READ'),units_verified=False,lead_geometry_qualified=False,cutting_conditions_qualified=False)
    def save_group(name,**values):
        observation.update(values);observation['observation_groups'].append(name)
        if progress is not None:progress(deepcopy(observation))
    boundary();doc=typed(read(app,'IGetActiveDoc'),'ICWDoc3');part=typed(doc,'ICWPartDoc');machine=typed(read(part,'IGetMachine'),'ICWMachine');require(read(machine,'MachType')==1,'Current MILL required')
    rows=[];chosen=None
    for rawsetup in _items(read(machine,'IGetEnumOpSetups'),typed,read,8):
        setup=typed(rawsetup,'ICWBaseOpSetup');sid=_object_id(doc,rawsetup,read)
        for raw in _items(read(setup,'IGetEnumOperations'),typed,read,32):
            require(len(rows)<32,'At most32 operations');op=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation');oid=_object_id(doc,raw,read);kind=read(mill,'OpernType');suppressed=read(op,'Suppressed');generated=read(op,'GetIsToolpathGenerated');require(type(kind) is int and type(suppressed) is bool and type(generated) is bool,'Strict operation type/flags required')
            counts=[]
            for rawpath in _items(read(op,'IGetEnumToolpaths'),typed,read,1):
                count=read(typed(rawpath,'ICWToolpath'),'RecordCount');require(type(count) is int and 0<count<=100000,'One positive bounded path required');counts.append(count)
            require(generated is bool(counts),'Generated count mismatch');tool=typed(read(op,'IGetTool'),'ICWTool');tid=_object_id(doc,tool,read);rows.append(dict(native_id=oid,setup_native_id=sid,mill_operation_type=kind,suppressed=suppressed,toolpath_generated=generated,toolpath_record_counts=counts,tool_native_id=tid))
            if oid==v['operation_native_id']:require(chosen is None,'Unique selected Finish required');chosen=op
    require(rows==inventory_projection(loaded['state']) and chosen is not None,'Current full operation table differs from completed saved authority')
    save_group('inventory',inventory=rows)
    links=[_object_id(doc,x,read) for x in _items(read(chosen,'IGetAllFeatures'),typed,read,2)];require(links==[v['expected_feature_native_id']],'Selected Finish feature link changed')
    require(read(typed(chosen,'ICWMillOperation'),'OpernType')==1,'Only explicit Finish operation allowed')
    finish=typed(chosen,'ICWFinishMillOp');finish3=typed(chosen,'ICWFinishMillOp3')
    pairs={name:diagnostics._scalar(read(finish3,name),'double_bool') for name in PAIRS}
    save_group('depth_and_side_pairs',depth_and_side_pairs=pairs)
    flags={name:diagnostics._scalar(read(finish3,name),'bool') for name in SCOPE_FLAGS};flags['DepthProcessOpt']=diagnostics._scalar(read(finish,'DepthProcessOpt'),'long')
    save_group('finish_scope',finish_scope=flags)
    raw=read(typed(chosen,'ICWMillOperation'),'IGetNCParam');nc1=typed(raw,'ICWNCParam');nc2=typed(raw,'ICWNCParam2');nc4=typed(raw,'ICWNCParam4')
    cutting={name:read(nc1,name) for name in ('GetSpndlSpeed','GetCNCComp','GetTlpComp')};cutting['XYFeed']=read(nc2,'XYFeed')
    for name in ('GetSpeedFeedMethod','LinkToTool','GetIsLockSpindleSpeed','GetZFeedrate2','GetLeadinFeedratePercent'):cutting[name]=read(nc4,name)
    for name in ('GetSpndlSpeed','XYFeed','GetLeadinFeedratePercent'):cutting[name]=nc.finite(cutting[name])
    for name in ('GetCNCComp','GetTlpComp','GetSpeedFeedMethod'):require(type(cutting[name]) is int,'Strict NC enum required')
    require(cutting['GetSpeedFeedMethod'] in (0,1,2),'Declared NC method required')
    for name in ('LinkToTool','GetIsLockSpindleSpeed'):require(type(cutting[name]) is bool,'Strict NC flag required')
    cutting['GetZFeedrate2']=diagnostics._scalar(cutting['GetZFeedrate2'],'double_bool');detail={};cutting['leadin_feed']=pointer(nc1,detail)
    save_group('nc',nc=cutting,leadin_pointer_diagnostic=detail)
    if v.get('read_scope','full')=='full':
        found=read(doc,'GetCWObjectFromID',1,v['expected_feature_native_id']);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True and _object_id(doc,found[0],read)==v['expected_feature_native_id'],'Exact feature required');feature=read(found[0],'QueryInterface',IDispatch)
        lead_values=leads.read_lead_details(chosen,feature,read=read,typed=typed,lead_typed=lambda raw:typed(raw,'ICWLeadInOut'))
        save_group('leads',leads=lead_values)
    boundary();observation['capture_complete']=True;return observation


def finalize_runtime_failure(result,error):
    result.update(status='error',phase='finished',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,source_unchanged=False,production_qualified=False)
    _write_receipt(Path(result['receipt_path']),result);return result


def dispatch(sw,clsid,tlb,*,runtime_check,**v):
    loaded=validate(v);classes,abi=preflight(tlb);session=None
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),receipt_path=v['receipt_path'],authority_binding_sha256=loaded['bound']['binding_sha256'],evidence_pins=deepcopy(loaded['pins']),abi=abi,native_read_count=0,native_read_limit=MAX_READS,read_only=True,mutation_attempted=False,save_attempted=False,GTP_attempted=False,GOP_attempted=False,parameter_setter_attempted=False,readback_verified=False,source_unchanged=False,runtime_unchanged=False,production_qualified=False)
    def persist():_write_receipt(loaded['receipt'],r)
    _write_receipt(loaded['receipt'],r,create=True)
    try:
        def identity():
            runtime_check();p=_process_identity(v['process_id']);require(p.get('alive') is True and p.get('process_id')==v['process_id'] and p.get('create_time')==v['expected_process_create_time'] and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact owned lifetime required');pid=_member(sw,'GetProcessID');require(type(pid) is int and pid==v['process_id'],'Selected process changed');d=document_snapshot(sw);require(type(d) is dict and d.get('type')==1 and d.get('needs_save') is False,'Current clean saved part required');check_document_target(d['path'],d['title'],expected_path=v['expected_document_path'],required=True);require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Saved source changed')
            for pin in loaded['pins']:require(_file_hash(pin['path'])==pin['sha256'],'Current authority or implementation changed')
            return d
        with solidworks_operation_lock(timeout_seconds=1,process_id=v['process_id']):
            initial=identity();require(initial==loaded['state']['document'],'Document differs from completed saved authority');addin=_member(sw,'GetAddInObject',clsid);require(addin is not None,'CAM must already be loaded');app=_typed(_member(addin,'GetCWApp'),'ICWApp4',tlb);require(identity()==initial,'Identity changed in bootstrap');session=CamMessageSession(app,tlb)
            def check():
                summary=session.summary();r['messages']=summary;require(summary.get('active') is True and summary.get('subscribed') is True and not any(summary.get(k) for k in nc.EVENT_ERRORS),'CAM event requires stop')
            def boundary():check();require(identity()==initial,'Current document changed');check()
            def admission(name):check();require(r['native_read_count']<MAX_READS,'Read budget exhausted');r['native_read_count']+=1;r['phase']=name
            def read(owner,name,*args):
                require(name in GETTERS and not (v.get('read_scope')=='modes_nc_only' and name in ('IGetLeadin','IGetLeadout')),'Getter outside fixed Finish scope');admission(name);r['last_attempted_read']=name
                try:value=_member(owner,name,*args)
                except Exception:r['failed_read']=name;raise
                r['last_returned_read']=name;check();return value
            def typed(owner,name):
                require(name in classes and not (v.get('read_scope')=='modes_nc_only' and name=='ICWLeadInOut'),'Interface outside fixed Finish scope');admission('QI '+name);value=owner.QueryInterface(classes[name]);require(value is not None and bool(value) and isinstance(value,POINTER(classes[name])),'Exact typed pointer required');check();return value
            def pointer(owner,detail):
                admission('GetLeadinFeedrate');r.setdefault('pointer_attempts',[]).append(detail);persist()
                try:return nc.lead_pointer_value(owner,detail)
                finally:check();persist()
            with session:
                for label in ('before','after'):
                    r['phase']=label;persist()
                    def progress(observation):r[label]=observation;persist()
                    r[label]=capture(app,loaded,v,read,typed,pointer,boundary,progress=progress);persist()
                require(r['before']==r['after'],'Two complete Finish observations differ');boundary()
            r['messages']=session.summary();clean_events(r);require(identity()==initial,'Document changed after cleanup');runtime_check();r.update(status='review_required',phase='finished',readback_verified=True,source_unchanged=True,runtime_unchanged=True,source_sha256=v['expected_source_sha256'],reason='CURRENT_FINISH_MODES_AND_NC_OBSERVED_LEAD_GEOMETRY_NOT_OBSERVED' if v.get('read_scope')=='modes_nc_only' else 'CURRENT_FINISH_MODES_LEADS_AND_NC_OBSERVED_WITHOUT_MUTATION')
    except Exception as error:r.update(status='error',failed_phase=r.get('phase'),phase='finished',issue=_error(error),readback_verified=False,source_unchanged=False,runtime_unchanged=False)
    finally:
        if session is not None:r['messages']=session.summary()
        persist()
    return r
