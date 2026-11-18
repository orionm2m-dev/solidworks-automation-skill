"""File-only admission of a genuine completed RecoveryV2 Save and CL.
No application access, replay, receipt relabelling or historical pin replacement.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,os,re
from scripts import sw_cam_current_pocket_generation_recovery_v2 as recovery
from scripts import sw_cam_current_pocket_saved_context as saved_context
from scripts import sw_cam_chamfer_cl_review as cl_signature
from scripts.sw_cam_generic_cl_reader_bounded import parse_generic_cl_bytes
producer=recovery.prior
current=recovery.current
definition=producer.reader.definition
delta=recovery.delta
fields=recovery.fields
require=recovery.require
block_signature=cl_signature.block_signature
SCOPE='RECOVERED_GENERATED_POCKET_V2_FILE_ADMISSION_V1'
KEYS=set(current.IDENTITY_KEYS)|{'recovered_receipt_path','recovered_receipt_sha256'}
MAX_BYTES=32*1024*1024


def _strict_zero(row):
    require(type(row)is dict and row.get('attempted')is True and row.get('returned')is True
        and row.get('native_dispatch_pending')is False and row.get('native_return_type')=='int'
        and type(row.get('native_return_value'))is int and row['native_return_value']==0,
        'Completed unique native integer-zero action required')

def _clean(r):
    definition.creator.clean(r)
    require(producer.reader.shared.event_health(r.get('messages',{}),active=False)==0,'Clean completed event scope required')
    require(not any(k in r for k in ('cleanup_error','runtime_error','receipt_write_error','issue')),'Error receipt is not terminal authority')

def _saved(r):
    """Existing Save proof without demanding an obsolete target file hash."""
    require(r.get('status')=='review_required' and r.get('phase')=='finished','Completed saved observation required')
    for k in ('current_context_verified','save_readback_verified','inventory_delta_verified','parameter_delta_verified','runtime_unchanged','model_saved'):
        require(r.get(k)is True,'Incomplete saved fact: '+k)
    _clean(r)
    p=r['current_context']
    require(p['scope']in(current.legacy.SCOPE,current.SCOPE) and p['limitations']==current.LIMITS,'Known exact saved context and limitations required')
    a,b=r['save_snapshots']['before'],r['save_snapshots']['after']
    require(b==p['snapshot'] and current._without_save_fields(a)==current._without_save_fields(b),'Save changed protected snapshot')
    require(p['state_sha256']==producer._digest(b) and b['inventory']['document']['needs_save']is False,'Clean digest-bound saved snapshot required')
    n=r['native_save']
    require(n.get('native_call_returned')is True and n.get('save_pending')is False
        and n.get('native_return_type')=='int' and type(n.get('native_return_value'))is int
        and n['native_return_value']==0 and n.get('save_readback_verified')is True,'Actual native Save int0 required')
    old,new=a['inventory']['saved_file_sha256'],b['inventory']['saved_file_sha256']
    require(new==p['identity']['expected_source_sha256']==p['capture_context']['expected_source_sha256']
        ==p['capture_context']['current_sketch_baseline']['saved_file_sha256'],'Saved hash/identity/capture lineage differs')
    require(definition.creator.same_path(b['inventory']['document']['path'],p['identity']['expected_document_path'])
        and definition.creator.same_path(p['capture_context']['expected_document_path'],p['identity']['expected_document_path']),'Saved document identity differs')
    require(old!=new and new==r['saved_file_sha256_after_native_return']
        and p['source_transition']==dict(before_sha256=old,after_sha256=new,native_return_value=0),'Exact changed source transition required')
    require(n['before']==n['after']==current._without_save_fields(b) and n['saved_file_sha256']==new,'Native Save observations differ from payload')
    require(r['current_baseline_receipt_pin']==p['predecessor_pin'],'Predecessor binding differs')
    require(r['after_cleanup_identity']==dict(document=b['inventory']['document'],saved_file_sha256=new),'Final cleanup differs from saved observation')
    return p

def protected_signature(parsed):
    """Preserve outer commands too; no invented timestamp exceptions."""
    block=parsed['operation_blocks'][0]
    outer=[x['raw']for x in parsed['commands']if not block['start_line']<=x['line']<=block['end_line']]
    return dict(block=block_signature(parsed,0),outer_commands=outer,declared_units=deepcopy(parsed['declared_units']))

def verify_protected_cl(authority,parsed,rows):
    count=authority['rows'][0]['toolpath_record_counts'][0];oid=authority['rows'][0]['operation_native_id']
    delta.verify_first_cl(parsed,oid,count)
    require(parsed['sha256']==authority['parsed']['sha256'] and parsed['bytes']==authority['parsed']['bytes'],'Protected raw CL bytes changed')
    require(rows==authority['rows'],'Protected generated identity/count context changed')
    proof=delta.existing.compare_cl(authority['parsed'],parsed,authority['rows'],rows,[])
    require(protected_signature(parsed)==authority['signature'],'Protected outer CL commands changed')
    return proof

def _projection(pin):
    require(type(pin)is dict and {'path','sha256'}<=set(pin)<= {'path','sha256','canonical_path','bytes','identity'},'Known immutable file pin required')
    require(type(pin['path'])is str and Path(pin['path']).is_absolute() and type(pin['sha256'])is str
        and re.fullmatch('[0-9a-f]{64}',pin['sha256'])is not None,'Exact absolute path and SHA required')
    return dict(path=pin['path'],sha256=pin['sha256'])

def _same_pin(a,b):
    a,b=_projection(a),_projection(b)
    return definition.creator.same_path(a['path'],b['path']) and a['sha256']==b['sha256']

def _signature(stat):
    return [stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_mode,stat.st_ctime_ns]

def _bytes(pin):
    base=_projection(pin);p=Path(base['path']);before=p.stat();canonical=p.resolve(strict=True)
    require(p.is_file() and not p.is_symlink() and 0<before.st_size<=MAX_BYTES,'Bounded pinned regular evidence file required')
    with p.open('rb')as stream:
        opened=os.fstat(stream.fileno());require(_signature(before)==_signature(opened),'Evidence path/handle changed')
        raw=stream.read(MAX_BYTES+1)
        require(_signature(opened)==_signature(os.fstat(stream.fileno())),'Evidence changed during read')
    require(len(raw)==before.st_size and _signature(before)==_signature(p.stat()) and canonical==p.resolve(strict=True)
        and not p.is_symlink(),'Evidence path changed during read')
    require(hashlib.sha256(raw).hexdigest()==base['sha256'],'Evidence bytes changed')
    if 'canonical_path'in pin:
        require(type(pin['canonical_path'])is str and Path(pin['canonical_path']).is_absolute()
            and str(canonical).casefold()==str(Path(pin['canonical_path'])).casefold(),'Rich pin canonical path differs')
    if 'bytes'in pin:require(type(pin['bytes'])is int and pin['bytes']==len(raw),'Rich pin byte count differs')
    if 'identity'in pin:
        require(type(pin['identity'])is list and len(pin['identity'])==6 and all(type(x)is int for x in pin['identity'])
            and pin['identity']==_signature(opened),'Rich pin file identity differs')
    return raw

def _json(pin):
    def unique(pairs):
        out={}
        for key,value in pairs:require(key not in out,'Duplicate JSON key');out[key]=value
        return out
    value=json.loads(_bytes(pin).decode('utf-8-sig'),object_pairs_hook=unique,
        parse_constant=lambda value:require(False,'Nonfinite JSON'))
    require(type(value)is dict,'Object evidence required');delta._json(value);return value

def _pin_keys(pins):
    return {(definition.creator.canonical(x['path']),x['sha256'])for x in current.pin_union(pins)}


def _marker(owner,report,pin,marker,status):
    q=report['request']
    expected=dict(scope=owner.SCOPE,receipt_path=str(Path(q['receipt_path'])),receipt_sha256=pin['sha256'],
        configuration_receipt_pin=report['configuration_receipt_pin'],selected_operation_native_ids=[q['selected_operation_native_id']],
        status=status,phase='finished',automatic_replay=False)
    require(marker==expected and definition.creator.same_path(q['receipt_path'],pin['path']),'Exact consumed marker differs')


def _context_without_source(value):
    value=deepcopy(value);value.pop('expected_source_sha256');value['current_sketch_baseline'].pop('saved_file_sha256');return value


def verify_terminal(r,raw,previous,recipe,markers,receipt_pin,raw_pin,previous_pin,request):
    """Pure semantic validation; load supplies stable pinned JSON and actual CL."""
    require(r.get('scope')==recovery.SCOPE and r.get('evidence_pin_limit')==128,'Exact RecoveryV2 authority required')
    require(r.get('status')=='review_required' and r.get('phase')=='finished','Terminal successful recovery required')
    for key in recovery.FLAGS:require(r.get(key)is True,'Incomplete recovery fact: '+key)
    for key in ('Save_attempted','save_attempted','save_readback_verified','model_saved','CL_export_attempted','receipt_created','marker_created','native_call_attempted','native_call_returned','mutation_attempted','feed_unqualified'):
        require(r.get(key)is True,'Missing recorded recovery action: '+key)
    for key in ('operation_parameter_setters_attempted','setters_replayed','GTP_attempted','GTP_replayed','GOP_attempted','Import_attempted','automatic_replay','preCL_exported','native_dispatch_pending','feed_change_cause_verified','production_qualified','physical_tool_qualified','native_units_verified','cutting_conditions_qualified','island_geometry_verified','geometry_sweep_verified','reopen_persistence_verified'):
        require(r.get(key)is False,'Unexpected replay or qualification: '+key)
    _clean(r);q=r['request'];recovery.shape(q)
    require(list(r['actions'])==['SaveActiveDocument','postCL'],'Exactly one Save then CL, no replay')
    for action in r['actions'].values():recovery.strict_return(action)
    pp=_saved(previous);current._check_request(raw['request'],pp['identity'])
    for key in ('GTP_attempted','GOP_attempted','Import_attempted','automatic_replay','production_qualified'):
        require(previous.get(key)is False,'Historical baseline is not an ungenerated saved context')
    prior_bundle=dict(context=deepcopy(pp['capture_context']),state=deepcopy(pp['snapshot']['inventory']),parameters=deepcopy(pp['snapshot']['parameters']),receipt_pin=deepcopy(previous_pin),root_pins=deepcopy(pp['root_pins']))
    proof=recovery.verify_partial(raw,q,prior_bundle,recipe)
    require(_same_pin(raw_pin,dict(path=q['failed_generation_receipt_path'],sha256=q['failed_generation_receipt_sha256'])),'Recovery raw input differs')
    require(r['configuration_receipt_pin']==r['historical_GTP_receipt_pin']==raw_pin and r['current_baseline_receipt_pin']==raw['configuration_receipt_pin']==previous_pin,'Genuine direct history pins differ')
    require(_same_pin(previous_pin,dict(path=raw['request']['current_context_receipt_path'],sha256=raw['request']['current_context_receipt_sha256'])),'Original current baseline pin differs')
    require(r['recipe']==raw['recipe']==recipe and r['recipe_pin']==raw['recipe_pin'],'Original recipe differs')
    require(r['historical_status']=='uncertain' and r['historical_runtime_unchanged']is raw['runtime_unchanged'] is False,'Original uncertainty must remain')
    require(r['observed_feed_delta']==proof['feed_delta'] and r['historical_generation_proof']==proof['generation_proof'],'Recorded recovery proof/feed differs')
    require(r['setup_transform']==raw['setup_transform'] and r['setup_transform_proof']==raw['setup_transform_proof'],'Historical transform differs')
    oid=q['selected_operation_native_id'];require(r['selected_operation_native_ids']==[oid] and r['baseline_generated_operation_count']==1,'Selected recovery identity differs')
    expected=proof['expected_state'];require(r['before']==r['confirm_before']==expected and r['second_capture_roles']==['generated_state_confirmation','save_before'],'Two distinct full confirmations required')
    save=saved_context.saved_observation(r,prior_bundle,expected);p=r['current_context'];saved=save['snapshot']
    require(p['scope']==recovery.GENERATED_SCOPE and p['limitations']==current.LIMITS,'Exact recovered generated payload required')
    require(p['snapshot']==r['saved']==saved and p['state_sha256']==producer._digest(saved),'Saved payload/digest differs')
    require(p['predecessor_pin']==previous_pin and p['historical_generation_receipt_pin']==raw_pin and p['observed_feed_delta']==proof['feed_delta'],'Recovered payload history differs')
    require(p['source_transition']==dict(before_sha256=save['before_sha256'],after_sha256=save['after_sha256'],native_return_value=0),'Recorded source transition differs')
    current._check_request(request,p['identity'])
    for key in set(current.IDENTITY_KEYS)-{'expected_source_sha256'}:
        require(fields.equal(q[key],request[key]),'Recovery/current identity differs: '+key)
    d=p['capture_context'];new=save['after_sha256']
    require(new==request['expected_source_sha256']==p['identity']['expected_source_sha256']==d['expected_source_sha256']==d['current_sketch_baseline']['saved_file_sha256'],'Current source/capture hash differs')
    require(_context_without_source(d)==_context_without_source(pp['capture_context']),'Save changed immutable capture geometry/context')
    require(d['process_id']==request['process_id'] and d['request']['expected_process_create_time']==request['expected_process_create_time'] and d['expected_feature_native_id']==request['expected_feature_native_id'] and definition.creator.same_path(d['expected_document_path'],request['expected_document_path']),'Capture identity differs')
    require(d['creator']['status']=='uncertain' and d['creator']['feature_header']==saved['inventory']['selected_feature'],'Original creator limitation/header differs')
    require(r['after_cleanup_identity']==dict(document=saved['inventory']['document'],saved_file_sha256=new),'Final cleanup differs')
    require([x['native_id']for x in saved['inventory']['operations']]==request['expected_operation_native_ids'] and saved['inventory']['selected_feature']['native_id']==request['expected_feature_native_id'],'Ordered feature/operation identity differs')
    labels=['recovery_current','before','after','postCL_before','postCL_after'];values=[expected,expected,saved,saved,saved]
    require([x['label']for x in r['captures']]==labels,'Five complete ordered capture records required')
    for capture,value in zip(r['captures'],values):
        require(capture['diagnostic'].get('capture_complete')is True and capture['diagnostic']['state']==value['inventory'] and capture['observation']==value,'Full capture differs from actual snapshot')
    flat=delta.flatten(saved);selected=flat['operations'][0];count=selected['toolpath_record_counts']
    require(selected['native_id']==oid and len(count)==1 and flat['generated_operation_count']==1,'Sole generated Rough required')
    rows=[dict(operation_native_id=oid,toolpath_record_counts=count)];export=r['postCL']
    require(export.get('output_verified')is True and export.get('readback_verified')is True and export.get('native_call_returned')is True and export.get('native_dispatch_pending')is False and export.get('output_directory_created')is True,'Complete CL export required')
    require(export['source_sha256']==new and export['document']==saved['inventory']['document'] and export['before']==export['after']==flat and export['expected_generated_operations']==rows,'CL source/full observation binding differs')
    require(definition.creator.same_path(export['output_path'],q['saved_cl_path']) and definition.creator.same_path(export['output']['path'],q['saved_cl_path']),'CL output identity differs')
    require(export['parse_summary']==dict(parse_complete=True,native_count_matches=True,blocks=1,declared_units=['MM']),'CL parse summary differs')
    _marker(producer,raw,raw_pin,markers['original'],'uncertain');_marker(recovery,r,receipt_pin,markers['recovery'],'review_required')
    return dict(scope=SCOPE,producer_scope=recovery.SCOPE,protected_generated={oid:deepcopy(count)},state=deepcopy(saved['inventory']),parameters=deepcopy(saved['parameters']),generation_proof=proof['generation_proof'],feed_delta=proof['feed_delta'],rows=rows,live_capture_verified=False,native_calls=0,world_geometry_verified=False,production_qualified=False,cutting_conditions_qualified=False)


def _historical_modules():
    return [producer,delta,fields,producer.engine,producer.generation,producer.transforms,producer.transforms.metadata_reader,current,producer.tool,delta.existing,producer.cl_reader,producer.cl_bounded,producer.definition_capture,producer.guard_module,recovery]


def verify_files(bundle):
    """Recheck admitted bytes plus explicit reader dependencies, no semantic reload."""
    require(bundle.get('scope')==SCOPE and bundle.get('live_capture_verified')is False,'Known file-only bundle required')
    pins=bundle['context']['pins'];require(pins==bundle['pins'],'Context and bundle pins differ')
    actual={definition.creator.canonical(p['path']):p for p in current.pin_union(pins)}
    for pin in bundle['admitted_pins']:
        require(actual.get(definition.creator.canonical(pin['path']))==pin,'Admitted evidence was dropped or replaced')
    require(bundle['context']['expected_source_sha256']==bundle['state']['saved_file_sha256'] and bundle['context']['saved_plan_inventory']==bundle['state'],'Bound capture source/state changed')
    for pin in pins:_bytes(pin)
    cl=bundle['protected_cl'];raw=_bytes(cl['pin'])
    require(hashlib.sha256(raw).hexdigest()==cl['parsed']['sha256']==cl['raw_bytes_sha256'] and len(raw)==cl['parsed']['bytes'],'Protected CL bytes changed')
    return True


def load(request):
    require(type(request)is dict and set(request)==KEYS,'Exact recovered-context request required')
    v=deepcopy(request);receipt_pin=dict(path=v['recovered_receipt_path'],sha256=v['recovered_receipt_sha256']);r=_json(receipt_pin)
    require(r.get('scope')==recovery.SCOPE and r.get('phase')=='finished' and r.get('status')=='review_required','Only genuine completed RecoveryV2 is authority')
    q=r['request'];raw_pin=r['historical_GTP_receipt_pin'];raw=_json(raw_pin);previous_pin=r['current_baseline_receipt_pin'];previous=_json(previous_pin);recipe=_json(r['recipe_pin'])
    marker_pins=[];markers={}
    for label,owner,report in [('original',producer,raw),('recovery',recovery,r)]:
        path=owner.marker_path(report['request']);pin=dict(path=str(path),sha256=producer._file_hash(path));markers[label]=_json(pin);marker_pins.append(pin)
    require(_same_pin(r['historical_marker_pin'],marker_pins[0]),'Original consumed marker pin differs');_bytes(r['historical_marker_pin'])
    proof=verify_terminal(r,raw,previous,recipe,markers,receipt_pin,raw_pin,previous_pin,v)
    cp=r['postCL']['output'];cl_pin=dict(path=cp['path'],sha256=cp['sha256']);cl_raw=_bytes(cl_pin);require(type(cp['bytes'])is int and len(cl_raw)==cp['bytes'],'Actual CL length differs')
    parsed=parse_generic_cl_bytes(cl_raw,expected_block_record_counts=proof['rows'][0]['toolpath_record_counts']);clproof=delta.verify_first_cl(parsed,q['selected_operation_native_id'],proof['rows'][0]['toolpath_record_counts'][0]);require(clproof==r['first_CL_proof'],'Actual first CL proof differs')
    target=v['expected_document_path'];old=q['expected_source_sha256'];groups=[]
    for report in (raw,r):
        evidence=report['evidence_pins'];require(type(evidence)is list and 1<=len(evidence)<=128,'Bounded complete historical pins required')
        targets=[p for p in evidence if definition.creator.same_path(p['path'],target)]
        require(len(targets)==1 and targets[0]['sha256']==old,'Exact obsolete target preimage pin required')
        groups.append([p for p in evidence if not definition.creator.same_path(p['path'],target)])
    require(_pin_keys(raw['evidence_pins'])<=_pin_keys(r['evidence_pins']),'Recovery dropped original evidence')
    pp=previous['current_context'];p=r['current_context']
    require(_pin_keys(pp['root_pins'])<=_pin_keys(p['root_pins']),'Recovery dropped saved predecessor roots')
    for group in [pp['root_pins'],p['root_pins']]+groups:
        for pin in group:_bytes(pin)
    roots=current.pin_union(p['root_pins'],*groups,[raw_pin,previous_pin,r['recipe_pin'],pp['predecessor_pin']]+marker_pins+[cl_pin])
    require(not any(definition.creator.same_path(p['path'],target)for p in roots),'Mutable target cannot be an immutable root')
    keys=_pin_keys(roots)
    for module in _historical_modules():
        path=Path(module.__file__);require((definition.creator.canonical(str(path)),producer._file_hash(path))in keys,'Historical source pin missing or changed: '+path.name)
    dependencies=[Path(__file__).resolve(),Path(saved_context.__file__).resolve(),Path(cl_signature.__file__).resolve()]
    roots=current.pin_union(roots,[dict(path=str(p),sha256=producer._file_hash(p))for p in dependencies])
    pins=current.pin_union(roots,[receipt_pin,dict(path=target,sha256=v['expected_source_sha256'])])
    d=deepcopy(p['capture_context']);d.update(saved_plan_inventory=deepcopy(proof['state']),expected_operation_native_ids=deepcopy(v['expected_operation_native_ids']),authority_scope=SCOPE,pins=deepcopy(pins))
    proof.update(context=d,receipt_pin=receipt_pin,root_pins=roots,lineage_pins=[receipt_pin,raw_pin,previous_pin],pins=pins,admitted_pins=deepcopy(pins),CL_proof=clproof,
        protected_cl=dict(pin=cl_pin,raw_bytes_sha256=cl_pin['sha256'],parsed=parsed,rows=deepcopy(proof['rows']),signature=protected_signature(parsed)))
    verify_files(proof);return proof
