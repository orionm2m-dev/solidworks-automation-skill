"""One export of existing stock on an empty saved MILL qualification copy.

Native False offset outs are discarded in this export-only observer. Existing
strict stock/material/AFR readers remain unchanged. Mesh comparison never changes
the offset status and does not authorize recognition or production.
"""
from copy import deepcopy
import hashlib,json,math,re
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap,_snapshot as _mill_snapshot,_int,_text
from scripts.sw_cam_mill_stock import _bbox,_bounded_read_value
from scripts.sw_cam_mill_inventory import capture_guarded_mill_inventory,validate_inventory_request,_same_inventory
from scripts.sw_cam_mill_afr_delta import validate_empty_afr_baseline,_json
from scripts.sw_cam_mill_geometry import _output_plan,_collect_files
from scripts.sw_cam_simulation import _check_output_path
from scripts.sw_cam_stock_mesh_compare import compare_stock_meshes
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path,check_document_target

SCOPE='MILL_EMPTY_EXISTING_STOCK_EXPORT_V1'


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Exact lowercase SHA256 required')


def _export_stock(workpiece,typelib_path,read,diagnostic):
    """Only a strict native False permits unavailable outs; no invented offsets."""
    stock=_typed(workpiece,'ICWMillWorkpiece',typelib_path)
    kind=_int(read(stock,'GetMillWorkpieceType'))
    if kind!=4:raise ValueError('Existing STL stock type4 required')
    result=dict(type_raw=kind,bounds_native=_bbox(read(stock,'GetBoundingBoxSize')))
    raw=read(stock,'GetWorkpieceFromSTLParam')
    if not isinstance(raw,(tuple,list)) or len(raw)!=4 or raw[-1] is not True:raise ValueError('Successful STL parameters required')
    result.update(stl_path=_text(raw[0]),length_units_raw=_int(raw[1]),coordinate_system=_text(raw[2]))
    offsets=read(stock,'GetSTLOffset')
    diagnostic['GetSTLOffset']=dict(method='GetSTLOffset',native_returned=True,raw=_bounded_read_value(offsets))
    if not isinstance(offsets,(tuple,list)) or len(offsets)!=10 or type(offsets[-1]) is not bool:
        raise ValueError('Exact ten-value offset output and strict Boolean result required')
    if offsets[-1] is False:
        # All nine out parameters, including Boolean flags, are invalid on failure.
        result.update(offset_read_status='unavailable_native_false',offsets_native=None,uniform_flags=None)
    else:
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in offsets[:6]) or any(type(x) is not bool for x in offsets[6:9]):
            raise ValueError('Invalid successful native STL offset shape')
        result.update(offset_read_status='observed_native_true',offsets_native=[float(x) for x in offsets[:6]],uniform_flags=list(offsets[6:9]))
    source=Path(result['stl_path'])
    if not source.is_absolute() or not source.is_file() or source.is_symlink():raise ValueError('Existing regular absolute stock STL required')
    result['stl_sha256']=_file_hash(source)
    return result,stock


def validate_empty_stock_export_request(*,process_id,expected_document_path,expected_source_sha256,
        expected_stock_path,expected_stock_sha256,expected_stock_bounds_native,output_dir,action,
        qualification_only,acknowledge_disposable_copy,acknowledge_document_wide_export,receipt_path,
        message_policy='vendor_default',expected_state_sha256=None,prepare_receipt_path=None,prepare_receipt_sha256=None):
    validate_inventory_request(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,qualification_only=qualification_only,
        acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,message_policy=message_policy)
    if action not in ('prepare','apply') or acknowledge_document_wide_export is not True:raise ValueError('Explicit prepare/apply and document-wide export acknowledgement required')
    _sha(expected_stock_sha256)
    if type(expected_stock_path) is not str or not absolute_document_path(expected_stock_path) or Path(expected_stock_path).suffix.casefold()!='.stl':
        raise ValueError('Exact absolute input stock STL path required')
    p=Path(expected_stock_path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>4*1024*1024 or _file_hash(p)!=expected_stock_sha256:raise ValueError('Bounded unchanged input stock STL required')
    if type(expected_stock_bounds_native) is not list:raise ValueError('Exact raw stock bounds list required')
    _bbox(expected_stock_bounds_native+[True])
    directory,canonical=_output_plan(output_dir)
    if (canonical/'stock.stl').resolve(strict=False)==p.resolve(strict=True):raise ValueError('Output cannot replace the input stock')
    credentials=(expected_state_sha256,prepare_receipt_path,prepare_receipt_sha256)
    if action=='prepare':
        if any(x is not None for x in credentials):raise ValueError('Prepare rejects apply credentials')
    else:
        _sha(expected_state_sha256);_sha(prepare_receipt_sha256)
        if type(prepare_receipt_path) is not str or not absolute_document_path(prepare_receipt_path) or Path(prepare_receipt_path).suffix.casefold()!='.json':
            raise ValueError('Exact absolute prepare JSON required')


def _prepared(path,sha,expected_state):
    # Same bounded immutable prepare/unique attempt protocol as the material tool.
    _sha(sha);_sha(expected_state);p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>16*1024*1024:raise ValueError('Bounded immutable prepare required')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha or _file_hash(p)!=sha:raise ValueError('Prepare receipt changed')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate prepare JSON key')
            result[key]=value
        return result
    data=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite prepare JSON')))
    if (type(data) is not dict or data.get('scope')!=SCOPE or data.get('action')!='prepare'
        or data.get('status')!='review_required' or data.get('apply_eligible') is not True
        or data.get('mutation_attempted') is not False or data.get('state_sha256')!=expected_state):
        raise ValueError('Successful unused stock export prepare required')
    if _digest(dict(request=data['request'],before=data['before']))!=expected_state:raise ValueError('Prepared payload digest mismatch')
    marker=Path(str(p)+'.apply_attempt.json')
    if marker.exists() or marker.is_symlink():raise ValueError('Prepare consumed; export cannot be replayed')
    return p,marker,data


def _baseline(state,request):
    validate_empty_afr_baseline(state)
    if state['material_raw']!='304L':raise ValueError('Exact current native material304L required')
    expected=dict(type_raw=4,bounds_native=[float(v) for v in request['expected_stock_bounds_native']],
        stl_path=request['expected_stock_path'],stl_sha256=request['expected_stock_sha256'],
        length_units_raw=0,coordinate_system='',offset_read_status='unavailable_native_false',
        offsets_native=None,uniform_flags=None)
    if _json(state['stock'])!=_json(expected):raise ValueError('Pinned STL path/hash/units/defaultCS/bounds/unavailable offset status changed')


def export_empty_mill_stock(sw,clsid,typelib_path,*,process_id,expected_document_path,expected_source_sha256,
        expected_stock_path,expected_stock_sha256,expected_stock_bounds_native,output_dir,action,
        qualification_only,acknowledge_disposable_copy,acknowledge_document_wide_export,receipt_path,
        message_policy='vendor_default',expected_state_sha256=None,prepare_receipt_path=None,prepare_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status='error',phase='preflight',action=action,may_continue=False,
        apply_eligible=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,native_return=None,readback_verified=False,export_files_verified=False,
        mesh_content_verified=False,offset_read_status='unavailable_native_false',offsets_verified=False,
        model_saved=False,stock_edit_attempted=False,material_edit_attempted=False,AFR_attempted=False,
        GOP_attempted=False,GTP_attempted=False,TechDB_write_attempted=False,production_qualified=False,
        physical_depth_verified=False,incoming_turn_WIP_verified=False,AFR_gate_opened=False,
        post_cleanup_CAM_getters=False,snapshot_diagnostics=[])
    request=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        expected_stock_path=expected_stock_path,expected_stock_sha256=expected_stock_sha256,
        expected_stock_bounds_native=deepcopy(expected_stock_bounds_native),output_dir=output_dir)
    report['request']=request
    session=receipt=prep=marker=prepared=baseline=None;created=False
    def persist():
        if created:_write_receipt(receipt,report)
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id:raise ValueError('Exact process changed')
        doc=raw_part_identity(sw)
        check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
        if _file_hash(expected_document_path)!=expected_source_sha256:raise ValueError('Current saved source changed')
        return doc
    def check(active=True):
        state=session.summary();report['messages']=state
        if (state.get('subscribed') is not True or (active and state.get('active') is not True)
            or (not active and (state.get('active') is not False or state.get('disconnected') is not True))
            or any(state.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM event transport requires stop; no replay')
    def capture(phase):
        check();report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
        state=capture_guarded_mill_inventory(sw,clsid,typelib_path,expected_document_path,
            process_id=process_id,expected_source_sha256=expected_source_sha256,check=check,diagnostic=diag,
            stock_reader=lambda workpiece,tlb,read:_export_stock(workpiece,tlb,read,diag))
        # Source read handles have closed on return; native export runs afterward.
        if state['document']!=baseline:raise ValueError('Captured document identity changed')
        _baseline(state,request)
        return state
    def input_pin():
        if _file_hash(expected_stock_path)!=expected_stock_sha256:raise ValueError('Input stock STL changed')
    try:
        validate_empty_stock_export_request(**request,action=action,qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,acknowledge_document_wide_export=acknowledge_document_wide_export,
            receipt_path=receipt_path,message_policy=message_policy,expected_state_sha256=expected_state_sha256,
            prepare_receipt_path=prepare_receipt_path,prepare_receipt_sha256=prepare_receipt_sha256)
        if action=='apply':
            prep,marker,prepared=_prepared(prepare_receipt_path,prepare_receipt_sha256,expected_state_sha256)
            if prepared['request']!=request:raise ValueError('Apply differs from prepared export request')
        directory,canonical=_output_plan(output_dir);output=directory/'stock.stl'
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        baseline=identity()
        if baseline['needs_save'] is not False:raise ValueError('Clean saved copy required')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            before=capture('initial_capture');report['before']=before
            if action=='apply' and not _same_inventory(prepared['before'],before):raise ValueError('Prepared complete empty inventory changed')
            report['state_sha256']=_digest(dict(request=request,before=before)) if action=='prepare' else expected_state_sha256
            persist();current=capture('before_native_action')
            if not _same_inventory(before,current):raise ValueError('Inventory changed immediately before export')
            input_pin()
            if action=='prepare':report['apply_eligible']=True
            else:
                header,native=_mill_snapshot(sw,clsid,typelib_path,expected_document_path,check=check,required_machine_type=1)
                if any(header[key]!=before[key] for key in header):raise ValueError('Native handle context changed')
                check();machine=_typed(native['machine'],'ICWMachine5',typelib_path);check()
                if _file_hash(prep)!=prepare_receipt_sha256:raise ValueError('Prepared evidence changed before export')
                _write_receipt(marker,dict(status='consumed',scope=SCOPE,prepare_sha256=prepare_receipt_sha256,
                    receipt_path=receipt_path,meaning='durable attempt reservation; not proof of native entry'),create=True)
                directory.mkdir()
                if directory.is_symlink() or directory.resolve(strict=True)!=canonical:raise ValueError('Output directory identity changed')
                _check_output_path(output,directory,canonical)
                report.update(phase='ICWMachine5.CreateSTLOfStock',native_dispatch_pending=True);persist();check()
                if identity()!=baseline:raise ValueError('Document/source changed immediately before export')
                input_pin();_check_output_path(output,directory,canonical)
                if any(directory.iterdir()):raise ValueError('Exclusive empty export directory required')
                check();report.update(mutation_attempted=True,native_call_attempted=True)
                returned=_member(machine,'CreateSTLOfStock',str(output),'',0)
                report.update(native_call_returned=True,native_dispatch_pending=False,native_return=_bounded_read_value(returned));persist();check()
                if returned is not True:raise ValueError('Strict True native stock export required')
                files=_collect_files(directory,canonical,'stock');report['files']=files
                if len(files)!=1:raise ValueError('Exactly one nonempty stock STL required')
                after=capture('after_native_action');report['after']=after;persist()
                if not _same_inventory(before,after):raise ValueError('Export changed captured document/CAM context')
                report.update(export_files_verified=True)
            check()
        check(active=False)
        if identity()!=baseline:raise ValueError('Document/source changed during event cleanup')
        input_pin()
        if action=='apply':
            if _collect_files(directory,canonical,'stock')!=report['files']:raise ValueError('Export files changed during cleanup')
            report.update(phase='pure_file_mesh_comparison');persist()
            report['mesh_comparison']=compare_stock_meshes(expected_stock_path,str(output))
            if report['mesh_comparison'].get('equivalent_within_verification_tolerance') is not True:raise ValueError('Complete mesh equivalence not established')
            if (report['mesh_comparison']['expected_file']['sha256']!=expected_stock_sha256
                or report['mesh_comparison']['actual_file']['sha256']!=report['files'][0]['sha256']):raise ValueError('Mesh proof file pins differ from native export')
            input_pin()
            if _collect_files(directory,canonical,'stock')!=report['files']:raise ValueError('Output changed after mesh comparison')
            if identity()!=baseline:raise ValueError('Document/source changed during mesh comparison')
            report['mesh_content_verified']=True
        report.update(status='review_required',phase='finished',readback_verified=True,
            reason='PREPARED_EXISTING_STOCK_EXPORT_ONLY' if action=='prepare' else 'EXPORTED_STOCK_MESH_COMPARED_OFFSET_STILL_UNAVAILABLE_AFR_GATE_UNCHANGED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],
            phase='finished',issue=_error(exc),failure_message=str(exc)[:2048],apply_eligible=False,readback_verified=False,mesh_content_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',receipt_write_error=_error(exc),apply_eligible=False,readback_verified=False,mesh_content_verified=False)
    return report
