"""Complete eight wall lead fields after verified reopen; selected GTP and save.

Historical data supplies an explicit expectation. A fresh full native capture
must reconcile before any setter. No floor flag, assignment or global GTP.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_pocket_finish_apply as original
from scripts import sw_cam_pocket_finish_continuation as history
from scripts import sw_cam_pause_reopen as reopen
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
from scripts.sw_cam_rough_firstcut import require
common,group=original.common,original.group
SCOPE='REOPENED_POCKET_WALL_CONTINUATION_V1'
AUTHORITY=original.AUTHORITY
FIELDS=original.FIELDS[7:]
ACTIONS=tuple('field:'+x[0] for x in FIELDS)+('GenerateToolpath','SaveActiveDocument')
FORBIDDEN=original.FORBIDDEN+('assignment_attempted','bottom_finish_setter_attempted','floor_operation_attempted')
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','receipt_path','progress_path',
 'expected_module_sha256','reopen_receipt_path','reopen_receipt_sha256','failed_receipt_path','failed_receipt_sha256',
 'continuation_receipt_path','continuation_receipt_sha256','direct_receipt_path','direct_receipt_sha256'}
save_projection=original.save_projection
equivalent_projection=original.equivalent_projection
run_one_existing_save=original.run_one_existing_save


def expected_parameters(before,configured=False):
    value=original.projected(before)
    if configured:
        for spec in FIELDS:value['144']['leads'][spec[1]][spec[2]]=deepcopy(spec[6])
    return value


def verify_capture(loaded,value,*,configured=False,generated=False,saved_sha=None):
    a,b=deepcopy(loaded['state']),deepcopy(value['state'])
    require(a['operation_count']==b['operation_count']==8 and len(a['features'])==len(b['features'])==21,'Route size changed')
    require([x['native_id'] for x in a['operations']]==[x['native_id'] for x in b['operations']]==original.ORDER,'Route order changed')
    old,new=a['operations'][-1],b['operations'][-1]
    require(old['toolpath_generated'] is False and old['toolpath_record_counts']==[] and group.exact(old['assigned_tool'],original.wanted_assignment(loaded)),'Saved assigned ungenerated wall required')
    require(new['toolpath_generated'] is generated and group.exact(new['assigned_tool'],old['assigned_tool']),'Assignment or generation changed')
    counts=deepcopy(new['toolpath_record_counts'])
    require((generated and len(counts)==1 and type(counts[0]) is int and 0<counts[0]<=100000) or (not generated and counts==[]),'Bounded wall count required')
    new['toolpath_generated'],new['toolpath_record_counts']=False,[]
    require(type(b['document']['needs_save']) is bool,'Boolean dirty flag required')
    b['document']['needs_save']=a['document']['needs_save']
    if saved_sha is not None:
        require(value['state']['document']['needs_save'] is False and b['saved_file_sha256']==saved_sha,'Clean saved result required')
        b['saved_file_sha256']=a['saved_file_sha256']
    original.require_state_equivalent(a,b)
    expected=expected_parameters(loaded['pocket_parameters'],configured)
    observed=original.normalize_nc_roundoff(expected,original.projected(value['parameters']))
    require(group.exact(expected,observed) and observed['144']['finish']['BottomFinOpt'] is False,'NC, roughing, floor or unapproved parameters changed')
    require(group.exact(value['startpoints'],loaded['pocket_startpoints']),'Rough entry changed')
    if 'catalogue' in value:require(group.exact(value['catalogue'],loaded['neck_tool_checkpoint']['catalogue']),'Catalogue changed')
    return counts


def initial_fields():
    values={x[0]:deepcopy(x[5]) for x in original.FIELDS}
    for spec in original.FIELDS[:7]:values[spec[0]]=False if spec[0]=='bottom_finish' else deepcopy(spec[6])
    return values


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='continue_reopened_pocket_wall','Exact wall action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Owned PID required')
    for key,value in p.items():
        if key.endswith('_path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
        if key.endswith('_sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact hash required')
    require(p['expected_module_sha256']==_file_hash(__file__),'Writer changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM CLSID required')
    return p


def bind_expected(failed,continuation,direct,reopened):
    old=history.validate_failed(failed)
    require(continuation['scope']==history.SCOPE and continuation['status']=='uncertain' and continuation['failed_phase']=='field:bottom_finish' and continuation['model_saved'] is False,'Exact historical continuation required')
    require(set(continuation['actions'])=={'field:side_step','field:override_previous','field:bottom_finish'},'Unexpected historical actions')
    for name in ('side_step','override_previous'):
        history.verified_action(continuation['actions']['field:'+name])
        require(group.exact(continuation['actions']['field:'+name]['observed'],initial_fields()[name]),'Historical value differs')
    require(direct['read_only'] is True and direct['setter_attempted'] is False and direct['GTP_attempted'] is False and direct['readback_verified'] is True and direct['phase_proofs_verified'] is True and group.exact(direct['fields'],initial_fields()),'Actual fifteen-field read required')
    clean_events(direct)
    require(group.exact(reopened['actual']['finish_fields'],{k:initial_fields()[k] for k in reopened['actual']['finish_fields']}),'Reopen fields differ')
    runtime=deepcopy(old);runtime['state']=deepcopy(continuation['reconciled']['state'])
    runtime['state']['document']=deepcopy(reopened['actual']['document']);runtime['state']['saved_file_sha256']=reopened['source_sha256']
    runtime['source_sha256']=reopened['source_sha256'];runtime['ownership']=deepcopy(reopened['startup_identity'])
    runtime['pocket_parameters']=original.projected(continuation['reconciled']['parameters'])
    runtime['pocket_parameters']['144']['finish'].update(SideCutAmt=.25,OverridePrevAllow=True,BottomFinOpt=False)
    runtime['pocket_startpoints']=deepcopy(continuation['reconciled']['startpoints'])
    require(group.exact(continuation['reconciled']['catalogue'],old['neck_tool_checkpoint']['catalogue']),'Historical catalogue differs')
    require(runtime['state']['operations'][-1]['assigned_tool']['native_id']==old['neck_tool_candidate']['native_id'],'Historical assignment differs')
    require(len(runtime['state']['operations'])==len(reopened['actual']['operations'])==8,'Eight operations required')
    for row,actual in zip(runtime['state']['operations'],reopened['actual']['operations']):
        expected=dict(id=row['native_id'],setup_id=row['setup_native_id'],generated=row['toolpath_generated'],suppressed=row['suppressed'],tool_id=row['assigned_tool']['native_id'],record_counts=row['toolpath_record_counts'],feature_ids=row['linked_feature_ids'])
        require(group.exact(expected,actual),'Reopened inventory differs from expected history')
    runtime['authority_kind']='reopened_partial_wall_expected_projection_unverified'
    return runtime


def load_inputs(p):
    reopened=reopen.load_verified_reopen(p['reopen_receipt_path'],p['reopen_receipt_sha256'])
    require(reopened['process_id']==p['process_id'] and reopened['source_sha256']==p['expected_source_sha256'] and common._key(reopened['source_path'])==common._key(p['expected_document_path']),'Current reopen binding differs')
    failed,failedpin=read_pin(p['failed_receipt_path'],p['failed_receipt_sha256'])
    continuation,contpin=read_pin(p['continuation_receipt_path'],p['continuation_receipt_sha256'])
    direct,directpin=read_pin(p['direct_receipt_path'],p['direct_receipt_sha256'])
    runtime=bind_expected(failed,continuation,direct,reopened)
    recipe,recipepin=read_pin(failed['recipe_pin']['path'],failed['recipe_pin']['sha256']);original.validate_recipe(recipe)
    runtime['recipe_pin']=recipepin;runtime['reopen_pin']=common._pin(p['reopen_receipt_path'])
    retired=[x for x in runtime['pins'] if Path(x['path']).suffix.lower()=='.json' or Path(x['path']).name=='sw_cam_pocket_rough_exports.py']
    live=common._merge([x for x in runtime['pins'] if x not in retired],[common._pin(__file__),common._pin(original.__file__)])
    offline=common._merge(runtime['offline_export_proof_pins'],retired,[failedpin,contpin,directpin,recipepin,runtime['reopen_pin'],common._pin(history.__file__),common._pin(reopen.__file__)])
    require(len(live)<=63,'Reserve one completed receipt slot in bounded live closure')
    runtime.update(pins=live,offline_export_proof_pins=offline,parent_pin=runtime['reopen_pin'])
    runtime['current_context_sha256']=_digest(group.current_projection(runtime))
    common._check(live);common._check(offline);common._check(runtime['bootstrap_export_pins'])
    return runtime


def marker_path(source,sha):
    return common.local_evidence_root()/('pocket_wall_'+_digest(dict(scope=SCOPE,source=common._key(source),source_sha256=sha,operation=144))+'.json')


class Journal(original.Journal):
    def marker_state(self):
        return dict(super().marker_state(),scope=SCOPE,reopen_pin=self.report['reopen_pin'],floor_candidate_included=False)


class NativeBackend(original.NativeBackend):
    def assign(self,pending):raise RuntimeError('Wall continuation cannot assign tools')
    def set_field(self,spec,pending):
        require(spec in FIELDS,'Only eight lead fields may be written')
        return super().set_field(spec,pending)


def prepare(p,loaded,audit):
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p['expected_document_path'],p['expected_source_sha256'])
    paths=[receipt,marker]+[Path(p['progress_path']).with_name(Path(p['progress_path']).stem+'.'+label+'.json') for label in ('initial','configured','generated','saved')]
    protected={common._key(x['path']) for x in loaded['pins']+loaded['offline_export_proof_pins']+loaded['bootstrap_export_pins']};protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths),'Evidence aliases input')
    require(all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh outputs/once marker required')
    report=dict(schema_version=1,scope=SCOPE,status='prepared',phase='prepared',actions={},process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],receipt_path=str(receipt),module_pin=common._pin(__file__),recipe_pin=loaded['recipe_pin'],reopen_pin=loaded['reopen_pin'],parent_pin=loaded['parent_pin'],loaded_context_before=deepcopy(loaded),live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],setter_interface_audit=audit,mutation_attempted=False,configuration_readback_verified=False,readback_verified=False,model_saved=False,phase_proofs_verified=False,initial_full_capture_verified=False,actual_full_capture_count=0,floor_candidate_included=False,**{k:False for k in FORBIDDEN})
    return report,marker


def configure(backend,journal,loaded):
    r=journal.report;r['initial']=backend.capture_full('initial');r['initial_full_capture_count']=1
    r['initial_fields']={spec[0]:backend.field(spec) for spec in original.FIELDS};journal.persist()
    verify_capture(loaded,r['initial'])
    require(group.exact(r['initial_fields'],initial_fields()),'Reopened fifteen direct fields differ')
    r['initial_full_capture_verified']=True;journal.persist()
    for spec in FIELDS:
        require(group.exact(backend.field(spec),r['initial_fields'][spec[0]]),'Field drifted before setter')
        label='field:'+spec[0];result=backend.set_field(spec,lambda label=label:journal.pending(label));journal.returned(label,result)
        require(type(result) is int and result==0,'Strict native HRESULT zero required');backend.refresh_dirty()
        actual=backend.field(spec);r['actions'][label]['observed']=deepcopy(actual);journal.persist()
        require(group.exact(actual,spec[6]),'Direct lead readback differs')
        r['actions'][label]['readback_verified']=True;journal.persist()
    r['configured']=backend.capture_narrow('configured');journal.persist();verify_capture(loaded,r['configured'],configured=True)
    r['configuration_readback_verified']=True;journal.persist()


def validate_terminal(r):
    require(r['scope']==SCOPE and r['status']=='review_required' and r['phase']=='finished' and all(r.get(k) is True for k in ('readback_verified','configuration_readback_verified','model_saved','phase_proofs_verified','initial_full_capture_verified')) and r['initial_full_capture_count']==1 and r['actual_full_capture_count']==1,'Completed saved wall continuation required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')) and all(r[k] is False for k in FORBIDDEN) and r['floor_candidate_included'] is False and set(r['actions'])==set(ACTIONS),'Unexpected actions or uncertain evidence')
    loaded=r['loaded_context_before'];verify_capture(loaded,r['initial']);require(group.exact(r['initial_fields'],initial_fields()),'Initial direct read differs')
    for key,generated in (('configured',False),('generated',True),('final',True)):
        counts=verify_capture(loaded,r[key],configured=True,generated=generated,saved_sha=r['saved_source_sha256'] if key=='final' else None)
        if generated:require(group.exact(counts,r['generated_record_counts']),'Terminal wall counts differ')
    for action in r['actions'].values():history.verified_action(action)
    for spec in FIELDS:require(group.exact(r['actions']['field:'+spec[0]]['observed'],spec[6]),'Terminal lead read differs')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save incomplete')
    require(r['source_transition']['strict_save_return']==0 and r['source_transition']['source_before_sha256']==r['initial_source_sha256'] and r['source_transition']['source_after_sha256']==r['saved_source_sha256'],'Source transition differs')
    equivalent_projection(save_projection(r['generated']),save_projection(r['final']));clean_events(r)
    context=original.make_context(r);context['generated_pocket_finish'].update(floor_candidate_included=False,bottom_finish_enabled=False)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    registration=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    audit=original.audit_recipe(typelib,loaded['generated_pin']);report,marker=prepare(p,loaded,audit)
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),marker=str(marker),setter_count=8)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,loaded=loaded,params=p,report=report,marker=marker)


def generate_and_save(backend,journal,loaded):
    r=journal.report;require(r.get('configuration_readback_verified') is True and r.get('initial_full_capture_verified') is True,'Full reopened reconcile and configured wall required')
    result=backend.generate(lambda:journal.pending('GenerateToolpath'));journal.returned('GenerateToolpath',result)
    require(type(result) is int and result==0,'Strict selected GTP HRESULT0 required');backend.refresh_dirty()
    r['generated']=backend.capture_narrow('generated')
    r['generated_record_counts']=verify_capture(loaded,r['generated'],configured=True,generated=True)
    r['actions']['GenerateToolpath']['readback_verified']=True;journal.persist()
    expected=save_projection(r['generated']);r['save_stage']={}
    def capture(label):
        if label=='before':backend.boundary();return deepcopy(expected)
        r['final']=backend.capture_full('saved');r['actual_full_capture_count']=1
        counts=verify_capture(loaded,r['final'],configured=True,generated=True,saved_sha=r['saved_source_sha256'])
        require(group.exact(counts,r['generated_record_counts']),'Saved144 count changed')
        return equivalent_projection(expected,save_projection(r['final']))
    def save():
        result=backend.save();journal.returned('SaveActiveDocument',result);return result
    def saved_hash():
        sha=backend.saved_hash(r['save_stage']);require(sha!=r['initial_source_sha256'],'New saved bytes required')
        r['saved_source_sha256']=sha;journal.persist();return sha
    run_one_existing_save(r['save_stage'],capture=capture,verify=lambda value:equivalent_projection(expected,value),guard=backend.boundary,
        claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
    r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
    r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True)


def run_backend(backend,journal,loaded):
    r=journal.report
    try:
        backend.start();configure(backend,journal,loaded);generate_and_save(backend,journal,loaded)
    except Exception as exc:r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        journal.persist()
    return r


def execute(sw,clsid,typelib,*,loaded,params,report,marker):
    journal=Journal(report,params['receipt_path'],marker);_write_receipt(params['receipt_path'],report,create=True)
    backend=NativeBackend(loaded,params,sw,clsid,typelib,report,journal.persist);result=run_backend(backend,journal,loaded)
    try:
        common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins']);result['phase_proofs_verified']=True
        if result.get('readback_verified') is True:
            context=validate_terminal(result);result['checkpoint_digest']=_digest(group.current_projection(context));journal.persist()
            result['marker_pin']=common._pin(marker);journal.persist()
            require(result['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
    except Exception as exc:result.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
    journal.persist();return result


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved finish source/runtime/process differs')
    common._check(r['live_pins']);common._check(r['offline_proof_pins']);common._check(r['bootstrap_export_pins'])
    context=validate_terminal(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Saved finish checkpoint digest differs')
    marker=marker_path(r['source_path'],r['initial_source_sha256']);mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()),'Exact immutable terminal once-marker differs')
    live=common._merge([x for x in r['live_pins'] if common._key(x['path'])!=common._key(r['parent_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded completed finish runtime closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[r['parent_pin'],markpin]),parent_pin=pin,group_marker_pin=markpin)
    return context


def main(argv=None):
    import argparse
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true')
    args=parser.parse_args(argv)
    request=json.loads(Path(args.request).read_text(encoding='utf-8-sig'))
    result=dispatch_request(request,validate_only=args.validate_only)
    print(json.dumps({key:result.get(key) for key in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status')=='validated_offline' else 1

if __name__=="__main__":
    raise SystemExit(main())
