"""Save the existing verified empty ApplyToAll candidate without replay.

Reuses wall readers, journal and one-save helper. Full tool profiles are
inherited from the pinned candidate; fresh reads cover route and parameters.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_wall_apply_all as candidate
from scripts.sw_cam import _error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
common,group,wall=candidate.common,candidate.group,candidate.wall
SCOPE='SAVED_WALL_APPLY_ALL_CONFIGURATION_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','parent_receipt_path','parent_receipt_sha256','receipt_path','progress_path','module_sha256'}
FORBIDDEN=tuple(dict.fromkeys(candidate.FORBIDDEN+('setter_attempted','GTP_attempted')))


def validate_empty(r):
    require(r['scope']==candidate.SCOPE and r['status']=='no_toolpath_no_save' and r['phase']=='finished'
        and r['model_saved'] is False and r['generation_verified'] is False and r['generated_record_counts']==[],
        'Completed empty unsaved candidate required')
    require(all(r[k] is True for k in ('readback_verified','configuration_readback_verified','initial_full_capture_verified','phase_proofs_verified')),
        'Complete candidate readback and proofs required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error'))
        and all(r[k] is False for k in candidate.FORBIDDEN)
        and set(r['actions'])==set(candidate.ACTIONS)-{'SaveActiveDocument'},'Unexpected or uncertain candidate actions')
    for action in r['actions'].values():wall.history.verified_action(action)
    for spec in candidate.FIELDS:
        require(group.exact(r['actions']['field:'+spec[0]]['observed'],spec[6]),'Recorded candidate value differs')
    loaded=deepcopy(r['loaded_context_before']);candidate.saved.parent.qualify_scope(loaded)
    candidate.saved.parent.no_output(r['initial_status']);candidate.saved.parent.no_output(r['generation_status'])
    candidate.verify_capture(loaded,r['initial'])
    candidate.verify_capture(loaded,r['configured'],enabled=True)
    candidate.verify_capture(loaded,r['generated'],enabled=True)
    clean_events(r)
    loaded['state']=deepcopy(r['generated']['state'])
    loaded['authority_kind']='verified_unsaved_wall_apply_all_configuration'
    loaded['current_context_sha256']=_digest(group.current_projection(loaded))
    return loaded


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='save_wall_apply_all_configuration','Exact save-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact save-only fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Owned PID required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Strict digest required')
    require(p['module_sha256']==_file_hash(__file__),'Save-only writer changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM registration required')
    return p


def load_inputs(p):
    r,pin=read_pin(p['parent_receipt_path'],p['parent_receipt_sha256']);loaded=validate_empty(r)
    require(r['module_pin']==common._pin(candidate.__file__) and r['process_id']==p['process_id']
        and common._key(r['source_path'])==common._key(p['expected_document_path'])
        and r['initial_source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path']),
        'Candidate writer, owner or unchanged disk source differs')
    for k in ('live_pins','offline_proof_pins','bootstrap_export_pins'):
        common._check(r[k])
        require(all(common._key(x['path'])!=common._key(p['expected_document_path']) for x in r[k]),
            'Mutable part cannot be an immutable dependency')
    marker=candidate.marker_path(r['source_path'],r['initial_source_sha256'])
    mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(group.exact(mark,candidate.Journal(r,p['parent_receipt_path'],marker).marker_state()),'Terminal candidate marker differs')
    loaded.update(pins=common._merge(r['live_pins'],[common._pin(__file__)]),
        offline_export_proof_pins=common._merge(r['offline_proof_pins'],[pin,markpin]),parent_pin=pin)
    require(len(loaded['pins'])<=63,'Reserve completed checkpoint pin')
    return loaded,pin,markpin


def marker_path(source,sha,parent_sha):
    return common.local_evidence_root()/('wall_apply_all_save_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,parent_sha256=parent_sha))+'.json')


class Journal(candidate.original.prior.tools.Journal):
    def pending(self,label):
        require(label=='SaveActiveDocument','Only SaveActiveDocument is authorized');return super().pending(label)
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],initial_source_sha256=r['initial_source_sha256'],parent_pin=r['parent_pin'],
            actions=deepcopy(r['actions']),status=r['status'],phase=r['phase'],model_saved=r['model_saved'],readback_verified=r['readback_verified'],saved_source_sha256=r.get('saved_source_sha256'))


class NativeBackend(candidate.NativeBackend):
    def set_field(self,*args):raise RuntimeError('Save-only continuation cannot set parameters')
    def assign(self,*args):raise RuntimeError('Save-only continuation cannot assign tools')
    def generate(self,*args):raise RuntimeError('Save-only continuation cannot replay GTP')
    def capture_full(self,*args):raise RuntimeError('Save-only continuation reuses pinned tool catalogue')


def projection(value):return dict(machining=wall.save_projection(value),restrictions=deepcopy(value['restrictions']))
def equivalent(reference,actual):
    require(group.exact(reference['restrictions'],actual['restrictions']),'Save changed lead scope or gouge check')
    return dict(machining=wall.equivalent_projection(reference['machining'],actual['machining']),restrictions=deepcopy(actual['restrictions']))


def preserve(backend,journal,loaded):
    r=journal.report
    def guard():
        backend.boundary();r['latest_status']=backend.outcome();journal.persist()
        candidate.saved.parent.no_output(r['latest_status']);candidate.restrictions(backend.restrictions(),True)
    guard();r['before']=backend.capture_narrow('apply_all_save_before');journal.persist()
    candidate.verify_capture(loaded,r['before'],enabled=True)
    reference=projection(r['before']);r['save_stage']={}
    def capture(label):
        if label=='before':guard();return deepcopy(reference)
        r['final']=backend.capture_narrow('apply_all_save_after');journal.persist()
        candidate.verify_capture(loaded,r['final'],enabled=True,saved_sha=r['saved_source_sha256'])
        return equivalent(reference,projection(r['final']))
    def save():
        value=backend.save();journal.returned('SaveActiveDocument',value);return value
    def saved_hash():
        value=backend.saved_hash(r['save_stage']);require(value!=r['initial_source_sha256'],'Changed saved configuration bytes required')
        r['saved_source_sha256']=value;journal.persist();return value
    wall.run_one_existing_save(r['save_stage'],capture=capture,verify=lambda v:equivalent(reference,v),guard=guard,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
    r.update(status='saved_configuration_no_toolpath',phase='finished',model_saved=True,readback_verified=True,generated_record_counts=[])


def validate_saved(r):
    require(r['scope']==SCOPE and r['status']=='saved_configuration_no_toolpath' and r['phase']=='finished'
        and all(r[k] is True for k in ('model_saved','readback_verified','phase_proofs_verified')),'Completed saved settings-only checkpoint required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')) and set(r['actions'])=={'SaveActiveDocument'}
        and all(r[k] is False for k in FORBIDDEN) and r['generated_record_counts']==[],'Unexpected action, path or uncertainty')
    wall.history.verified_action(r['actions']['SaveActiveDocument'])
    loaded=deepcopy(r['loaded_context_before']);candidate.saved.parent.qualify_scope(loaded)
    candidate.saved.parent.no_output(r['latest_status'])
    candidate.verify_capture(loaded,r['before'],enabled=True)
    candidate.verify_capture(loaded,r['final'],enabled=True,saved_sha=r['saved_source_sha256'])
    equivalent(projection(r['before']),projection(r['final']))
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save stage incomplete')
    t=r['source_transition']
    require(type(t['strict_save_return']) is int and t['strict_save_return']==0 and t['source_before_sha256']==r['initial_source_sha256']
        and t['source_after_sha256']==r['saved_source_sha256'] and r['saved_source_sha256']!=r['initial_source_sha256'],'Strict source transition differs')
    require(r['catalogue_reuse']['fresh_full_profile_reads']==0 and r['catalogue_reuse']['parent_pin']==r['parent_pin']
        and r['catalogue_reuse']['catalogue_sha256']==_digest(loaded['neck_tool_checkpoint']['catalogue']),'Pinned catalogue reuse differs')
    clean_events(r)
    loaded.update(state=deepcopy(r['final']['state']),source_sha256=r['saved_source_sha256'],
        pocket_parameters=candidate.original.projected(r['final']['parameters']),pocket_startpoints=deepcopy(r['final']['startpoints']),
        authority_kind='saved_wall_apply_all_configuration_no_toolpath')
    loaded.pop('generated_pocket_finish',None)
    loaded['wall_apply_all_configuration']=dict(operation_native_id=144,feature_native_id=79,restrictions=deepcopy(r['final']['restrictions']),generated=False,record_counts=[],geometry_acceptance_complete=False)
    loaded['current_context_sha256']=_digest(group.current_projection(loaded));return loaded


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved configuration source, owner or writer changed')
    for k in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[k])
    parent,_=read_pin(r['parent_pin']['path'],r['parent_pin']['sha256']);previous=validate_empty(parent)
    require(group.exact(group.current_projection(previous),group.current_projection(r['loaded_context_before'])),'Save parent differs from terminal empty candidate')
    context=validate_saved(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Completed context digest differs')
    marker=marker_path(r['source_path'],r['initial_source_sha256'],r['parent_pin']['sha256']);mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()),'Saved once-marker differs')
    live=common._merge([x for x in r['live_pins'] if common._key(x['path'])!=common._key(parent['checkpoint_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded saved closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[markpin]),parent_pin=pin,group_marker_pin=markpin)
    return context


def run_backend(backend,journal,loaded):
    r=journal.report
    try:backend.start();preserve(backend,journal,loaded)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded,pin,parentmark=load_inputs(p)
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p['expected_document_path'],p['expected_source_sha256'],pin['sha256'])
    paths=[receipt,marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+x+'.json') for x in ('apply_all_save_before','apply_all_save_after')]
    protected={common._key(x['path']) for x in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']};protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths),'Evidence aliases input')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh evidence and once-marker required')
    reg=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(reg['addin_path']).parent/'camworks.tlb')
    if validate_only:return dict(status='validated_offline',native_called=False,only_action='SaveActiveDocument',live_pin_count=len(loaded['pins']),fresh_full_profile_reads=0)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],module_pin=common._pin(__file__),parent_pin=pin,parent_marker_pin=parentmark,
            loaded_context_before=loaded,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],actions={},mutation_attempted=False,model_saved=False,readback_verified=False,
            catalogue_reuse=dict(parent_pin=pin,catalogue_sha256=_digest(loaded['neck_tool_checkpoint']['catalogue']),fresh_full_profile_reads=0),**{k:False for k in FORBIDDEN})
        journal=Journal(r,receipt,marker);_write_receipt(receipt,r,create=True)
        backend=NativeBackend(loaded,p,sw,reg['clsid'],typelib,r,journal.persist);run_backend(backend,journal,loaded)
        try:
            for k in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[k])
            clean_events(r);r['phase_proofs_verified']=True
            if r['readback_verified'] is True:
                context=validate_saved(r);r['checkpoint_digest']=_digest(group.current_projection(context));journal.persist()
                r['marker_pin']=common._pin(marker);journal.persist();require(r['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
        except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
        journal.persist();return r


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','model_saved','saved_source_sha256','issue','native_called')}))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
