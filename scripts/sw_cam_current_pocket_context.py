"""Bounded current pocket authority and one existing Save; no new CAM API.
The first pair read anchors geometry. Later receipts carry the exact current
snapshot and direct predecessor pin without recursively replaying history.
"""
from copy import deepcopy
from pathlib import Path
import math
import re
from scripts import sw_cam_pocket_definition_context as definition
from scripts import sw_cam_current_pocket_pair_read as pair
from scripts import sw_cam_process_import as shared
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_ud14_save import run_one_existing_save

require=shared.require
SCOPE='CURRENT_SAVED_POCKET_CONTEXT_V1'
LIMITS=dict(persistence_verified=False,island_geometry_verified=False,physical_depth_verified=False,physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,production_qualified=False)
IDENTITY_KEYS=('process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids')
CAPTURE_KEYS=('scope','process_id','expected_document_path','expected_source_sha256','expected_feature_native_id','evidence','save_pin','saved_transition','expected_inventory','current_sketch_baseline','spec')


def _pins(pins):
    require(type(pins)is list and 1<=len(pins)<=64,'Bounded explicit evidence pins required')
    out=[];seen={}
    for pin in pins:
        require(type(pin)is dict and type(pin.get('path'))is str and Path(pin['path']).is_absolute()
                and type(pin.get('sha256'))is str and re.fullmatch('[0-9a-f]{64}',pin['sha256']),'Exact evidence pin required')
        key=definition.creator.canonical(pin['path'])
        require(key not in seen or seen[key]==pin['sha256'],'Conflicting evidence pins')
        if key not in seen:out.append(deepcopy(pin));seen[key]=pin['sha256']
    return out


def _compact(d):
    out={k:deepcopy(d[k])for k in CAPTURE_KEYS}
    out['request']={k:deepcopy(d['request'][k])for k in ('process_id','expected_process_create_time','expected_document_path','expected_sw_configuration','expected_cam_configuration','owner_setup_native_id')}
    out['creator']={k:deepcopy(d['creator'][k])for k in ('status','feature_header')}
    out['sketch']={'sketch_readback':deepcopy(d['sketch']['sketch_readback'])}
    out['saved_transition']={'document':deepcopy(d['saved_transition']['document'])}
    if definition.creator.saved_caps(d['request']):
        # Keep only the current-circle branch needed by definition.capture.
        # Historical sketch evidence and the genuine origin stay distinct.
        out['request']['source_variant']=d['request']['source_variant']
        out['creator']['circle_readback']=deepcopy(d['creator']['circle_readback'])
        out['origin_kind']=d['origin_kind']
    return out


def _snapshot(inventory,parameters):
    require(type(inventory)is dict and type(parameters)is list and len(parameters)==2,'Complete two-operation snapshot required')
    ids=[r['native_id']for r in inventory['operations']]
    require(len(ids)==2 and all(type(i)is int and 0<i<2**31 for i in ids) and len(set(ids))==2,'Exact two unique operation IDs required')
    require([r['operation_native_id']for r in parameters]==ids and all(r.get('read_complete')is True for r in parameters),'Complete ordered native parameter rows required')
    require(inventory['document']['needs_save']in (True,False) and type(inventory['document']['needs_save'])is bool,'Observed document dirty boolean required')
    return dict(inventory=deepcopy(inventory),parameters=deepcopy(parameters))


def _without_save_fields(snapshot):
    out=deepcopy(snapshot);out['inventory'].pop('saved_file_sha256');out['inventory']['document'].pop('needs_save');return out


def _check_request(v,identity):
    require(type(v)is dict,'Current context request object required')
    for k in IDENTITY_KEYS:
        require(k in v and k in identity,'Complete explicit current identity required')
        if k=='expected_document_path':require(definition.creator.same_path(v[k],identity[k]),'Current target path differs')
        else:require(type(v[k])is type(identity[k]) and v[k]==identity[k],'Current identity differs: '+k)
    require(type(v['process_id'])is int and v['process_id']>0 and type(v['expected_feature_native_id'])is int and v['expected_feature_native_id']>0,'Strict process/feature identities required')
    require(type(v['expected_process_create_time'])in(int,float) and math.isfinite(v['expected_process_create_time']),'Finite exact process lifetime required')


def _root_pins(receipt,pin):
    target=receipt['request']['expected_document_path']
    return _pins([p for p in receipt['evidence_pins']if not definition.creator.same_path(p['path'],target)]+[pin])


def _bind(d,state,parameters,root_pins,receipt_pin):
    d=deepcopy(d);d['saved_plan_inventory']=deepcopy(state)
    d['expected_operation_native_ids']=[r['native_id']for r in state['operations']]
    d['authority_scope']=SCOPE;d['expected_source_sha256']=state['saved_file_sha256']
    d['current_sketch_baseline']['saved_file_sha256']=state['saved_file_sha256']
    d['saved_transition']['document']=deepcopy(state['document'])
    d['pins']=_pins(root_pins+[receipt_pin,shared.file_pin(d['expected_document_path'],d['expected_source_sha256'])])
    definition.verify_files(d)
    return dict(context=d,state=deepcopy(state),parameters=deepcopy(parameters),receipt_pin=deepcopy(receipt_pin),root_pins=deepcopy(root_pins),lineage_pins=[deepcopy(receipt_pin)],pins=d['pins'])


def load_current_baseline(v):
    """Load one immediate accepted current baseline; no native calls."""
    receipt,pin=read_pin(v['current_context_receipt_path'],v['current_context_receipt_sha256'])
    if receipt.get('scope')==pair.SCOPE:
        require(receipt.get('status')=='observed' and receipt.get('phase')=='finished' and receipt.get('read_only')is True,'Completed pair reader required')
        for k in pair.FLAGS:require(receipt.get(k)is True,'Successful pair observation required: '+k)
        for k in ('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','Import_attempted','tool_creation_attempted','tool_assignment_attempted','automatic_replay','physical_tool_qualified','native_units_verified','cutting_conditions_qualified','island_geometry_verified','production_qualified'):
            require(receipt.get(k)is False,'Unexpected initial read action/qualification: '+k)
        definition.creator.clean(receipt);_check_request(v,receipt['request'])
        d=definition.load_saved_plan(receipt['request'])
        state=receipt['after'];require(receipt['before']==state==d['saved_plan_inventory'],'Initial pair inventory is not the saved authority')
        require(receipt['source_before_sha256']==receipt['source_after_sha256']==v['expected_source_sha256'],'Initial pair source differs')
        require(receipt['after_cleanup_identity']==dict(document=state['document'],saved_file_sha256=v['expected_source_sha256']),'Initial read cleanup differs')
        for label in ('before','after'):
            diag=receipt[label+'_diagnostic'];require(diag.get('capture_complete')is True and diag.get('state')==state,'Initial complete inventory capture required')
        snapshot=_snapshot(state,receipt['parameters']);roots=_root_pins(receipt,pin)
        old={(definition.creator.canonical(p['path']),p['sha256'])for p in roots}
        require(all((definition.creator.canonical(p['path']),p['sha256'])in old for p in d['pins']if not definition.creator.same_path(p['path'],v['expected_document_path'])),'Current read omitted root evidence')
        return _bind(_compact(d),snapshot['inventory'],snapshot['parameters'],roots,pin)
    return _load_current_receipt(receipt,pin,v)


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
    require(previous.get('phase')=='finished' and ((previous.get('scope')==pair.SCOPE and previous.get('status')=='observed' and all(previous.get(k)is True for k in pair.FLAGS))or(previous.get('status')=='review_required' and previous.get('current_context_verified')is True and previous.get('current_context',{}).get('scope')==SCOPE)),'Direct predecessor must be a completed current observation')
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
