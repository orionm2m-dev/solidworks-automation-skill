"""Insert one FACE operation while preserving a completed saved route.

The creator never assigns a tool, generates paths, saves or retries. A newly
inserted operation may expose a null tool; that observation is not a qualified
machining recipe. Existing route/tool getters retain their strict behavior.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import json,math,re
from scripts import sw_cam_upper_cone_feature as cone
from scripts import sw_cam_raw_mill_face_feature as face
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_comtypes import _is_comtypes_pointer
from scripts.sw_cam_rough_firstcut import require,read_firstcut_settings
from scripts.sw_cam_rough_entry_parameters import read_rough_entry_parameters
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import (integer,read_generic_tool,
    MAX_SETUPS,MAX_FEATURES,MAX_OPERATIONS,MAX_RECORDS)
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_mill_levels import read_mill_level_values
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_completed_sandvik_assignment import read_assignment_candidate
from scripts.sw_cam_finish_read_batch import ScopedFinishReadBatch
from scripts.sw_cam_finish_observation import read_finish_details
from scripts.sw_cam_finish_lead_observation import read_lead_details
from scripts.sw_cam_mill_selected_plan_context import read_header,read_options
from scripts.sw_cam_mill_profile_headers import read_profile_feature_headers
from scripts.sw_cam_empty_mill_stock_export import _export_stock
from scripts.sw_cam_mill_units_qualification import _features,_bodies

SCOPE='RAW_MILL_SINGLE_FACE_OPERATION_INSERT_V1'
OPERATION_TYPE=20
AFTER_OPERATION_ID=196
SETUP_ID=93
OLD_OPERATION_IDS=(143,144,195,196,247,248)


def _key(path):return str(Path(path).resolve()).casefold()
def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)
def _payload(loaded):return dict(rough=deepcopy(loaded['payload']),finish=deepcopy(loaded['finish_payload']))


def insert_marker(source,source_sha256,feature_id):
    key=_digest(dict(scope=SCOPE,source=_key(source),source_sha256=source_sha256,
        feature_native_id=feature_id,operation_type=OPERATION_TYPE,after_operation_id=AFTER_OPERATION_ID))
    return Path(source).resolve().parent/('raw_face_operation_'+key+'.json')


class FaceOperationContext(cone.UpperConeContext):
    def files(self):
        super().files()
        for pin in self.loaded.get('lineage_pins',[]):
            require(_file_hash(pin['path'])==pin['sha256'],'Checked operation lineage changed')


def verify_insert_delta(before,after,new_id,face_id,*,diagnostic=None):
    integer(new_id,'New operation ID',1);integer(face_id,'Face ID',1)
    require(len(before['features'])==len(after['features'])==21,'Exact21 features required')
    old=before['operations'];rows=after['operations']
    require(tuple(r['native_id'] for r in old)==OLD_OPERATION_IDS and before['operation_count']==6,
        'Exact saved six-operation baseline required')
    require(new_id not in OLD_OPERATION_IDS and len(rows)==7 and after['operation_count']==7,'Exactly one new operation required')
    expected_order=list(OLD_OPERATION_IDS);expected_order.insert(4,new_id)
    require([r['native_id'] for r in rows]==expected_order,'New FACE must follow196 before247')
    added=deepcopy(rows[4]);known={r['geometry']['native_id'] for r in before['features']}|{r['native_id'] for r in before['feature_setups']}|{r['native_id'] for r in before['operation_setups']}|{r['assigned_tool']['native_id'] for r in old}
    require(new_id not in known,'New operation identity collides with existing object')
    required=dict(setup_index=0,setup_native_id=SETUP_ID,operation_index=4,native_id=new_id,
        mill_operation_type=OPERATION_TYPE,base_operation_type=0,suppressed=False,
        toolpath_generated=False,linked_feature_ids=[face_id],toolpath_record_counts=[])
    require(set(added)==set(required)|{'assigned_tool'} and all(added[k]==v and type(added[k]) is type(v) for k,v in required.items()),
        'New FACE operation type/links/flags/counts differ')
    if added['assigned_tool'] is not None:
        tool=added['assigned_tool'];require(type(tool) is dict and tool.get('native_read_complete') is True
            and tool.get('is_mill_tool') is True,'Non-null new tool must be fully observed, never assumed suitable')
        integer(tool.get('native_id'),'Observed default tool ID',1)
    expected=deepcopy(before);normalized=deepcopy(after)
    require(before['document']['needs_save'] is False and after['document']['needs_save'] is True,'One unsaved inserted operation required')
    normalized['document']['needs_save']=False
    require(before['operation_counts']==[6,0,0] and after['operation_counts']==[7,0,0],'Only setup93 count may increase')
    normalized['operation_counts']=[6,0,0];normalized['operation_count']=6
    require(after['operation_setups']==[dict(index=0,native_id=93,operation_count=7),dict(index=1,native_id=94,operation_count=0),dict(index=2,native_id=95,operation_count=0)],'Operation setup identities/counts changed')
    normalized['operation_setups']=deepcopy(before['operation_setups'])
    normalized['operations'].pop(4)
    for index,row in enumerate(normalized['operations']):
        require(row['operation_index']==index+(index>=4),'Unexpected old operation index change')
        row['operation_index']=index
    cone.require_state_equivalent(expected,normalized,diagnostic=diagnostic)
    return added

def read_route_operations(state,native,read,typed,*,selected=None,diagnostic=None,nullable_operation_id=None):
    """Read known typed vtable getters; preserve ordered sibling identities."""
    if nullable_operation_id is not None:integer(nullable_operation_id,'Only new nullable operation ID',1)
    diagnostic={} if diagnostic is None else diagnostic
    diagnostic.update(operation_capture_complete=False,operations=[])
    features=[integer(r['geometry']['native_id'],'feature ID',1) for r in state['features']]
    feature_setups=[integer(r['native_id'],'feature setup ID',1) for r in state['feature_setups']]
    if (not 1<=len(features)<=MAX_FEATURES or not 1<=len(feature_setups)<=MAX_SETUPS
            or len(features)!=len(set(features)) or len(feature_setups)!=len(set(feature_setups))
            or set(features)&set(feature_setups)):
        raise ValueError('Bounded unique disjoint feature/setup identities required')
    known=set(features);protected=known|set(feature_setups)
    counts=state['operation_counts']
    if (type(counts) is not list or len(counts)>MAX_SETUPS
        or any(type(v) is not int or v<0 for v in counts) or sum(counts)>MAX_OPERATIONS):
        raise ValueError('Bounded operation counts required')
    setups=_items(read(native['machine'],'IGetEnumOpSetups'),typed,read,MAX_SETUPS)
    if len(setups)!=len(counts):
        raise ValueError('Operation setup count changed')
    state.update(operation_setups=[],operation_setup_count=len(setups),operations=[],
        operation_count=0,operation_inventory_scope='bounded_raw_id_links_flags_counts_and_generic_tool')
    op_ids=set();setup_ids=set();raw_ops={};tool_ids=set();total_records=0
    for si,raw_setup in enumerate(setups):
        setup=typed(raw_setup,'ICWBaseOpSetup')
        sid=integer(_object_id(native['doc'],setup,read),'operation setup ID',1)
        if sid in protected|setup_ids|op_ids|tool_ids:
            raise ValueError('Duplicate or cross-kind operation setup identity')
        setup_ids.add(sid)
        values=_items(read(setup,'IGetEnumOperations'),typed,read,MAX_OPERATIONS)
        if len(values)!=counts[si]:
            raise ValueError('Operation count changed')
        state['operation_setups'].append(dict(index=si,native_id=sid,operation_count=len(values)))
        for oi,raw in enumerate(values):
            operation=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation')
            oid=integer(_object_id(native['doc'],operation,read),'operation ID',1)
            if oid in protected|setup_ids|op_ids|tool_ids:
                raise ValueError('Duplicate or cross-kind operation identity')
            op_ids.add(oid);raw_ops[oid]=raw
            row=dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=oid)
            state['operations'].append(row);diagnostic['operations'].append(row)
            row['mill_operation_type']=integer(read(mill,'OpernType'),'MILL operation type')
            row['base_operation_type']=integer(read(operation,'OpernType'),'base operation type')
            row['suppressed']=read(operation,'Suppressed')
            row['toolpath_generated']=read(operation,'GetIsToolpathGenerated')
            if type(row['suppressed']) is not bool or type(row['toolpath_generated']) is not bool:
                raise ValueError('Strict operation flags required')
            links=[integer(_object_id(native['doc'],item,read),'linked feature ID',1)
                for item in _items(read(operation,'IGetAllFeatures'),typed,read,MAX_FEATURES)]
            if not links or len(set(links))!=len(links) or not set(links)<=known:
                raise ValueError('Nonempty unique links to captured features required')
            row['linked_feature_ids']=links
            records=[]
            for value in _items(read(operation,'IGetEnumToolpaths'),typed,read,32):
                path=typed(value,'ICWToolpath')
                records.append(integer(read(path,'RecordCount'),'record count',0,MAX_RECORDS))
            total_records+=sum(records)
            if total_records>MAX_RECORDS:raise ValueError('Aggregate path-record count bound exceeded')
            row['toolpath_record_counts']=records
            candidate=read(operation,'IGetTool') if oid==nullable_operation_id else True
            if oid==nullable_operation_id and (candidate is None or (_is_comtypes_pointer(candidate) and not bool(candidate))):
                row['assigned_tool']=None;tool=None
            else:
                if oid==nullable_operation_id:require(_is_comtypes_pointer(candidate) and bool(candidate),'New default tool must be a real COM pointer or null')
                row['assigned_tool'],tool=read_generic_tool(raw,native['doc'],read,typed)
                tid=row['assigned_tool']['native_id']
                if tid in protected|setup_ids|op_ids:
                    raise ValueError('Tool identity collides with captured object kind')
                tool_ids.add(tid)
            if selected is not None and oid==selected['operation_native_id']:
                require(tool is not None,'Selected full tool cannot be nullable')
                if (links!=[selected['feature_native_id']] or
                    row['mill_operation_type']!=selected['mill_operation_type'] or row['suppressed'] is not False):
                    raise ValueError('Selected operation must be unsuppressed and link only to exact feature/type')
                detail={}
                diagnostic['selected_tool_geometry']=detail
                row['full_tool']=read_full_mill_tool(tool,generic=row['assigned_tool'],read=read,
                    typed=typed,diagnostic=detail)
    state['operation_count']=len(state['operations'])
    if state['operation_count']!=sum(counts):
        raise ValueError('Operation inventory changed')
    if selected is not None and sum(r['native_id']==selected['operation_native_id'] for r in state['operations'])!=1:
        raise ValueError('Exact selected operation not found')
    native['operations']=raw_ops
    diagnostic['operation_capture_complete']=True


def _capture_headers(ctx,clsid,reference,count,diagnostic,*,nullable_operation_id=None):
    """Same complete20/21 header state, with strong global checks around a read batch."""
    require(type(count) is int and count==21 and len(reference['features'])==21,
        'RAW face pre/post inventory required')
    started=perf_counter();diagnostic.update(header_read_mode='bounded_header_batch',capture_complete=False)
    state=native=batch=None
    try:
        ctx.files();ctx.events();doc=ctx.identity()
        before_started=perf_counter()
        with ctx.guard() as g:
            try:
                state,native=face._snapshot_bounded(ctx,clsid,diagnostic.setdefault('global_snapshot_before',{}))
                diagnostic['header_state']=state
                diagnostic['capture_complete']=False
                require(state['document']==doc and sum(r['feature_count'] for r in state['feature_setups'])==count,
                    'Exact branch feature count required')
                state['stock'],_=_export_stock(g.read(native['machine'],'IGetWorkpiece'),ctx.typelib_path,g.read,diagnostic)
                require(state['stock']==reference['stock'],'Stock changed')
            finally:diagnostic['header_strong_before']=g.summary()
        diagnostic['header_strong_before_seconds']=perf_counter()-before_started
        batch=cone.ScopedUpperHeaderReadBatch(ctx.sw,ctx.typelib_path,native_context=native,reference_state=state,
            process_id=ctx.args['process_id'],expected_document=ctx.identity(),source_sha256=ctx.args['expected_source_sha256'],
            evidence_pins=ctx.loaded['pins'],verify_evidence=ctx.files,verify_owned_process=ctx.owned,check_events=ctx.events)
        try:
            with batch:
                state['recognition_options'],state['recognition_method']=read_options(native['doc'],batch.read)
                state['features']=[];ids=set()
                for si,raw in enumerate(native['setups']):
                    setup=batch.typed(raw,'ICWBaseSetup');sid=_object_id(native['doc'],setup,batch.read)
                    require(sid==state['feature_setups'][si]['native_id'],'Setup ID differs')
                    values=_items(batch.read(setup,'IGetEnumFeatures'),batch.typed,batch.read,count)
                    require(len(values)==state['feature_setups'][si]['feature_count'],'Feature count changed')
                    for fi,value in enumerate(values):
                        header,_=read_header(value,native['doc'],batch.read,batch.typed,sid)
                        state['features'].append(dict(setup_index=si,feature_index=fi,setup_native_id=sid,geometry=header))
                        require(header['native_id'] not in ids,'Duplicate feature ID');ids.add(header['native_id'])
                previous=reference['selected_profile_headers']
                selection=dict(feature_native_id=previous['native_id'],owner_setup_native_id=previous['owner_setup_native_id'],
                    volume_type=previous['volume_type'],shape=previous['shape'],island_count=previous['island_count'],include_contours=False)
                state['selected_profile_headers']=read_profile_feature_headers(native['doc'],selected=selection,
                    read=batch.read,typed=batch.typed,diagnostic=diagnostic.setdefault('header_profile',{}))
                read_route_operations(state,native,batch.read,batch.typed,diagnostic=diagnostic.setdefault('header_operations',{}),nullable_operation_id=nullable_operation_id)
            batch.require_complete()
        finally:diagnostic['header_read_batch']=deepcopy(batch.summary())
        after_started=perf_counter()
        with ctx.guard() as g:
            try:
                model=g.read(ctx.sw,'ActiveDoc');g._fast();tree,_=_features(model);g._fast();solids=_bodies(model);g._fast()
                state['sw_reference']=dict(feature_tree=tree,solids=solids)
                visible=g.read(model,'GetBodies2',0,True)
                require(visible is None or (type(visible) in (list,tuple) and len(visible)<=64),'Bounded visible body collection required')
                state.update(visible_solid_body_count=0 if visible is None else len(visible),all_solid_body_count=len(solids))
                final,_=face._snapshot_bounded(ctx,clsid,diagnostic.setdefault('global_snapshot_after',{}))
                diagnostic['header_final_snapshot']=deepcopy(final)
                require(all(state[key]==value for key,value in final.items()),'Native machine/header changed during capture')
            finally:diagnostic['header_strong_after']=g.summary()
        diagnostic['header_strong_after_seconds']=perf_counter()-after_started
        require(ctx.identity()==doc,'Document changed during header capture');ctx.files();ctx.events()
        diagnostic.update(capture_complete=True,expected_feature_count=count)
        return state,native
    finally:
        diagnostic['header_elapsed_seconds']=perf_counter()-started
        if state is not None:diagnostic['observed_state']=deepcopy(state)


def capture_assignment_snapshot(app, *, read, typed, reference_state, current_document,
        source_sha256, target_feature_native_id, target_operation_native_id, boundary, diagnostic,
        native_context=None, feature_dispatch_reader=None,nullable_operation_id=None):
    """Refresh operation state and target settings, reusing pinned model geometry."""
    require(callable(boundary), "Caller identity/evidence/event boundary required")
    boundary()
    require(native_context is not None,'Retained strong native graph required')
    native=native_context
    state = deepcopy(reference_state)
    read_route_operations(state, native, read, typed, diagnostic=diagnostic.setdefault("operations", {}),nullable_operation_id=nullable_operation_id)
    state["document"] = deepcopy(current_document)
    state["saved_file_sha256"] = source_sha256
    found = read(native["doc"], "GetCWObjectFromID", 1, target_feature_native_id)
    require(isinstance(found, (tuple, list)) and len(found) == 2 and found[1] is True,
            "Exact target feature lookup failed")
    feature = typed(found[0], "ICWFeature")
    require(_object_id(native["doc"], feature, read) == target_feature_native_id, "Target feature differs")
    selected = [o for o in state["operations"] if o["native_id"] == target_operation_native_id]
    require(len(selected) == 1 and selected[0]["linked_feature_ids"] == [target_feature_native_id]
        and selected[0]["mill_operation_type"] == 0 and selected[0]["suppressed"] is False,
        "Exact unsuppressed rough operation and feature link required")
    raw_op = native["operations"][target_operation_native_id]
    def native_read(label, invoke, decoder=None, interface=False, validator=None):
        boundary()
        value = (feature_dispatch_reader(feature)
            if label == "QueryInterface.IDispatch.feature" and feature_dispatch_reader is not None
            else invoke())
        boundary()
        if interface:require(value is not None and bool(value), "Non-null interface required")
        if validator:validator(value)
        return decoder(value) if decoder else value
    def getter(raw, interface_name, name, *params, **kw):
        return native_read(interface_name + "." + name, lambda:read(raw, name, *params), **kw)
    levels = {}
    read_mill_level_values(feature, raw_op, native_read=native_read, typed=typed, getter=getter, report=levels)
    firstcut = read_firstcut_settings(raw_op, read, typed)
    entry = read_rough_entry_parameters(raw_op, found[0], read=read, typed=typed,
        diagnostic=diagnostic.setdefault("entry_parameter_diagnostic", {}))
    diagnostic.update(capture_complete=True, fresh_full_snapshot=False,
        fresh_fields=["document", "operations", "target_levels", "firstcut", "entry_parameters"],
        reused_fields=["feature_geometry", "stock_geometry", "legacy_tool_profiles"])
    boundary()
    return state, native, levels, firstcut, entry


def _capture_payload(ctx,state,native,diagnostic,*,nullable_operation_id=None):
    """Reuse original rough/finish getters; inventory was freshly bounded above."""
    def units():
        with ctx.guard() as g:
            return read_document_cam_unit_scope(g.read(ctx.sw,'ActiveDoc'),ctx.app,sw_read=g.read,cam_read=g.read)
    metric=units();binding={k:native[k] for k in ('doc','machine','operations')}
    batch=ScopedFinishReadBatch(ctx.sw,ctx.typelib_path,native_context=binding,reference_state=state,
        process_id=ctx.args['process_id'],expected_document=ctx.identity(),source_sha256=ctx.args['expected_source_sha256'],
        evidence_pins=ctx.loaded['pins'],verify_evidence=ctx.files,verify_owned_process=ctx.owned,check_events=ctx.events,max_native_calls=1500)
    try:
        with batch:
            fresh,bound,levels,firstcut,entry=capture_assignment_snapshot(ctx.app,read=batch.read,typed=batch.typed,
                reference_state=state,current_document=state['document'],source_sha256=ctx.args['expected_source_sha256'],
                target_feature_native_id=ctx.args['target_feature_native_id'],target_operation_native_id=ctx.args['target_operation_native_id'],
                boundary=ctx.events,diagnostic=diagnostic,native_context=binding,feature_dispatch_reader=batch.feature_dispatch,nullable_operation_id=nullable_operation_id)
            require(fresh==state,'Operation summaries changed between header and payload reads')
            crib=batch.typed(batch.read(bound['machine'],'IGetToolcrib'),'ICWToolcrib4')
            diagnostic['observed_toolcrib_ids']=[_object_id(bound['doc'],v,batch.read) for v in _items(batch.read(crib,'GetAllTools'),batch.typed,batch.read,128)]
            candidate=read_assignment_candidate(bound,ctx.app,ctx.sw,read=batch.read,typed=batch.typed,
                expected_candidate_tool_native_id=ctx.args['expected_candidate_tool_native_id'],reference=ctx.loaded['payload']['candidate'],
                observation_pin=ctx.loaded['observation_pin'],firstcut=firstcut,diagnostic={},metric_scope=metric)
            raw=bound['operations'][ctx.args['finish_operation_native_id']]
            generic,tool=read_generic_tool(raw,bound['doc'],batch.read,batch.typed)
            expected=[r for r in state['operations'] if r['native_id']==ctx.args['finish_operation_native_id']]
            require(len(expected)==1 and generic==expected[0]['assigned_tool'],'Finish tool assignment changed')
            found=batch.read(bound['doc'],'GetCWObjectFromID',1,ctx.args['target_feature_native_id'])
            require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Protected feature lookup failed')
            feature=batch.typed(found[0],'ICWFeature');require(_object_id(bound['doc'],feature,batch.read)==ctx.args['target_feature_native_id'],'Protected feature ID changed')
            def read_native(label,invoke,decoder=None,interface=False,validator=None):
                value=batch.feature_dispatch(feature) if label=='QueryInterface.IDispatch.feature' else invoke()
                if interface:require(value is not None and bool(value),'Non-null level interface required')
                if validator:validator(value)
                return decoder(value) if decoder else value
            def getter(obj,interface_name,name,*values,**kw):return read_native(interface_name+'.'+name,lambda:batch.read(obj,name,*values),**kw)
            finish_levels={};read_mill_level_values(feature,raw,native_read=read_native,typed=batch.typed,getter=getter,report=finish_levels)
            details=read_finish_details(raw,found[0],tool,read=batch.read,typed=batch.typed,diagnostic={})
            leads=read_lead_details(raw,found[0],read=batch.read,typed=batch.typed,lead_typed=batch.lead_interface)
            full=read_full_mill_tool(tool,generic=generic,read=batch.read,typed=batch.typed,diagnostic={})
        batch.require_complete();after_units=units();require(metric==after_units,'Units changed across payload batch')
        result=dict(rough=dict(candidate=candidate,levels=levels,entry=entry),
            finish=dict(details=details,levels=finish_levels,leads=leads,full_tool=full,unit_record=after_units))
        diagnostic['observed_payload']=deepcopy(result)
        require(result==dict(rough=ctx.loaded['payload'],finish=ctx.loaded['finish_payload']),'Protected completed rough/finish payload changed')
        diagnostic['full_parent_payload_matched']=True
        return result
    finally:diagnostic['read_batch']=deepcopy(batch.summary())



def load_face_operation_parent(path,digest,*,process_id,expected_document_path,
        expected_source_sha256,expected_feature_native_id):
    from scripts.sw_cam_raw_mill_face_save import load_completed_face_save
    loaded=load_completed_face_save(path,digest,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        expected_feature_native_id=expected_feature_native_id)
    require(loaded.get('historical_only') is not True,'Current saved21 binding required')
    state=loaded['state'];require(len(state['features'])==21 and state['operation_count']==6
        and state['document']['needs_save'] is False,'Clean saved21/six-operation parent required')
    require(tuple(r['native_id'] for r in state['operations'])==OLD_OPERATION_IDS
        and all(expected_feature_native_id not in r['linked_feature_ids'] for r in state['operations']),
        'FACE already planned or old route changed')
    require(loaded['face_feature_native_id']==expected_feature_native_id,'Saved FACE identity differs')
    marker=loaded['save_marker_pin'];key=_key(marker['path'])
    matches=[v for v in loaded['pins'] if _key(v['path'])==key]
    require(len(matches)==1 and matches[0]['sha256']==marker['sha256'],'Only exact completed Save21 marker may retire')
    require(key!=_key(loaded['parent_pin']['path']),'Save21 receipt must remain live')
    past=canonical_evidence_pins(loaded.get('lineage_pins',[]),[marker])
    live=canonical_evidence_pins([v for v in loaded['pins'] if _key(v['path'])!=key],[_self_pin()])
    require(len(live)<=64 and len(past)<=16,'Unchanged pin limits required')
    loaded.update(pins=live,lineage_pins=past,retired_save_marker_pin=deepcopy(marker))
    for pin in live+past:require(_file_hash(pin['path'])==pin['sha256'],'Operation parent dependency changed')
    return loaded


def _fresh_output(loaded,path,marker,source):
    target=Path(path)
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.casefold()=='.json'
        and not target.exists() and not target.is_symlink() and not marker.exists() and not marker.is_symlink(),
        'Fresh output and never-attempted single operation required')
    protected={_key(v['path']) for v in loaded['pins']+loaded.get('lineage_pins',[])}|{_key(source)}
    require(_key(target) not in protected and _key(marker) not in protected and _key(target)!=_key(marker),
        'Operation outputs alias source/evidence')
    return target


def insert_raw_mill_face_operation(sw,clsid,typelib_path,*,saved_face_receipt_path,saved_face_receipt_sha256,
        process_id,expected_document_path,expected_source_sha256,expected_feature_native_id,receipt_path,
        qualification_only,acknowledge_disposable_copy,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True and message_policy=='vendor_default',
        'Explicit disposable qualification required')
    loaded=load_face_operation_parent(saved_face_receipt_path,saved_face_receipt_sha256,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        expected_feature_native_id=expected_feature_native_id)
    marker=insert_marker(expected_document_path,expected_source_sha256,expected_feature_native_id)
    receipt=_fresh_output(loaded,receipt_path,marker,expected_document_path)
    args=dict(process_id=process_id,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,status='error',phase='preflight',process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        parent_pin=deepcopy(loaded['parent_pin']),operation_module_pin=_self_pin(),
        evidence_pins=deepcopy(loaded['pins']),lineage_pins=deepcopy(loaded.get('lineage_pins',[])),
        retired_save_marker_pin=deepcopy(loaded['retired_save_marker_pin']),face_feature_native_id=expected_feature_native_id,
        after_operation_native_id=AFTER_OPERATION_ID,operation_setup_native_id=SETUP_ID,operation_type=OPERATION_TYPE,
        marker_path=str(marker),receipt_path=str(receipt),mutation_attempted=False,native_call_attempted=False,
        native_call_returned=False,native_dispatch_pending=False,creator_call_count=0,
        GOP_attempted=False,GTP_attempted=False,tool_assignment_attempted=False,save_attempted=False,model_saved=False,
        CAD_solid_edit_attempted=False,sketch_edit_attempted=False,automatic_replay=False,automatic_retry=False,
        automatic_rollback=False,readback_verified=False,operation_delta_verified=False,
        recipe_qualified=False,production_qualified=False,may_generate=False,snapshot_diagnostics=[])
    created=claimed=False;session=ctx=None
    def persist():
        if created:_write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count',
                'subscription_error','disconnect_errors')),'CAM event/transport requires stop')
    def capture(phase,new_id=None):
        report['phase']=phase;diag=dict(phase=phase);report['snapshot_diagnostics'].append(diag);persist()
        try:
            state,native=_capture_headers(ctx,clsid,loaded['state'],21,diag,nullable_operation_id=new_id)
            report[phase+'_context']=deepcopy(state);persist()
            payload=_capture_payload(ctx,state,native,diag,nullable_operation_id=new_id)
            report[phase+'_payload']=deepcopy(payload);persist()
            cone_obs=cone._read_sketch_and_cone(ctx,native,loaded['cone_sketch_spec'],loaded['cone_feature_native_id'])
            report[phase+'_cone_observation']=deepcopy(cone_obs);persist()
            face_diag={};report[phase+'_face_observation']=face_diag
            face_obs=face._read_face(ctx,native,loaded['face_sketch_spec'],expected_feature_native_id,
                diagnostic=face_diag,persist=persist)
            report[phase+'_face_observation']=deepcopy(face_obs);persist()
            require(cone_obs==loaded['cone_observation'] and face_obs==loaded['face_observation'],
                'Existing cone/FACE geometry or sketches changed')
            return state,native,payload
        finally:persist()
    def pending():
        nonlocal claimed
        require(report['creator_call_count']==0,'Only one InsertOperation call allowed')
        _write_receipt(marker,dict(scope=SCOPE,status='dispatch_pending',source=expected_document_path,
            source_sha256=expected_source_sha256,face_feature_native_id=expected_feature_native_id,
            after_operation_native_id=AFTER_OPERATION_ID,operation_type=OPERATION_TYPE,
            receipt_path=str(receipt),automatic_replay=False),create=True)
        claimed=True
        report.update(phase='InsertOperation',mutation_attempted=True,native_call_attempted=True,
            native_dispatch_pending=True,creator_call_count=1);persist()
    try:
        _write_receipt(receipt,report,create=True);created=True
        ctx=FaceOperationContext(loaded,args,sw,typelib_path,None,events,loaded['state'])
        ctx.files();ctx.identity();ctx.app=cone._bootstrap(sw,clsid,typelib_path,expected_document_path)
        ctx.identity();session=CamMessageSession(ctx.app,typelib_path)
        with session:
            before,native,before_payload=capture('before')
            report['before_state_equivalence']={}
            cone.require_state_equivalent(loaded['state'],before,diagnostic=report['before_state_equivalence']);persist()
            require(before_payload==_payload(loaded),'Protected baseline payload differs')
            with ctx.guard() as guard:
                found=guard.read(native['doc'],'GetCWObjectFromID',1,expected_feature_native_id)
                require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact FACE lookup failed')
                feature=guard.typed(found[0],'ICWFeature')
                require(_object_id(native['doc'],feature,guard.read)==expected_feature_native_id,'FACE ID changed')
                after_op=guard.typed(native['operations'][AFTER_OPERATION_ID],'ICWOperation')
                require(_object_id(native['doc'],after_op,guard.read)==AFTER_OPERATION_ID,'Insertion anchor ID changed')
                result=guard.dispatch_once(lambda:_member(feature,'InsertOperation',OPERATION_TYPE,after_op),persist_pending=pending)
                report.update(native_call_returned=True,native_dispatch_pending=False,native_return_type=type(result).__name__);persist()
            report['dispatch_guard']=guard.summary();persist()
            require(_is_comtypes_pointer(result) and bool(result),'InsertOperation must return one non-null COM operation, never scalar HRESULT')
            observed_document=raw_part_identity(sw);report['document_after_creator']=deepcopy(observed_document);persist()
            expected_document=deepcopy(before['document']);expected_document['needs_save']=True
            require(observed_document==expected_document and _file_hash(expected_document_path)==expected_source_sha256,
                'Insertion may only dirty the exact current saved document')
            ctx.expected_document=deepcopy(observed_document);ctx.files();ctx.identity();events()
            with ctx.guard() as guard:
                op=guard.typed(result,'ICWOperation');new_id=_object_id(native['doc'],op,guard.read)
            integer(new_id,'Created operation ID',1);report['new_operation_native_id']=new_id;persist()
            after,native,after_payload=capture('after',new_id)
            report['delta_state_equivalence']={}
            added=verify_insert_delta(before,after,new_id,expected_feature_native_id,diagnostic=report['delta_state_equivalence'])
            require(before_payload==after_payload,'Protected rough/finish payload changed')
            report.update(new_operation=added,operation_delta_verified=True);persist()
        events(False);ctx.files();require(ctx.identity()==after['document'],'Document changed during cleanup')
        checkpoint=dict(state=deepcopy(after),payload=deepcopy(after_payload),face_observation=deepcopy(loaded['face_observation']),
            cone_observation=deepcopy(loaded['cone_observation']),face_sketch_spec=deepcopy(loaded['face_sketch_spec']),
            cone_sketch_spec=deepcopy(loaded['cone_sketch_spec']),face_feature_native_id=expected_feature_native_id,
            cone_feature_native_id=loaded['cone_feature_native_id'],new_operation_native_id=new_id,source_sha256=expected_source_sha256)
        report.update(status='review_required',phase='finished',readback_verified=True,
            source_after_sha256=_file_hash(expected_document_path),checkpoint=checkpoint,checkpoint_sha256=_digest(checkpoint),
            reason='ONE_UNSAVED_FACE_DEFINITION_TOOL_OBSERVED_NOT_ASSIGNED_OR_QUALIFIED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],
            phase='finished',issue=_error(exc),readback_verified=False,operation_delta_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:
            persist()
            if claimed:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],source=expected_document_path,
                source_sha256=expected_source_sha256,face_feature_native_id=expected_feature_native_id,
                after_operation_native_id=AFTER_OPERATION_ID,operation_type=OPERATION_TYPE,
                receipt_path=str(receipt),receipt_sha256=_file_hash(receipt),native_call_attempted=report['native_call_attempted'],
                native_call_returned=report['native_call_returned'],readback_verified=report['readback_verified'],automatic_replay=False))
        except Exception as exc:report.update(status='uncertain',readback_verified=False,receipt_write_error=_error(exc))
    return report


PARAMS={'saved_face_receipt_path','saved_face_receipt_sha256','process_id','expected_document_path',
    'expected_source_sha256','expected_feature_native_id','receipt_path','qualification_only','acknowledge_disposable_copy',
    'message_policy','addin_clsid','module_sha256'}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='insert_raw_mill_face_operation',
        'Only one FACE operation insertion supported')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact FACE insertion request fields required')
    integer(p['process_id'],'Owned process ID',1);integer(p['expected_feature_native_id'],'Saved FACE ID',1)
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    require(p['module_sha256']==_self_pin()['sha256'] and p['qualification_only'] is True and p['acknowledge_disposable_copy'] is True
        and p['message_policy']=='vendor_default','Exact implementation and disposable qualification required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),
        'Exact add-in CLSID required')
    return dict(p)


def dispatch_request(request):
    p=validate_request(request)
    load_face_operation_parent(p['saved_face_receipt_path'],p['saved_face_receipt_sha256'],**{key:p[key] for key in
        ('process_id','expected_document_path','expected_source_sha256','expected_feature_native_id')})
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    from scripts.sw_cam_installation import discover_cam_installations
    from scripts.sw_cam import select_registration
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        inventory=discover_cam_installations();require(not inventory['errors'],'Installation discovery errors')
        registration=select_registration(inventory,p.pop('addin_clsid'));p.pop('module_sha256')
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        require(type(_member(sw,'GetProcessID')) is int and _member(sw,'GetProcessID')==p['process_id'],'Connected PID differs')
        return insert_raw_mill_face_operation(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),**p)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    ns=parser.parse_args(argv);request=json.loads(Path(ns.request).read_text(encoding='utf-8-sig'))
    result=dispatch_request(request)
    print(json.dumps({key:result.get(key) for key in ('scope','status','phase','readback_verified','operation_delta_verified',
        'new_operation_native_id','issue','receipt_path')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1


if __name__=='__main__':raise SystemExit(main())
