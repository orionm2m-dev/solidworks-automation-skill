"""Configurable one-shot serial flat-tool creation over a saved MILL context.

Uses the established native backend. A trusted completed-checkpoint provider is
required; this module does not infer authority from an arbitrary JSON snapshot.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_long_cut_tool_definition as existing
from scripts import sw_cam_exact_cutter_reuse as reuse
from scripts import sw_cam_long_cut_reconciliation as bounded
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_shared_holder_geometry import check_holder_pins
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error
try:
 from scripts import sw_cam_serial_flat_profile as geometry
except ImportError:
 import sw_cam_serial_flat_profile as geometry

common,group,prior,deep=existing.common,existing.group,existing.prior,existing.deep
FIELD_ORDER,TEXT_FIELDS=existing.FIELD_ORDER,existing.TEXT_FIELDS
SCOPE='SAVED_CONFIGURABLE_SERIAL_FLAT_TOOL_V1'
REUSE_POLICY_PIN=common._pin(reuse.__file__)
verify_catalogue=existing.verify_catalogue
verify_protected=existing.verify_protected
verify_candidate=geometry.verify_candidate

class NativeBackend(existing.NativeBackend):
 """No new native interface/member; keep the proved shared-session owner."""
 pass

class Journal(prior.Journal):
 def marker_state(self):return dict(super().marker_state(),scope=SCOPE)

def catalogue_authority(loaded):
 rows=loaded['serial_flat_catalogue']
 require(type(rows)is list and 1<=len(rows)<=128,'Bounded actual saved catalogue required')
 ids=[r['native_id']for r in rows]
 require(all(type(v)is int and v>0 for v in ids)and len(set(ids))==len(ids),'Unique native catalogue IDs required')
 return deepcopy(rows)

def validate_recipe(recipe):
 require(type(recipe)is dict and set(recipe)=={'target','identity','profile_basis','source_pins','accepted_identity_aliases'},
  'Exact configurable serial-flat recipe required')
 geometry.validate_target(recipe['target'])
 require(recipe['profile_basis']==geometry.BASIS,'Conservative representation must remain explicit')
 require(type(recipe['identity'])is dict and set(recipe['identity'])==TEXT_FIELDS,'Exact bounded serial identity fields required')
 require(all(type(v)is str and 0<len(v)<=1000 and '\x00'not in v for v in recipe['identity'].values()),'Bounded identity text required')
 require(type(recipe['accepted_identity_aliases'])is list and len(recipe['accepted_identity_aliases'])<=8,'Bounded explicit aliases required')
 reuse.identity_key(recipe['identity'])
 for identity in recipe['accepted_identity_aliases']:reuse.identity_key(identity)
 require(type(recipe['source_pins'])is list and 1<=len(recipe['source_pins'])<=8,'Pinned manufacturer and envelope sources required')
 common._check(recipe['source_pins'])
 return dict(recipe['target'],**recipe['identity'])

def marker_path(source,sha):
 return common.local_evidence_root()/('serial_flat_tool_'+prior._digest(
  dict(scope=SCOPE,source=common._key(source),source_sha256=sha))+'.json')

def guard_constructor_preflight(p,loaded,typelib):
 return existing.guard_constructor_preflight(p,loaded,typelib)

PARAMS={'process_id','expected_document_path','expected_source_sha256','expected_configuration','addin_clsid',
 'module_sha256','qualification_only','acknowledge_disposable_copy','message_policy','receipt_path','saved_cl_path',
 'context_receipt_path','context_receipt_sha256','recipe_path','recipe_sha256','source_backup_path','source_backup_sha256'}

def prepare(request,*,context_provider=None):
 require(type(request)is dict and set(request)=={'action','params'}and request['action']=='create_serial_flat_tool',
  'Only one tool-only create/configure/save action allowed')
 require(callable(context_provider),'Explicit trusted completed-context provider required; source is not yet sealed')
 p=deepcopy(request['params']);require(type(p)is dict and set(p)==PARAMS,'Exact serial-flat request required')
 require(type(p['process_id'])is int and 0<p['process_id']<2**32,'Positive exact owned PID required')
 for name,value in p.items():
  if name.endswith('sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
  if name.endswith('path'):require(type(value)is str and Path(value).is_absolute(),'Absolute input/output path required')
 require(p['module_sha256']==prior._file_hash(__file__)and p['qualification_only']is True and p['acknowledge_disposable_copy']is True
  and p['message_policy']=='vendor_default','Exact qualified one-tool request required')
 require(type(p['addin_clsid'])is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact native registration required')
 require(type(p['expected_configuration'])is str and p['expected_configuration'],'Exact saved configuration required')
 require(p['expected_source_sha256']==prior._file_hash(p['expected_document_path'])
  ==p['source_backup_sha256']==prior._file_hash(p['source_backup_path']),'Current source and immutable backup must match')
 require(common._key(p['source_backup_path'])!=common._key(p['expected_document_path']),'Independent immutable source backup required')
 # Provider repeats its complete terminal contract, including the two native
 # feature additions. It must not synthesize an inventory from planned curves.
 supplied=context_provider(deepcopy(p))
 require(type(supplied)is dict and set(supplied)=={'loaded','registration','typelib','interface_audit','provider_pin'},
  'Exact verified provider result required')
 loaded=deepcopy(supplied['loaded'])
 context_pin=common._pin(p['context_receipt_path'])
 require(context_pin['sha256']==p['context_receipt_sha256'] and group.exact(loaded['parent_pin'],context_pin),'Provider must bind this exact completed authority receipt')
 registration=supplied['registration'];typelib=supplied['typelib']
 require(p['addin_clsid'].casefold()==registration['clsid'].casefold(),'Exact native registration required')
 require(loaded['source_sha256']==p['expected_source_sha256']
  and common._key(loaded['state']['document']['path'])==common._key(p['expected_document_path']),'Current native context/source mismatch')
 require(loaded['state']['document']['needs_save']is False,'Saved input context required')
 snapshot=loaded['deep_loaded']['guide_parameters']['expected_parameters']
 deep.cl.contract(snapshot['binding'])
 require(len(snapshot['binding']['operations'])==17 and len(snapshot['parameters'])==8,'Current17/8 route required')
 require(group.exact(loaded['state']['operations'],snapshot['binding']['operations']),'Full inventory route differs from guide binding')
 require(loaded.get('native_feature_inventory_verified')is True,'Actual full feature inventory, including the two additions, required')
 catalogue=catalogue_authority(loaded)
 # These aliases are data adapters for the executed backend, not OSG authority.
 loaded['registration']=deepcopy(registration)
 loaded['long_cut_initial_catalogue']=deepcopy(catalogue)
 loaded['saved_cl_path']=p['saved_cl_path']
 loaded['source_backup_pin']=common._pin(p['source_backup_path'])
 loaded['pins']=common._merge(loaded['pins'],[common._pin(v)for v in (__file__,geometry.__file__,existing.__file__,existing.factory.__file__,prior.__file__,deep.__file__)])
 loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],[supplied['provider_pin']])
 require(1<=len(loaded['pins'])<=64,'Native live dependency closure exceeds shared64 limit; audit phase projection before dispatch')
 common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins']);common._check(loaded['bootstrap_export_pins'])
 loaded['native_guard_preflight']=guard_constructor_preflight(p,loaded,typelib)
 recipe,recipepin=bounded.read_pin(p['recipe_path'],p['recipe_sha256']);validate_recipe(recipe);check_holder_pins(loaded['holder_recipe'])
 loaded['offline_export_proof_pins']=common._merge(loaded['offline_export_proof_pins'],[context_pin,loaded['source_backup_pin'],recipepin,REUSE_POLICY_PIN,common._pin(bounded.__file__)],recipe['source_pins'])
 common._check(loaded['offline_export_proof_pins'])
 audit=existing.factory.audit_interfaces(typelib,loaded['generated_pin'])
 output=deep.cl._fresh_path(p['saved_cl_path']);receipt=Path(p['receipt_path']);common._local_receipt(receipt)
 marker=marker_path(p['expected_document_path'],p['expected_source_sha256']);context=receipt.with_suffix('.context.json')
 protected={common._key(v['path'])for key in ('pins','offline_export_proof_pins','bootstrap_export_pins')for v in loaded[key]}
 protected.update(map(common._key,[p['expected_document_path'],p['recipe_path'],p['source_backup_path'],p['context_receipt_path']]))
 paths=[receipt,marker,context,output]
 require(len(set(map(common._key,paths)))==4 and not protected.intersection(map(common._key,paths)),'Outputs alias protected evidence')
 require(all(v.is_absolute()and v.suffix.casefold()=='.json'and v.parent.is_dir()and not v.exists()and not v.is_symlink()for v in (receipt,marker,context)),'Fresh distinct receipts/marker required; no replay')
 audit['completed_context_provider_audit']=deepcopy(supplied['interface_audit'])
 return p,loaded,recipe,recipepin,registration,typelib,audit,marker



def run_backend(backend,journal,loaded,recipe,holder_recipe):
    """One creation/configuration/save attempt; never assign or regenerate.

    Caller must have checked source/PID/pins and a fresh receipt/marker before
    constructing the backend. This entry also rejects any prior attempted action.
    """
    r=journal.report;persist=journal.persist
    require(r.get('scope')==SCOPE and r.get('actions')=={} and not journal.claimed
        and not journal.marker.exists(), 'Fresh exact attempt required')
    proposed=validate_recipe(recipe);check_holder_pins(holder_recipe)
    initial_catalogue=catalogue_authority(loaded)
    try:
        backend.start();initial=backend.snapshot('initial');r['initial_observation']=initial;persist()
        require(group.exact(initial['route'],prior.expected_route(loaded)),'Actual initial route differs from saved authority')
        require(group.exact(initial['tools'],initial_catalogue), 'Actual prior catalogue changed')
        require(group.exact(initial['guide_snapshot'],loaded['deep_loaded']['guide_parameters']['expected_parameters']),
            'Actual current guide snapshot differs')
        candidates=backend.duplicate_candidates(recipe)
        common._check([REUSE_POLICY_PIN])
        r['duplicate_policy']=reuse.require_new_exact_cutter(initial_catalogue,candidates,recipe['identity'],recipe['target'],
            accepted_identity_aliases=recipe['accepted_identity_aliases']);persist()
        common._check([REUSE_POLICY_PIN])
        new_id=backend.create(lambda:journal.pending('AddNewTool3'),
            lambda v:journal.returned('AddNewTool3',v,pointer=True))
        forbidden={v['geometry']['native_id'] for v in loaded['state']['features']}
        forbidden|={v['native_id'] for v in loaded['state']['operations']+loaded['state']['feature_setups']+loaded['state']['operation_setups']}
        require(new_id not in forbidden,'Created tool ID collides with protected CAM object')
        r['new_tool_native_id']=new_id;persist()
        classification=backend.created_classification();r['created_classification']=deepcopy(classification);persist()
        require(type(classification['MillToolType']) is int and classification['MillToolType']==1
            and type(classification['MillToolSubType']) is int and classification['MillToolSubType']==3
            and prior.scalar_equal(classification['EndRadius'],0.),'Factory must already be flat/BOTH/zero-radius before configuration')
        verify_catalogue(initial['tools'],backend.catalogue(),new_id)
        for name in FIELD_ORDER:
            if name=='Protrusion':
                result=backend.attach_holder(holder_recipe['file_path'],lambda:journal.pending('SetFilePathForUserDefinedHolder'))
                journal.returned('SetFilePathForUserDefinedHolder',result)
                require(type(result) is int and result==0,'Strict holder reference HRESULT0 required')
                backend.refresh_dirty()
            before=backend.field(name);wanted=proposed[name];label='property:'+name
            row=dict(property=name,before=before,requested=wanted,readback_verified=False)
            r.setdefault('field_readbacks',[]).append(row);persist()
            if not prior.scalar_equal(before,wanted):
                result=backend.property(name,wanted,lambda label=label:journal.pending(label))
                journal.returned(label,result)
                require(result is None,'Property return must be None; actual readback proves value')
                backend.refresh_dirty()
            actual=backend.field(name);row['actual']=actual
            require(prior.scalar_equal(actual,wanted),'Immediate candidate readback differs: '+name)
            row['readback_verified']=True;persist()
        candidate=backend.candidate('configured');proof=verify_candidate(candidate,recipe,holder_recipe)
        configured=backend.snapshot('configured');verify_protected(initial,configured,new_id)
        r.update(configured_candidate=candidate,candidate_qualification=proof,configured_observation=configured);persist()
        def capture(label):
            if label=='before':backend.boundary();return dict(observation=configured,candidate=candidate)
            observation=backend.snapshot('save_'+label);verify_protected(initial,observation,new_id)
            actual=backend.candidate('save_'+label);verify_candidate(actual,recipe,holder_recipe)
            require(group.exact(candidate,actual),'Candidate changed during Save')
            r.update(final_candidate=actual,final_observation=observation,final_state=deepcopy(backend.current_state));persist()
            return dict(observation=observation,candidate=actual)
        def verify(value):require(group.exact(value,dict(observation=configured,candidate=candidate)),'Save projection changed')
        def save():
            value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage'])
            require(value!=r['initial_source_sha256'],'New tool must produce new saved bytes')
            r['saved_source_sha256']=value;persist();return value
        r['save_stage']={}
        prior.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        backend.finish()
        r.update(status='review_required',phase='finished',readback_verified=True,model_saved=True,
            exact_one_tool_created=True,assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,
            TechDB_write_attempted=False,prior_full_profiles_reused=True,prior_full_profiles_freshly_reverified=False,
            manufacturing_qualified=False,physical_collet_seating_verified=False,production_qualified=False)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',failed_phase=r.get('phase'),
            readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        persist()
    return r

def make_checkpoint(report,loaded):
 """Compact transition: reference the initial context once, never nest receipts."""
 return dict(initial_context_pin=deepcopy(report['loaded_context_pin']),
  source_sha256=report['saved_source_sha256'],source_path=report['source_path'],
  state=deepcopy(report['final_state']),document=deepcopy(report['source_transition']['document']),
  catalogue=deepcopy(report['final_observation']['tools']),
  guide_snapshot=deepcopy(report['final_observation']['guide_snapshot']),
  new_tool=deepcopy(report['final_candidate']),new_tool_native_id=report['new_tool_native_id'],
  recipe=deepcopy(report['recipe']),profile_qualification=deepcopy(report['candidate_qualification']),
  saved_cl=deepcopy(report['saved_cl']),registration=deepcopy(loaded['registration']))

def validate_terminal(r,initial=None):
 require(r.get('scope')==SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished'
  and r.get('readback_verified')is True and r.get('model_saved')is True and r.get('exact_one_tool_created')is True
  and r.get('phase_proofs_verified')is True and r.get('protected_fourteen_cl_verified')is True,'Completed saved generic tool receipt required')
 require(all(r.get(k)is False for k in ('assignment_attempted','GTP_attempted','GOP_attempted','TechDB_write_attempted')),
  'Tool-only scope required')
 allowed={'AddNewTool3','SetFilePathForUserDefinedHolder','SaveActiveDocument'}|{'property:'+v for v in FIELD_ORDER}
 require(set(r['actions'])<=allowed and all(v.get('returned')is True and v.get('pending')is False for v in r['actions'].values()),
  'No pending or unknown action permitted')
 creation=r['actions']['AddNewTool3']
 require(creation.get('returned_interface_pointer')is True,'Actual native factory pointer required')
 for name in ('SaveActiveDocument','SetFilePathForUserDefinedHolder'):
  a=r['actions'][name];require(a.get('native_return_type')=='int'and type(a.get('native_return_value'))is int and a['native_return_value']==0,
   'Strict completed native HRESULT0 required: '+name)
 proposed=validate_recipe(r['recipe'])
 require([v['property']for v in r['field_readbacks']]==list(FIELD_ORDER)
  and all(v['readback_verified']is True and prior.scalar_equal(v['requested'],proposed[v['property']])
   and prior.scalar_equal(v['actual'],proposed[v['property']])for v in r['field_readbacks']),'All thirteen actual scalar readbacks required')
 if initial is None:initial,_=bounded.read_pin(r['loaded_context_pin']['path'],r['loaded_context_pin']['sha256'])
 require(group.exact(r['initial_catalogue'],catalogue_authority(initial))
  and group.exact(r['initial_observation']['tools'],r['initial_catalogue'])
  and group.exact(r['initial_observation']['route'],prior.expected_route(initial))
  and group.exact(r['initial_observation']['guide_snapshot'],initial['deep_loaded']['guide_parameters']['expected_parameters']),
  'Initial native observations differ from pinned saved context')
 verify_protected(r['initial_observation'],r['configured_observation'],r['new_tool_native_id'])
 verify_protected(r['initial_observation'],r['final_observation'],r['new_tool_native_id'])
 require(group.exact(r['configured_candidate'],r['final_candidate']),'Configured and saved full profiles differ')
 expected={'AddNewTool3','SetFilePathForUserDefinedHolder','SaveActiveDocument'}
 for row in r['field_readbacks']:
  if not prior.scalar_equal(row['before'],proposed[row['property']]):expected.add('property:'+row['property'])
 require(set(r['actions'])==expected,'Exact changed-field action inventory required')
 for name,action in r['actions'].items():
  require(action.get('attempted')is True,'Completed action must have actual attempt evidence')
  if name.startswith('property:'):
   require(action.get('native_return_type')=='NoneType'and action.get('native_return_value')is None,'Strict property completion required')
 save=r['save_stage'];transition=r['source_transition'];sha=r['saved_source_sha256']
 require(save.get('save_readback_verified')is True and save.get('native_call_returned')is True
  and save.get('save_pending')is False and save.get('native_return_type')=='int'
  and type(save.get('native_return_value'))is int and save['native_return_value']==0
  and save['saved_file_sha256']==sha==transition['source_after_sha256']
  and transition['source_before_sha256']==r['initial_source_sha256']==initial['source_sha256']
  and sha!=r['initial_source_sha256']and type(transition['strict_save_return'])is int and transition['strict_save_return']==0,
  'Verified changed-source Save transition required')
 require(group.exact(save['before'],save['after'])and group.exact(save['after'],
  dict(observation=r['final_observation'],candidate=r['final_candidate'])),'Save readback differs from final evidence')
 reference=deepcopy(initial['state']);reference['saved_file_sha256']=sha;reference['document']['needs_save']=False
 require(group.exact(reference,r['final_state'])and group.exact(transition['document'],r['final_state']['document']),
  'Final full inventory changed beyond the saved source transition')
 require(type(r['new_tool_native_id'])is int and r['final_candidate']['full_tool']['tool_native_id']==r['new_tool_native_id'],'Final candidate identity differs')
 require(group.exact(r['candidate_qualification'],verify_candidate(r['final_candidate'],r['recipe'],r['holder_recipe'])),'Final profile proof differs')
 require(group.exact(r['saved_cl_comparison'],deep.cl.verify_all(initial['deep_loaded']['generated']['saved_cl'],r['saved_cl'])),
  'All fourteen complete saved CL streams must be preserved')
 require(group.exact(r['checkpoint'],make_checkpoint(r,initial))and prior._digest(r['checkpoint'])==r['checkpoint_digest'],
  'Compact saved checkpoint differs')
 existing.clean_events(r)
 return initial

def execute(sw,clsid,typelib,*,p,loaded,recipe,recipepin,audit,marker):
 args={k:p[k]for k in ('process_id','expected_document_path','expected_source_sha256','qualification_only',
  'acknowledge_disposable_copy','message_policy','expected_configuration')}
 context_path=Path(p['receipt_path']).with_suffix('.context.json')
 # Bound the actual context before any native action, using the established decoder.
 bounded.decode_bounded(json.dumps(loaded,ensure_ascii=False,allow_nan=False).encode('utf-8'))
 _write_receipt(context_path,loaded,create=True);context_pin=common._pin(context_path)
 r=dict(schema_version=1,scope=SCOPE,status='error',phase='prepared',request=deepcopy(p),
  source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],
  process_id=p['process_id'],receipt_path=p['receipt_path'],source_backup_pin=deepcopy(loaded['source_backup_pin']),
  module_pin=common._pin(__file__),profile_module_pin=common._pin(geometry.__file__),
  parent_pin=deepcopy(loaded['parent_pin']),recipe_pin=recipepin,recipe=deepcopy(recipe),
  holder_recipe=deepcopy(loaded['holder_recipe']),loaded_context_pin=context_pin,
  live_pins=deepcopy(loaded['pins']),offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
  bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),interface_audit=audit,
  native_guard_preflight=deepcopy(loaded['native_guard_preflight']),initial_catalogue=catalogue_authority(loaded),
  actions={},mutation_attempted=False,readback_verified=False,model_saved=False,phase_proofs_verified=False,
  protected_fourteen_cl_verified=False,assignment_attempted=False,GTP_attempted=False,GOP_attempted=False,
  TechDB_write_attempted=False,automatic_replay=False,automatic_rollback=False,production_qualified=False)
 _write_receipt(p['receipt_path'],r,create=True);journal=Journal(r,p['receipt_path'],marker)
 backend=NativeBackend(loaded,args,sw,clsid,typelib,r,journal.persist)
 run_backend(backend,journal,loaded,recipe,loaded['holder_recipe'])
 try:
  for key in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[key])
  common._check([context_pin])
  if r['readback_verified']is True:
   r['phase_proofs_verified']=True;r['checkpoint']=make_checkpoint(r,loaded)
   r['checkpoint_digest']=prior._digest(r['checkpoint']);validate_terminal(r,loaded)
 except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proofs_verified=False,terminal_issue=_error(exc))
 journal.persist()
 if journal.claimed:r['marker_pin']=common._pin(marker);journal.persist()
 return r

def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
 r,pin=bounded.read_pin(path,digest);initial=validate_terminal(r)
 require(type(process_id)is int and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
  and r['saved_source_sha256']==expected_source_sha256==prior._file_hash(expected_document_path),'Exact current saved source/PID required')
 require(r['module_pin']==common._pin(__file__)and r['profile_module_pin']==common._pin(geometry.__file__),'Frozen implementation changed')
 for key in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[key])
 mark,_=bounded.read_pin(r['marker_pin']['path'],r['marker_pin']['sha256'])
 require(mark['scope']==SCOPE and mark['readback_verified']is True and mark['saved_source_sha256']==expected_source_sha256
  and group.exact(mark['actions'],r['actions']),'Completed source-bound once marker differs')
 context=deepcopy(initial);saved=r['checkpoint']
 context.update(state=deepcopy(saved['state']),source_sha256=expected_source_sha256,
  serial_flat_catalogue=deepcopy(saved['catalogue']),long_cut_initial_catalogue=deepcopy(saved['catalogue']),
  serial_flat_tool=deepcopy(saved['new_tool']),serial_flat_tool_native_id=saved['new_tool_native_id'],
  registration=deepcopy(saved['registration']))
 context['state']['saved_file_sha256']=expected_source_sha256
 context['state']['document']=deepcopy(saved['document']);context['state']['document']['needs_save']=False
 context['deep_loaded']['guide_parameters']['document']=deepcopy(saved['document'])
 context['deep_loaded']['guide_parameters']['expected_parameters']=deepcopy(saved['guide_snapshot'])
 context['deep_loaded']['generated']['saved_cl']=deepcopy(saved['saved_cl'])
 oldparent=context['parent_pin'];oldmarker=context['group_marker_pin']
 context['pins']=common._merge([v for v in context['pins']if common._key(v['path'])!=common._key(oldparent['path'])],[pin])
 context['offline_export_proof_pins']=common._merge(context['offline_export_proof_pins'],[oldparent,oldmarker,r['marker_pin'],r['loaded_context_pin']])
 context.update(parent_pin=pin,group_marker_pin=deepcopy(r['marker_pin']),authority_kind='saved_serial_flat_tool_unassigned')
 context['current_context_sha256']=prior._digest(group.current_projection(context))
 bounded.decode_bounded(json.dumps(context,ensure_ascii=False,allow_nan=False).encode('utf-8'))
 return context

def dispatch_request(request,*,validate_only=False,context_provider=None):
 p,loaded,recipe,recipepin,registration,typelib,audit,marker=prepare(request,context_provider=context_provider)
 if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),
  native_guard_preflight=deepcopy(loaded['native_guard_preflight']),protected_operation_count=17,protected_path_count=14,
  profile_proposal=deepcopy(recipe['target']),native_profile_qualified=False)
 from scripts.sw_operation_guard import solidworks_operation_lock
 from scripts.sw_connect import connect_solidworks
 with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
  common._check(loaded['pins']);common._check(loaded['offline_export_proof_pins'])
  sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
  return execute(sw,registration['clsid'],typelib,p=p,loaded=loaded,recipe=recipe,recipepin=recipepin,audit=audit,marker=marker)

