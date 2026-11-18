"""Read-only current saved boundary, preserving the uncertain producer status.

No output allocation, native call, CL export, GTP or model Save. The exact
partial producer is proven by the existing verifier and immutable creation /
configuration ancestry. Live owner identity and a fresh native capture remain
caller obligations. CL content/geometry and WIP freshness are separate evidence.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_saved_finish_cl_recovery as recovery
from scripts import sw_cam_current_saved_finish_cl_context as context
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
generation=recovery.generation;delta=recovery.delta;history=recovery.history;partial=recovery.partial
require=delta.require;exact=delta.exact
SCOPE='CURRENT_SAVED_PARTIAL_TERMINAL_READ_AUTHORITY_V1'
KEYS=recovery.KEYS-{'receipt_path','saved_cl_path'}
_same=recovery._same

def dependency_paths():
    return (__file__,context.__file__,*recovery.dependency_paths())

def load_saved_boundary(v):
    require(type(v)is dict and set(v)==KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact saved-boundary read request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**32 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact current owner lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact lowercase file SHA required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute exact file path required')
    source=Path(v['expected_document_path']);sha=v['expected_source_sha256']
    require(source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==sha,'Exact current saved source required')
    r,rp=read_pin(v['generation_receipt_path'],v['generation_receipt_sha256'])
    require(_same(r['request']['expected_document_path'],source)and _same(r['request']['receipt_path'],rp['path'])and _same(r['receipt_path'],rp['path']),'Exact partial source and receipt required')
    require(exact(r['binding'],generation.binding(r['request']))and set(r['request'])==generation.KEYS,'Exact raw generation binding required')
    cf,cp=read_pin(r['configuration_receipt_pin']['path'],r['configuration_receipt_pin']['sha256'])
    require(exact(cp,r['configuration_receipt_pin']),'Original configuration pin changed')
    boundary=partial.verify_partial(r,cf,source_sha256=sha,process_id=v['process_id'],process_create_time=v['expected_process_create_time'])
    old_marker=generation.marker_path(r['request']);require(_same(old_marker,r['dispatch_marker_path']),'Original consumed GTP marker differs')
    mark,mp=read_pin(str(old_marker),_file_hash(old_marker))
    expected=dict(scope=generation.SCOPE,receipt_path=rp['path'],receipt_sha256=rp['sha256'],configuration_receipt_pin=cp,selected_operation_native_ids=[boundary['operation_id']],status='uncertain',phase='finished',automatic_replay=False)
    require(_same(mark['receipt_path'],rp['path']),'Old marker receipt path differs');marked=deepcopy(mark);marked['receipt_path']=rp['path'];require(exact(marked,expected),'Exact consumed uncertain generation marker required')
    # Revalidate the original configured lineage once, separating its historical
    # saved SHA from the later Save proven above. Raw historical records stay intact.
    data=history.load_history(cp['path'],cp['sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=str(source),source_sha256=r['source_before_sha256'],physical_source_sha256=sha)
    require(exact(data['pin'],cp)and delta.configuration.circular.circular_state_equal(data['state'],r['before']),'Exact configured ancestor required')
    pins=list(data['pins'])+[rp,mp]
    for p in r['evidence_pins']:
        if _same(p['path'],source):require(p['sha256']==r['source_before_sha256'],'Only original generation source pin may advance');continue
        generation.creation.partial._observed_pin(p);pins.append(p)
    pins += [generation.creation.partial._filepin(p)for p in dependency_paths()]
    pins.append(dict(path=str(source),sha256=sha));unique={}
    for p in pins:
        observed=generation.creation.partial._observed_pin(p);key=str(Path(p['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==observed['sha256'],'Conflicting recovery pin');unique[key]=observed
    data.update(pins=list(unique.values()),generation_receipt=deepcopy(r),generation_receipt_pin=rp,generation_marker_pin=mp,saved_boundary_proof=boundary,recovery_saved_state=deepcopy(boundary['state']),source_sha256=sha)
    data['configuration_data']['state']=deepcopy(boundary['state'])
    data['configuration_data']['pins']=deepcopy(data['pins'])
    require(_file_hash(source)==sha and read_pin(rp['path'],rp['sha256'])[1]==rp,'Recovery inputs changed during preparation')
    data.update(authority_scope=SCOPE, original_terminal_status=r['status'], original_runtime_unchanged=r['runtime_unchanged'], native_calls=0, source_authority='verified_partial_saved_boundary', completed_producer_claimed=False)
    return data
