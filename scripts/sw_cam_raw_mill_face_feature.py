"""One SLAB feature in the saved RAW MILL qualification copy.

Production TURN facing already exists in ROUTE-02. This command does not add
production operations, generate paths, save a document or replace its stock.
"""
from copy import deepcopy
from pathlib import Path
from time import perf_counter
import json,math,re
from scripts import sw_cam_upper_cone_feature as cone
from scripts import sw_cam_upper_cone_save as saved
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_comtypes import _is_comtypes_pointer
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam_mill_qualification import _int,_text,_vector
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_mill_units_qualification import _circle_contour,_circle_sketch,_nonnull,_number,_vector
from scripts.sw_cam_mill_circle_geometry import _circle_chain
from scripts.sw_cam_profile_sketch import _input,_read_sketch
from scripts.sw_cam_upper_cone_feature import (ScopedUpperHeaderReadBatch,_snapshot,_export_stock,
    read_options,_items,read_header,read_profile_feature_headers,read_route_operations,_features,_bodies)

SCOPE='RAW_MILL_FACE_FEATURE_ONLY_V1'
ROUTE_SCOPE='RAW_MILL_QUALIFICATION'
FACE_SPEC=dict(plane_axis='Z',plane_offset_mm=28.0,sketch_name='FaceStockCircle',plane_name='FaceStockPlane',
    profile=dict(kind='circle',center_model_mm=[0.0,0.0,28.0],radius_mm=32.5))
TARGET=dict(owner_setup_native_id=69,axis=[0,0,-1],stock_top_mm=28.0,target_top_mm=26.0,diameter_mm=65.0)

def _key(path):return str(Path(path).resolve()).casefold()
def _pin(path):return dict(path=str(Path(path).resolve()),sha256=_file_hash(path))
def _self_pin():return _pin(__file__)

def validate_face_spec(spec,route_scope):
    require(route_scope==ROUTE_SCOPE,'Only RAW MILL qualification supported; production TURN facing is separate')
    out=_input(spec)
    require(out==FACE_SPEC,'Only exact stock circle D65 at Z28 supported')
    return out

def face_marker(source,source_sha256):
    value=_digest(dict(scope=SCOPE,source=_key(source),saved_source_sha256=source_sha256,target=TARGET))
    return Path(source).resolve().parent/('raw_mill_face_'+value+'.json')

def load_face_parent(path,digest,*,process_id,expected_document_path,expected_source_sha256,expected_feature_native_id):
    loaded=saved.load_completed_upper_cone_save(path,digest,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        expected_feature_native_id=expected_feature_native_id)
    require(len(loaded['state']['features'])==20 and len(loaded['state']['operations'])==6
        and loaded['state']['document']['needs_save'] is False,'Exact clean saved20/6 required')
    # Only the completed cone sketch moves to checked history. Parent validation
    # above has verified it; the original file remains checked at every boundary.
    old=loaded['sketch_receipt_pin'];key=_key(old['path'])
    matched=[p for p in loaded['pins'] if _key(p['path'])==key]
    require(len(matched)==1 and matched[0]['sha256']==old['sha256'],'Exact completed cone sketch path and hash required')
    loaded['pins']=canonical_evidence_pins([p for p in loaded['pins'] if _key(p['path'])!=key],[_self_pin()])
    loaded['lineage_pins']=canonical_evidence_pins(loaded.get('lineage_pins',[]),[old])
    require(len(loaded['lineage_pins'])<=16,'Bounded completed lineage required')
    return loaded

def verify_face_delta(before,after,new_id,owner_id=69,*,diagnostic=None):
    require(type(new_id) is int and new_id>0 and owner_id==69,'Exact new face/owner ID required')
    old=before['features'];rows=after['features'];oldids=[r['geometry']['native_id'] for r in old]
    require(len(old)==20 and len(rows)==21 and len({r['geometry']['native_id'] for r in rows})==21 and new_id not in oldids,
        'Exactly one new feature20 to21 required')
    added=[r for r in rows if r['geometry']['native_id'] not in oldids]
    require(len(added)==1 and added[0]['geometry']['native_id']==new_id and added[0]['setup_native_id']==owner_id,'Exact new owner/feature required')
    retained=[r for r in rows if r['geometry']['native_id'] in oldids]
    for a,b in zip(old,retained):
        x,y=deepcopy(a),deepcopy(b);x.pop('feature_index');y.pop('feature_index');require(x==y,'Existing feature changed')
    require(len(before['feature_setups'])==len(after['feature_setups']) and sum(r['native_id']==owner_id for r in before['feature_setups'])==1,
        'Exactly unchanged setups and one owner required')
    expected=deepcopy(before);expected['features']=deepcopy(rows)
    require(after['document']['needs_save'] is True,'New unsaved feature must leave dirty document')
    for i,(a,b) in enumerate(zip(before['feature_setups'],after['feature_setups'])):
        target=deepcopy(a)
        if a['native_id']==owner_id:target['feature_count']+=1
        require(target==b,'Unexpected feature setup delta')
        local=[r for r in rows if r['setup_index']==i]
        require(len(local)==b['feature_count'] and [r['feature_index'] for r in local]==list(range(len(local))),'Feature order/count differs')
    expected['feature_setups']=deepcopy(after['feature_setups'])
    cone.require_state_equivalent(expected,after,diagnostic=diagnostic)
    return deepcopy(added[0])

def verify_face_geometry(observed,circle,new_id):
    close=lambda a,b:type(a) in (int,float) and math.isfinite(a) and abs(a-b)<=1e-6
    vec=lambda a,b:type(a) in (list,tuple) and len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    require(type(new_id) is int and new_id>0 and type(observed['native_id']) is int and observed['native_id']==new_id
        and type(observed['volume_type']) is int and observed['volume_type']==5 and observed['suppressed'] is False,'Exact unsuppressed SLAB identity required')
    require(close(observed['depth_native'],2) and vec(observed['axis_native'],[0,0,-1])
        and vec(observed['start_native'],[0,0,28]) and vec(observed['bounds_native'],[65,65,2]),'Face header differs')
    require(observed['taper_enabled'] is False and type(observed['island_count']) is int and observed['island_count']==0,'Untapered face without islands required')
    require(vec([v*1000 for v in circle['center_model_m']],[0,0,28]) and close(circle['radius_m']*1000,32.5),'Measured sketch differs')
    top=_circle_chain(observed['top_curves_native'],1e-8,1e-8,1e-7,'face_top')
    bottom=_circle_chain(observed['bottom_curves_native'],1e-8,1e-8,1e-7,'face_bottom')
    require(vec(top['center'],[0,0,28]) and close(top['radius'],32.5) and close(bottom['radius'],32.5),'Full D65 profiles required')
    coplanar=vec(bottom['center'],top['center']);distinct=vec(bottom['center'],[0,0,26])
    require(coplanar or distinct,'Unexpected raw lower profile plane')
    for row in (top,bottom):require(abs(row['normal'][0])<1e-7 and abs(row['normal'][1])<1e-7 and close(abs(row['normal'][2]),1),'XY contours required')
    return dict(native_configuration_verified=True,complete_circular_profiles_verified=True,
        raw_top_center_native=top['center'],raw_bottom_center_native=bottom['center'],raw_radius_native=top['radius'],
        raw_profiles_coplanar=coplanar,distinct_native_planes_observed=distinct,raw_header_depth_native=observed['depth_native'],
        coordinate_frame_qualified=False,geometric_depth_verified=False,physical_stock_removal_proved=False,
        lower_world_boundary_synthesized=False,target_only=deepcopy(TARGET),production_route_changed=False,
        limit='RAW MILL configuration only. Physical Z28 to26 removal requires later CL/WIP. Production TURN facing is separate.')


SNAPSHOT_READ_MEMBERS=frozenset({
    'GetDocType','MachType','Name','MachId','Description','GetNumMachineOfType','GetMachines',
    'Count','Item','IGetEnumSetups','IGetEnumFeatures','GetCWObjectID','SetupName','Axis',
    'GetReferencePosition','OriginType','IGetEnumOpSetups','IGetEnumOperations',
    'IGetWorkpiece','Material','ExtendHolesToStock',
})
SNAPSHOT_READ_INTERFACES=frozenset({
    'ICWMillMachine','ICWDispatchCollection','ICWBaseSetup','ICWSetup','ICWBaseOpSetup','ICWWorkpiece',
})

class ScopedMillSnapshotReadBatch(ScopedCamReadBatch):
    """Existing MILL global snapshot fields on strongly resolved native roots.

    Global ActiveDoc/add-in acquisition and SW solids remain outside. This is a
    separate read scope, not an extension of an earlier route qualification.
    """
    def __init__(self,*args,native_context,**kwargs):
        require(type(native_context) is dict and all(k in native_context for k in ('app','doc','machine')),
            'Strong-resolved application/document/machine roots required')
        self._snapshot_native=native_context;self._snapshot_bindings=[];self._binding_checks=0;self._binding_reads=0
        check=kwargs.get('check_events');require(callable(check),'Per-read event verifier required')
        def binding():
            def read(obj,name,*values):
                check();self._binding_reads+=1;value=_member(obj,name,*values);check();return value
            kind=read(native_context['doc'],'GetDocType');machine_kind=read(native_context['machine'],'MachType')
            require(type(kind) is int and kind==1,'Retained snapshot document type changed')
            require(type(machine_kind) is int and machine_kind==1,'Retained snapshot machine type changed')
            for native_id,setup in self._snapshot_bindings:
                require(_object_id(native_context['doc'],setup,read)==native_id,'Retained snapshot setup ID changed')
            self._binding_checks+=1
        super().__init__(*args,retained_objects=tuple(native_context[k] for k in ('app','doc','machine')),
            verify_retained_binding=binding,max_native_calls=1500,**kwargs)
    def bind_setups(self,rows,objects):
        require(not self._snapshot_bindings and len(rows)==len(objects) and 1<=len(rows)<=8,'One bounded setup binding required')
        ids=[r['native_id'] for r in rows]
        require(len(ids)==len(set(ids)) and all(type(i) is int and 0<i<2**32 for i in ids),'Exact unique setup IDs required')
        require(all(id(obj) in self._known_objects for obj in objects),'Setup outside retained snapshot graph')
        self._snapshot_bindings=list(zip(ids,objects))
    def read(self,obj,name,*args):
        try:
            require(type(name) is str and name in SNAPSHOT_READ_MEMBERS,'Getter outside bounded MILL snapshot scope')
            if name in ('GetNumMachineOfType','GetMachines'):
                require(len(args)==1 and type(args[0]) is int and args[0]==1,'Only existing MILL catalogue allowed')
            elif name=='Item':require(len(args)==1 and type(args[0]) is int and 0<=args[0]<512,'Bounded snapshot collection index required')
            elif name=='GetCWObjectID':require(len(args)==1 and id(args[0]) in self._known_objects,'Retained snapshot object ID required')
            else:require(not args,'Snapshot getter takes no arguments')
            return self._observe_read(obj,'getter',lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(type(name) is str and name in SNAPSHOT_READ_INTERFACES,'Interface outside bounded MILL snapshot scope')
            return self._observe_read(obj,'qi',lambda:_typed(obj,name,self.typelib_path))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def summary(self):
        out=super().summary();out.update(scope='BOUNDED_MILL_GLOBAL_SNAPSHOT_READ_V1',dispatch_available=False,
            retained_binding_checks=self._binding_checks,retained_binding_native_calls=self._binding_reads,
            original_route_qualification_extended=False,global_active_document_reads_batched=False,
            physical_geometry_or_manufacturing_qualified=False)
        return out

def _snapshot_bounded(ctx,clsid,diagnostic):
    """Same original MILL snapshot schema; unchanged global root acquisition."""
    started=perf_counter();state={};batch=None
    diagnostic.update(capture_complete=False,read_scope='BOUNDED_MILL_GLOBAL_SNAPSHOT_READ_V1')
    try:
        ctx.files();ctx.events();docinfo=ctx.identity()
        with ctx.guard() as g:
            try:
                addin=g.read(ctx.sw,'GetAddInObject',clsid);require(addin is not None,'CAM add-in must already be loaded')
                app=g.typed(g.read(addin,'GetCWApp'),'ICWApp4')
                active=g.read(app,'IGetActiveDoc');doc=g.typed(active,'ICWDoc3');part=g.typed(active,'ICWPartDoc')
                machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
                require(_int(g.read(doc,'GetDocType'))==1 and _int(g.read(machine,'MachType'))==1,'Existing MILL part required')
            finally:diagnostic['root_acquisition_guard']=g.summary()
        roots=dict(app=app,doc=doc,machine=machine)
        batch=ScopedMillSnapshotReadBatch(ctx.sw,ctx.typelib_path,native_context=roots,
            process_id=ctx.args['process_id'],expected_document=docinfo,source_sha256=ctx.args['expected_source_sha256'],
            evidence_pins=ctx.loaded['pins'],verify_evidence=ctx.files,verify_owned_process=ctx.owned,check_events=ctx.events)
        state.update(document=deepcopy(docinfo),saved_file_sha256=ctx.args['expected_source_sha256'])
        with batch:
            read,typed=batch.read,batch.typed
            def machine_info(obj,row):
                row['machine_type']=1;native=typed(obj,'ICWMillMachine')
                for name,key in (('Name','name'),('MachId','machine_id'),('Description','description')):row[key]=_text(read(native,name))
                return row
            state['current_machine']={};machine_info(machine,state['current_machine'])
            declared=_int(read(app,'GetNumMachineOfType',1));diagnostic['catalogue_declared_count']=declared
            candidates=_items(read(app,'GetMachines',1),typed,read,128)
            diagnostic['catalogue_collection_count']=len(candidates)
            require(declared==len(candidates),'MILL catalogue count differs from collection')
            state['mill_catalogue']=[];diagnostic['catalogue_entries']=[]
            for index,raw in enumerate(candidates):
                native=typed(raw,'ICWMillMachine');entry=dict(catalogue_index=index,read_complete=False,machine={})
                diagnostic['catalogue_entries'].append(entry);entry['observed_machine_type']=_int(read(native,'MachType'))
                require(entry['observed_machine_type']==1,'Non-MILL candidate in native catalogue')
                info=machine_info(native,entry['machine']);entry.update(read_complete=True)
                require(bool(info['machine_id']),'Empty native machine identity');state['mill_catalogue'].append(info)
            diagnostic['catalogue_read_complete']=True;groups={}
            for index,info in enumerate(state['mill_catalogue']):groups.setdefault(info['machine_id'],[]).append(index)
            diagnostic['duplicate_machine_ids']=[dict(machine_id=key,catalogue_indices=ids) for key,ids in groups.items() if len(ids)>1]
            diagnostic['catalogue_identity_unique']=not diagnostic['duplicate_machine_ids']
            setups=_items(read(machine,'IGetEnumSetups'),typed,read,8);state['feature_setups']=[]
            for raw in setups:
                setup=typed(raw,'ICWBaseSetup');features=_items(read(setup,'IGetEnumFeatures'),typed,read,256)
                row=dict(native_id=_object_id(doc,setup,read),name=_text(read(setup,'SetupName')),feature_count=len(features))
                mill_setup=typed(raw,'ICWSetup');row.update(axis_native=_vector(read(setup,'Axis')),
                    origin_native=_vector(read(mill_setup,'GetReferencePosition')),origin_type_raw=_int(read(mill_setup,'OriginType')))
                state['feature_setups'].append(row)
            require(len({r['native_id'] for r in state['feature_setups']})==len(setups),'Duplicate native setup identity')
            batch.bind_setups(state['feature_setups'],setups)
            op_setups=_items(read(machine,'IGetEnumOpSetups'),typed,read,8);state['operation_counts']=[]
            for raw in op_setups:
                setup=typed(raw,'ICWBaseOpSetup');state['operation_counts'].append(len(_items(read(setup,'IGetEnumOperations'),typed,read,512)))
            wp=read(machine,'IGetWorkpiece');state['material_raw']=None if wp is None or not bool(wp) else _text(read(typed(wp,'ICWWorkpiece'),'Material'))
            extend=read(doc,'ExtendHolesToStock');require(type(extend) is bool,'Strict ExtendHolesToStock required')
            state.update(extend_holes_to_stock=extend,unit_record_raw=None,
                unit_record_status='unavailable_native_getter_disabled_after_RPC_failure')
            diagnostic['observed_state']=deepcopy(state)
        batch.require_complete();require(ctx.identity()==docinfo,'Document changed during global snapshot')
        ctx.files();ctx.events();diagnostic['capture_complete']=True
        return state,dict(app=app,doc=doc,machine=machine,candidates=candidates,setups=setups)
    finally:
        diagnostic['observed_state']=deepcopy(state)
        diagnostic['elapsed_seconds']=perf_counter()-started
        if batch is not None:diagnostic['read_batch']=deepcopy(batch.summary())

def _capture_headers(ctx,clsid,reference,count,diagnostic):
    """Same complete20/21 header state, with strong global checks around a read batch."""
    require(type(count) is int and count in (20,21) and len(reference['features'])==20,
        'RAW face pre/post inventory required')
    started=perf_counter();diagnostic.update(header_read_mode='bounded_header_batch',capture_complete=False)
    state=native=batch=None
    try:
        ctx.files();ctx.events();doc=ctx.identity()
        before_started=perf_counter()
        with ctx.guard() as g:
            try:
                state,native=_snapshot_bounded(ctx,clsid,diagnostic.setdefault('global_snapshot_before',{}))
                diagnostic['header_state']=state
                diagnostic['capture_complete']=False
                require(state['document']==doc and sum(r['feature_count'] for r in state['feature_setups'])==count,
                    'Exact branch feature count required')
                state['stock'],_=_export_stock(g.read(native['machine'],'IGetWorkpiece'),ctx.typelib_path,g.read,diagnostic)
                require(state['stock']==reference['stock'],'Stock changed')
            finally:diagnostic['header_strong_before']=g.summary()
        diagnostic['header_strong_before_seconds']=perf_counter()-before_started
        batch=ScopedUpperHeaderReadBatch(ctx.sw,ctx.typelib_path,native_context=native,reference_state=state,
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
                read_route_operations(state,native,batch.read,batch.typed,diagnostic=diagnostic.setdefault('header_operations',{}))
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
                final,_=_snapshot_bounded(ctx,clsid,diagnostic.setdefault('global_snapshot_after',{}))
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

def _read_face(ctx,native,spec,new_id=None,diagnostic=None,persist=lambda:None):
    result={} if diagnostic is None else diagnostic
    with ctx.guard() as g:
        model=g.read(ctx.sw,'ActiveDoc');feature=g.read(model,'FeatureByName',spec['sketch_name'])
        require(feature is not None,'Required circle sketch missing')
        sketch=g.read(feature,'GetSpecificFeature2');g._fast();measured=_read_sketch(ctx.sw,sketch,spec);g._fast()
        result.update(sketch=measured,sketch_circle_m=_circle_sketch(measured,spec));persist()
        if new_id is None:return result
        found=g.read(native['doc'],'GetCWObjectFromID',1,new_id)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'New SLAB lookup failed')
        header,_=read_header(found[0],native['doc'],g.read,g.typed,69);result['feature']=header;persist()
        require(header['native_id']==new_id and header['volume_type']==5 and header['suppressed'] is False,'New unsuppressed SLAB required')
        mill=g.typed(found[0],'ICWMillFeature')
        header['taper_enabled']=g.read(mill,'Taper');header['island_count']=g.read(mill,'IGetIslandCount');persist()
        header['top_curves_native']=_circle_contour(mill,'IGetTopSegChain',ctx.typelib_path,g.read,g.typed);persist()
        header['bottom_curves_native']=_circle_contour(mill,'IGetBottomSegChain',ctx.typelib_path,g.read,g.typed);persist()
        return result

def _check_raw_stock(state):
    stock=state['stock']
    require(type(stock['type_raw']) is int and stock['type_raw']==4 and stock['length_units_raw']==0,'Imported RAW MILL stock required')
    a=stock['bounds_native'];b=[-.0325,-.0325,-.032,.0325,.0325,.028]
    require(type(a) in (list,tuple) and len(a)==6 and all(type(x) in (int,float) and math.isfinite(x) and abs(x-y)<1e-10 for x,y in zip(a,b)),
        'Existing stock bounds must remain D65 and upper Z28')

def create_raw_mill_face(sw,clsid,typelib_path,*,saved_cone_receipt_path,saved_cone_receipt_sha256,
        sketch_receipt_path,sketch_receipt_sha256,process_id,expected_document_path,expected_source_sha256,
        expected_feature_native_id,sketch_spec,route_scope,receipt_path,qualification_only,
        acknowledge_disposable_copy,message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    require(qualification_only is True and acknowledge_disposable_copy is True and message_policy=='vendor_default','Explicit disposable qualification required')
    spec=validate_face_spec(sketch_spec,route_scope)
    loaded=load_face_parent(saved_cone_receipt_path,saved_cone_receipt_sha256,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,
        expected_feature_native_id=expected_feature_native_id)
    _check_raw_stock(loaded['state'])
    sketch_evidence,sketch_pin,expected=cone.load_sketch_prerequisite(sketch_receipt_path,sketch_receipt_sha256,loaded,spec,process_id)
    loaded['pins']=canonical_evidence_pins(loaded['pins'],[sketch_pin])
    marker=face_marker(expected_document_path,expected_source_sha256);receipt=Path(receipt_path)
    require(receipt.is_absolute() and receipt.suffix.casefold()=='.json' and receipt.parent.is_dir()
        and not receipt.exists() and not receipt.is_symlink() and not marker.exists() and not marker.is_symlink(),'Fresh receipt and unattempted face region required')
    protected={_key(p['path']) for p in loaded['pins']+loaded.get('lineage_pins',[])}|{_key(expected_document_path)}
    require(_key(receipt) not in protected and _key(marker) not in protected and _key(marker)!=_key(receipt),'Output/evidence/source aliases')
    args=dict(process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,**loaded['ids'])
    report=dict(schema_version=1,scope=SCOPE,route_scope=route_scope,status='error',phase='preflight',process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256,parent_pin=loaded['parent_pin'],
        parent_cone_feature_native_id=expected_feature_native_id,face_module_pin=_self_pin(),sketch_receipt_pin=sketch_pin,
        evidence_pins=deepcopy(loaded['pins']),lineage_pins=deepcopy(loaded.get('lineage_pins',[])),sketch_spec=spec,
        receipt_path=str(receipt),marker_path=str(marker),target=deepcopy(TARGET),
        mutation_attempted=False,native_dispatch_pending=False,native_call_attempted=False,native_call_returned=False,
        creator_call_count=0,GOP_attempted=False,GTP_attempted=False,save_attempted=False,model_saved=False,
        sketch_edit_attempted=False,CAD_solid_edit_attempted=False,automatic_retry=False,automatic_replay=False,
        automatic_rollback=False,readback_verified=False,production_qualified=False,production_route_changed=False,
        may_generate=False,snapshot_diagnostics=[])
    created=claimed=False;session=ctx=None
    def persist():
        if created:_write_receipt(receipt,report)
    def events(active=True):
        value=session.summary();report['messages']=value
        require(value.get('subscribed') is True and value.get('active') is active and (active or value.get('disconnected') is True)
            and not any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),'CAM event/transport requires stop')
    def capture(phase,count):
        report['phase']=phase;diagnostic=dict(phase=phase);report['snapshot_diagnostics'].append(diagnostic);persist()
        try:
            state,native=_capture_headers(ctx,clsid,expected,count,diagnostic);diagnostic['observed_state']=deepcopy(state);persist()
            payload=cone._capture_payload(ctx,state,native,diagnostic)
            return state,native,payload
        finally:persist()
    def retained_cone(phase,native):
        value=cone._read_sketch_and_cone(ctx,native,loaded['sketch_spec'],expected_feature_native_id)
        report[phase+'_cone_observation']=value;persist()
        require(value==loaded['cone_observation'],'Existing saved cone/sketch changed')
        return value
    def pending():
        nonlocal claimed
        require(not report['creator_call_count'],'No second creator call')
        report.update(phase='CreateMillFeature2',mutation_attempted=True,native_call_attempted=True,native_dispatch_pending=True,creator_call_count=1)
        _write_receipt(marker,dict(scope=SCOPE,status='dispatch_pending',source=expected_document_path,source_sha256=expected_source_sha256,
            receipt_path=str(receipt),automatic_replay=False),create=True)
        claimed=True;persist()
    try:
        _write_receipt(receipt,report,create=True);created=True
        ctx=saved.UpperConeSaveContext(loaded,args,sw,typelib_path,None,events,expected);ctx.files();ctx.identity()
        ctx.app=cone._bootstrap(sw,clsid,typelib_path,expected_document_path);ctx.identity();session=CamMessageSession(ctx.app,typelib_path)
        with session:
            before,native,before_payload=capture('before',20)
            report.update(before=before,before_payload=before_payload);persist()
            report['before_state_equivalence']={};cone.require_state_equivalent(expected,before,diagnostic=report['before_state_equivalence']);persist()
            retained_cone('before',native)
            report['face_sketch_before']={};_read_face(ctx,native,spec,diagnostic=report['face_sketch_before'],persist=persist)
            owners=[i for i,row in enumerate(before['feature_setups']) if row['native_id']==69]
            require(len(owners)==1 and before['feature_setups'][owners[0]]['axis_native']==[0.,0.,-1.],'Exact existing negativeZ owner69 required')
            with ctx.guard() as g:
                setup=g.typed(native['setups'][owners[0]],'ICWSetup')
                require(_object_id(native['doc'],setup,g.read)==69,'Creator owner changed')
                value=g.dispatch_once(lambda:_member(setup,'CreateMillFeature2',6,spec['sketch_name'],False,2.0,
                    False,False,False,False,0.0,-1,False,0,0),persist_pending=pending)
                report.update(native_call_returned=True,native_dispatch_pending=False);persist()
            report['dispatch_guard']=g.summary();_nonnull(value,'CreateMillFeature2 return')
            require(_is_comtypes_pointer(value),'CreateMillFeature2 must return typed IDispatch, not scalar HRESULT')
            with ctx.guard() as g:new_id=_object_id(native['doc'],value,g.read)
            report['new_feature_native_id']=new_id;persist()
            after,native,after_payload=capture('after',21);report.update(after=after,after_payload=after_payload);persist()
            report['after_state_equivalence']={};report['new_feature']=verify_face_delta(before,after,new_id,69,diagnostic=report['after_state_equivalence'])
            retained_cone('after',native)
            report['face_observation']={};observation=_read_face(ctx,native,spec,new_id,diagnostic=report['face_observation'],persist=persist)
            report['geometry_acceptance']=verify_face_geometry(observation['feature'],observation['sketch_circle_m'],new_id)
            require(before_payload==after_payload,'Protected payload changed')
        events(False);ctx.files();require(ctx.identity()==after['document'],'Document changed during cleanup')
        report.update(status='review_required',phase='finished',readback_verified=True,feature_delta_verified=True,
            native_configuration_captured=True,coordinate_frame_qualified=False,geometric_depth_verified=False,
            source_after_sha256=_file_hash(expected_document_path),reason='ONE_UNSAVED_RAW_MILL_FACE_CONFIGURATION_ONLY')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        try:
            persist()
            if claimed:_write_receipt(marker,dict(scope=SCOPE,status=report['status'],source=expected_document_path,source_sha256=expected_source_sha256,
                receipt_path=str(receipt),receipt_sha256=_file_hash(receipt),native_call_attempted=report['native_call_attempted'],
                native_call_returned=report['native_call_returned'],readback_verified=report['readback_verified'],automatic_replay=False))
        except Exception as exc:report.update(status='uncertain',readback_verified=False,receipt_write_error=_error(exc))
    return report

PARAMS={'saved_cone_receipt_path','saved_cone_receipt_sha256','sketch_receipt_path','sketch_receipt_sha256','process_id',
    'expected_document_path','expected_source_sha256','expected_feature_native_id','sketch_spec','route_scope',
    'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy','addin_clsid','module_sha256'}

def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='create_raw_mill_face','Only create-RAW-face action supported')
    p=request['params'];require(type(p) is dict and set(p)==PARAMS,'Exact RAW face request fields required')
    require(type(p['process_id']) is int and p['process_id']>0 and type(p['expected_feature_native_id']) is int and p['expected_feature_native_id']>0,'Exact PID and parent cone ID required')
    for key,value in p.items():
        if key.endswith('sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
        if key.endswith('path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
    validate_face_spec(p['sketch_spec'],p['route_scope'])
    require(p['module_sha256']==_self_pin()['sha256'] and p['qualification_only'] is True and p['acknowledge_disposable_copy'] is True
        and p['message_policy']=='vendor_default','Exact module and qualification required')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']),'Exact add-in CLSID required')
    return dict(p)

def dispatch_request(request):
    p=validate_request(request)
    load_face_parent(p['saved_cone_receipt_path'],p['saved_cone_receipt_sha256'],**{k:p[k] for k in
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
        return create_raw_mill_face(sw,registration['clsid'],str(Path(registration['addin_path']).parent/'camworks.tlb'),**p)

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--result',required=True)
    a=parser.parse_args(argv);source,target=Path(a.request),Path(a.result)
    require(source.is_absolute() and source.is_file() and source.stat().st_size<=65536,'Bounded request required')
    require(target.is_absolute() and target.parent.is_dir() and target.suffix.lower()=='.json' and not target.exists() and not target.is_symlink(),'Fresh result path required')
    try:
        request=json.loads(source.read_text(encoding='utf-8'));p=validate_request(request)
        require(_key(target)!=_key(source) and _key(target) not in {_key(v) for k,v in p.items() if k.endswith('path')},'Output aliases request/input')
        result=dispatch_request(request)
    except Exception as exc:result=dict(status='error',issue=_error(exc),automatic_replay=False)
    _write_receipt(target,result,create=True)
    print(json.dumps(dict(status=result.get('status'),readback_verified=result.get('readback_verified'),result_path=str(target))))
    return 0 if result.get('readback_verified') is True else 2

if __name__=='__main__':raise SystemExit(main())
