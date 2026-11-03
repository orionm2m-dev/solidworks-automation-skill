"""One fixed owner-STA TURN bore create/bind/own-NC qualification on a disposable copy.

Prepare is offline. Use the existing read_turn_snapshot on the already-open copy
for baseline evidence. No tool factory, Save, GTP or per-document wrapper.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib,json,math,os,re,time,uuid
from scripts import sw_cam_inprocess_reader as reader
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
from scripts.sw_operation_guard import solidworks_operation_lock

SCOPE='TURN_OWNER_STA_BORE_CLIENT_V1'
NATIVE_SCOPE='TURN_OWNER_STA_BORE_QUALIFICATION_V1'
BUILDER_IID='{63CD9668-1A04-4D45-AC42-AD484D30F9EB}'
FIELDS={'process_id','expected_process_creation_time','expected_document_path','expected_source_sha256','protected_document_path','protected_source_sha256','protected_part_pins','qualification_root','host_dll_path','host_dll_sha256','host_tlb_path','host_tlb_sha256','expected_host_module_version_id','reference_receipt_path','reference_receipt_sha256','protected_cl_path','protected_cl_sha256','selected_tool_id','feature_id','anchor_id','default_name','default_id','max_tools','native_receipt_path','receipt_path','module_sha256','qualification_only','acknowledge_ram_only'}
require=reader.require
key=reader.key
digest=reader.digest

def pinned(path,sha):
    q=Path(path);reader.check_files([{'path':str(q),'sha256':sha}]);return reader.decode(q.read_text(encoding='utf-8-sig'))

def under(path,root):
    return key(path).startswith(key(root).rstrip('\\')+'\\')

def validate_params(params):
    require(type(params) is dict and set(params)==FIELDS,'Exact qualification parameters required');p=deepcopy(params)
    for n in ('process_id','selected_tool_id','feature_id','anchor_id','default_id'):require(type(p[n]) is int and 0<p[n]<2**31,'Strict positive identity required')
    require(type(p['max_tools']) is int and 1<=p['max_tools']<=64,'Tools bound1..64 required')
    require(reader.finite(p['expected_process_creation_time']) and p['expected_process_creation_time']>0,'Exact process lifetime required')
    for n,v in p.items():
        if n.endswith('_path') or n=='qualification_root':require(type(v) is str and Path(v).is_absolute() and len(v)<=32767,'Absolute bounded paths required')
        if n.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact lowercase SHA256 required')
    p['expected_host_module_version_id']=str(uuid.UUID(p['expected_host_module_version_id']))
    require(type(p['default_name']) is str and 0<len(p['default_name'])<=1000,'Observed named default required')
    require(p['qualification_only'] is True and p['acknowledge_ram_only'] is True,'Qualification RAM-only acknowledgement required')
    require(p['module_sha256']==digest(__file__),'Exact implementation pin required')
    require(p['expected_source_sha256']==p['protected_source_sha256'],'Copy must initially equal protected baseline')
    require(under(p['expected_document_path'],p['qualification_root']) and not under(p['protected_document_path'],p['qualification_root']),'Separate qualification root required')
    for n in ('expected_document_path','protected_document_path'):require(Path(p[n]).suffix.lower()=='.sldprt','Part files required')
    for n in ('receipt_path','native_receipt_path'):require(Path(p[n]).suffix.lower()=='.json' and under(p[n],p['qualification_root']),'Receipts must be in qualification root')
    q=p['protected_part_pins'];require(type(q) is list and 1<=len(q)<=8,'Bounded protected working/archive pins required')
    for x in q:require(type(x) is dict and set(x)=={'path','sha256'} and type(x['path']) is str and Path(x['path']).is_absolute() and type(x['sha256']) is str and re.fullmatch('[0-9a-f]{64}',x['sha256']),'Exact protected pin required')
    require(len({key(x['path']) for x in q})==len(q),'Unique protected pins required')
    require(any(key(x['path'])==key(p['protected_document_path']) and x['sha256']==p['protected_source_sha256'] for x in q),'Primary working source must be protected')
    require(all(key(x['path'])!=key(p['expected_document_path']) for x in q),'Qualification copy cannot be an immutable/protected file')
    return p

def reader_params(p):
    return dict(process_id=p['process_id'],expected_process_creation_time=p['expected_process_creation_time'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'],host_dll_path=p['host_dll_path'],host_dll_sha256=p['host_dll_sha256'],host_tlb_path=p['host_tlb_path'],host_tlb_sha256=p['host_tlb_sha256'],expected_host_module_version_id=p['expected_host_module_version_id'],max_operations=64,max_tools=p['max_tools'],receipt_path=p['reference_receipt_path'],reference_receipt_path=None,reference_receipt_sha256=None,nc_operation_ids=[])

def marker_path(p):
    q=Path(p['expected_document_path']);return q.parent/('.'+q.name+'.turn-bore-qualification.once.json')

def prepare(params):
    p=validate_params(params)
    pins=[{'path':p[a],'sha256':p[b]} for a,b in (('expected_document_path','expected_source_sha256'),('host_dll_path','host_dll_sha256'),('host_tlb_path','host_tlb_sha256'),('reference_receipt_path','reference_receipt_sha256'),('protected_cl_path','protected_cl_sha256'))]+deepcopy(p['protected_part_pins'])+[{'path':str(Path(__file__).resolve()),'sha256':p['module_sha256']}]
    require(len({key(x['path']) for x in pins})==len(pins),'Pinned files may not alias');reader.check_files(pins)
    require(all(not os.path.samefile(p['expected_document_path'],x['path']) for x in p['protected_part_pins']),'Copy aliases protected file identity')
    outputs=[p['receipt_path'],p['native_receipt_path'],str(marker_path(p))]
    require(len({key(x) for x in outputs})==3 and not {key(x) for x in outputs}.intersection(key(x['path']) for x in pins),'Output aliases protected input')
    require(all(Path(x).parent.is_dir() and not Path(x).exists() and not Path(x).is_symlink() for x in outputs),'Fresh receipts and no previous attempt required')
    baseline=pinned(p['reference_receipt_path'],p['reference_receipt_sha256']);rp=reader_params(p)
    require(baseline.get('scope')==reader.SCOPE and baseline.get('status')=='observed' and baseline.get('phase')=='finished' and baseline.get('read_only') is True and baseline.get('mutation_attempted') is False and baseline.get('readback_verified') is True and baseline.get('batch_calls')==1 and baseline.get('native_dispatch_pending') is False,'Completed copy snapshot required')
    require(baseline.get('source_sha256')==p['expected_source_sha256'],'Snapshot source differs')
    for n in ('process_id','expected_process_creation_time','expected_document_path','expected_source_sha256','host_dll_path','host_dll_sha256','host_tlb_path','host_tlb_sha256','expected_host_module_version_id','max_tools'):
        actual=baseline['request'][n];require(key(actual)==key(p[n]) if n.endswith('_path') else actual==p[n],'Snapshot binding differs: '+n)
    reader.check_owner(baseline['owner_before'],p);reader.check_owner(baseline['owner_after'],p);require(baseline['owner_before']==baseline['owner_after'],'Snapshot owner drift')
    native=baseline['host_response'];reader.validate_response(json.dumps(native),rp)
    require(native['document_before']['needs_save'] is False and native['nc_parameters']==[],'Clean copy snapshot without extra NC reads required')
    inventory=native['inventory'];require(inventory['operation_setup_count']==1 and inventory['operation_count']<64,'One bounded setup required')
    rows=inventory['operations'];anchor=[x for x in rows if x['native_id']==p['anchor_id']];require(len(anchor)==1 and anchor[0]['turn_operation_type']==9 and anchor[0]['linked_feature_ids']==[p['feature_id']] and anchor[0]['suppressed'] is False,'Exact internal drill anchor required')
    require(not any(x['turn_operation_type'] in (5,6) and p['feature_id'] in x['linked_feature_ids'] for x in rows),'Existing bore prohibits repeated qualification')
    tools=native['tools'];selected=[x for x in tools if x['native_id']==p['selected_tool_id']];require(len(selected)==1 and selected[0]['candidate'] is True and selected[0]['insert_dimensions_native']['IncludedAngle']==80,'Current-copy80-degree boring tool required; no factory fallback')
    request=dict(schema_version=1,expected_process_id=p['process_id'],expected_process_creation_time=p['expected_process_creation_time'],expected_document_path=p['expected_document_path'],expected_source_sha256=p['expected_source_sha256'],protected_document_path=p['protected_document_path'],protected_source_sha256=p['protected_source_sha256'],protected_part_pins=p['protected_part_pins'],qualification_root=p['qualification_root'],expected_sw_configuration=native['document_before']['configuration'],expected_cam_configuration=native['cam_configuration'],expected_inventory=inventory,expected_tools=tools,selected_tool_id=p['selected_tool_id'],feature_id=p['feature_id'],anchor_id=p['anchor_id'],default_name=p['default_name'],default_id=p['default_id'],max_tools=p['max_tools'],native_receipt_path=p['native_receipt_path'],expected_host_module_version_id=p['expected_host_module_version_id'])
    return dict(params=p,pins=pins,native_request=request,baseline_snapshot=baseline,marker_path=str(marker_path(p)))

def validate_host(host,p,plan):
    require(type(host) is dict and host.get('schema_version')==1 and host.get('scope')==NATIVE_SCOPE and host.get('engine_version')=='turn-bore-builder-1','Native builder protocol differs')
    require(host.get('process_id')==p['process_id'] and host.get('host_module_version_id')==p['expected_host_module_version_id'] and key(host.get('host_assembly_location',''))==key(p['host_dll_path']),'Native host identity differs')
    require(host.get('status') in ('error','uncertain','created_bound_nc_read_ram_only'),'Unknown native status')
    for n in ('model_saved','GTP_attempted','GOP_attempted','tool_creation_attempted','existing_tool_edit_attempted','persistence_qualified','physical_tool_qualified','production_qualified','protected_CL_bytes_compared'):require(host.get(n) is False,'Unexpected native scope '+n)
    if host['status']!='created_bound_nc_read_ram_only':require(host.get('readback_verified') is False,'Failure cannot be verified');return False
    require(host.get('stage')=='finished' and host.get('readback_verified') is True and host.get('native_dispatch_pending') is False and not any(k in host for k in ('hresult','error_type','message','cleanup_error','failed_stage')),'Incomplete successful native result')
    for n in ('mutation_attempted','insert_attempted','insert_returned','bind_attempted','bind_returned','own_read_attempted','own_read_returned'):require(host.get(n) is True,'Missing native stage '+n)
    nr=plan['native_request'];before=host['before'];after=host['after'];require(before['inventory']==nr['expected_inventory'] and before['tools']==nr['expected_tools'],'Native before differs from pinned copy snapshot')
    expected=deepcopy(before['inventory']);new=host['new_operation_id'];require(type(new) is int and new>0 and all(x['native_id']!=new for x in expected['operations']),'Fresh new operation ID required')
    at=next(i for i,x in enumerate(expected['operations']) if x['native_id']==p['anchor_id'])+1
    for row in expected['operations'][at:]:row['operation_index']+=1
    added=dict(setup_index=0,operation_index=at,native_id=new,turn_operation_type=5,linked_feature_ids=[p['feature_id']],suppressed=False,toolpath_generated=False,toolpath_record_counts=[])
    expected['operations'].insert(at,added);expected['operation_count']+=1
    require(host['after_insert']['inventory']==expected and after['inventory']==expected,'Unexpected operation/path delta')
    bd=before['document'];ad=after['document'];reader.validate_document(bd,reader_params(p));reader.validate_document(ad,reader_params(p));require(bd['needs_save'] is False,'Dirty initial copy');bd=deepcopy(bd);bd['needs_save']=ad['needs_save'];require(bd==ad and before['configuration']==after['configuration'],'Native document/configuration drift')
    for state in (host['after_insert'],after):
        ts=state['tools'];require(type(ts) is list and len(ts)<=p['max_tools'] and len({x['native_id'] for x in ts})==len(ts),'Bounded unique crib rows required')
        for old in before['tools']:require([x for x in ts if x['native_id']==old['native_id']]==[old],'Preexisting tool changed')
    own=host['own_readback'];require(own['operation_native_id']==new and own['tool_native_id']==p['selected_tool_id'] and own['stage']=='finished' and all(own.get(k) is True for k in ('tool_getter_attempted','tool_getter_returned','tool_present','nc_getter_attempted','nc_getter_returned','nc_present','nc_interface_verified')),'Own tool/NC evidence incomplete')
    require(reader.finite(own.get('spindle_speed_native')) and reader.finite(own.get('feed_rate_ipm_native')) and own.get('units_qualified') is False,'Raw NC values required')
    m=host['messages'];require(m.get('subscribed') is True and m.get('disconnected') is True and m.get('active') is False and m.get('event_count')==0 and m.get('overflow')==0 and m.get('callback_error_count')==0 and m.get('cleanup_error') is None,'CAM event/cleanup not quiet')
    require(Path(plan['marker_path']).is_file(),'Durable attempt marker missing')
    marker=reader.decode(Path(plan['marker_path']).read_text(encoding='utf-8-sig'));expected=dict(scope=NATIVE_SCOPE,status='claimed_no_replay',copy=p['expected_document_path'],sha256=p['expected_source_sha256'],feature_id=p['feature_id'],anchor_id=p['anchor_id'],receipt=p['native_receipt_path'])
    require(type(marker) is dict and set(marker)==set(expected),'Durable marker schema differs')
    require(all(key(marker[k])==key(expected[k]) if k in ('copy','receipt') else marker[k]==expected[k] for k in expected),'Durable marker binding differs')
    recorded=reader.decode(Path(p['native_receipt_path']).read_text(encoding='utf-8-sig'));sent=deepcopy(host);sent.pop('elapsed_ms',None);require(recorded==sent,'Native durable receipt differs from return')
    return True

class NativeBackend(reader.NativeBackend):
    def invoke_once(self,request_json):
        from ctypes import POINTER
        from comtypes import BSTR,typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        from scripts.sw_connect import connect_solidworks
        library=typeinfo.LoadTypeLibEx(self.p['host_tlb_path'],typeinfo.REGKIND_NONE);attr=library.GetLibAttr();require(str(attr.guid).upper()==reader.HOST_LIBID and (attr.wMajorVerNum,attr.wMinorVerNum)==(1,0),'Exact host TLB required')
        module=GetModule(library);interface=module.ICamTurnBoreBuilder;require(str(interface._iid_).upper()==BUILDER_IID,'Builder IID mismatch');members=[x for x in interface._methods_ if x.name=='QualifyCreateBoundTurnBore'];require(len(members)==1,'Unique builder method required');require_abi(members[0],1,(BSTR,POINTER(BSTR)),(1,10))
        sw,_=connect_solidworks(process_id=self.p['process_id'],launch_new_instance=False,wait_seconds=1);require(reader._member(sw,'GetProcessID')==self.p['process_id'],'Bound SW PID differs');raw=reader._member(sw,'GetAddInObject',reader.HOST_CLSID);require(raw is not None,'Pinned host must already be loaded; no loader fallback')
        pointer=_marshal_pywin32_unknown(raw).QueryInterface(interface);return pointer.QualifyCreateBoundTurnBore(request_json)

def run(params,*,backend=None):
    plan=prepare(params);p=plan['params'];engine=backend or NativeBackend(p);out=Path(p['receipt_path']);result=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,source_sha256=p['expected_source_sha256'],pins=plan['pins'],native_request=plan['native_request'],mutation_attempted=False,attempt_marker_meaning='Client intent before host dispatch; host_response stage flags establish actual native entry.',model_saved=False,GTP_attempted=False,readback_verified=False,persistence_qualified=False,physical_tool_qualified=False,production_qualified=False,batch_calls=0,protected_CL_bytes_compared=False)
    _write_receipt(out,result,create=True);start=time.perf_counter()
    try:
        owner=engine.owner();reader.check_owner(owner,p);result['owner_before']=owner;reader.check_files(plan['pins']);require(not Path(plan['marker_path']).exists(),'Prior attempt marker appeared')
        result.update(phase='single_owner_sta_call',batch_calls=1,mutation_attempted=True,native_dispatch_pending=True);_write_receipt(out,result)
        text=engine.invoke_once(json.dumps(plan['native_request'],ensure_ascii=False));result['native_dispatch_pending']=False;host=reader.decode(text);result['host_response']=host
        accepted=validate_host(host,p,plan);after=engine.owner();reader.check_owner(after,p);require(after==owner,'Owner changed');result['owner_after']=after;reader.check_files(plan['pins'])
        result.update(status='created_bound_nc_read_ram_only' if accepted else host['status'],phase='finished',readback_verified=accepted)
    except Exception as exc:result.update(status='uncertain' if result['mutation_attempted'] else 'error',phase='finished',issue=_error(exc),readback_verified=False)
    result['elapsed_seconds']=time.perf_counter()-start;_write_receipt(out,result);return result

def dispatch_request(request,*,validate_only=False,backend=None):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='qualify_create_bound_turn_bore','Exact fixed qualification action required')
    if validate_only:
        p=prepare(request['params']);return dict(status='validated_offline',native_called=False,native_request=p['native_request'],marker_path=p['marker_path'],tool_creation_supported=False,save_authorized=False,GTP_authorized=False,pins=p['pins'])
    p=validate_params(request['params'])
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):return run(p,backend=backend)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True);ap.add_argument('--validate-only',action='store_true');a=ap.parse_args();r=dispatch_request(reader.decode(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only);print(json.dumps({k:r[k] for k in ('status','phase','readback_verified','batch_calls','elapsed_seconds','issue') if k in r},ensure_ascii=False));raise SystemExit(0 if r['status'] in ('validated_offline','created_bound_nc_read_ram_only') else 2)
