"""Read default rough/finish TURN operations on an existing linked ID feature.

No change of feature strategy, operation insertion, tool lookup, generation or save.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_chamfer_catalogue_preflight as catalogue
from scripts import sw_cam_turn_feature_attribute as turn_context
from scripts import sw_cam_operation_profile as profile
from scripts import sw_cam_jobs as jobs
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_thread import _object_id,_file_hash
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target,solidworks_operation_lock
common=catalogue.exports
SCOPE='SAVED_TURN_ID_CATALOGUE_READ_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','typelib_path','setup_index','operation_index','expected_operation_native_id','expected_operation_type','reference_path','reference_sha256','generated_path','generated_sha256','receipt_path','module_sha256'}
OPERATION_TYPES=(1,2)
HEADER_KEYS=('name','feature_type_raw','turn_feature_type_raw','attribute_id_raw','attribute_name','diameters_native','start_native','end_native')
READ_MEMBERS={'GetAddInObject','GetCWApp','IGetActiveDoc','GetDocType','IGetMachine','MachType','IGetEnumSetups','IGetEnumFeatures','IGetEnumOpSetups','IGetEnumOperations','Count','Item','GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','OpernType','IGetWorkpiece','GetTurnWorkpieceType','GetCWObjectID','Suppressed','IGetAllFeatures','FeatureName','FeatType','GetTurnFeatureType','Attribute','GetAttributeName','GetMinMaxDiameter','GetStartPosition','GetEndPosition','IGetAllDefaultOperations','GetTdbIdForDefaultOperation'}


def read_catalogues(turn,*,read,record):
    result={}
    for kind in OPERATION_TYPES:
        raw=read(turn,'IGetAllDefaultOperations',kind)
        record('catalogue_names_'+str(kind),raw)
        if type(raw) in (tuple,list) and not raw:
            value=dict(operation_type=kind,converted_python_type=type(raw).__name__,entries=[],unique_default_available=False,selected_default_operation_id=None,selection_performed=False)
        else:
            def lookup(name):
                value=read(turn,'GetTdbIdForDefaultOperation',kind,name);record('catalogue_id_'+str(kind)+'_'+name,value);return value
            value=catalogue.decode_catalogue(raw,lookup);value['operation_type']=kind
        result[str(kind)]=value
    return result


def feature_header(raw,typelib,read):
    base=_typed(raw,'ICWFeature',typelib);turn=_typed(raw,'ICWTurnFeature',typelib)
    value=dict(name=profile._text(read(base,'FeatureName')),feature_type_raw=profile._integer(read(base,'FeatType')),turn_feature_type_raw=profile._integer(read(turn,'GetTurnFeatureType')),attribute_id_raw=profile._integer(read(turn,'Attribute')),attribute_name=profile._text(read(turn,'GetAttributeName')),diameters_native=dict(zip(('minimum','maximum'),map(profile._number,profile._values(read(turn,'GetMinMaxDiameter'),2)))),start_native=list(map(profile._number,profile._values(read(turn,'GetStartPosition'),3))),end_native=list(map(profile._number,profile._values(read(turn,'GetEndPosition'),3))))
    return value,turn


def selected(doc,machine,p,header,typelib,read):
    setups=turn_context._items(read(machine,'IGetEnumOpSetups'),typelib,read,limit=8)
    require(p['setup_index']<len(setups),'Selected setup absent')
    setup=_typed(setups[p['setup_index']],'ICWBaseOpSetup',typelib)
    operations=turn_context._items(read(setup,'IGetEnumOperations'),typelib,read,limit=32)
    require(p['operation_index']<len(operations),'Selected operation absent')
    raw=operations[p['operation_index']];op=_typed(raw,'ICWOperation',typelib);turn=_typed(raw,'ICWTurnOperation',typelib)
    row=dict(operation_native_id=_object_id(doc,op,read),operation_type=profile._integer(read(turn,'OpernType')),suppressed=read(op,'Suppressed'),generated=read(op,'GetIsToolpathGenerated'))
    require(row==dict(operation_native_id=p['expected_operation_native_id'],operation_type=p['expected_operation_type'],suppressed=False,generated=False),'Exact ungenerated reference operation required')
    linked=turn_context._items(read(op,'IGetAllFeatures'),typelib,read,limit=2);require(len(linked)==1,'One linked feature required')
    fid=_object_id(doc,linked[0],read);actual,owner=feature_header(linked[0],typelib,read)
    row.update(feature_native_id=fid,feature_header=actual)
    require(actual==header,'Existing linked ID profile header changed')
    return row,owner


def audit(typelib,generated_pin):
    from ctypes import POINTER,c_int
    from comtypes.automation import VARIANT,BSTR
    from scripts.sw_cam_comtypes import _load_type_library,_INTERFACES
    from scripts.sw_cam_face_interfaces import _verify_generated_class
    from scripts.sw_cam_pocket_rough_apply import require_abi
    cls=_verify_generated_class(getattr(_load_type_library(typelib),'ICWTurnFeature'),_INTERFACES['ICWTurnFeature'],generated_pin)
    rows=[]
    for name,ident,args,flags in [('IGetAllDefaultOperations',10,(c_int,POINTER(VARIANT)),(1,10)),('GetTdbIdForDefaultOperation',11,(c_int,BSTR,POINTER(c_int)),(1,1,10))]:
        found=[m for m in cls._methods_ if m.name==name];require(len(found)==1,'Unique declared catalogue method required');require_abi(found[0],ident,args,flags);rows.append(dict(interface='ICWTurnFeature',member=name,dispid=ident))
    return dict(abi_verified=True,native_calls=0,methods=rows)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_turn_bore_catalogue','Exact read-only catalogue action required')
    p=deepcopy(request['params']);require(set(p)==PARAMS,'Exact request fields required')
    for name,minimum in [('process_id',1),('expected_operation_native_id',1),('expected_operation_type',1),('setup_index',0),('operation_index',0)]:require(type(p[name]) is int and minimum<=p[name]<2**31,'Strict selector required')
    require(p['setup_index']<8 and p['operation_index']<32,'Bounded selectors required')
    for name,value in p.items():
        if name.endswith('_path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
        if name.endswith('_sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader changed');return p


def prepare(p):
    ref,rpin=read_pin(p['reference_path'],p['reference_sha256'])
    require(ref['scope']=='SAVED_TURN_ID_CATALOGUE_REFERENCE_V1' and ref['source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path'])
        and common._key(ref['source_path'])==common._key(p['expected_document_path']),'Exact source reference required')
    common._check(ref['evidence_pins'])
    require(set(ref['feature_header'])==set(HEADER_KEYS) and ref['feature_header']['turn_feature_type_raw']==2,'Saved ID-feature header required')
    checkpoint,_=read_pin(ref['checkpoint_pin']['path'],ref['checkpoint_pin']['sha256']);state=checkpoint['final_state']
    require(checkpoint['save_readback_verified'] is True and state['saved_file_sha256']==p['expected_source_sha256'] and state['document']['needs_save'] is False,'Saved clean TURN checkpoint required')
    require(state['inventory']==ref['inventory'],'Reference inventory differs from saved checkpoint')
    row=next(x for x in ref['inventory']['operations'] if x['setup_index']==p['setup_index'] and x['operation_index']==p['operation_index'])
    require(row['turn_operation_type']==p['expected_operation_type'] and row['toolpath_generated'] is False and row['toolpath_record_counts']==[],'Ungenerated selected operation required')
    generated=common._pin(p['generated_path']);require(generated['sha256']==p['generated_sha256'],'Generated binding changed')
    reg=jobs._validate_registration(p);abi=audit(p['typelib_path'],generated)
    pins=common._merge([rpin,generated,common._pin(__file__),common._pin(catalogue.__file__),common._pin(turn_context.__file__),common._pin(profile.__file__)],ref['evidence_pins'])
    output=common._local_receipt(p['receipt_path']);require(output.parent.is_dir() and not output.exists() and not output.is_symlink()
        and common._key(output) not in {common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])},'Fresh nonaliased receipt required')
    return ref,pins,abi,output,reg


def cleanup(session,report,persist):
    if session is not None:
        report['messages']=session.summary()
        if report['messages'].get('active') or report['messages'].get('disconnected') is not True or any(report['messages'].get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
            report.update(status='error',readback_verified=False,cleanup_incomplete=True)
    persist()


def inspect(sw,p,ref,pins,report,persist):
    session=None
    try:
        def identity():
            require(_member(sw,'GetProcessID')==p['process_id'],'Owned process changed')
            state=document_snapshot(sw);require(state is not None and state['type']==1 and state['needs_save'] is False,'Clean saved part required')
            check_document_target(state['path'],state['title'],expected_path=p['expected_document_path'],required=True)
            require(_file_hash(state['path'])==p['expected_source_sha256'],'Source bytes changed');return state
        def check():
            value=session.summary();report['messages']=value
            require(value.get('active') and value.get('subscribed') and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event requires stop')
        calls=0
        def read(obj,name,*args):
            nonlocal calls
            require(name in READ_MEMBERS and calls<700,'Bounded read-only catalogue scope required');calls+=1
            report.update(current_read=name,native_dispatch_pending=True);check();value=_member(obj,name,*args);check();report['native_dispatch_pending']=False;return value
        def record(key,value):
            scalar=value is None or type(value) in (bool,int,float,str)
            simple_array=type(value) in (list,tuple) and len(value)<=32 and all(type(x) is str and len(x)<=1000 for x in value)
            row=dict(key=key,returned_type=type(value).__name__)
            if scalar or simple_array:row['value']=value
            else:row['unserializable_or_out_of_scope_shape']=True
            report['observations'].append(row);persist()
        initial=identity();common._check(pins)
        addin=_member(sw,'GetAddInObject',p['addin_clsid']);require(addin is not None,'CAM addin must already be loaded')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',p['typelib_path']);session=CamMessageSession(app,p['typelib_path'])
        with session:
            report['phase']='binding_before';_,doc,_,machine,_=turn_context._context(sw,p['addin_clsid'],p['typelib_path'],read)
            report['inventory_before']=turn_context._inventory(machine,p['typelib_path'],read);require(report['inventory_before']==ref['inventory'],'Saved TURN inventory changed')
            report['before'],owner=selected(doc,machine,p,ref['feature_header'],p['typelib_path'],read);persist()
            report['phase']='catalogue';report['catalogues']=read_catalogues(owner,read=read,record=record);persist()
            report['phase']='binding_after';report['after'],_=selected(doc,machine,p,ref['feature_header'],p['typelib_path'],read)
            report['inventory_after']=turn_context._inventory(machine,p['typelib_path'],read)
            require(report['before']==report['after'] and report['inventory_before']==report['inventory_after'],'Target or TURN inventory changed')
            require(identity()==initial,'Document changed during read');check()
        require(identity()==initial,'Document changed after cleanup');common._check(pins)
        report.update(status='observed',phase='finished',readback_verified=True,native_read_calls=calls)
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,native_dispatch_pending=False)
    finally:cleanup(session,report,persist)
    return report


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);ref,pins,abi,output,reg=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,abi=abi,requested_turn_operation_types=list(OPERATION_TYPES),source_sha256=p['expected_source_sha256'])
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        report=dict(scope=SCOPE,status='prepared',phase='prepared',read_only=True,mutation_attempted=False,GTP_attempted=False,model_saved=False,operation_inserted=False,attribute_changed=False,readback_verified=False,source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],process_id=p['process_id'],request=p,runtime_and_evidence_pins=pins,abi=abi,observations=[],geometry_acceptance_complete=False)
        persist=lambda:_write_receipt(output,report);_write_receipt(output,report,create=True);return inspect(sw,p,ref,pins,report,persist)


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','catalogues','issue','native_called')},ensure_ascii=False));return 0 if r.get('readback_verified') or r.get('status')=='validated_offline' else 1
if __name__=='__main__':raise SystemExit(main())
