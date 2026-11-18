"""Opt-in 128-pin current context; legacy files and their pinned hashes stay intact.
Only capacity and scope differ. Save uses the same run_one_existing_save native
primitive and exact before/after checks. Generated GTP receipts are deliberately
not admitted by the generic context loader.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_current_pocket_context as legacy
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest

definition=legacy.definition
pair=legacy.pair
shared=legacy.shared
require=legacy.require
LIMITS=legacy.LIMITS
IDENTITY_KEYS=legacy.IDENTITY_KEYS
SCOPE='CURRENT_SAVED_POCKET_CONTEXT_V2_PIN128'
PIN_LIMIT=128
_compact=legacy._compact
_snapshot=legacy._snapshot
_without_save_fields=legacy._without_save_fields
_check_request=legacy._check_request
_root_pins=legacy._root_pins

def _pins(pins):
    require(type(pins)is list and 1<=len(pins)<=PIN_LIMIT,'Bounded explicit evidence pins required')
    out=[];seen={}
    for pin in pins:
        require(type(pin)is dict and type(pin.get('path'))is str and Path(pin['path']).is_absolute()
                and type(pin.get('sha256'))is str and re.fullmatch('[0-9a-f]{64}',pin['sha256']),'Exact evidence pin required')
        key=definition.creator.canonical(pin['path'])
        require(key not in seen or seen[key]==pin['sha256'],'Conflicting evidence pins')
        if key not in seen:out.append(deepcopy(pin));seen[key]=pin['sha256']
    return out

def pin_union(*groups):
    merged={}
    for pin in (p for group in groups for p in group):
        require(type(pin)is dict and type(pin.get('path'))is str and Path(pin['path']).is_absolute() and type(pin.get('sha256'))is str and re.fullmatch('[0-9a-f]{64}',pin['sha256']),'Exact evidence pin required')
        key=definition.creator.canonical(pin['path'])
        require(key not in merged or merged[key]['sha256']==pin['sha256'],'Conflicting evidence pins')
        merged.setdefault(key,deepcopy(pin))
    return _pins(list(merged.values()))


def save_bundle_for_context(bundle):
    """Preserve the exact authority union while removing duplicate Save inputs."""
    out=deepcopy(bundle);d=out['context']
    excluded={definition.creator.canonical(p['path'])for p in out.get('lineage_pins',[out['receipt_pin']])}
    extra=[p for p in d['pins']if not definition.creator.same_path(p['path'],d['expected_document_path']) and definition.creator.canonical(p['path'])not in excluded]
    keys={(definition.creator.canonical(p['path']),p['sha256'])for p in extra}
    original={(definition.creator.canonical(p['path']),p['sha256'])for p in out['root_pins']}
    context_keys={(definition.creator.canonical(p['path']),p['sha256'])for p in d['pins']}
    require(original<=context_keys,'Full guarded context omitted a prior root pin')
    out['root_pins']=[p for p in out['root_pins']if (definition.creator.canonical(p['path']),p['sha256'])not in keys]
    final=_pins(out['root_pins']+extra)
    require(original|keys=={(definition.creator.canonical(p['path']),p['sha256'])for p in final},'Save preparation changed canonical evidence union')
    require(len(final)<=PIN_LIMIT-3,'Reserve slots for current receipt, target and predecessor')
    return out


def load_current_baseline(v):
    receipt,pin=read_pin(v['current_context_receipt_path'],v['current_context_receipt_sha256'])
    if receipt.get('current_context',{}).get('scope')==SCOPE:
        return _load_current_receipt(receipt,pin,v)
    return legacy.load_current_baseline(v)

def _bind(d,state,parameters,root_pins,receipt_pin):
    d=deepcopy(d);d['saved_plan_inventory']=deepcopy(state)
    d['expected_operation_native_ids']=[r['native_id']for r in state['operations']]
    d['authority_scope']=SCOPE;d['expected_source_sha256']=state['saved_file_sha256']
    d['current_sketch_baseline']['saved_file_sha256']=state['saved_file_sha256']
    d['saved_transition']['document']=deepcopy(state['document'])
    d['pins']=_pins(root_pins+[receipt_pin,shared.file_pin(d['expected_document_path'],d['expected_source_sha256'])])
    definition.verify_files(d)
    return dict(context=d,state=deepcopy(state),parameters=deepcopy(parameters),receipt_pin=deepcopy(receipt_pin),root_pins=deepcopy(root_pins),lineage_pins=[deepcopy(receipt_pin)],pins=d['pins'])

def _load_current_receipt(r,pin,v):
    require(r.get('status')=='review_required' and r.get('phase')=='finished','Completed current mutation receipt required')
    for k in ('current_context_verified','save_readback_verified','inventory_delta_verified','parameter_delta_verified','runtime_unchanged'):
        require(r.get(k)is True,'Completed current-context fact required: '+k)
    for k in ('GOP_attempted','GTP_attempted','Import_attempted','automatic_replay','production_qualified'):
        require(r.get(k)is False,'Unexpected current-context action/qualification: '+k)
    definition.creator.clean(r)
    p=r['current_context'];require(p['scope']==SCOPE and p['limitations']==LIMITS,'Exact unqualified current-context scope required')
    _check_request(v,p['identity']);state=p['snapshot']['inventory'];parameters=p['snapshot']['parameters'];_snapshot(state,parameters)
    require(p['state_sha256']==_digest(p['snapshot']) and state['saved_file_sha256']==v['expected_source_sha256'] and state['document']['needs_save']is False,'Exact saved current snapshot required')
    require(r['save_snapshots']['after']==p['snapshot'],'Current context must be the actual after-Save observation')
    require(r['current_baseline_receipt_pin']==p['predecessor_pin'],'Direct predecessor binding differs')
    previous,previous_pin=read_pin(p['predecessor_pin']['path'],p['predecessor_pin']['sha256'])
    require(previous.get('phase')=='finished' and ((previous.get('scope')==pair.SCOPE and previous.get('status')=='observed' and all(previous.get(k)is True for k in pair.FLAGS))or(previous.get('status')=='review_required' and previous.get('current_context_verified')is True and previous.get('current_context',{}).get('scope')in (legacy.SCOPE,SCOPE))),'Direct predecessor must be a completed current observation')
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
    out=_bind(d,state,parameters,roots,pin)
    out['lineage_pins'].append(previous_pin);out['context']['pins']=_pins(out['context']['pins']+[previous_pin]);out['pins']=out['context']['pins'];definition.verify_files(out['context']);return out

def save_current_baseline(report,bundle,expected_after,*,capture,guard,claim,persist,save,adopt_context):
    """Reuse one proven Save primitive; callbacks own native/session boundaries.

    capture returns {inventory,parameters} and closes all file-holding guards.
    save is exactly one already-bound ICWApp.SaveActiveDocument invocation.
    The caller alone sets terminal current_context_verified after cleanup.
    """
    expected=_snapshot(expected_after['inventory'],expected_after['parameters']);source=bundle['context']['expected_source_sha256']
    require(expected['inventory']['saved_file_sha256']==source,'Expected after-tool source differs')
    current=deepcopy(bundle['context']);report['save_snapshots']={};report['current_baseline_receipt_pin']=deepcopy(bundle['receipt_pin'])
    report['current_context_verified']=False;save_record={};report['native_save']=save_record
    def read(label):
        observed=capture(label);_snapshot(observed['inventory'],observed['parameters'])
        require(observed['inventory']['saved_file_sha256']==current['expected_source_sha256'],'Captured current Save source differs')
        if label=='after':require(observed['inventory']['document']['needs_save']is False,'Native Save did not leave a clean document')
        report['save_snapshots'][label]=deepcopy(observed);persist()
        normalized=_without_save_fields(observed)
        require(normalized==_without_save_fields(expected),'Save boundary differs from allowed after-tool state')
        return normalized
    def verify(observed):require(observed==_without_save_fields(expected),'Complete saved state differs')
    def saved_hash():
        nonlocal current
        new_sha=_file_hash(current['expected_document_path'])
        report['saved_file_sha256_after_native_return']=new_sha;persist()
        current=definition.after_native_save_source(current,new_sha,native_return_value=save_record['native_return_value'])
        new_state=deepcopy(expected['inventory']);new_state.update(saved_file_sha256=new_sha);new_state['document']['needs_save']=False
        current['saved_plan_inventory']=new_state;current['saved_transition']['document']=deepcopy(new_state['document'])
        adopt_context(current);report['model_saved']=True;persist();return new_sha
    def persist_save():
        if save_record.get('save_attempted')is True:report['Save_attempted']=True
        persist()
    run_one_existing_save(save_record,capture=read,verify=verify,guard=guard,claim=claim,persist=persist_save,save=save,saved_hash=saved_hash)
    report['save_readback_verified']=True;report['Save_attempted']=True
    snapshot=deepcopy(report['save_snapshots']['after'])
    identity={k:deepcopy(bundle['context']['request'][k])for k in ('process_id','expected_process_create_time','expected_document_path')}
    identity.update(expected_source_sha256=current['expected_source_sha256'],expected_feature_native_id=current['expected_feature_native_id'],expected_operation_native_ids=[r['native_id']for r in snapshot['inventory']['operations']])
    excluded={definition.creator.canonical(p['path'])for p in bundle.get('lineage_pins',[bundle['receipt_pin']])}
    extra=[p for p in current['pins']if not definition.creator.same_path(p['path'],current['expected_document_path']) and definition.creator.canonical(p['path'])not in excluded]
    roots=_pins(bundle['root_pins']+extra)
    payload=dict(scope=SCOPE,identity=identity,capture_context=_compact(current),snapshot=snapshot,state_sha256=_digest(snapshot),
        root_pins=roots,predecessor_pin=deepcopy(bundle['receipt_pin']),limitations=deepcopy(LIMITS),
        source_transition=dict(before_sha256=source,after_sha256=current['expected_source_sha256'],native_return_value=0))
    report['current_context']=deepcopy(payload);persist()
    return dict(context=current,state=snapshot['inventory'],parameters=snapshot['parameters'],payload=payload)
