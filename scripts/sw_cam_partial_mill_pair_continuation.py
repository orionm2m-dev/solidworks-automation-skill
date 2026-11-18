"""Continue only the unwritten suffix of a source-bound partial MILL configuration."""
from copy import deepcopy
from pathlib import Path
import math,re
from scripts import sw_cam_saved_floor_wall_configure as writer
from scripts import sw_cam_failed_configuration_depth_read as depth_reader
from scripts import sw_cam_partial_mill_pair_projection as projection
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import check_document_target
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
require=writer.require;exact=writer.exact;common=depth_reader.common
SCOPE='SAVED_FLOOR_WALL_CONFIGURATION_CONTINUATION_V1'
KEYS=depth_reader.KEYS|{'depth_read_receipt_path','depth_read_receipt_sha256'}


def marker_path(v):
    return Path(v['expected_document_path']).parent/('continue_mill_pair_'+_digest(dict(scope=SCOPE,failure_sha256=v['failure_receipt_sha256'],depth_read_sha256=v['depth_read_receipt_sha256'],source_sha256=v['expected_source_sha256']))+'.json')


def completed_marker(r,receipt_pin):
    """Pure expected marker content; the caller pins and checks the actual file."""
    v=r['request'];return dict(scope=SCOPE,status=r['status'],phase='consumed',failure_receipt_sha256=v['failure_receipt_sha256'],depth_read_receipt_sha256=v['depth_read_receipt_sha256'],source_before_sha256=r['source_before_sha256'],receipt_path=receipt_pin['path'],receipt_sha256=receipt_pin['sha256'],automatic_replay=False)


def validate_depth_read(r,pin,v,target,failure_pin,marker_pin):
    require(r.get('scope')==depth_reader.SCOPE and r.get('status')=='review_required'and r.get('phase')=='finished','Completed raw depth observation required')
    for key in('read_only','readback_verified','source_unchanged','runtime_unchanged'):require(r.get(key)is True,'Depth observation lacks '+key)
    for key in('mutation_attempted','save_attempted','GTP_attempted','parameter_setter_attempted','marker_created','continuation_authorized','full_configuration_reconciled'):require(r.get(key)is False,'Unexpected depth observation authority')
    require(not any(k in r for k in('issue','failed_phase','cleanup_error','runtime_error')),'Depth observation has unresolved error');clean_events(r)
    for key in depth_reader.KEYS-{'receipt_path'}:require(exact(r['request'][key],v[key]),'Depth observation request differs: '+key)
    require(common.same_path(r['receipt_path'],pin['path'])and r['source_sha256']==v['expected_source_sha256'],'Depth observation source/path differs')
    require(exact(r['failure_pin'],failure_pin)and exact(r['failure_marker_pin'],marker_pin)and exact(r['target'],target),'Exact failed attempt binding required')
    require(exact(r['before'],r['after'])and r['before']['complete']is True and exact(r['before']['target'],target),'Two matching complete raw depth triples required')
    require(exact(r['document_before'],r['document_after'])and type(r['document_before']['needs_save'])is bool,'Exact observed document identity required')
    values=r['before']['values'];require(values['complete']is True,'Complete depth values required')
    for key in('GetMachiningDepth','GetMachiningDepthValue'):
        item=values[key];value=item['value'];require(item['python_type']=='float'and type(value)is float and item['float_hex']==value.hex(),'Exact raw float and hexadecimal representation required');projection.fixed_double(value,target['requested_depth'])
    flag=values['GetOverrideMachiningDepth'];require(exact(flag,dict(value=True,python_type='bool',float_hex=None)),'Actual depth override True required')
    return deepcopy(values)


def _observed_file_pin(pin):
    from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes
    from scripts.sw_cam_stock_mesh_compare import _signature
    p=Path(pin['path']);require(p.is_absolute()and p.is_file()and not p.is_symlink(),'Direct regular evidence required')
    if p.suffix.lower()=='.json':_,observed=_receipt_bytes(str(p))
    else:
        canonical=p.resolve(strict=True);before=list(_signature(p.stat()));sha=_file_hash(p)
        require(not p.is_symlink()and p.resolve(strict=True)==canonical and list(_signature(p.stat()))==before,'Evidence changed while hashing')
        observed=dict(path=str(p),canonical_path=str(canonical),bytes=before[2],sha256=sha,identity=before)
    require(all(k in observed and observed[k]==value for k,value in pin.items()),'Evidence hash or metadata changed');return observed


def unique_pins(pins):
    out={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold()
        require(key not in out or out[key]['sha256']==pin['sha256'],'Conflicting immutable evidence')
        if key not in out or len(pin)>len(out[key]):out[key]=deepcopy(pin)
    return list(out.values())


def _fresh_outputs(v,data):
    out=Path(v['receipt_path']);marker=marker_path(v)
    require(out.is_absolute()and out.parent.is_dir()and out.suffix.lower()=='.json'and not out.exists()and not out.is_symlink()and not marker.exists()and not marker.is_symlink(),'Fresh result and unused continuation marker required')
    protected={Path(v['expected_document_path']).resolve(),*(Path(p['path']).resolve()for p in data['pins'])}
    require(out.resolve()!=marker.resolve()and out.resolve()not in protected and marker.resolve()not in protected,'Output aliases source/evidence')
    return marker


def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact partial continuation request required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit qualification only required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact process lifetime required')
    for k,value in v.items():
        if k.endswith('_sha256'):require(type(value)is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA required')
        if k.endswith('_path'):require(type(value)is str and Path(value).is_absolute(),'Absolute path required')
    failure,fp=read_pin(v['failure_receipt_path'],v['failure_receipt_sha256']);oldmarker,mp=read_pin(v['failure_marker_path'],v['failure_marker_sha256']);target=depth_reader.validate_failure(failure,oldmarker,v)
    data=writer.load_read_authority(failure['request'])
    require(exact(failure['recipe'],data['recipe'])and writer.writer.same(failure['before'],data['state']),'Original failed request baseline differs')
    require(exact(failure['target_observations']['before'],data['targets'])and exact(failure['draft_observations']['before'],data['draft']),'Original raw target/draft baseline differs')
    require(list(failure['actions'])==projection.prefix_actions(data['recipe']),'Only the established returned action prefix may continue')
    require(any(common.same_path(p['path'],writer.__file__)and p['sha256']==_file_hash(writer.__file__)for p in failure['evidence_pins']),'Original writer implementation differs')
    depth,dp=read_pin(v['depth_read_receipt_path'],v['depth_read_receipt_sha256']);triple=validate_depth_read(depth,dp,v,target,fp,mp)
    for p in depth['evidence_pins']:common.direct(p)
    prefix_targets=projection.expected_targets(data['targets'],data['recipe'],'prefix')
    data.update(failure=failure,failure_pin=fp,failure_marker_pin=mp,depth_read=depth,depth_read_pin=dp,depth_values=triple,prefix_targets=prefix_targets,prefix_state=writer.expected_configuration_state(data['state'],data['recipe'],data['candidate'],prefix_targets))
    data['pins']=unique_pins(data['pins']+[fp,mp,dp]+depth['evidence_pins']+[dict(path=p,sha256=_file_hash(p))for p in(__file__,projection.__file__,depth_reader.__file__,writer.__file__)])
    data['marker']=str(_fresh_outputs(v,data));data['output']=v['receipt_path'];data['evidence_pins']=deepcopy(data['pins']);return data


_PREPARED_ISSUER=object()
class _PreparedInvocation:
    __slots__=('_v','_data','_pins','_request_sha','_content_sha','_used','_issuer')
    def __init__(self,issuer,v,data,pins):
        require(issuer is _PREPARED_ISSUER,'Private invocation required');self._issuer=issuer;self._v=deepcopy(v);self._data=deepcopy(data);self._pins=deepcopy(pins);self._request_sha=_digest(v);self._used=False;self._content_sha=self._fingerprint()
    def _fingerprint(self):return _digest(dict(v=self._v,data=self._data,pins=self._pins,request_sha=self._request_sha))
    @property
    def addin_clsid(self):return self._data['lineage']['loaded']['addin_clsid']


def _prepare_invocation(v,*,runtime_check):
    require(callable(runtime_check),'Runtime guard required');runtime_check();data=validate(v)
    pins=[_observed_file_pin(p)for p in unique_pins(data['pins']+[dict(path=v['expected_document_path'],sha256=v['expected_source_sha256'])])]
    require(str(_fresh_outputs(v,data))==data['marker'],'Marker differs');runtime_check();return _PreparedInvocation(_PREPARED_ISSUER,v,data,pins)


def _consume_prepared(bundle,v,*,runtime_check):
    require(callable(runtime_check)and type(bundle)is _PreparedInvocation and bundle._issuer is _PREPARED_ISSUER and bundle._used is False,'Unused private prepared invocation required');bundle._used=True
    require(_digest(v)==bundle._request_sha and bundle._fingerprint()==bundle._content_sha,'Prepared request or authority changed');runtime_check()
    for p in bundle._pins:_observed_file_pin(p)
    require(str(_fresh_outputs(v,bundle._data))==bundle._data['marker'],'Marker changed');runtime_check();return bundle._data


class Context(writer.Context):
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        super().__init__(sw,clsid,tlb,v,data,report,persist,runtime_check)
        self.continuation=data;self.expected_route=deepcopy(data['prefix_state']);self._native_read_limit=20000
        self.data['recovery']={'expected_state':deepcopy(self.expected_route)}
    def start(self):
        actual=self.identity();expected=deepcopy(self.expected_route['document']);require(type(actual.get('needs_save'))is bool,'Strict observed dirty flag required');expected['needs_save']=actual['needs_save']
        require(exact(actual,expected),'Partial continuation document changed');self.data['recovery']['expected_state']['document']=deepcopy(actual);self.report['initial_partial_document']=deepcopy(actual);self.persist();return super().start()
    def assign(self,*a,**k):raise ValueError('Continuation cannot repeat tool assignment')
    def generate(self,*a,**k):raise ValueError('Continuation never generates')
    def insert(self,*a,**k):raise ValueError('Continuation never inserts')
    def verify_owned_identity_only(self):
        self.check();self.runtime_check();v=self.v;p=_process_identity(v['process_id'])
        require(p.get('alive')is True and p.get('process_id')==v['process_id']and p.get('create_time')==v['expected_process_create_time']and Path(p.get('executable','')).name.casefold()=='sldworks.exe','Exact process lifetime changed')
        pid=_member(self.sw,'GetProcessID');require(type(pid)is int and pid==v['process_id'],'Native PID changed');d=document_snapshot(self.sw)
        require(type(d)is dict and type(d.get('type'))is int and d['type']==1 and type(d.get('needs_save'))is bool,'Strict part identity required');check_document_target(d['path'],d['title'],expected_path=v['expected_document_path'],required=True)
        require(exact(d,self._guard_expected_document),'Native document identity changed');self.check();return d
    def guard_pins(self):
        pins=list(self.pins)+list(self.continuation['evidence_pins'])+list(self.append_plan['pins'])+[self.revision['cl_pin'],dict(path=writer.writer.__file__,sha256=self.revision['module_sha256'])]
        if self.request.get('prepare_receipt_path'):pins.append(dict(path=self.request['prepare_receipt_path'],sha256=self.request['prepare_receipt_sha256']))
        pins=unique_pins(pins);require(1<=len(pins)<=63,'Bounded full immutable evidence required');return pins
    def guard(self):
        require(getattr(self,'_capture_pin_scope',False)is False,'Dispatch forbidden inside readonly capture');expected=self.boundary();self._guard_expected_document=deepcopy(expected)
        return ScopedCamDispatchGuard(self.sw,self.tlb,process_id=self.v['process_id'],expected_document=expected,source_sha256=self.source,evidence_pins=self.guard_pins(),verify_evidence=self.verify_files,verify_owned_process=self.verify_owned_identity_only,check_events=self.check)
    def set_change(self,row,change,*,pending,returned):
        remaining=projection.remaining_changes(self.continuation['recipe']);require(exact(row,remaining)and change in remaining['changes'],'Only exact sealed suffix fields allowed')
        with self.guard()as g:
            owner,feature,interface,setter,mode,actual=self.field(row,change['field'],g.read,lambda raw,name:self.guarded_typed(g,raw,name),g._observe)
            require(exact(actual,change['expected']),'Immediate expected suffix field changed');new=change['new']
            def invoke():
                value=getattr(owner,'_'+interface+'__com__set_'+setter)(new)if mode=='property'else _member(owner,setter,*((feature,new)if mode=='feature'else tuple(new)if mode in('pair','depth_pair')else(new,)))
                returned(value);return value
            value=g.dispatch_once(invoke,persist_pending=pending)
        require(type(value)is int and value==0,'Exact suffix setter HRESULT0 required; no replay')
        with self.guard()as g:observed=self.field(row,change['field'],g.read,lambda raw,name:self.guarded_typed(g,raw,name),g._observe)[-1]
        name='field:'+str(row['operation_native_id'])+':'+change['field'];self.report['actions'][name]['raw_immediate_readback']=deepcopy(observed);self.persist()
        if change['field']in('first_depth','max_depth'):
            require(type(observed)is list and len(observed)==2 and observed[1]is False and new[1]is False,'Exact absolute depth pair required');projection.fixed_double(observed[0],new[0])
        else:require(exact(observed,new),'Immediate suffix readback differs')
        return observed


class Journal(writer.Journal):
    def marker_state(self):return completed_marker(self.report,dict(path=str(self.receipt),sha256=_file_hash(self.receipt)))


def action_names(recipe):
    row=projection.remaining_changes(recipe);return ['field:'+str(row['operation_native_id'])+':'+c['field']for c in row['changes']]+['SaveActiveDocument']


def checkpoint(data,state,targets,draft,phase):
    return projection.verify_checkpoint(data['state'],state,data['recipe'],data['candidate'],data['targets'],targets,data['draft'],draft,phase)


def run_once(backend,journal,data,v):
    r=journal.report
    def observe(label):
        detail=dict(label=label,capture_complete=False,state={});r['captures'].append(detail);r['phase']=label;journal.persist();actual=backend.capture(label,detail['state']);require(all(actual.get(k)is True for k in('capture_complete','parameter_capture_complete','extended_capture_complete')),'Complete full route snapshot required');detail.update(capture_complete=True,state=deepcopy(actual));r[label]=deepcopy(actual);journal.persist();return actual
    def targets(label):return r['target_observations'][label]
    def draft(label):return r['draft_observations'][label]
    try:
        journal.create();backend.start();before=observe('before');r['prefix_proof']=checkpoint(data,before,targets('before'),draft('before'),'prefix');r['partial_prefix_reconciled']=True;journal.persist();backend.boundary();journal.claim()
        row=projection.remaining_changes(data['recipe'])
        for change in row['changes']:
            name='field:'+str(row['operation_native_id'])+':'+change['field'];journal.action(name)
            observed=backend.set_change(row,change,pending=lambda name=name:journal.pending(name),returned=lambda value,name=name:journal.returned(name,value));r['actions'][name]['immediate_readback']=deepcopy(observed);journal.persist()
        configured=observe('configured');r['final_configuration_proof']=checkpoint(data,configured,targets('configured'),draft('configured'),'final');r['parameters_readback_verified']=True;journal.persist()
        backend.boundary();journal.action('SaveActiveDocument');r['save_stage']=dict(before_state_reused_from='configured',save_pending=False);journal.persist()
        def returned(value):
            journal.returned('SaveActiveDocument',value);r['save_stage'].update(native_call_returned=True,save_pending=False,native_return_type=type(value).__name__,native_return_value=value if type(value)in(int,bool,float,str)or value is None else None);journal.persist()
        journal.pending('SaveActiveDocument');r['save_stage']['save_pending']=True;journal.persist();backend.save(returned=returned);sha=backend.adopt_saved_source(r['save_stage']);r.update(source_after_sha256=sha,saved_file_sha256=sha);journal.persist()
        saved=observe('saved');writer.writer.CircularGenerationProof(backend,reference=before).verify_saved(configured,saved)
        require(exact(targets('configured'),targets('saved'))and exact(draft('before'),draft('saved')),'Raw selected configuration or draft changed during Save')
        r['saved_configuration_proof']=dict(final_configured_proof_reused=True,raw_targets_preserved=True,source_transition_verified_by_existing_save_proof=True,source_after_sha256=sha)
        confirm=observe('confirm_saved');require(writer.writer.same(saved,confirm)and exact(targets('saved'),targets('confirm_saved'))and exact(draft('saved'),draft('confirm_saved')),'Two complete saved states differ')
        r.update(model_saved=True,save_readback_verified=True,source_update_verified=True,saved_observations=deepcopy(targets('saved')),saved_draft_witness=deepcopy(draft('saved')));backend.boundary();backend.finish();r.update(status='review_required',phase='finished',readback_verified=True,runtime_unchanged=True,parameters_configured=True,configuration_saved=True,reason='RECONCILED_PARTIAL_PREFIX_AND_ONLY_REMAINING_SUFFIX_SAVED_NO_GTP')
    except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',failed_phase=r['phase'],phase='finished',issue=_error(error),reason=str(error),readback_verified=False,runtime_unchanged=False,parameters_configured=False,configuration_saved=False)
    finally:
        try:backend.close()
        except Exception as error:r.update(status='uncertain'if r.get('mutation_attempted')else'error',cleanup_error=_error(error),readback_verified=False,runtime_unchanged=False,parameters_configured=False,configuration_saved=False)
        journal.persist()
    return r


def _dispatch_prepared(sw,clsid,tlb,v,bundle,*,runtime_check,_context_factory=Context):
    data=_consume_prepared(bundle,v,runtime_check=runtime_check);require(data['lineage']['loaded']['addin_clsid'].casefold()==clsid.casefold(),'Exact producer add-in required');abi=writer.preflight(tlb)
    r=dict(scope=SCOPE,status='error',phase='preflight',request=deepcopy(v),original_request=deepcopy(data['failure']['request']),original_failure_pin=data['failure_pin'],original_failure_marker_pin=data['failure_marker_pin'],depth_read_pin=data['depth_read_pin'],recipe=deepcopy(data['recipe']),recipe_pin=data['recipe_pin'],receipt_path=v['receipt_path'],dispatch_marker_path=data['marker'],source_before_sha256=v['expected_source_sha256'],historical_CL_pin=data['lineage']['cl_pin'],evidence_pins=deepcopy(data['pins']),selected_operation_native_ids=[x['operation_native_id']for x in data['recipe']['rows']],protected_draft_native_id=data['draft']['operation_native_id'],future_machining_excluded_operation_ids=[data['draft']['operation_native_id']],abi=abi,allowed_actions=action_names(data['recipe']),actions={},captures=[],target_observations={},draft_observations={},native_read_count=0,receipt_created=False,marker_created=False,mutation_attempted=False,native_call_attempted=False,native_call_returned=False,native_dispatch_pending=False,operation_creation_attempted=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,save_attempted=False,parameter_setter_attempted=False,tool_assignment_attempted=False,tool_edit_attempted=False,CL_export_attempted=False,automatic_replay=False,automatic_rollback=False,model_saved=False,save_readback_verified=False,source_update_verified=False,readback_verified=False,runtime_unchanged=False,parameters_configured=False,parameters_readback_verified=False,configuration_saved=False,partial_prefix_reconciled=False,machining_eligible=False,production_qualified=False,reopen_persistence_verified=False,CL_streams_reexported=False)
    journal=Journal(v['receipt_path'],data['marker'],r);backend=_context_factory(sw,clsid,tlb,v,data,r,journal.persist,runtime_check);runtime_check();result=run_once(backend,journal,data,v)
    try:runtime_check()
    except Exception as error:return finalize_runtime_failure(result,error)
    return result


def dispatch(sw,clsid,tlb,v,*,runtime_check,_context_factory=Context):
    bundle=_prepare_invocation(v,runtime_check=runtime_check);return _dispatch_prepared(sw,clsid,tlb,v,bundle,runtime_check=runtime_check,_context_factory=_context_factory)


def finalize_runtime_failure(result,error):
    result.update(status='uncertain'if result.get('mutation_attempted')else'error',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,configuration_saved=False,parameters_configured=False,machining_eligible=False,production_qualified=False)
    if result.get('receipt_created'):
        _write_receipt(Path(result['receipt_path']),result)
        if result.get('marker_created'):_write_receipt(Path(result['dispatch_marker_path']),completed_marker(result,dict(path=result['receipt_path'],sha256=_file_hash(result['receipt_path']))))
    return result
