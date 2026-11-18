"""Selected saved Rough/Finish pair generation through the existing sealed endpoint."""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_saved_generation as legacy
from scripts import sw_cam_saved_floor_wall_generation_continuation_authority as authority
from scripts import sw_cam_saved_floor_wall_generation_delta as delta
from scripts import sw_cam_saved_floor_wall_generation_flow as flow
from scripts import sw_cam_saved_floor_wall_generation_context as native
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam import _error
require=delta.require;SCOPE=flow.SCOPE;ACK=legacy.ACK;PARAMS=legacy.PARAMS


def prepare_request(request):
    require(type(request)is dict and set(request)=={'action','params'}and request['action']=='generate_configured_local_group','Existing sealed packet action required')
    v=deepcopy(request['params']);require(type(v)is dict and set(v)==PARAMS,'Exact selected pair packet fields required')
    require(v['generation_mode']=='saved_mill_pair'and v['acknowledgement']==ACK,'Explicit mixed generation/Save/CL acknowledgement required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact process lifetime required')
    for name in('expected_source_sha256','configuration_receipt_sha256','module_sha256'):
        require(type(v[name])is str and re.fullmatch('[0-9a-f]{64}',v[name]),'Exact SHA required: '+name)
    source=Path(v['expected_document_path']);require(source.is_absolute()and source.is_file()and not source.is_symlink()and source.suffix.lower()=='.sldprt'and _file_hash(source)==v['expected_source_sha256'],'Exact current saved part required')
    require(v['module_sha256']==_file_hash(__file__),'Installed pair-generation module differs')
    loaded=authority.load_completed(v['configuration_receipt_path'],v['configuration_receipt_sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=str(source),source_sha256=v['expected_source_sha256'],selected_ids=v['selected_operation_native_ids'])
    for module in(__file__,authority.__file__,delta.__file__,flow.__file__,native.__file__,legacy.__file__):loaded['pins'].append(dict(path=module,sha256=_file_hash(module)))
    loaded['context_data']['pins']=deepcopy(loaded['pins'])
    return v,loaded,_fresh_outputs(v,loaded)


def _fresh_outputs(v,loaded):
    source=Path(v['expected_document_path'])
    from scripts.sw_cam_deep_guide_cl import _fresh_path
    before=_fresh_path(v['before_cl_path']);after=_fresh_path(v['saved_cl_path']);directory=Path(v['attempt_registry_path'])
    require(directory.is_absolute()and directory.is_dir()and not directory.is_symlink(),'Existing absolute attempt registry required')
    marker=directory/('saved_pair_gtp_'+_digest(dict(scope=SCOPE,source=str(source.resolve()).casefold(),source_sha256=v['expected_source_sha256'],selected_ids=v['selected_operation_native_ids']))+'.json')
    require(not marker.exists()and not marker.is_symlink(),'Prior selected attempt exists; no replay')
    outputs=[Path(v[k])for k in('receipt_path','progress_path')]
    for p in outputs:require(p.is_absolute()and p.suffix.lower()=='.json'and p.parent.is_dir()and not p.exists()and not p.is_symlink(),'Fresh absolute JSON output required')
    protected={source.resolve(),*(Path(p['path']).resolve()for p in loaded['pins'])}
    all_outputs=outputs+[marker,before,after]
    require(len({p.resolve()for p in all_outputs})==len(all_outputs)and not protected.intersection(p.resolve()for p in all_outputs),'Output aliases source/evidence/another output')
    require(before.parent.resolve()!=after.parent.resolve(),'Distinct fresh pre/post CL directories required')
    return marker

_PREPARED_ISSUER=object()


def _observed_file_pin(pin):
    """Hash bytes plus stable identity without reparsing JSON or CL."""
    from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes
    from scripts.sw_cam_stock_mesh_compare import _signature
    p=Path(pin['path']);require(p.is_absolute()and p.is_file()and not p.is_symlink(),'Direct regular prepared evidence required')
    if p.suffix.lower()=='.json':
        _,observed=_receipt_bytes(str(p))
    else:
        canonical=p.resolve(strict=True);before=list(_signature(p.stat()));sha=_file_hash(p)
        require(not p.is_symlink()and p.resolve(strict=True)==canonical and list(_signature(p.stat()))==before,'Prepared evidence changed while hashing')
        observed=dict(path=str(p),canonical_path=str(canonical),bytes=before[2],sha256=sha,identity=before)
    require(all(key in observed and observed[key]==value for key,value in pin.items()),'Prepared evidence hash or metadata changed')
    return observed


class _PreparedInvocation:
    __slots__=('_v','_loaded','_marker','_request_sha','_content_sha','_pins','_used','_issuer')
    def __init__(self,issuer,request,v,loaded,marker,pins):
        require(issuer is _PREPARED_ISSUER,'Private prepared invocation required')
        self._issuer=issuer;self._v=deepcopy(v);self._loaded=deepcopy(loaded);self._marker=marker
        self._request_sha=_digest(request);self._pins=deepcopy(pins);self._used=False
        self._content_sha=self._fingerprint()
    def _fingerprint(self):
        return _digest(dict(v=self._v,loaded=self._loaded,marker=str(self._marker),pins=self._pins,request_sha=self._request_sha))
    @property
    def addin_clsid(self):return self._loaded['addin_clsid']


def _prepare_invocation(request,*,runtime_check):
    """One invocation-local authority parse; no reusable or caller-provided cache."""
    require(callable(runtime_check),'Runtime guard required');runtime_check()
    v,loaded,marker=prepare_request(request)
    pins={}
    for pin in loaded['pins']+[dict(path=v['expected_document_path'],sha256=v['expected_source_sha256'])]:
        observed=_observed_file_pin(pin);key=str(Path(observed['path']).resolve()).casefold()
        require(key not in pins or pins[key]['sha256']==observed['sha256'],'Conflicting prepared evidence pins');pins[key]=observed
    require(_fresh_outputs(v,loaded)==marker,'Prepared marker changed');runtime_check()
    return _PreparedInvocation(_PREPARED_ISSUER,request,v,loaded,marker,list(pins.values()))


def _consume_prepared(prepared,request,*,runtime_check):
    require(callable(runtime_check),'Runtime guard required')
    require(type(prepared)is _PreparedInvocation and prepared._issuer is _PREPARED_ISSUER and prepared._used is False,'Unused private prepared invocation required')
    prepared._used=True
    require(_digest(request)==prepared._request_sha and prepared._fingerprint()==prepared._content_sha,'Prepared request or authority bundle changed')
    runtime_check()
    for pin in prepared._pins:_observed_file_pin(pin)
    require(_fresh_outputs(prepared._v,prepared._loaded)==prepared._marker,'Prepared marker changed');runtime_check()
    return prepared._v,prepared._loaded,prepared._marker



class Journal(legacy.Journal):
    def marker_state(self):
        return dict(scope=SCOPE,receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),configuration_receipt_pin=deepcopy(self.report['configuration_receipt_pin']),selected_operation_native_ids=list(self.report['selected_operation_native_ids']),status=self.report['status'],phase=self.report['phase'],automatic_replay=False)


def dispatch_current_saved(sw,clsid,tlb,request,*,runtime_check,_backend_factory=None):
    prepared=_prepare_invocation(request,runtime_check=runtime_check)
    return _dispatch_prepared(sw,clsid,tlb,request,prepared,runtime_check=runtime_check,_backend_factory=_backend_factory)


def _dispatch_prepared(sw,clsid,tlb,request,prepared,*,runtime_check,_backend_factory=None):
    v,loaded,marker=_consume_prepared(prepared,request,runtime_check=runtime_check)
    require(loaded['addin_clsid'].casefold()==clsid.casefold(),'Exact producer CAM add-in required')
    legacy.preflight(tlb);authority.config.reader.preflight(tlb)
    r=dict(scope=SCOPE,receipt_path=v['receipt_path'],dispatch_marker_path=str(marker),request=deepcopy(request),request_sha256=_digest(request),runtime_unchanged=False,configuration_receipt_pin=loaded['pin'],evidence_pins=deepcopy(loaded['pins']),selected_operation_native_ids=loaded['selected_ids'],target_observations={},draft_observations={},native_read_count=0)
    class ProgressJournal(Journal):
        progress_created=False
        def persist(self):
            super().persist()
            if self.created:
                _write_receipt(Path(v['progress_path']),dict(scope=SCOPE,status=self.report.get('status'),phase=self.report.get('phase'),receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),native_dispatch_pending=self.report.get('native_dispatch_pending',False)),create=not self.progress_created);self.progress_created=True
    journal=ProgressJournal(v['receipt_path'],marker,r);factory=_backend_factory or native.Context
    backend=factory(sw,clsid,tlb,v,loaded,r,journal.persist,runtime_check);runtime_check();result=flow.run_once(backend,journal,loaded)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result


def revoke_runtime(report,error):
    """保留已返回 native evidence，撤销最终成功；只重写本次创建的回执。"""
    report.update(status='uncertain'if report.get('mutation_attempted')or report.get('CL_export_attempted')else'error',runtime_unchanged=False,readback_verified=False,model_saved=False,save_readback_verified=False,source_update_verified=False,runtime_error=_error(error),reason='RUNTIME_CHANGED_AFTER_CALL')
    try:
        path=Path(report['receipt_path'])
        if report.get('receipt_created') is True:
            import json
            current=json.loads(path.read_text(encoding='utf-8'))
            require(current.get('scope')==SCOPE and current.get('request_sha256')==report.get('request_sha256') and current.get('dispatch_marker_path')==report.get('dispatch_marker_path'),'Only invocation-owned generation receipt may be rewritten')
            _write_receipt(path,report)
            if report.get('marker_created') is True:
                marker=Path(report['dispatch_marker_path']);prior=json.loads(marker.read_text(encoding='utf-8'))
                require(prior.get('scope')==SCOPE and Path(prior.get('receipt_path','')).resolve()==path.resolve(),'Only invocation-owned marker may be updated')
                prior.update(status=report['status'],receipt_sha256=_file_hash(path));_write_receipt(marker,prior)
    except Exception as exc:report['runtime_receipt_update_error']=_error(exc)
    return report
