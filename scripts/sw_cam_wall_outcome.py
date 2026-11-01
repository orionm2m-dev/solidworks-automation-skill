"""Inspect one selected GTP outcome, then optionally preserve its current state.

No setters or GTP replay. The save action requires a completed background result
observed by the separate read-only action and repeats that status immediately
before Save. An absent path is saved only as settings, never generated authority.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_pocket_wall_continue as wall
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
common,group=wall.common,wall.group
SCOPE='WALL_GTP_OUTCOME_PRESERVATION_V1'
STATUS_SCOPE='WALL_GTP_OUTCOME_STATUS_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','failed_receipt_path','failed_receipt_sha256','receipt_path','progress_path','module_sha256'}
SAVE_PARAMS=PARAMS|{'status_receipt_path','status_receipt_sha256'}
FLAGS=('setter_attempted','assignment_attempted','GTP_attempted','operation_creation_attempted','automatic_replay','production_qualified','geometry_acceptance_complete')


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action'] in ('inspect_wall_outcome','save_wall_outcome'),'Exact inspect/save outcome action required')
    p=deepcopy(request['params']);save=request['action']=='save_wall_outcome'
    require(type(p) is dict and set(p)==(SAVE_PARAMS if save else PARAMS),'Exact outcome fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact hash required')
    require(p['module_sha256']==_file_hash(__file__),'Outcome module changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM CLSID required')
    return p,save


def validate_failed(r):
    require(r['scope']==wall.SCOPE and r['status']=='uncertain' and r['failed_phase']=='GenerateToolpath' and r['phase']=='finished'
        and r['model_saved'] is False and r['configuration_readback_verified'] is True and r['initial_full_capture_verified'] is True,'Exact configured no-save outcome required')
    require(set(r['actions'])==set(wall.ACTIONS)-{'SaveActiveDocument'} and all(r[k] is False for k in wall.FORBIDDEN),'Unexpected prior action')
    require(r['issue']['type']=='ValueError' and any(x.get('function')=='verify_capture' and x.get('line')==45 for x in r['issue']['locations']),'Exact generated-flag mismatch required')
    for spec in wall.FIELDS:
        a=r['actions']['field:'+spec[0]];wall.history.verified_action(a)
        require(group.exact(a['observed'],spec[6]),'Incomplete recorded lead settings')
    a=r['actions']['GenerateToolpath']
    require(a['attempted'] is True and a['returned'] is True and a['pending'] is False and a['native_return_type']=='int' and type(a['native_return_value']) is int and a['native_return_value']==0 and not a.get('readback_verified'),'Exact unconfirmed GTP return required')
    loaded=r['loaded_context_before'];wall.verify_capture(loaded,r['initial'])
    wall.verify_capture(loaded,r['configured'],configured=True);wall.verify_capture(loaded,r['generated'],configured=True,generated=False)
    clean_events(r);return loaded


def status_contract(value,*,completed=False):
    require(value['operation_native_id']==144 and value['feature_native_id']==79 and value['tool_native_id']==273,'Selected status binding differs')
    for key in ('background_over_before','background_over_after','generated','generated_for_feature'):require(type(value[key]) is bool,'Strict status Boolean required')
    counts=value['record_counts'];require(type(counts) is list and len(counts)<=1 and all(type(n) is int and 0<n<=100000 for n in counts),'Bounded actual path counts required')
    if completed:
        require(value['background_over_before'] is True and value['background_over_after'] is True,'Background GTP has not completed')
        require(value['generated'] is value['generated_for_feature'] and bool(counts) is value['generated'],'Completed flag/feature/stream state inconsistent')
    return value


def load_inputs(p,save):
    failed,pin=read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);loaded=deepcopy(validate_failed(failed))
    require(failed['module_pin']==common._pin(wall.__file__) and failed['process_id']==p['process_id'] and common._key(failed['source_path'])==common._key(p['expected_document_path'])
        and failed['initial_source_sha256']==p['expected_source_sha256']==_file_hash(p['expected_document_path']),'Exact unchanged process/source/writer required')
    common._check(failed['live_pins']);common._check(failed['offline_proof_pins']);common._check(failed['bootstrap_export_pins'])
    loaded.update(pins=common._merge(failed['live_pins'],[common._pin(__file__)]),offline_export_proof_pins=common._merge(failed['offline_proof_pins'],[pin]),parent_pin=pin)
    require(len(loaded['pins'])<=63,'Bounded outcome closure required')
    expected=None
    if save:
        status,statuspin=read_pin(p['status_receipt_path'],p['status_receipt_sha256'])
        require(status['scope']==STATUS_SCOPE and status['status']=='observed' and status['readback_verified'] is True and status['module_pin']==common._pin(__file__)
            and status['process_id']==p['process_id'] and status['source_sha256']==p['expected_source_sha256'] and common._key(status['source_path'])==common._key(p['expected_document_path'])
            and status['failed_pin']==pin and status['save_attempted'] is False and status['phase_proofs_verified'] is True and status['mutation_attempted'] is False and status['actions']=={} and all(status[k] is False for k in FLAGS),'Exact completed read-only status receipt required')
        clean_events(status);expected=deepcopy(status_contract(status['actual_status'],completed=True))
        loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],[statuspin])
    return loaded,failed,pin,expected


class NativeBackend(wall.NativeBackend):
    def set_field(self,*a):raise RuntimeError('Outcome preservation cannot set parameters')
    def assign(self,*a):raise RuntimeError('Outcome preservation cannot assign')
    def generate(self,*a):raise RuntimeError('Outcome preservation cannot replay GTP')
    def outcome(self):
        from comtypes.automation import IDispatch
        from scripts.sw_cam_mill_route_context import read_generic_tool
        with self.ctx.guard() as g:
            before=g.read(self.ctx.app,'IsBackgroundProcessForGTPOver')
            raw,feature=self.target(g,144);op=g.typed(raw,'ICWOperation');dispatch=g.read(feature,'QueryInterface',IDispatch)
            generated=g.read(op,'GetIsToolpathGenerated');byfeature=g.read(op,'GetIsToolpathGeneratedForFeature',dispatch)
            collection=g.read(op,'IGetEnumToolpaths');rows=wall.original.prior._items(collection,g.typed,g.read,1)
            counts=[g.read(g.typed(row,'ICWToolpath'),'RecordCount') for row in rows]
            tool,_=read_generic_tool(raw,self.native['doc'],g.read,g.typed)
            result=dict(operation_native_id=_object_id(self.native['doc'],op,g.read),feature_native_id=_object_id(self.native['doc'],feature,g.read),tool_native_id=tool['native_id'],
                background_over_before=before,background_over_after=g.read(self.ctx.app,'IsBackgroundProcessForGTPOver'),generated=generated,generated_for_feature=byfeature,record_counts=counts)
        return status_contract(result)


def marker_path(p):return common.local_evidence_root()/('wall_outcome_save_'+_digest(dict(source=common._key(p['expected_document_path']),sha=p['expected_source_sha256'],failed=p['failed_receipt_sha256']))+'.json')


class Journal(wall.Journal):
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],initial_source_sha256=r['initial_source_sha256'],failed_pin=r['failed_pin'],actions=deepcopy(r['actions']),status=r['status'],phase=r['phase'],model_saved=r['model_saved'],readback_verified=r['readback_verified'])


def preserve(backend,journal,loaded,expected):
    r=journal.report
    def guard():
        backend.boundary();actual=backend.outcome();r['latest_status']=actual;journal.persist()
        status_contract(actual,completed=True);require(group.exact(actual,expected),'Outcome changed since explicit status read')
    guard();r['before']=backend.capture_full('outcome_before');wall.verify_capture(loaded,r['before'],configured=True,generated=expected['generated']);journal.persist()
    reference=wall.save_projection(r['before']);r['save_stage']={}
    def capture(label):
        if label=='before':guard();return deepcopy(reference)
        r['final']=backend.capture_full('outcome_saved');journal.persist()
        wall.verify_capture(loaded,r['final'],configured=True,generated=expected['generated'],saved_sha=r['saved_source_sha256'])
        return wall.equivalent_projection(reference,wall.save_projection(r['final']))
    def save():
        result=backend.save();journal.returned('SaveActiveDocument',result);return result
    def saved_hash():
        sha=backend.saved_hash(r['save_stage']);require(sha!=r['initial_source_sha256'],'New saved CAM settings bytes required')
        r['saved_source_sha256']=sha;journal.persist();return sha
    wall.run_one_existing_save(r['save_stage'],capture=capture,verify=lambda v:wall.equivalent_projection(reference,v),guard=guard,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;r['generated_record_counts']=deepcopy(expected['record_counts'])
    backend.finish();r.update(status='saved_generated_review_required' if expected['generated'] else 'saved_settings_no_toolpath',phase='finished',model_saved=True,readback_verified=True)


def execute(sw,clsid,typelib,*,loaded,p,failedpin,expected,save):
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p)
    paths=[receipt]+([marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+x+'.json') for x in ('outcome_before','outcome_saved')] if save else [])
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']};protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths),'Evidence aliases input')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh evidence/once marker required')
    r=dict(scope=SCOPE if save else STATUS_SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],initial_source_sha256=p['expected_source_sha256'],module_pin=common._pin(__file__),failed_pin=failedpin,parent_pin=failedpin,loaded_context_before=loaded,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],save_attempted=False,model_saved=False,readback_verified=False,mutation_attempted=False,actions={},**{k:False for k in FLAGS})
    journal=Journal(r,str(receipt),marker);_write_receipt(receipt,r,create=True)
    backend=NativeBackend(loaded,p,sw,clsid,typelib,r,journal.persist)
    try:
        backend.start();r['actual_status']=backend.outcome();journal.persist()
        if save:
            require(group.exact(r['actual_status'],expected),'Outcome changed since status receipt');status_contract(expected,completed=True)
            r['save_attempted']=True;preserve(backend,journal,loaded,expected)
        else:backend.finish();r.update(status='observed',phase='finished',readback_verified=True)
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);clean_events(r);r['phase_proofs_verified']=True
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',phase='finished',readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


def audit_status(typelib,generated):
    from ctypes import POINTER
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class,_INTERFACES
    rows=[]
    for owner,name,ident,args,flags in (('ICWApp4','_get_IsBackgroundProcessForGTPOver',57,(POINTER(VARIANT_BOOL),),(10,)),
        ('ICWOperation','GetIsToolpathGeneratedForFeature',83,(POINTER(IDispatch),POINTER(VARIANT_BOOL)),(1,10))):
        cls=wall.original.prior.pocket._verify_generated_class(_interface_class(owner,str(typelib)),_INTERFACES[owner],generated)
        members=[v for v in cls._methods_ if v.name==name];require(len(members)==1,'Unique status member required')
        wall.original.prior.require_abi(members[0],ident,args,flags);rows.append(dict(interface=owner,member=name,dispid=ident))
    return dict(native_calls=0,members=rows)


def dispatch_request(request,*,validate_only=False):
    p,save=validate_request(request);loaded,failed,pin,expected=load_inputs(p,save)
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb')
    audit=audit_status(tlb,loaded['generated_pin'])
    if validate_only:return dict(status='validated_offline',native_called=False,save_authorized=save,live_pin_count=len(loaded['pins']),audit=audit)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,reg['clsid'],tlb,loaded=loaded,p=p,failedpin=pin,expected=expected,save=save)


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','actual_status','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
