"""Read the current TURN toolcrib after a verified first BORE insertion.

The first operation's tool lookup failed. This module reads no operation tool
reference and grants no insertion, assignment, generation or Save authority.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_named_bore_definitions as parent
from scripts import sw_cam_turn_toolcrib_diagnostic as reader
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=parent.common
SCOPE='PARTIAL_NAMED_BORE_TOOLCRIB_READ_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','parent_receipt_path','parent_receipt_sha256','receipt_path','module_sha256'}


def validate_partial(r,observed,resolved):
    p=r['request'];require(r['scope']==parent.SCOPE and r['status']=='uncertain' and r['phase']=='finished' and r['readback_verified'] is False and r['failed_phase']=='tool_reference_rough_bore','Exact first BORE tool-reference failure required')
    require(r['issue'].get('type')=='COMError' and r['issue'].get('hresult')==-2147220990,'Known unreadable tool-reference result required; different failure needs separate reconciliation')
    require(r['mutation_attempted'] is True and r['native_dispatch_pending'] is False and all(r[k] is False for k in parent.FORBIDDEN),'Only the first insertion may have been attempted')
    require(not any(k in r for k in ('cleanup_issue','phase_proof_error','after','final_tool_references')),'Unexpected completed/unclean state');clean_events(r)
    parent.validate_catalogue(observed,p,resolved);parent.verify_before(r['before'],observed,p,resolved)
    label='InsertOperation_rough_bore';require(set(r['actions'])=={label},'No second operation or other action allowed')
    a=r['actions'][label];require(a['attempted'] is True and a['returned'] is True and a['pending'] is False and a['readback_verified'] is False,'First insertion returned but tool gate did not complete')
    require(len(r['new_operations'])==len(r['insertion_observations'])==1 and not r.get('verified_tool_references') and not r.get('tool_reference_observations'),'No observed tool reference may be silently reused')
    row=r['new_operations'][0];state=r['insertion_observations'][0]
    require(a['new_native_id']==row['native_id'] and a['resolved_native_value']==row['turn_operation_type'],'Recorded inserted identity differs')
    require(parent.verify_added(r['before'],state,row['native_id'],'rough_bore',p['feature_native_id'],p['anchor_operation_native_id'],resolved)==row,'First insertion delta differs')
    return state


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_partial_bore_toolcrib','Exact read-only partial BORE action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact diagnostic parameters required')
    require(type(p['process_id']) is int and p['process_id']>0,'Strict owned PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact hash required')
    require(p['module_sha256']==_file_hash(__file__),'Reader changed');return p


def prepare(p):
    r,rpin=read_pin(p['parent_receipt_path'],p['parent_receipt_sha256']);q=r['request']
    require(q['process_id']==p['process_id'] and common._key(q['expected_document_path'])==common._key(p['expected_document_path']) and q['expected_source_sha256']==p['expected_source_sha256'],'Exact current owner/source required')
    loaded=parent.load_catalogue(q);reference=validate_partial(r,loaded['catalogue'],loaded['roles']);common._check(r['runtime_and_evidence_pins'])
    require(r['module_pin']==common._pin(parent.__file__),'Parent implementation changed')
    marker=parent.marker_path(q);claim,mpin=read_pin(str(marker),_file_hash(marker));require(claim==parent.claim_value(q),'Original durable once marker required')
    reg=parent.prior.catalogue.jobs._validate_registration(loaded['catalogue']['request']);abi=reader.audit(loaded['typelib_path'],loaded['generated_pin'])
    pins=common._merge(r['runtime_and_evidence_pins'],[rpin,mpin]+[common._pin(x.__file__) for x in (parent,reader,reader.profile,reader.batches,reader.collection_support)]+[common._pin(__file__)])
    require(len(pins)<=64,'Bounded diagnostic closure required');output=common._local_receipt(p['receipt_path'])
    require(output.parent.is_dir() and not output.exists() and not output.is_symlink() and common._key(output) not in {common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])},'Fresh nonaliased read-only receipt required')
    return dict(parent=r,reference=reference,catalogue=loaded['catalogue'],roles=loaded['roles'],pins=pins,typelib_path=loaded['typelib_path'],generated_pin=loaded['generated_pin'],registration=reg,abi=abi,output=output,parent_pin=rpin,marker_pin=mpin)


class NativeBackend(reader.NativeBackend):
    def start(self):
        initial=self.identity();require(initial==self.plan['reference']['document'],'Exact observed dirty/document state required');common._check(self.plan['pins'])
        addin=_member(self.sw,'GetAddInObject',self.plan['catalogue']['request']['addin_clsid']);require(addin is not None,'Existing CAM addin required')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.typelib);self.session=reader.prior.events.CamMessageSession(app,self.typelib);self.session.__enter__();self.active=True
        require(self.identity()==initial,'Initial binding changed');self.boundary()


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),operation_native_id=plan['parent']['new_operations'][0]['native_id'],operation_count=plan['reference']['inventory']['operation_count'],operation_tool_lookup_authorized=False,mutation_authorized=False)
    from scripts.sw_connect import connect_solidworks
    bp=dict(p,feature_native_id=plan['parent']['request']['feature_native_id'])
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,operation_inserted=False,tool_assignment_attempted=False,operation_tool_lookup_attempted=False,persistence_qualified=False,physical_tool_qualified=False,production_qualified=False,readback_verified=False,tools=[],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],runtime_and_evidence_pins=plan['pins'],parent_pin=plan['parent_pin'],marker_pin=plan['marker_pin'],abi=plan['abi'],limitations=['Read-only current RAM toolcrib after first valid BORE insertion and unavailable tool reference','No operation IGetTool, InsertOperation, SetTool, GTP or Save','Candidate means diamond boring-bar type only; physical tool/depth/access remain unqualified','Protected paths checked by route metadata and counts, not new CL hashes'])
        _write_receipt(plan['output'],r,create=True);persist=lambda:_write_receipt(plan['output'],r)
        return reader.run_backend(NativeBackend(sw,bp,plan,r,persist),plan,r,persist)


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True);ap.add_argument('--validate-only',action='store_true');a=ap.parse_args()
    r=dispatch_request(json.loads(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only)
    print(json.dumps({k:r[k] for k in ('scope','status','phase','readback_verified','native_called','pin_count','operation_native_id','operation_count','tool_ids','issue') if k in r},ensure_ascii=False,indent=2));raise SystemExit(0 if r['status'] in ('validated_offline','observed') else 2)
