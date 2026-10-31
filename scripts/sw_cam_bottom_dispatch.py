"""One reviewed Automation property write on an existing owned finish operation.

No generation, Save, rollback, UI action, interface discovery or automatic retry.
"""
from copy import deepcopy
from pathlib import Path
import ast
import json
import re
from scripts import sw_cam_pocket_finish_apply as finish
from scripts import sw_cam_finish_field_batch as fields
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam import _error

require = finish.require
SCOPE = 'BOUNDED_BOTTOM_FINISH_DUAL_DISPATCH_V1'
IID = '{4EDDCA7E-325A-11D6-A9A7-00062999E55F}'
PROPERTY, CACHED_DISPID, PROPERTYGET, PROPERTYPUT, LCID = 'BottomFinOpt', 22, 2, 4, 0
BINDING_CONTRACT = 'SAME_TYPED_OWNER_RUNTIME_NAME_BINDING_V2'
ACK = 'one_propertyput_true_after_exact_false_comparison'
COMMON = {'process_id','expected_document_path','expected_source_sha256','addin_clsid',
    'receipt_path','progress_path','failed_receipt_path','failed_receipt_sha256',
    'field_receipt_path','field_receipt_sha256','module_sha256'}
APPLY = {'comparison_receipt_path','comparison_receipt_sha256','acknowledgement'}
RETIRED_PROFILE_MODULES = frozenset({'sw_cam_mill_inventory_geometry.py',
    'sw_cam_shared_cutter_geometry.py','sw_cam_shared_holder_geometry.py'})

def audit_cached_dual(pin):
    """Read the existing pinned generated type metadata; never import COM."""
    finish.common._check([pin])
    tree = ast.parse(Path(pin['path']).read_text(encoding='mbcs'))
    cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ICWFinishMillOp')
    assign = {n.targets[0].id:n.value for n in cls.body if isinstance(n,ast.Assign)
        and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
    require(ast.literal_eval(assign['_idlflags_'])==['dual','oleautomation'],'Dual Automation required')
    require(ast.literal_eval(assign['_iid_'].args[0])==IID,'Exact finish IID required')
    require(len(cls.bases)==1 and isinstance(cls.bases[0],ast.Attribute)
        and cls.bases[0].attr=='IDispatch','IDispatch base required')
    methods = next(n.value for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
        and isinstance(n.targets[0],ast.Attribute) and isinstance(n.targets[0].value,ast.Name)
        and n.targets[0].value.id=='ICWFinishMillOp' and n.targets[0].attr=='_methods_')
    found = []
    for item in methods.elts:
        if not isinstance(item,ast.Call) or len(item.args)!=4: continue
        if not isinstance(item.args[2],ast.Constant) or item.args[2].value!=PROPERTY: continue
        flags,result,_,arg=item.args
        require(isinstance(flags,ast.List) and len(flags.elts)==3
            and isinstance(flags.elts[0],ast.Call) and isinstance(flags.elts[0].func,ast.Name)
            and flags.elts[0].func.id=='dispid' and ast.literal_eval(flags.elts[0].args[0])==CACHED_DISPID
            and isinstance(result,ast.Name) and result.id=='HRESULT','Property metadata differs')
        kind=ast.literal_eval(flags.elts[2]); aflags=ast.literal_eval(arg.elts[0])
        native_type=ast.unparse(arg.elts[1])
        require((kind,aflags,native_type) in (
            ('propget',['out','retval'],'POINTER(VARIANT_BOOL)'),
            ('propput',['in'],'VARIANT_BOOL')),'Only Boolean get/put supported')
        found.append(dict(kind=kind,argument_flags=aflags,native_type=native_type))
    require(len(found)==2 and {x['kind'] for x in found}=={'propget','propput'},'Exact property pair required')
    return dict(interface='ICWFinishMillOp',iid=IID,idlflags=['dual','oleautomation'],
        dispid=CACHED_DISPID,member=PROPERTY,members=found,generated_pin=deepcopy(pin),
        source_kind='installed_pinned_generated_type_information',live_typeinfo_invoked=False)

def valid_runtime_dispid(value):
    return type(value) is int and 0 < value <= 2147483647

class PropertyAccess:
    """Public inherited IDispatch calls on the SAME typed finish pointer."""
    def __init__(self,owner): self.owner=owner;self.dispid=None
    def names(self): return self.owner.GetIDsOfNames(PROPERTY,lcid=LCID)
    def get(self):
        require(valid_runtime_dispid(self.dispid),'Resolved runtime member required')
        return self.owner.Invoke(self.dispid,_invkind=PROPERTYGET,_lcid=LCID)
    def put_true(self):
        require(valid_runtime_dispid(self.dispid),'Resolved runtime member required')
        return self.owner.Invoke(self.dispid,True,_invkind=PROPERTYPUT,_lcid=LCID)

def read_pair(guard,owner,row,persist,*,approved_dispid=None):
    access=PropertyAccess(owner)
    ids=guard.read(access,'names')
    row['resolved_names']=fields.raw_observation(ids);persist()
    require(type(ids) is list and len(ids)==1 and valid_runtime_dispid(ids[0]),
        'BottomFinOpt must resolve to one positive int32 runtime DISPID')
    access.dispid=ids[0]
    row.update(binding_contract=BINDING_CONTRACT,resolved_dispid=access.dispid,
        cached_metadata_dispid=CACHED_DISPID,member=PROPERTY,lcid=LCID)
    persist()
    if approved_dispid is not None:
        require(valid_runtime_dispid(approved_dispid) and access.dispid==approved_dispid,
            'Runtime name binding differs from reviewed inspection')
    value=guard.read(owner,PROPERTY)
    row['vtable']=fields.raw_observation(value);persist()
    require(type(value) is bool,'Vtable result must be strict bool')
    dispatch=guard.read(access,'get')
    row['dispatch']=fields.raw_observation(dispatch);persist()
    require(type(dispatch) is bool,'Automation result must be strict bool')
    require(value is dispatch,'Vtable and Automation getters disagree')
    row.update(equal=True,value=value,complete=True);persist()
    return value,access

class Journal(finish.prior.tools.Journal):
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,receipt_path=str(self.receipt),source_path=r['source_path'],
            initial_source_sha256=r['initial_source_sha256'],process_id=r['process_id'],
            failed_receipt_pin=r['failed_receipt_pin'],field_receipt_pin=r['field_receipt_pin'],
            actions=deepcopy(r['actions']),phase=r['phase'],status=r['status'],
            readback_verified=r['readback_verified'],automatic_replay=False)

class NativeBackend(finish.NativeBackend):
    def confirm_ungenerated(self,g):
        # owner() has just refreshed this exact operation handle under the guard.
        op=g.typed(self.native['operations'][144],'ICWOperation')
        require(g.read(op,'GetIsToolpathGenerated') is False,'Generated finish forbids this experiment')
    def compare(self,label):
        row=self.report.setdefault('comparisons',{}).setdefault(label,{})
        with self.ctx.guard() as g:
            owner,_,_=self.owner(g,next(x for x in finish.FIELDS if x[0]=='bottom_finish'))
            self.confirm_ungenerated(g)
            value,_=read_pair(g,owner,row,self.persist,
                approved_dispid=self.loaded.get('approved_runtime_dispid'))
        return value
    def put_once(self,journal):
        row=self.report.setdefault('comparisons',{}).setdefault('immediately_before_put',{})
        with self.ctx.guard() as g:
            owner,_,_=self.owner(g,next(x for x in finish.FIELDS if x[0]=='bottom_finish'))
            self.confirm_ungenerated(g)
            approved=self.loaded.get('approved_runtime_dispid')
            require(valid_runtime_dispid(approved),'Reviewed runtime member required before put')
            value,access=read_pair(g,owner,row,self.persist,approved_dispid=approved)
            require(value is False,'Both getters must still be false immediately before put')
            return g.dispatch_once(access.put_true,
                persist_pending=lambda:journal.pending('IDispatch.PROPERTYPUT.BottomFinOpt'))
    def all_fields(self,label): return fields.read_fields(self,label)

def marker_path(p):
    return finish.common.local_evidence_root()/('bottom_dispatch_'+_digest(dict(
        scope=SCOPE,source=finish.common._key(p['expected_document_path']),
        source_sha256=p['expected_source_sha256'],failed_sha256=p['failed_receipt_sha256'],
        operation=144,feature=79,member=PROPERTY,value=True))+'.json')

def validate_observation(v,p):
    require(v.get('scope')==fields.SCOPE and v.get('status')=='observed'
        and v.get('phase')=='finished' and v.get('read_only') is True
        and v.get('readback_verified') is True and v.get('phase_proofs_verified') is True
        and v.get('setter_attempted') is False and v.get('GTP_attempted') is False
        and v.get('model_saved') is False,'Complete direct read-only observation required')
    require(v['process_id']==p['process_id']
        and finish.common._key(v['source_path'])==finish.common._key(p['expected_document_path'])
        and v['source_sha256']==p['expected_source_sha256']
        and v['failed_receipt_pin']['sha256']==p['failed_receipt_sha256'],'Observation binding differs')
    require(v['module_pin']==finish.common._pin(fields.__file__),'Direct reader changed')
    actual=v['fields']
    require(set(actual)=={s[0] for s in finish.FIELDS} and actual['bottom_finish'] is False,
        'Observed strict false and fifteen fields required')
    require(v['before_document']==v['after_document'],'Read-only identity changed')
    clean_events(v)
    return deepcopy(actual)

def validate_comparison(v,p,field_pin):
    require(v.get('scope')==SCOPE and v.get('action')=='inspect' and v.get('status')=='inspected'
        and v.get('phase')=='finished' and v.get('readback_verified') is True
        and v.get('phase_proofs_verified') is True and v.get('ready_for_one_put') is True
        and v.get('mutation_attempted') is False and v.get('actions')=={},
        'Completed read-only false comparison required')
    require(v['module_pin']==finish.common._pin(__file__) and v['process_id']==p['process_id']
        and finish.common._key(v['source_path'])==finish.common._key(p['expected_document_path'])
        and v['initial_source_sha256']==p['expected_source_sha256']
        and v['field_receipt_pin']['sha256']==field_pin['sha256']
        and v['failed_receipt_pin']['sha256']==p['failed_receipt_sha256'],
        'Comparison authority binding differs')
    pair=v['comparisons']['before']
    resolved=pair.get('resolved_dispid')
    require(pair.get('binding_contract')==BINDING_CONTRACT and valid_runtime_dispid(resolved)
        and pair.get('resolved_names')==fields.raw_observation([resolved])
        and pair.get('cached_metadata_dispid')==CACHED_DISPID
        and pair.get('member')==PROPERTY and pair.get('lcid')==LCID,
        'Exact inspected runtime name binding required')
    require(pair.get('complete') is True and pair.get('equal') is True and pair.get('value') is False
        and pair['vtable']==fields.raw_observation(False) and pair['dispatch']==fields.raw_observation(False),
        'Exact two false getter results required')
    require(v.get('GTP_attempted') is False and v.get('model_saved') is False
        and not any(k in v for k in ('issue','cleanup_issue','phase_proof_error')),
        'Comparison contains failure or forbidden action')
    clean_events(v)
    return resolved

def load_inputs(request):
    require(type(request) is dict and set(request)=={'action','params'}
        and request['action'] in ('inspect','apply'),'Explicit inspect/apply required')
    action=request['action'];p=deepcopy(request['params'])
    require(type(p) is dict and set(p)==COMMON|(APPLY if action=='apply' else set()),'Exact request fields required')
    require(p['module_sha256']==finish._file_hash(__file__),'Reviewed module hash differs')
    for k,v in p.items():
        if k.endswith('_path'): require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'): require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact SHA256 required')
    if action=='apply': require(p['acknowledgement']==ACK,'Explicit reviewed one-put request required')
    rp={k:p[k] for k in COMMON-{'field_receipt_path','field_receipt_sha256'}}
    rp['module_sha256']=finish._file_hash(fields.__file__)
    _,loaded,failed_pin=fields.inspect_inputs(dict(action='inspect_partial_finish_fields',params=rp))
    observation,field_pin=read_pin(p['field_receipt_path'],p['field_receipt_sha256'])
    expected=validate_observation(observation,p)
    require(observation['after_document']==loaded['state']['document'],'Partial document differs')
    audit=audit_cached_dual(loaded['generated_pin'])
    generated=Path(loaded['generated_pin']['path']);comtypes=generated.parent.parent
    dependencies=[finish.common._pin(__file__),finish.common._pin(comtypes/'automation.py'),
        finish.common._pin(generated.parent/'_00020430_0000_0000_C000_000000000046_0_2_0.py')]
    retired=[pin for pin in loaded['pins'] if Path(pin['path']).name in RETIRED_PROFILE_MODULES]
    require(len(retired)==3 and {Path(pin['path']).name for pin in retired}==RETIRED_PROFILE_MODULES,
        'Exactly three inactive profile-review modules required')
    # start/current_tool/field reads use IDs and scalar values only. Profile
    # readers, snapshot/candidate acceptance and holder validation are not called.
    # These immutable historical inputs remain checked before/after the phase.
    loaded['retired_profile_review_pins']=deepcopy(retired)
    loaded['offline_export_proof_pins']=finish.common._merge(loaded['offline_export_proof_pins'],retired)
    loaded['pins']=finish.common._merge([pin for pin in loaded['pins'] if pin not in retired],dependencies)
    require(len(loaded['pins'])<=64,'Bounded live closure required')
    loaded['offline_export_proof_pins']=finish.common._merge(loaded['offline_export_proof_pins'],[field_pin])
    comparison_pin=None
    loaded['approved_runtime_dispid']=None
    if action=='apply':
        comparison,comparison_pin=read_pin(p['comparison_receipt_path'],p['comparison_receipt_sha256'])
        loaded['approved_runtime_dispid']=validate_comparison(comparison,p,field_pin)
        loaded['offline_export_proof_pins']=finish.common._merge(loaded['offline_export_proof_pins'],[comparison_pin])
    loaded['current_context_sha256']=_digest(finish.group.current_projection(loaded))
    marker=marker_path(p)
    require(not marker.exists() and not marker.is_symlink(),'Existing put attempt forbids replay')
    protected={finish.common._key(x['path']) for x in loaded['pins']+loaded['offline_export_proof_pins']
        +loaded['bootstrap_export_pins']}
    protected.add(finish.common._key(p['expected_document_path']))
    outputs=[Path(p['receipt_path']),Path(p['progress_path']),marker]
    require(len({finish.common._key(x) for x in outputs})==len(outputs)
        and not protected.intersection(finish.common._key(x) for x in outputs),'Output aliases evidence')
    return action,p,loaded,failed_pin,field_pin,comparison_pin,expected,audit,marker

def validate_document_transition(before,after,action):
    require(type(before) is dict and type(after) is dict
        and type(before.get('needs_save')) is bool and type(after.get('needs_save')) is bool,
        'Exact document identities with Boolean dirty flags required')
    if action=='inspect':
        require(finish.group.exact(before,after),'Read-only document identity changed')
        return
    require(action=='apply','Bounded identity transition action required')
    require(not (before['needs_save'] is True and after['needs_save'] is False),
        'Property update cannot clear the dirty flag')
    expected=deepcopy(before);expected['needs_save']=after['needs_save']
    require(finish.group.exact(expected,after),'Property update changed another document identity field')


def run_steps(backend,journal,action,expected):
    require(action in ('inspect','apply'),'Bounded lifecycle action required')
    if action=='apply':
        require(valid_runtime_dispid(backend.loaded.get('approved_runtime_dispid')),
            'Successful inspection must supply the runtime member for apply')
    r=journal.report;backend.start()
    r['before_document']=backend.ctx.identity();r['before_tool']=backend.current_tool();journal.persist()
    require(finish.group.exact(r['before_tool'],finish.wanted_assignment(backend.loaded)),'Assigned tool changed')
    r['before_fields']=backend.all_fields('dispatch_before');journal.persist()
    require(finish.group.exact(r['before_fields'],expected),'Partial recipe changed after observation')
    require(backend.compare('before') is False,'Reviewed experiment requires false')
    r['ready_for_one_put']=True;journal.persist()
    if action=='apply':
        result=backend.put_once(journal)
        journal.returned('IDispatch.PROPERTYPUT.BottomFinOpt',result)
        # Public Invoke returns VARIANT content, not HRESULT. COM failure raises.
        require(result is None,'PROPERTYPUT must return no VARIANT result')
        backend.refresh_dirty()
        require(backend.compare('after') is True,'Both post-put getters must be true')
        r['after_fields']=backend.all_fields('dispatch_after');journal.persist()
        wanted=deepcopy(expected);wanted['bottom_finish']=True
        require(finish.group.exact(r['after_fields'],wanted),'Another recipe field changed')
        r['actions']['IDispatch.PROPERTYPUT.BottomFinOpt']['readback_verified']=True
    else:r['after_fields']=deepcopy(r['before_fields'])
    r['after_tool']=backend.current_tool();r['after_document']=backend.ctx.identity();journal.persist()
    require(finish.group.exact(r['before_tool'],r['after_tool']),'Assigned tool changed')
    validate_document_transition(r['before_document'],r['after_document'],action)
    backend.boundary()
    finish.common._check(backend.loaded['offline_export_proof_pins'])
    finish.common._check(backend.loaded['bootstrap_export_pins'])
    r.update(status='verified' if action=='apply' else 'inspected',phase='finished',
        readback_verified=True,phase_proofs_verified=True)
    journal.persist()

def execute(sw,clsid,typelib,*,inputs):
    action,p,loaded,failed_pin,field_pin,comparison_pin,expected,audit,marker=inputs
    r=dict(schema_version=1,scope=SCOPE,action=action,status='prepared',phase='prepared',
        process_id=p['process_id'],source_path=p['expected_document_path'],
        initial_source_sha256=p['expected_source_sha256'],module_pin=finish.common._pin(__file__),
        failed_receipt_pin=failed_pin,field_receipt_pin=field_pin,comparison_receipt_pin=comparison_pin,
        metadata_audit=audit,binding_contract=BINDING_CONTRACT,
        approved_runtime_dispid=loaded['approved_runtime_dispid'],live_pins=deepcopy(loaded['pins']),
        retired_profile_review_pins=deepcopy(loaded['retired_profile_review_pins']),
        offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),readback_verified=False,
        phase_proofs_verified=False,mutation_attempted=False,GTP_attempted=False,model_saved=False,
        automatic_replay=False,production_qualified=False,ready_for_one_put=False,actions={})
    journal=Journal(r,p['receipt_path'],marker);_write_receipt(p['receipt_path'],r,create=True)
    backend=NativeBackend(loaded,p,sw,clsid,typelib,r,journal.persist)
    try:run_steps(backend,journal,action,expected)
    except Exception as exc:
        r.update(status='uncertain' if r['mutation_attempted'] else 'error',
            failed_phase=r['phase'],phase='finished',issue=_error(exc),
            readback_verified=False,ready_for_one_put=False)
    finally:
        try:backend.close()
        except Exception as exc:
            r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False,ready_for_one_put=False)
        journal.persist()
    return r

def dispatch_request(request,*,validate_only=False):
    inputs=load_inputs(request)
    action,p,loaded,_,_,_,_,audit,marker=inputs
    if validate_only:return dict(status='validated_offline',native_called=False,action=action,
        live_pin_count=len(loaded['pins']),metadata_audit=audit,marker=str(marker))
    registration=finish.common.discover_export_registration(loaded,p['addin_clsid'])
    typelib=str(Path(registration['addin_path']).parent/'camworks.tlb')
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        finish.common._check(loaded['pins']);finish.common._check(loaded['offline_export_proof_pins'])
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,registration['clsid'],typelib,inputs=inputs)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true');args=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','phase','readback_verified','issue','native_called')},ensure_ascii=False))
    return 0 if r.get('status')=='validated_offline' or r.get('readback_verified') is True else 1

if __name__=='__main__': raise SystemExit(main())