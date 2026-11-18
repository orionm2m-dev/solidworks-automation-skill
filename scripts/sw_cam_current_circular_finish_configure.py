"""One saved ordinary-circle Finish configuration; existing setters/context, no generation."""
from copy import deepcopy
from pathlib import Path
import json,math,re
from scripts import sw_cam_current_circular_finish as creation
from scripts import sw_cam_saved_floor_wall_configure as setters
from scripts import sw_cam_current_finish_configuration_delta as delta
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _error
require=delta.require;exact=delta.exact
SCOPE='CURRENT_ORDINARY_CIRCULAR_FINISH_CONFIGURATION_V1'
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','creation_receipt_path','creation_receipt_sha256','recipe_path','recipe_sha256','receipt_path','qualification_only','message_policy'}

def binding(v):return{k:deepcopy(x)for k,x in v.items()if k!='receipt_path'}
def marker_path(v):return Path(v['expected_document_path']).parent/('configure_circle_finish_'+_digest(dict(scope=SCOPE,binding=binding(v)))+'.json')
def outputs(v,pins):
    out=Path(v['receipt_path']);marker=marker_path(v);protected={Path(v['expected_document_path']).resolve(),*(Path(x['path']).resolve()for x in pins)}
    for p in(out,marker):require(p.is_absolute()and p.parent.is_dir()and p.suffix.lower()=='.json'and not p.exists()and not p.is_symlink()and p.resolve()not in protected,'Fresh distinct result/marker required')
    require(out.resolve()!=marker.resolve(),'Output aliases marker');return str(out),str(marker)

def validate(v):
    require(type(v)is dict and set(v)==KEYS and v['qualification_only']is True and v['message_policy']=='vendor_default','Exact qualification-only request required')
    require(type(v['process_id'])is int and v['process_id']>0 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact owner lifetime required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact lowercase digest required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Explicit absolute path required')
    from scripts import sw_cam_current_circular_finish_configuration_authority as authority
    a=authority.load_completed(v['creation_receipt_path'],v['creation_receipt_sha256'],process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=v['expected_source_sha256'])
    recipe,rp=read_pin(v['recipe_path'],v['recipe_sha256']);delta.validate_recipe(recipe,a['state'],a['operation_id'],a['feature_id'])
    from scripts import sw_cam_current_finish_configuration_context as native
    dependencies=(__file__,delta.__file__,authority.__file__,native.__file__,setters.__file__,delta.fields.__file__,delta.numeric.__file__,native.creation.__file__,native.continuation.__file__,native.planes.__file__,native.nc_reader.__file__,native.complete_guard.__file__)
    pins=list(a['pins'])+[rp]+[creation.partial._filepin(x)for x in dependencies]
    unique={}
    for p in pins:
        observed=creation.partial._observed_pin(p);key=str(Path(observed['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==observed['sha256'],'Conflicting immutable evidence');unique[key]=observed
    pins=list(unique.values());out,marker=outputs(v,pins)
    return dict(authority=a,state=deepcopy(a['state']),recipe=recipe,recipe_pin=rp,candidate=deepcopy(a['state']['parameter_batch']['candidate_tool']),pins=pins,output=out,marker=marker,addin_clsid=a['addin_clsid'],definition_mode=a['definition_mode'])

_ISSUER=object()
class _Prepared:
    def __init__(self,v,data,pins):self.issuer=_ISSUER;self.v=deepcopy(v);self.data=deepcopy(data);self.pins=deepcopy(pins);self.used=False;self.digest=self.fingerprint()
    def fingerprint(self):return _digest(dict(v=self.v,data=self.data,pins=self.pins))
def _prepare_invocation(v,*,runtime_check):
    runtime_check();data=validate(v);pins=[creation.partial._observed_pin(p)for p in data['pins']]+[creation.partial._observed_pin(dict(path=v['expected_document_path'],sha256=v['expected_source_sha256']))];runtime_check();return _Prepared(v,data,pins)
def consume(bundle,v,runtime_check):
    require(type(bundle)is _Prepared and bundle.issuer is _ISSUER and bundle.used is False,'Private unused validated bundle required');bundle.used=True;require(exact(bundle.v,v)and bundle.fingerprint()==bundle.digest,'Prepared input changed');runtime_check()
    for p in bundle.pins:creation.partial._observed_pin(p)
    require(outputs(v,bundle.data['pins'])==(bundle.data['output'],bundle.data['marker']),'Output changed');runtime_check();return bundle.data

def action_names(recipe):
    oid=str(recipe['row']['operation_native_id']);return ['field:'+oid+':link_to_tool','SetTool:'+oid]+['field:'+oid+':'+c['field']for c in recipe['row']['changes']if c['field']!='link_to_tool']+['SaveActiveDocument']
class Journal(setters.Journal):
    def marker_state(self):return dict(scope=SCOPE,status=self.report['status'],phase=self.report['phase'],binding=self.report['binding'],authority_pin=self.report['authority_pin'],recipe_pin=self.report['recipe_pin'],receipt_path=str(self.receipt),receipt_sha256=_file_hash(self.receipt),automatic_replay=False)

def run_once(backend,journal,data,v):
    r=journal.report;recipe=data['recipe'];row=recipe['row']
    def capture(label):
        r['phase']=label;detail=dict(label=label,state={},capture_complete=False);r['captures'].append(detail);journal.persist();state=backend.capture(label,detail['state']);require(all(state.get(k)is True for k in('capture_complete','extended_capture_complete','parameter_capture_complete')),'Complete fresh full snapshot required');detail.update(state=deepcopy(state),capture_complete=True);r[label]=deepcopy(state);journal.persist();return state
    def set_one(change):
        name='field:'+str(row['operation_native_id'])+':'+change['field'];journal.action(name);observed=backend.set_change(row,change,pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value));r['actions'][name]['immediate_readback']=deepcopy(observed);journal.persist()
    try:
        journal.create();backend.start();before=capture('before');require(delta.circular.circular_state_equal(before,data['state']),'Fresh saved30 differs');delta.validate_recipe(recipe,before,row['operation_native_id'],row['feature_native_id']);before_planes=deepcopy(r['plane_observations']['before']);backend.boundary();journal.claim()
        changes={c['field']:c for c in row['changes']};set_one(changes['link_to_tool']);expected_unlinked=deepcopy(before[delta.EXTRA]['operation_observation']);expected_unlinked['modes']['nc']['LinkToTool']=False
        with backend.selected_snapshot('unlinked_new_finish'):unlinked=backend.observe_target(row)
        require(exact(unlinked,expected_unlinked),'Unlink changed unrelated selected fields');name='SetTool:'+str(row['operation_native_id']);journal.action(name);backend.assign(row,pending=lambda:journal.pending(name),returned=lambda value:journal.returned(name,value))
        with backend.selected_snapshot('assigned_new_finish'):assigned=backend.observe_target(row)
        r['assignment_observation']=dict(before=unlinked,after=assigned,proof=setters.verify_assignment(unlinked,assigned,row));journal.persist()
        for original in row['changes']:
            if original['field']=='link_to_tool':continue
            change=deepcopy(original)
            if change['field']in('spindle','xy_feed','leadin_feed'):change['expected']=deepcopy(assigned['modes']['nc'][{'spindle':'GetSpndlSpeed','xy_feed':'XYFeed','leadin_feed':'leadin_feed'}[change['field']]])
            set_one(change)
        compact=backend.compact_before_save();r['compact_configuration_proof']=delta.verify_compact(before,compact,recipe,before_planes);r['parameters_readback_verified']=True;journal.persist();backend.boundary()
        journal.action('SaveActiveDocument');r['save_stage']={}
        def returned(value):journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(int,bool,float,str)or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha,save_returned_zero=True);journal.persist();saved=capture('saved')
        r['saved_configuration_proof']=delta.verify_full(before,saved,recipe,saved_source=sha);require(exact(compact['new_circle'],saved[delta.EXTRA])and exact(compact['inventory']['operations'],saved['operations'])and exact(r['plane_observations']['saved'],before_planes),'Raw selected route/geometry/planes changed during Save')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True);journal.persist();backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,parameters_configured=True,configuration_saved=True,reason='ONE_ORDINARY_CIRCLE_FINISH_CONFIGURED_NO_GTP')
    except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r.get('phase'),phase='finished',issue=_error(exc),reason=str(exc),readback_verified=False,runtime_unchanged=False,configuration_saved=False,parameters_configured=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(exc),readback_verified=False,runtime_unchanged=False,configuration_saved=False,parameters_configured=False)
        journal.persist()
    return r

def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=None):
    data=consume(bundle,v,runtime_check);require(data['addin_clsid'].casefold()==clsid.casefold(),'Exact CAM registration required')
    from scripts.sw_cam_current_finish_configuration_context import Context,preflight
    abi=preflight(tlb,data['definition_mode']);abi.pop('setup_plane_class',None)
    r=dict(scope=SCOPE,status='error',phase='preflight',binding=binding(v),request=deepcopy(v),recipe=deepcopy(data['recipe']),recipe_pin=data['recipe_pin'],authority_pin=data['authority']['pin'],evidence_pins=data['pins'],receipt_path=v['receipt_path'],dispatch_marker_path=data['marker'],source_before_sha256=v['expected_source_sha256'],selected_operation_native_id=data['recipe']['row']['operation_native_id'],abi=abi,allowed_actions=action_names(data['recipe']),actions={},captures=[],plane_observations={},target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,reference_geometry_creation_attempted=False,operation_creation_attempted=False,save_attempted=False,model_saved=False,save_readback_verified=False,source_update_verified=False,parameters_configured=False,configuration_saved=False,readback_verified=False,runtime_unchanged=False,automatic_replay=False,automatic_rollback=False,production_qualified=False,machining_eligible=False,reopen_persistence_verified=False)
    j=Journal(data['output'],data['marker'],r);b=(_context_factory or Context)(sw,clsid,tlb,v,data,r,j.persist,runtime_check);result=run_once(b,j,data,v)
    try:runtime_check()
    except Exception as exc:return revoke_runtime(result,exc)
    return result

def revoke_runtime(r,error):
    r.update(status='uncertain'if r.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,configuration_saved=False,parameters_configured=False)
    if r.get('receipt_created')is True:
        p=Path(r['receipt_path']);old=json.loads(p.read_text(encoding='utf-8'));require(old.get('scope')==SCOPE and exact(old.get('binding'),r['binding']),'Only own receipt may be revoked');_write_receipt(p,r)
        if r.get('marker_created')is True:
            m=Path(r['dispatch_marker_path']);value=json.loads(m.read_text(encoding='utf-8'));require(value.get('scope')==SCOPE and exact(value.get('binding'),r['binding']),'Only own marker may be updated');value.update(status=r['status'],phase=r['phase'],receipt_sha256=_file_hash(p));_write_receipt(m,value)
    return r
