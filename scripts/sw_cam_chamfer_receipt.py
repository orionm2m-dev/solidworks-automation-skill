"""Bounded offline loader for a completed saved Contour approach receipt.

The complete immutable writer receipt remains the authority. This loader allows
its measured larger observation tree without changing the generic JSON decoder,
the pinned native writer, or any source/model bytes. No application connection.
"""
from copy import deepcopy
import json
import math
from scripts import sw_cam_chamfer_approach_correction as writer
from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes, _sha
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest

MAX_NODES=350000
MAX_DEPTH=32
MAX_LIST=8192
MAX_STRING=16384
common,group,exports=writer.common,writer.group,writer.exports


def decode_completed(data):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON key in completed receipt')
            result[key]=value
        return result
    def bad(_):raise ValueError('Nonfinite completed receipt JSON')
    try:value=json.loads(data,object_pairs_hook=pairs,parse_constant=bad)
    except (RecursionError,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('Invalid bounded completed receipt JSON') from exc
    require(type(value) is dict and value.get('scope')==writer.SCOPE
        and value.get('status')=='review_required' and value.get('phase')=='finished'
        and value.get('readback_verified') is True and value.get('model_saved') is True,
        'Only a completed saved Contour approach receipt is accepted')
    pending=[(value,0)];count=0
    while pending:
        item,depth=pending.pop();count+=1
        require(count<=MAX_NODES and depth<=MAX_DEPTH,'Completed receipt structure exceeds scoped bounds')
        if type(item) is dict:pending.extend((v,depth+1) for v in item.values())
        elif type(item) is list:
            require(len(item)<=MAX_LIST,'Completed receipt list exceeds bound')
            pending.extend((v,depth+1) for v in item)
        elif type(item) is float:require(math.isfinite(item),'Nonfinite completed receipt value')
        elif type(item) is str:require(len(item)<=MAX_STRING,'Completed receipt string exceeds bound')
    return value


def read_completed(path,digest):
    _sha(digest);raw,pin=_receipt_bytes(path)
    require(pin['sha256']==digest,'Completed receipt SHA differs')
    return decode_completed(raw),pin


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    """Use the unchanged writer validators and current saved flat authority."""
    r,pin=read_completed(path,digest)
    require(r['module_pin']==common._pin(writer.__file__) and r['process_id']==process_id
        and common._key(r['source_path'])==common._key(expected_document_path)
        and common._key(r['receipt_path'])==common._key(path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),
        'Current writer runtime/process/source differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    require(r['historical_source_pin']['sha256']==r['initial_source_sha256']
        and _file_hash(r['historical_source_pin']['path'])==r['initial_source_sha256'],'Original source archive differs')
    recipe,_=read_pin(r['recipe_pin']['path'],r['recipe_pin']['sha256'])
    require(group.exact(recipe,r['plan']),'Completed recipe changed')
    checkpoint=writer.validate_terminal(r)
    require(group.exact(checkpoint,r['checkpoint']) and _digest(checkpoint)==r['checkpoint_sha256'],
        'Flat completed checkpoint differs')
    marker=writer.continuation_marker_path(r) if r.get('continuation') else writer.marker_path(
        r['source_path'],r['initial_source_sha256'],r['operation_native_id'])
    mark,marker_pin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(common._key(marker)==common._key(r['marker_pin']['path'])
        and group.exact(mark,writer.Journal(r,path,marker).marker_state()),'Stable terminal marker differs')
    context=deepcopy(checkpoint['context'])
    live=common._merge([v for v in r['live_pins'] if common._key(v['path'])!=common._key(r['parent_pin']['path'])],
        [pin,common._pin(__file__)])
    require(len(live)<=64,'Bounded completed receipt loader dependency closure required')
    offline=common._merge(r['offline_proof_pins'],[r['parent_pin'],marker_pin])
    context.update(pins=live,offline_export_proof_pins=offline,parent_pin=pin,group_marker_pin=marker_pin,
        bootstrap_export_pins=deepcopy(r['bootstrap_export_pins']))
    exports.operation_contract(context);exports.validate_catalogue_authority(context)
    return context
