"""Repair two existing TURN tool references once; no Save or generation.

The source is a RAM observation after a known CAM Save error. Successful tool
reference readback does not establish disk persistence or machining suitability.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_toolcrib_diagnostic as reader
from scripts import sw_cam_dispatch_guard as dispatch
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=reader.common
SCOPE='TURN_EXISTING_TOOL_REFERENCE_REPAIR_RAM_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','crib_receipt_path','crib_receipt_sha256','assignments','receipt_path','module_sha256','qualification_only','acknowledge_ram_only'}


def validate_assignments(rows):
    require(type(rows) is list and len(rows)==2,'Exactly one rough/finish reference pair required')
    for r in rows:
        require(type(r) is dict and set(r)=={'operation_native_id','operation_type','feature_native_id','tool_native_id'},'Exact assignment fields required')
        require(all(type(v) is int and 0<v<2**31 for v in r.values()),'Strict positive IDs/types required')
    require([r['operation_type'] for r in rows]==[1,2] and len({r['operation_native_id'] for r in rows})==2 and len({r['feature_native_id'] for r in rows})==1,'Distinct rough then finish on one feature required')


def observed_crib(r,p):
    require(r['scope']==reader.SCOPE and r['status']=='observed' and r['phase']=='finished' and r['readback_verified'] is True and r['read_only'] is True,'Completed read-only crib observation required')
    require(all(r[k] is False for k in ('mutation_attempted','model_saved','GTP_attempted','persistence_qualified','physical_tool_qualified','production_qualified')),'Diagnostic-only observation required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_error')),'Uncertain crib is not an assignment basis');clean_events(r)
    q=r['request'];require(q['process_id']==p['process_id'] and common._key(r['source_path'])==common._key(p['expected_document_path']) and r['source_sha256']==p['expected_source_sha256'],'Same owned source required')
    require(r['before']==r['after'] and r['before']['saved_file_sha256']==p['expected_source_sha256'],'Unchanged observed RAM reference required')
    validate_assignments(p['assignments']);tools={x['native_id']:x for x in r['tools']}
    require(len(tools)==len(r['tools']) and sorted(tools)==r['tool_ids'] and all(x['complete'] is True for x in tools.values()),'Complete unique observed toolcrib required')
    operations={x['native_id']:x for x in r['after']['operations']}
    for a in p['assignments']:
        op=operations[a['operation_native_id']];tool=tools[a['tool_native_id']]
        require(op['turn_operation_type']==a['operation_type'] and op['linked_feature_ids']==[a['feature_native_id']] and op['suppressed'] is False,'Exact unsuppressed operation/feature required')
        route=next(x for x in r['after']['inventory']['operations'] if x['setup_index']==op['setup_index'] and x['operation_index']==op['operation_index'])
        require(route['toolpath_generated'] is False and route['toolpath_record_counts']==[],'Only ungenerated targets may be repaired')
        require(tool['candidate'] is True and tool['tool_type_raw']==15 and tool['turn_tool_type_raw']==1 and tool['insert_type_raw']==1 and tool['holder_present'] is True and tool['holder_type_raw']==2,'Observed diamond boring-bar reference required')
        require(type(tool['insert_dimensions_native']) is dict and type(tool['holder_dimensions_native']) is dict,'Full observed candidate dimensions required')
    return tools


def marker_path(p):
    key=reader.prior._digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha256=p['expected_source_sha256'],targets=sorted((x['operation_native_id'],x['operation_type'],x['feature_native_id']) for x in p['assignments'])))
    return common.local_evidence_root()/('turn_tool_reference_'+key+'.json')


def audit(typelib,generated_pin):
    from ctypes import POINTER
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _load_type_library,_INTERFACES
    from scripts.sw_cam_face_interfaces import _verify_generated_class
    from scripts.sw_cam_pocket_rough_apply import require_abi
    lib=_load_type_library(typelib)
    rows=[]
    for name,member,ident,args,flags in [('ICWTurnOperation','SetTool',23,(POINTER(IDispatch),),(1,)),('ICWOperation','IGetTool',2,(POINTER(POINTER(IDispatch)),),(10,))]:
        cls=_verify_generated_class(getattr(lib,name),_INTERFACES[name],generated_pin)
        found=[x for x in cls._methods_ if x.name==member];require(len(found)==1,'Unique declared TURN binding required');require_abi(found[0],ident,args,flags)
        rows.append(dict(interface=name,member=member,dispid=ident))
    return dict(abi_verified=True,native_called=False,methods=rows)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='repair_turn_tool_references','Exact link-repair action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact parameters required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict PID required');validate_assignments(p['assignments'])
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True and p['acknowledge_ram_only'] is True,'Exact module and explicit RAM-only qualification required');return p


def prepare(p):
    observed,cpin=read_pin(p['crib_receipt_path'],p['crib_receipt_sha256']);tools=observed_crib(observed,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Source bytes changed')
    common._check(observed['runtime_and_evidence_pins'])
    parent,ppin=read_pin(observed['request']['parent_receipt_path'],observed['request']['parent_receipt_sha256'])
    require(parent['scope']==reader.prior.SCOPE and parent['final_state']==observed['before'],'Pinned insertion RAM observation differs')
    new={x['native_id']:x for x in parent['new_operations']}
    require(set(new)=={x['operation_native_id'] for x in p['assignments']},'Only exact inserted pair may be repaired')
    cat,catpin=read_pin(parent['catalogue_pin']['path'],parent['catalogue_pin']['sha256']);q=cat['request']
    generated=common._pin(q['generated_path']);require(generated['sha256']==q['generated_sha256'],'Generated ABI binding changed')
    reg=reader.prior.catalogue.jobs._validate_registration(q);abi=audit(q['typelib_path'],generated)
    pins=common._merge(observed['runtime_and_evidence_pins'],[cpin,ppin,catpin,common._pin(__file__),common._pin(reader.__file__)])
    require(len(pins)<=64 and common._key(p['expected_document_path']) not in {common._key(x['path']) for x in pins},'Bounded immutable closure excluding mutable source required')
    output=common._local_receipt(p['receipt_path']);marker=marker_path(p)
    forbidden={common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])}
    require(len({common._key(output),common._key(marker)})==2 and not forbidden.intersection((common._key(output),common._key(marker))),'Output aliases source/evidence')
    require(all(x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in (output,marker)),'Fresh receipt and no prior repair attempt required')
    return dict(observed=observed,reference=observed['after'],tools=tools,catalogue=cat,pins=pins,typelib_path=q['typelib_path'],generated_pin=generated,registration=reg,abi=abi,output=output,marker=marker)


def unchanged_route(before,after):
    expected=deepcopy(before);require(type(after['document']['needs_save']) is bool,'Strict dirty flag required')
    expected['document']['needs_save']=after['document']['needs_save']
    require(expected==after,'Reference assignment changed source or protected route metadata')


def expected_reference(a,tool):
    return dict(operation_native_id=a['operation_native_id'],tool_native_id=a['tool_native_id'],tool_type_raw=tool['tool_type_raw'],turn_tool_type_raw=tool['turn_tool_type_raw'],insert_type_raw=tool['insert_type_raw'],holder_type_raw=tool['holder_type_raw'],holder_id_raw=tool['holder_id_raw'])


class NativeBackend(reader.NativeBackend):
    def start(self):
        initial=self.identity();require(initial==self.plan['reference']['document'],'Exact observed dirty/document state required');common._check(self.plan['pins'])
        addin=_member(self.sw,'GetAddInObject',self.plan['catalogue']['request']['addin_clsid']);require(addin is not None,'Existing CAM addin required')
        app=reader._typed(_member(addin,'GetCWApp'),'ICWApp4',self.typelib)
        self.session=reader.prior.events.CamMessageSession(app,self.typelib);self.session.__enter__();self.active=True
        require(self.identity()==initial,'Initial binding changed');self.boundary()
    def tool_snapshot(self,label):
        self.report['tools']=[];ids=self.tools();value=deepcopy(self.report['tools'])
        self.report.setdefault('tool_observations',[]).append(dict(label=label,tool_ids=ids,tools=value,batch=deepcopy(self.report['read_batch'])));self.persist();return value
    def guard(self):
        current=self.identity();self.boundary()
        return dispatch.ScopedCamDispatchGuard(self.sw,self.typelib,process_id=self.p['process_id'],expected_document=current,source_sha256=self.source,evidence_pins=self.plan['pins'],verify_evidence=lambda:common._check(self.plan['pins']),verify_owned_process=self.owned,check_events=self.event_check)
    def assign(self,a,pending):
        with self.guard() as g:
            op=g.typed(self.native['operations'][a['operation_native_id']],'ICWTurnOperation')
            require(_object_id(self.native['doc'],op,g.read)==a['operation_native_id'] and g.read(op,'OpernType')==a['operation_type'],'Exact retained target changed')
            machine=g.typed(self.machine,'ICWMachine');crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4')
            handles=_items(g.read(crib,'GetAllTools'),g.typed,g.read,reader.MAX_TOOLS)
            matches=[v for v in handles if _object_id(self.native['doc'],v,g.read)==a['tool_native_id']]
            require(len(matches)==1,'Exact accepted tool is absent or duplicated')
            value=g.dispatch_once(lambda:_member(op,'SetTool',matches[0]),persist_pending=pending)
        self.report.setdefault('assignment_guards',[]).append(g.summary());return value
    def assigned(self,a):
        with self.guard() as g:
            op=g.typed(self.native['operations'][a['operation_native_id']],'ICWOperation')
            require(_object_id(self.native['doc'],op,g.read)==a['operation_native_id'],'Readback operation identity changed')
            raw=g.read(op,'IGetTool');require(raw is not None and bool(raw),'Assignment returned no tool reference')
            tool=g.typed(raw,'ICWTool')
            value=dict(operation_native_id=a['operation_native_id'],tool_native_id=_object_id(self.native['doc'],tool,g.read),tool_type_raw=g.read(tool,'ToolType'))
            self.report.setdefault('reference_readbacks',[]).append(value);self.persist()
            require(value['tool_native_id']==a['tool_native_id'] and type(value['tool_type_raw']) is int and value['tool_type_raw']==15,'Immediate tool ID/type differs')
            turn=g.typed(raw,'ICWTurnTool');value.update(turn_tool_type_raw=g.read(turn,'ToolType'));self.persist()
            require(type(value['turn_tool_type_raw']) is int and value['turn_tool_type_raw']==1,'Returned tool is not an insert holder')
            value['insert_type_raw']=g.read(turn,'InsertType');self.persist()
            require(type(value['insert_type_raw']) is int and value['insert_type_raw']==1,'Returned insert is not diamond')
            holder=g.typed(g.read(turn,'IGetTurnToolHolder'),'ICWTurnToolHolder')
            value.update(holder_type_raw=g.read(holder,'GetHolderType'),holder_id_raw=g.read(holder,'GetHolderId'));self.persist()
            require(all(type(x) is int for x in value.values()),'Strict native ID/type readback required')
        return value


def run_backend(backend,p,plan,r,persist,claim):
    claimed=False
    def pending(label):
        nonlocal claimed
        require(label not in r['actions'],'No repeated native setter')
        if not claimed:claim();claimed=True
        r.update(phase=label,mutation_attempted=True,native_dispatch_pending=True)
        r['actions'][label]=dict(attempted=True,pending=True,returned=False,readback_verified=False);persist()
    try:
        backend.start();r['phase']='before';r['before']=backend.capture('before');persist()
        require(r['before']==plan['reference'],'Current RAM reference changed')
        r['tools_before']=backend.tool_snapshot('before');require(r['tools_before']==plan['observed']['tools'],'Actual toolcrib changed before repair');persist()
        for a in p['assignments']:
            label='SetTool_'+str(a['operation_native_id'])
            result=backend.assign(a,lambda label=label:pending(label))
            r['actions'][label].update(returned=True,pending=False,native_return=result);r['native_dispatch_pending']=False;persist()
            require(type(result) is int and result==0,'Strict successful TURN SetTool HRESULT required')
            actual=backend.assigned(a);r['actions'][label]['observed']=actual;persist()
            require(actual==expected_reference(a,plan['tools'][a['tool_native_id']]),'Immediate assigned tool reference differs')
            r['actions'][label]['readback_verified']=True
            state=backend.capture(label+'_readback');r.setdefault('route_observations',[]).append(state);persist();unchanged_route(r['before'],state)
        r['phase']='final_readback';r['references_after']=[backend.assigned(a) for a in p['assignments']]
        require(r['references_after']==[expected_reference(a,plan['tools'][a['tool_native_id']]) for a in p['assignments']],'Final pair references differ')
        r['tools_after']=backend.tool_snapshot('after');require(r['tools_after']==r['tools_before'],'Tool geometry or crib changed')
        r['after']=backend.capture('after');persist();unchanged_route(r['before'],r['after'])
        backend.finish();r.update(status='repaired_ram_no_save',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',cleanup_error=_error(exc),readback_verified=False)
        persist()
    return r


def validate_repaired(r,observed):
    require(r['scope']==SCOPE and r['status']=='repaired_ram_no_save' and r['phase']=='finished' and r['readback_verified'] is True,'Completed RAM-only reference repair required')
    require(r['mutation_attempted'] is True and r['native_dispatch_pending'] is False and not any(k in r for k in ('issue','failed_phase','cleanup_error')),'Uncertain repair cannot authorize continuation')
    require(all(r[k] is False for k in ('model_saved','GTP_attempted','GOP_attempted','tool_geometry_changed','operation_inserted','automatic_retry','automatic_replay','persistence_qualified','physical_tool_qualified','production_qualified')),'Repair authority must remain RAM-only')
    clean_events(r);p=r['request'];tools=observed_crib(observed,p)
    require(r['source_path']==p['expected_document_path'] and r['source_sha256']==p['expected_source_sha256'],'Receipt source binding differs')
    require(r['before']==observed['after'],'Repair baseline differs');unchanged_route(r['before'],r['after'])
    require(r['tools_before']==r['tools_after']==observed['tools'],'Tool definitions changed')
    expected=[expected_reference(a,tools[a['tool_native_id']]) for a in p['assignments']]
    require(r['references_after']==expected and r['accepted_candidate_rows']==[tools[a['tool_native_id']] for a in p['assignments']],'Final tool references/candidate fingerprints differ')
    require(set(r['actions'])=={'SetTool_'+str(a['operation_native_id']) for a in p['assignments']},'Only two tool assignments may have occurred')
    for a,wanted in zip(p['assignments'],expected):
        row=r['actions']['SetTool_'+str(a['operation_native_id'])]
        require(row['attempted'] is True and row['returned'] is True and row['pending'] is False and row['readback_verified'] is True and type(row['native_return']) is int and row['native_return']==0 and row['observed']==wanted,'Each assignment needs strict native return and immediate readback')
    require(len(r['route_observations'])==2,'Two immediate route observations required')
    for state in r['route_observations']:unchanged_route(r['before'],state)
    return tools


def load_repaired(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,rpin=read_pin(path,digest);p=r['request']
    require(p['process_id']==process_id and common._key(p['expected_document_path'])==common._key(expected_document_path) and p['expected_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Same current source/owner required')
    observed,cpin=read_pin(p['crib_receipt_path'],p['crib_receipt_sha256']);tools=validate_repaired(r,observed)
    common._check(r['runtime_and_evidence_pins'])
    marker=marker_path(p);claim,mpin=read_pin(str(marker),_file_hash(marker))
    require(claim==dict(scope=SCOPE,status='claimed_no_replay',source_sha256=p['expected_source_sha256'],assignments=p['assignments'],receipt_path=p['receipt_path']),'Durable repair marker differs')
    parent,_=read_pin(observed['request']['parent_receipt_path'],observed['request']['parent_receipt_sha256'])
    cat,_=read_pin(parent['catalogue_pin']['path'],parent['catalogue_pin']['sha256'])
    pins=common._merge(r['runtime_and_evidence_pins'],[rpin,cpin,mpin]);require(len(pins)<=64,'Bounded continuation pins required')
    return dict(authority='ram_tool_references_repaired_no_save',receipt=r,reference=r['after'],state=r['after'],assignments=p['assignments'],references=r['references_after'],tool_snapshot=r['tools_after'],tools=tools,source_path=expected_document_path,source_sha256=expected_source_sha256,catalogue=cat,typelib_path=cat['request']['typelib_path'],pins=pins,persistence_qualified=False)


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),abi=plan['abi'],assignments=p['assignments'],save_authorized=False,GTP_authorized=False)
    from scripts.sw_connect import connect_solidworks
    bp=dict(p,feature_native_id=p['assignments'][0]['feature_native_id'])
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,actions={},mutation_attempted=False,native_dispatch_pending=False,readback_verified=False,model_saved=False,GTP_attempted=False,GOP_attempted=False,tool_geometry_changed=False,operation_inserted=False,automatic_retry=False,automatic_replay=False,persistence_qualified=False,physical_tool_qualified=False,production_qualified=False,source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],runtime_and_evidence_pins=plan['pins'],abi=plan['abi'],accepted_candidate_rows=[deepcopy(plan['tools'][x['tool_native_id']]) for x in p['assignments']],limitations=['RAM link repair only; source Save previously reported CAM data error','Default R0.4 and holder values are not physical or final-profile qualification','No Save/GTP/InsertOperation or tool geometry edits','Old path protection is counts/flags and route metadata, not CL byte hashes'])
        _write_receipt(plan['output'],r,create=True)
        persist=lambda:_write_receipt(plan['output'],r)
        def claim():_write_receipt(plan['marker'],dict(scope=SCOPE,status='claimed_no_replay',source_sha256=p['expected_source_sha256'],assignments=p['assignments'],receipt_path=p['receipt_path']),create=True)
        return run_backend(NativeBackend(sw,bp,plan,r,persist),p,plan,r,persist,claim)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:result[k] for k in ('scope','status','phase','readback_verified','pin_count','native_called','issue','cleanup_error') if k in result},ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status'] in ('validated_offline','repaired_ram_no_save') else 2)
