"""Save a reconciled wall configuration without claiming a generated path.

Only the existing CAM SaveActiveDocument is dispatched. Tool assignment,
parameter writes, generation, document closing and global CAM commands are absent.
"""
from copy import deepcopy
from pathlib import Path
import json, re
from scripts import sw_cam_wall_perimeter_first as parent
from scripts import sw_cam_wall_outcome as outcome
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error
common, group, wall = parent.common, parent.group, parent.wall
SCOPE='SAVED_WALL_CONFIGURATION_ONLY_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','parent_receipt_path','parent_receipt_sha256','receipt_path','progress_path','module_sha256'}


def validate_parent(r):
    require(r['scope']==parent.SCOPE and r['status']=='uncertain' and r['failed_phase']=='GenerateToolpath'
        and r['phase']=='finished' and r['model_saved'] is False and r['configuration_readback_verified'] is True
        and r['initial_full_capture_verified'] is True,'Exact configured empty-path attempt required')
    require(set(r['actions'])=={'field:perimeter_first','GenerateToolpath'} and all(r[k] is False for k in parent.FORBIDDEN),'Unexpected prior action')
    a=r['actions']['field:perimeter_first'];wall.history.verified_action(a)
    require(type(a['observed']) is int and a['observed']==2,'Actual First profile pass required')
    a=r['actions']['GenerateToolpath']
    require(a['attempted'] is True and a['returned'] is True and a['pending'] is False and a['native_return_type']=='int'
        and type(a['native_return_value']) is int and a['native_return_value']==0 and not a.get('readback_verified'),'Exact returned empty GTP required')
    parent.no_output(r['generation_status']);clean_events(r)
    loaded=deepcopy(r['loaded_context_before']);parent.qualify_scope(loaded)
    parent.verify_capture(loaded,r['initial']);parent.verify_capture(loaded,r['configured'],corrected=True)
    return loaded


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='save_wall_configuration_only','Exact save-only request required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact save-only fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Owned PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Strict hash required')
    require(p['module_sha256']==_file_hash(__file__),'Save-only module changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM CLSID required')
    return p


def load_inputs(p):
    r,pin=read_pin(p['parent_receipt_path'],p['parent_receipt_sha256']);loaded=validate_parent(r)
    require(r['module_pin']==common._pin(parent.__file__) and r['process_id']==p['process_id']
        and common._key(r['source_path'])==common._key(p['expected_document_path'])
        and r['initial_source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path']),'Exact current source/owner/writer required')
    for key in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[key])
    loaded.update(pins=common._merge(r['live_pins'],[common._pin(__file__)]),
        offline_export_proof_pins=common._merge(r['offline_proof_pins'],[pin]),parent_pin=pin)
    require(len(loaded['pins'])<=63,'Bounded save-only closure required')
    return loaded,pin


class Journal(parent.Journal):
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],initial_source_sha256=r['initial_source_sha256'],parent_pin=r['parent_pin'],
            actions=deepcopy(r['actions']),status=r['status'],phase=r['phase'],model_saved=r['model_saved'],readback_verified=r['readback_verified'])


def preserve(backend,journal,loaded):
    r=journal.report
    def guard():
        backend.boundary();actual=backend.outcome();r['latest_status']=actual;journal.persist();parent.no_output(actual)
    guard();r['before']=backend.capture_full('settings_before');journal.persist()
    parent.verify_capture(loaded,r['before'],corrected=True,generated=False)
    expected=wall.save_projection(r['before']);r['save_stage']={}
    def capture(label):
        if label=='before':guard();return deepcopy(expected)
        r['final']=backend.capture_full('settings_saved');journal.persist()
        parent.verify_capture(loaded,r['final'],corrected=True,generated=False,saved_sha=r['saved_source_sha256'])
        return wall.equivalent_projection(expected,wall.save_projection(r['final']))
    def save():
        result=backend.save();journal.returned('SaveActiveDocument',result);return result
    def saved_hash():
        sha=backend.saved_hash(r['save_stage']);require(sha!=r['initial_source_sha256'],'Changed configuration bytes required')
        r['saved_source_sha256']=sha;journal.persist();return sha
    wall.run_one_existing_save(r['save_stage'],capture=capture,verify=lambda v:wall.equivalent_projection(expected,v),guard=guard,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
    r.update(status='saved_configuration_no_toolpath',phase='finished',readback_verified=True,model_saved=True,generated_record_counts=[])


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded,pin=load_inputs(p)
    receipt=common._local_receipt(p['receipt_path'])
    marker=common.local_evidence_root()/('wall_settings_save_'+_digest(dict(source=common._key(p['expected_document_path']),source_sha=p['expected_source_sha256'],parent_sha=pin['sha256']))+'.json')
    paths=[receipt,marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+x+'.json') for x in ('settings_before','settings_saved')]
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']};protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths),'Evidence aliases input')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh evidence/once marker required')
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb')
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),only_action='SaveActiveDocument')
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],module_pin=common._pin(__file__),parent_pin=pin,
            loaded_context_before=loaded,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],actions={},mutation_attempted=False,model_saved=False,readback_verified=False,
            setter_attempted=False,assignment_attempted=False,GTP_attempted=False,automatic_replay=False,geometry_acceptance_complete=False,production_qualified=False)
        journal=Journal(r,str(receipt),marker);_write_receipt(receipt,r,create=True)
        backend=outcome.NativeBackend(loaded,p,sw,reg['clsid'],tlb,r,journal.persist)
        try:
            backend.start();preserve(backend,journal,loaded)
            for key in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[key])
            clean_events(r);r['phase_proofs_verified']=True
        except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
        finally:
            try:backend.close()
            except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
            journal.persist()
        return r


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','model_saved','saved_source_sha256','issue','native_called')},ensure_ascii=False))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1

if __name__=='__main__':raise SystemExit(main())