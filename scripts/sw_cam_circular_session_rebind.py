"""Read-only association of an unchanged saved circular pocket with a new PID."""
from copy import deepcopy
from pathlib import Path
import math, re
from scripts import sw_cam_current_circular_authority as authority
from scripts.sw_cam_current_circular_continuation import CircularBatchContext
from scripts.sw_cam_current_circular_context import preflight
from scripts import sw_cam_current_saved_parameter_batch as batch
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import clean_events, read_pin

SCOPE = 'SAVED_CIRCULAR_POCKET_SESSION_REBIND_V1'
require = authority.require
KEYS = {'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','pocket_receipt_path','pocket_receipt_sha256','expected_feature_native_id','expected_operation_native_id','expected_operation_native_ids','expected_generated_operation_count','expected_total_record_count','receipt_path'}

def validate(v, *, require_new_output=True, check_current_source=True):
    require(type(v) is dict and set(v)==KEYS, 'Exact read-only rebind fields required')
    for k in ('process_id','expected_feature_native_id','expected_operation_native_id'):
        require(type(v[k]) is int and 0<v[k]<2**31, 'Strict positive identity required: '+k)
    t=v['expected_process_create_time']
    require(type(t) in (int,float) and math.isfinite(t) and t>0, 'Exact current lifetime required')
    for k in ('expected_source_sha256','pocket_receipt_sha256'):
        require(type(v[k]) is str and re.fullmatch('[0-9a-f]{64}',v[k]), 'Exact SHA required')
    ids=v['expected_operation_native_ids']
    require(type(ids) is list and 1<=len(ids)<=32 and all(type(x) is int and 0<x<2**31 for x in ids) and len(set(ids))==len(ids), 'Exact ordered operation IDs required')
    for k,b in (('expected_generated_operation_count',32),('expected_total_record_count',100000)):
        require(type(v[k]) is int and 0<=v[k]<=b, 'Strict bounded count required')
    p=Path(v['expected_document_path'])
    require(p.is_absolute() and p.suffix.lower()=='.sldprt' and p.is_file() and not p.is_symlink() and (not check_current_source or _file_hash(p)==v['expected_source_sha256']), 'Exact unchanged saved source required')
    out=Path(v['receipt_path'])
    require(out.is_absolute() and out.suffix.lower()=='.json' and out.parent.is_dir() and (not out.exists() if require_new_output else out.is_file()) and not out.is_symlink(), 'Fresh or pinned receipt required')
    return out

def verify_scope(s,v):
    require(all(s.get(k) is True for k in ('capture_complete','extended_capture_complete','parameter_capture_complete')), 'Complete circular capture required')
    require(s['document']['needs_save'] is False and s['sketch_state']['needs_save'] is False, 'Clean saved state required')
    rows=s['operations']
    require([r['native_id'] for r in rows]==v['expected_operation_native_ids'], 'Operation order differs')
    require(sum(r['toolpath_generated'] for r in rows)==v['expected_generated_operation_count'] and sum(sum(r['toolpath_record_counts']) for r in rows)==v['expected_total_record_count'], 'Saved path/record count differs')
    target=[r for r in rows if r['native_id']==v['expected_operation_native_id']]
    require(len(target)==1 and target[0]['linked_feature_ids']==[v['expected_feature_native_id']] and target[0]['mill_operation_type']==0 and target[0]['toolpath_generated'] is False and target[0]['toolpath_record_counts']==[], 'Exact ungenerated target rough required')
    require(s['target_header']['native_id']==v['expected_feature_native_id'], 'Pocket identity differs')

def load_inputs(v,clsid):
    out=validate(v);old,pin=read_pin(v['pocket_receipt_path'],v['pocket_receipt_sha256']);b=old['binding']
    require(b['process_id']!=v['process_id'] and b['expected_process_create_time']!=v['expected_process_create_time'], 'Distinct historical/current session required')
    h=authority.load_pocket(pin['path'],pin['sha256'],process_id=b['process_id'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'])
    require(h['addin_clsid']==clsid, 'Historical CAM registration differs')
    require(h['restore']['new_feature_native_id']==v['expected_feature_native_id'] and [r['native_id'] for r in h['restore']['new_operations']]==[v['expected_operation_native_id']], 'Historical target differs')
    require(h['state']['sketch_state']['pid']==b['process_id'], 'Historical snapshot PID differs')
    verify_scope(h['state'],v)
    pins=deepcopy(h['pins']);pins['pocket']=pin
    protected={Path(p['path']).resolve() for p in pins.values()}
    require(out.resolve() not in protected and out.resolve()!=Path(v['expected_document_path']).resolve(), 'Output aliases immutable input')
    return dict(circular=h,baseline=deepcopy(h['state']),pins={'pocket':pin},protected_pins=pins,definition_mode=batch.load_inputs(h['original']['binding'],clsid)['authority']['definition_mode'])

class ReadOnlyRebindContext(CircularBatchContext):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        # Parent constructor only reads files. Historical bindings stay untouched.
        # Only the separate live reader identity changes before __enter__.
        for current in (self.v,self.request):
            current['process_id']=v['process_id']
            current['expected_process_create_time']=v['expected_process_create_time']
    def guard(self):raise ValueError('Read-only rebind cannot dispatch mutations')
    def save(self,*a,**k):raise ValueError('Read-only rebind cannot save')
    def set_tool(self,*a,**k):raise ValueError('Read-only rebind cannot assign tools')
    def set_field(self,*a,**k):raise ValueError('Read-only rebind cannot modify parameters')

def verify_observations(r,data,v):
    historical_pid=data['baseline']['sketch_state']['pid']
    require(type(historical_pid) is int and historical_pid!=v['process_id'], 'Historical sketch PID differs')
    for name in ('before','after'):
        verify_scope(r[name],v)
        require(type(r[name]['sketch_state']['pid']) is int and r[name]['sketch_state']['pid']==v['process_id'], 'Live sketch PID differs')
        projected=deepcopy(r[name]);projected['sketch_state']['pid']=historical_pid
        require(authority.circular_state_equal(data['baseline'],projected), 'Current circular state differs from history: '+name)
    require(authority.circular_state_equal(r['before'],r['after']), 'Repeated current observations differ')

def run_rebind(sw,clsid,typelib_path,*,runtime_check,_loader=load_inputs,_context_factory=ReadOnlyRebindContext,_preflight=preflight,**v):
    data=_loader(v,clsid);h=data['circular'];runtime_check()
    abi=_preflight(typelib_path,data['definition_mode'])
    r=dict(scope=SCOPE,status='running',phase='preflight',request=deepcopy(v),historical_pocket_pin=deepcopy(h['pin']),historical_process_id=h['binding']['process_id'],historical_process_create_time=h['binding']['expected_process_create_time'],process_id=v['process_id'],expected_process_create_time=v['expected_process_create_time'],source_sha256=v['expected_source_sha256'],historical_receipt_modified=False,mutation_attempted=False,save_attempted=False,GOP_attempted=False,GTP_attempted=False,AFR_attempted=False,production_qualified=False,session_rebind_verified=False,readback_verified=False,runtime_unchanged=False,native_read_count=0,captures=[],native_interface_audit=abi,module_sha256=_file_hash(__file__))
    def persist():_write_receipt(Path(v['receipt_path']),r)
    _write_receipt(Path(v['receipt_path']),r,create=True)
    c=None
    try:
        with _context_factory(sw,clsid,typelib_path,v,data,r,persist,runtime_check) as c:
            r['before']=c.capture('before');r['after']=c.capture('after')
            verify_observations(r,data,v);c.boundary()
        r['messages']=c.session.summary();clean_events(r)
        require(c.identity()==r['after']['document'], 'Identity changed after cleanup')
        runtime_check()
        require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'], 'Saved source changed')
        for p in data['protected_pins'].values():require(read_pin(p['path'],p['sha256'])[1]==p, 'Historical evidence changed')
        r.update(status='observed',phase='finished',session_rebind_verified=True,readback_verified=True,runtime_unchanged=True,state_sha256=_digest(r['before']))
    except Exception as exc:
        r.update(status='error',failed_phase=r['phase'],phase='finished',issue=dict(type=type(exc).__name__,message=str(exc)),session_rebind_verified=False,readback_verified=False)
    if c is not None and c.session is not None:r['messages']=c.session.summary()
    persist();return r



def load_verified_rebind(path, sha, *, process_id, source_path, source_sha256):
    """Consume a separate proven association; retain historical bindings intact."""
    r,pin=read_pin(path,sha)
    require(r.get('scope')==SCOPE and r.get('status')=='observed' and r.get('phase')=='finished'
        and r.get('session_rebind_verified') is True and r.get('readback_verified') is True
        and r.get('runtime_unchanged') is True, 'Completed read-only association required')
    require(not any(k in r for k in ('issue','failed_phase','runtime_error','receipt_write_error')), 'Failed association rejected')
    for k in ('historical_receipt_modified','mutation_attempted','save_attempted','GOP_attempted','GTP_attempted','AFR_attempted','production_qualified'):
        require(r.get(k) is False, 'Unexpected association side effect: '+k)
    require(r.get('module_sha256')==_file_hash(__file__), 'Association implementation changed')
    v=r['request'];validate(v,require_new_output=False,check_current_source=False)
    require(Path(v['receipt_path']).resolve()==Path(path).resolve(), 'Association receipt path differs')
    require(type(process_id) is int and v['process_id']==process_id and r['process_id']==process_id
        and Path(v['expected_document_path']).resolve()==Path(source_path).resolve()
        and v['expected_source_sha256']==r['source_sha256']==source_sha256, 'Current association identity differs')
    # Validate immutable request fields without demanding that its own output be absent.
    historical_doc,historical_pin=read_pin(v['pocket_receipt_path'],v['pocket_receipt_sha256'])
    b=historical_doc['binding']
    h=authority.load_pocket(v['pocket_receipt_path'],v['pocket_receipt_sha256'],process_id=b['process_id'],source_path=source_path,source_sha256=source_sha256)
    require(r['historical_pocket_pin']==historical_pin and r['historical_process_id']==b['process_id']
        and r['historical_process_create_time']==b['expected_process_create_time']
        and r['expected_process_create_time']==v['expected_process_create_time']
        and b['process_id']!=process_id and b['expected_process_create_time']!=v['expected_process_create_time'], 'Association provenance differs')
    require(h['state']['sketch_state']['pid']==b['process_id'], 'Historical snapshot PID differs')
    verify_observations(r,dict(baseline=h['state']),v);clean_events(r)
    require(r.get('state_sha256')==_digest(r['before']), 'Association state digest differs')
    require(h['restore']['new_feature_native_id']==v['expected_feature_native_id']
        and [x['native_id'] for x in h['restore']['new_operations']]==[v['expected_operation_native_id']], 'Association target differs')
    h['state']=deepcopy(r['after'])  # Proven raw current capture; historical files unchanged.
    h['current_owner']=dict(process_id=process_id,expected_process_create_time=v['expected_process_create_time'])
    h['session_rebind_pin']=pin
    h['pins']['session_rebind']=pin
    return h
