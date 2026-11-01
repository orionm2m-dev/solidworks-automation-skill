"""Create one rough/finish TURN definition pair on an observed ID feature.

Two individually guarded InsertOperation calls, exact deltas, then one save.
No strategy/tool/depth edits, path generation or manufacturing qualification.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_turn_bore_catalogue as catalogue
from scripts import sw_cam_thread as thread
from scripts import sw_cam_ud14_save as save_support
from scripts import sw_cam_dispatch_guard as dispatch
from scripts import sw_cam_generation as generation
from scripts import sw_cam_events as events
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target,solidworks_operation_lock
from scripts.sw_executable_launch import _process_identity,_same_path
common,context=catalogue.common,catalogue.turn_context
SCOPE='SAVED_TURN_BORE_DEFINITION_PAIR_V1'
PARAMS={'process_id','expected_document_path','expected_source_sha256','catalogue_receipt_path','catalogue_receipt_sha256','feature_native_id','anchor_operation_native_id','definitions','receipt_path','module_sha256','qualification_only','acknowledge_disposable_copy','message_policy'}
FORBIDDEN=('GTP_attempted','GOP_attempted','geometry_edit_attempted','attribute_changed','tool_assignment_attempted','tool_edit_attempted','depth_edit_attempted','automatic_replay','automatic_retry','production_qualified','geometry_acceptance_complete')


def validate_specs(specs):
    require(type(specs) is list and len(specs)==2,'Exactly one rough/finish pair required')
    for kind,s in zip((1,2),specs):
        require(type(s) is dict and set(s)=={'operation_type','default_name','default_operation_id'}
            and type(s['operation_type']) is int and s['operation_type']==kind
            and type(s['default_name']) is str and 0<len(s['default_name'])<=1000
            and type(s['default_operation_id']) is int and 0<s['default_operation_id']<2**31,'Exact observed TURN default required')


def marker_path(p):
    key=_digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),source_sha256=p['expected_source_sha256'],feature_native_id=p['feature_native_id'],anchor_native_id=p['anchor_operation_native_id']))
    return common.local_evidence_root()/('turn_bore_definitions_'+key+'.json')


def validate_catalogue(r,p):
    require(r['scope']==catalogue.SCOPE and r['status']=='observed' and r['phase']=='finished'
        and r['readback_verified'] is True and r['read_only'] is True,'Completed observed TURN catalogue required')
    require(all(r[k] is False for k in ('mutation_attempted','GTP_attempted','model_saved','operation_inserted','attribute_changed'))
        and not any(k in r for k in ('issue','failed_phase','cleanup_incomplete')),'Uncertain catalogue cannot authorize insertion')
    clean_events(r)
    require(type(r['process_id']) is int and r['process_id']==p['process_id']
        and r['source_sha256']==p['expected_source_sha256']
        and common._key(r['source_path'])==common._key(p['expected_document_path']),'Catalogue source/owner differs')
    b=r['before'];require(b==r['after'] and r['inventory_before']==r['inventory_after'],'Catalogue changed during read')
    require(b['operation_native_id']==p['anchor_operation_native_id'] and b['feature_native_id']==p['feature_native_id']
        and b['operation_type']==9 and b['suppressed'] is False and b['generated'] is False
        and b['feature_header']['turn_feature_type_raw']==2,'Exact ungenerated drill anchor and ID feature required')
    validate_specs(p['definitions'])
    for s in p['definitions']:
        rows=r['catalogues'][str(s['operation_type'])]['entries']
        require(dict(name=s['default_name'],default_operation_id=s['default_operation_id']) in rows,'Requested default not in observed selected-feature catalogue')
    return b


def audit(typelib,generated_pin):
    from ctypes import POINTER,c_int
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _load_type_library,_INTERFACES
    from scripts.sw_cam_face_interfaces import _verify_generated_class
    from scripts.sw_cam_pocket_rough_apply import require_abi
    cls=_verify_generated_class(getattr(_load_type_library(typelib),'ICWTurnFeature'),_INTERFACES['ICWTurnFeature'],generated_pin)
    found=[m for m in cls._methods_ if m.name=='InsertOperation'];require(len(found)==1,'Unique typed TURN insertion required')
    require_abi(found[0],12,(c_int,c_int,POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,1,1,10))
    return dict(abi_verified=True,native_calls=0,interface='ICWTurnFeature',member='InsertOperation',dispid=12,operations_per_call=1)


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='create_turn_bore_definitions','Exact definitions-only action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    for k in ('process_id','feature_native_id','anchor_operation_native_id'):require(type(p[k]) is int and 0<p[k]<2**31,'Strict positive identity required')
    for k,v in p.items():
        if k.endswith('_path'):require(type(v) is str and Path(v).is_absolute(),'Absolute path required')
        if k.endswith('_sha256'):require(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'Exact digest required')
    validate_specs(p['definitions'])
    require(p['module_sha256']==_file_hash(__file__) and p['qualification_only'] is True and p['acknowledge_disposable_copy'] is True
        and p['message_policy']=='vendor_default','Explicit qualification-only definitions required');return p


def prepare(p):
    r,rpin=read_pin(p['catalogue_receipt_path'],p['catalogue_receipt_sha256']);validate_catalogue(r,p)
    require(_file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Current saved source differs')
    common._check(r['runtime_and_evidence_pins'])
    q=r['request'];reg=catalogue.jobs._validate_registration(q)
    generated=common._pin(q['generated_path']);require(generated['sha256']==q['generated_sha256'],'Generated binding differs')
    a=audit(q['typelib_path'],generated)
    runtime=[common._pin(x.__file__) for x in (catalogue,context,thread,save_support,dispatch,generation,events)]+[common._pin(__file__)]
    pins=common._merge(r['runtime_and_evidence_pins'],runtime,[rpin]);require(len(pins)<=64,'Bounded definition evidence required')
    require(common._key(p['expected_document_path']) not in {common._key(x['path']) for x in pins},'Mutable source cannot be an immutable proof pin')
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p)
    forbidden={common._key(x['path']) for x in pins}|{common._key(p['expected_document_path'])}
    require(len({common._key(receipt),common._key(marker)})==2 and not forbidden.intersection((common._key(receipt),common._key(marker))),'Output aliases source/evidence')
    require(all(x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in (receipt,marker)),'Fresh receipt and no prior pair attempt required')
    return dict(catalogue=r,catalogue_pin=rpin,pins=pins,registration=reg,typelib_path=q['typelib_path'],generated_pin=generated,abi=a,marker=marker)


def verify_before(state,observed,p):
    require(state['document']['needs_save'] is False and state['saved_file_sha256']==p['expected_source_sha256']
        and state['inventory']==observed['inventory_before'] and state['feature_header']==observed['before']['feature_header'],'Saved catalogue/reference changed')
    rows=state['operations'];require(len({x['native_id'] for x in rows})==len(rows),'Unique native operation IDs required')
    anchor=next(x for x in rows if x['native_id']==p['anchor_operation_native_id'])
    q=observed['request'];require(anchor['setup_index']==q['setup_index'] and anchor['operation_index']==q['operation_index']
        and anchor['turn_operation_type']==9 and anchor['linked_feature_ids']==[p['feature_native_id']]
        and anchor['suppressed'] is False,'Exact existing drill anchor required')
    require(not any(x['turn_operation_type'] in (1,2) and p['feature_native_id'] in x['linked_feature_ids'] for x in rows),'Target already has rough/finish definitions; no replay')


def verify_added(before,after,new_id,kind,feature_id,anchor_id):
    """Same exact TURN insertion delta as sw_cam_thread, bounded to rough/finish."""
    require(type(new_id) is int and new_id>0 and type(kind) is int and kind in (1,2),'Exact positive TURN insertion identity required')
    ids=[x['native_id'] for x in before['operations']];require(new_id not in ids,'Returned pre-existing operation')
    anchor=next(x for x in before['operations'] if x['native_id']==anchor_id);si=anchor['setup_index'];oi=anchor['operation_index']+1
    added=[x for x in after['operations'] if x['native_id']==new_id];require(len(added)==1,'Exactly one returned new operation required');new=added[0]
    require(new==dict(setup_index=si,operation_index=oi,native_id=new_id,turn_operation_type=kind,linked_feature_ids=[feature_id],suppressed=False),'New operation identity/position/feature differs')
    expected=deepcopy(before);expected['document']['needs_save']=after['document']['needs_save']
    require(type(after['document']['needs_save']) is bool,'Strict dirty flag required')
    at=ids.index(anchor_id)+1
    for x in expected['operations']:
        if x['setup_index']==si and x['operation_index']>=oi:x['operation_index']+=1
    expected['operations'].insert(at,deepcopy(new))
    for x in expected['inventory']['operations']:
        if x['setup_index']==si and x['operation_index']>=oi:x['operation_index']+=1
    expected['inventory']['operations'].insert(at,dict(setup_index=si,operation_index=oi,turn_operation_type=kind,toolpath_generated=False,toolpath_record_counts=[]))
    expected['inventory']['operation_count']+=1
    require(expected==after,'Insertion changed protected state, existing paths or more than one definition')
    return deepcopy(new)


def stable_save_state(state):
    result=deepcopy(state);result.pop('saved_file_sha256');result['document']['needs_save']=False;return result


class NativeBackend:
    def __init__(self,sw,p,plan,report,persist):
        self.sw,self.p,self.plan,self.report,self.persist=sw,p,plan,report,persist
        self.session=None;self.active=False;self.source=p['expected_source_sha256'];self.typelib=plan['typelib_path'];self.calls=0;self.native=None
        self.owner=_process_identity(p['process_id']);require(self.owner.get('alive') is True,'Owned process absent')
    def owned(self):
        now=_process_identity(self.p['process_id']);require(now.get('alive') is True and now.get('process_id')==self.owner.get('process_id') and now.get('create_time')==self.owner.get('create_time') and _same_path(now.get('executable',''),self.owner.get('executable','')),'Owned process changed')
    def identity(self):
        self.owned();require(type(_member(self.sw,'GetProcessID')) is int and _member(self.sw,'GetProcessID')==self.p['process_id'],'Owned PID changed')
        d=raw_part_identity(self.sw);require(type(d['needs_save']) is bool,'Strict dirty flag required')
        check_document_target(d['path'],d['title'],expected_path=self.p['expected_document_path'],required=True)
        require(_file_hash(d['path'])==self.source,'Saved source changed');return d
    def event_check(self):
        s=self.session.summary();self.report['messages']=s
        require(s.get('active') is True and s.get('subscribed') is True and not any(s.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event requires stop')
    def boundary(self):common._check(self.plan['pins']);self.identity();self.event_check()
    def read(self,obj,name,*args):
        require(name in catalogue.READ_MEMBERS and self.calls<3500,'Bounded known TURN getter required');self.calls+=1
        self.report.update(current_read=name,read_dispatch_pending=True);self.event_check();value=_member(obj,name,*args);self.event_check();self.report['read_dispatch_pending']=False;return value
    def start(self):
        initial=self.identity();require(initial['needs_save'] is False,'Clean saved source required');common._check(self.plan['pins'])
        addin=_member(self.sw,'GetAddInObject',self.plan['catalogue']['request']['addin_clsid']);require(addin is not None,'Existing CAM addin required')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',self.typelib);self.session=events.CamMessageSession(app,self.typelib);self.session.__enter__();self.active=True
        require(self.identity()==initial,'Initial binding changed');self.boundary()
    def capture(self,label):
        self.boundary();d=self.identity();_,doc,_,machine,app=context._context(self.sw,self.plan['catalogue']['request']['addin_clsid'],self.typelib,self.read)
        inventory=context._inventory(machine,self.typelib,self.read);rows=[];handles={};feature_ids=[];target=None
        for si,raw in enumerate(context._items(self.read(machine,'IGetEnumSetups'),self.typelib,self.read,limit=8)):
            setup=_typed(raw,'ICWBaseSetup',self.typelib)
            ids=[]
            for f in context._items(self.read(setup,'IGetEnumFeatures'),self.typelib,self.read,limit=64):
                fid=_object_id(doc,f,self.read);ids.append(fid)
                if fid==self.p['feature_native_id']:require(target is None,'Duplicate target feature');target=f
            feature_ids.append(dict(setup_index=si,native_ids=ids))
        require(target is not None,'Existing ID feature absent');header,feature=catalogue.feature_header(target,self.typelib,self.read)
        for si,raw in enumerate(context._items(self.read(machine,'IGetEnumOpSetups'),self.typelib,self.read,limit=8)):
            setup=_typed(raw,'ICWBaseOpSetup',self.typelib)
            for oi,rawop in enumerate(context._items(self.read(setup,'IGetEnumOperations'),self.typelib,self.read,limit=32)):
                op=_typed(rawop,'ICWOperation',self.typelib);turn=_typed(rawop,'ICWTurnOperation',self.typelib);oid=_object_id(doc,op,self.read)
                linked=context._items(self.read(op,'IGetAllFeatures'),self.typelib,self.read,limit=4)
                rows.append(dict(setup_index=si,operation_index=oi,native_id=oid,turn_operation_type=self.read(turn,'OpernType'),linked_feature_ids=[_object_id(doc,f,self.read) for f in linked],suppressed=self.read(op,'Suppressed')));require(oid not in handles,'Duplicate operation ID');handles[oid]=op
        require(len(rows)==inventory['operation_count'] and self.identity()==d,'Capture changed identity/count')
        self.native=dict(doc=doc,feature=feature,app=app,operations=handles)
        self.boundary();return dict(document=d,saved_file_sha256=self.source,inventory=inventory,operations=rows,feature_ids=feature_ids,feature_header=header)
    def catalogue_check(self):
        actual=catalogue.read_catalogues(self.native['feature'],read=self.read,record=lambda k,v:None)
        require(actual==self.plan['catalogue']['catalogues'],'Observed feature default catalogue changed')
    def insert(self,spec,anchor,pending):
        current=self.identity();self.boundary()
        with dispatch.ScopedCamDispatchGuard(self.sw,self.typelib,process_id=self.p['process_id'],expected_document=current,source_sha256=self.source,evidence_pins=self.plan['pins'],verify_evidence=lambda:common._check(self.plan['pins']),verify_owned_process=self.owned,check_events=self.event_check) as g:
            feature=g.typed(self.native['feature'],'ICWTurnFeature');previous=g.typed(self.native['operations'][anchor],'ICWOperation')
            raw=g.dispatch_once(lambda:_member(feature,'InsertOperation',spec['operation_type'],spec['default_operation_id'],previous),persist_pending=pending)
        self.report.setdefault('dispatch_guards',[]).append(g.summary());self.event_check()
        from scripts.sw_cam_comtypes import _is_comtypes_pointer
        require(_is_comtypes_pointer(raw) and bool(raw),'One returned native operation pointer required')
        return _object_id(self.native['doc'],raw,self.read)
    def save(self):
        self.boundary();app=_typed(self.native['app'],'ICWApp',self.typelib);self.boundary();return _member(app,'SaveActiveDocument')
    def saved_hash(self):
        value=_file_hash(self.p['expected_document_path']);require(value!=self.source,'Definition Save must change source bytes')
        self.source=value;require(self.identity()['needs_save'] is False,'Saved document must be clean');return value
    def finish(self):
        self.boundary();self.session.__exit__(None,None,None);self.active=False;self.report['messages']=self.session.summary();clean_events(self.report);common._check(self.plan['pins']);self.identity()
    def close(self):
        if self.active:
            try:self.session.__exit__(None,None,None)
            finally:self.active=False
        if self.session is not None:self.report['messages']=self.session.summary();clean_events(self.report)


def run_backend(backend,p,plan,r,persist):
    claimed=False
    def pending(label):
        nonlocal claimed
        require(label not in r['actions'],'No repeated native action')
        r.update(phase=label,mutation_attempted=True,native_dispatch_pending=True)
        r['actions'][label]=dict(attempted=True,pending=True,returned=False,readback_verified=False)
        if not claimed:
            _write_receipt(plan['marker'],dict(scope=SCOPE,source_sha256=p['expected_source_sha256'],feature_native_id=p['feature_native_id'],anchor_operation_native_id=p['anchor_operation_native_id'],receipt_path=p['receipt_path'],status='claimed_no_replay'),create=True);claimed=True
        persist()
    try:
        backend.start();r['before']=backend.capture('before');verify_before(r['before'],plan['catalogue'],p);backend.catalogue_check();persist()
        current=r['before'];anchor=p['anchor_operation_native_id']
        for spec in p['definitions']:
            label='InsertOperation_'+str(spec['operation_type']);new_id=backend.insert(spec,anchor,lambda:pending(label))
            r['actions'][label].update(returned=True,pending=False,new_native_id=new_id);r['native_dispatch_pending']=False;persist()
            after=backend.capture(label+'_readback');r.setdefault('insertion_observations',[]).append(deepcopy(after));persist()
            new=verify_added(current,after,new_id,spec['operation_type'],p['feature_native_id'],anchor)
            r.setdefault('new_operations',[]).append(new);r['actions'][label]['readback_verified']=True;persist();current=after;anchor=new_id
        expected=stable_save_state(current);r['save_stage']={}
        def capture(label):
            if label=='before':backend.boundary();return deepcopy(expected)
            actual=backend.capture('saved');r['final_state']=actual;persist();return stable_save_state(actual)
        def verify(value):require(value==expected,'Save changed protected TURN definition state')
        def save():
            result=backend.save();r['actions']['SaveActiveDocument'].update(returned=True,pending=False,native_return_value=result,native_return_type=type(result).__name__);r['native_dispatch_pending']=False;persist();return result
        def saved_hash():
            value=backend.saved_hash();r['saved_source_sha256']=value;r['source_transition']=dict(source_before_sha256=p['expected_source_sha256'],source_after_sha256=value,strict_save_return=0);persist();return value
        save_support.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=backend.boundary,claim=lambda:pending('SaveActiveDocument'),persist=persist,save=save,saved_hash=saved_hash)
        r['actions']['SaveActiveDocument']['readback_verified']=True;r['model_saved']=True;backend.finish();r.update(status='saved_definitions_no_toolpath',phase='finished',readback_verified=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',cleanup_issue=_error(exc),readback_verified=False)
        persist()
    return r


def validate_saved(r):
    validate_specs(r['request']['definitions'])
    require(r['scope']==SCOPE and r['status']=='saved_definitions_no_toolpath' and r['phase']=='finished' and r['readback_verified'] is True and r['model_saved'] is True,'Completed definition pair required')
    require(all(r[k] is False for k in FORBIDDEN) and not any(k in r for k in ('issue','failed_phase','cleanup_issue')),'Unexpected mutation or incomplete definition pair')
    require(set(r['actions'])=={'InsertOperation_1','InsertOperation_2','SaveActiveDocument'} and r['native_dispatch_pending'] is False,'Exact completed actions required')
    for action in r['actions'].values():require(action['attempted'] is True and action['returned'] is True and action['pending'] is False and action['readback_verified'] is True,'Action incomplete')
    current=r['before'];anchor=r['request']['anchor_operation_native_id'];require(len(r['insertion_observations'])==2 and len(r['new_operations'])==2,'Exact pair observations required')
    for spec,after,row in zip(r['request']['definitions'],r['insertion_observations'],r['new_operations']):
        require(r['actions']['InsertOperation_'+str(spec['operation_type'])]['new_native_id']==row['native_id'],'Action/result ID differs')
        require(verify_added(current,after,row['native_id'],spec['operation_type'],r['request']['feature_native_id'],anchor)==row,'Recorded insertion delta differs');current=after;anchor=row['native_id']
    require(stable_save_state(current)==stable_save_state(r['final_state']) and r['final_state']['document']['needs_save'] is False and r['final_state']['saved_file_sha256']==r['saved_source_sha256'],'Saved definition state differs')
    s=r['save_stage'];a=r['actions']['SaveActiveDocument'];require(s['save_readback_verified'] is True and type(a['native_return_value']) is int and a['native_return_value']==0 and s['saved_file_sha256']==r['saved_source_sha256'],'Strict native Save proof required')
    t=r['source_transition'];require(t==dict(source_before_sha256=r['initial_source_sha256'],source_after_sha256=r['saved_source_sha256'],strict_save_return=0) and type(t['strict_save_return']) is int and r['saved_source_sha256']!=r['initial_source_sha256'],'Exact nonempty source transition required')
    clean_events(r);return r['final_state']


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest);state=validate_saved(r)
    observed,_=read_pin(r['catalogue_pin']['path'],r['catalogue_pin']['sha256']);validate_catalogue(observed,r['request']);verify_before(r['before'],observed,r['request'])
    require(r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path) and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved definition owner/source differs')
    common._check(r['runtime_and_evidence_pins']);require(r['module_pin']==common._pin(__file__),'Definition writer changed')
    marker=marker_path(r['request']);m,mpin=read_pin(str(marker),r['marker_pin']['sha256']);require(m==dict(scope=SCOPE,source_sha256=r['initial_source_sha256'],feature_native_id=r['request']['feature_native_id'],anchor_operation_native_id=r['request']['anchor_operation_native_id'],receipt_path=r['request']['receipt_path'],status='claimed_no_replay') and common._key(m['receipt_path'])==common._key(path),'Once marker differs')
    return dict(authority_kind='saved_turn_bore_definitions_no_toolpath',state=deepcopy(state),new_operations=deepcopy(r['new_operations']),feature_native_id=r['request']['feature_native_id'],source_sha256=expected_source_sha256,parent_pin=pin,pins=common._merge(r['runtime_and_evidence_pins'],[pin,mpin]),tooling_qualified=False,depths_qualified=False,GTP_authorized=False)


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);plan=prepare(p)
    if validate_only:return dict(status='validated_offline',native_called=False,abi=plan['abi'],definition_specs=p['definitions'],feature_native_id=p['feature_native_id'],anchor_operation_native_id=p['anchor_operation_native_id'],native_insert_calls=2,native_save_calls=1,GTP_calls=0,live_pin_count=len(plan['pins']))
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',request=p,process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],catalogue_pin=plan['catalogue_pin'],module_pin=common._pin(__file__),runtime_and_evidence_pins=plan['pins'],abi=plan['abi'],actions={},native_dispatch_pending=False,mutation_attempted=False,readback_verified=False,model_saved=False,tooling_qualified=False,depths_qualified=False,**{k:False for k in FORBIDDEN})
        persist=lambda:_write_receipt(p['receipt_path'],r);_write_receipt(p['receipt_path'],r,create=True)
        backend=NativeBackend(sw,p,plan,r,persist);run_backend(backend,p,plan,r,persist)
        if r['readback_verified'] is True:
            try:common._check(plan['pins']);r['marker_pin']=common._pin(plan['marker']);validate_saved(r)
            except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
            persist()
        return r


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--validate-only',action='store_true');a=parser.parse_args(argv)
    r=dispatch_request(json.loads(Path(a.request).read_text(encoding='utf-8-sig')),validate_only=a.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','new_operations','saved_source_sha256','issue','native_called')},ensure_ascii=False));return 0 if r.get('readback_verified') or r.get('status')=='validated_offline' else 1
if __name__=='__main__':raise SystemExit(main())