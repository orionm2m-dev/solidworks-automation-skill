"""Observe a failed configured depth twice in the same owned RAM session; never write."""
from copy import deepcopy
from pathlib import Path
from ctypes import HRESULT,POINTER,c_double
from ctypes.wintypes import VARIANT_BOOL
from comtypes.automation import IDispatch
import math,re
from scripts import sw_cam_saved_floor_wall_configure as writer
from scripts import sw_cam_saved_finish_pair_read as shared
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_generation import _write_receipt,_typed
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import check_document_target,solidworks_operation_lock
require=writer.require;exact=writer.exact;common=shared.ancestry.common
SCOPE='FAILED_CONFIGURATION_DEPTH_OBSERVATION_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','failure_receipt_path','failure_receipt_sha256','failure_marker_path','failure_marker_sha256','receipt_path','qualification_only','message_policy'}
GETTERS={'IGetActiveDoc','GetCWObjectFromID','GetCWObjectID','OpernType','Suppressed','GetIsToolpathGenerated','IGetEnumToolpaths','IGetAllFeatures','IGetTool','GetMachiningDepth','GetMachiningDepthValue','GetOverrideMachiningDepth','Count','Item'}
INTERFACES={'ICWApp4','ICWDoc3','ICWOperation','ICWMillOperation','ICWMillOperation3','ICWTool','ICWDispatchCollection'}
MAX_READS=128


def validate_failure(r,marker,v):
    require(r.get('scope')==writer.SCOPE and r.get('status')=='uncertain'and r.get('phase')=='finished'and r.get('reason')=='Immediate field readback differs','Exact terminal depth-readback failure required')
    require(r.get('issue',{}).get('type')=='ValueError'and not any(k in r for k in('cleanup_error','runtime_error','receipt_write_error')),'Unresolved native transport or cleanup failure')
    require(r.get('mutation_attempted')is True and r.get('marker_created')is True and r.get('native_dispatch_pending')is False,'Completed partial mutation required')
    for key in('save_attempted','GTP_attempted','GOP_attempted','AFR_attempted','CL_export_attempted','model_saved','configuration_saved','parameters_configured','operation_creation_attempted','tool_edit_attempted'):
        require(r.get(key)is False,'Unexpected failure authority fact: '+key)
    require(not r.get('source_after_sha256')and not r.get('saved_file_sha256'),'No later Save may be assumed');clean_events(r)
    req=r['request']
    for key in('process_id','expected_process_create_time','expected_source_sha256'):require(exact(req[key],v[key]),'Failure owner/source differs: '+key)
    require(common.same_path(req['expected_document_path'],v['expected_document_path'])and r['source_before_sha256']==v['expected_source_sha256'],'Exact original saved source required')
    require(common.same_path(r['receipt_path'],v['failure_receipt_path'])and common.same_path(r['dispatch_marker_path'],v['failure_marker_path']),'Failure receipt/marker path differs')
    actions=r['actions'];allowed=writer.action_names(r['recipe']);names=list(actions)
    require(r['allowed_actions']==allowed and names and names==allowed[:len(names)]and len(names)<len(allowed),'Exact completed prefix before Save required')
    failed=r['failed_phase'];match=re.fullmatch(r'field:([1-9][0-9]*):machining_depth',failed)
    require(match is not None and names[-1]==failed,'Only the last returned depth write may be inspected');oid=int(match.group(1))
    rows=[x for x in r['recipe']['rows']if x['operation_native_id']==oid];require(len(rows)==1 and rows[0]['operation_kind']==1,'One exact Finish depth target required');row=rows[0]
    change=next(x for x in row['changes']if x['field']=='machining_depth')
    require(type(change['new'])is float and math.isfinite(change['new']),'Finite requested depth required')
    for name,a in actions.items():
        require(a.get('attempted')is True and a.get('returned')is True and a.get('native_dispatch_pending')is False and a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0,'Exact completed setter prefix required')
        if name.startswith('field:')and name!=failed:
            _,idtext,key=name.split(':');definition=next(x for x in r['recipe']['rows']if x['operation_native_id']==int(idtext));c=next(x for x in definition['changes']if x['field']==key)
            require('immediate_readback'in a and exact(a['immediate_readback'],c['new']),'Earlier returned field lacks exact readback')
    require('immediate_readback'not in actions[failed]and 'SetTool:'+str(oid)in actions,'Only unrecorded final readback after an observed tool assignment supported')
    require(row['existing_tool_native_id']==r['before']['parameter_batch']['candidate_tool']['generic']['native_id'],'Actual existing candidate tool required')
    old=next(x for x in r['before']['operations']if x['native_id']==oid)
    require(old['mill_operation_type']==1 and old['linked_feature_ids']==[row['feature_native_id']]and old['toolpath_generated']is False and old['toolpath_record_counts']==[],'Originally empty exact target required')
    expected=dict(scope=writer.SCOPE,status='uncertain',phase='finished',recipe_pin=r['recipe_pin'],read_authority_pin=r['read_authority_pin'],source_before_sha256=r['source_before_sha256'],receipt_path=v['failure_receipt_path'],receipt_sha256=v['failure_receipt_sha256'],automatic_replay=False)
    normalized=deepcopy(marker);require(common.same_path(normalized.get('receipt_path',''),v['failure_receipt_path']),'Consumed marker receipt path differs');normalized['receipt_path']=v['failure_receipt_path'];require(exact(normalized,expected),'Exact failure marker required')
    return dict(operation_native_id=oid,feature_native_id=row['feature_native_id'],operation_kind=1,tool_native_id=row['existing_tool_native_id'],requested_depth=change['new'],requested_depth_hex=change['new'].hex(),completed_action_count=len(names),full_configuration_reconciled=False)


def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact partial-depth read request required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit read-only qualification required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owner/lifetime required')
    for key,value in v.items():
        if key.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
        if key.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
    source=Path(v['expected_document_path']);require(source.suffix.lower()=='.sldprt'and source.is_file()and not source.is_symlink()and _file_hash(source)==v['expected_source_sha256'],'Exact unchanged saved part required')
    r,rp=read_pin(v['failure_receipt_path'],v['failure_receipt_sha256']);m,mp=read_pin(v['failure_marker_path'],v['failure_marker_sha256']);target=validate_failure(r,m,v)
    recipe,recipe_pin=read_pin(r['recipe_pin']['path'],r['recipe_pin']['sha256']);require(exact(recipe,r['recipe']),'Pinned original recipe differs')
    module_pin=dict(path=writer.__file__,sha256=_file_hash(writer.__file__))
    require(any(common.same_path(p['path'],module_pin['path'])and p['sha256']==module_pin['sha256']for p in r['evidence_pins']),'Original writer implementation must remain pinned')
    out=Path(v['receipt_path']);pins=[rp,mp,recipe_pin,module_pin,dict(path=__file__,sha256=_file_hash(__file__))]
    require(out.suffix.lower()=='.json'and out.parent.is_dir()and not out.exists()and not out.is_symlink(),'Fresh JSON result required')
    require(out.resolve()not in{source.resolve(),*(Path(p['path']).resolve()for p in pins)},'Result may not alias evidence or source')
    return dict(target=target,pins=pins,output=out,failure=r,failure_pin=rp,marker_pin=mp)


def preflight(tlb):
    classes={name:_interface_class(name,tlb)for name in INTERFACES};classes['IDispatch']=IDispatch
    specs=[('ICWMillOperation','GetMachiningDepth',4,c_double),('ICWMillOperation3','GetMachiningDepthValue',51,c_double),('ICWMillOperation3','GetOverrideMachiningDepth',34,VARIANT_BOOL)]
    for interface,name,dispid,result in specs:
        methods=[x for x in classes[interface]._methods_ if x.name==name];require(len(methods)==1,'One exact getter required');m=methods[0]
        require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==(POINTER(IDispatch),POINTER(result))and tuple(x[0]for x in m.paramflags)==(1,10),'Depth getter ABI differs: '+name)
    return classes


def depth_values(operation,feature,read,typed,persist,out):
    dispatch=typed(feature,'IDispatch');mill=typed(operation,'ICWMillOperation');mill3=typed(operation,'ICWMillOperation3')
    for owner,name in((mill,'GetMachiningDepth'),(mill3,'GetMachiningDepthValue'),(mill3,'GetOverrideMachiningDepth')):
        value=read(owner,name,dispatch)
        # Persist the complete primitive before semantic validation or a later call.
        out[name]=dict(value=value if type(value)in(float,int,bool)else None,python_type=type(value).__name__,float_hex=value.hex()if type(value)is float else None);persist()
        require(type(value)is bool if name=='GetOverrideMachiningDepth'else type(value)is float and math.isfinite(value),'Strict finite native depth/flag required')
    out['complete']=True;persist();return out


def capture_depth(app,target,read,typed,persist,out):
    out.update(target=deepcopy(target),complete=False);doc=typed(read(app,'IGetActiveDoc'),'ICWDoc3')
    def lookup(kind,oid):
        value=read(doc,'GetCWObjectFromID',kind,oid);require(type(value)in(tuple,list)and len(value)==2 and value[1]is True and _object_id(doc,value[0],read)==oid,'Exact native object required');return value[0]
    opraw=lookup(3,target['operation_native_id']);op=typed(opraw,'ICWOperation');mill=typed(opraw,'ICWMillOperation')
    kind=read(mill,'OpernType');require(type(kind)is int and kind==target['operation_kind']and read(op,'Suppressed')is False,'Exact active Finish target required')
    require(read(op,'GetIsToolpathGenerated')is False and not _items(read(op,'IGetEnumToolpaths'),typed,read,1),'Selected operation must remain ungenerated')
    require([_object_id(doc,x,read)for x in _items(read(op,'IGetAllFeatures'),typed,read,2)]==[target['feature_native_id']],'Exact selected feature link required')
    tool=typed(read(op,'IGetTool'),'ICWTool');require(_object_id(doc,tool,read)==target['tool_native_id'],'Post-assignment tool differs')
    feature=lookup(1,target['feature_native_id']);out['values']={};persist();depth_values(opraw,feature,read,typed,persist,out['values']);out['complete']=True;persist();return out


def dispatch(sw,clsid,tlb,values,*,runtime_check):
    require(callable(runtime_check),'Runtime guard required');runtime_check();v=values;data=validate(v);classes=preflight(tlb);runtime_check();session=None
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),receipt_path=v['receipt_path'],failure_pin=data['failure_pin'],failure_marker_pin=data['marker_pin'],target=data['target'],evidence_pins=deepcopy(data['pins']),source_sha256=v['expected_source_sha256'],read_only=True,native_read_count=0,native_read_limit=MAX_READS,mutation_attempted=False,save_attempted=False,GTP_attempted=False,parameter_setter_attempted=False,marker_created=False,readback_verified=False,source_unchanged=False,runtime_unchanged=False,continuation_authorized=False,full_configuration_reconciled=False,production_qualified=False,physical_units_verified=False)
    def persist():_write_receipt(data['output'],r)
    _write_receipt(data['output'],r,create=True)
    def verify_pins():
        for p in data['pins']:
            if Path(p['path']).suffix.lower()=='.json':require(read_pin(p['path'],p['sha256'])[1]==p,'Recovery evidence metadata changed')
            else:common.direct(p)
    def identity():
        runtime_check();p=_process_identity(v['process_id']);require(p.get('alive')is True and p.get('process_id')==v['process_id']and p.get('create_time')==v['expected_process_create_time']and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact process lifetime required')
        pid=_member(sw,'GetProcessID');require(type(pid)is int and pid==v['process_id'],'Native owner differs');doc=document_snapshot(sw);require(type(doc)is dict and type(doc.get('type'))is int and doc['type']==1 and type(doc.get('needs_save'))is bool,'Explicit part identity with observed dirty flag required');check_document_target(doc['path'],doc['title'],expected_path=v['expected_document_path'],required=True);require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Saved source changed');return doc
    try:
        with solidworks_operation_lock(timeout_seconds=1,process_id=v['process_id']):
            verify_pins();initial=identity();r['document_before']=deepcopy(initial);addin=_member(sw,'GetAddInObject',clsid);require(addin is not None,'CAM must already be loaded');appraw=_member(addin,'GetCWApp');app=_typed(appraw,'ICWApp4',tlb);require(app is not None and bool(app),'Typed CAM application required');require(identity()==initial,'Bootstrap changed document');session=CamMessageSession(app,tlb)
            def check():
                summary=session.summary();r['messages']=summary;require(summary.get('active')is True and summary.get('subscribed')is True and not any(summary.get(k)for k in shared.finish.nc.EVENT_ERRORS),'CAM event requires stop')
            def admission(name):
                check();require(r['native_read_count']<MAX_READS,'Depth read budget exceeded');r['native_read_count']+=1;r['last_attempted_read']=name
            def read(owner,name,*args):
                require(name in GETTERS,'Getter outside depth observation scope');admission(name)
                try:value=_member(owner,name,*args)
                except Exception:r['failed_read']=name;persist();raise
                r['last_returned_read']=name;check();return value
            def typed(owner,name):
                require(name in classes and name!='ICWApp4','Interface outside depth observation scope');admission('QI '+name);value=owner.QueryInterface(classes[name]);require(value is not None and bool(value)and isinstance(value,POINTER(classes[name])),'Typed pointer required');check();return value
            with session:
                for label in('before','after'):
                    r['phase']=label;r[label]={};persist();verify_pins();check();require(identity()==initial,'Document changed before depth observation');capture_depth(app,data['target'],read,typed,persist,r[label]);check();require(identity()==initial,'Document changed after depth observation');verify_pins()
                require(exact(r['before'],r['after']),'Two depth observations differ');check()
            r['messages']=session.summary();clean_events(r);r['document_after']=identity();require(r['document_after']==initial,'Document changed after cleanup');verify_pins();runtime_check();r.update(status='review_required',phase='finished',readback_verified=True,source_unchanged=True,runtime_unchanged=True,reason='TWO_MATCHING_RAW_DEPTH_TRIPLES_ONLY_NO_CONTINUATION_AUTHORIZATION')
    except Exception as error:r.update(status='error',failed_phase=r.get('phase'),phase='finished',issue=_error(error),reason=str(error),readback_verified=False,source_unchanged=False,runtime_unchanged=False)
    finally:
        if session is not None:r['messages']=session.summary()
        persist()
    return r


def finalize_runtime_failure(result,error):
    result.update(status='error',phase='finished',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,source_unchanged=False,continuation_authorized=False);_write_receipt(Path(result['receipt_path']),result);return result
