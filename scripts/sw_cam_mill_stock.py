"""Guarded manufacturing-stock assignment for separate MILL qualification copies.
The STL is reviewed machining stock/WIP, never the source of the product model.
"""
from __future__ import annotations
from copy import deepcopy
import json
import math
from pathlib import Path
from scripts.sw_cam import _error,_member,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap,_snapshot as _mill_snapshot,_int,_text
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import absolute_document_path


def _bbox(raw):
    if not isinstance(raw,(tuple,list)) or len(raw)!=7 or raw[-1] is not True:raise ValueError('Successful six-value native stock bounds required')
    values=raw[:6]
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in values):raise ValueError('Finite stock bounds required')
    if any(values[i]>=values[i+3] for i in range(3)):raise ValueError('Stock must have positive dimensions')
    return [float(x) for x in values]


def _stock(workpiece,typelib_path,read):
    stock=_typed(workpiece,'ICWMillWorkpiece',typelib_path)
    kind=_int(read(stock,'GetMillWorkpieceType'))
    result=dict(type_raw=kind,bounds_native=_bbox(read(stock,'GetBoundingBoxSize')))
    if kind==4:
        raw=read(stock,'GetWorkpieceFromSTLParam')
        if not isinstance(raw,(tuple,list)) or len(raw)!=4 or raw[-1] is not True:raise ValueError('Successful STL stock readback required')
        result.update(stl_path=_text(raw[0]),length_units_raw=_int(raw[1]),coordinate_system=_text(raw[2]))
        offsets=read(stock,'GetSTLOffset')
        if not isinstance(offsets,(tuple,list)) or len(offsets)!=10 or offsets[-1] is not True:raise ValueError('Successful STL offset readback required')
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in offsets[:6]) or any(type(x) is not bool for x in offsets[6:9]):raise ValueError('Invalid native STL offset shape')
        result.update(offsets_native=[float(x) for x in offsets[:6]],uniform_flags=list(offsets[6:9]))
        source=Path(result['stl_path'])
        if not source.is_absolute() or not source.is_file():raise ValueError('Native STL stock path must exist')
        result['stl_sha256']=_file_hash(source)
    return result,stock


def _snapshot(sw,clsid,typelib_path,expected_path,*,check=lambda:None):
    base,native=_mill_snapshot(sw,clsid,typelib_path,expected_path,check=check)
    if base['current_machine']['machine_type']!=1:raise ValueError('MILL machine required')
    def read(obj,name,*args):check();v=_member(obj,name,*args);check();return v
    workpiece=read(native['machine'],'IGetWorkpiece')
    if workpiece is None or not bool(workpiece):raise ValueError('Existing native workpiece required')
    values,stock=_stock(workpiece,typelib_path,read)
    final,_=_mill_snapshot(sw,clsid,typelib_path,expected_path,check=check)
    if final!=base:raise ValueError('Document definitions changed during stock read')
    base['stock']=values;native['stock']=stock
    return base,native


def _evidence(value,stl_path,stl_sha256,target_sha):
    if not isinstance(value,dict) or set(value)!={'path','sha256'}:raise ValueError('Hash-bound manufacturing-stock evidence required')
    path=Path(value['path']) if isinstance(value.get('path'),str) else None
    if path is None or not path.is_absolute() or not path.is_file() or path.stat().st_size>1048576:raise ValueError('Bounded absolute evidence file required')
    if _file_hash(path)!=value['sha256']:raise ValueError('Stock evidence hash changed')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if (data.get('status')!='reviewed_manufacturing_stock' or data.get('source_kind') not in ('turning_simulation_wip','machining_allowance_model')
            or data.get('stock_stl_sha256')!=stl_sha256 or data.get('target_part_sha256')!=target_sha
            or data.get('units')!='mm' or data.get('geometric_containment_verified') is not True):
        raise ValueError('Stock must be reviewed WIP/allowance geometry containing this target, in mm')
    if Path(data.get('stock_stl_path','')).resolve()!=Path(stl_path).resolve():raise ValueError('Stock evidence is for another file')
    for name in ('derivation','containment_evidence_path'):
        if not isinstance(data.get(name),str) or not data[name].strip():raise ValueError('Stock derivation/containment proof required')
    proof=Path(data['containment_evidence_path'])
    if not proof.is_absolute() or not proof.is_file() or _file_hash(proof)!=data.get('containment_evidence_sha256'):raise ValueError('Containment proof file/hash required')
    return dict(path=str(path),sha256=value['sha256'],source_kind=data['source_kind'],units='mm',
                scope='caller_reviewed_manufacturing_stock_not_independent_geometric_recalculation')


def configure_mill_stock(sw,clsid,typelib_path,*,expected_document_path,action,
        stl_path=None,stl_sha256=None,stock_evidence=None,expected_state_sha256=None,receipt_path=None,
        qualification_only,message_policy):
    """DefineWorkpieceFromSTL2 with explicit millimetres, default CS and no bounding-box replacement.
    Does not alter material, units setting, setups, features, tools, operations or product geometry.
    """
    from scripts.sw_cam_events import CamMessageSession
    if qualification_only is not True or message_policy!='vendor_default':raise ValueError('Qualification/vendor_default required')
    if action not in ('inspect','prepare','apply'):raise ValueError('Unsupported action')
    if not isinstance(expected_document_path,str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.lower()!='.sldprt':raise ValueError('Exact absolute SLDPRT required')
    receipt=None
    if action=='apply':
        source=Path(stl_path) if isinstance(stl_path,str) else None
        if source is None or not source.is_absolute() or not source.is_file() or source.suffix.lower()!='.stl':raise ValueError('Existing absolute manufacturing STL required')
        for value in (stl_sha256,expected_state_sha256):
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Exact SHA256 required')
        if _file_hash(source)!=stl_sha256:raise ValueError('Stock STL hash mismatch')
        receipt=Path(receipt_path) if isinstance(receipt_path,str) else None
        if receipt is None or not receipt.is_absolute() or receipt.suffix.lower()!='.json' or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink():raise ValueError('Unique JSON receipt required')
    elif any(x is not None for x in (stl_path,stl_sha256,stock_evidence,expected_state_sha256,receipt_path)):raise ValueError('Read action rejects mutation inputs')
    report=dict(status='started',phase='initial',action=action,mutation_attempted=False,native_call_returned=False,
                readback_verified=False,model_saved=False,AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,
                product_geometry_edit_attempted=False,physical_stock_independently_qualified=False,
                bounding_box_api_units_independently_qualified=False,post_cleanup_CAM_getters=False,may_continue=False)
    if receipt:_write_receipt(receipt,report,create=True)
    session=None
    try:
        session=CamMessageSession(_bootstrap(sw,clsid,typelib_path,expected_document_path),typelib_path)
        def check():
            s=session.summary();report['messages']=s
            if (not s.get('subscribed') or not s.get('active') or s.get('event_count') or s.get('overflow') or s.get('callback_errors') or s.get('callback_error_count') or s.get('subscription_error') or s.get('disconnect_errors')):raise ValueError('Native message/event transport: stop')
        def verify(after):
            actual=after['stock']
            if (actual['type_raw']!=4 or actual.get('length_units_raw')!=0 or actual.get('coordinate_system')!=''
                    or actual.get('stl_sha256')!=stl_sha256 or Path(actual.get('stl_path','')).resolve()!=Path(stl_path).resolve()
                    or any(actual.get('offsets_native',[1]))):raise ValueError('Stock definition/readback differs')
            expected=deepcopy(before);expected['document']['needs_save']=after['document']['needs_save'];expected['stock']=actual
            if expected!=after:raise ValueError('Unrequested CAM definition changes')
        with session:
            check()
            before,native=_snapshot(sw,clsid,typelib_path,expected_document_path,check=check)
            eligible=(not before['document']['needs_save'] and not any(x['feature_count'] for x in before['feature_setups']) and not before['operation_counts'])
            report.update(before=before,state_sha256=_digest(before),apply_eligible=eligible)
            if action=='apply':
                if not eligible:raise ValueError('Clean MILL copy with no features/operations required before stock assignment')
                if report['state_sha256']!=expected_state_sha256:raise ValueError('Prepare fingerprint changed')
                evidence=_evidence(stock_evidence,stl_path,stl_sha256,before['saved_file_sha256']);report['stock_evidence']=evidence
                old=before['stock']
                if old.get('stl_sha256')==stl_sha256 and old.get('length_units_raw')==0 and old.get('coordinate_system')=='':raise ValueError('Stock already assigned; no write')
                check();current,native=_snapshot(sw,clsid,typelib_path,expected_document_path,check=check)
                if current!=before or _file_hash(stl_path)!=stl_sha256 or _evidence(stock_evidence,stl_path,stl_sha256,before['saved_file_sha256'])!=evidence:raise ValueError('Definition/source evidence changed before assignment')
                report.update(phase='native_write',mutation_attempted=True);_write_receipt(receipt,report)
                if document_snapshot(sw)!=before['document'] or _file_hash(expected_document_path)!=before['saved_file_sha256']:raise ValueError('Document/file changed before assignment')
                check();result=_member(native['stock'],'DefineWorkpieceFromSTL2',str(stl_path),0,'',0)
                report.update(native_call_returned=True,native_return_value=result,phase='native_return');_write_receipt(receipt,report);check()
                if result is not True:raise ValueError('Native stock assignment did not return true')
                after,_=_snapshot(sw,clsid,typelib_path,expected_document_path,check=check);verify(after);report['after']=after
                final,_=_snapshot(sw,clsid,typelib_path,expected_document_path,check=check);verify(final);report['final_subscribed']=final;check()
            else:
                report.update(status='ok',phase='prepared' if action=='prepare' else 'inspected')
                final=before
                report['final_subscribed']=final
            check()
        s=session.summary();report['messages']=s
        if (not s.get('disconnected') or s.get('active') or s.get('event_count') or s.get('overflow') or s.get('callback_errors') or s.get('callback_error_count') or s.get('subscription_error') or s.get('disconnect_errors')):raise ValueError('Event cleanup unconfirmed')
        if document_snapshot(sw)!=final['document'] or _file_hash(expected_document_path)!=before['saved_file_sha256'] or (action=='apply' and _file_hash(stl_path)!=stl_sha256):raise ValueError('Document/STL changed during cleanup')
        report.update(status='review_required' if action=='apply' else 'ok',phase='finished',readback_verified=action=='apply',reason='STOCK_DEFINITION_ONLY_SAVE_REOPEN_AND_GEOMETRY_CHECK_REQUIRED')
    except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',issue=_error(exc),failed_phase=report['phase'],phase='finished')
    finally:
        if session is not None:report['messages']=session.summary()
        if receipt:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status='uncertain',readback_verified=False,receipt_write_error=_error(exc))
    return report
