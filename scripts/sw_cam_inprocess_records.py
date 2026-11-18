"""One owner-STA positional record observation; no remote record fallback or mutation."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json,re,time
from scripts import sw_cam_inprocess_reader as core
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_operation_guard import solidworks_operation_lock

SCOPE='TURN_OWNER_RECORD_READ_V1'
SELECTION_FIELDS={'operation_native_id','feature_native_id','operation_type','setup_index','operation_index','expected_operation_count','expected_setup_count','expected_record_count'}
EXTRA={'record_read','cam_typelib_path','cam_typelib_sha256','qualification_only','message_policy'}
EVENT_ERRORS=('event_count','events','overflow','callback_error_count','callback_errors','subscription_error','disconnect_errors')
require=core.require

def validate(params):
    require(type(params) is dict and core.FIELDS|EXTRA <= set(params) <= core.FIELDS|EXTRA|{'nc_operation_ids'},'Exact record-reader fields required')
    p=deepcopy(params);base={k:v for k,v in p.items() if k not in EXTRA};core.validate_params(base)
    require(not p.get('nc_operation_ids') and p['reference_receipt_path'] is None and p['reference_receipt_sha256'] is None,'Record reader has no NC scalars or legacy reference comparison')
    require(p['qualification_only'] is True and p['message_policy']=='vendor_default','Explicit read qualification policy required')
    require(type(p['cam_typelib_path']) is str and Path(p['cam_typelib_path']).is_absolute() and Path(p['cam_typelib_path']).suffix.casefold()=='.tlb','Exact CAM typelib required')
    require(type(p['cam_typelib_sha256']) is str and re.fullmatch('[0-9a-f]{64}',p['cam_typelib_sha256']),'Exact CAM typelib SHA required')
    s=p['record_read'];require(type(s) is dict and set(s)==SELECTION_FIELDS,'Exact selected record binding required')
    bounds={'operation_native_id':(1,2**31-1),'feature_native_id':(1,2**31-1),'operation_type':(7,8),'setup_index':(0,7),'operation_index':(0,63),'expected_operation_count':(1,64),'expected_setup_count':(1,8),'expected_record_count':(1,256)}
    for k,(lo,hi) in bounds.items():require(type(s[k]) is int and lo<=s[k]<=hi,'Strict bounded '+k+' required')
    require(s['setup_index']<s['expected_setup_count'] and s['operation_index']<s['expected_operation_count'] and s['expected_operation_count']<=p['max_operations'],'Selection position/count mismatch')
    return p

def native_request(p):
    result=core.native_request(p);result['record_read']=deepcopy(p['record_read']);return result

def validate_selection(inventory,s):
    require(inventory['operation_count']==s['expected_operation_count'] and inventory['operation_setup_count']==s['expected_setup_count'],'Exact inventory counts required')
    rows=[x for x in inventory['operations'] if x['native_id']==s['operation_native_id']];require(len(rows)==1,'Selected native ID absent or duplicate');r=rows[0]
    require(r['setup_index']==s['setup_index'] and r['operation_index']==s['operation_index'] and r['turn_operation_type']==s['operation_type'] and r['linked_feature_ids']==[s['feature_native_id']],'Selected operation binding mismatch')
    require(r['suppressed'] is False and r['toolpath_generated'] is True and r['toolpath_record_counts']==[s['expected_record_count']],'Exact generated selected path required')

def validate_response(text,p):
    r=core.validate_response(text,p)
    if r['status']=='error':return r
    owner=r.get('owner_thread');require(type(owner) is dict and set(owner)=={'expected_managed_thread_id','actual_managed_thread_id','apartment','in_process'} and type(owner['expected_managed_thread_id']) is int and type(owner['actual_managed_thread_id']) is int and owner['expected_managed_thread_id']>0 and owner['expected_managed_thread_id']==owner['actual_managed_thread_id'] and owner['apartment']=='STA' and owner['in_process'] is True,'Owner STA evidence required')
    require(r['document_before']['needs_save'] is False and r['document_after']['needs_save'] is False,'Clean saved document required')
    core.validate_inventory(r['inventory_after'],p);require(r['inventory']==r['inventory_after'] and r.get('record_inventory_unchanged') is True,'Full native inventory changed')
    validate_selection(r['inventory'],p['record_read'])
    require(r['tools']==[] and r['nc_parameters']==[],'Unrequested tool/NC reads prohibited')
    d=r['record_read'];s=p['record_read'];require(type(d) is dict and type(d.get('schema_version')) is int and d['schema_version']==1 and d.get('status')=='observed' and d.get('stage')=='finished','Incomplete record observation')
    require(d.get('accessor')=='GetEnumRecords' and d.get('fallback_attempted') is False and all(d.get(k) is False for k in ('units_verified','frame_verified','tool_vector_read','complete_payload_read')),'Exact bounded accessor and limitations required')
    require(not any(k in d for k in ('hresult','error_type','message')),'Record error cannot be verified')
    require(type(d.get('expected_record_count')) is int and d['expected_record_count']==s['expected_record_count'],'Record count binding differs')
    rows=d.get('records');require(type(rows) is list and len(rows)==s['expected_record_count'],'Incomplete native record list')
    for i,row in enumerate(rows):
        require(type(row) is dict and type(row.get('index')) is int and row['index']==i and type(row.get('type_raw')) is int,'Exact native index/type required')
        if row['type_raw']==7:
            require(set(row)=={'index','type_raw','position_read','rapid_raw','point_native'} and row['position_read'] is True and type(row['rapid_raw']) is int,'Exact GOTO payload required')
            require(type(row['point_native']) is list and len(row['point_native'])==3 and all(core.finite(x) for x in row['point_native']),'Finite native XYZ required')
        else:require(set(row)=={'index','type_raw','position_read'} and row['position_read'] is False,'Non-GOTO payload must remain undecoded')
    return r

class NativeBackend(core.NativeBackend):
    def __init__(self,p,sw):super().__init__(p);self.sw=sw;self.session=None
    def start(self):
        from scripts.sw_cam_events import CamMessageSession
        from scripts.sw_cam_comtypes import query_cam_interface
        require(_member(self.sw,'GetProcessID')==self.p['process_id'],'Bound SW PID differs')
        bridge=_member(self.sw,'GetAddInObject',core.CAM_CLSID);require(bridge is not None,'CAM must already be loaded')
        app=query_cam_interface(_member(bridge,'GetCWApp'),'ICWApp4',self.p['cam_typelib_path'])
        self.session=CamMessageSession(app,self.p['cam_typelib_path']);self.session.__enter__()
        m=self.session.summary();require(m['active'] and m['subscribed'] and not any(m.get(k) for k in EVENT_ERRORS),'Event subscription not clean')
    def read_once(self,request_json):
        from ctypes import POINTER
        from comtypes import BSTR,typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        library=typeinfo.LoadTypeLibEx(self.p['host_tlb_path'],typeinfo.REGKIND_NONE);attr=library.GetLibAttr()
        require(str(attr.guid).upper()==core.HOST_LIBID and (attr.wMajorVerNum,attr.wMinorVerNum)==(1,0),'Exact host typelib required')
        interface=getattr(GetModule(library),'ICamBatchReader');require(str(interface._iid_).upper()==core.READER_IID,'Exact reader interface required')
        methods=[m for m in interface._methods_ if m.name=='ReadTurnSnapshot'];require(len(methods)==1,'Unique reader ABI required');require_abi(methods[0],1,(BSTR,POINTER(BSTR)),(1,10))
        require(_member(self.sw,'GetProcessID')==self.p['process_id'],'Bound SW PID differs')
        raw=_member(self.sw,'GetAddInObject',core.HOST_CLSID);require(raw is not None,'Reader must already be loaded; no load fallback')
        return _marshal_pywin32_unknown(raw).QueryInterface(interface).ReadTurnSnapshot(request_json)
    def finish(self):
        if self.session is not None:self.session.__exit__(None,None,None)
        return self.session.summary() if self.session else {}

def run_read(params,*,backend,runtime_check=lambda:None):
    p=validate(params);pins=core.pins_for(p)+[{'path':p['cam_typelib_path'],'sha256':p['cam_typelib_sha256']},{'path':str(Path(__file__).resolve()),'sha256':core.digest(__file__)},{'path':str(Path(core.__file__).resolve()),'sha256':core.digest(core.__file__)}]
    require(len({core.key(x['path']) for x in pins})==len(pins),'Distinct input pins required');core.check_files(pins);runtime_check()
    out=Path(p['receipt_path']);require(out.suffix.casefold()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink() and core.key(out) not in {core.key(x['path']) for x in pins},'Fresh nonaliased receipt required')
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,pins=pins,read_only=True,mutation_attempted=False,GTP_attempted=False,model_saved=False,readback_verified=False,source_unchanged=False,runtime_unchanged=False,inventory_unchanged=False,cleanup_verified=False,batch_calls=0,automatic_retry_permitted=False,units_verified=False,frame_verified=False,production_qualified=False)
    _write_receipt(out,r,create=True);start=time.perf_counter();owner=None
    try:
        owner=backend.owner();core.check_owner(owner,p);r['owner_before']=owner;backend.start();core.check_files(pins);runtime_check()
        r.update(phase='single_owner_host_call',batch_calls=1,native_dispatch_pending=True);_write_receipt(out,r)
        text=backend.read_once(json.dumps(native_request(p),ensure_ascii=False));r['native_dispatch_pending']=False;r['host_response']=core.decode(text);validate_response(text,p)
        if r['host_response']['status']=='error':
            host=r['host_response'];native=host.get('record_read',host)
            r['native_issue']={k:native[k] for k in ('stage','record_index','hresult','error_type','message') if k in native}
            raise RuntimeError('Owner host failed; exact native stage/HRESULT retained in native_issue; no retry')
    except Exception as exc:r['issue']=_error(exc)
    finally:
        try:
            r['messages']=backend.finish();m=r['messages'];require(m.get('subscribed') is True and m.get('disconnected') is True and m.get('active') is False and not any(m.get(k) for k in EVENT_ERRORS),'Event cleanup or CAM message failure');r['cleanup_verified']=True
        except Exception as exc:r['cleanup_issue']=_error(exc)
        try:
            after=backend.owner();core.check_owner(after,p);require(owner is not None and after==owner,'Owned lifetime changed');r['owner_after']=after
            core.check_files(pins);runtime_check();r['source_unchanged']=True;r['runtime_unchanged']=True
        except Exception as exc:r['after_guard_issue']=_error(exc)
    ok=not any(k in r for k in ('issue','cleanup_issue','after_guard_issue'))
    r.update(status='observed' if ok else 'error',phase='finished',readback_verified=ok,inventory_unchanged=ok,elapsed_seconds=time.perf_counter()-start)
    _write_receipt(out,r);return r

def read_turn_records(params,sw,*,runtime_check=lambda:None):
    p=validate(params)
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):return run_read(p,backend=NativeBackend(p,sw),runtime_check=runtime_check)
