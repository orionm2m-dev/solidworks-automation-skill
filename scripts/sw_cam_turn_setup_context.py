"""Bounded TURN setup links and frame metadata; no matrix decoder or mutation."""
from ctypes import HRESULT, POINTER, c_double, c_int
from ctypes.wintypes import VARIANT_BOOL
import re
from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_operation_profile import _integer, _number, _values, _position
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_turn_feature_attribute import _items

_COUNTS = {
    "expected_feature_count": (1,64), "expected_operation_count": (1,512),
    "expected_feature_setup_count": (1,64), "expected_operation_setup_count": (1,64),
    "expected_generated_operation_count": (0,512), "expected_toolpath_record_count": (0,2147483647)}
_SETUP_IDS = ("expected_feature_setup_native_id", "expected_operation_setup_native_id")
_GUID = re.compile(r"^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$")


def validate_config(config):
    if type(config) is not dict or set(config) != set(_COUNTS) | set(_SETUP_IDS):
        raise ValueError("Exact setup counts and optional setup IDs required")
    for name,(lo,hi) in _COUNTS.items():
        if type(config[name]) is not int or not lo <= config[name] <= hi:
            raise ValueError("Invalid strict setup count: " + name)
    for name in _SETUP_IDS:
        value=config[name]
        if value is not None and (type(value) is not int or not 1 <= value < 2**32):
            raise ValueError("Optional setup ID must be a positive native ULONG")
    if config["expected_generated_operation_count"] > config["expected_operation_count"]:
        raise ValueError("Generated operations cannot exceed operation count")
    return dict(config)


def verify_counts(inventory,config):
    observed={"expected_"+name:inventory[name] for name in
        ("feature_count","operation_count","feature_setup_count","operation_setup_count")}
    observed["expected_generated_operation_count"]=sum(row["toolpath_generated"] for row in inventory["operations"])
    observed["expected_toolpath_record_count"]=sum(sum(row["toolpath_record_counts"]) for row in inventory["operations"])
    if any(observed[name] != config[name] for name in _COUNTS):
        raise ValueError("Exact setup/feature/operation/generated-path counts changed")


def setup_abi(typelib_path):
    """Validate only known getter signatures; no object activation or dispatch."""
    from comtypes.automation import IDispatch, VARIANT
    dispatch=POINTER(IDispatch)
    specs=[
        ("ICWBaseSetup","_get_Axis",5,(POINTER(VARIANT),),(10,),True),
        ("ICWBaseSetup","IsReverseDirection",10,(POINTER(VARIANT_BOOL),),(10,),False),
        ("ICWBaseSetup","IGetRefPoint",6,(POINTER(dispatch),),(10,),False),
        ("ICWBaseSetup","IGetXYTransform",7,(POINTER(dispatch),),(10,),False),
        ("ICWBaseOpSetup","_get_Axis",2,(POINTER(VARIANT),),(10,),True),
        ("ICWBaseOpSetup","GetSetup",30,(POINTER(dispatch),),(10,),False),
        ("ICWBaseOpSetup","GetSetupOriginInFCSSpace",13,(POINTER(c_double),)*3,(2,2,2),False),
        ("ICWBaseOpSetup","IGetXYTransform",18,(POINTER(dispatch),),(10,),False),
        ("ICWTransform","GetData",3,(POINTER(dispatch),)*4+(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,)*6,False),
        ("ICWPosition","GetCoordinates",1,(POINTER(c_double),)*3,(2,)*3,False)]
    result=[]
    for owner,name,dispid,args,flags,prop in specs:
        interface=_interface_class(owner,typelib_path)
        matches=[m for m in interface._methods_ if m.name==name]
        if len(matches)!=1: raise ValueError("Exact unique setup getter required: "+owner+"."+name)
        method=matches[0]
        if (method.restype is not HRESULT or method.idlflags[0]!=dispid or method.argtypes!=args
                or tuple(p[0] for p in method.paramflags)!=flags or (prop and "propget" not in method.idlflags)):
            raise ValueError("Exact setup getter ABI changed: "+owner+"."+name)
        result.append(dict(interface=owner,iid=str(interface._iid_).upper(),method=name,dispid=dispid))
    return dict(methods=result,native_calls=0)


def _metadata(obj,read):
    """Reuse the bounded standard IDispatch type-info route; never guess an IID."""
    if obj is None or not bool(obj): raise ValueError("Non-null returned object required")
    info=read(obj,"GetTypeInfo",0)
    if info is None or not bool(info): raise ValueError("Returned object has no type information")
    attr=read(info,"GetTypeAttr")
    guid=str(attr.guid).upper()
    kind,count=int(attr.typekind),int(attr.cFuncs)
    if not _GUID.fullmatch(guid) or not 0<=kind<=8 or not 0<=count<=4096:
        raise ValueError("Bounded returned object type metadata required")
    return dict(guid=guid,typekind=kind,member_count=count)


def _vector(raw):
    return list(map(_number,_values(raw,3)))


def _canonical(obj,read):
    from comtypes import IUnknown
    return read(obj,"QueryInterface",IUnknown)


def _transform(owner,typelib_path,read,result):
    result.update(present=False,decoded=False,GetData_called=False,output_coordinates_read=False,
                  generic_cl_frame_verified=False)
    raw=read(owner,"IGetXYTransform")
    if raw is None or not bool(raw): raise ValueError("Non-null setup transform required")
    result.update(present=True,type_metadata=_metadata(raw,read))
    if result["type_metadata"]["guid"] != _INTERFACES["ICWTransform"]:
        raise ValueError("Observed transform type is not exact ICWTransform; no fallback")
    transform=_typed(raw,"ICWTransform",typelib_path)
    values=read(transform,"GetData")
    result["GetData_called"]=True
    if type(values) not in (tuple,list) or len(values)!=6:
        raise ValueError("Transform GetData must return exactly six OUT values")
    result["scale_raw"]=_number(values[4])
    if type(values[5]) is not bool: raise ValueError("Transform rotation flag must be a native Boolean")
    result["rotate_raw"]=values[5]
    result["output_types"]={}
    for name,value in zip(("x_axis","y_axis","z_axis","translation"),values[:4]):
        result["output_types"][name]=_metadata(value,read)
    result["reason"]="GetData output interface GUIDs observed; no output QI, coordinate getter or matrix convention inferred"


def read_setup_context(doc,machine,operation_setups,selected_index,typelib_path,config,selected_operation,read,check,result):
    """Both setup collections are independent; GetSetup supplies their native link."""
    result.update(complete=False,units_verified=False,coordinate_frame_verified=False,
        generic_cl_frame_verified=False,feature_setups=[],operation_setups=[],
        setup_native_ids_discovered=config["expected_feature_setup_native_id"] is None or config["expected_operation_setup_native_id"] is None)
    raw_features=_items(read(machine,"IGetEnumSetups"),typelib_path,read,limit=64)
    if len(raw_features)!=config["expected_feature_setup_count"] or len(operation_setups)!=config["expected_operation_setup_count"]:
        raise ValueError("Exact setup counts changed")
    feature_handles={};canonical_handles={};all_features=[]
    for index,raw in enumerate(raw_features):
        setup=_typed(raw,"ICWBaseSetup",typelib_path);sid=_object_id(doc,setup,read)
        if sid in feature_handles: raise ValueError("Duplicate native feature setup ID")
        features=_items(read(setup,"IGetEnumFeatures"),typelib_path,read,limit=64-len(all_features))
        ids=[_object_id(doc,feature,read) for feature in features]
        all_features.extend(ids)
        feature_handles[sid]=setup;canonical_handles[sid]=_canonical(setup,read)
        result["feature_setups"].append(dict(index=index,native_id=sid,feature_native_ids=ids))
    if len(all_features)!=config["expected_feature_count"] or len(set(all_features))!=len(all_features):
        raise ValueError("Feature native identity/count inventory changed")
    all_ops=[];selected=None;seen_setups=[]
    for index,raw in enumerate(operation_setups):
        setup=_typed(raw,"ICWBaseOpSetup",typelib_path);sid=_object_id(doc,setup,read)
        if sid in seen_setups: raise ValueError("Duplicate native operation setup ID")
        seen_setups.append(sid)
        linked_raw=read(setup,"GetSetup")
        if linked_raw is None or not bool(linked_raw): raise ValueError("Operation setup has no linked feature setup")
        feature_setup=_typed(linked_raw,"ICWBaseSetup",typelib_path);fid=_object_id(doc,feature_setup,read)
        if fid not in feature_handles: raise ValueError("GetSetup links outside current feature setups")
        canonical=_canonical(feature_setup,read)
        same=bool(canonical==canonical_handles[fid])
        row=dict(index=index,native_id=sid,feature_setup_native_id=fid,
            feature_setup_canonical_identity_equal=same,operations=[])
        result["operation_setups"].append(row)
        features=next(item["feature_native_ids"] for item in result["feature_setups"] if item["native_id"]==fid)
        operations=_items(read(setup,"IGetEnumOperations"),typelib_path,read,limit=512-len(all_ops))
        for oi,raw_op in enumerate(operations):
            op=_typed(raw_op,"ICWOperation",typelib_path);oid=_object_id(doc,op,read)
            refs=_items(read(op,"IGetAllFeatures"),typelib_path,read,limit=64)
            ids=[_object_id(doc,feature,read) for feature in refs]
            if len(ids)!=len(set(ids)) or not set(ids)<=set(features): raise ValueError("Operation links do not belong to its native feature setup")
            row["operations"].append(dict(index=oi,native_id=oid,linked_feature_ids=ids))
            all_ops.append(oid)
        if index==selected_index:
            if config["expected_operation_setup_native_id"] not in (None,sid) or config["expected_feature_setup_native_id"] not in (None,fid):
                raise ValueError("Exact selected setup native ID differs")
            selected_oi=selected_operation["operation_index"]
            if selected_oi>=len(row["operations"]): raise ValueError("Selected operation absent from repeated setup enumeration")
            repeated=row["operations"][selected_oi]
            linked_ids=selected_operation["linked_feature_ids"]
            if repeated["native_id"]!=selected_operation["native_id"] or sorted(repeated["linked_feature_ids"])!=sorted(linked_ids):
                raise ValueError("Repeated setup enumeration contradicts the pinned selected operation")
            if not set(linked_ids)<=set(features): raise ValueError("Selected feature IDs absent from linked setup")
            selected=(setup,feature_setup,sid,fid)
    if len(all_ops)!=config["expected_operation_count"] or len(set(all_ops))!=len(all_ops) or selected is None:
        raise ValueError("Operation native identity/count inventory changed")
    setup,feature_setup,sid,fid=selected
    state=dict(operation_setup_native_id=sid,feature_setup_native_id=fid)
    result["selected_setup"]=state
    state["operation_axis_native"]=_vector(read(setup,"Axis"))
    state["feature_axis_native"]=_vector(read(feature_setup,"Axis"))
    reverse=read(feature_setup,"IsReverseDirection")
    if type(reverse) is not bool: raise ValueError("Reverse-direction flag must be a native Boolean")
    state["is_reverse_direction"]=reverse
    state["origin_in_fcs_native"]=_vector(read(setup,"GetSetupOriginInFCSSpace"))
    position=read(feature_setup,"IGetRefPoint")
    state["reference_point_type"]=_metadata(position,read)
    if state["reference_point_type"]["guid"] != _INTERFACES["ICWPosition"]:
        raise ValueError("Observed reference point is not exact ICWPosition; no fallback")
    state["reference_point_native"]=_position(position,typelib_path,read)
    for name,owner in (("feature_xy_transform",feature_setup),("operation_xy_transform",setup)):
        state[name]={};_transform(owner,typelib_path,read,state[name])
    check();result["complete"]=True


def inspect_turn_setup_context(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,setup_index,operation_index,
        expected_operation_native_id,expected_operation_type,expected_linked_feature_ids,
        expected_feature_count,expected_operation_count,expected_feature_setup_count,
        expected_operation_setup_count,expected_generated_operation_count,expected_toolpath_record_count,
        expected_feature_setup_native_id=None,expected_operation_setup_native_id=None,
        action="read",message_policy="vendor_default"):
    from scripts.sw_cam_turn_variable_allowance import _inspect_turn_operation_parameters
    config={name:value for name,value in locals().copy().items() if name in _COUNTS or name in _SETUP_IDS}
    return _inspect_turn_operation_parameters(sw,clsid,typelib_path,process_id=process_id,
        expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,setup_index=setup_index,operation_index=operation_index,
        expected_operation_native_id=expected_operation_native_id,expected_operation_type=expected_operation_type,
        expected_linked_feature_ids=expected_linked_feature_ids,action=action,message_policy=message_policy,
        inspection_scope="turn_setup_context",setup_context_config=config)
