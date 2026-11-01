"""One typed call to an already loaded, pinned in-process TURN reader."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib,json,math,re,time,uuid
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_operation_guard import solidworks_operation_lock

HOST_CLSID='{8EE76E8D-9B47-4DE0-AFA2-B2E36621A134}'
HOST_LIBID='{AF071B05-0956-3EFB-B3F0-77BC51751AC9}'
READER_IID='{DA9D97F8-EB0E-4D7B-A741-0E1736E899A2}'
CAM_CLSID='{CCAC6208-0E19-6455-2022-2026CEB541FA}'
SCOPE='TURN_INPROCESS_CLIENT_READ_V1'
FIELDS={'process_id','expected_process_creation_time','expected_document_path','expected_source_sha256','host_dll_path','host_dll_sha256','host_tlb_path','host_tlb_sha256','expected_host_module_version_id','max_operations','max_tools','receipt_path','reference_receipt_path','reference_receipt_sha256'}
MAX_RESPONSE=1048576
INSERT_DIMENSIONS={'Thickness','IncludedAngle','NoseRadius','InscribedCircle'}
HOLDER_DIMENSIONS={'BoringBarDiameter','ShankLength','LeadAngle','BackClearAngle','FrontClearAngle','ZInsertOffset','XInsertOffset','Protrusion','HolderShape'}

def require(value,message):
    if not value: raise ValueError(message)

def key(path):return str(Path(path).resolve()).replace('/','\\').casefold()
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def finite(v):return type(v) in (int,float) and math.isfinite(v)
def duplicate_safe(pairs):
    result={}
    for k,v in pairs:
        require(k not in result,'Duplicate JSON key');result[k]=v
    return result

def decode(text):
    require(type(text) is str and 0<len(text.encode('utf-8'))<=MAX_RESPONSE,'Bounded JSON text required')
    return json.loads(text,object_pairs_hook=duplicate_safe,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))

def validate_params(params):
    require(type(params) is dict and FIELDS<=set(params)<=FIELDS|{'nc_operation_ids'},'Exact reader fields required');p=deepcopy(params)
    nc=p.get('nc_operation_ids',[]);require(type(nc) is list and len(nc)<=8 and all(type(x) is int and 0<x<2**31 for x in nc) and len(set(nc))==len(nc),'Bounded unique NC operation IDs required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict owned PID required')
    require(finite(p['expected_process_creation_time']) and p['expected_process_creation_time']>0,'Exact process creation time required')
    for n in ('max_operations','max_tools'):require(type(p[n]) is int and 1<=p[n]<=64,'Reader bounds must be 1..64')
    for n in ('expected_document_path','host_dll_path','host_tlb_path','receipt_path'):
        require(type(p[n]) is str and Path(p[n]).is_absolute() and len(p[n])<=32767,'Absolute bounded paths required')
    require(Path(p['expected_document_path']).suffix.casefold()=='.sldprt' and Path(p['host_dll_path']).suffix.casefold()=='.dll' and Path(p['host_tlb_path']).suffix.casefold()=='.tlb','Part/DLL/TLB paths required')
    for n in ('expected_source_sha256','host_dll_sha256','host_tlb_sha256'):require(type(p[n]) is str and re.fullmatch('[0-9a-f]{64}',p[n]),'Exact lowercase SHA256 required')
    require(type(p['expected_host_module_version_id']) is str,'Exact host MVID required');p['expected_host_module_version_id']=str(uuid.UUID(p['expected_host_module_version_id']))
    rp,rs=p['reference_receipt_path'],p['reference_receipt_sha256']
    require((rp is None)==(rs is None),'Reference path/hash supplied together')
    if rp is not None:require(type(rp) is str and Path(rp).is_absolute() and type(rs) is str and re.fullmatch('[0-9a-f]{64}',rs),'Exact optional reference pin required')
    return p

def native_request(p):
    result={'schema_version':1,'expected_process_id':p['process_id'],'expected_document_path':p['expected_document_path'],'cam_addin_clsid':CAM_CLSID,'max_operations':p['max_operations'],'max_tools':p['max_tools']}
    if p.get('nc_operation_ids'):result['nc_operation_ids']=p['nc_operation_ids']
    return result

def pins_for(p):
    pins=[{'path':p[a],'sha256':p[b]} for a,b in [('expected_document_path','expected_source_sha256'),('host_dll_path','host_dll_sha256'),('host_tlb_path','host_tlb_sha256')]]
    if p['reference_receipt_path'] is not None:pins.append({'path':p['reference_receipt_path'],'sha256':p['reference_receipt_sha256']})
    require(len({key(x['path']) for x in pins})==len(pins),'Pinned inputs may not alias');return pins

def check_files(pins):
    for pin in pins:
        q=Path(pin['path']);require(q.is_file() and not q.is_symlink() and 0<q.stat().st_size<=128*1024*1024,'Existing bounded regular input required')
        require(digest(q)==pin['sha256'],'Pinned input hash changed')

def check_owner(owner,p):
    require(type(owner) is dict and owner.get('alive') is True and type(owner.get('process_id')) is int and owner['process_id']==p['process_id'] and owner.get('create_time')==p['expected_process_creation_time'],'Owned process lifetime changed')
    require(type(owner.get('executable')) is str and Path(owner['executable']).name.casefold()=='sldworks.exe','SOLIDWORKS owner required')

def validate_document(doc,p):
    require(type(doc) is dict and set(doc)=={'path','title','type','needs_save','configuration'},'Exact host document identity required')
    require(type(doc['path']) is str and key(doc['path'])==key(p['expected_document_path']) and type(doc['type']) is int and doc['type']==1 and type(doc['needs_save']) is bool,'Host document mismatch')
    require(type(doc['title']) is str and len(doc['title'])<=4096 and type(doc['configuration']) is str and 0<len(doc['configuration'])<=4096,'Bounded title and configuration required')

def validate_inventory(inv,p):
    require(type(inv) is dict and set(inv)=={'machine_type','operation_setup_count','operation_count','operations'},'Exact inventory required')
    require(type(inv['machine_type']) is int and inv['machine_type']==3 and type(inv['operation_setup_count']) is int and 0<=inv['operation_setup_count']<=8,'TURN inventory required')
    rows=inv['operations'];require(type(rows) is list and type(inv['operation_count']) is int and inv['operation_count']==len(rows)<=p['max_operations'],'Bounded operation count required')
    ids=set();positions=set()
    for r in rows:
        require(type(r) is dict and set(r)=={'setup_index','operation_index','native_id','turn_operation_type','linked_feature_ids','suppressed','toolpath_generated','toolpath_record_counts'},'Exact operation row required')
        require(all(type(r[n]) is int for n in ('setup_index','operation_index','native_id','turn_operation_type')) and 0<=r['setup_index']<inv['operation_setup_count'] and 0<=r['operation_index']<p['max_operations'] and 0<r['native_id']<2**32 and 1<=r['turn_operation_type']<=64,'Operation ID/type/position invalid')
        pos=(r['setup_index'],r['operation_index']);require(r['native_id'] not in ids and pos not in positions,'Duplicate operation identity');ids.add(r['native_id']);positions.add(pos)
        f=r['linked_feature_ids'];require(type(f) is list and len(f)<=16 and all(type(x) is int and 0<x<2**32 for x in f) and len(set(f))==len(f),'Feature links invalid')
        c=r['toolpath_record_counts'];require(type(r['suppressed']) is bool and type(r['toolpath_generated']) is bool and type(c) is list and len(c)<=64 and all(type(x) is int and x>=0 for x in c),'Path metadata invalid')
        require(r['toolpath_generated'] or not c,'Ungenerated operation has path counts')

def validate_response(text,p):
    r=decode(text);require(type(r) is dict,'Host response object required')
    require(r.get('schema_version')==1 and type(r['schema_version']) is int and r.get('scope')=='TURN_INPROCESS_READ_V1' and r.get('engine_version')=='turn-reader-1','Host protocol mismatch')
    require(r.get('read_only') is True and r.get('mutation_attempted') is False,'Read-only host response required')
    require(type(r.get('process_id')) is int and r['process_id']==p['process_id'],'Host PID mismatch')
    require(type(r.get('host_module_version_id')) is str and str(uuid.UUID(r['host_module_version_id']))==p['expected_host_module_version_id'],'Loaded host MVID mismatch')
    require(type(r.get('host_assembly_location')) is str and key(r['host_assembly_location'])==key(p['host_dll_path']),'Loaded host location mismatch')
    require(finite(r.get('elapsed_ms')) and r['elapsed_ms']>=0,'Host timing invalid')
    require(r.get('status') in ('error','observed'),'Unknown host result status')
    if r['status']=='error':
        require(r.get('readback_verified') is False,'Error response cannot be verified');return r
    require(r.get('readback_verified') is True and r.get('stage')=='finished' and not any(k in r for k in ('error_type','hresult','message')),'Incomplete host observation')
    validate_document(r['document_before'],p);validate_document(r['document_after'],p);require(r['document_before']==r['document_after'],'Document changed during host call')
    validate_inventory(r['inventory'],p);ts=r['tools'];require(type(ts) is list and len(ts)<=p['max_tools'],'Bounded tools required');ids=set()
    for tool in ts:
        require(type(tool) is dict and tool.get('complete') is True and type(tool.get('native_id')) is int and 0<tool['native_id']<2**32 and tool['native_id'] not in ids,'Unique complete tool identity required');ids.add(tool['native_id'])
        require(type(tool.get('tool_type_raw')) is int and type(tool.get('candidate')) is bool and type(tool.get('info_raw')) is str and len(tool['info_raw'])<=4096,'Tool metadata invalid')
        if tool['candidate']:
            require(all(type(tool.get(n)) is int for n in ('turn_tool_type_raw','insert_type_raw','holder_type_raw','holder_id_raw')) and tool['tool_type_raw']==15 and tool.get('turn_tool_type_raw')==1 and tool.get('insert_type_raw')==1 and tool.get('holder_present') is True and tool.get('holder_type_raw')==2,'Candidate classification mismatch')
            for name,fields in (('insert_dimensions_native',INSERT_DIMENSIONS),('holder_dimensions_native',HOLDER_DIMENSIONS)):
                require(type(tool.get(name)) is dict and set(tool[name])==fields and all(finite(v) for v in tool[name].values()),'Exact finite candidate dimensions required')
            require(type(tool['holder_dimensions_native']['HolderShape']) is int,'Strict holder shape required')
    requested=p.get('nc_operation_ids',[])
    nc=r.get('nc_parameters');require(type(nc) is list and len(nc)==len(requested) and all(type(x) is dict for x in nc) and [x.get('operation_native_id') for x in nc]==requested,'NC response selection differs')
    require(type(r.get('nc_parameters_complete')) is bool,'NC completion flag required')
    for row in nc:
        require(type(row) is dict and type(row['operation_native_id']) is int and row.get('status') in ('observed','error'),'NC result invalid')
        if row['status']=='observed':require(finite(row.get('spindle_speed_native')) and finite(row.get('feed_rate_ipm_native')),'Finite raw NC values required')
        else:require(type(row.get('hresult')) is int and type(row.get('stage')) is str and type(row.get('error_type')) is str,'Exact partial NC error required')
    require(r['nc_parameters_complete']==all(x['status']=='observed' for x in nc),'NC completion inconsistent')
    return r

def compare_reference(host,reference,p):
    require(reference.get('read_only') is True and reference.get('mutation_attempted') is False and reference.get('readback_verified') is True and reference.get('source_sha256')==p['expected_source_sha256'],'Verified same-source read reference required')
    require(reference.get('status')=='observed','Only completed observation is reference')
    state=reference['after'];require(reference['before']==state,'Unchanged reference read required')
    expected={k:deepcopy(state['inventory'][k]) for k in ('machine_type','operation_setup_count','operation_count','operations')};metadata={(x['setup_index'],x['operation_index']):x for x in expected['operations']}
    rows=[]
    for row in state['operations']:
        value=deepcopy(row);value.update({k:v for k,v in metadata[(row['setup_index'],row['operation_index'])].items() if k in ('toolpath_generated','toolpath_record_counts')});rows.append(value)
    expected['operations']=rows
    reference_doc=state['document'];fields={'path','title','type','needs_save'}
    require(set(reference_doc) in (fields,fields|{'configuration'}),'Known reference document schema required')
    configuration_compared='configuration' in reference_doc
    observed_doc={k:host['document_before'][k] for k in reference_doc}
    require(host['inventory']==expected and observed_doc==reference_doc,'Host observation differs from pinned reference')
    return {'verified':True,'scope':'operation_identity_order_links_and_path_metadata','configuration_compared':configuration_compared,'tool_geometry_compared':False,'CL_bytes_compared':False}

class NativeBackend:
    def __init__(self,p):self.p=p
    def owner(self):
        from scripts.sw_executable_launch import _process_identity
        return _process_identity(self.p['process_id'])
    def read_once(self,request_json):
        from ctypes import POINTER
        from comtypes import BSTR,typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        from scripts.sw_connect import connect_solidworks
        library=typeinfo.LoadTypeLibEx(self.p['host_tlb_path'],typeinfo.REGKIND_NONE);attr=library.GetLibAttr()
        require(str(attr.guid).upper()==HOST_LIBID and (attr.wMajorVerNum,attr.wMinorVerNum)==(1,0),'Exact host type library required')
        module=GetModule(library);interface=getattr(module,'ICamBatchReader');require(str(interface._iid_).upper()==READER_IID,'Exact reader interface required')
        methods=[m for m in interface._methods_ if m.name=='ReadTurnSnapshot'];require(len(methods)==1,'Unique reader ABI required');require_abi(methods[0],1,(BSTR,POINTER(BSTR)),(1,10))
        sw,_=connect_solidworks(process_id=self.p['process_id'],launch_new_instance=False,wait_seconds=1)
        require(_member(sw,'GetProcessID')==self.p['process_id'],'Bound SW PID differs')
        raw=_member(sw,'GetAddInObject',HOST_CLSID);require(raw is not None,'Reader add-in must already be loaded; no load fallback')
        pointer=_marshal_pywin32_unknown(raw).QueryInterface(interface)
        return pointer.ReadTurnSnapshot(request_json)

def run_read(params,*,backend=None):
    p=validate_params(params);pins=pins_for(p);check_files(pins);out=Path(p['receipt_path'])
    require(out.suffix.casefold()=='.json' and out.parent.is_dir() and not out.exists() and not out.is_symlink() and key(out) not in {key(x['path']) for x in pins},'Fresh nonaliased receipt required')
    reference=None
    if p['reference_receipt_path'] is not None:reference=decode(Path(p['reference_receipt_path']).read_text(encoding='utf-8-sig'))
    engine=backend or NativeBackend(p);r={'scope':SCOPE,'status':'prepared','phase':'prepared','request':p,'source_sha256':p['expected_source_sha256'],'read_only':True,'mutation_attempted':False,'model_saved':False,'GTP_attempted':False,'readback_verified':False,'batch_calls':0,'pins':pins,'client_module_sha256':digest(__file__)}
    _write_receipt(out,r,create=True);start=time.perf_counter()
    try:
        owner=engine.owner();check_owner(owner,p);r['owner_before']=owner;check_files(pins);r.update(phase='single_host_call',batch_calls=1,native_dispatch_pending=True);_write_receipt(out,r)
        text=engine.read_once(json.dumps(native_request(p),ensure_ascii=False));r['native_dispatch_pending']=False;r['host_response']=decode(text);validate_response(text,p)
        after=engine.owner();check_owner(after,p);require(after==owner,'Owner identity changed');check_files(pins);r['owner_after']=after
        require(r['host_response']['status']=='observed','Host returned an error; see host_response')
        if reference is not None:r['reference_comparison']=compare_reference(r['host_response'],reference,p)
        r.update(status='observed',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='error',phase='finished',issue=_error(exc),readback_verified=False)
    r['elapsed_seconds']=time.perf_counter()-start;_write_receipt(out,r);return r

def read_turn_snapshot(params):
    p=validate_params(params)
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):return run_read(p)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True);args=ap.parse_args();r=read_turn_snapshot(decode(Path(args.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:r[k] for k in ('status','phase','readback_verified','batch_calls','elapsed_seconds','issue') if k in r},ensure_ascii=False));raise SystemExit(0 if r['status']=='observed' else 2)
