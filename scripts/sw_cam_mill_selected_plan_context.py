"""Bounded header and operation capture for one selected MILL plan."""
from contextlib import ExitStack
from copy import deepcopy
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles
from scripts.sw_cam_mill_qualification import _snapshot, _vector
from scripts.sw_cam_mill_inventory_geometry import _integer, _number
from scripts.sw_cam_mill_units_qualification import _features, _bodies, _nonnull
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_profile_headers import read_profile_feature_headers
from scripts.sw_cam_mill_route_context import read_route_operations
from scripts.sw_operation_guard import check_document_target

MAX_READS = 4096

def read_header(raw, doc, read, typed, owner):
    base = typed(raw,'ICWFeature'); mill=typed(raw,'ICWMillFeature')
    out = dict(native_id=_integer(_object_id(doc,base,read),'feature ID',1),
        volume_type=_integer(read(mill,'VolumeType'),'VolumeType'),
        subtype_raw=_integer(read(mill,'SubType'),'SubType'),
        shape_raw=_integer(read(mill,'Shape'),'Shape'))
    out['suppressed'] = read(base,'Suppressed')
    if type(out['suppressed']) is not bool: raise ValueError('Strict feature suppression flag required')
    out['name'] = read(base,'FeatureName')
    if type(out['name']) is not str or len(out['name'])>1024: raise ValueError('Bounded feature name required')
    out['axis_native'] = _vector(read(base,'Axis'))
    out['depth_native'] = _number(read(mill,'Depth'))
    out['bounds_native'] = _vector(read(mill,'GetBoundParams'))
    out['start_native'] = _vector(read(mill,'GetStartPosition'))
    if _object_id(doc,_nonnull(read(base,'GetOwner'),'feature owner'),read) != owner:
        raise ValueError('Feature moved to a different owner setup')
    return out,base

def read_options(doc, read):
    out={}
    for getter, values in [('GetEMFFeatTypeOptions',range(6)),('GetEMFPartPeriTypeOptions',range(2)),
                           ('GetEMFTypeOptions',range(4))]:
        out[getter]=[]
        for index in values:
            v=read(doc,getter,index)
            if type(v) is not bool: raise ValueError('Strict recognition option required')
            out[getter].append(dict(enum_value=index,enabled=v))
    v=read(doc,'FeatureCreationStyle')
    if type(v) is not int or v not in (0,1): raise ValueError('Known feature creation style required')
    method=dict(value=v,name='AFR' if v==0 else 'MFGVIEW',status='observed_via_ICWDoc3_FeatureCreationStyle')
    for name in ('EMFHoleMaxDiameter','EMFHoleMinimumIncludedAngle'):
        out[name]=_number(read(doc,name))
    return out,method

def resolve_expected_feature_count(evidence, explicit=None):
    if explicit is None:
        context=getattr(evidence,"state",getattr(evidence,"context",None))
        explicit=len(context["features"]) if context is not None else 18
        if explicit==19 and getattr(evidence,"data",{}).get("scope")!="MILL_ADDED_CIRCULAR_POCKET_PLAN_V1":
            raise ValueError("Nineteen features require a verified additive pocket anchor")
    if type(explicit) is not int or explicit not in (18,19):
        raise ValueError("Only the exact original18 or additive19 feature scope is supported")
    return explicit

def capture_selected_plan(sw,clsid,typelib_path,expected_path,*,process_id,
        expected_source_sha256,evidence,check,diagnostic,progress=lambda:None,operation_details_reader=None,
        expected_feature_count=None):
    """All COM reads guarded; pointers expire at the caller's event-session boundary."""
    expected_feature_count=resolve_expected_feature_count(evidence,expected_feature_count)
    diagnostic.update(capture_complete=False,native_read_count=0,native_qi_count=0,
                      identity_scope='feature_setup_operation_and_phase_boundaries')
    def identity():
        pid=_member(sw,'GetProcessID')
        if type(pid) is not int or pid!=process_id: raise ValueError('Exact process changed')
        d=raw_part_identity(sw)
        check_document_target(d['path'],d['title'],expected_path=expected_path,required=True)
        if _file_hash(expected_path)!=expected_source_sha256: raise ValueError('Saved source changed')
        return d
    check(); begin=identity(); evidence.check_files(); check()
    with ExitStack() as stack:
        files=[stack.enter_context(_CaptureReadFiles(expected_path))]
        files.extend(stack.enter_context(_CaptureReadFiles(p['path'])) for p in evidence.pins)
        def guard():
            check()
            for item in files:item.check()
            check()
        def boundary(stage):
            guard(); diagnostic['stage']=stage
            pid=_member(sw,'GetProcessID')
            if type(pid) is not int or pid!=process_id or raw_part_identity(sw)!=begin:
                raise ValueError('Document/PID/dirty state changed at capture boundary')
            guard(); progress()
        def read(obj,name,*args):
            guard()
            if diagnostic['native_read_count']>=MAX_READS: raise ValueError('Header/operation read budget exceeded')
            diagnostic.update(stage=name,native_read_count=diagnostic['native_read_count']+1)
            value=_member(obj,name,*args);guard();return value
        def typed(raw,name):
            guard()
            diagnostic['native_qi_count']+=1
            if diagnostic['native_qi_count']>=MAX_READS: raise ValueError('QI budget exceeded')
            if name in ('ICWOperation','ICWBaseOpSetup'):boundary('QI '+name)
            value=_nonnull(_typed(_nonnull(raw,name+' raw'),name,typelib_path),name)
            guard();return value
        boundary('machine_before')
        state,native=_snapshot(sw,clsid,typelib_path,expected_path,check=guard,
                              diagnostic=diagnostic,required_machine_type=1)
        diagnostic['capture_complete']=False
        if sum(r['feature_count'] for r in state['feature_setups'])!=expected_feature_count:
            raise ValueError('Current feature count differs from pinned expected count')
        boundary('recognition_options')
        state['recognition_options'],state['recognition_method']=read_options(native['doc'],read)
        boundary('stock')
        state['stock'],_=evidence.read_stock(read(native['machine'],'IGetWorkpiece'),typelib_path,read,diagnostic)
        state['features']=[]; ids=set()
        for si,raw_setup in enumerate(native['setups']):
            boundary('setup:'+str(si))
            setup=typed(raw_setup,'ICWBaseSetup')
            sid=_object_id(native['doc'],setup,read)
            if sid!=state['feature_setups'][si]['native_id']:raise ValueError('Setup identity changed')
            values=_items(read(setup,'IGetEnumFeatures'),typed,read,expected_feature_count)
            if len(values)!=state['feature_setups'][si]['feature_count']:raise ValueError('Feature count changed')
            for fi,raw in enumerate(values):
                boundary('feature:'+str(si)+':'+str(fi))
                row,base=read_header(raw,native['doc'],read,typed,sid)
                if row['native_id'] in ids:raise ValueError('Duplicate native feature identity')
                ids.add(row['native_id'])
                state['features'].append(dict(setup_index=si,feature_index=fi,setup_native_id=sid,geometry=row))
                if row['native_id']==evidence.selected['feature_native_id']:
                    native['selected_feature']=base
                boundary('feature_end:'+str(row['native_id']))
        boundary('selected_profile')
        state['selected_profile_headers']=read_profile_feature_headers(native['doc'],selected=evidence.selected,
            read=read,typed=typed,diagnostic=diagnostic.setdefault('selected_profile',{}),progress=progress)
        if 'selected_feature' not in native:raise ValueError('Selected feature missing from enumeration')
        boundary('operations')
        read_route_operations(state,native,read,typed,diagnostic=diagnostic.setdefault('operations',{}))
        if operation_details_reader is not None:
            boundary('operation_details')
            operation_details_reader(state,native,read,typed,diagnostic.setdefault('operation_details',{}),
                boundary=lambda:boundary('tool_detail_check'))
            boundary('operation_details_end')
        boundary('solidworks_reference')
        model=sw.ActiveDoc;guard();tree,_=_features(model);guard();solids=_bodies(model);guard()
        state['sw_reference']=dict(feature_tree=tree,solids=solids)
        visible=read(model,'GetBodies2',0,True)
        if visible is None:visible_count=0
        elif isinstance(visible,(tuple,list)) and len(visible)<=64:visible_count=len(visible)
        else:raise ValueError('Bounded visible solid collection required')
        state.update(visible_solid_body_count=visible_count,all_solid_body_count=len(solids))
        boundary('machine_after')
        final,_=_snapshot(sw,clsid,typelib_path,expected_path,check=guard,required_machine_type=1)
        if any(state[key]!=value for key,value in final.items()):raise ValueError('Machine/header state changed during capture')
        boundary('capture_end')
        if identity()!=begin or state['document']!=begin:raise ValueError('Document/source changed across capture')
        evidence.check_files();guard()
    diagnostic.update(capture_complete=True,stage='complete')
    return state,native

def exact_dispatch_target(native, evidence, read):
    selected=evidence.selected
    value=read(native['doc'],'GetCWObjectFromID',1,selected['feature_native_id'])
    if not isinstance(value,(tuple,list)) or len(value)!=2 or value[1] is not True:
        raise ValueError('Exact pre-dispatch feature lookup failed')
    feature=native['selected_feature']
    if (_object_id(native['doc'],value[0],read)!=selected['feature_native_id']
        or _object_id(native['doc'],feature,read)!=selected['feature_native_id']
        or _object_id(native['doc'],read(feature,'GetOwner'),read)!=selected['owner_setup_native_id']
        or read(feature,'Suppressed') is not False):
        raise ValueError('Exact pre-dispatch target/owner changed')
    return feature
