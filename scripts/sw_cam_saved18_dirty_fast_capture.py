"""Four fixed read-only in-process snapshots for an already qualified owned host.

The surrounding mutation packet owns allowed parameter/source transitions. This
helper observes actual values and never assigns, generates, saves or activates.
"""
from copy import deepcopy
from pathlib import Path
import json,time
from scripts import sw_cam_mill_host_lifecycle as lifecycle
from scripts import sw_cam_mill_packet_projection as projection
from scripts import sw_cam_saved18_restarted_dirty_verify as authority
from scripts.sw_cam import _error
common=lifecycle.common
require=common.require
SCOPE='QUALIFIED_OBSERVED_DIRTY_MILL_FOUR_CONTROL_SNAPSHOTS_V1'
LABELS=('saved_existing_before_optimization','configured_optimization','generated_four','saved_generated_four')
AUTHORITY_SHA256='ab4f20647188adde419f25189a8c265e12d77251ee7ce309a76d25115cf2b1e4'

class HostCall:
    def __init__(self,backend):self.backend=backend
    def application(self):return self.backend.sw
    def read(self,artifact,request):
        return lifecycle.NativeBackend._read(self,artifact,mill=True,text=json.dumps(request,ensure_ascii=False,allow_nan=False))

def prepare_capture(loaded):
    """Pure/native-free capability after trusted completed-rebind loading."""
    require(common.digest(authority.__file__)==AUTHORITY_SHA256,'Frozen qualified-reopen loader required')
    require('reopened_checkpoint_pin'in loaded and 'host_reference'in loaded and 'host_artifact'in loaded,'Actual qualified new-owned host required')
    pin=deepcopy(loaded['reopened_checkpoint_pin']);r=authority.checkpoint.authority.read(pin['path'],pin['sha256'])
    require(r['scope']==authority.SCOPE and r['status']=='saved_eighteen_observed_dirty_verified'and r['phase']=='finished'and r['readback_verified']is True and r['persistence_after_reopen_verified']is True and r['loaded_mvid_verified']is True and r['host_native_compatibility_qualified']is True,'Successful host/reopen receipt required')
    require(r['ownership']==loaded['ownership']and r['module_pin']==lifecycle.pin(authority.__file__),'Qualified process/producer differs')
    ref=deepcopy(loaded['host_reference']);artifact=deepcopy(loaded['host_artifact']);request=ref['mill_request']
    require(r['identity']['loaded_artifact']=='new'and r['identity']['module_version_id']==artifact['mvid']and common.key(r['identity']['assembly_location'])==common.key(artifact['dll']['path']),'Actual loaded host identity differs')
    require(projection.reader.group.exact(request,r['host_response']['validated_request'])and projection.reader.group.exact(ref['expected_snapshot'],r['projection']['snapshot']),'Host request/snapshot must come from the actual qualified receipt')
    require(ref['ownership']==loaded['ownership']and ref['counts']==dict(operations=21,parameters=12,features=6,paths=18),'Fixed current21/12/6 authority required')
    require(len(request['expected_operation_ids'])==21 and len(request['parameter_targets'])==12 and len(request['feature_ids'])==6,'Fixed host request bounds required')
    pins=lifecycle.merge_pins(loaded['pins'],[pin,lifecycle.pin(__file__),lifecycle.pin(authority.__file__),lifecycle.pin(lifecycle.__file__),lifecycle.pin(projection.__file__),lifecycle.pin(common.__file__),artifact['dll'],artifact['tlb']],artifact['dependencies'])
    require(len(pins)<=96,'Bounded complete host-call code/artifact closure required')
    common.check_files(pins)
    return dict(scope=SCOPE,request=request,artifact=artifact,ownership=deepcopy(loaded['ownership']),pins=pins,reopen_pin=pin,cam_typelib_pin=deepcopy(ref['cam_typelib_pin']))

def capture_snapshot(backend,label,capability,*,host_call=None):
    """Return actual full21/12; the surrounding packet validates allowed deltas."""
    require(capability['scope']==SCOPE and label in LABELS,'One of four explicit control snapshots required')
    attempts=backend.report.setdefault('fast_captures',[])
    require(len(attempts)<4 and all(v['status']=='observed'for v in attempts)and label==LABELS[len(attempts)],'Control snapshots must execute once in fixed order')
    expected=deepcopy(backend.ctx.expected_document);source=backend.ctx.args['expected_source_sha256'];request=capability['request']
    require(type(expected['needs_save'])is bool and backend.args['process_id']==capability['ownership']['process_id']==request['expected_process_id'],'Expected dirty flag and qualified PID required')
    require(common.key(expected['path'])==common.key(request['expected_document_path'])and common.key(backend.typelib_path)==common.key(capability['cam_typelib_pin']['path']),'Exact current document and CAM typelib required')
    row=dict(scope=SCOPE,label=label,status='prepared',native_call_attempted=False,native_call_returned=False,readback_verified=False,source_sha256=source,expected_document=expected,reopen_pin=deepcopy(capability['reopen_pin']),mutation_attempted=False)
    attempts.append(row);backend.persist()
    def boundary():
        backend.boundary();common.check_files(capability['pins'])
        require(backend.ctx.expected_document==expected and backend.ctx.args['expected_source_sha256']==source and backend.ctx.identity()==expected,'Source/document transition during a single snapshot')
    try:
        boundary()
        with backend.ctx.guard()as guard:
            backend.doc=guard.typed(guard.read(backend.ctx.app,'IGetActiveDoc'),'ICWDoc3')
            backend.save_app=guard.typed(backend.ctx.app,'ICWApp')
        backend.verify_catalogue(label+'_before_fast')
        row.update(status='pending',native_call_attempted=True);backend.persist();started=time.perf_counter()
        raw=(host_call or HostCall(backend)).read(capability['artifact'],request)
        row.update(native_call_returned=True,host_call_seconds=time.perf_counter()-started,raw_host_response=raw);backend.persist()
        packet=common.decode(raw);row['host_response']=packet;backend.persist()
        require(packet.get('host_module_version_id')==capability['artifact']['mvid']and common.key(packet.get('host_assembly_location',''))==common.key(capability['artifact']['dll']['path']),'Qualified loaded host changed')
        checked=projection.project_packet(packet,request);row['projection']=checked;backend.persist()
        doc=packet['document_before'];require(doc['needs_save']is expected['needs_save']and doc['type']==expected['type']and doc['title']==expected['title']and common.key(doc['path'])==common.key(expected['path']),'Observed native document/dirty differs')
        backend.verify_catalogue(label+'_after_fast')
        boundary();row.update(status='observed',readback_verified=True)
        capture=dict(label=label,binding=deepcopy(checked['snapshot']['binding']),parameters=deepcopy(checked['snapshot']['parameters']),capture_mode='qualified_inprocess',fast_capture_index=len(attempts)-1)
        backend.report.setdefault('captures',[]).append(capture);backend.persist()
        return deepcopy(checked['snapshot'])
    except Exception as exc:
        row.update(status='error',issue=_error(exc),readback_verified=False);backend.persist();raise
