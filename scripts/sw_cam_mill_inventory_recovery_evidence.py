"""Pure provenance for a fresh read-only inventory after uncertain EMF and save.

The EMF post-state was not verified. Only a new complete inventory can establish
its delta. Q16's original geometry anchor is never replaced by a later snapshot.
No native calls occur when loading, checking files, or verifying supplied states.
"""
from copy import deepcopy
from pathlib import Path
import math
from scripts.sw_cam_mill_stock_export_evidence import (
    _receipt_bytes,_decode,_sha,_require,load_stock_export_evidence)
from scripts.sw_cam_mill_afr_delta import _json,verify_afr_delta
from scripts.sw_cam_lifecycle import _verify_save
from scripts.sw_cam_mill_lifecycle import _zero_operations

_HEADER={'document','saved_file_sha256','current_machine','mill_catalogue','feature_setups',
    'operation_counts','material_raw','extend_holes_to_stock','unit_record_raw','unit_record_status','machine_kind','process_id'}
_MESSAGES=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,
    event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


def _integer(value,label,low=0,high=0xFFFFFFFF):
    _require(type(value) is int and low<=value<=high,'Strict bounded integer required: '+label)
    return value


def _load(path,sha):
    _sha(sha);raw,pin=_receipt_bytes(path)
    _require(pin['sha256']==sha,'Recovery evidence SHA differs')
    return _decode(raw),pin


def _flags(data,true,false):
    _require(all(data.get(k) is True for k in true) and all(data.get(k) is False for k in false),
        'Strict recovery receipt flags differ')
    _require(_json(data.get('messages'))==_json(_MESSAGES),'Clean disconnected CAM events required')


def _header(state,*,process_id,path,source,count):
    _require(type(state) is dict and set(state)==_HEADER,'Exact MILL lifecycle count-snapshot scope required')
    _zero_operations(state)
    _require(state['machine_kind']=='mill_qualification' and _integer(state['process_id'],'snapshot PID',1)==process_id,
        'MILL lifecycle process binding differs')
    doc=state['document']
    _require(type(doc) is dict and set(doc)=={'path','title','type','needs_save'} and
        _integer(doc['type'],'part type',1,1)==1 and doc['path']==path and type(doc['title']) is str,
        'Exact saved part identity required')
    _require(state['saved_file_sha256']==source and state['material_raw']=='304L' and
        _integer(state['current_machine']['machine_type'],'machine type',1,1)==1,'Save source/material/machine differs')
    _require(type(state['extend_holes_to_stock']) is bool,'Strict extend-holes flag required')
    ids=[];total=0
    for row in state['feature_setups']:
        _require(type(row) is dict and set(row)=={'native_id','name','feature_count','axis_native','origin_native','origin_type_raw'},
            'Exact bounded feature setup row required')
        ids.append(_integer(row['native_id'],'setup ID',1));total+=_integer(row['feature_count'],'setup feature count',0,64)
        _integer(row['origin_type_raw'],'setup origin type')
        _require(type(row['name']) is str and len(row['name'])<=1024,'Bounded setup name required')
        for key in ('axis_native','origin_native'):
            value=row[key]
            _require(type(value) is list and len(value)==3 and all(type(n) in (int,float) and math.isfinite(n) for n in value),
                'Finite native setup vector required')
    _require(len(ids)==len(set(ids)) and total==count,'Saved feature IDs/count differ from native EMF return')


class MillInventoryRecoveryEvidence:
    def __init__(self,recognition,rpin,save,spin,stock,*,current_process_id,allow_saved_process_rebind):
        self._recognition=deepcopy(recognition);self._rpin=deepcopy(rpin)
        self._save=deepcopy(save);self._spin=deepcopy(spin);self._stock=stock
        self._before=deepcopy(recognition['before']);self._after_header=deepcopy(save['after'])
        self._count=recognition['native_return_value']
        self._historical_process_id=recognition['request']['process_id']
        self._current_process_id=current_process_id
        self._allow_saved_process_rebind=allow_saved_process_rebind

    def summary(self):
        return dict(kind='uncertain_emf_preservation_save_inventory_recovery',
            recognition_receipt=deepcopy(self._rpin),preservation_save_receipt=deepcopy(self._spin),
            stock_export_evidence=self._stock.summary(),recognition_native_return_count=self._count,
            original_recognition_readback_verified=False,fresh_complete_inventory_required=True,
            old_source_sha256=self._before['saved_file_sha256'],current_source_sha256=self._after_header['saved_file_sha256'],
            preservation_save_readback_verified=True,reopen_persistence_verified=False,
            historical_process_id=self._historical_process_id,current_process_id=self._current_process_id,
            saved_process_rebind_requested=self._allow_saved_process_rebind,
            saved_process_rebind_required=self._current_process_id!=self._historical_process_id,
            saved_process_rebind_verified=False,
            stock_offsets_verified=False,actual_incoming_WIP_verified=False,production_qualified=False)

    def check_files(self):
        for expected in (self._rpin,self._spin):
            _,current=_receipt_bytes(expected['path'])
            _require(_json(current)==_json(expected),'Pinned recovery receipt changed')
        self._stock.check_files()
        return True

    def read_stock(self,wp,tlb,read,diag):
        return self._stock.read_stock(wp,tlb,read,diag)

    def verify_inventory(self,state,*,captured_process_id=None):
        """Verify full captured state; the caller must retain its exact live PID guard.

        Rebinding is limited to an explicit saved-file read. Historical receipts
        are never rewritten and only the saved SHA is normalized for the delta.
        """
        try:
            if self._current_process_id!=self._historical_process_id or captured_process_id is not None:
                _require(type(captured_process_id) is int and captured_process_id==self._current_process_id,
                    'Fresh capture process binding differs')
            _json(state)
            for key,value in self._after_header.items():
                if key not in ('machine_kind','process_id'):
                    _require(_json(state[key])==_json(value),'Fresh inventory differs from preserved save header: '+key)
            self._stock.verify_geometry(state)
            normalized=deepcopy(state)
            normalized['saved_file_sha256']=self._before['saved_file_sha256']
            return verify_afr_delta(self._before,normalized,self._count)
        except (KeyError,TypeError,IndexError) as exc:raise ValueError('Complete fresh recovery inventory required') from exc


def load_mill_inventory_recovery_evidence(recognition_path,recognition_sha,save_path,save_sha,*,
        process_id,expected_document_path,expected_source_sha256,allow_saved_process_rebind=False):
    _integer(process_id,'process ID',1);_sha(expected_source_sha256)
    _require(type(allow_saved_process_rebind) is bool,'Strict saved process rebind boolean required')
    _require(type(expected_document_path) is str and Path(expected_document_path).is_absolute()
        and Path(expected_document_path).suffix.casefold()=='.sldprt','Exact absolute part path required')
    recognition,rpin=_load(recognition_path,recognition_sha);save,spin=_load(save_path,save_sha)
    _require(rpin['canonical_path']!=spin['canonical_path'],'Distinct recognition and preservation save receipts required')
    try:
        _require(all(recognition.get(k)==v for k,v in dict(scope='MILL_EMPTY_COPY_AFR_SMOKE_V1',status='uncertain',
            action='apply',phase='finished',failed_phase='after_native_action',native_return_type='int',
            recognition_probe_method='EMF/MfgView').items()),'Expected uncertain returned EMF receipt required')
        _flags(recognition,('mutation_attempted','native_call_attempted','native_call_returned','AFR_attempted','stock_mesh_evidence_checked'),
            ('may_continue','apply_eligible','native_dispatch_pending','GOP_attempted','GTP_attempted','model_saved',
             'stock_edit_attempted','material_edit_attempted','TechDB_write_attempted','TechDB_internal_writes_verified_absent',
             'readback_verified','physical_depth_verified','production_qualified','actual_incoming_WIP_verified',
             'post_cleanup_CAM_getters','stock_offsets_verified'))
        _require('receipt_write_error' not in recognition,'Recognition receipt persistence failed')
        count=_integer(recognition['native_return_value'],'returned EMF count',1,64)
        request=recognition['request'];before=recognition['before'];old=before['saved_file_sha256'];_sha(old)
        historical_pid=_integer(request['process_id'],'recognition PID',1)
        _require(historical_pid==process_id or allow_saved_process_rebind,
            'Saved process changed; explicit read-only rebind required')
        _require(request['expected_document_path']==expected_document_path
            and request['expected_source_sha256']==old,'Recognition target binding differs')
        stock=load_stock_export_evidence(request['stock_export_receipt_path'],request['stock_export_receipt_sha256'],
            process_id=historical_pid,expected_document_path=expected_document_path,expected_source_sha256=old,
            expected_material_raw=request['expected_material_raw'],expected_stock_sha256=request['expected_stock_sha256'],stock_basis=request['stock_basis'])
        stock.verify_initial(before)
        _require(_json(stock.summary())==_json(recognition['stock_export_evidence']),'Recognition Q16 summary differs from its pinned receipt')
        _require(all(save.get(k)==v for k,v in dict(status='review_required',machine_kind='mill_qualification',action='save',
            phase='finished',native_return_type='int',native_outcome='save_returned_readback_verified',
            snapshot_scope='MILL configuration and bounded feature counts; no complete feature geometry',
            last_CAM_snapshot_scope='inside active event subscription before cleanup',message_policy='vendor_default',
            reason='SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN').items()),'Successful scoped MILL preservation save required')
        _require(_integer(save['process_id'],'save PID',1)==historical_pid,'Save historical PID differs')
        _flags(save,('mutation_attempted','native_call_attempted','native_call_returned','native_save_call_returned','save_readback_verified','saved_file_changed'),
            ('may_continue','native_dispatch_pending','native_close_call_returned','close_verified','persistence_verified',
             'generation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','post_cleanup_CAM_getters'))
        for key in ('native_return_value','native_hresult'):_integer(save[key],key,0,0)
        _require(not any(k in save for k in ('issue','failed_phase','failure_message','receipt_write_error')),'Save contains failure evidence')
        _require(old!=expected_source_sha256,'Recovery requires the explicit old-to-new saved source transition')
        sb=save['before'];sa=save['after']
        _header(sb,process_id=historical_pid,path=expected_document_path,source=old,count=count)
        _header(sa,process_id=historical_pid,path=expected_document_path,source=expected_source_sha256,count=count)
        _require(sb['document']['needs_save'] is True and sa['document']['needs_save'] is False,'Preservation save must clear strict dirty flag')
        _verify_save(sb,sa)
        expected=deepcopy(sb);expected['document']['needs_save']=False;expected['saved_file_sha256']=expected_source_sha256
        _require(_json(expected)==_json(sa),'Save changed fields outside source SHA and dirty flag')
        _require(_json(save['final_state'])==_json(sa),'Save final state differs from its verified after state')
        _require(_json(save['after_cleanup_sw_file'])==_json({k:sa[k] for k in ('document','saved_file_sha256')}),'Save cleanup identity differs')
        for key in _HEADER-{'document','saved_file_sha256','feature_setups','operation_counts','machine_kind','process_id'}:
            _require(_json(sb[key])==_json(before[key]),'Pre-save captured context differs from EMF baseline: '+key)
        doc=deepcopy(before['document']);doc['needs_save']=True
        _require(_json(doc)==_json(sb['document']),'Preservation save document differs from EMF baseline')
    except (KeyError,TypeError,IndexError) as exc:raise ValueError('Incomplete recovery evidence') from exc
    result=MillInventoryRecoveryEvidence(recognition,rpin,save,spin,stock,
        current_process_id=process_id,allow_saved_process_rebind=allow_saved_process_rebind)
    result.check_files();return result
