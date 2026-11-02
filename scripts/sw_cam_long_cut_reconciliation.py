"""Offline reconciliation of a completed tool factory rejected by JSON size bounds.

No native methods, Save, marker updates, or replay. The original receipt and
writer remain unchanged; authority is a compact reference to verified evidence.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,math,os,re
from scripts import sw_cam_long_cut_tool_definition as creator
from scripts.sw_cam_mill_stock_export_evidence import _signature
from scripts.sw_cam_mill_selected_plan_evidence import clean_events
from scripts.sw_cam_rough_firstcut import require

MAX_BYTES=32*1024*1024
MAX_NODES=1000000
CREATOR_SHA='baa712761ff6977f7442489f109143ec8652cd1969565cb80bcd93545d3a20f6'
RECONCILIATION_SCOPE='LONG_CUT_TERMINAL_OFFLINE_RECONCILIATION_V1'
SCOPE,FIELD_ORDER=creator.SCOPE,creator.FIELD_ORDER
common,group,prior,deep=creator.common,creator.group,creator.prior,creator.deep
validate_recipe=creator.validate_recipe
verify_candidate=creator.verify_candidate
verify_protected=creator.verify_protected
catalogue_authority=creator.catalogue_authority
make_checkpoint=creator.make_checkpoint


def decode_bounded(data):
    require(type(data)is bytes and 0<len(data)<=MAX_BYTES,'Bounded receipt bytes required')
    def pairs(items):
        out={}
        for key,value in items:
            require(key not in out,'Duplicate JSON key');out[key]=value
        return out
    def bad(_):raise ValueError('Nonfinite receipt JSON')
    try:obj=json.loads(data,object_pairs_hook=pairs,parse_constant=bad)
    except (RecursionError,UnicodeError,json.JSONDecodeError)as exc:raise ValueError('Invalid bounded receipt JSON')from exc
    stack=[(obj,0)];count=0
    while stack:
        value,depth=stack.pop();count+=1
        require(depth<=64 and count<=MAX_NODES,'Receipt JSON structure exceeds scoped bounds')
        if type(value)is dict:stack.extend((v,depth+1)for v in value.values())
        elif type(value)is list:
            require(len(value)<=8192,'Receipt JSON list exceeds bound');stack.extend((v,depth+1)for v in value)
        elif type(value)is float:require(math.isfinite(value),'Nonfinite receipt JSON')
        elif type(value)is str:require(len(value)<=16384,'Receipt JSON string exceeds bound')
    require(type(obj)is dict,'Receipt object required')
    return obj


def read_pin(path,digest):
    require(type(path)is str and type(digest)is str and re.fullmatch('[0-9a-f]{64}',digest),'Exact pinned path/hash required')
    p=Path(path)
    require(p.is_absolute()and p.suffix.casefold()=='.json'and not p.is_symlink(),'Absolute non-symlink JSON required')
    canonical=p.resolve(strict=True);before=p.stat()
    require(p.is_file()and 0<before.st_size<=MAX_BYTES,'Bounded regular JSON required')
    with p.open('rb')as stream:
        opened=os.fstat(stream.fileno())
        require(_signature(before)[:-1]==_signature(opened)[:-1],'JSON path/handle identity changed')
        raw=stream.read(MAX_BYTES+1)
        require(_signature(opened)==_signature(os.fstat(stream.fileno())),'JSON changed during read')
    require(len(raw)==before.st_size and _signature(before)[:-1]==_signature(p.stat())[:-1]
        and _signature(before)[:-1]==_signature(canonical.stat())[:-1]
        and not p.is_symlink()and canonical==p.resolve(strict=True),'JSON path changed during read')
    require(hashlib.sha256(raw).hexdigest()==digest,'Pinned JSON SHA differs')
    return decode_bounded(raw),dict(path=str(p),sha256=digest)


def _exact_failure(r):
    require(r.get('status')=='uncertain'and r.get('phase')=='finished'
        and r.get('readback_verified')is False and r.get('phase_proofs_verified')is False,
        'Only completed factory JSON-terminal failure may be reconciled')
    issue=r.get('terminal_issue')or{}
    require(set(issue)=={'type','hresult','actual_return_type','locations'}and issue['type']=='ValueError'
        and issue['hresult']is None and issue['actual_return_type']is None,
        'Exact decoder failure required')
    require(issue['locations']==[
        {'file':'sw_cam_mill_selected_plan_evidence.py','function':'read_pin','line':30},
        {'file':'sw_cam_mill_stock_export_evidence.py','function':'_decode','line':72},
        {'file':'sw_cam_mill_stock_export_evidence.py','function':'_require','line':33}],
        'Unrelated terminal failure cannot be reconciled')
    require(not r.get('issue')and not r.get('cleanup_issue'),'Additional native or cleanup issue')
    require(r.get('automatic_replay')is False and r.get('automatic_rollback')is False
        and r.get('production_qualified')is False and r.get('mutation_attempted')is True,
        'Original once-only nonproduction scope differs')
    clean_events(r)

def _validate_terminal_semantics(r, initial):
    require(r.get('scope')==SCOPE and r.get('status')=='review_required' and r.get('phase')=='finished'
        and r.get('readback_verified') is True and r.get('model_saved') is True and r.get('exact_one_tool_created') is True
        and r.get('phase_proofs_verified') is True,'Completed saved candidate receipt required')
    require(r.get('protected_fourteen_cl_verified')is True,'Saved fourteen CL preservation required')
    require(all(r.get(k) is False for k in ('assignment_attempted','GTP_attempted','GOP_attempted','TechDB_write_attempted')),
        'Tool-only scope required')
    creation=r['actions']['AddNewTool3'];save=r['actions']['SaveActiveDocument']
    require(creation.get('returned') is True and creation.get('returned_interface_pointer') is True
        and creation.get('pending') is False,'Completed unique factory action required')
    require(save.get('returned') is True and save.get('pending') is False
        and save.get('native_return_type')=='int' and type(save.get('native_return_value')) is int
        and save['native_return_value']==0,'Strict completed Save0 required')
    allowed={'AddNewTool3','SetFilePathForUserDefinedHolder','SaveActiveDocument'}|{'property:'+v for v in FIELD_ORDER}
    require(set(r['actions'])<=allowed and all(v.get('returned') is True and v.get('pending') is False for v in r['actions'].values()),
        'No unknown or pending action permitted')
    require([v['property'] for v in r['field_readbacks']]==list(FIELD_ORDER)
        and all(v['readback_verified'] is True for v in r['field_readbacks']),'All requested fields need actual readback')
    require(group.exact(r['initial_observation']['tools'],r['initial_catalogue']), 'Initial actual catalogue authority differs')
    wanted=validate_recipe(r['recipe'])
    require(all(prior.scalar_equal(v['requested'],wanted[v['property']])
        and prior.scalar_equal(v['actual'],wanted[v['property']]) for v in r['field_readbacks']),
        'Terminal field values differ from pinned recipe')
    holder=r['actions']['SetFilePathForUserDefinedHolder']
    require(holder.get('native_return_type')=='int' and type(holder.get('native_return_value')) is int
        and holder['native_return_value']==0,'Completed strict holder HRESULT0 required')
    verify_protected(r['initial_observation'],r['final_observation'],r['new_tool_native_id'])
    require(type(r['new_tool_native_id']) is int and r['final_candidate']['full_tool']['tool_native_id']==r['new_tool_native_id'],
        'Final complete profile must belong to the actual created tool')
    verify_candidate(r['final_candidate'],r['recipe'],r['holder_recipe'])
    require(prior._digest(r['checkpoint'])==r['checkpoint_digest'],'Saved checkpoint digest differs')
    require(group.exact(r['initial_observation']['guide_snapshot'],initial['deep_loaded']['guide_parameters']['expected_parameters']),
        'Pinned initial eight-group snapshot differs')
    require(group.exact(r['saved_cl_comparison'],deep.cl.verify_all(initial['deep_loaded']['generated']['saved_cl'],r['saved_cl'])),
        'Completed fourteen-stream comparison differs')
    require(group.exact(r['initial_catalogue'],catalogue_authority(initial))
        and group.exact(r['initial_observation']['route'],prior.expected_route(initial)),
        'Initial observation must match the pinned current source context')
    require(group.exact(r['checkpoint'],make_checkpoint(r,initial,r['recipe'])),
        'Saved flat checkpoint differs from terminal evidence')


def verify_original(receipt_pin,context_pin,saved_backup_pin,*,check_current=True):
    require(prior._file_hash(creator.__file__)==CREATOR_SHA,'Frozen factory implementation changed')
    r,rpin=read_pin(receipt_pin['path'],receipt_pin['sha256']);_exact_failure(r)
    require(r['module_pin']['sha256']==CREATOR_SHA and common._key(r['module_pin']['path'])==common._key(creator.__file__),
        'Original writer pin differs')
    require(context_pin['sha256']==r['loaded_context_pin']['sha256'],'Archived context differs from original')
    initial,cpin=read_pin(context_pin['path'],context_pin['sha256'])
    # Confirm the exact original bound failure, rather than assume a ValueError cause.
    from scripts.sw_cam_mill_stock_export_evidence import _decode
    raw=Path(context_pin['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==context_pin['sha256'],'Context changed before original-bound check')
    try:_decode(raw)
    except ValueError as exc:require(str(exc)=='Receipt JSON structure exceeds bounds','Different original decoder rejection')
    else:raise ValueError('Original decoder must actually reject this context')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    common._check([r['module_pin'],r['marker_pin'],r['recipe_pin'],r['source_backup_pin'],saved_backup_pin])
    require(saved_backup_pin['sha256']==r['saved_source_sha256'],'Saved backup does not match completed Save')
    if check_current:require(prior._file_hash(r['source_path'])==r['saved_source_sha256'],'Current saved source changed')
    require(r['source_transition']['source_before_sha256']==r['initial_source_sha256']
        and r['source_backup_pin']['sha256']==r['initial_source_sha256']
        and r['source_transition']['source_after_sha256']==r['saved_source_sha256']
        and r['source_transition']['strict_save_return']==0
        and r['source_transition']['document']['needs_save']is False,
        'Exact successful source transition required')
    require(common._key(r['source_transition']['document']['path'])==common._key(r['source_path'])
        and r['final_state']['saved_file_sha256']==r['saved_source_sha256'],
        'Saved source/document binding differs')
    mark,_=read_pin(r['marker_pin']['path'],r['marker_pin']['sha256'])
    require(mark.get('scope')==SCOPE and mark.get('phase')=='finished'and mark.get('readback_verified')is False
        and mark.get('automatic_replay')is False and mark.get('new_tool_native_id')==r['new_tool_native_id']
        and mark.get('initial_source_sha256')==r['initial_source_sha256']and mark.get('saved_source_sha256')==r['saved_source_sha256']
        and common._key(mark['source_path'])==common._key(r['source_path'])
        and common._key(mark['receipt_path'])==common._key(r['receipt_path'])and group.exact(mark['actions'],r['actions']),
        'Original uncertain once marker differs; it must remain unchanged')
    normalized=deepcopy(r)
    normalized.update(status='review_required',readback_verified=True,phase_proofs_verified=True)
    _validate_terminal_semantics(normalized,initial)
    require(len(normalized['final_observation']['route']['operations'])==17,'Exactly17 protected operation definitions required')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    common._check([rpin,cpin,r['marker_pin'],saved_backup_pin])
    return r,initial


def make_authority(receipt_pin,context_pin,saved_backup_pin):
    r,_=verify_original(receipt_pin,context_pin,saved_backup_pin,check_current=True)
    return dict(schema_version=1,scope=RECONCILIATION_SCOPE,status='verified_offline',
        native_called=False,model_modified=False,automatic_replay=False,production_qualified=False,
        source_path=r['source_path'],saved_source_sha256=r['saved_source_sha256'],process_id=r['process_id'],
        new_tool_native_id=r['new_tool_native_id'],original_receipt_pin=deepcopy(receipt_pin),
        original_context_pin=deepcopy(context_pin),original_marker_pin=deepcopy(r['marker_pin']),
        saved_source_backup_pin=deepcopy(saved_backup_pin),creator_pin=deepcopy(r['module_pin']),
        reconciliation_module_pin=common._pin(__file__),original_checkpoint_digest=r['checkpoint_digest'],
        checks=dict(all_terminal_semantics=True,clean_event_shutdown=True,strict_save_zero=True,
            complete_tool_and_holder_profile=True,protected_definitions=17,protected_parameter_groups=8,
            protected_complete_cl_streams=14,original_receipt_and_marker_unchanged=True),
        original_status='uncertain',reason='Completed factory rejected solely by historical JSON structure bound',
        scoped_decoder=dict(max_bytes=MAX_BYTES,max_nodes=MAX_NODES,max_depth=64,max_list=8192,max_string=16384))


def verified_terminal(path,digest,*,check_current=False):
    a,apin=read_pin(path,digest)
    require(a.get('scope')==RECONCILIATION_SCOPE and a.get('status')=='verified_offline',
        'Explicit offline reconciliation authority required')
    require(all(a.get(k)is False for k in ('native_called','model_modified','automatic_replay','production_qualified')),
        'Offline-only authority required')
    require(a['reconciliation_module_pin']['sha256']==prior._file_hash(__file__)
        and common._key(a['reconciliation_module_pin']['path'])==common._key(__file__), 'Reconciliation implementation differs')
    r,initial=verify_original(a['original_receipt_pin'],a['original_context_pin'],a['saved_source_backup_pin'],check_current=check_current)
    require(a['source_path']==r['source_path']and a['saved_source_sha256']==r['saved_source_sha256']
        and type(a['process_id'])is int and a['process_id']==r['process_id']
        and a['new_tool_native_id']==r['new_tool_native_id']and a['original_checkpoint_digest']==r['checkpoint_digest']
        and group.exact(a['original_marker_pin'],r['marker_pin'])and group.exact(a['creator_pin'],r['module_pin']),
        'Reconciled authority does not match actual terminal evidence')
    require(a['checks']==dict(all_terminal_semantics=True,clean_event_shutdown=True,strict_save_zero=True,
        complete_tool_and_holder_profile=True,protected_definitions=17,protected_parameter_groups=8,
        protected_complete_cl_streams=14,original_receipt_and_marker_unchanged=True), 'Reconciled checks differ')
    require(a['scoped_decoder']==dict(max_bytes=MAX_BYTES,max_nodes=MAX_NODES,max_depth=64,max_list=8192,max_string=16384),
        'Scoped decoder contract differs')
    common._check([apin,a['reconciliation_module_pin']])
    return r,initial,apin,a


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,initial,pin,a=verified_terminal(path,digest,check_current=True)
    require(type(process_id)is int and r['process_id']==process_id
        and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256,'Exact owned current source required')
    context=deepcopy(r['checkpoint']['context']);oldparent=context['parent_pin'];oldmarker=context['group_marker_pin']
    context['pins']=common._merge([v for v in context['pins']if common._key(v['path'])!=common._key(oldparent['path'])],[pin])
    context['offline_export_proof_pins']=common._merge(context['offline_export_proof_pins'],[
        oldparent,oldmarker,r['marker_pin'],a['original_receipt_pin'],a['original_context_pin'],
        a['saved_source_backup_pin'],a['reconciliation_module_pin']])
    context.update(parent_pin=pin,group_marker_pin=deepcopy(r['marker_pin']),authority_kind=creator.AUTHORITY,
        offline_reconciliation=deepcopy(a))
    require(len(context['pins'])<=128,'Bounded current candidate context required')
    common._check(context['pins']);common._check(context['offline_export_proof_pins'])
    return context
