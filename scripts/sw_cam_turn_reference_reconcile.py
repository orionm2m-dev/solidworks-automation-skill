"""Read one attempted TURN tool reference after an uncertain setter return.

No assignment retry, generation, Save or recovery authority. The original
attempt receipt and its no-replay marker remain untouched.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_tool_reference_repair as repair
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=repair.common
SCOPE='TURN_UNCERTAIN_REFERENCE_READ_ONLY_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','failed_receipt_path','failed_receipt_sha256','receipt_path','module_sha256'}
KNOWN_UNAVAILABLE=-2147220990


def pending_assignment(failed):
    require(failed['scope']==repair.SCOPE and failed['status']=='uncertain' and failed['phase']=='finished' and failed['mutation_attempted'] is True and failed['readback_verified'] is False,'Terminal uncertain reference attempt required')
    require(failed['issue'].get('type')=='COMError' and failed['issue'].get('hresult')==-2147417851,'Observed RPC_E_SERVERFAULT attempt required')
    require(all(failed[k] is False for k in ('model_saved','GTP_attempted','GOP_attempted','tool_geometry_changed','operation_inserted','automatic_retry','automatic_replay','persistence_qualified')),'No unrelated mutation may have occurred')
    clean_events(failed);rows=failed['request']['assignments'];repair.validate_assignments(rows)
    require(set(failed['actions'])=={'SetTool_'+str(rows[0]['operation_native_id'])},'Exactly first assignment attempted; no second attempt permitted')
    a=failed['actions']['SetTool_'+str(rows[0]['operation_native_id'])]
    require(a==dict(attempted=True,pending=True,returned=False,readback_verified=False),'No completed return/readback expected')
    return deepcopy(rows[0])


def read_reference(op,doc,expected_tool_id,*,read,typed,publish):
    observation={'getter_attempted':True,'getter_returned':False,'binding_determined':False}
    publish(observation)
    try:raw=read(op,'IGetTool')
    except Exception as exc:
        observation.update(issue=_error(exc),outcome='tool_reference_unavailable');publish(observation)
        if getattr(exc,'hresult',None)!=KNOWN_UNAVAILABLE:raise
        return observation
    observation['getter_returned']=True
    observation['present']=raw is not None and bool(raw);publish(observation)
    if not observation['present']:
        observation.update(outcome='null_tool_reference_observed',binding_determined=True);publish(observation);return observation
    tool=typed(raw,'ICWTool');ident=_object_id(doc,tool,read)
    observation['tool_native_id']=ident;publish(observation)
    generic=read(tool,'ToolType');require(type(generic) is int,'Strict tool type required')
    info=read(tool,'GetToolInfoString');require(type(info) is str,'Tool info BSTR required')
    observation.update(tool_type_raw=generic,info_raw=info[:1000],binding_determined=True,outcome='desired_tool_reference_observed' if ident==expected_tool_id else 'different_tool_reference_observed');publish(observation)
    return observation


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_uncertain_turn_reference','Exact read-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    require(type(p['process_id']) is int and 0<p['process_id']<2**31,'Strict PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__),'Reader bytes changed');return p


def prepare(p):
    failed,fpin=read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);a=pending_assignment(failed);q=failed['request']
    require(q['process_id']==p['process_id'] and common._key(q['expected_document_path'])==common._key(p['expected_document_path']) and q['expected_source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path']),'Same current source and owner required')
    common._check(failed['runtime_and_evidence_pins'])
    observed,opin=read_pin(q['crib_receipt_path'],q['crib_receipt_sha256']);repair.observed_crib(observed,q)
    require(failed['before']==observed['after'] and failed['tools_before']==observed['tools'],'Pre-attempt observation differs')
    parent,ppin=read_pin(observed['request']['parent_receipt_path'],observed['request']['parent_receipt_sha256'])
    cat,cpin=read_pin(parent['catalogue_pin']['path'],parent['catalogue_pin']['sha256'])
    marker=repair.marker_path(q);claim,mpin=read_pin(str(marker),_file_hash(marker))
    require(claim==dict(scope=repair.SCOPE,status='claimed_no_replay',source_sha256=q['expected_source_sha256'],assignments=q['assignments'],receipt_path=q['receipt_path']),'Original no-replay marker differs')
    pins=common._merge(failed['runtime_and_evidence_pins'],[fpin,opin,ppin,cpin,mpin,common._pin(__file__),common._pin(repair.__file__)])
    require(len(pins)<=64,'Bounded reconciliation closure required')
    generated=common._pin(cat['request']['generated_path']);require(generated['sha256']==cat['request']['generated_sha256'],'Generated binding changed')
    abi=repair.audit(cat['request']['typelib_path'],generated)
    reg=repair.reader.prior.catalogue.jobs._validate_registration(cat['request'])
    out=common._local_receipt(p['receipt_path']);require(out.parent.is_dir() and not out.exists() and not out.is_symlink(),'Fresh existing-parent diagnostic receipt required')
    require(common._key(out) not in {common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])},'Diagnostic aliases source/evidence')
    return dict(failed=failed,assignment=a,reference=failed['before'],catalogue=cat,pins=pins,typelib_path=cat['request']['typelib_path'],generated_pin=generated,abi=abi,registration=reg,output=out)


class NativeBackend(repair.NativeBackend):
    def start(self):
        # The preceding attempted setter may have changed dirty state. Observe
        # it once, then use the existing exact-state startup guard thereafter.
        initial=self.identity();self.report['entry_document']=initial;self.persist()
        self.plan=dict(self.plan,reference=deepcopy(self.plan['reference']))
        self.plan['reference']['document']['needs_save']=initial['needs_save']
        super().start()
    def observe_reference(self,a):
        def publish(v):self.report['reference_observation']=deepcopy(v);self.persist()
        with self.guard() as g:
            op=g.typed(self.native['operations'][a['operation_native_id']],'ICWOperation')
            require(_object_id(self.native['doc'],op,g.read)==a['operation_native_id'],'Retained target identity changed')
            value=read_reference(op,self.native['doc'],a['tool_native_id'],read=g.read,typed=g.typed,publish=publish)
        self.report['reference_guard']=g.summary();return value


def run_backend(backend,plan,r,persist):
    try:
        backend.start();r['phase']='before';r['before']=backend.capture('before');persist()
        repair.unchanged_route(plan['reference'],r['before'])
        r['phase']='reference_read';r['reference_observation']=backend.observe_reference(plan['assignment']);persist()
        r['phase']='after';r['after']=backend.capture('after');persist()
        require(r['after']==r['before'],'Read changed observed route/source/dirty state')
        backend.finish();r.update(status='observed',phase='finished',readback_verified=True,protected_route_unchanged=True)
    except Exception as exc:r.update(status='error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='error',cleanup_error=_error(exc),readback_verified=False)
        persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),operation_native_id=plan['assignment']['operation_native_id'],IGetTool_max_calls=1,mutation_authorized=False)
    from scripts.sw_connect import connect_solidworks
    bp=dict(p,feature_native_id=plan['assignment']['feature_native_id'])
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,operation_inserted=False,assignment_attempted=False,persistence_qualified=False,production_qualified=False,readback_verified=False,source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],runtime_and_evidence_pins=plan['pins'],attempted_assignment=plan['assignment'],protected_route_unchanged=False,limitations=['One current reference observation only; setter RPC fault remains in immutable evidence','The second operation was not assigned and its known failed getter is not retried','No tool geometry or physical access qualification','No Save/GTP or authority to repeat the prior setter'])
        _write_receipt(plan['output'],r,create=True);persist=lambda:_write_receipt(plan['output'],r)
        return run_backend(NativeBackend(sw,bp,plan,r,persist),plan,r,persist)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    value=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:value[k] for k in ('scope','status','phase','readback_verified','native_called','pin_count','reference_observation','issue') if k in value},ensure_ascii=False,indent=2))
    raise SystemExit(0 if value['status'] in ('validated_offline','observed') else 2)
