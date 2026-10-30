"""Read-only reconciliation of one returned FACE insertion with unchanged SW save flag.

The failed creator receipt and marker remain immutable. No insertion, assignment,
generation or persistence operation is available here. Recovery captures the route
and compares the actual unchanged False save flag without substituting True.
"""
from copy import deepcopy
from pathlib import Path
import json,re
from scripts import sw_cam_raw_mill_face_operation as creator
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_route_context import integer
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch

SCOPE='RAW_MILL_FACE_INSERT_READONLY_RECOVERY_V1'
READ_MEMBERS=frozenset({'GetCWObjectID','Count','Item','IGetEnumOpSetups','IGetEnumOperations','OpernType',
 'Suppressed','GetIsToolpathGenerated','IGetAllFeatures'})
READ_INTERFACES=frozenset({'ICWDispatchCollection','ICWBaseOpSetup','ICWOperation','ICWMillOperation'})


def _key(path):return str(Path(path).resolve()).casefold()
def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)


def verify_recovery_delta(before,after,new_id,face_id,*,diagnostic=None):
    integer(new_id,'New operation ID',1);integer(face_id,'Face ID',1)
    require(len(before['features'])==len(after['features'])==21,'Exact21 features required')
    old=before['operations'];rows=after['operations']
    require(tuple(r['native_id'] for r in old)==creator.OLD_OPERATION_IDS and before['operation_count']==6,'Exact saved six-operation baseline required')
    require(new_id not in creator.OLD_OPERATION_IDS and len(rows)==7 and after['operation_count']==7,'Exactly one new operation required')
    expected_order=list(creator.OLD_OPERATION_IDS);expected_order.insert(4,new_id)
    require([r['native_id'] for r in rows]==expected_order,'New FACE must follow196 before247')
    added=deepcopy(rows[4]);known={r['geometry']['native_id'] for r in before['features']}|{r['native_id'] for r in before['feature_setups']}|{r['native_id'] for r in before['operation_setups']}|{r['assigned_tool']['native_id'] for r in old}
    require(new_id not in known,'New operation identity collides with existing object')
    required=dict(setup_index=0,setup_native_id=93,operation_index=4,native_id=new_id,mill_operation_type=20,base_operation_type=0,
      suppressed=False,toolpath_generated=False,linked_feature_ids=[face_id],toolpath_record_counts=[])
    require(set(added)==set(required)|{'assigned_tool'} and all(added[k]==v and type(added[k]) is type(v) for k,v in required.items()),'New FACE type/links/flags/counts differ')
    if added['assigned_tool'] is not None:
        tool=added['assigned_tool'];require(type(tool) is dict and tool.get('native_read_complete') is True and tool.get('is_mill_tool') is True,'Non-null tool must be observed')
        integer(tool.get('native_id'),'Observed default tool ID',1)
    require(before['document']['needs_save'] is False and after['document']['needs_save'] is False,'Actual unchanged False SW save flag required')
    normalized=deepcopy(after)
    require(before['operation_counts']==[6,0,0] and after['operation_counts']==[7,0,0],'Only setup93 count may increase')
    normalized['operation_counts']=[6,0,0];normalized['operation_count']=6
    require(after['operation_setups']==[dict(index=0,native_id=93,operation_count=7),dict(index=1,native_id=94,operation_count=0),dict(index=2,native_id=95,operation_count=0)],'Operation setups changed')
    normalized['operation_setups']=deepcopy(before['operation_setups']);normalized['operations'].pop(4)
    for index,row in enumerate(normalized['operations']):
        require(row['operation_index']==index+(index>=4),'Unexpected old operation index change');row['operation_index']=index
    creator.cone.require_state_equivalent(before,normalized,diagnostic=diagnostic)
    return added


def load_failed_face_operation(path,digest,*,process_id,expected_document_path,expected_source_sha256,expected_feature_native_id):
    data,pin=read_pin(path,digest)
    require(data.get('scope')==creator.SCOPE and data.get('status')=='uncertain' and data.get('phase')=='finished'
      and data.get('failed_phase')=='InsertOperation' and data.get('operation_module_pin')==_pin(creator.__file__),'Exact immutable returned creator failure required')
    require(data.get('process_id')==process_id and _key(data['expected_document_path'])==_key(expected_document_path)
      and data['expected_source_sha256']==expected_source_sha256 and data['face_feature_native_id']==expected_feature_native_id,'Failed creator identity differs')
    require(type(data.get('creator_call_count')) is int and data['creator_call_count']==1 and data.get('native_return_type')=='POINTER(ICWFaceMillOp)'
      and all(data.get(k) is True for k in ('mutation_attempted','native_call_attempted','native_call_returned'))
      and all(data.get(k) is False for k in ('native_dispatch_pending','readback_verified','operation_delta_verified','GOP_attempted','GTP_attempted',
      'tool_assignment_attempted','save_attempted','model_saved','CAD_solid_edit_attempted','sketch_edit_attempted','automatic_replay','automatic_retry','automatic_rollback')),
      'Only one returned unverified insertion is recoverable')
    require(not any(k in data for k in ('new_operation_native_id','after_context','checkpoint','receipt_write_error')),'Unexpected later phase or write failure')
    issue=data.get('issue',{});require(issue.get('type')=='ValueError' and issue.get('locations')==[
      dict(file='sw_cam_raw_mill_face_operation.py',function='insert_raw_mill_face_operation',line=462),
      dict(file='sw_cam_rough_firstcut.py',function='require',line=38)],'Unexpected failed assertion')
    clean_events(data);parent=data['parent_pin']
    loaded=creator.load_face_operation_parent(parent['path'],parent['sha256'],process_id=process_id,expected_document_path=expected_document_path,
      expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    require(canonical_evidence_pins(data['evidence_pins'])==canonical_evidence_pins(loaded['pins'])
      and canonical_evidence_pins(data['lineage_pins'])==canonical_evidence_pins(loaded['lineage_pins']),'Failed creator dependency scope differs')
    creator.cone.require_state_equivalent(loaded['state'],data['before_context'])
    require(data['document_after_creator']==data['before_context']['document'] and data['document_after_creator']['needs_save'] is False,'Failure must be only unchanged SW False flag')
    require(data['before_payload']==creator._payload(loaded),'Prior protected payload differs')
    for label in ('cone','face'):require(data['before_'+label+'_observation']==loaded[label+'_observation'],'Prior feature observation differs')
    marker=creator.insert_marker(expected_document_path,expected_source_sha256,expected_feature_native_id)
    mark,markpin=read_pin(str(marker),_file_hash(marker))
    require(_key(data['marker_path'])==_key(marker) and mark.get('scope')==creator.SCOPE and mark.get('status')=='uncertain'
      and _key(mark['source'])==_key(expected_document_path) and mark['source_sha256']==expected_source_sha256
      and mark['face_feature_native_id']==expected_feature_native_id and mark['after_operation_native_id']==196 and mark['operation_type']==20
      and _key(mark['receipt_path'])==_key(path) and mark['receipt_sha256']==digest and mark.get('native_call_attempted') is True
      and mark.get('native_call_returned') is True and mark.get('readback_verified') is False and mark.get('automatic_replay') is False,
      'Exact original uncertain marker required')
    retired=[]
    for row in loaded['pins']:
        name=Path(row['path']).name
        if _key(row['path'])==_key(parent['path']):retired.append(row)
        elif name=='97a_saved_route_manifest.json':
            obj,_=read_pin(row['path'],row['sha256']);require(obj.get('scope')=='SAVED_ROUTE_MANIFEST_94_95_96_V1' and obj.get('status')=='validated_offline','Completed saved manifest required');retired.append(row)
        elif name=='RESULT.json' and Path(row['path']).parent.name=='finish_square_candidate_20261030':
            obj,_=read_pin(row['path'],row['sha256']);require(obj.get('status')=='NOMINAL_VIRTUAL_FINISH_CANDIDATE_REVIEWED_NOT_ASSIGNED'
              and obj.get('production_qualified') is False and obj.get('native_CAD_calls')==0,'Completed nominal research report required');retired.append(row)
    require(len(retired)==3,'Exactly three reviewed completed ancestors must retire')
    removed={_key(v['path']) for v in retired};pins=canonical_evidence_pins([v for v in loaded['pins'] if _key(v['path']) not in removed],[_self_pin(),pin,markpin])
    history=canonical_evidence_pins(loaded['lineage_pins'],retired);require(len(pins)==64 and len(history)==13,'Exact64live/13history recovery closure required')
    out=dict(loaded);out.update(pins=pins,lineage_pins=history,failed_receipt=data,failed_pin=pin,failed_marker_pin=markpin,
      parent_pin=pin,saved_parent_pin=parent,retired_ancestor_pins=retired,recovery_module_pin=_self_pin(),failure_resolved=False)
    return out


class DiscoveryReadBatch(ScopedCamReadBatch):
    def read(self,obj,name,*args):
        try:
            require(name in READ_MEMBERS,'Outside discovery getter scope')
            for value in args:require(type(value) is int or id(value) in self._known_objects,'Outside retained discovery graph')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(name in READ_INTERFACES,'Outside discovery interface scope')
            return self._observe_read(obj,'qi',lambda:_typed(obj,name,self.typelib_path))
        except BaseException:self._invalid=True;self._completed=False;raise


def read_discovery_rows(doc,machine,*,read,typed,report,persist):
    rows=[];report['discovered_rows']=rows;report['discovered_setups']=[];persist()
    for si,value in enumerate(_items(read(machine,'IGetEnumOpSetups'),typed,read,3)):
        setup=typed(value,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        operations=_items(read(setup,'IGetEnumOperations'),typed,read,7)
        report['discovered_setups'].append(dict(index=si,native_id=sid,operation_count=len(operations)));persist()
        for oi,raw in enumerate(operations):
            op=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation')
            row=dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=_object_id(doc,op,read))
            rows.append(row);persist()
            for key,obj,name in (('base_operation_type',op,'OpernType'),('mill_operation_type',mill,'OpernType'),
                ('suppressed',op,'Suppressed'),('toolpath_generated',op,'GetIsToolpathGenerated')):
                row[key]=read(obj,name);persist()
            row['linked_feature_ids']=[_object_id(doc,feat,read) for feat in _items(read(op,'IGetAllFeatures'),typed,read,64)];persist()
    return rows


def verify_discovery(report,before,face_id):
    rows=report['discovered_rows'];require(len(rows)==7 and len({r['native_id'] for r in rows})==7,'Exactly seven unique operations required')
    new=rows[4];newid=integer(new['native_id'],'Discovered operation ID',1)
    require(newid not in creator.OLD_OPERATION_IDS,'Existing operation cannot be recovery target')
    expected=deepcopy(before['operations'])
    for r in expected:
        for key in ('assigned_tool','toolpath_record_counts'):r.pop(key)
        if r['operation_index']>=4:r['operation_index']+=1
    expected.insert(4,dict(setup_index=0,setup_native_id=93,operation_index=4,native_id=newid,base_operation_type=0,mill_operation_type=20,
      suppressed=False,toolpath_generated=False,linked_feature_ids=[face_id]))
    require(_digest(rows)==_digest(expected),'Discovered insertion target or protected summaries differ')
    require(report['discovered_setups']==[dict(index=0,native_id=93,operation_count=7),dict(index=1,native_id=94,operation_count=0),dict(index=2,native_id=95,operation_count=0)],'Exact original setup identities required')
    return newid


def discover_operation(ctx,report,persist):
    with ctx.guard() as g:
        active=g.read(ctx.app,'IGetActiveDoc');doc=g.typed(active,'ICWDoc3')
        machine=g.typed(g.read(g.typed(active,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    def binding():
        ctx.events();kind=_member(doc,'GetDocType');mach=_member(machine,'MachType');ctx.events()
        require(type(kind) is int and kind==1 and type(mach) is int and mach==1,'Retained discovery part/MILL changed')
    batch=DiscoveryReadBatch(ctx.sw,ctx.typelib_path,retained_objects=(doc,machine),verify_retained_binding=binding,max_native_calls=180,
      process_id=ctx.args['process_id'],expected_document=ctx.identity(),source_sha256=ctx.args['expected_source_sha256'],
      evidence_pins=ctx.loaded['pins'],verify_evidence=ctx.files,verify_owned_process=ctx.owned,check_events=ctx.events)
    try:
        with batch:read_discovery_rows(doc,machine,read=batch.read,typed=batch.typed,report=report,persist=persist)
        batch.require_complete();return verify_discovery(report,ctx.loaded['state'],ctx.args['face_feature_native_id'])
    finally:report['discovery_read_batch']=batch.summary();persist()


def recover_face_operation(sw,clsid,typelib_path,*,failed_receipt_path,failed_receipt_sha256,process_id,expected_document_path,
        expected_source_sha256,expected_feature_native_id,receipt_path):
    from scripts.sw_cam_events import CamMessageSession
    loaded=load_failed_face_operation(failed_receipt_path,failed_receipt_sha256,process_id=process_id,expected_document_path=expected_document_path,
      expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    receipt=Path(receipt_path);protected={_key(v['path']) for v in loaded['pins']+loaded['lineage_pins']}|{_key(expected_document_path)}
    require(receipt.is_absolute() and receipt.parent.is_dir() and receipt.suffix.casefold()=='.json' and not receipt.exists()
      and not receipt.is_symlink() and _key(receipt) not in protected,'Fresh recovery evidence output required')
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,source_path=expected_document_path,
      source_sha256=expected_source_sha256,failed_pin=loaded['failed_pin'],failed_marker_pin=loaded['failed_marker_pin'],module_pin=_self_pin(),
      saved_parent_pin=loaded['saved_parent_pin'],evidence_pins=deepcopy(loaded['pins']),lineage_pins=deepcopy(loaded['lineage_pins']),
      retired_ancestor_pins=deepcopy(loaded['retired_ancestor_pins']),face_feature_native_id=expected_feature_native_id,receipt_path=str(receipt),
      read_only=True,mutation_attempted=False,creator_attempted=False,tool_assignment_attempted=False,GOP_attempted=False,GTP_attempted=False,
      save_attempted=False,model_saved=False,set_save_flag_attempted=False,automatic_replay=False,readback_verified=False,state_recovered=False,
      original_failure_resolved=False,recipe_qualified=False,production_qualified=False,may_generate=False)
    created=False;session=None
    def persist():
        if created:_write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
          and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM events require stop')
    try:
        _write_receipt(receipt,report,create=True);created=True
        args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
          **loaded['ids']);args['face_feature_native_id']=expected_feature_native_id
        ctx=creator.FaceOperationContext(loaded,args,sw,typelib_path,None,events,loaded['state'])
        ctx.files();ctx.identity();ctx.app=creator.cone._bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity()
        session=CamMessageSession(ctx.app,typelib_path)
        with session:
            report['phase']='discover_only';persist();newid=discover_operation(ctx,report,persist)
            report.update(new_operation_native_id=newid,phase='capture_full_route');persist();diag={};report['capture_diagnostics']=diag
            try:
                state,native=creator._capture_headers(ctx,clsid,loaded['state'],21,diag,nullable_operation_id=newid)
                report['observed_context']=deepcopy(state);persist()
                payload=creator._capture_payload(ctx,state,native,diag,nullable_operation_id=newid)
                report['observed_payload']=deepcopy(payload);persist()
                cone_obs=creator.cone._read_sketch_and_cone(ctx,native,loaded['cone_sketch_spec'],loaded['cone_feature_native_id'])
                report['observed_cone']=deepcopy(cone_obs);persist();face_diag={};report['observed_face']=face_diag
                face_obs=creator.face._read_face(ctx,native,loaded['face_sketch_spec'],expected_feature_native_id,diagnostic=face_diag,persist=persist)
                report['observed_face']=deepcopy(face_obs);persist()
            finally:persist()
            report['state_equivalence']={};added=verify_recovery_delta(loaded['state'],state,newid,expected_feature_native_id,diagnostic=report['state_equivalence'])
            require(payload==creator._payload(loaded) and cone_obs==loaded['cone_observation'] and face_obs==loaded['face_observation'],'Protected payload or geometry changed')
            report['new_operation']=added;persist()
        events(False);ctx.files();require(ctx.identity()==state['document'],'Document changed during read cleanup')
        checkpoint=dict(state=deepcopy(state),payload=deepcopy(payload),cone_observation=deepcopy(cone_obs),face_observation=deepcopy(face_obs),
          cone_sketch_spec=deepcopy(loaded['cone_sketch_spec']),face_sketch_spec=deepcopy(loaded['face_sketch_spec']),
          cone_feature_native_id=loaded['cone_feature_native_id'],face_feature_native_id=expected_feature_native_id,
          new_operation_native_id=newid,source_sha256=expected_source_sha256)
        report.update(status='observed',phase='finished',readback_verified=True,state_recovered=True,original_failure_resolved=True,
          resolved_by=str(receipt),checkpoint=checkpoint,checkpoint_sha256=_digest(checkpoint),actual_SW_needs_save=False,
          CAM_insertion_persistence_verified=False,reason='EXACT_INSERTION_OBSERVED_SW_SAVE_FLAG_UNCHANGED_NO_MUTATION_OR_SAVE')
    except Exception as exc:report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),state_recovered=False,readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:persist()
        except Exception as exc:report.update(status='error',readback_verified=False,state_recovered=False,receipt_write_error=_error(exc))
    return report


def load_completed_face_operation_recovery(path,digest,*,process_id,expected_document_path,expected_source_sha256,
        expected_feature_native_id,expected_operation_native_id):
    data,pin=read_pin(path,digest)
    require(data.get('scope')==SCOPE and data.get('status')=='observed' and data.get('phase')=='finished' and data.get('module_pin')==_self_pin(), 'Completed exact recovery required')
    require(data.get('process_id')==process_id and _key(data['source_path'])==_key(expected_document_path) and data['source_sha256']==expected_source_sha256
      and data['face_feature_native_id']==expected_feature_native_id and data['new_operation_native_id']==expected_operation_native_id,'Recovery identity differs')
    require(all(data.get(k) is True for k in ('read_only','readback_verified','state_recovered','original_failure_resolved'))
      and all(data.get(k) is False for k in ('mutation_attempted','creator_attempted','tool_assignment_attempted','GOP_attempted','GTP_attempted','save_attempted',
      'model_saved','set_save_flag_attempted','automatic_replay','recipe_qualified','production_qualified','may_generate','actual_SW_needs_save','CAM_insertion_persistence_verified'))
      and not any(k in data for k in ('issue','failed_phase','receipt_write_error')),'Uncertain or broadened recovery forbidden')
    clean_events(data);failed=data['failed_pin']
    loaded=load_failed_face_operation(failed['path'],failed['sha256'],process_id=process_id,expected_document_path=expected_document_path,
      expected_source_sha256=expected_source_sha256,expected_feature_native_id=expected_feature_native_id)
    require(canonical_evidence_pins(data['evidence_pins'])==canonical_evidence_pins(loaded['pins']) and canonical_evidence_pins(data['lineage_pins'])==canonical_evidence_pins(loaded['lineage_pins']), 'Recovery dependency scope differs')
    require(verify_discovery(data,loaded['state'],expected_feature_native_id)==expected_operation_native_id,'Recovery discovery target differs')
    added=verify_recovery_delta(loaded['state'],data['observed_context'],expected_operation_native_id,expected_feature_native_id)
    require(added==data['new_operation'] and data['observed_payload']==creator._payload(loaded)
      and data['observed_cone']==loaded['cone_observation'] and data['observed_face']==loaded['face_observation'],'Recovery protected data differs')
    checkpoint=dict(state=data['observed_context'],payload=data['observed_payload'],cone_observation=loaded['cone_observation'],face_observation=loaded['face_observation'],
      cone_sketch_spec=loaded['cone_sketch_spec'],face_sketch_spec=loaded['face_sketch_spec'],cone_feature_native_id=loaded['cone_feature_native_id'],
      face_feature_native_id=expected_feature_native_id,new_operation_native_id=expected_operation_native_id,source_sha256=expected_source_sha256)
    require(checkpoint==data['checkpoint'] and data['checkpoint_sha256']==_digest(checkpoint),'Recovery checkpoint differs')
    out=dict(loaded);out.update(state=deepcopy(checkpoint['state']),payload=deepcopy(checkpoint['payload']['rough']),finish_payload=deepcopy(checkpoint['payload']['finish']),
      checkpoint=deepcopy(checkpoint),checkpoint_sha256=data['checkpoint_sha256'],expected_operation=added,recovery_pin=pin,parent_pin=pin,failure_resolved=True,
      resolved_by=pin,full_creator_proof_verified=True,current_protected_route_revalidated=False)
    out['pins']=canonical_evidence_pins([v for v in loaded['pins'] if _key(v['path'])!=_key(failed['path'])],[pin])
    out['lineage_pins']=canonical_evidence_pins(loaded['lineage_pins'],[failed]);require(len(out['pins'])==64 and len(out['lineage_pins'])==14,'Exact64live/14history completed recovery required')
    return out


PARAMS={'failed_receipt_path','failed_receipt_sha256','process_id','expected_document_path','expected_source_sha256','expected_feature_native_id','receipt_path','addin_clsid','module_sha256'}
def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='recover_raw_mill_face_operation','Only readonly recovery action supported')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact recovery fields required')
    for key in ('process_id','expected_feature_native_id'):integer(p[key],key,1)
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Strict SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'],'Exact recovery implementation required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact CLSID required')
    return dict(p)

def dispatch_request(request):
    p=validate_request(request)
    # Offline evidence validation precedes even connecting to the owned process.
    load_failed_face_operation(**{('path' if k=='failed_receipt_path' else 'digest' if k=='failed_receipt_sha256' else k):v for k,v in p.items()
      if k not in ('receipt_path','addin_clsid','module_sha256')})
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return recover_face_operation(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),**p)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    args=parser.parse_args(argv);result=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:result.get(k) for k in ('scope','status','phase','readback_verified','new_operation_native_id','issue','receipt_path')},ensure_ascii=False))
    return 0 if result.get('state_recovered') is True else 1

if __name__=='__main__':raise SystemExit(main())
