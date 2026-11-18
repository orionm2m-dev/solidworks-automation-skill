"""Export-only continuation of an already verified native Save.
Historical target hashes stay historical; only a proven Save admits the live source.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_pocket_generation_recovery as recovery
from scripts import sw_cam_current_pocket_generate as generation
from scripts import sw_cam_current_pocket_context as current
from scripts import sw_cam_current_pocket_saved_context as finalize
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_current_pocket_generation_delta as delta
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error

reader=generation.reader
definition=reader.definition
pair=current.pair
require=current.require
read_pin=definition.read_pin
_pins=current._pins
_check_request=current._check_request
_snapshot=current._snapshot
_without_save_fields=current._without_save_fields
_root_pins=current._root_pins
SCOPE='CURRENT_POCKET_COMPLETED_SAVE_CL_ONLY_RECOVERY_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids','selected_operation_native_id','saved_attempt_receipt_path','saved_attempt_receipt_sha256','receipt_path','saved_cl_path','qualification_only','acknowledge_export_only','message_policy'}
FLAGS=('readback_verified','current_context_verified','saved_generation_context_verified','inventory_delta_verified','parameter_delta_verified','CL_verified','runtime_unchanged')


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact completed-Save export-only request required')
    for k in ('process_id','expected_feature_native_id','selected_operation_native_id'):
        require(type(v[k])is int and 0<v[k]<2**31,'Strict positive identity required')
    ids=v['expected_operation_native_ids'];require(type(ids)is list and len(ids)==2 and all(type(x)is int and 0<x<2**31 for x in ids) and len(set(ids))==2 and ids[0]==v['selected_operation_native_id'],'Exact ordered current Rough/Contour pair required')
    require(type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact finite process lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute bound paths required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact immutable SHA required')
    require(v['qualification_only']is True and v['acknowledge_export_only']is True and v['message_policy']=='vendor_default','Explicit diagnostic CL-only admission required')


def historical_bind(d,state,parameters,roots,pin,previous_pin,evidence_pins):
    """Not live authority: keep the recorded old target until strict Save transition."""
    d=deepcopy(d);target=d['expected_document_path'];sha=state['saved_file_sha256']
    require(type(evidence_pins)is list and 1<=len(evidence_pins)<=64,'Bounded immutable attempt pin list required')
    targets=[p for p in evidence_pins if definition.creator.same_path(p['path'],target)]
    require(len(targets)==1 and targets[0]['sha256']==sha,'Exactly one historical target preimage pin required')
    pins=finalize.merge_pins(roots,evidence_pins);pins=finalize.merge_pins(pins,[pin,previous_pin])
    for item in pins:
        if not definition.creator.same_path(item['path'],target):require(_file_hash(item['path'])==item['sha256'],'Historical immutable evidence changed')
    d.update(saved_plan_inventory=deepcopy(state),expected_operation_native_ids=[r['native_id']for r in state['operations']],authority_scope='HISTORICAL_CURRENT_CONTEXT_NOT_LIVE',expected_source_sha256=sha,pins=pins)
    d['current_sketch_baseline']['saved_file_sha256']=sha;d['saved_transition']['document']=deepcopy(state['document'])
    return dict(context=d,state=deepcopy(state),parameters=deepcopy(parameters),receipt_pin=deepcopy(pin),root_pins=deepcopy(roots),lineage_pins=[deepcopy(pin),deepcopy(previous_pin)],pins=pins,historical_only=True)


def historical_baseline(r,pin,v,*,evidence_pins):
    require(r.get('status')=='review_required' and r.get('phase')=='finished','Completed current mutation receipt required')
    for k in ('current_context_verified','save_readback_verified','inventory_delta_verified','parameter_delta_verified','runtime_unchanged'):
        require(r.get(k)is True,'Completed current-context fact required: '+k)
    for k in ('GOP_attempted','GTP_attempted','Import_attempted','automatic_replay','production_qualified'):
        require(r.get(k)is False,'Unexpected current-context action/qualification: '+k)
    definition.creator.clean(r)
    p=r['current_context'];require(p['scope']==current.SCOPE and p['limitations']==current.LIMITS,'Exact unqualified current-context scope required')
    _check_request(v,p['identity']);state=p['snapshot']['inventory'];parameters=p['snapshot']['parameters'];_snapshot(state,parameters)
    require(p['state_sha256']==_digest(p['snapshot']) and state['saved_file_sha256']==v['expected_source_sha256'] and state['document']['needs_save']is False,'Exact saved current snapshot required')
    require(r['save_snapshots']['after']==p['snapshot'],'Current context must be the actual after-Save observation')
    require(r['current_baseline_receipt_pin']==p['predecessor_pin'],'Direct predecessor binding differs')
    previous,previous_pin=read_pin(p['predecessor_pin']['path'],p['predecessor_pin']['sha256'])
    require(previous.get('phase')=='finished' and ((previous.get('scope')==pair.SCOPE and previous.get('status')=='observed' and all(previous.get(k)is True for k in pair.FLAGS))or(previous.get('status')=='review_required' and previous.get('current_context_verified')is True and previous.get('current_context',{}).get('scope')==current.SCOPE)),'Direct predecessor must be a completed current observation')
    require(not definition.creator.same_path(previous_pin['path'],pin['path']),'Current receipt cannot be its own predecessor')
    native_save=r['native_save']
    require(type(native_save.get('native_return_value'))is int and native_save['native_return_value']==0 and native_save.get('native_return_type')=='int' and native_save.get('native_call_returned')is True and native_save.get('save_readback_verified')is True,'Recorded native Save int0 required')
    transition=p['source_transition'];require(transition==dict(before_sha256=r['save_snapshots']['before']['inventory']['saved_file_sha256'],after_sha256=r['saved_file_sha256_after_native_return'],native_return_value=0)
        and transition['after_sha256']==v['expected_source_sha256'] and transition['before_sha256']!=transition['after_sha256'],'Recorded changed Save source transition required')
    require(_without_save_fields(r['save_snapshots']['before'])==_without_save_fields(p['snapshot']),'Save changed current parameters or inventory')
    require(r['after_cleanup_identity']==dict(document=state['document'],saved_file_sha256=v['expected_source_sha256']),'Final cleanup differs from saved context')
    d=p['capture_context'];require(d['expected_source_sha256']==v['expected_source_sha256'] and d['process_id']==v['process_id'] and d['expected_feature_native_id']==v['expected_feature_native_id']
        and definition.creator.same_path(d['expected_document_path'],v['expected_document_path']) and d['request']['expected_process_create_time']==v['expected_process_create_time'],'Capture context identity differs')
    require(d['creator']['status']=='uncertain' and d['creator']['feature_header']==state['selected_feature'],'Original feature limitation/header must remain exact')
    roots=_pins(p['root_pins'])
    prior_payload=previous.get('current_context')
    prior_roots=prior_payload['root_pins']if prior_payload is not None else _root_pins(previous,previous_pin)
    root_keys={(definition.creator.canonical(x['path']),x['sha256'])for x in roots}
    require(all((definition.creator.canonical(x['path']),x['sha256'])in root_keys for x in prior_roots),'Current receipt dropped or changed a root pin')
    require(not any(definition.creator.same_path(x['path'],v['expected_document_path'])for x in roots),'Mutable target cannot become immutable root evidence')
    if prior_payload is not None:
        left,right=deepcopy(d),deepcopy(prior_payload['capture_context'])
        for value in (left,right):
            value.pop('expected_source_sha256');value['current_sketch_baseline'].pop('saved_file_sha256')
        require(left==right,'Current transition changed immutable capture geometry/context')
    else:
        require(d['creator']['feature_header']==previous['after']['selected_feature'],'Initial observed feature header changed')
        actual=deepcopy(previous['before_diagnostic']['actual_sketch_snapshot']);expected=deepcopy(d['current_sketch_baseline'])
        for value in (actual,expected):value.pop('saved_file_sha256');value.pop('needs_save')
        sa,sb=actual.pop('solids'),expected.pop('solids')
        require(actual==expected and definition._same_bodies(sa,sb),'Initial observed CAD/sketch geometry changed')
    return historical_bind(d,state,parameters,roots,pin,previous_pin,evidence_pins)

def verify_saved_attempt(raw,v,expected):
    shape(v);old=raw['request'];recovery.shape(old)
    for key in recovery.IDENTITY:
        if key=='expected_source_sha256':continue
        require(definition.creator.same_path(old[key],v[key])if key=='expected_document_path'else type(old[key])is type(v[key]) and old[key]==v[key],'Saved attempt identity differs: '+key)
    require(raw.get('scope')==recovery.SCOPE and raw.get('status')=='uncertain' and raw.get('phase')=='finished' and raw.get('failed_phase')=='after' and raw.get('reason')=='Bounded explicit evidence pins required','Exact completed-Save packaging failure required')
    issue=raw.get('issue',{});require(issue.get('type')=='ValueError' and issue.get('hresult')is None and [(x.get('file'),x.get('function'))for x in issue.get('locations',[])]==[('sw_cam_current_pocket_context.py','save_current_baseline'),('sw_cam_current_pocket_context.py','_pins'),('sw_cam_process_import.py','require')],'Different failure is outside this admission')
    require(not any(k in raw for k in ('cleanup_error','runtime_error','receipt_write_error','current_context','postCL')),'Unrelated post-Save state not admitted')
    require(all(raw.get(k)is False for k in recovery.FLAGS),'Original uncertain flags must remain false')
    require(all(raw.get(k)is True for k in ('Save_attempted','save_attempted','save_readback_verified','model_saved','mutation_attempted','native_call_attempted','native_call_returned','receipt_created','marker_created')) and raw.get('native_dispatch_pending')is False,'Completed unique native Save required')
    require(all(raw.get(k)is False for k in ('operation_parameter_setters_attempted','setters_replayed','GTP_attempted','GTP_replayed','GOP_attempted','Import_attempted','CL_export_attempted','automatic_replay','production_qualified','native_units_verified','cutting_conditions_qualified')),'Only completed Save may precede this export')
    require(reader.shared.event_health(raw.get('messages',{}),active=False)==0 and raw['messages'].get('subscribed')is True and raw['messages'].get('subscription_error')is None,'Clean historical event cleanup required')
    require(list(raw.get('actions',{}))==['SaveActiveDocument'],'Exactly one historical Save action required');recovery.strict_return(raw['actions']['SaveActiveDocument'])
    require(raw.get('before')==raw.get('confirm_before')==raw['save_snapshots']['before']==expected and raw.get('second_capture_roles')==['generated_state_confirmation','save_before'],'Two fresh pre-Save captures differ from generated authority')
    require(raw['saved_file_sha256_after_native_return']==v['expected_source_sha256']!=old['expected_source_sha256'],'Exact completed changed Save source required')
    captures=raw.get('captures',[]);require([x.get('label')for x in captures]==['recovery_current','before','after'],'Complete three historical readback captures required')
    for item in captures:
        value=expected if item['label']=='recovery_current'else raw['save_snapshots'][item['label']]
        require(item.get('diagnostic',{}).get('capture_complete')is True and item.get('observation')==value and item['diagnostic'].get('state')==value['inventory'],'Incomplete or contradictory historical capture')
    return True


def marker_path(v):
    return Path(v['expected_document_path']).parent/('current_pocket_saved_cl_'+_digest(dict(scope=SCOPE,target=definition.creator.canonical(v['expected_document_path']),source_sha256=v['expected_source_sha256']))+'.json')


def prepare(v):
    shape(v);raw,rawpin=read_pin(v['saved_attempt_receipt_path'],v['saved_attempt_receipt_sha256'])
    failed,failedpin=read_pin(raw['historical_GTP_receipt_pin']['path'],raw['historical_GTP_receipt_pin']['sha256'])
    tool,toolpin=read_pin(raw['current_baseline_receipt_pin']['path'],raw['current_baseline_receipt_pin']['sha256'])
    require(toolpin==raw['current_baseline_receipt_pin']==failed['configuration_receipt_pin'],'Exact original accepted current context pin required')
    historical=historical_baseline(tool,toolpin,failed['request'],evidence_pins=raw['evidence_pins'])
    recipe,recipepin=read_pin(failed['request']['recipe_path'],failed['request']['recipe_sha256'])
    proof=recovery.verify_partial(failed,raw['request'],historical,recipe)
    require(raw['configuration_receipt_pin']==failedpin and raw['recipe']==recipe and raw['recipe_pin']==recipepin and raw['observed_feed_delta']==proof['feed_delta'] and raw['historical_generation_proof']==proof['generation_proof'],'Recovery history differs from original proof')
    verify_saved_attempt(raw,v,proof['expected_state'])
    pins=[]
    for owner,receipt,pin,mpath in ((generation,failed,failedpin,generation.marker_path(failed['request'])),(recovery,raw,rawpin,recovery.marker_path(raw['request']))):
        marker,markerpin=read_pin(str(mpath),_file_hash(mpath))
        expected=dict(scope=owner.SCOPE,receipt_path=receipt['request']['receipt_path'],receipt_sha256=pin['sha256'],configuration_receipt_pin=receipt['configuration_receipt_pin'],selected_operation_native_ids=[v['selected_operation_native_id']],status='uncertain',phase='finished',automatic_replay=False)
        require(marker==expected and definition.creator.same_path(receipt['request']['receipt_path'],pin['path']),'Consumed historical marker differs');pins.append(markerpin)
    saved=finalize.finalize_saved_context(raw,historical,proof['expected_state']);d=saved['context'];d['authority_scope']=finalize.GENERATED_SCOPE
    require(d['expected_source_sha256']==v['expected_source_sha256'] and saved['state']==raw['save_snapshots']['after']['inventory'] and saved['parameters']==raw['save_snapshots']['after']['parameters'],'Reconstructed current saved context differs')
    extra=[rawpin,failedpin,toolpin,recipepin]+pins+[reader.shared.file_pin(p,_file_hash(p))for p in (__file__,finalize.__file__,recovery.__file__,generation.__file__)]
    d['pins']=finalize.merge_pins(d['pins'],extra);definition.verify_files(d)
    payload=deepcopy(saved['payload']);require(payload['scope']==recovery.GENERATED_SCOPE,'Explicit generated scope required')
    payload.update(historical_generation_receipt_pin=failedpin,historical_save_receipt_pin=rawpin,observed_feed_delta=proof['feed_delta'])
    snapshot=dict(inventory=saved['state'],parameters=saved['parameters'])
    bundle=dict(context=d,state=saved['state'],parameters=saved['parameters'],receipt_pin=rawpin,root_pins=payload['root_pins'],lineage_pins=[rawpin],pins=d['pins'])
    receipt=Path(v['receipt_path']);marker=marker_path(v);cl=generation._fresh_path(v['saved_cl_path'])
    for output in (receipt,marker):require(output.suffix.lower()=='.json' and output.parent.is_dir() and not output.exists() and not output.is_symlink(),'Fresh receipt/marker required; no export replay')
    require(receipt!=marker and all(not definition.creator.same_path(str(output),p['path'])for output in(receipt,marker,cl)for p in d['pins']),'Outputs alias protected evidence')
    return dict(request=deepcopy(v),raw=raw,raw_pin=rawpin,failed_pin=failedpin,recipe=recipe,recipe_pin=recipepin,bundle=bundle,expected_state=snapshot,payload=payload,feed_delta=proof['feed_delta'],generation_proof=proof['generation_proof'],receipt=receipt,marker=marker,consumed=False)


class Backend(recovery.Backend):
    def save(self):raise ValueError('CL-only recovery forbids any native Save')


class Journal(engine.Journal):
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE)
    def action(self,name):require(name=='postCL','Only CL export is allowed');return super().action(name)
    def pending(self,name):require(name=='postCL','No Save, settings or generation replay');return super().pending(name)


def preflight(tlb):return generation.preflight(tlb)


def run_backend(backend,journal,data):
    r=journal.report;v=data['request'];oid=v['selected_operation_native_id']
    try:
        journal.create();backend.start();backend.boundary();journal.claim();journal.action('postCL')
        state=delta.flatten(data['expected_state']);selected=next(x for x in state['operations']if x['native_id']==oid)
        rows=[dict(operation_native_id=oid,toolpath_record_counts=selected['toolpath_record_counts'])];export={};r['postCL']=export
        backend.export_cl('postCL',state,rows,export,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value))
        recovery.strict_return(r['actions']['postCL']);require(export.get('output_verified')is True and export.get('readback_verified')is True,'Complete verified native export required')
        parsed=backend.parse_cl(export);r['first_CL_proof']=delta.verify_first_cl(parsed,oid,selected['toolpath_record_counts'][0]);journal.persist()
        backend.close();backend.runtime_check();document=backend.identity();require(document==backend.expected_document,'Current document changed during cleanup');backend.files()
        require(reader.shared.event_health(r['messages'],active=False)==0,'Clean current event cleanup required')
        r['after_cleanup_identity']=dict(document=document,saved_file_sha256=backend.source)
        r.update(status='review_required',phase='finished',**{k:True for k in FLAGS})
    except Exception as error:r.update(status='uncertain'if r.get('CL_export_attempted')else'error',failed_phase=r.get('phase'),phase='finished',reason=str(error),issue=_error(error),**{k:False for k in FLAGS})
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('CL_export_attempted')else'error',cleanup_error=_error(error),**{k:False for k in FLAGS})
        r['phase']='finished';journal.persist()
    return r


def run(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_backend_factory=Backend):
    data=prepare(v)if prepared is None else prepared;require(data.get('consumed')is False and data['request']==v,'Exact prepared CL-only request may be consumed once');data['consumed']=True
    abi=preflight(tlb);d=data['bundle']['context'];d['pins']=finalize.merge_pins(d['pins'],[abi['generated_pin'],reader.shared.file_pin(tlb,_file_hash(tlb))]);definition.verify_files(d);runtime_check()
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(v),configuration_receipt_pin=data['raw_pin'],historical_save_receipt_pin=data['raw_pin'],historical_GTP_receipt_pin=data['failed_pin'],historical_save_status='uncertain',historical_model_saved=True,historical_save_readback_verified=True,historical_runtime_unchanged=data['raw']['runtime_unchanged'],selected_operation_native_ids=[v['selected_operation_native_id']],current_context=deepcopy(data['payload']),saved=deepcopy(data['expected_state']),observed_feed_delta=data['feed_delta'],historical_generation_proof=data['generation_proof'],setup_transform=data['raw']['setup_transform'],setup_transform_proof=data['raw']['setup_transform_proof'],evidence_pins=deepcopy(d['pins']),abi=abi,actions={},captures=[],mutation_attempted=False,operation_parameter_setters_attempted=False,setters_replayed=False,GTP_attempted=False,GTP_replayed=False,GOP_attempted=False,Import_attempted=False,Save_attempted=False,save_attempted=False,model_saved=False,CL_export_attempted=False,automatic_replay=False,generated_current_context_readable_by_old_loader=False,feed_unqualified=True,feed_change_cause_verified=False,production_qualified=False,physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,island_geometry_verified=False,geometry_sweep_verified=False,reopen_persistence_verified=False,**{k:False for k in FLAGS})
    journal=Journal(data['receipt'],data['marker'],r);backend=_backend_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check,abi)
    return run_backend(backend,journal,data)


def revoke(r,error):
    r.update(status='uncertain'if r.get('CL_export_attempted')else'error',runtime_error=_error(error),**{k:False for k in FLAGS});reader._write_receipt(Path(r['request']['receipt_path']),r);return r
