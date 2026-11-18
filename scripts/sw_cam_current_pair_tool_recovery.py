"""Recover one interrupted, already assigned flat tool; never create or assign.
The original raw receipt and once marker remain immutable. Only a positively
returned SetTool may be adopted, with either one not-yet-attempted Save or a
read-only verification of a positively returned Save with observed new bytes.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_current_pair_tool as tool
from scripts import sw_cam_current_pocket_context as current
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error

require=tool.require
definition=tool.reader.definition
SCOPE='CURRENT_POCKET_EXISTING_ASSIGNED_TOOL_RECOVERY_V1'
KEYS=set(current.IDENTITY_KEYS)|{'selected_operation_native_id','expected_tool_native_id','partial_receipt_path','partial_receipt_sha256','original_marker_path','original_marker_sha256','cli_result_path','cli_result_sha256','executor_exit_path','executor_exit_sha256','receipt_path','qualification_only','acknowledge_existing_tool_recovery','message_policy'}

def shape(v):
    require(type(v)is dict and set(v)==KEYS,'Exact existing-tool recovery request required')
    for k in ('process_id','expected_feature_native_id','selected_operation_native_id','expected_tool_native_id'):
        require(type(v[k])is int and 0<v[k]<2**31,'Strict positive identity required')
    ids=v['expected_operation_native_ids']
    require(type(ids)is list and len(ids)==2 and all(type(x)is int and 0<x<2**31 for x in ids) and len(set(ids))==2 and ids[0]==v['selected_operation_native_id'],'Ordered current Rough/Contour pair required')
    require(type(v['expected_process_create_time'])in(int,float) and tool.reader.math.isfinite(v['expected_process_create_time']) and v['expected_process_create_time']>0,'Exact owned lifetime required')
    for k,x in v.items():
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
    require(v['qualification_only']is True and v['acknowledge_existing_tool_recovery']is True and v['message_policy']=='vendor_default','Explicit recovery scope required')

def _executor_creation_time(pid):
    try:identity=definition._process_identity(pid)
    except Exception as error:
        # OpenProcess(ERROR_INVALID_PARAMETER) is the existing helper's absent
        # PID result. Access denied and unknown errors must remain blockers.
        if getattr(error,'winerror',None)==87:return None
        raise
    require(identity.get('process_id')==pid and type(identity.get('alive'))is bool and type(identity.get('create_time'))in(int,float) and tool.reader.math.isfinite(identity['create_time']),'Complete executor OS identity required')
    return identity['create_time']if identity['alive']else None

def check_executors(exit_observation,*,creation_time=None):
    if creation_time is None:creation_time=_executor_creation_time
    observations=[]
    for p in exit_observation['executor_processes']:
        actual=creation_time(p['process_id'])
        same=actual is not None and abs(actual-p['creation_time'])<=0.001
        observations.append(dict(process_id=p['process_id'],recorded_creation_time=p['creation_time'],actual_creation_time=actual,original_alive=same,role=p['role']))
        if p['role']!='console':require(not same,'Original client/backend lifetime still exists; recovery forbidden')
    return observations

def validate_interruption(v,raw,marker,cli,ex):
    require(cli.get('status')=='timeout' and cli.get('current_request',{}).get('name')=='solidworks_cam_create_assign_current_pocket_tool','Actual terminal timeout of this tool required')
    require(ex.get('scope')=='CURRENT_PAIR_TOOL_EXECUTOR_EXIT_V1' and ex.get('status')=='observed' and ex.get('all_executors_absent')is True,'Confirmed executor exit observation required')
    for k in ('process_id','expected_process_create_time','expected_document_path'):
        require(ex.get(k)==v[k],'Executor observation owned identity differs')
    for prefix in ('partial_receipt','original_marker','cli_result'):
        require(ex.get(prefix+'_pin')==dict(path=v[prefix+'_path'],sha256=v[prefix+'_sha256']),'Exit observation input pin differs')
    processes=ex.get('executor_processes')
    require(type(processes)is list and 2<=len(processes)<=8,'Bounded observed original executor tree required')
    ids=[]
    for p in processes:
        require(set(p)=={'process_id','creation_time','alive','role'} and type(p['process_id'])is int and 0<p['process_id']<2**31 and p['process_id']!=v['process_id'] and type(p['creation_time'])in(int,float) and tool.reader.math.isfinite(p['creation_time']) and p['creation_time']>0 and p['role']in ('client','backend','console') and (p['alive']is False or p['role']=='console'),'Exact absent original executor identity required')
        ids.append(p['process_id'])
    require(len(set(ids))==len(ids) and {'client','backend'}<={p['role']for p in processes},'Distinct client and backend executor identities required')
    require(marker.get('scope')==tool.SCOPE and marker.get('actions')==raw.get('actions') and marker.get('new_tool_native_id')==raw.get('new_tool_native_id'),'Original once journal differs from partial actions')
    require(definition.creator.same_path(marker.get('receipt_path',''),v['partial_receipt_path']) and definition.creator.same_path(raw.get('receipt_path',''),v['partial_receipt_path']),'Raw receipt and once binding differ')
    require(marker.get('source_path')==raw.get('source_path') and marker.get('initial_source_sha256')==raw.get('initial_source_sha256') and marker.get('automatic_replay')is False,'Original once source binding differs')
    require(definition.creator.same_path(str(tool.marker_path(raw['request'])),v['original_marker_path']),'Exact original target/source marker required')

def returned_zero(row):
    return (type(row)is dict and row.get('attempted')is True and row.get('returned')is True and row.get('pending')is False and row.get('native_return_type')=='int' and type(row.get('native_return_value'))is int and row['native_return_value']==0)

def validate_partial(raw,v):
    require(raw.get('scope')==tool.SCOPE and raw.get('status')in ('prepared','uncertain') and raw.get('mutation_attempted')is True and raw.get('assignment_attempted')is True,'Interrupted original one-tool attempt required')
    tool.shape(raw['request'])
    for k in set(current.IDENTITY_KEYS)-{'expected_source_sha256'}|{'selected_operation_native_id'}:
        require(type(raw['request'][k])is type(v[k]) and raw['request'][k]==v[k],'Original recovery identity differs: '+k)
    require(type(raw.get('new_tool_native_id'))is int and raw['new_tool_native_id']==v['expected_tool_native_id'],'Exact actual created tool required')
    for k in ('GOP_attempted','GTP_attempted','Import_attempted','operation_parameter_setters_attempted','TechDB_write_attempted','automatic_replay','production_qualified'):
        require(raw.get(k)is False,'Unexpected original action/qualification: '+k)
    require(not any(raw.get(k)for k in ('issue','cleanup_error','runtime_error')),'Known original failure is not a transport interruption')
    a=raw['actions'];require(type(a)is dict and set(a)<=tool.ACTIONS and returned_zero(a.get('SetTool')) and returned_zero(a.get('SetFilePathForUserDefinedHolder')),'Completed SetTool and holder return0 required')
    creation=a.get('AddNewTool3',{})
    require(creation.get('attempted')is True and creation.get('returned')is True and creation.get('pending')is False and creation.get('returned_interface_pointer')is True,'Completed original factory return required')
    for name,row in a.items():
        require(row.get('attempted')is True and row.get('returned')is True and row.get('pending')is False,'No pending native action may be recovered')
        if name.startswith('property:'):require(row.get('native_return_type')=='NoneType' and row.get('native_return_value')is None,'Exact completed field return required')
    proposed=tool.serial.validate_recipe(raw['recipe']);rows=raw.get('field_readbacks',[])
    require([x.get('property')for x in rows]==list(tool.factory.FIELD_ORDER),'All ordered field readbacks required')
    for row in rows:require(row.get('readback_verified')is True and tool.prior.scalar_equal(row.get('requested'),proposed[row['property']]) and tool.prior.scalar_equal(row.get('actual'),proposed[row['property']]),'Exact configured field readback required')
    require(raw.get('factory_classification')==dict(MillToolType=1,MillToolSubType=3,EndRadius=0.),'Original flat BOTH classification required')
    tool.geometry.verify_candidate(raw['configured_candidate'],raw['recipe'],raw['holder_recipe'])
    require(raw['duplicate_policy'].get('new_definition_permitted_by_duplicate_policy')is True,'Original duplicate admission required')
    require(tool.reader.shared.event_health(raw['messages'],active=raw['messages'].get('active'))==0,'Original CAM event scope is not clean')
    configured=[c['observation']for c in raw['captures']if c.get('label')=='configured_unassigned' and 'observation'in c]
    require(len(configured)==1,'Complete original configured/unassigned capture required')
    tool.verify_pair_delta(raw['before'],configured[0],selected_id=v['selected_operation_native_id'])
    protected={str(x['assigned_tool']['native_id'])for x in raw['before']['inventory']['operations']}
    require(set(raw['protected_tools_before'])==protected and all(type(row.get('native_id'))is int and str(row['native_id'])==key for key,row in raw['protected_tools_before'].items()),'Complete original assigned-tool protection required')
    if raw.get('Save_attempted')is False:
        require('SaveActiveDocument'not in a and raw.get('native_save',{})in ({},{'phase':'before_capture'}) and raw.get('model_saved')is False and not raw.get('saved_file_sha256_after_native_return'),'Save preimage must be explicitly unattempted')
        require(v['expected_source_sha256']==raw['initial_source_sha256']==raw['request']['expected_source_sha256'],'Unattempted Save source changed')
        require(type(raw.get('after_assignment',{}).get('inventory',{}).get('document',{}).get('needs_save'))is bool,'Completed original assignment/dirty observation required')
        tool.verify_pair_delta(raw['before'],raw['after_assignment'],selected_id=v['selected_operation_native_id'],new_tool_id=v['expected_tool_native_id'])
        return 'save_once'
    require(raw.get('Save_attempted')is True and returned_zero(a.get('SaveActiveDocument')) and raw.get('model_saved')is True,'Only positively returned already-saved branch supported')
    n=raw.get('native_save',{})
    require(n.get('save_pending')is False and n.get('native_call_returned')is True and n.get('native_return_type')=='int' and type(n.get('native_return_value'))is int and n['native_return_value']==0,'Original native Save int0/no pending required')
    require(raw.get('saved_file_sha256_after_native_return')==v['expected_source_sha256'] and v['expected_source_sha256']!=raw['request']['expected_source_sha256'],'Actual changed saved SHA required')
    require(raw.get('after_assignment')==raw.get('save_snapshots',{}).get('before'),'Complete assigned/before-Save snapshot required')
    return 'read_saved'

def historical_bundle(raw,v):
    """Reconstruct the existing first pair authority without reading old target bytes.
    All original semantic validators are reused; only the current target file pin
    is rebound after the already-validated explicit native Save int0.
    """
    q=raw['request'];pair,pin=definition.read_pin(q['current_context_receipt_path'],q['current_context_receipt_sha256'])
    require(pair.get('scope')==tool.reader.SCOPE and pair.get('status')=='observed' and pair.get('phase')=='finished' and pair.get('read_only')is True and all(pair.get(k)is True for k in tool.reader.FLAGS),'Recovery currently requires the completed original pair reader')
    for key in ('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','Import_attempted','tool_creation_attempted','tool_assignment_attempted','automatic_replay','physical_tool_qualified','native_units_verified','cutting_conditions_qualified','island_geometry_verified','production_qualified'):
        require(pair.get(key)is False,'Original pair action/qualification differs: '+key)
    definition.creator.clean(pair);current._check_request(q,pair['request'])
    require(pair['before']==pair['after']==raw['before']['inventory'] and pair['parameters']==raw['before']['parameters'],'Original pair/partial baseline differs')
    for label in ('before','after'):
        diag=pair[label+'_diagnostic'];require(diag.get('capture_complete')is True and diag.get('state')==pair['after'],'Complete original paired inventory required')
    require(pair['source_before_sha256']==pair['source_after_sha256']==q['expected_source_sha256'] and pair['after_cleanup_identity']==dict(document=pair['after']['document'],saved_file_sha256=q['expected_source_sha256']),'Original pair cleanup/source differs')
    pv=pair['request'];recovered=definition._read_recovery(pv['definition_recovery_receipt_path'],pv['definition_recovery_receipt_sha256'])
    saved,save_pin=definition.read_pin(pv['definition_save_receipt_path'],pv['definition_save_receipt_sha256'])
    transition=definition.verify_saved_transition(recovered,saved,process_id=v['process_id'],expected_document_path=v['expected_document_path'],expected_source_sha256=saved['after']['saved_file_sha256'],expected_feature_native_id=v['expected_feature_native_id'])
    old=recovered['old'];sketch=definition.definition_sketch_baseline(recovered);prior_source=saved['after']['saved_file_sha256']
    sketch.update(features=deepcopy(recovered['expected_inventory']['sw_reference']['feature_tree']),saved_file_sha256=prior_source,needs_save=False)
    d=dict(scope=definition.SCOPE,process_id=v['process_id'],expected_document_path=v['expected_document_path'],expected_source_sha256=prior_source,expected_feature_native_id=v['expected_feature_native_id'],origin_kind=recovered.get('origin_kind','recovery'),evidence=recovered['receipt_pin'],save_pin=save_pin,saved_transition=transition,expected_inventory=recovered['expected_inventory'],current_sketch_baseline=sketch,spec=recovered['spec'],request=old['request'],creator=old,sketch=recovered['sketch'])
    d['recovered']=recovered;d['marker']=Path(v['expected_document_path']).parent/('feature_gop_'+_digest(dict(scope=definition.SCOPE,target=definition.creator.canonical(v['expected_document_path']),creator_sha256=recovered['creator_pin']['sha256'],feature_id=v['expected_feature_native_id']))+'.json')
    from scripts.sw_cam_pocket_gop_evidence import read_gop_receipt
    plan=read_gop_receipt(pv['definition_gop_receipt_path'],pv['definition_gop_receipt_sha256'],d,v['expected_operation_native_ids'])
    post,_=definition.read_pin(pv['definition_gop_save_receipt_path'],pv['definition_gop_save_receipt_sha256'])
    verified=definition._verify_saved_plan_transition(d,plan,post,q['expected_source_sha256'])
    require(verified['saved_plan_inventory']==pair['after'],'Historical saved plan differs from original pair')
    roots=current._root_pins(pair,pin)
    required=recovered['pins']+[recovered['creator_pin'],recovered['marker_pin'],recovered['receipt_pin'],save_pin,plan['gop_pin'],plan['marker_pin'],dict(path=pv['definition_gop_save_receipt_path'],sha256=pv['definition_gop_save_receipt_sha256'])]
    root_keys={(definition.creator.canonical(x['path']),x['sha256'])for x in roots}
    require(all((definition.creator.canonical(x['path']),x['sha256'])in root_keys for x in required if not definition.creator.same_path(x['path'],v['expected_document_path'])),'Historical pair omitted authority pins')
    d['expected_source_sha256']=q['expected_source_sha256'];d['current_sketch_baseline']['saved_file_sha256']=q['expected_source_sha256']
    d=current._compact(d);d['pins']=current._pins(roots+[dict(path=v['expected_document_path'],sha256=q['expected_source_sha256'])])
    d=definition.after_native_save_source(d,v['expected_source_sha256'],native_return_value=raw['native_save']['native_return_value'])
    d['saved_transition']['document']=deepcopy(pair['after']['document'])
    return dict(context=d,state=deepcopy(raw['before']['inventory']),parameters=deepcopy(raw['before']['parameters']),receipt_pin=pin,root_pins=roots,lineage_pins=[pin],pins=d['pins'])

def merged_pins(*groups):
    merged={}
    for pin in (p for group in groups for p in group):
        key=definition.creator.canonical(pin['path'])
        require(key not in merged or merged[key]['sha256']==pin['sha256'],'Conflicting recovery evidence pins')
        merged.setdefault(key,deepcopy(pin))
    return current._pins(list(merged.values()))

def save_bundle_without_duplicate_roots(bundle):
    # Existing Save combines root_pins + extra before its 64-pin bound. Remove
    # only roots that this very same full context already supplies as extras.
    out=deepcopy(bundle);d=out['context'];excluded={definition.creator.canonical(p['path'])for p in out.get('lineage_pins',[out['receipt_pin']])}
    extra=[p for p in d['pins']if not definition.creator.same_path(p['path'],d['expected_document_path']) and definition.creator.canonical(p['path'])not in excluded]
    keys={(definition.creator.canonical(p['path']),p['sha256'])for p in extra}
    context_keys={(definition.creator.canonical(p['path']),p['sha256'])for p in d['pins']}
    original_keys={(definition.creator.canonical(p['path']),p['sha256'])for p in bundle['root_pins']}
    require(original_keys<=context_keys,'Full guarded context omitted a root pin')
    out['root_pins']=[p for p in out['root_pins']if (definition.creator.canonical(p['path']),p['sha256'])not in keys]
    final=current._pins(out['root_pins']+extra)
    require(len(final)<=61,'Leave bounded slots for final receipt, target and predecessor')
    final_keys={(definition.creator.canonical(p['path']),p['sha256'])for p in final}
    require(original_keys|keys==final_keys,'Save input dedup changed canonical authority union')
    return out

def prepare(v):
    shape(v);pins=[];values=[]
    for prefix in ('partial_receipt','original_marker','cli_result','executor_exit'):
        value,pin=definition.read_pin(v[prefix+'_path'],v[prefix+'_sha256']);values.append(value);pins.append(pin)
    raw,marker,cli,ex=values;branch=validate_partial(raw,v);validate_interruption(v,raw,marker,cli,ex);check_executors(ex)
    require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Actual current target source differs')
    bundle=current.load_current_baseline(raw['request'])if branch=='save_once'else historical_bundle(raw,v)
    require(dict(inventory=bundle['state'],parameters=bundle['parameters'])==raw['before'],'Original complete baseline differs')
    recipe,rp=definition.read_pin(raw['request']['recipe_path'],raw['request']['recipe_sha256']);require(recipe==raw['recipe'],'Original recipe differs')
    holder=tool.read_holder_recipe(raw['request']['holder_file_path'],raw['request']['holder_file_sha256'],raw['request']['holder_recipe_path'],raw['request']['holder_recipe_sha256']);require(holder==raw['holder_recipe'],'Original holder evidence differs')
    target=v['expected_document_path'];historical=[]
    for pin in raw['evidence_pins']:
        if definition.creator.same_path(pin['path'],target):
            require(pin['sha256']==raw['initial_source_sha256'],'Historical target source differs');historical.append(pin)
        else:pins.append(pin)
    require(historical,'Original target pin required')
    bundle['context']['pins']=merged_pins(bundle['context']['pins'],pins,[dict(path=__file__,sha256=_file_hash(__file__))]);definition.verify_files(bundle['context'])
    receipt=Path(v['receipt_path']);once=Path(target).parent/('current_pair_tool_recovery_'+_digest(dict(scope=SCOPE,target=definition.creator.canonical(target),original_marker=definition.creator.canonical(v['original_marker_path'])))+'.json')
    for path in (receipt,once):
        require(path.is_absolute() and path.suffix.lower()=='.json' and path.parent.is_dir() and not path.exists() and not path.is_symlink(),'Fresh recovery receipt/once required; no retry')
        require(not any(definition.creator.same_path(str(path),p['path'])for p in bundle['context']['pins']),'Recovery output aliases protected evidence')
    require(receipt!=once,'Separate recovery receipt/once required')
    save_bundle=save_bundle_without_duplicate_roots(bundle)
    return dict(bundle=bundle,save_bundle=save_bundle,recipe=recipe,recipe_pin=rp,holder=holder,proposed=tool.serial.validate_recipe(recipe),raw=raw,branch=branch,exit_observation=ex,receipt=receipt,marker=once,request=deepcopy(v),consumed=False)

class Journal(tool.Journal):
    def marker_state(self):
        value=super().marker_state();value.update(scope=SCOPE,partial_receipt_pin=deepcopy(self.report['partial_receipt_pin']));return value
    def pending(self,label):
        require(label=='SaveActiveDocument' and self.report['branch']=='save_once','Recovery can only perform one previously unattempted Save')
        super().pending(label)

class Backend(tool.Backend):
    def create(self,*a):raise ValueError('Recovery never creates tools')
    def assign_selected(self,*a):raise ValueError('Recovery never assigns tools')
    def property(self,*a):raise ValueError('Recovery never writes tool properties')
    def attach_holder(self,*a):raise ValueError('Recovery never attaches holders')
    def files(self):
        super().files();check_executors(self.data['exit_observation'])
    def start(self):
        self.files();self.expected_document=self.identity()
        expected=deepcopy(self.data['raw']['after_assignment']['inventory']['document'])
        if self.data['branch']=='read_saved':expected['needs_save']=False
        require(self.expected_document==expected,'Exact observed post-assignment dirty/document state required')
        addin=tool._member(self.sw,'GetAddInObject',self.clsid);require(addin is not None,'CAM must already be loaded')
        self.app=tool._typed(tool._member(addin,'GetCWApp'),'ICWApp4',self.typelib_path)
        require(self.identity()==self.expected_document,'Bootstrap changed current target')
        self.session=tool.reader.CamMessageSession(self.app,self.typelib_path);self.session.__enter__();self.events()
        with self.guard()as g:
            doc=g.typed(g.read(self.app,'IGetActiveDoc'),'ICWDoc3');machine=g.typed(g.read(g.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            self.native=dict(doc=doc,machine=machine);self.doc=doc
            self.crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4');self.save_app=g.typed(self.app,'ICWApp')
    def bind_existing(self):
        catalogue=self.initial_tools();tid=self.args['expected_tool_native_id']
        require(tid in self.handles,'Exact original created tool absent from current catalogue')
        self.new_id,self.new_tool=tid,self.handles[tid]
        return catalogue

def normalized_after(raw,after,v):
    normalized=deepcopy(after);normalized['inventory']['saved_file_sha256']=raw['before']['inventory']['saved_file_sha256']
    tool.verify_pair_delta(raw['before'],normalized,selected_id=v['selected_operation_native_id'],new_tool_id=v['expected_tool_native_id'])
    require(type(after['inventory']['document']['needs_save'])is bool,'Exact current dirty boolean required')
    expected=raw.get('after_assignment')
    if expected is not None:
        require(current._without_save_fields(expected)==current._without_save_fields(after),'Fresh assigned state differs from completed original observation')
        dirty=False if raw['Save_attempted']else expected['inventory']['document']['needs_save']
        require(after['inventory']['document']['needs_save']is dirty,'Unexpected recovery dirty transition')
    return after

def restore_saved_context(r,data,after,persist):
    raw=data['raw'];bundle=data['bundle'];d=bundle['context'];source=raw['request']['expected_source_sha256']
    require(current._without_save_fields(raw['save_snapshots']['before'])==current._without_save_fields(after),'Fresh saved state differs from original before Save')
    r['native_save']=deepcopy(raw['native_save']);r['native_save'].update(after=current._without_save_fields(after),save_readback_verified=True)
    r['save_snapshots']=dict(before=deepcopy(raw['save_snapshots']['before']),after=deepcopy(after))
    r['saved_file_sha256_after_native_return']=d['expected_source_sha256'];r['model_saved']=True;r['save_readback_verified']=True
    identity={k:deepcopy(data['request'][k])for k in current.IDENTITY_KEYS}
    roots=merged_pins(bundle['root_pins'],[p for p in d['pins']if not definition.creator.same_path(p['path'],d['expected_document_path'])])
    payload=dict(scope=current.SCOPE,identity=identity,capture_context=current._compact(d),snapshot=deepcopy(after),state_sha256=_digest(after),root_pins=roots,predecessor_pin=deepcopy(bundle['receipt_pin']),limitations=deepcopy(current.LIMITS),source_transition=dict(before_sha256=source,after_sha256=d['expected_source_sha256'],native_return_value=0))
    r['current_context']=payload;r['save_provenance']=dict(kind='original_returned_save_then_fresh_readback',partial_receipt_pin=deepcopy(r['partial_receipt_pin']));persist()

def run_backend(backend,journal,data):
    r=journal.report;raw=data['raw'];v=data['request'];assigned=list(raw['protected_tools_before'])
    try:
        journal.claim();backend.start();catalogue=backend.bind_existing();tool.factory.verify_catalogue(raw['initial_catalogue'],catalogue,v['expected_tool_native_id'])
        require(backend.created_classification()==raw['factory_classification'],'Actual existing tool classification differs')
        after=normalized_after(raw,backend.capture_current('recovery_before'),v);r['before_recovery']=deepcopy(after)
        candidate=backend.candidate('recovery_before');require(candidate==raw['configured_candidate'],'Actual configured tool profile differs');tool.geometry.verify_candidate(candidate,data['recipe'],data['holder'])
        observed={tid:backend.full_existing(int(tid),'recovery_before')for tid in assigned};require(observed==raw['protected_tools_before'],'Protected original tool/holder changed');r['protected_tools_before']=observed;journal.persist()
        if data['branch']=='save_once':
            def save():
                value=backend.save();journal.returned('SaveActiveDocument',value);return value
            saved=current.save_current_baseline(r,data.get('save_bundle',data['bundle']),after,capture=backend.capture_current,guard=backend.boundary,claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,adopt_context=backend.adopt_context)
            r['current_context']=saved['payload'];r['model_saved']=True
        else:
            final=normalized_after(raw,backend.capture_current('recovery_after'),v);require(final==after,'Saved recovery paired readback changed');restore_saved_context(r,data,final,journal.persist)
        final_candidate=backend.candidate('recovery_final');require(final_candidate==candidate,'Recovery/Save changed full candidate profile');r['final_candidate']=final_candidate
        protected={tid:backend.full_existing(int(tid),'recovery_final')for tid in assigned};require(protected==observed,'Recovery/Save changed protected tools');r['protected_tools_saved']=protected
        tool.factory.verify_catalogue(raw['initial_catalogue'],backend.catalogue(),v['expected_tool_native_id'])
        backend.close();backend.runtime_check();document=backend.identity();require(document==backend.expected_document and document['needs_save']is False,'Cleanup changed current clean document');backend.files()
        require(tool.reader.shared.event_health(r['messages'],active=False)==0,'Clean recovery message teardown required')
        r['after_cleanup_identity']=dict(document=deepcopy(document),saved_file_sha256=backend.d['expected_source_sha256'])
        r.update(status='review_required',phase='finished',selected_assignment_verified=True,original_one_tool_creation_observed=True,**{k:True for k in tool.ACCEPTANCE})
    except Exception as error:r.update(status='uncertain',failed_phase=r.get('phase'),phase='finished',issue=_error(error),reason=str(error),**{k:False for k in tool.ACCEPTANCE})
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain',cleanup_error=_error(error),**{k:False for k in tool.ACCEPTANCE})
        r['phase']='finished';journal.persist()
    return r

def run_tool(sw,clsid,tlb,v,*,prepared=None,runtime_check=lambda:None,_backend_factory=Backend):
    data=prepared if prepared is not None else prepare(v)
    require(data.get('consumed')is False and data['request']==v,'Exact fresh recovery preparation required');data['consumed']=True
    abi=tool.preflight(tlb);d=data['bundle']['context']
    d['pins']=merged_pins(d['pins'],[abi['generated_pin'],dict(path=tlb,sha256=_file_hash(tlb))]);data['save_bundle']=save_bundle_without_duplicate_roots(data['bundle']);definition.verify_files(d);check_executors(data['exit_observation']);runtime_check()
    r=dict(scope=SCOPE,status='prepared',phase='prepared',request=deepcopy(v),branch=data['branch'],source_path=v['expected_document_path'],initial_source_sha256=v['expected_source_sha256'],receipt_path=str(data['receipt']),partial_receipt_pin=dict(path=v['partial_receipt_path'],sha256=v['partial_receipt_sha256']),original_marker_pin=dict(path=v['original_marker_path'],sha256=v['original_marker_sha256']),current_baseline_receipt_pin=deepcopy(data['bundle']['receipt_pin']),new_tool_native_id=v['expected_tool_native_id'],actions={},evidence_pins=deepcopy(d['pins']),mutation_attempted=False,tool_creation_attempted=False,assignment_attempted=False,property_writes_attempted=False,holder_assignment_attempted=False,Save_attempted=False,model_saved=False,save_readback_verified=False,GOP_attempted=False,GTP_attempted=False,Import_attempted=False,automatic_replay=False,automatic_defaults_qualified=False,production_qualified=False,**{k:False for k in tool.ACCEPTANCE})
    _write_receipt(data['receipt'],r,create=True);journal=Journal(r,data['receipt'],data['marker']);backend=_backend_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check,abi)
    return run_backend(backend,journal,data)

revoke=tool.revoke
