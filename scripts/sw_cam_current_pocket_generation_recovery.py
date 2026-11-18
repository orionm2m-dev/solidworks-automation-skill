"""Explicit Save/CL continuation of one observed first-GTP feed delta.
No setters or generation are replayed. The immutable partial stays uncertain.
"""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_current_pocket_generate as prior
from scripts import sw_cam_current_pocket_context as current
from scripts import sw_cam_current_saved_parameter_fields as fields
from scripts import sw_cam_current_saved_generation as engine
from scripts import sw_cam_current_pocket_generation_delta as delta
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error

reader=prior.reader
require=prior.require
SCOPE='CURRENT_POCKET_OBSERVED_GENERATION_SAVE_CL_RECOVERY_V1'
GENERATED_SCOPE='CURRENT_GENERATED_POCKET_CONTEXT_V1'
REASON='GTP changed protected operation, suppression, tool, parameter, feature/setup or source fields'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids','selected_operation_native_id','failed_generation_receipt_path','failed_generation_receipt_sha256','observed_xy_feed_before','observed_xy_feed_after','receipt_path','saved_cl_path','qualification_only','acknowledge_observed_feed_save_export','message_policy'}
FLAGS=('readback_verified','current_context_verified','recovery_saved_context_verified','inventory_delta_verified','parameter_delta_verified','generation_verified','CL_verified','runtime_unchanged')
IDENTITY=('process_id','expected_process_create_time','expected_document_path','expected_source_sha256','expected_feature_native_id','expected_operation_native_ids','selected_operation_native_id')


def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact observed-generation recovery request required')
    for k in ('process_id','expected_feature_native_id','selected_operation_native_id'):
        require(type(v[k])is int and 0<v[k]<2**31,'Strict positive identity required')
    ids=v['expected_operation_native_ids']
    require(type(ids)is list and len(ids)==2 and all(type(x)is int and 0<x<2**31 for x in ids) and len(set(ids))==2 and v['selected_operation_native_id']==ids[0],'Exact ordered Rough/Contour pair required')
    for k in ('expected_process_create_time','observed_xy_feed_before','observed_xy_feed_after'):
        require(type(v[k])in(int,float) and math.isfinite(v[k]) and v[k]>0,'Finite positive lifetime and observed feeds required')
    require(v['observed_xy_feed_before']!=v['observed_xy_feed_after'],'One explicitly observed changed feed required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute bound paths required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact immutable SHA required')
    require(v['qualification_only']is True and v['acknowledge_observed_feed_save_export']is True and v['message_policy']=='vendor_default','Explicit unqualified-feed Save/export admission required')


def strict_return(action):
    require(type(action)is dict and action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type')=='int' and type(action.get('native_return_value'))is int and action['native_return_value']==0,'Unique strict int0 native return required')


def verify_partial(raw,v,bundle,recipe):
    """Pure reconciliation: exactly recorded XYFeed, never an inferred factor."""
    shape(v);request=raw.get('request',{});prior.shape(request)
    for key in IDENTITY:
        match=reader.definition.creator.same_path(request[key],v[key])if key=='expected_document_path'else type(request[key])is type(v[key]) and request[key]==v[key]
        require(match,'Partial identity differs: '+key)
    require(raw.get('scope')==prior.SCOPE and raw.get('status')=='uncertain' and raw.get('phase')=='finished' and raw.get('failed_phase')=='generated' and raw.get('reason')==REASON,'Exact post-generation protected-state failure required')
    issue=raw.get('issue',{});require(issue.get('type')=='ValueError' and issue.get('hresult')is None and [(x.get('file'),x.get('function'))for x in issue.get('locations',[])]==[('sw_cam_current_pocket_generation_delta.py','verify_generation'),('sw_cam_current_saved_generation_delta.py','verify_generation'),('sw_cam_current_saved_generation_delta.py','require')],'Different failure is outside this recovery')
    require(not any(k in raw for k in ('cleanup_error','runtime_error','receipt_write_error')),'Cleanup/runtime failure is not admitted')
    require(all(raw.get(k)is True for k in ('GTP_attempted','native_call_attempted','native_call_returned','receipt_created','marker_created')) and raw.get('native_dispatch_pending')is False,'Completed historical single GTP required')
    require(all(raw.get(k)is False for k in ('Save_attempted','save_attempted','save_readback_verified','model_saved','CL_export_attempted','GOP_attempted','Import_attempted','automatic_replay','production_qualified','native_units_verified','cutting_conditions_qualified')),'Partial already saved/exported or outside permitted actions')
    require(all(raw.get(k)is False for k in prior.FLAGS),'Original uncertain verification flags must remain false')
    require(reader.shared.event_health(raw.get('messages',{}),active=False)==0 and raw['messages'].get('subscribed')is True and raw['messages'].get('subscription_error')is None,'Clean original event cleanup required')
    baseline=dict(inventory=bundle['state'],parameters=bundle['parameters'])
    require(raw.get('before')==baseline and raw.get('recipe')==recipe,'Actual original baseline/recipe differs')
    configured=raw['configured'];generated=raw['generated'];oid=v['selected_operation_native_id']
    plan=fields.compile_plan(delta.flatten(baseline),recipe)
    require(len(plan['rows'])==1 and plan['rows'][0]['operation_native_id']==oid and tuple(x['field']for x in plan['rows'][0]['fields'])==prior.FIELD_NAMES,'One original seven-field selected plan required')
    require(plan['rows'][0]['existing_tool_native_id']is None,'Tool assignment is outside original settings scope')
    fields.verify_final(delta.flatten(baseline),delta.flatten(configured),plan,{},observed_floor_alias=True)
    expected_readbacks=[];names=[]
    for change in plan['rows'][0]['fields']:
        changed=not fields.equal(change['expected'],change['new'])
        expected_readbacks.append(dict(field=change['field'],before=change['expected'],requested=change['new'],setter_attempted=changed,readback_verified=True,actual=change['new']))
        if changed:names.append('field:'+change['field'])
    names.append('GTP:'+str(oid))
    require(raw.get('field_readbacks')==expected_readbacks and list(raw.get('actions',{}))==names,'Historical action/readback sequence differs')
    for name in names:strict_return(raw['actions'][name])
    captures=raw.get('captures',[])
    require([x.get('label')for x in captures]==['before','configured','generated'],'Three complete original captures required')
    for item in captures:
        require(item.get('diagnostic',{}).get('capture_complete')is True and item.get('observation')==raw[item['label']] and item['diagnostic'].get('state')==raw[item['label']]['inventory'],'Raw full capture differs from claimed snapshot')
    require(configured['parameters'][0]['operation_native_id']==generated['parameters'][0]['operation_native_id']==oid,'Selected parameter row binding differs')
    before=configured['parameters'][0]['nc']['feeds_compensation']['XYFeed'];after=generated['parameters'][0]['nc']['feeds_compensation']['XYFeed']
    require(type(before)in(int,float) and type(after)in(int,float) and before==v['observed_xy_feed_before'] and after==v['observed_xy_feed_after'],'Explicit observed feed values differ from immutable raw')
    admitted=deepcopy(configured);admitted['parameters'][0]['nc']['feeds_compensation']['XYFeed']=after
    proof=delta.verify_generation(admitted,generated,oid,raw['actions']['GTP:'+str(oid)])
    transform=prior.verify_transform(raw['setup_transform'],fields.parameter_row(delta.flatten(baseline),oid)['levels'])
    require(transform==raw.get('setup_transform_proof'),'Original setup-transform proof differs')
    return dict(plan=plan,expected_state=deepcopy(generated),feed_delta=dict(operation_native_id=oid,path='/parameters/0/nc/feeds_compensation/XYFeed',before=before,after=after,feed_unqualified=True,cause_verified=False),generation_proof=proof)


def marker_path(v):
    return Path(v['expected_document_path']).parent/('current_pocket_generated_recovery_'+_digest(dict(scope=SCOPE,target=reader.definition.creator.canonical(v['expected_document_path']),source_sha256=v['expected_source_sha256']))+'.json')


def prepare(v):
    shape(v);raw,pin=reader.definition.read_pin(v['failed_generation_receipt_path'],v['failed_generation_receipt_sha256'])
    original=raw['request'];bundle=current.load_current_baseline(original)
    recipe,recipe_pin=reader.definition.read_pin(original['recipe_path'],original['recipe_sha256'])
    proof=verify_partial(raw,v,bundle,recipe)
    require(raw['configuration_receipt_pin']==bundle['receipt_pin'] and raw['recipe_pin']==recipe_pin,'Original direct input pin binding differs')
    old_marker_path=prior.marker_path(original);old_marker,old_pin=reader.definition.read_pin(str(old_marker_path),_file_hash(old_marker_path))
    expected=dict(scope=prior.SCOPE,receipt_path=original['receipt_path'],receipt_sha256=pin['sha256'],configuration_receipt_pin=raw['configuration_receipt_pin'],selected_operation_native_ids=[v['selected_operation_native_id']],status='uncertain',phase='finished',automatic_replay=False)
    require(old_marker==expected and reader.definition.creator.same_path(original['receipt_path'],pin['path']),'Consumed original marker differs')
    original_pins=raw.get('evidence_pins');require(type(original_pins)is list and 1<=len(original_pins)<=64,'Complete original bounded evidence required')
    extras=[pin,old_pin,recipe_pin]+[reader.shared.file_pin(p,_file_hash(p))for p in (__file__,prior.__file__,current.__file__,fields.__file__,engine.__file__,delta.__file__)]
    d=bundle['context']
    for extra in original_pins+extras:d['pins']=current._pins(d['pins']+[extra])
    require(len(d['pins'])<=64,'Complete recovery evidence exceeds existing guard bound');reader.definition.verify_files(d)
    receipt=Path(v['receipt_path']);marker=marker_path(v);cl=prior._fresh_path(v['saved_cl_path'])
    for output in (receipt,marker):
        require(output.suffix.lower()=='.json' and output.parent.is_dir() and not output.exists() and not output.is_symlink(),'Fresh recovery receipt and unused marker required; no replay')
    require(receipt!=marker and all(not reader.definition.creator.same_path(str(output),p['path'])for output in(receipt,marker,cl)for p in d['pins']),'Recovery outputs alias protected evidence')
    return dict(bundle=bundle,raw=raw,raw_pin=pin,old_marker_pin=old_pin,recipe=recipe,recipe_pin=recipe_pin,request=deepcopy(v),receipt=receipt,marker=marker,consumed=False,**proof)


def preflight(tlb):
    return prior.preflight(tlb)


class Journal(engine.Journal):
    def marker_state(self):return dict(super().marker_state(),scope=SCOPE)
    def action(self,name):
        require(name in ('SaveActiveDocument','postCL'),'Only Save and postCL are permitted');return super().action(name)
    def pending(self,name):
        require(name in ('SaveActiveDocument','postCL'),'No setters or generation replay');return super().pending(name)


class Backend(prior.Backend):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        # Reader admission only: this operation was generated by the pinned prior call.
        self.attempted=[self.args['selected_operation_native_id']]
    def start(self):
        super().start()
        require(self.expected_document==self.data['expected_state']['inventory']['document'],'Fresh active document differs from historical generated state')
    def forbidden(self,*args,**kwargs):raise ValueError('Recovery forbids setters, tool changes and generation replay')
    generate=set_field=read_field=create=field=property=attach_holder=assign_selected=forbidden


def run_backend(backend,journal,data):
    r=journal.report;v=data['request'];oid=v['selected_operation_native_id']
    try:
        journal.create();backend.start();fresh=backend.capture_current('recovery_current');r['before']=deepcopy(fresh);journal.persist()
        require(fresh==data['expected_state'],'Fresh generated state differs from pinned observed state')
        backend.boundary();journal.claim();backend.boundary();journal.action('SaveActiveDocument')
        def capture(label):
            value=backend.capture_current(label)
            if label=='before':
                r['confirm_before']=deepcopy(value);journal.persist()
                require(value==fresh==data['expected_state'],'Second fresh confirmation and Save-before differ')
                r['second_capture_roles']=['generated_state_confirmation','save_before'];journal.persist()
            return value
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        saved=current.save_current_baseline(r,data['bundle'],fresh,capture=capture,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,adopt_context=backend.adopt_context)
        r['current_context']=deepcopy(saved['payload']);r['current_context']['scope']=GENERATED_SCOPE
        r['current_context']['historical_generation_receipt_pin']=deepcopy(data['raw_pin'])
        r['current_context']['observed_feed_delta']=deepcopy(data['feed_delta'])
        r['saved']=dict(inventory=saved['state'],parameters=saved['parameters']);journal.persist()
        state=delta.flatten(r['saved']);selected=next(x for x in state['operations']if x['native_id']==oid)
        rows=[dict(operation_native_id=oid,toolpath_record_counts=selected['toolpath_record_counts'])]
        journal.action('postCL');export={};r['postCL']=export
        backend.export_cl('postCL',state,rows,export,pending=lambda:journal.pending('postCL'),returned=lambda value:journal.returned('postCL',value))
        strict_return(r['actions']['postCL']);require(export.get('output_verified')is True and export.get('readback_verified')is True,'Verified native export required')
        parsed=backend.parse_cl(export);r['first_CL_proof']=delta.verify_first_cl(parsed,oid,selected['toolpath_record_counts'][0]);journal.persist()
        backend.close();backend.runtime_check();document=backend.identity();require(document==backend.expected_document,'Document changed during cleanup');backend.files()
        require(reader.shared.event_health(r['messages'],active=False)==0,'Clean event cleanup required')
        r['after_cleanup_identity']=dict(document=document,saved_file_sha256=backend.source)
        r.update(status='review_required',phase='finished',**{key:True for key in FLAGS})
    except Exception as error:
        r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',failed_phase=r.get('phase'),phase='finished',reason=str(error),issue=_error(error),**{key:False for key in FLAGS})
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',cleanup_error=_error(error),**{key:False for key in FLAGS})
        r['phase']='finished';journal.persist()
    return r


def run(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_backend_factory=Backend):
    data=prepare(v)if prepared is None else prepared;require(data.get('consumed')is False and data['request']==v,'Prepared recovery may be consumed exactly once');data['consumed']=True
    abi=preflight(tlb);d=data['bundle']['context'];d['pins']=current._pins(d['pins']+[abi['generated_pin'],reader.shared.file_pin(tlb,_file_hash(tlb))]);reader.definition.verify_files(d);runtime_check()
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(v),configuration_receipt_pin=data['raw_pin'],current_baseline_receipt_pin=data['bundle']['receipt_pin'],historical_GTP_receipt_pin=data['raw_pin'],historical_marker_pin=data['old_marker_pin'],historical_status='uncertain',historical_runtime_unchanged=data['raw']['runtime_unchanged'],selected_operation_native_ids=[v['selected_operation_native_id']],recipe=data['recipe'],recipe_pin=data['recipe_pin'],observed_feed_delta=data['feed_delta'],historical_generation_proof=data['generation_proof'],setup_transform=data['raw']['setup_transform'],setup_transform_proof=data['raw']['setup_transform_proof'],evidence_pins=deepcopy(d['pins']),abi=abi,actions={},captures=[],mutation_attempted=False,operation_parameter_setters_attempted=False,setters_replayed=False,GTP_attempted=False,GTP_replayed=False,GOP_attempted=False,Import_attempted=False,Save_attempted=False,save_attempted=False,save_readback_verified=False,model_saved=False,CL_export_attempted=False,automatic_replay=False,preCL_exported=False,baseline_generated_operation_count=1,generated_current_context_readable_by_old_loader=False,feed_unqualified=True,feed_change_cause_verified=False,production_qualified=False,physical_tool_qualified=False,native_units_verified=False,cutting_conditions_qualified=False,island_geometry_verified=False,geometry_sweep_verified=False,reopen_persistence_verified=False,**{key:False for key in FLAGS})
    journal=Journal(data['receipt'],data['marker'],r);backend=_backend_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check,abi)
    return run_backend(backend,journal,data)


def revoke(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')or r.get('CL_export_attempted')else'error',runtime_error=_error(error),**{key:False for key in FLAGS});reader._write_receipt(Path(r['request']['receipt_path']),r);return r
