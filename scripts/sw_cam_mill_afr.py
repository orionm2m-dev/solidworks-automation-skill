"""One prepared, receipt-consumed Doc3 AFR dispatch on an empty disposable MILL copy."""
from copy import deepcopy
import hashlib,json,re
from pathlib import Path
from scripts.sw_cam import _member,_error
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap,_snapshot as _mill_snapshot
from scripts.sw_cam_mill_inventory import capture_guarded_mill_inventory,validate_inventory_request,_same_inventory
from scripts.sw_cam_mill_afr_delta import validate_empty_afr_baseline,verify_afr_delta
from scripts.sw_cam_mill_stock_export_evidence import load_stock_export_evidence
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path,check_document_target


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Exact lowercase SHA256 required')


def _prepared(path,sha,expected_state):
    _sha(sha);_sha(expected_state)
    p=Path(path) if type(path) is str else None
    if p is None or not p.is_absolute() or p.suffix.casefold()!='.json' or not p.is_file() or p.is_symlink() or p.stat().st_size>16*1024*1024:
        raise ValueError('Bounded existing immutable prepare receipt required')
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha or _file_hash(p)!=sha:raise ValueError('Prepare receipt SHA changed')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate prepare JSON key')
            result[key]=value
        return result
    data=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite prepare JSON')))
    if (type(data) is not dict or data.get('scope')!='MILL_EMPTY_COPY_AFR_SMOKE_V1' or data.get('action')!='prepare'
        or data.get('status')!='review_required' or data.get('apply_eligible') is not True
        or data.get('mutation_attempted') is not False or data.get('state_sha256')!=expected_state):
        raise ValueError('Exact successful unused AFR prepare required')
    if _digest(dict(request=data['request'],before=data['before']))!=expected_state:raise ValueError('Prepared payload digest mismatch')
    marker=Path(str(p)+'.apply_attempt.json')
    if marker.exists() or marker.is_symlink():raise ValueError('AFR prepare already consumed; no replay')
    return p,marker,data


def validate_afr_request(*,process_id,expected_document_path,expected_source_sha256,
        expected_material_raw,expected_stock_sha256,stock_basis,action,qualification_only,
        acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',
        expected_state_sha256=None,prepare_receipt_path=None,prepare_receipt_sha256=None,
        techdb_source_path=None,techdb_source_sha256=None,
        stock_export_receipt_path=None,stock_export_receipt_sha256=None):
    validate_inventory_request(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,qualification_only=qualification_only,
        acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,message_policy=message_policy)
    if action not in ('prepare','apply'):raise ValueError('Explicit prepare/apply required')
    if type(expected_material_raw) is not str or not expected_material_raw or '304l' not in expected_material_raw.casefold():
        raise ValueError('Exact native 304L material designation required for this BASE qualification')
    _sha(expected_stock_sha256)
    if stock_basis not in ('documented_raw_stock','actual_turning_wip'):raise ValueError('Explicit qualification-stock provenance required')
    if (techdb_source_path is None)!=(techdb_source_sha256 is None):raise ValueError('TechDB source evidence requires paired path/SHA')
    if techdb_source_path is not None:
        _sha(techdb_source_sha256)
        if type(techdb_source_path) is not str or not absolute_document_path(techdb_source_path) or not Path(techdb_source_path).is_file():
            raise ValueError('Caller-known existing TechDB source required; no discovery')
    if (stock_export_receipt_path is None)!=(stock_export_receipt_sha256 is None):raise ValueError('Stock export evidence requires paired path/SHA')
    if stock_export_receipt_path is not None:
        _sha(stock_export_receipt_sha256)
        path=Path(stock_export_receipt_path) if type(stock_export_receipt_path) is str else None
        if path is None or not absolute_document_path(stock_export_receipt_path) or path.suffix.casefold()!='.json' or not path.is_file() or path.is_symlink():
            raise ValueError('Existing absolute stock export JSON receipt required')
        if stock_basis!='documented_raw_stock' or expected_material_raw!='304L':
            raise ValueError('Export evidence gate is only documented raw stock with exact304L')
    credentials=(expected_state_sha256,prepare_receipt_path,prepare_receipt_sha256)
    if action=='prepare':
        if any(x is not None for x in credentials):raise ValueError('Prepare rejects apply credentials')
    else:
        _sha(expected_state_sha256);_sha(prepare_receipt_sha256)
        if type(prepare_receipt_path) is not str or not absolute_document_path(prepare_receipt_path) or Path(prepare_receipt_path).suffix.casefold()!='.json':
            raise ValueError('Absolute prepare JSON receipt required')


def qualify_mill_feature_recognition(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,expected_material_raw,expected_stock_sha256,stock_basis,
        action,qualification_only,acknowledge_disposable_copy,receipt_path,message_policy='vendor_default',
        expected_state_sha256=None,prepare_receipt_path=None,prepare_receipt_sha256=None,
        techdb_source_path=None,techdb_source_sha256=None,
        stock_export_receipt_path=None,stock_export_receipt_sha256=None):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope='MILL_EMPTY_COPY_AFR_SMOKE_V1',status='error',phase='preflight',action=action,
        may_continue=False,apply_eligible=False,mutation_attempted=False,native_call_attempted=False,
        native_call_returned=False,native_dispatch_pending=False,AFR_attempted=False,GOP_attempted=False,
        GTP_attempted=False,model_saved=False,stock_edit_attempted=False,material_edit_attempted=False,
        TechDB_write_attempted=False,TechDB_internal_writes_verified_absent=False,readback_verified=False,
        physical_depth_verified=False,production_qualified=False,actual_incoming_WIP_verified=False,
        post_cleanup_CAM_getters=False,snapshot_diagnostics=[])
    session=receipt=prep=marker=prepared=stock_evidence=None;created=False;baseline=None
    request=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,expected_material_raw=expected_material_raw,
        expected_stock_sha256=expected_stock_sha256,stock_basis=stock_basis,
        techdb_source_path=techdb_source_path,techdb_source_sha256=techdb_source_sha256)
    if stock_export_receipt_path is not None:
        request.update(stock_export_receipt_path=stock_export_receipt_path,stock_export_receipt_sha256=stock_export_receipt_sha256)
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
        s=session.summary();report['messages']=s
        if (s.get('subscribed') is not True or (active and s.get('active') is not True)
            or (not active and (s.get('active') is not False or s.get('disconnected') is not True))
            or any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM event transport requires stop; no replay')
    def techdb_check(phase):
        if techdb_source_path is None:return
        actual=_file_hash(techdb_source_path)
        report.setdefault('caller_identified_techdb_source',{})[phase]=actual
        if actual!=techdb_source_sha256:raise ValueError('Caller-identified TechDB source bytes changed')
    def capture(phase):
        check();report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
        capture_args=dict(process_id=process_id,expected_source_sha256=expected_source_sha256,check=check,diagnostic=diag)
        if stock_evidence is not None:
            stock_evidence.check_files()
            capture_args['stock_reader']=lambda wp,tlb,read:stock_evidence.read_stock(wp,tlb,read,diag)
        state=capture_guarded_mill_inventory(sw,clsid,typelib_path,expected_document_path,**capture_args)
        if stock_evidence is not None:stock_evidence.check_files()
        # Each returned capture closed its ordinary rb file handles before any dispatch.
        reference=deepcopy(baseline)
        if report['native_call_returned']:reference['needs_save']=state['document']['needs_save']
        if state['document']!=reference:raise ValueError('Captured document identity changed')
        if stock_evidence is not None:
            stock_evidence.verify_geometry(state)
            if not report['native_call_returned']:stock_evidence.verify_initial(state)
        return state
    try:
        validation_request=dict(request,stock_export_receipt_path=stock_export_receipt_path,stock_export_receipt_sha256=stock_export_receipt_sha256)
        validate_afr_request(**validation_request,action=action,qualification_only=qualification_only,
            acknowledge_disposable_copy=acknowledge_disposable_copy,receipt_path=receipt_path,message_policy=message_policy,
            expected_state_sha256=expected_state_sha256,prepare_receipt_path=prepare_receipt_path,prepare_receipt_sha256=prepare_receipt_sha256)
        if stock_export_receipt_path is not None:
            stock_evidence=load_stock_export_evidence(stock_export_receipt_path,stock_export_receipt_sha256,
                process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
                expected_material_raw=expected_material_raw,expected_stock_sha256=expected_stock_sha256,stock_basis=stock_basis)
            report.update(stock_export_evidence=stock_evidence.summary(),stock_offsets_verified=False,
                recognition_probe_method='EMF/MfgView',stock_mesh_evidence_checked=True)
        if action=='apply':
            prep,marker,prepared=_prepared(prepare_receipt_path,prepare_receipt_sha256,expected_state_sha256)
            if prepared['request']!=request:raise ValueError('Apply request differs from prepared stock/material/source context')
        receipt=Path(receipt_path);_write_receipt(receipt,report,create=True);created=True
        baseline=identity()
        if baseline['needs_save'] is not False:raise ValueError('Clean saved copy required before AFR')
        techdb_check('before')
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path)
        if identity()!=baseline:raise ValueError('Identity changed acquiring event host')
        session=CamMessageSession(app,typelib_path)
        with session:
            before=capture('initial_capture');report['before']=before
            validate_empty_afr_baseline(before)
            if before['material_raw']!=expected_material_raw or _digest(before['stock'])!=expected_stock_sha256:
                raise ValueError('Pinned initial material or stock differs')
            if action=='apply' and not _same_inventory(prepared['before'],before):raise ValueError('Prepared empty inventory changed')
            report['state_sha256']=_digest(dict(request=request,before=before)) if action=='prepare' else expected_state_sha256
            persist();current=capture('before_native_action')
            if not _same_inventory(before,current):raise ValueError('Empty inventory changed immediately before AFR')
            if action=='prepare':report['apply_eligible']=True
            else:
                header,native=_mill_snapshot(sw,clsid,typelib_path,expected_document_path,check=check,required_machine_type=1)
                if any(header[key]!=before[key] for key in header):raise ValueError('Native document handle context changed')
                if _file_hash(prep)!=prepare_receipt_sha256:raise ValueError('Prepare receipt changed before dispatch')
                techdb_check('before_dispatch');check()
                if stock_evidence is not None:stock_evidence.check_files()
                _write_receipt(marker,dict(status='consumed',scope=report['scope'],prepare_sha256=prepare_receipt_sha256,
                    receipt_path=receipt_path,meaning='durable attempt reservation; not proof of native entry'),create=True)
                report.update(phase='ExtractMachinableFeatures',native_dispatch_pending=True);persist();check()
                if identity()!=baseline:raise ValueError('Document/source changed immediately before AFR dispatch')
                check()
                if stock_evidence is not None:stock_evidence.check_files()
                report.update(mutation_attempted=True,native_call_attempted=True,AFR_attempted=True)
                returned=_member(native['doc'],'ExtractMachinableFeatures')
                report.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(returned).__name__,
                    native_return_value=returned if type(returned) in (int,float,bool,str,type(None)) else None)
                persist();check();techdb_check('after_dispatch')
                if type(returned) is not int or not 1<=returned<=64:raise ValueError('Unexpected or empty native AFR result; no replay')
                after=capture('after_native_action');report['after']=after;persist()
                report['delta']=verify_afr_delta(before,after,returned)
                final=capture('final_subscribed');report['final_subscribed']=final
                if not _same_inventory(after,final):raise ValueError('Recognized inventory changed during final capture')
            check()
        check(active=False);techdb_check('after_cleanup')
        if stock_evidence is not None:stock_evidence.check_files()
        expected_final=report.get('final_subscribed',before)['document']
        if identity()!=expected_final:raise ValueError('Document/source changed during event cleanup')
        report.update(status='review_required',phase='finished',readback_verified=True,
            reason='PREPARED_EMPTY_MILL_AFR_ONLY' if action=='prepare' else 'AFR_DEFINITIONS_READBACK_ONLY_NO_OPERATIONS_OR_PHYSICAL_PROOF')
        if stock_evidence is not None:
            report['reason']='PREPARED_EMPTY_MILL_EMF_MFGVIEW_WITH_STOCK_MESH_EVIDENCE' if action=='prepare' else 'EMF_MFGVIEW_DEFINITIONS_READBACK_OFFSET_UNAVAILABLE_NO_OPERATIONS_OR_PHYSICAL_PROOF'
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],
            phase='finished',issue=_error(exc),apply_eligible=False,readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',receipt_write_error=_error(exc),apply_eligible=False,readback_verified=False)
    return report
