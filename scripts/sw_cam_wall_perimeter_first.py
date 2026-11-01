"""Apply one documented wall-profile correction, then one selected GTP.

Only PerimeterPassType 1 -> 2 is writable. Every other parameter, the assigned
qualified tool and five prior paths are preserved. The owned, returned 2.5D call is bound by explicit evidence. The global
Process Manager flag is retained as telemetry, not a universal idle signal.
"""
from copy import deepcopy
from pathlib import Path
import re,json
from scripts import sw_cam_wall_outcome as outcome
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam import _error
from scripts.sw_cam_rough_firstcut import require
wall=outcome.wall
original,common,group=wall.original,wall.common,wall.group
SCOPE='SAVED_WALL_PERIMETER_FIRST_V1'
SPEC=('perimeter_first','ICWFinishMillOp','PerimeterPassType','PerimeterPassType','property',1,2)
PARAMS=outcome.SAVE_PARAMS|{'diagnosis_path','diagnosis_sha256','execution_contract_path','execution_contract_sha256'}
ACTIONS=('field:perimeter_first','GenerateToolpath','SaveActiveDocument')
FORBIDDEN=wall.FORBIDDEN+('automatic_replay',)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='apply_wall_perimeter_first','Exact perimeter-first action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact correction request fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact hash required')
    require(p['module_sha256']==_file_hash(__file__),'Correction module changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM CLSID required')
    return p


def status_25d(value):
    outcome.status_contract(value)
    require(value['background_over_before'] is value['background_over_after'],'Global background telemetry changed during observation')
    require(value['generated'] is value['generated_for_feature'] and bool(value['record_counts']) is value['generated'],'Selected flag/feature/stream state inconsistent')
    return value


def qualify_scope(loaded):
    state=loaded['state'];op=state['operations'][-1];profile=state['selected_profile_headers']
    require(state['current_machine']['machine_type']==1 and op['native_id']==144 and op['mill_operation_type']==1
        and op['base_operation_type']==0 and op['setup_native_id']==93 and op['linked_feature_ids']==[79]
        and profile['native_id']==79 and profile['representation']=='ICWProfileFeature metadata',
        'Only the returned owned 2.5D profile FinishMill scope is qualified')


def no_output(value):
    status_25d(value)
    require(value['generated'] is False and value['generated_for_feature'] is False and value['record_counts']==[],'Existing path forbids a new selected GTP')
    return value


def load_inputs(p):
    base={k:v for k,v in p.items() if k in outcome.PARAMS};base['module_sha256']=_file_hash(outcome.__file__)
    loaded,failed,failedpin,_=outcome.load_inputs(base,False)
    status,statuspin=read_pin(p['status_receipt_path'],p['status_receipt_sha256'])
    require(status['scope']==outcome.STATUS_SCOPE and status['status']=='observed' and status['readback_verified'] is True
        and status['module_pin']==common._pin(outcome.__file__) and status['process_id']==p['process_id']
        and status['source_sha256']==p['expected_source_sha256'] and common._key(status['source_path'])==common._key(p['expected_document_path'])
        and status['failed_pin']==failedpin and status['actions']=={} and status['save_attempted'] is False and status['mutation_attempted'] is False
        and status['phase_proofs_verified'] is True and all(status[k] is False for k in outcome.FLAGS),'Exact read-only status authority required')
    clean_events(status);status_25d(status['actual_status']);qualify_scope(loaded)
    contract,contractpin=read_pin(p['execution_contract_path'],p['execution_contract_sha256'])
    require(contract['scope']=='OWNED_RETURNED_2_5D_FINISH_V1' and contract['process_id']==p['process_id']
        and contract['failed_receipt_sha256']==failedpin['sha256'] and contract['status_receipt_sha256']==statuspin['sha256']
        and contract['operation_native_id']==144 and contract['global_background_flag_is_idle_proof'] is False
        and contract['new_generation_is_single_changed_recipe'] is True,'Exact bounded execution evidence required')
    diagnosis,diagnosispin=read_pin(p['diagnosis_path'],p['diagnosis_sha256']);delta=diagnosis['recommended_single_delta']
    require(diagnosis['native_calls']==0 and diagnosis['offline_only'] is True and diagnosis['actual_receipt_pin']['sha256']==failedpin['sha256']
        and delta['interface']=='ICWFinishMillOp' and delta['iid']=='{4EDDCA7E-325A-11D6-A9A7-00062999E55F}'
        and delta['member']=='PerimeterPassType' and delta['dispid']==23 and delta['expected_before']==1 and delta['target']==2
        and delta['constant']=='CW_PROFILE_PASS_FIRST' and delta['hypothesis_confirmed'] is False,'Exact one-factor diagnosis required')
    primary=[{'path':x['path'],'sha256':x['sha256']} for x in diagnosis['primary_sources']];common._check(primary)
    loaded.update(pins=common._merge(loaded['pins'],[common._pin(__file__)]),
        offline_export_proof_pins=common._merge(loaded['offline_export_proof_pins'],[statuspin,diagnosispin,contractpin],primary),parent_pin=statuspin)
    require(len(loaded['pins'])<=63,'Bounded correction closure required')
    return loaded,failedpin,statuspin,diagnosispin,status['actual_status']


def verify_capture(loaded,value,*,corrected=False,generated=False,saved_sha=None):
    baseline=deepcopy(loaded)
    if corrected:
        parameters=original.projected(baseline['pocket_parameters'])
        require(parameters['144']['finish']['PerimeterPassType']==1,'Expected original None profile pass')
        parameters['144']['finish']['PerimeterPassType']=2;baseline['pocket_parameters']=parameters
    return wall.verify_capture(baseline,value,configured=True,generated=generated,saved_sha=saved_sha)


class NativeBackend(outcome.NativeBackend):
    def set_field(self,spec,pending):
        require(spec==SPEC,'Only documented PerimeterPassType1 to2 is writable')
        return original.NativeBackend.set_field(self,spec,pending)
    def generate(self,pending):return original.NativeBackend.generate(self,pending)


def marker_path(source,sha):
    return common.local_evidence_root()/('wall_perimeter_first_'+_digest(dict(scope=SCOPE,source=common._key(source),sha=sha,operation=144))+'.json')


class Journal(original.prior.tools.Journal):
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,source_path=r['source_path'],initial_source_sha256=r['initial_source_sha256'],
            failed_pin=r['failed_pin'],status_pin=r['status_pin'],diagnosis_pin=r['diagnosis_pin'],actions=deepcopy(r['actions']),
            status=r['status'],phase=r['phase'],model_saved=r['model_saved'],readback_verified=r['readback_verified'])


def audit(typelib,generated):
    from ctypes import POINTER,c_int
    cls=original.interface_class('ICWFinishMillOp',typelib,generated);rows=[]
    for name,args,flags in (('_get_PerimeterPassType',(POINTER(c_int),),(10,)),('_set_PerimeterPassType',(c_int,),(1,))):
        members=[x for x in cls._methods_ if x.name==name];require(len(members)==1,'Unique perimeter property required')
        original.prior.require_abi(members[0],23,args,flags);rows.append(name)
    require(hasattr(POINTER(cls),'_ICWFinishMillOp__com__set_PerimeterPassType'),'Raw HRESULT property setter required')
    return dict(native_calls=0,interface='ICWFinishMillOp',iid=str(cls._iid_),dispid=23,members=rows)


def configure(backend,journal,loaded):
    r=journal.report;r['initial_status']=backend.outcome();journal.persist();no_output(r['initial_status'])
    require(group.exact(r['initial_status'],r['expected_status']),'Status changed since explicit read')
    r['initial']=backend.capture_full('initial');journal.persist();verify_capture(loaded,r['initial'])
    initial=backend.field(SPEC);require(type(initial) is int and initial==1,'Direct perimeter None expected')
    r['initial_full_capture_verified']=True;r['initial_perimeter']=initial;journal.persist()
    no_output(backend.outcome());result=backend.set_field(SPEC,lambda:journal.pending(ACTIONS[0]));journal.returned(ACTIONS[0],result)
    require(type(result) is int and result==0,'Strict property HRESULT0 required');backend.refresh_dirty()
    observed=backend.field(SPEC);r['actions'][ACTIONS[0]]['observed']=observed;journal.persist()
    require(type(observed) is int and observed==2,'Direct perimeter First readback required')
    r['actions'][ACTIONS[0]]['readback_verified']=True
    r['configured']=backend.capture_narrow('configured');journal.persist();verify_capture(loaded,r['configured'],corrected=True)
    r['configuration_readback_verified']=True;journal.persist()


def generate_and_save(backend,journal,loaded):
    r=journal.report;require(r.get('configuration_readback_verified') is True and r.get('initial_full_capture_verified') is True,'Reconciled corrected wall required')
    no_output(backend.outcome())
    result=backend.generate(lambda:journal.pending('GenerateToolpath'));journal.returned('GenerateToolpath',result)
    require(type(result) is int and result==0,'Strict selected GTP HRESULT0 required');backend.refresh_dirty()
    r['generation_status']=backend.outcome();journal.persist()
    status_25d(r['generation_status'])
    require(r['generation_status']['generated'] is True,'Selected GTP returned without actual output; no save or retry')
    r['generated']=backend.capture_narrow('generated');journal.persist()
    r['generated_record_counts']=verify_capture(loaded,r['generated'],corrected=True,generated=True)
    require(group.exact(r['generated_record_counts'],r['generation_status']['record_counts']),'Fresh stream counts differ')
    r['actions']['GenerateToolpath']['readback_verified']=True;journal.persist()
    reference=wall.save_projection(r['generated']);r['save_stage']={}
    def guard():
        backend.boundary();actual=backend.outcome();status_25d(actual)
        require(group.exact(actual,r['generation_status']),'Generated state changed before/after save')
    def capture(label):
        if label=='before':guard();return deepcopy(reference)
        r['final']=backend.capture_full('saved');journal.persist()
        counts=verify_capture(loaded,r['final'],corrected=True,generated=True,saved_sha=r['saved_source_sha256'])
        require(group.exact(counts,r['generated_record_counts']),'Saved wall counts changed')
        return wall.equivalent_projection(reference,wall.save_projection(r['final']))
    def save():
        result=backend.save();journal.returned('SaveActiveDocument',result);return result
    def saved_hash():
        sha=backend.saved_hash(r['save_stage']);require(sha!=r['initial_source_sha256'],'Changed saved CAM bytes required')
        r['saved_source_sha256']=sha;journal.persist();return sha
    wall.run_one_existing_save(r['save_stage'],capture=capture,verify=lambda x:wall.equivalent_projection(reference,x),guard=guard,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
    r.update(status='review_required',phase='finished',model_saved=True,readback_verified=True)


def validate_terminal(r):
    require(r['scope']==SCOPE and r['status']=='review_required' and r['phase']=='finished' and all(r[k] is True for k in ('readback_verified','configuration_readback_verified','model_saved','phase_proofs_verified','initial_full_capture_verified')),'Completed saved perimeter correction required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')) and all(r[k] is False for k in FORBIDDEN) and set(r['actions'])==set(ACTIONS),'Unexpected actions or uncertain evidence')
    no_output(r['initial_status']);require(group.exact(r['initial_status'],r['expected_status']),'Initial status differs')
    verify_capture(r['loaded_context_before'],r['initial'])
    for key,generated in (('configured',False),('generated',True),('final',True)):
        counts=verify_capture(r['loaded_context_before'],r[key],corrected=True,generated=generated,saved_sha=r['saved_source_sha256'] if key=='final' else None)
        if generated:require(group.exact(counts,r['generated_record_counts']),'Terminal path count differs')
    for action in r['actions'].values():wall.history.verified_action(action)
    require(type(r['actions'][ACTIONS[0]]['observed']) is int and r['actions'][ACTIONS[0]]['observed']==2,'Terminal perimeter differs')
    status_25d(r['generation_status'])
    require(r['generation_status']['generated'] is True and r['generation_status']['record_counts']==r['generated_record_counts'],'Terminal generated status differs')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save incomplete')
    require(r['source_transition']['strict_save_return']==0 and r['source_transition']['source_before_sha256']==r['initial_source_sha256'] and r['source_transition']['source_after_sha256']==r['saved_source_sha256'],'Saved transition differs')
    wall.equivalent_projection(wall.save_projection(r['generated']),wall.save_projection(r['final']));clean_events(r)
    context=original.make_context(r);context['generated_pocket_finish'].update(floor_candidate_included=False,bottom_finish_enabled=False,perimeter_pass_type=2)
    return context


def execute(sw,clsid,typelib,*,loaded,p,failedpin,statuspin,diagnosispin,expected,audit_result):
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p['expected_document_path'],p['expected_source_sha256'])
    paths=[receipt,marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+x+'.json') for x in ('initial','configured','generated','saved')]
    protected={common._key(v['path']) for v in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']};protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths),'Evidence aliases input')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh evidence/once marker required')
    r=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],module_pin=common._pin(__file__),failed_pin=failedpin,status_pin=statuspin,diagnosis_pin=diagnosispin,parent_pin=statuspin,expected_status=expected,loaded_context_before=loaded,live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],setter_interface_audit=audit_result,model_saved=False,readback_verified=False,mutation_attempted=False,configuration_readback_verified=False,initial_full_capture_verified=False,actions={},**{k:False for k in FORBIDDEN})
    journal=Journal(r,str(receipt),marker);_write_receipt(receipt,r,create=True)
    backend=NativeBackend(loaded,p,sw,clsid,typelib,r,journal.persist)
    try:
        backend.start();configure(backend,journal,loaded);generate_and_save(backend,journal,loaded)
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);r['phase_proofs_verified']=True
        context=validate_terminal(r);r['checkpoint_digest']=_digest(group.current_projection(context));journal.persist()
        r['marker_pin']=common._pin(marker);journal.persist();require(r['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved correction source/runtime/process differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    context=validate_terminal(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Saved correction digest differs')
    marker=marker_path(r['source_path'],r['initial_source_sha256']);mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()),'Immutable terminal once-marker differs')
    live=common._merge(r['live_pins'],[pin]);require(len(live)<=64,'Bounded completed correction closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[markpin]),parent_pin=pin,group_marker_pin=markpin)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded,failedpin,statuspin,diagnosispin,expected=load_inputs(p)
    reg=common.discover_export_registration(loaded,p['addin_clsid']);tlb=str(Path(reg['addin_path']).parent/'camworks.tlb');audit_result=audit(tlb,loaded['generated_pin'])
    no_output(expected);ready=True
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),setter_count=1,audit=audit_result,background_gate_ready=ready)
    no_output(expected)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,reg['clsid'],tlb,loaded=loaded,p=p,failedpin=failedpin,statuspin=statuspin,diagnosispin=diagnosispin,expected=expected,audit_result=audit_result)


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','native_called','background_gate_ready')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
