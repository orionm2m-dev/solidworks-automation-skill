"""One receipt-pinned native material setter on an empty disposable MILL copy.

Reuses the typed inventory/guard and existing catalogue mapping validator. Does
not broaden the TURN cutting-condition writer or qualify a cutting recipe.
"""
from copy import deepcopy
import hashlib,json,re
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_cutting_conditions import _material_evidence,_read_bstr
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap,_snapshot as _mill_snapshot
from scripts.sw_cam_mill_inventory import capture_guarded_mill_inventory,validate_inventory_request,_same_inventory
from scripts.sw_cam_mill_material_delta import validate_empty_mill_material_baseline,verify_mill_material_delta,_material as _known_material
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path,check_document_target

SCOPE='MILL_EMPTY_COPY_MATERIAL_V1'


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Exact lowercase SHA256 required')


def validate_mill_material_request(*,process_id,expected_document_path,expected_source_sha256,
        expected_old_material,value_native,material_evidence,action,qualification_only,
        acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',
        expected_state_sha256=None,prepare_receipt_path=None,prepare_receipt_sha256=None):
    validate_inventory_request(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,qualification_only=qualification_only,
        acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,message_policy=message_policy)
    if action not in ('prepare','apply'):raise ValueError('Explicit prepare/apply required')
    _read_bstr(expected_old_material);_read_bstr(value_native)
    _known_material(expected_old_material);_known_material(value_native)
    if type(expected_old_material) is not str or type(value_native) is not str or not value_native.strip() or len(value_native)>512:
        raise ValueError('Exact bounded old/new native material names required')
    if expected_old_material==value_native:raise ValueError('Material already requested; no write')
    if type(material_evidence) is not dict or set(material_evidence)!={'path','sha256'}:raise ValueError('Exact mapping path/SHA required')
    _sha(material_evidence['sha256'])
    path=material_evidence['path']
    if type(path) is not str or not absolute_document_path(path) or Path(path).suffix.casefold()!='.json':
        raise ValueError('Absolute material mapping JSON required')
    credentials=(expected_state_sha256,prepare_receipt_path,prepare_receipt_sha256)
    if action=='prepare':
        if any(x is not None for x in credentials):raise ValueError('Prepare rejects apply credentials')
    else:
        _sha(expected_state_sha256);_sha(prepare_receipt_sha256)
        if type(prepare_receipt_path) is not str or not absolute_document_path(prepare_receipt_path) or Path(prepare_receipt_path).suffix.casefold()!='.json':
            raise ValueError('Absolute prepare JSON receipt required')


def _prepared(path,sha,expected_state):
    # Same bounded immutable receipt/attempt pattern as the separately reviewed AFR wrapper.
    _sha(sha);_sha(expected_state);p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>16*1024*1024:raise ValueError('Bounded immutable prepare required')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha or _file_hash(p)!=sha:raise ValueError('Prepare receipt bytes changed')
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
        raise ValueError('Exact successful unused MILL material prepare required')
    if _digest(dict(request=data['request'],before=data['before']))!=expected_state:raise ValueError('Prepared payload digest mismatch')
    marker=Path(str(p)+'.apply_attempt.json')
    if marker.exists() or marker.is_symlink():raise ValueError('Material prepare already consumed; no replay')
    return p,marker,data


def configure_mill_material(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,expected_old_material,value_native,material_evidence,action,
        qualification_only,acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',
        expected_state_sha256=None,prepare_receipt_path=None,prepare_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status='error',phase='preflight',action=action,may_continue=False,
        apply_eligible=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,
        native_dispatch_pending=False,material_edit_attempted=False,stock_edit_attempted=False,
        AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,TechDB_write_attempted=False,
        model_saved=False,readback_verified=False,production_qualified=False,cutting_recipe_qualified=False,
        stock_grade_delivery_verified=False,physical_depth_verified=False,post_cleanup_CAM_getters=False,
        snapshot_diagnostics=[])
    session=receipt=prep=marker=prepared=baseline=None;created=False
    request=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,expected_old_material=expected_old_material,
        value_native=value_native,material_evidence=deepcopy(material_evidence))
    report['request']=request
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
    def mapping():
        return _material_evidence(material_evidence,value_native,expected_document_path)
    def capture(phase):
        check();report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
        state=capture_guarded_mill_inventory(sw,clsid,typelib_path,expected_document_path,
            process_id=process_id,expected_source_sha256=expected_source_sha256,check=check,diagnostic=diag)
        # Shared source-only read handles have closed when the capture returns.
        reference=deepcopy(baseline)
        if report['native_call_returned']:reference['needs_save']=state['document']['needs_save']
        if state['document']!=reference:raise ValueError('Captured document identity changed')
        return state
    try:
        validate_mill_material_request(**request,action=action,qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,message_policy=message_policy,
            expected_state_sha256=expected_state_sha256,prepare_receipt_path=prepare_receipt_path,prepare_receipt_sha256=prepare_receipt_sha256)
        if action=='apply':
            prep,marker,prepared=_prepared(prepare_receipt_path,prepare_receipt_sha256,expected_state_sha256)
            if prepared['request']!=request:raise ValueError('Apply differs from prepared material/mapping/source context')
        report['material_mapping']=mapping()
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        baseline=identity()
        if baseline['needs_save'] is not False:raise ValueError('Clean saved copy required before material assignment')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            before=capture('initial_capture');report['before']=before
            validate_empty_mill_material_baseline(before)
            if _read_bstr(before['material_raw'])!=expected_old_material:raise ValueError('Expected old native material differs')
            if action=='apply' and not _same_inventory(prepared['before'],before):raise ValueError('Prepared empty inventory changed')
            report['state_sha256']=_digest(dict(request=request,before=before)) if action=='prepare' else expected_state_sha256
            persist();current=capture('before_native_action')
            if not _same_inventory(before,current):raise ValueError('Empty inventory changed immediately before material action')
            if mapping()!=report['material_mapping']:raise ValueError('Material mapping changed')
            if action=='prepare':report['apply_eligible']=True
            else:
                header,native=_mill_snapshot(sw,clsid,typelib_path,expected_document_path,check=check,required_machine_type=1)
                if any(header[key]!=before[key] for key in header):raise ValueError('Native document handle context changed')
                check();workpiece=_typed(_member(native['machine'],'IGetWorkpiece'),'ICWWorkpiece',typelib_path);check()
                if _read_bstr(_member(workpiece,'Material'))!=expected_old_material:raise ValueError('Old material changed before setter')
                check()
                if _file_hash(prep)!=prepare_receipt_sha256 or mapping()!=report['material_mapping']:raise ValueError('Prepared evidence changed before setter')
                _write_receipt(marker,dict(status='consumed',scope=SCOPE,prepare_sha256=prepare_receipt_sha256,
                    receipt_path=receipt_path,meaning='durable attempt reservation; not proof of native entry'),create=True)
                report.update(phase='ICWWorkpiece.Material',native_dispatch_pending=True);persist();check()
                if identity()!=baseline:raise ValueError('Document/source changed immediately before material dispatch')
                check();report.update(mutation_attempted=True,native_call_attempted=True,material_edit_attempted=True)
                setattr(workpiece,'Material',value_native)
                report.update(native_call_returned=True,native_dispatch_pending=False);persist();check()
                after=capture('after_native_action');report['after']=after;persist()
                report['delta']=verify_mill_material_delta(before,after,expected_old_material,value_native)
                final=capture('final_subscribed');report['final_subscribed']=final
                if not _same_inventory(after,final):raise ValueError('Material inventory changed during final capture')
            check()
        check(active=False)
        if mapping()!=report['material_mapping']:raise ValueError('Material mapping changed during cleanup')
        expected_final=report.get('final_subscribed',before)['document']
        if identity()!=expected_final:raise ValueError('Document/source changed during event cleanup')
        report.update(status='review_required',phase='finished',readback_verified=True,
            reason='PREPARED_EMPTY_MILL_MATERIAL_ONLY' if action=='prepare' else 'NATIVE_MATERIAL_NAME_READBACK_ONLY_NOT_CUTTING_RECIPE_OR_DELIVERY_PROOF')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],
            phase='finished',issue=_error(exc),apply_eligible=False,readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',receipt_write_error=_error(exc),apply_eligible=False,readback_verified=False)
    return report
