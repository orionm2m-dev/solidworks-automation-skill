"""Insert named BORE definitions with immediate tool-reference gates, without Save."""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_bore_role_catalogue as roles
from scripts import sw_cam_turn_bore_definitions as prior
from scripts import sw_cam_turn_tool_reference_repair as references
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import solidworks_operation_lock
common=prior.common
SCOPE='NAMED_TURN_BORE_PAIR_RAM_NO_SAVE_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','catalogue_receipt_path','catalogue_receipt_sha256','producer_archive_path','producer_archive_sha256','feature_native_id','anchor_operation_native_id','definitions','receipt_path','module_sha256','qualification_only','acknowledge_ram_only'}
FORBIDDEN=('model_saved','GTP_attempted','GOP_attempted','geometry_edit_attempted','tool_assignment_attempted','tool_edit_attempted','depth_edit_attempted','automatic_replay','automatic_retry','persistence_qualified','physical_tool_qualified','production_qualified')


def validate_specs(specs):
    require(type(specs) is list and len(specs)==2,'Exactly one named BORE pair required')
    for role,s in zip(roles.ROLE_SYMBOLS,specs):
        require(type(s) is dict and set(s)=={'role','default_name','default_operation_id'} and s['role']==role,'Named BORE role order required; numeric TURN type is forbidden')
        require(type(s['default_name']) is str and 0<len(s['default_name'])<=1000 and type(s['default_operation_id']) is int and 0<s['default_operation_id']<2**31,'Strict observed default name/ID required')


def validate_catalogue(r,p,resolved):
    require(r['scope']==roles.SCOPE and r['status']=='observed' and r['phase']=='finished' and r['readback_verified'] is True and r['read_only'] is True,'Observed named BORE catalogue required')
    require(all(r[k] is False for k in ('mutation_attempted','GTP_attempted','model_saved','operation_inserted','assignment_attempted')) and not any(k in r for k in ('issue','failed_phase','cleanup_incomplete')),'Uncertain catalogue cannot authorize insertion')
    clean_events(r);q=r['request']
    require(q['process_id']==p['process_id'] and r['source_sha256']==p['expected_source_sha256'] and common._key(r['source_path'])==common._key(p['expected_document_path']),'Catalogue source/owner differs')
    b=r['before'];require(b==r['after'] and r['inventory_before']==r['inventory_after'],'Catalogue changed during read')
    require(b['operation_native_id']==p['anchor_operation_native_id'] and b['feature_native_id']==p['feature_native_id'] and b['operation_type']==9 and b['suppressed'] is False and b['generated'] is False and b['feature_header']['turn_feature_type_raw']==2,'Exact linked internal feature and drill anchor required')
    normalized=roles.normalize_observed_catalogues(r,resolved,allow_legacy_operation_type=True);validate_specs(p['definitions'])
    for s in p['definitions']:require(dict(name=s['default_name'],default_operation_id=s['default_operation_id']) in normalized[s['role']]['entries'],'Default absent from actual named BORE catalogue')
    return normalized


def marker_path(p):
    key=_digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),sha256=p['expected_source_sha256'],feature=p['feature_native_id'],anchor=p['anchor_operation_native_id'],roles=list(roles.ROLE_SYMBOLS)))
    return common.local_evidence_root()/('named_turn_bore_pair_'+key+'.json')


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='insert_named_turn_bore_pair','Exact named BORE RAM-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact parameters required');validate_specs(p['definitions'])
    for k in ('process_id','feature_native_id','anchor_operation_native_id'):require(type(p[k]) is int and 0<p[k]<2**31,'Strict positive identity required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True and p['acknowledge_ram_only'] is True,'Exact module and RAM-only qualification required');return p


def load_catalogue(p):
    raw,rpin=read_pin(p['catalogue_receipt_path'],p['catalogue_receipt_sha256']);q=raw['request']
    archive=common._pin(p['producer_archive_path']);require(archive['sha256']==p['producer_archive_sha256']==q['module_sha256'],'Exact historical producer archive required')
    original=[x for x in raw['runtime_and_evidence_pins'] if Path(x['path']).name==Path(roles.__file__).name]
    require(len(original)==1 and original[0]['sha256']==archive['sha256'],'Only exact archived producer may be retired')
    retained=[x for x in raw['runtime_and_evidence_pins'] if x is not original[0]];common._check(retained)
    generated=common._pin(q['generated_path']);require(generated['sha256']==q['generated_sha256'],'Generated binding changed')
    semantic=roles.audit(q['typelib_path'],generated,list(roles.ROLE_SYMBOLS));normalized=validate_catalogue(raw,p,semantic['roles'])
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Source bytes changed')
    pins=common._merge(retained,[archive,rpin,common._pin(roles.__file__)])
    return dict(catalogue=raw,catalogue_pin=rpin,normalized_catalogues=normalized,producer_archive_pin=archive,pins=pins,roles=semantic['roles'],semantic_abi=semantic,typelib_path=q['typelib_path'],generated_pin=generated)


def prepare(p):
    plan=load_catalogue(p);q=plan['catalogue']['request'];reg=prior.catalogue.jobs._validate_registration(q)
    abi=prior.audit(plan['typelib_path'],plan['generated_pin']);reference_abi=references.audit(plan['typelib_path'],plan['generated_pin'])
    pins=common._merge(plan['pins'],[common._pin(x.__file__) for x in (prior,prior.context,prior.thread,prior.dispatch,prior.generation,prior.events,references)],[common._pin(__file__)])
    require(len(pins)<=64,'Bounded runtime/evidence closure required')
    output=common._local_receipt(p['receipt_path']);marker=marker_path(p);protected={common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])}
    require(len({common._key(output),common._key(marker)})==2 and not protected.intersection((common._key(output),common._key(marker))),'Fresh outputs must not alias evidence or source')
    require(all(x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in (output,marker)),'Fresh receipt and no prior pair attempt required')
    plan.update(pins=pins,registration=reg,abi=abi,reference_abi=reference_abi,output=output,marker=marker);return plan


def verify_before(state,observed,p,resolved):
    prior.verify_before(state,observed,p)
    kinds={x['resolved_native_value'] for x in resolved}
    require(not any(x['turn_operation_type'] in kinds and p['feature_native_id'] in x['linked_feature_ids'] for x in state['operations']),'Existing named BORE definitions prohibit replay')


def verify_added(before,after,new_id,role,feature_id,anchor_id,resolved):
    require(role in roles.ROLE_SYMBOLS,'Named BORE role required')
    kind=next(x['resolved_native_value'] for x in resolved if x['role']==role)
    require(type(new_id) is int and new_id>0,'Positive inserted native ID required')
    ids=[x['native_id'] for x in before['operations']];require(new_id not in ids,'Returned pre-existing operation')
    anchor=next(x for x in before['operations'] if x['native_id']==anchor_id);si=anchor['setup_index'];oi=anchor['operation_index']+1
    added=[x for x in after['operations'] if x['native_id']==new_id];require(len(added)==1,'Exactly one returned new operation required');new=added[0]
    require(new==dict(setup_index=si,operation_index=oi,native_id=new_id,turn_operation_type=kind,linked_feature_ids=[feature_id],suppressed=False),'Inserted type is not the declared BORE role or identity/link differs')
    expected=deepcopy(before);expected['document']['needs_save']=after['document']['needs_save'];require(type(after['document']['needs_save']) is bool,'Strict dirty flag required');at=ids.index(anchor_id)+1
    for x in expected['operations']:
        if x['setup_index']==si and x['operation_index']>=oi:x['operation_index']+=1
    expected['operations'].insert(at,deepcopy(new))
    for x in expected['inventory']['operations']:
        if x['setup_index']==si and x['operation_index']>=oi:x['operation_index']+=1
    expected['inventory']['operations'].insert(at,dict(setup_index=si,operation_index=oi,turn_operation_type=kind,toolpath_generated=False,toolpath_record_counts=[]));expected['inventory']['operation_count']+=1
    require(expected==after,'Insertion changed protected geometry/source/route metadata or more than one operation');return deepcopy(new)


def validate_reference(value,operation_id):
    require(type(value) is dict and value['operation_native_id']==operation_id and type(value['tool_native_id']) is int and value['tool_native_id']>0,'Readable positive tool reference required')
    require(value['tool_type_raw']==15 and value['turn_tool_type_raw']==1 and value['insert_type_raw']==1 and value['holder_type_raw']==2 and all(type(v) is int for v in value.values()),'Expected TURN diamond boring-holder reference required')


class NativeBackend(prior.NativeBackend):
    def catalogue_check(self):
        actual=roles.read_catalogues(self.native['feature'],self.plan['roles'],read=self.read,record=lambda *a:None)
        require(actual==self.plan['normalized_catalogues'],'Named BORE catalogue changed')
    def assigned(self,operation_id):
        current=self.identity();self.boundary()
        with prior.dispatch.ScopedCamDispatchGuard(self.sw,self.typelib,process_id=self.p['process_id'],expected_document=current,source_sha256=self.source,evidence_pins=self.plan['pins'],verify_evidence=lambda:common._check(self.plan['pins']),verify_owned_process=self.owned,check_events=self.event_check) as g:
            op=g.typed(self.native['operations'][operation_id],'ICWOperation');require(_object_id(self.native['doc'],op,g.read)==operation_id,'New operation identity changed')
            raw=g.read(op,'IGetTool');require(raw is not None and bool(raw),'New operation has no readable tool reference')
            tool=g.typed(raw,'ICWTool');value=dict(operation_native_id=operation_id,tool_native_id=_object_id(self.native['doc'],tool,g.read),tool_type_raw=g.read(tool,'ToolType'))
            self.report.setdefault('tool_reference_observations',[]).append(value);self.persist();require(type(value['tool_type_raw']) is int and value['tool_type_raw']==15,'Generic tool is not TURN')
            turn=g.typed(raw,'ICWTurnTool');value['turn_tool_type_raw']=g.read(turn,'ToolType');self.persist();require(type(value['turn_tool_type_raw']) is int and value['turn_tool_type_raw']==1,'TURN tool is not an insert holder')
            value['insert_type_raw']=g.read(turn,'InsertType');self.persist();require(type(value['insert_type_raw']) is int and value['insert_type_raw']==1,'TURN insert is not diamond')
            holder=g.typed(g.read(turn,'IGetTurnToolHolder'),'ICWTurnToolHolder');value.update(holder_type_raw=g.read(holder,'GetHolderType'),holder_id_raw=g.read(holder,'GetHolderId'));self.persist();validate_reference(value,operation_id)
        return value


def claim_value(p):return dict(scope=SCOPE,status='claimed_no_replay',source_sha256=p['expected_source_sha256'],feature_native_id=p['feature_native_id'],anchor_operation_native_id=p['anchor_operation_native_id'],roles=list(roles.ROLE_SYMBOLS),receipt_path=p['receipt_path'])


def run_backend(backend,p,plan,r,persist):
    claimed=False
    def pending(label):
        nonlocal claimed
        require(label not in r['actions'],'No repeated insertion')
        if not claimed:_write_receipt(plan['marker'],claim_value(p),create=True);claimed=True
        r.update(phase=label,mutation_attempted=True,native_dispatch_pending=True);r['actions'][label]=dict(attempted=True,pending=True,returned=False,readback_verified=False);persist()
    try:
        backend.start();r['phase']='before';r['before']=backend.capture('before');persist();verify_before(r['before'],plan['catalogue'],p,plan['roles']);backend.catalogue_check()
        current=r['before'];anchor=p['anchor_operation_native_id']
        for spec in p['definitions']:
            role=spec['role'];kind=next(x['resolved_native_value'] for x in plan['roles'] if x['role']==role);label='InsertOperation_'+role
            native=dict(operation_type=kind,default_name=spec['default_name'],default_operation_id=spec['default_operation_id'])
            new_id=backend.insert(native,anchor,lambda label=label:pending(label));r['actions'][label].update(returned=True,pending=False,new_native_id=new_id,resolved_native_value=kind);r['native_dispatch_pending']=False;persist()
            after=backend.capture(label+'_readback');r.setdefault('insertion_observations',[]).append(after);persist();row=verify_added(current,after,new_id,role,p['feature_native_id'],anchor,plan['roles']);r.setdefault('new_operations',[]).append(row)
            r['phase']='tool_reference_'+role;persist();tool=backend.assigned(new_id);validate_reference(tool,new_id);r.setdefault('verified_tool_references',[]).append(deepcopy(tool));r['actions'][label]['readback_verified']=True;persist();current=after;anchor=new_id
        r['phase']='final_pair_references';persist();r['final_tool_references']=[backend.assigned(x['native_id']) for x in r['new_operations']];persist()
        require(r['final_tool_references']==r['verified_tool_references'],'Tool references changed after pair insertion')
        r['after']=backend.capture('after');persist();require(r['after']==current,'Final route changed after tool-reference reads');backend.finish();r.update(status='created_bore_pair_ram_no_save',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return r


def validate_created(r,observed,resolved):
    p=r['request'];validate_catalogue(observed,p,resolved);validate_specs(p['definitions'])
    require(r['scope']==SCOPE and r['status']=='created_bore_pair_ram_no_save' and r['phase']=='finished' and r['readback_verified'] is True and r['mutation_attempted'] is True and r['native_dispatch_pending'] is False,'Completed RAM-only BORE pair required')
    require(all(r[k] is False for k in FORBIDDEN) and not any(k in r for k in ('issue','failed_phase','cleanup_issue')),'Unexpected mutation/uncertain pair');clean_events(r)
    verify_before(r['before'],observed,p,resolved);current=r['before'];anchor=p['anchor_operation_native_id']
    require(len(r['new_operations'])==len(r['insertion_observations'])==len(r['verified_tool_references'])==2 and set(r['actions'])=={'InsertOperation_'+x for x in roles.ROLE_SYMBOLS},'Exact two insertions and reference gates required')
    for spec,state,row,tool in zip(p['definitions'],r['insertion_observations'],r['new_operations'],r['verified_tool_references']):
        action=r['actions']['InsertOperation_'+spec['role']];require(action['attempted'] is True and action['returned'] is True and action['pending'] is False and action['readback_verified'] is True and action['new_native_id']==row['native_id'] and action['resolved_native_value']==row['turn_operation_type'],'Incomplete insertion')
        require(verify_added(current,state,row['native_id'],spec['role'],p['feature_native_id'],anchor,resolved)==row,'Recorded insertion differs');validate_reference(tool,row['native_id']);current=state;anchor=row['native_id']
    require(r['final_tool_references']==r['verified_tool_references'],'Final pair references differ from verified insertion links')
    require(current==r['after'] and r['after']['saved_file_sha256']==p['expected_source_sha256'],'RAM final state/source differs');return r['after']


def load_created(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest);p=r['request'];require(p['process_id']==process_id and common._key(p['expected_document_path'])==common._key(expected_document_path) and p['expected_source_sha256']==expected_source_sha256,'Exact created pair owner/source required')
    plan=load_catalogue(p);state=validate_created(r,plan['catalogue'],plan['roles']);common._check(r['runtime_and_evidence_pins']);require(r['module_pin']==common._pin(__file__),'Writer changed')
    marker=marker_path(p);v,mpin=read_pin(str(marker),r['marker_pin']['sha256']);require(v==claim_value(p),'Original once marker required')
    pins=common._merge(r['runtime_and_evidence_pins'],[pin,mpin]);require(len(pins)<=64,'Bounded continuation closure required')
    return dict(authority='named_bore_pair_ram_no_save',receipt=r,state=deepcopy(state),reference=deepcopy(state),new_operations=deepcopy(r['new_operations']),tool_references=deepcopy(r['verified_tool_references']),catalogue=plan['catalogue'],normalized_catalogues=plan['normalized_catalogues'],roles=plan['roles'],typelib_path=plan['typelib_path'],pins=pins,source_sha256=expected_source_sha256,persistence_qualified=False,GTP_authorized=False)


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,pin_count=len(plan['pins']),roles=plan['roles'],definitions=p['definitions'],max_insert_calls=2,tool_reference_gate_after_each=True,save_authorized=False,GTP_authorized=False)
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,process_id=p['process_id'],source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],catalogue_pin=plan['catalogue_pin'],producer_archive_pin=plan['producer_archive_pin'],module_pin=common._pin(__file__),runtime_and_evidence_pins=plan['pins'],abi=plan['abi'],semantic_abi=plan['semantic_abi'],actions={},native_dispatch_pending=False,mutation_attempted=False,readback_verified=False,**{k:False for k in FORBIDDEN})
        _write_receipt(plan['output'],r,create=True);persist=lambda:_write_receipt(plan['output'],r)
        backend=NativeBackend(sw,p,plan,r,persist);run_backend(backend,p,plan,r,persist)
        if r['readback_verified']:
            try:r['marker_pin']=common._pin(plan['marker']);validate_created(r,plan['catalogue'],plan['roles']);common._check(plan['pins'])
            except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
            persist()
        return r


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--request',required=True);ap.add_argument('--validate-only',action='store_true');a=ap.parse_args()
    r=dispatch_request(json.loads(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only)
    print(json.dumps({k:r[k] for k in ('scope','status','phase','readback_verified','native_called','pin_count','roles','definitions','new_operations','issue') if k in r},ensure_ascii=False,indent=2));raise SystemExit(0 if r['status'] in ('validated_offline','created_bore_pair_ram_no_save') else 2)
