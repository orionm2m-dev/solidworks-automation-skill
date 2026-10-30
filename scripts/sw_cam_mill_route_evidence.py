"""Pinned completed MILL inventory evidence for read-only route observation."""
from copy import deepcopy
from pathlib import Path
from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes,_decode,_sha,_require
from scripts.sw_cam_mill_inventory import _same_inventory
from scripts.sw_cam_mill_inventory_recovery_evidence import load_mill_inventory_recovery_evidence
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_mill_route_context import verify_route_anchor


class MillRouteAnchor:
    def __init__(self,pin,state,recovery):
        self.pin=deepcopy(pin);self.state=deepcopy(state);self.recovery=recovery

    def check_files(self):
        _,actual=_receipt_bytes(self.pin['path'])
        _require(actual==self.pin,'Pinned inventory receipt changed')
        if self.recovery is not None:self.recovery.check_files()

    def verify(self,state):
        self.check_files()
        return verify_route_anchor(state,self.state)

    def read_stock(self,wp,tlb,read,diag):
        if self.recovery is None:
            from scripts.sw_cam_mill_stock import _stock
            return _stock(wp,tlb,read)
        return self.recovery.read_stock(wp,tlb,read,diag)

    def summary(self):
        return dict(kind='completed_mill_inventory_route_anchor',inventory_receipt=deepcopy(self.pin),
            source_sha256=self.state['saved_file_sha256'],feature_count=len(self.state['features']),
            operation_state_may_differ_in_memory=True,saved_source_rebase_allowed=False,
            recovery_evidence=None if self.recovery is None else self.recovery.summary(),
            actual_incoming_WIP_verified=False,production_qualified=False)


def load_mill_route_anchor(path,sha,*,process_id,expected_document_path,expected_source_sha256):
    _sha(sha);_sha(expected_source_sha256)
    raw,pin=_receipt_bytes(path)
    _require(pin['sha256']==sha,'Pinned inventory SHA differs')
    data=_decode(raw)
    _require(data.get('status')=='review_required' and data.get('phase')=='finished',
        'Completed read-only inventory receipt required')
    for key in ('read_only','inventory_read_complete','readback_verified'):
        _require(data.get(key) is True,'Required inventory evidence missing: '+key)
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','model_saved','stock_edit_attempted',
                'material_edit_attempted','TechDB_write_attempted','post_cleanup_CAM_getters'):
        _require(data.get(key) is False,'Unexpected inventory mutation/state: '+key)
    messages=data.get('messages',{})
    _require(messages.get('subscribed') is True and messages.get('disconnected') is True and messages.get('active') is False,
        'Completed event cleanup required')
    _require(not any(messages.get(key) for key in ('event_count','overflow','callback_errors',
        'callback_error_count','subscription_error','disconnect_errors')),'Inventory has CAM event errors')
    before=data.get('before');after=data.get('after')
    _require(type(before) is dict and type(after) is dict and _same_inventory(before,after),
        'Two consistent complete inventory snapshots required')
    _require(data.get('state_sha256')==_digest(before),'Inventory state digest differs')
    _require(before.get('saved_file_sha256')==expected_source_sha256,'Current saved source differs from inventory anchor')
    doc=before['document']
    check_document_target(doc.get('path'),doc.get('title'),expected_path=expected_document_path,required=True)
    _require(doc.get('type')==1 and doc.get('needs_save') is False,'Clean saved part anchor required')
    _require(before.get('operation_count')==0 and not any(before['operation_counts']),
        'Route anchor must precede operation generation')
    rebind=data.get('allow_saved_process_rebind',False)
    _require(type(rebind) is bool,'Strict saved-process rebind flag required')
    if rebind:
        _require(data.get('process_id')==process_id and type(data.get('process_id')) is int
            and data.get('saved_process_rebind_verified') is True,'Verified current-process inventory binding required')
    if rebind:
        _require(type(data.get('recovery_evidence')) is dict, 'Saved-process rebind requires pinned recovery evidence')
    recovery=None
    if 'recovery_evidence' in data:
        _require(data.get('recovery_delta_verified') is True,'Recovery inventory delta was not verified')
        evidence=data['recovery_evidence'];r=evidence['recognition_receipt'];s=evidence['preservation_save_receipt']
        options={'allow_saved_process_rebind':True} if rebind else {}
        recovery=load_mill_inventory_recovery_evidence(r['path'],r['sha256'],s['path'],s['sha256'],
            process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**options)
        _require(evidence==recovery.summary(),'Recovery summary differs from pinned evidence')
        if rebind:recovery.verify_inventory(before,captured_process_id=process_id)
        else:recovery.verify_inventory(before)
    result=MillRouteAnchor(pin,before,recovery);result.check_files()
    return result
