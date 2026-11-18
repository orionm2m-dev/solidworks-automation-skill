"""Read two completed appended MILL definitions; no mutations or lead objects."""
from copy import deepcopy
from pathlib import Path
from ctypes import POINTER
from comtypes.automation import IDispatch
import json,math,re
from scripts import sw_cam_saved_finish_pair_recipe as recipe
from scripts import sw_cam_current_finish_read as finish
from scripts import sw_cam_chamfer_defaults as defaults
from scripts import sw_cam_rough_entry_parameters as rough
from scripts import sw_cam_pocket_pair_read as pocket
from scripts import sw_cam_append_finish_definitions as producer
from scripts import sw_cam_reconfigured_circular_wip_binding as ancestry
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_executable_launch import _process_identity
from scripts.sw_operation_guard import check_document_target,solidworks_operation_lock
require=recipe.require
SCOPE='SAVED_FINISH_PAIR_CONTEXT_READ_V1'
MAX_READS=2048
KEYS={'process_id','expected_process_create_time','expected_document_path','expected_source_sha256','definition_receipt_path','definition_receipt_sha256','definition_marker_path','definition_marker_sha256','producer_module_sha256','receipt_path','qualification_only','message_policy'}
GETTERS=finish.nc.GETTERS|defaults.GETTERS|set(finish.PAIRS)|set(finish.SCOPE_FLAGS)|{'GetCWObjectFromID','OpernType','DepthProcessOpt','QueryInterface'}|{name for group in (rough.ENTRY_FIELDS,rough.DEPTH_FIELDS,rough.BOUNDARY_FIELDS,rough.NC_FIELDS) for name,_ in group}


def load_completed(v):
    raw,_=read_pin(v['definition_receipt_path'],v['definition_receipt_sha256'])
    if raw.get('scope')=='SAVED_CIRCULAR_FLOOR_WALL_APPEND_V1':
        from scripts.sw_cam_saved_floor_wall_authority import load_completed as mixed_completed
        loaded=mixed_completed(v);unique={}
        for pin in loaded['pins']+[dict(path=p,sha256=_file_hash(p))for p in(__file__,recipe.__file__,finish.__file__,defaults.__file__,rough.__file__,pocket.__file__)]:
            key=str(Path(pin['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==pin['sha256'],'Conflicting immutable reader evidence');unique[key]=pin
        loaded['pins']=list(unique.values());return loaded
    pins=[]
    def read(path,sha):
        value,pin=read_pin(path,sha);pins.append(pin);return value,pin
    r,rp=read(v['definition_receipt_path'],v['definition_receipt_sha256']);marker,mp=read(v['definition_marker_path'],v['definition_marker_sha256'])
    require(r.get('scope')in recipe.PRODUCER_SCOPES and r.get('status')=='review_required'and r.get('phase')=='finished','Actual completed definition producer required')
    require(not any(k in r for k in ('issue','failed_phase','runtime_error','cleanup_error')),'Unresolved producer error')
    request=r['request'];require(request['expected_source_sha256']==r['source_before_sha256'],'Original producer source binding differs');require(request['process_id']==v['process_id']and type(request['process_id'])is int and request['expected_process_create_time']==v['expected_process_create_time']and type(request['expected_process_create_time'])is type(v['expected_process_create_time']),'Exact producer owner/lifetime required')
    require(ancestry.common.same_path(request['expected_document_path'],v['expected_document_path'])and ancestry.common.same_path(r['receipt_path'],rp['path'])and ancestry.common.same_path(r['dispatch_marker_path'],mp['path']),'Producer path binding differs');clean_events(r)
    previous,previous_pin=read(request['revision_receipt_path'],request['revision_receipt_sha256']);require(ancestry.common.same_path(r['authority_pin']['path'],previous_pin['path'])and r['authority_pin']['sha256']==previous_pin['sha256'],'Original authority pin differs');previous_marker=dict(path=request['revision_marker_path'],sha256=request['revision_marker_sha256']);rows=previous['postCL']['expected_generated_operations'];oid=previous['operation_native_id']
    bound=ancestry.bind_completed_revision(previous_pin,process_id=v['process_id'],process_create_time=v['expected_process_create_time'],source_path=v['expected_document_path'],source_sha256=r['source_before_sha256'],selected_operation_ids=[oid],protected_operation_ids=[x['operation_native_id']for x in rows if x['operation_native_id']!=oid],expected_generated_operations=rows,marker_pin=previous_marker,writer_pin=dict(path=producer.writer.__file__,sha256=_file_hash(producer.writer.__file__)),verify_current_source=False)
    require(bound.get('physical_source_verified')is False,'Historical source policy must remain explicit');original=bound['snapshot']
    actual_recipe,recipepin=read(r['recipe_pin']['path'],r['recipe_pin']['sha256']);require(ancestry.common.same_path(recipepin['path'],request['recipe_path'])and recipepin['sha256']==request['recipe_sha256'],'Recipe request binding differs');require(actual_recipe==r['recipe'],'Pinned definition recipe differs');producer.validate_recipe(actual_recipe,original)
    payload=recipe.validate_completed_payload(r,original,expected_scope=r['scope'],source_sha256=v['expected_source_sha256']);producer.writer.authority.pocket.verify_saved(r['inserted'],r['saved'],v['expected_source_sha256'])
    require(len(r['inserted_defaults'])==len(r['saved_defaults'])==2,'Exactly two before/after defaults required')
    for a,b in zip(r['inserted_defaults'],r['saved_defaults']):defaults.validate_defaults(a);defaults.validate_defaults(b);require(producer.fields.equal(a,b),'Defaults changed across Save')
    expected_marker=dict(scope=r['scope'],status='review_required',phase='finished',recipe_pin=r['recipe_pin'],source_before_sha256=r['source_before_sha256'],receipt_path=rp['path'],receipt_sha256=rp['sha256'],automatic_replay=False)
    if r['scope']=='SAVED_CIRCULAR_APPEND_FINISH_RECOVERY_V1':
        from scripts import sw_cam_append_finish_recovery as recovery
        require(r.get('mode')=='recovery_continue','Only completed recovery continuation qualifies')
        failure,fp=read(request['failure_receipt_path'],request['failure_receipt_sha256']);fm,fmp=read(request['failure_marker_path'],request['failure_marker_sha256']);recovery.validate_failure(failure,fm,request)
        inspection,ip=read(request['inspection_receipt_path'],request['inspection_receipt_sha256']);data=dict(state=original,recipe=actual_recipe,failure_pin=fp,failure_marker_pin=fmp);recovery.validate_inspection(inspection,data,request)
        require(producer.writer.same(failure['before'],previous['saved'])and r['new_operations'][0]==inspection['new_operations'][0]and producer.writer.same(r['observed'],inspection['confirm_observed']),'Recovered floor chain differs')
        require(producer.fields.equal(r['observed_defaults'],inspection['observed_defaults']),'Recovered floor default changed')
        require(r.get('failure_pin')==fp and r.get('failure_marker_pin')==fmp and r.get('inspection_pin')==ip,'Pinned recovery ancestry differs')
        expected_marker['failure_receipt_pin']=fp;names=['InsertOperation:wall','SaveActiveDocument'];module=recovery.__file__
    else:
        require(producer.writer.same(r['before'],original),'Original saved producer baseline differs');names=['InsertOperation:floor','InsertOperation:wall','SaveActiveDocument'];module=producer.__file__
    require(list(r['actions'])==names,'Exact definition/Save action sequence required')
    for name in names[:-1]:
        action=r['actions'][name];index=0 if name.endswith('floor')else 1
        require(action.get('attempted')is True and action.get('returned')is True and action.get('native_dispatch_pending')is False and action.get('native_return_type','').startswith('POINTER(')and action.get('native_return_value')is None and action.get('actual_operation_native_id')==r['new_operations'][index]['native_id'],'Actual returned and observed insertion differs')
    require(ancestry.common.same_path(marker['receipt_path'],expected_marker['receipt_path']),'Marker receipt path differs');adjusted=deepcopy(marker);adjusted['receipt_path']=expected_marker['receipt_path'];require(adjusted==expected_marker,'Consumed terminal definition marker differs')
    require(_file_hash(module)==v['producer_module_sha256']and any(ancestry.common.same_path(x['path'],module)and x['sha256']==v['producer_module_sha256']for x in r['evidence_pins']),'Exact completed producer module required')
    for pin in bound['pins']+r['evidence_pins']:
        if ancestry.common.same_path(pin['path'],v['expected_document_path']):
            require(pin['sha256']==r['source_before_sha256'],'Historical source pin differs');continue
        ancestry.common.direct(pin);pins.append(pin)
    pins.extend(dict(path=x,sha256=_file_hash(x))for x in (__file__,recipe.__file__,producer.__file__,ancestry.__file__,finish.__file__,defaults.__file__,module))
    unique={}
    for pin in pins:
        key=str(Path(pin['path']).resolve()).casefold();require(key not in unique or unique[key]['sha256']==pin['sha256'],'Conflicting immutable evidence');unique[key]=pin
    return dict(receipt=r,payload=payload,state=r['saved'],pins=list(unique.values()),receipt_pin=rp,marker_pin=mp,original=original,producer_lineage_verified=True)


def validate(v):
    require(type(v)is dict and set(v)==KEYS,'Exact Finish pair read request required')
    require(type(v['process_id'])is int and 0<v['process_id']<2**31 and type(v['expected_process_create_time'])in(int,float)and math.isfinite(v['expected_process_create_time'])and v['expected_process_create_time']>0,'Exact current owner required')
    require(v['qualification_only']is True and v['message_policy']=='vendor_default','Explicit read-only qualification required')
    for k,x in v.items():
        if k.endswith('_sha256'):require(type(x)is str and re.fullmatch('[0-9a-f]{64}',x),'Exact SHA required')
        if k.endswith('_path'):require(type(x)is str and Path(x).is_absolute(),'Absolute paths required')
    src=Path(v['expected_document_path']);require(src.is_file()and not src.is_symlink()and src.suffix.lower()=='.sldprt'and _file_hash(src)==v['expected_source_sha256'],'Exact current saved source required')
    loaded=load_completed(v);out=Path(v['receipt_path']);require(out.parent.is_dir()and out.suffix.lower()=='.json'and not out.exists()and not out.is_symlink(),'Fresh read-only receipt required')
    require(all(out.resolve()!=Path(p['path']).resolve()for p in loaded['pins'])and out.resolve()!=src.resolve(),'Receipt may not alias evidence/source');loaded['output']=out;return loaded


def preflight(tlb):
    classes,abi=finish.preflight(tlb)
    for name in defaults.INTERFACES|{'ICWRghMillOp'}:classes[name]=_interface_class(name,tlb)
    classes['IDispatch']=IDispatch;classes.pop('ICWLeadInOut',None);return classes,abi


def read_target(raw,feature,identity,read,typed,pointer,persist,partial):
    kind=identity.get('operation_kind',1);require(type(kind)is int and kind in(0,1),'Only explicit Rough/Finish kinds allowed')
    partial.update(identity,capture_complete=False,leads=dict(status='not_observed',reason='LEAD_OBJECTS_EXCLUDED_FROM_THIS_READ'))
    if kind==1:
        partial['defaults']=defaults.read_defaults(raw,feature,read=read,typed=typed,persist=persist,diagnostic=partial.setdefault('defaults_diagnostic',{}));persist()
        f=typed(raw,'ICWFinishMillOp');f3=typed(raw,'ICWFinishMillOp3');pairs={name:finish.diagnostics._scalar(read(f3,name),'double_bool')for name in finish.PAIRS};partial['depth_and_side_pairs']=pairs;persist()
        flags={name:finish.diagnostics._scalar(read(f3,name),'bool')for name in finish.SCOPE_FLAGS};flags['DepthProcessOpt']=finish.diagnostics._scalar(read(f,'DepthProcessOpt'),'long');partial['finish_scope']=flags;persist()
    else:
        partial['rough_diagnostic']={}
        def rough_read(owner,name,*args):
            persist()
            try:return read(owner,name,*args)
            finally:persist()
        dispatch=typed(feature,'IDispatch');partial['rough']=rough.read_rough_entry_parameters(raw,dispatch,read=rough_read,typed=typed,diagnostic=partial['rough_diagnostic']);persist()
        partial['level_state']=pocket.read_levels(raw,feature,read=read,typed=typed,feature_dispatch=lambda obj:typed(obj,'IDispatch'));persist()
        partial['level_state']['levels']['machining_depth_value_native']=defaults.scalar('GetMachiningDepthValue',read(typed(raw,'ICWMillOperation3'),'GetMachiningDepthValue',dispatch));persist()
    read_nc(raw,read,typed,pointer,persist,partial);partial['capture_complete']=True;persist();return partial


def read_nc(raw,read,typed,pointer,persist,partial,*,saved_feeds=None):
    ncraw=read(typed(raw,'ICWMillOperation'),'IGetNCParam');n1=typed(ncraw,'ICWNCParam');n2=typed(ncraw,'ICWNCParam2');n4=typed(ncraw,'ICWNCParam4')
    values=deepcopy(saved_feeds)if saved_feeds is not None else{name:read(n1,name)for name in('GetSpndlSpeed','GetCNCComp','GetTlpComp')}
    if saved_feeds is None:values['XYFeed']=read(n2,'XYFeed')
    for name in ('GetSpeedFeedMethod','LinkToTool','GetIsLockSpindleSpeed','GetZFeedrate2','GetLeadinFeedratePercent'):values[name]=read(n4,name)
    for name in ('GetSpndlSpeed','XYFeed','GetLeadinFeedratePercent'):values[name]=finish.nc.finite(values[name])
    for name in ('GetCNCComp','GetTlpComp','GetSpeedFeedMethod'):require(type(values[name])is int,'Strict NC enum required')
    for name in ('LinkToTool','GetIsLockSpindleSpeed'):require(type(values[name])is bool,'Strict NC flag required')
    require(values['GetSpeedFeedMethod']in(0,1,2),'Declared NC mode required');values['GetZFeedrate2']=finish.diagnostics._scalar(values['GetZFeedrate2'],'double_bool');detail={};partial['leadin_pointer_diagnostic']=detail;values['leadin_feed']=pointer(n1,detail);partial['nc']=values;persist();return values


def read_missing_target(raw,feature,identity,saved_observation,authority_pin,read,typed,pointer,persist,partial):
    """Read only absent scalar modes; explicitly retain source-pinned saved groups."""
    kind=identity['operation_kind'];require(type(kind)is int and kind in(0,1),'Explicit selected kind required')
    require(saved_observation['operation_kind']==kind and saved_observation['operation_native_id']==identity['operation_native_id']and saved_observation['feature_native_id']==identity['feature_native_id'],'Reused saved observation identity differs')
    partial.update(identity,capture_complete=False,leads=dict(status='not_observed',reason='LEAD_OBJECTS_EXCLUDED_FROM_THIS_READ'),reused_from_terminal=dict(authority_pin=deepcopy(authority_pin),groups=['own_nc.feeds_compensation']),fresh_observation_groups=[])
    if kind==0:
        params=saved_observation['parameters'];require(params['read_complete']is True and params['rough']['parameter_reads_complete']is True,'Complete saved Rough required')
        partial['rough']=deepcopy(params['rough']);partial['rough_diagnostic']=deepcopy(params['rough_diagnostic']);partial['level_state']=deepcopy(params['levels']);partial['reused_from_terminal']['groups']+=['rough','rough_diagnostic','level_state'];persist()
        dispatch=typed(feature,'IDispatch');partial['level_state']['levels']['machining_depth_value_native']=defaults.scalar('GetMachiningDepthValue',read(typed(raw,'ICWMillOperation3'),'GetMachiningDepthValue',dispatch));partial['fresh_observation_groups'].append('stored_machining_depth');persist()
    else:
        defaults.validate_defaults(saved_observation['defaults']);partial['defaults']=deepcopy(saved_observation['defaults']);partial['reused_from_terminal']['groups'].append('defaults');persist()
        f=typed(raw,'ICWFinishMillOp');f3=typed(raw,'ICWFinishMillOp3');partial['depth_and_side_pairs']={name:finish.diagnostics._scalar(read(f3,name),'double_bool')for name in finish.PAIRS};partial['fresh_observation_groups'].append('finish_depth_side_pairs');persist()
        partial['finish_scope']={name:finish.diagnostics._scalar(read(f3,name),'bool')for name in finish.SCOPE_FLAGS};partial['finish_scope']['DepthProcessOpt']=finish.diagnostics._scalar(read(f,'DepthProcessOpt'),'long');partial['fresh_observation_groups'].append('finish_scope');persist()
    saved_nc=saved_observation['own_nc'];require(saved_nc['read_complete']is True and saved_nc['operation_native_id']==identity['operation_native_id'],'Complete saved own NC required')
    read_nc(raw,read,typed,pointer,persist,partial,saved_feeds=saved_nc['feeds_compensation']);partial['fresh_observation_groups'].append('nc_modes_and_lead_scalar');partial['capture_complete']=True;persist();return partial



def capture_pair(app,loaded,read,typed,pointer,boundary,persist,out):
    out.update(capture_complete=False,inventory=[],targets=[]);boundary();doc=typed(read(app,'IGetActiveDoc'),'ICWDoc3');machine=typed(read(typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine');require(read(machine,'MachType')==1,'MILL required');handles={}
    for rawsetup in _items(read(machine,'IGetEnumOpSetups'),typed,read,8):
        setup=typed(rawsetup,'ICWBaseOpSetup');sid=_object_id(doc,rawsetup,read)
        for raw in _items(read(setup,'IGetEnumOperations'),typed,read,32):
            require(len(out['inventory'])<32,'At most32 operations');op=typed(raw,'ICWOperation');oid=_object_id(doc,raw,read);mill=typed(raw,'ICWMillOperation');kind=read(mill,'OpernType');suppressed=read(op,'Suppressed');generated=read(op,'GetIsToolpathGenerated');counts=[]
            for path in _items(read(op,'IGetEnumToolpaths'),typed,read,1):
                count=read(typed(path,'ICWToolpath'),'RecordCount');require(type(count)is int and 0<count<=100000,'Positive bounded path count required');counts.append(count)
            require(type(kind)is int and type(suppressed)is bool and type(generated)is bool and generated is bool(counts),'Strict native operation flags required');tid=_object_id(doc,typed(read(op,'IGetTool'),'ICWTool'),read)
            out['inventory'].append(dict(native_id=oid,setup_native_id=sid,mill_operation_type=kind,suppressed=suppressed,toolpath_generated=generated,toolpath_record_counts=counts,tool_native_id=tid));require(oid not in handles,'Unique operation IDs required');handles[oid]=raw
    require(out['inventory']==finish.inventory_projection(loaded['state']),'Current full operation inventory differs');persist()
    selected=loaded['receipt']['new_operations'];require(len(selected)==2 and tuple(x['mill_operation_type']for x in selected)in((1,1),(0,1)),'Exactly two selected Finish or Rough/Finish definitions required')
    mixed='saved_observations'in loaded['receipt']
    require(mixed is(tuple(x['mill_operation_type']for x in selected)==(0,1)),'Producer observation kind mismatch')
    if mixed:require(len(loaded['receipt']['saved_observations'])==2,'Two saved mixed observations required')
    for i,row in enumerate(selected):
        oid=row['native_id'];fid=row['linked_feature_ids'][0];raw=handles[oid];op=typed(raw,'ICWOperation');require([_object_id(doc,x,read)for x in _items(read(op,'IGetAllFeatures'),typed,read,2)]==[fid],'Exact selected feature link required')
        kind=read(typed(op,'ICWMillOperation'),'OpernType');require(type(kind)is int and kind==row['mill_operation_type']and kind in(0,1)and row['toolpath_generated']is False and row['toolpath_record_counts']==[],'Only exact empty selected kind allowed');found=read(doc,'GetCWObjectFromID',1,fid);require(type(found)in(tuple,list)and len(found)==2 and found[1]is True and _object_id(doc,found[0],read)==fid,'Exact existing feature required');target={};out['targets'].append(target);persist()
        ident=dict(operation_native_id=oid,feature_native_id=fid,tool_native_id=row['assigned_tool']['native_id'],operation_kind=kind)
        if mixed:read_missing_target(raw,found[0],ident,loaded['receipt']['saved_observations'][i],loaded['receipt_pin'],read,typed,pointer,persist,target)
        else:read_target(raw,found[0],ident,read,typed,pointer,persist,target)
        if mixed:
            expected=loaded['receipt']['saved_observations'][i];require(expected['operation_kind']==kind and expected['operation_native_id']==oid and expected['feature_native_id']==fid,'Saved observation identity differs')
            if kind==1:require(producer.fields.equal(target['defaults'],expected['defaults']),'Current defaults differ from completed save')
            else:
                levels=deepcopy(target['level_state']);levels['levels'].pop('machining_depth_value_native');require(producer.fields.equal(target['rough'],expected['parameters']['rough'])and producer.fields.equal(levels,expected['parameters']['levels']),'Current Rough parameters differ from completed save')
            require(expected['own_nc']['read_complete']is True and producer.fields.equal(expected['own_nc']['feeds_compensation'],{k:target['nc'][k]for k in('GetSpndlSpeed','XYFeed','GetCNCComp','GetTlpComp')}),'Current own NC differs from completed save')
        else:require(producer.fields.equal(target['defaults'],loaded['receipt']['saved_defaults'][i]),'Current defaults differ from completed save')
        boundary()
    out['capture_complete']=True;persist();return out


def bounded_snapshot(capture,identity_boundary,verify_pins):
    """Full immutable-chain checks bracket a read-only snapshot, never each getter."""
    verify_pins();identity_boundary();value=capture();identity_boundary();verify_pins();return value



def finalize_runtime_failure(result,error):
    result.update(status='error',phase='finished',runtime_error=_error(error),runtime_unchanged=False,readback_verified=False,source_unchanged=False,production_qualified=False);_write_receipt(Path(result['receipt_path']),result);return result


def dispatch(sw,clsid,tlb,values,*,runtime_check):
    v=values;loaded=validate(v);classes,abi=preflight(tlb);session=None
    r=dict(scope=SCOPE,observation_policy='REUSE_COMPLETED_SAVED_GROUPS_READ_ONLY_MISSING_MODES',status='running',phase='preflight',request=deepcopy(v),receipt_path=v['receipt_path'],evidence_pins=deepcopy(loaded['pins']),authority_pin=loaded['receipt_pin'],abi=abi,native_read_count=0,native_read_limit=MAX_READS,read_only=True,mutation_attempted=False,save_attempted=False,GTP_attempted=False,GOP_attempted=False,parameter_setter_attempted=False,readback_verified=False,source_unchanged=False,runtime_unchanged=False,production_qualified=False,lead_geometry_qualified=False)
    def persist():_write_receipt(loaded['output'],r)
    _write_receipt(loaded['output'],r,create=True)
    try:
        def identity():
            runtime_check();p=_process_identity(v['process_id']);require(p.get('alive')is True and p.get('process_id')==v['process_id']and p.get('create_time')==v['expected_process_create_time']and Path(p.get('executable','')).name.lower()=='sldworks.exe','Exact owned lifetime required');pid=_member(sw,'GetProcessID');require(type(pid)is int and pid==v['process_id'],'Native owner differs');doc=document_snapshot(sw);require(type(doc)is dict and type(doc.get('type'))is int and doc['type']==1 and doc.get('needs_save')is False,'Clean saved part required');check_document_target(doc['path'],doc['title'],expected_path=v['expected_document_path'],required=True);require(_file_hash(v['expected_document_path'])==v['expected_source_sha256'],'Current source changed')
            return doc
        def verify_pins():
            for pin in loaded['pins']:ancestry.common.direct(pin)
        with solidworks_operation_lock(timeout_seconds=1,process_id=v['process_id']):
            verify_pins();initial=identity();require(initial==loaded['state']['document'],'Current document differs from authority');addin=_member(sw,'GetAddInObject',clsid);require(addin is not None,'CAM must be loaded');app=_typed(_member(addin,'GetCWApp'),'ICWApp4',tlb);require(identity()==initial,'Bootstrap changed identity');session=CamMessageSession(app,tlb)
            def check():
                summary=session.summary();r['messages']=summary;require(summary.get('active')is True and summary.get('subscribed')is True and not any(summary.get(k)for k in finish.nc.EVENT_ERRORS),'CAM event requires stop')
            def boundary():check();require(identity()==initial,'Document changed');check()
            def admission(name):check();require(r['native_read_count']<MAX_READS,'Read budget exhausted');r['native_read_count']+=1;r['phase']=name
            def read(owner,name,*args):
                require(name in GETTERS,'Getter outside fixed read scope');admission(name);r['last_attempted_read']=name
                try:value=_member(owner,name,*args)
                except Exception:r['failed_read']=name;raise
                r['last_returned_read']=name;check();return value
            def typed(owner,name):
                require(name in classes and name!='ICWLeadInOut','Interface outside fixed read scope');admission('QI '+name);value=owner.QueryInterface(classes[name]);require(value is not None and bool(value)and isinstance(value,POINTER(classes[name])),'Typed pointer required');check();return value
            def pointer(owner,detail):
                admission('GetLeadinFeedrate');persist()
                try:return finish.nc.lead_pointer_value(owner,detail)
                finally:check();persist()
            with session:
                for label in ('before','after'):
                    r['phase']=label;r[label]={};persist();bounded_snapshot(lambda:capture_pair(app,loaded,read,typed,pointer,boundary,persist,r[label]),boundary,verify_pins)
                require(r['before']==r['after'],'Two complete targeted observations differ');boundary()
            r['messages']=session.summary();clean_events(r);require(identity()==initial,'Document changed after cleanup');verify_pins();runtime_check();r.update(status='review_required',phase='finished',readback_verified=True,source_unchanged=True,runtime_unchanged=True,reason='TWO_MATCHING_MISSING_SCALAR_CAPTURES_WITH_PINNED_SAVED_CONTEXT_NO_LEAD_OBJECTS')
    except Exception as error:r.update(status='error',failed_phase=r.get('phase'),phase='finished',issue=_error(error),readback_verified=False,source_unchanged=False,runtime_unchanged=False)
    finally:
        if session is not None:r['messages']=session.summary()
        persist()
    return r
