"""Pinned export-only receipt evidence for documented raw-stock EMF qualification.

No native calls occur on load/check/verify. read_stock delegates only to the
existing observed-stock reader. Unavailable native offsets remain unavailable;
mesh evidence does not certify actual incoming WIP or authorize production.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import os
import re
from scripts.sw_cam_empty_mill_stock_export import _baseline, _export_stock
from scripts.sw_cam_mill_inventory import _same_inventory
from scripts.sw_cam_profile_sketch import _same_bodies
from scripts.sw_cam_mill_afr_delta import _json
from scripts.sw_cam_stock_mesh_compare import _read_pinned, _signature
from scripts.sw_cam_turn_tool import _digest

MAX_RECEIPT_BYTES = 16 * 1024 * 1024
_SCOPE = 'MILL_EMPTY_EXISTING_STOCK_EXPORT_V1'
_MODE = dict(value=1,name='MFGVIEW',status='observed_via_ICWDoc3_FeatureCreationStyle')
_TRUE = ('mutation_attempted','native_call_attempted','native_call_returned',
         'readback_verified','export_files_verified','mesh_content_verified')
_FALSE = ('may_continue','apply_eligible','native_dispatch_pending','offsets_verified',
          'model_saved','stock_edit_attempted','material_edit_attempted','AFR_attempted',
          'GOP_attempted','GTP_attempted','TechDB_write_attempted','production_qualified',
          'physical_depth_verified','incoming_turn_WIP_verified','AFR_gate_opened','post_cleanup_CAM_getters')


def _require(ok, text):
    if not ok: raise ValueError(text)


def _sha(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'Exact lowercase SHA256 required')


def _receipt_bytes(path):
    _require(type(path) is str,'Exact receipt path string required')
    p=Path(path)
    _require(p.is_absolute() and p.suffix.casefold()=='.json' and not p.is_symlink(),'Absolute non-symlink JSON receipt required')
    try:
        canonical=p.resolve(strict=True); before=p.stat()
        _require(p.is_file() and 1<=before.st_size<=MAX_RECEIPT_BYTES,'Bounded regular export receipt required')
        with p.open('rb') as stream:
            opened=os.fstat(stream.fileno())
            _require(_signature(before)[:-1]==_signature(opened)[:-1],'Receipt path/handle identity changed')
            data=stream.read(MAX_RECEIPT_BYTES+1)
            _require(_signature(opened)==_signature(os.fstat(stream.fileno())),'Receipt changed during read')
        _require(len(data)==before.st_size and _signature(before)[:-1]==_signature(p.stat())[:-1]
            and _signature(before)[:-1]==_signature(canonical.stat())[:-1]
            and not p.is_symlink() and canonical==p.resolve(strict=True),'Receipt path changed during read')
    except OSError as exc: raise ValueError('Export receipt unavailable') from exc
    return data,dict(path=str(p),canonical_path=str(canonical),bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),identity=list(_signature(opened)))


def _decode(data):
    def pairs(items):
        out={}
        for key,value in items:
            _require(key not in out,'Duplicate JSON key');out[key]=value
        return out
    def bad(_): raise ValueError('Nonfinite receipt JSON')
    try: obj=json.loads(data,object_pairs_hook=pairs,parse_constant=bad)
    except (RecursionError,UnicodeError,json.JSONDecodeError) as exc: raise ValueError('Invalid bounded receipt JSON') from exc
    pending=[(obj,0)];count=0
    while pending:
        value,depth=pending.pop();count+=1
        _require(depth<=64 and count<=200000,'Receipt JSON structure exceeds bounds')
        if type(value) is dict:pending.extend((v,depth+1) for v in value.values())
        elif type(value) is list:
            _require(len(value)<=8192,'Receipt JSON list exceeds bound');pending.extend((v,depth+1) for v in value)
        elif type(value) is float:_require(math.isfinite(value),'Nonfinite receipt JSON')
        elif type(value) is str:_require(len(value)<=16384,'Receipt JSON string exceeds bound')
    _require(type(obj) is dict,'Receipt object required');return obj


def _same_state(a,b):
    if not _same_inventory(a,b):return False
    # Existing helper owns body tolerance; all other fields retain JSON types.
    normalized=deepcopy(a);normalized['sw_reference']['solids']=deepcopy(b['sw_reference']['solids'])
    return _json(normalized)==_json(b)


class StockExportEvidence:
    def __init__(self,receipt,pin):
        self._receipt=deepcopy(receipt);self._pin=deepcopy(pin)
        self._before=deepcopy(receipt['before']);self._request=deepcopy(receipt['request'])
        self._input=deepcopy(receipt['mesh_comparison']['expected_file'])
        self._output=deepcopy(receipt['mesh_comparison']['actual_file'])

    def summary(self):
        return dict(kind='documented_raw_stock_export_mesh_evidence',receipt=deepcopy(self._pin),
            input_stl=deepcopy(self._input),native_export_stl=deepcopy(self._output),
            stock_snapshot_sha256=_digest(self._before['stock']),
            source_sha256=self._before['saved_file_sha256'],material_raw=self._before['material_raw'],
            recognition_method=deepcopy(self._before['recognition_method']),
            verification_tolerance_mm=0.0001,offset_read_status='unavailable_native_false',
            offsets_verified=False,incoming_turn_WIP_verified=False,production_qualified=False)

    def check_files(self):
        _,current=_receipt_bytes(self._pin['path'])
        _require(_json(current)==_json(self._pin),'Pinned export receipt changed')
        for expected in (self._input,self._output):
            _,current=_read_pinned(expected['path'])
            _require(_json(current)==_json(expected),'Original pinned stock STL changed or unavailable')
        return True

    def verify_initial(self,state):
        _baseline(state,self._request)
        _require(_same_state(self._before,state),'Initial full inventory differs from exported-stock evidence')
        return True

    def verify_geometry(self,state):
        """Compare every capture directly to the immutable Q16 body anchor."""
        try:
            _require(_same_bodies(self._before['sw_reference']['solids'],state['sw_reference']['solids']),
                'Solid geometry differs from immutable exported-stock anchor')
        except (KeyError,TypeError,IndexError) as exc:raise ValueError('Complete solid geometry snapshot required') from exc
        return True

    def read_stock(self,workpiece,tlb,read,diagnostic):
        # Deliberately stock-only: new features after EMF are checked by AFR delta.
        stock,native=_export_stock(workpiece,tlb,read,diagnostic)
        _require(_json(stock)==_json(self._before['stock']),'Observed stock changed from exported-stock evidence')
        return stock,native


def load_stock_export_evidence(path,sha,*,process_id,expected_document_path,
        expected_source_sha256,expected_material_raw,expected_stock_sha256,stock_basis):
    """expected_stock_sha256 pins the complete stock snapshot, not STL bytes."""
    for value in (sha,expected_source_sha256,expected_stock_sha256):_sha(value)
    _require(type(process_id) is int and process_id>0,'Strict positive process ID required')
    _require(type(expected_document_path) is str and Path(expected_document_path).is_absolute(),'Exact absolute document path required')
    _require(expected_material_raw=='304L' and type(expected_material_raw) is str,'Exact material 304L required')
    _require(stock_basis=='documented_raw_stock','Export evidence is for documented raw stock only')
    raw,pin=_receipt_bytes(path);_require(pin['sha256']==sha,'Export receipt SHA differs')
    data=_decode(raw)
    _require(all(data.get(k)==v for k,v in dict(scope=_SCOPE,status='review_required',phase='finished',action='apply').items()),'Finished successful stock-export apply receipt required')
    _require(all(data.get(k) is True for k in _TRUE) and all(data.get(k) is False for k in _FALSE),'Strict stock-export success/no-edit flags required')
    _require(_json(data.get('native_return'))==_json(dict(python_type='bool',value=True)),'Strict native True return evidence required')
    _require(data.get('offset_read_status')=='unavailable_native_false','Unavailable native offset status required')
    _require(not any(k in data for k in ('issue','failed_phase','failure_message','receipt_write_error')),'Receipt contains failure evidence')
    messages=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,
        event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])
    _require(_json(data.get('messages'))==_json(messages),'Clean disconnected event transport required')
    try:
        request=data['request'];before=data['before'];after=data['after']
        _require(type(request['process_id']) is int and request['process_id']==process_id
            and request['expected_document_path']==expected_document_path
            and request['expected_source_sha256']==expected_source_sha256,'Export request target differs')
        for state in (before,after):
            _baseline(state,request)
            _require(state['document']['path']==expected_document_path and state['saved_file_sha256']==expected_source_sha256
                and state['material_raw']==expected_material_raw and _json(state['recognition_method'])==_json(_MODE),'Source/material/observed MFGVIEW binding differs')
        _require(_same_state(before,after),'Stock export changed complete inventory')
        _require(_digest(before['stock'])==expected_stock_sha256,'Stock snapshot digest differs from EMF request')
        mesh=data['mesh_comparison'];inp=mesh['expected_file'];out=mesh['actual_file'];files=data['files']
        _require(mesh['status']=='PASS_CONVEX_STOCK_GEOMETRY_COMPARISON' and mesh['equivalent_within_verification_tolerance'] is True
            and mesh['files_pinned_before_after'] is True and mesh['coordinate_frame']=='WORLD' and mesh['units']=='mm'
            and type(mesh['verification_tolerance_mm']) is float and mesh['verification_tolerance_mm']==0.0001
            and all(mesh[k] is False for k in ('alignment_performed','rescaling_performed','reflection_performed','production_qualified'))
            and mesh['bounds_and_volume_are_corroboration_only'] is True,'Full fixed-frame convex mesh proof required')
        for side in ('expected_mesh','actual_mesh'):
            fact=mesh[side]
            for name,low,high in (('triangles',4,4096),('vertices',4,2048),('edges',6,6144),('unique_oriented_planes',4,4096)):
                _require(type(fact[name]) is int and low<=fact[name]<=high,'Bounded full-shell counts required')
            _require(fact['closed_connected_oriented_manifold'] is True and fact['vertex_links_single_cycles'] is True
                and type(fact['Euler_characteristic']) is int and fact['Euler_characteristic']==2
                and type(fact['signed_volume_mm3']) in (int,float) and fact['signed_volume_mm3']>0
                and type(fact['max_outward_vertex_plane_mm']) in (int,float) and fact['max_outward_vertex_plane_mm']<=0.0001,'Convex shell facts incomplete')
        count=mesh['mutual_containment']['vertex_plane_tests']
        _require(type(count) is int and 1<=count<=8000000,'Bounded positive mesh comparison count required')
        for key in ('expected_vertices_in_actual_max_signed_distance_mm','actual_vertices_in_expected_max_signed_distance_mm'):
            value=mesh['mutual_containment'][key]
            _require(type(value) in (int,float) and value<=0.0001,'Mutual full-mesh containment exceeds fixed tolerance')
        _require(type(files) is list and len(files)==1,'Exactly one original native export required')
        native=files[0];native_path=str(Path(request['output_dir'])/'stock.stl')
        _require(inp['path']==request['expected_stock_path']==before['stock']['stl_path']
            and inp['sha256']==request['expected_stock_sha256']==before['stock']['stl_sha256']
            and out['path']==native_path==native['path']==native['native_path']
            and out['canonical_path']==native['canonical_path']
            and out['sha256']==native['sha256'] and type(native['bytes']) is int and out['bytes']==native['bytes'],
            'Mesh proof does not bind original native output and input files')
        _require(inp['canonical_path']!=out['canonical_path'] and inp['identity'][:2]!=out['identity'][:2], 'Input and native output must be distinct files')
    except (KeyError,TypeError,IndexError) as exc:raise ValueError('Incomplete stock-export evidence') from exc
    result=StockExportEvidence(data,pin);result.check_files();return result
