"""Read named internal TURN bore-operation defaults from current type metadata.

The rough_bore/finish_bore roles resolve to declared BORE enum symbols. Ordinary
ROUGH_TURN/FINISH_TURN values cannot be substituted merely because a feature is ID.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_bore_catalogue as previous
from scripts.sw_cam import _error,_member,document_snapshot
from scripts.sw_cam_generation import _write_receipt,_typed
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock,check_document_target
from scripts.sw_cam_events import CamMessageSession
common=previous.common
SCOPE='NAMED_TURN_BORE_DEFAULT_CATALOGUE_READ_V1'
ROLE_SYMBOLS={'rough_bore':'CW_TURN_OP_ROUGH_BORE','finish_bore':'CW_TURN_OP_FINISH_BORE'}
TURN_SYMBOLS=('CW_TURN_OP_ROUGH_TURN','CW_TURN_OP_FINISH_TURN')
PARAMS=previous.PARAMS|{'roles','reopened_receipt_path','reopened_receipt_sha256','expected_feature_native_id'}


def resolve_roles(constants,roles):
    require(type(roles) is list and roles==list(ROLE_SYMBOLS),'Exact named rough_bore then finish_bore roles required')
    forbidden=[getattr(constants,x) for x in TURN_SYMBOLS]
    require(all(type(x) is int and 0<x<2**31 for x in forbidden),'Declared TURN constants required')
    result=[]
    for role in roles:
        symbol=ROLE_SYMBOLS[role];value=getattr(constants,symbol)
        require(type(value) is int and 0<value<2**31 and value not in forbidden,'BORE intent cannot use ordinary TURN enum')
        result.append(dict(role=role,enum_symbol=symbol,resolved_native_value=value))
    require(len({x['resolved_native_value'] for x in result})==2,'Distinct BORE enum values required')
    return result


def check_operation_role(actual,role,constants):
    require(role in ROLE_SYMBOLS and type(actual) is int,'Strict named BORE readback required')
    expected=next(x['resolved_native_value'] for x in resolve_roles(constants,list(ROLE_SYMBOLS)) if x['role']==role)
    require(actual==expected,'Operation type differs from declared BORE role')


def read_catalogues(owner,roles,*,read,record):
    result={}
    for spec in roles:
        role=spec['role'];kind=spec['resolved_native_value']
        raw=read(owner,'IGetAllDefaultOperations',kind);record(role+'_names',raw)
        if type(raw) in (tuple,list) and not raw:
            value=dict(converted_python_type=type(raw).__name__,entries=[],unique_default_available=False,selected_default_operation_id=None,selection_performed=False)
        else:
            def lookup(name):
                value=read(owner,'GetTdbIdForDefaultOperation',kind,name);record(role+'_id_'+name,value);return value
            value=previous.catalogue.decode_catalogue(raw,lookup)
        result[role]=dict(value,**spec)
    return result


def audit(typelib,generated_pin,roles):
    from scripts.sw_cam_comtypes import _load_type_library
    methods=previous.audit(typelib,generated_pin)
    resolved=resolve_roles(_load_type_library(typelib),roles)
    return dict(abi_verified=methods['abi_verified'],native_called=False,methods=methods['methods'],roles=resolved,generated_pin=generated_pin,ordinary_turn_types_allowed_for_bore=False)


def old_params(p):
    q={k:p[k] for k in previous.PARAMS};q['module_sha256']=_file_hash(previous.__file__)
    return q


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_named_turn_bore_defaults','Exact read-only named-bore action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    require(type(p['roles']) is list and p['roles']==list(ROLE_SYMBOLS),'Explicit named BORE intent required')
    require(p['module_sha256']==_file_hash(__file__),'Reader bytes changed')
    require(type(p['expected_feature_native_id']) is int and 0<p['expected_feature_native_id']<2**31,'Strict linked feature identity required')
    require(type(p['reopened_receipt_path']) is str and Path(p['reopened_receipt_path']).is_absolute() and type(p['reopened_receipt_sha256']) is str and re.fullmatch('[0-9a-f]{64}',p['reopened_receipt_sha256']),'Pinned reopened-session evidence required')
    previous.validate_request(dict(action='read_turn_bore_catalogue',params=old_params(p)))
    return p


def prepare(p):
    # Reuse the original verified clean-source checkpoint/reference directly.
    # Do not carry the failed insert/repair loader lineage into the reopened part.
    ref,pins,_,output,reg=previous.prepare(old_params(p))
    reopened,rpin=read_pin(p['reopened_receipt_path'],p['reopened_receipt_sha256'])
    require(type(reopened) is dict,'Reopened-session evidence must be JSON')
    # This extra pin records provenance only. Actual session/source/feature and
    # inventory are verified fresh below against the saved clean reference.
    generated=common._pin(p['generated_path']);require(generated['sha256']==p['generated_sha256'],'Generated binding differs')
    abi=audit(p['typelib_path'],generated,p['roles'])
    pins=common._merge(pins,[rpin,common._pin(__file__),common._pin(previous.__file__)])
    require(len(pins)<=64 and common._key(output) not in {common._key(x['path']) for x in pins},'Bounded nonaliased evidence closure required')
    return dict(reference=ref,roles=abi['roles'],pins=pins,typelib_path=p['typelib_path'],generated_pin=generated,abi=abi,registration=reg,output=output,reopened_receipt_pin=rpin)


def inspect(sw,p,plan,r,persist):
    session=None;calls=0
    try:
        def identity():
            pid=_member(sw,'GetProcessID');require(type(pid) is int and pid==p['process_id'],'Owned process changed')
            state=document_snapshot(sw);require(state is not None and state['type']==1 and state['needs_save'] is False,'Clean reopened part required')
            check_document_target(state['path'],state['title'],expected_path=p['expected_document_path'],required=True)
            require(_file_hash(state['path'])==p['expected_source_sha256'],'Source bytes changed');return state
        def events():
            value=session.summary();r['messages']=value
            require(value.get('active') and value.get('subscribed') and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event requires stop')
        def read(obj,name,*args):
            nonlocal calls
            require(name in previous.READ_MEMBERS and calls<700,'Bounded read-only catalogue scope required');calls+=1
            r.update(current_read=name,native_dispatch_pending=True);events();value=_member(obj,name,*args);events();r['native_dispatch_pending']=False;return value
        def record(key,value):
            scalar=value is None or type(value) in (bool,int,float,str)
            array=type(value) in (tuple,list) and len(value)<=64 and all(type(x) is str and len(x)<=1000 for x in value)
            row=dict(key=key,returned_type=type(value).__name__)
            if scalar or array:row['value']=value
            else:row['unsupported_shape']=True
            r['observations'].append(row);persist()
        initial=identity();common._check(plan['pins'])
        addin=_member(sw,'GetAddInObject',p['addin_clsid']);require(addin is not None,'Existing CAM addin required')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',p['typelib_path']);session=CamMessageSession(app,p['typelib_path'])
        with session:
            r['phase']='before';_,doc,_,machine,_=previous.turn_context._context(sw,p['addin_clsid'],p['typelib_path'],read)
            r['inventory_before']=previous.turn_context._inventory(machine,p['typelib_path'],read)
            require(r['inventory_before']==plan['reference']['inventory'],'Reopened inventory differs from verified saved checkpoint')
            r['before'],owner=previous.selected(doc,machine,p,plan['reference']['feature_header'],p['typelib_path'],read);persist()
            require(r['before']['feature_native_id']==p['expected_feature_native_id'],'Linked feature ID changed')
            r['phase']='named_bore_catalogues';r['catalogues']=read_catalogues(owner,plan['roles'],read=read,record=record);persist()
            r['phase']='after';r['after'],_=previous.selected(doc,machine,p,plan['reference']['feature_header'],p['typelib_path'],read)
            r['inventory_after']=previous.turn_context._inventory(machine,p['typelib_path'],read)
            require(r['after']==r['before'] and r['inventory_after']==r['inventory_before'],'Read changed selected feature or inventory')
            require(identity()==initial,'Reopened document changed');events()
        require(identity()==initial,'Document changed after cleanup');common._check(plan['pins'])
        r.update(status='observed',phase='finished',readback_verified=True,native_read_calls=calls)
    except Exception as exc:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:previous.cleanup(session,r,persist)
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),roles=plan['roles'],mutation_authorized=False)
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,operation_inserted=False,assignment_attempted=False,persistence_qualified=False,production_qualified=False,readback_verified=False,source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],runtime_and_evidence_pins=plan['pins'],abi=plan['abi'],reopened_receipt_pin=plan['reopened_receipt_pin'],observations=[],limitations=['Defaults only; no operation insertion/deletion/assignment/Save/GTP','BORE roles resolve from pinned type metadata; ordinary TURN1/2 are rejected for bore intent','Reopened provenance receipt is pinned; live checks bind exact saved-source inventory and linked ID-feature'])
        _write_receipt(plan['output'],r,create=True);persist=lambda:_write_receipt(plan['output'],r)
        return inspect(sw,p,plan,r,persist)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    value=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:value[k] for k in ('scope','status','phase','readback_verified','native_called','pin_count','roles','catalogues','issue') if k in value},ensure_ascii=False,indent=2))
    raise SystemExit(0 if value['status'] in ('validated_offline','observed') else 2)
