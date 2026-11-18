"""Finalize already-recorded Save observations without any native call or replay.
Caller validates immutable receipt/history authority and supplies its prior bundle.
Only the admitted target source transitions; all other pins remain current.
"""
from copy import deepcopy
import re
from scripts import sw_cam_current_pocket_context as current
from scripts import sw_cam_pocket_definition_context as definition
from scripts.sw_cam_turn_tool import _digest

require=current.require
GENERATED_SCOPE='CURRENT_GENERATED_POCKET_CONTEXT_V1'


def merge_pins(left,right):
    """Two independently bounded lists; validate all, deduplicate, cap unique at64."""
    require(type(left)is list and type(right)is list and len(left)<=64 and len(right)<=64 and 1<=len(left)+len(right)<=128,'Two bounded pin lists required')
    out=[];seen={}
    for group in (left,right):
        valid=current._pins(group)if group else[]
        for pin in valid:
            key=definition.creator.canonical(pin['path'])
            require(key not in seen or seen[key]==pin['sha256'],'Conflicting evidence pins')
            if key not in seen:out.append(deepcopy(pin));seen[key]=pin['sha256']
    require(len(out)<=64,'Unique evidence pins exceed guard bound')
    return current._pins(out)


def saved_observation(report,bundle,expected_after):
    """Pure exact Save-record validation; no current-file checks and no mutation."""
    require(type(report)is dict and type(bundle)is dict,'Explicit recorded Save and predecessor bundle required')
    expected=current._snapshot(expected_after['inventory'],expected_after['parameters'])
    source=bundle['context']['expected_source_sha256'];native=report['native_save'];snapshots=report['save_snapshots']
    require(report.get('model_saved')is True and report.get('save_readback_verified')is True and report.get('Save_attempted')is True,'Completed recorded Save/readback facts required')
    require(report.get('current_baseline_receipt_pin')==bundle['receipt_pin'],'Recorded Save predecessor pin differs')
    require(type(native)is dict and native.get('phase')=='after_capture' and native.get('save_pending')is False,'Completed Save without pending native dispatch required')
    require(all(native.get(k)is True for k in ('save_attempted','mutation_attempted','native_call_attempted','native_call_returned','save_readback_verified')),'Complete native Save facts required')
    require(native.get('native_return_type')=='int' and type(native.get('native_return_value'))is int and native['native_return_value']==0,'Recorded native Save must be strict int0')
    require(type(snapshots)is dict and set(snapshots)=={'before','after'},'Exactly before/after Save observations required')
    before=current._snapshot(snapshots['before']['inventory'],snapshots['before']['parameters']);after=current._snapshot(snapshots['after']['inventory'],snapshots['after']['parameters'])
    require(before==expected and expected['inventory']['saved_file_sha256']==source,'Recorded Save before differs from admitted expected state/source')
    new_sha=report.get('saved_file_sha256_after_native_return')
    require(type(source)is str and re.fullmatch('[0-9a-f]{64}',source) and type(new_sha)is str and re.fullmatch('[0-9a-f]{64}',new_sha) and new_sha!=source,'Exact changed source hash required')
    require(native.get('saved_file_sha256')==new_sha==after['inventory']['saved_file_sha256'] and after['inventory']['document']['needs_save']is False,'Recorded Save hash and clean after state differ')
    normal=current._without_save_fields(expected)
    require(current._without_save_fields(after)==normal and native.get('before')==normal and native.get('after')==normal,'Save changed parameters, inventory or protected document state')
    require(before['inventory'].get('capture_complete')is True and after['inventory'].get('capture_complete')is True,'Complete inventory Save observations required')
    return dict(snapshot=after,before_sha256=source,after_sha256=new_sha)


def finalize_saved_context(report,bundle,expected_after):
    """File-only payload reconstruction; never calls Save, GTP or a CAD getter.

    Does not promote or rewrite the historical receipt. Completion/cleanup/current
    runtime authority still belongs to a new caller-owned observation receipt.
    """
    proof=saved_observation(report,bundle,expected_after);snapshot=proof['snapshot'];old=bundle['context']
    excluded={definition.creator.canonical(p['path'])for p in bundle.get('lineage_pins',[bundle['receipt_pin']])}
    extra=[p for p in old['pins']if not definition.creator.same_path(p['path'],old['expected_document_path']) and definition.creator.canonical(p['path'])not in excluded]
    roots=merge_pins(bundle['root_pins'],extra)
    now=definition.after_native_save_source(old,proof['after_sha256'],native_return_value=0)
    now['saved_plan_inventory']=deepcopy(snapshot['inventory']);now['saved_transition']['document']=deepcopy(snapshot['inventory']['document'])
    identity={k:deepcopy(old['request'][k])for k in ('process_id','expected_process_create_time','expected_document_path')}
    identity.update(expected_source_sha256=proof['after_sha256'],expected_feature_native_id=now['expected_feature_native_id'],expected_operation_native_ids=[r['native_id']for r in snapshot['inventory']['operations']])
    generated=any(row.get('toolpath_generated')is True for row in snapshot['inventory']['operations'])
    payload=dict(scope=GENERATED_SCOPE if generated else current.SCOPE,identity=identity,capture_context=current._compact(now),snapshot=deepcopy(snapshot),state_sha256=_digest(snapshot),root_pins=roots,predecessor_pin=deepcopy(bundle['receipt_pin']),limitations=deepcopy(current.LIMITS),source_transition=dict(before_sha256=proof['before_sha256'],after_sha256=proof['after_sha256'],native_return_value=0))
    return dict(context=now,state=deepcopy(snapshot['inventory']),parameters=deepcopy(snapshot['parameters']),payload=payload)
