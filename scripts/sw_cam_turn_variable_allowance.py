"""Read-only operation-owned turning allowances and bounded bore rough options.
Optional own-tool contours; no setter, CL read, GTP, GOP, save or inferred unit conversion.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_qualification_context import _segment_profile
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_operation_profile import _integer, _number, _read_profile
from scripts.sw_executable_launch import _process_identity
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock

_MODE_INTERFACES={1:'ICWTurnRoughOp',2:'ICWTurnFinishOp'}

_BORE_BOOL = {"RadialCut": 8, "AxialCut": 9, "ReverseCut": 10,
              "MirrorAboutCenterline": 11, "Undercut": 20}
_BORE_NUMBER = {"FirstCutAmt": 12, "MaxCutAmt": 13, "FinalCutAmt": 14,
                "RadialStockAmt": 25, "AxialStockAmt": 26}


def _bore_options_abi(typelib_path, *, include_leftover_control=False):
    """Metadata-only exact getter contract; no activation, QI or setters."""
    from ctypes import HRESULT, POINTER, c_int, c_double
    from ctypes.wintypes import VARIANT_BOOL
    interface = _interface_class("ICWTurnBoreRoughOp", typelib_path)
    specifications = [("_get_"+name, dispid, VARIANT_BOOL) for name,dispid in _BORE_BOOL.items()]
    specifications += [("_get_"+name, dispid, c_double) for name,dispid in _BORE_NUMBER.items()]
    specifications += [("GetAllowanceMethodVariable", 23, c_int)]
    if include_leftover_control:
        specifications += [("_get_GenerateLeftOver", 21, VARIANT_BOOL), ("_get_LEFTOVER_TYPE", 22, c_int)]
    for name,dispid,scalar in specifications:
        methods = [m for m in interface._methods_ if m.name == name]
        if len(methods) != 1:
            raise ValueError("Unique exact bore getter required: "+name)
        method = methods[0]
        if (method.restype is not HRESULT or method.idlflags[0] != dispid
                or method.argtypes != (POINTER(scalar),)
                or tuple(x[0] for x in method.paramflags) != (10,)
                or (name.startswith("_get_") and "propget" not in method.idlflags)):
            raise ValueError("Exact bore getter ABI differs: "+name)
    return dict(interface="ICWTurnBoreRoughOp", iid=str(interface._iid_).upper(),
                getter_count=len(specifications), native_calls=0)


def _read_bore_options(raw, typelib_path, read, result, *, include_leftover_control=False):
    interface = _typed(raw, "ICWTurnBoreRoughOp", typelib_path)
    for name in _BORE_BOOL:
        value = read(interface,name)
        if type(value) is not bool:
            raise ValueError("Bore option must be a strict Boolean: "+name)
        result[name] = value
    for name in _BORE_NUMBER:
        result[name] = _number(read(interface,name))
    mode = read(interface,"GetAllowanceMethodVariable")
    if type(mode) is not int or not -(2**31) <= mode < 2**31:
        raise ValueError("Bore allowance method must be exact native LONG")
    result["GetAllowanceMethodVariable"] = mode
    if include_leftover_control:
        generated = read(interface, "GenerateLeftOver")
        if type(generated) is not bool:
            raise ValueError("GenerateLeftOver must be a strict Boolean")
        result["GenerateLeftOver"] = generated
        kind = read(interface, "LEFTOVER_TYPE")
        if type(kind) is not int or kind not in range(5):
            raise ValueError("LEFTOVER_TYPE must be a declared native enum 0..4")
        result["LEFTOVER_TYPE"] = kind



def _tool_contour_abi(typelib_path):
    """Exact two profile calls and operation-orientation getter, metadata only."""
    from ctypes import HRESULT, POINTER, c_int
    from comtypes.automation import IDispatch
    dispatch = POINTER(IDispatch)
    specs = (("ICWTool", "GetToolProfile", 12, (POINTER(dispatch),), (10,)),
             ("ICWTurnToolHolder", "GetHolderProfile", 1, (dispatch, POINTER(dispatch)), (1,10)),
             ("ICWTurnToolHolder", "GetToolOrientationForOperation", 7, (dispatch, POINTER(c_int)), (1,10)))
    observed = []
    for owner,name,dispid,args,flags in specs:
        interface = _interface_class(owner, typelib_path)
        methods = [m for m in interface._methods_ if m.name == name]
        if len(methods) != 1:
            raise ValueError("Unique exact tool contour getter required: " + name)
        method = methods[0]
        if (method.restype is not HRESULT or method.idlflags[0] != dispid
                or method.argtypes != args or tuple(x[0] for x in method.paramflags) != flags):
            raise ValueError("Exact tool contour getter ABI differs: " + name)
        observed.append(dict(interface=owner, iid=str(interface._iid_).upper(), method=name, dispid=dispid))
    return dict(methods=observed, native_calls=0)


def _read_bore_tool_contours(doc, operation, typelib_path, expected_tool_id, read, result):
    """Read only the selected own diamond insert and its operation-specific holder contour."""
    result.update(coordinate_frame_verified=False, program_point_verified=False, units_verified=False,
                  solid_geometry_verified=False, physical_holder_verified=False, complete=False)
    raw_tool = read(operation, "IGetTool")
    if raw_tool is None or not bool(raw_tool):
        raise ValueError("Selected operation has no own tool")
    tool = _typed(raw_tool, "ICWTool", typelib_path)
    result["tool_native_id"] = _object_id(doc, tool, read)
    if result["tool_native_id"] != expected_tool_id:
        raise ValueError("Exact selected own tool ID differs")
    result["tool_type_raw"] = _integer(read(tool, "ToolType"))
    if result["tool_type_raw"] != 15:
        raise ValueError("Only an existing TURN tool contour is supported")
    turn = _typed(raw_tool, "ICWTurnTool", typelib_path)
    result["turn_tool_type_raw"] = _integer(read(turn, "ToolType"))
    if result["turn_tool_type_raw"] != 1:
        raise ValueError("Only an existing single-point TURN insert is supported")
    result["insert_type_raw"] = _integer(read(turn, "InsertType"))
    if result["insert_type_raw"] != 1:
        raise ValueError("Only an existing diamond insert is supported")
    result["insert_dimensions_native"] = {}
    for field in ("IncludedAngle", "NoseRadius", "InscribedCircle", "Thickness"):
        result["insert_dimensions_native"][field] = _number(read(turn, field))
    raw_holder = read(turn, "IGetTurnToolHolder")
    if raw_holder is None or not bool(raw_holder):
        raise ValueError("Selected own tool has no holder")
    holder = _typed(raw_holder, "ICWTurnToolHolder", typelib_path)
    result["holder_type_raw"] = _integer(read(holder, "GetHolderType"))
    if result["holder_type_raw"] != 2:
        raise ValueError("Only an existing boring-bar holder is supported")
    result["holder_id_raw"] = _integer(read(holder, "GetHolderId"))
    if result["holder_id_raw"] < 0:
        raise ValueError("Existing boring-bar holder ID must be nonnegative")
    result["orientation_for_operation_raw"] = _integer(read(holder, "GetToolOrientationForOperation", operation))
    result["insert_offsets_native"] = {}
    for field in ("XInsertOffset", "ZInsertOffset"):
        result["insert_offsets_native"][field] = _number(read(holder, field))
    for label,owner,method,args in (("insert_profile",tool,"GetToolProfile",()),
                                  ("holder_profile",holder,"GetHolderProfile",(operation,))):
        profile = dict(source_method=method)
        result[label] = profile
        raw_chain = read(owner, method, *args)
        _segment_profile(raw_chain, typelib_path, read, profile)
        if not profile.get("available") or not profile.get("parameters_complete"):
            raise ValueError("Complete bounded line/arc contour required: " + label)
    result["complete"] = True


def _read_cutoff_tool_contours(doc, operation, typelib_path, expected_tool_id, read, result):
    """仅读取 CutOff 自有槽刀及该操作专用夹持器轮廓；不推断坐标系。"""
    result.update(coordinate_frame_verified=False, program_point_verified=False, units_verified=False,
                  solid_geometry_verified=False, physical_holder_verified=False, complete=False)
    raw_tool = read(operation, "IGetTool")
    if raw_tool is None or not bool(raw_tool):
        raise ValueError("Selected operation has no own tool")
    tool = _typed(raw_tool, "ICWTool", typelib_path)
    result["tool_native_id"] = _object_id(doc, tool, read)
    if result["tool_native_id"] != expected_tool_id:
        raise ValueError("Exact selected own tool ID differs")
    result["tool_type_raw"] = _integer(read(tool, "ToolType"))
    if result["tool_type_raw"] != 15:
        raise ValueError("Only an existing TURN tool contour is supported")
    turn = _typed(raw_tool, "ICWTurnTool", typelib_path)
    result["turn_tool_type_raw"] = _integer(read(turn, "ToolType"))
    if result["turn_tool_type_raw"] != 1:
        raise ValueError("Only an existing single-point TURN insert is supported")
    result["insert_type_raw"] = _integer(read(turn, "InsertType"))
    if result["insert_type_raw"] != 2:
        raise ValueError("Only an existing Groove insert is supported")
    result["insert_dimensions_native"] = {}
    for field in ("Thickness", "Width", "length", "Radius1", "Radius2"):
        result["insert_dimensions_native"][field] = _number(read(turn, field))
    raw_holder = read(turn, "IGetTurnToolHolder")
    if raw_holder is None or not bool(raw_holder):
        raise ValueError("Selected own tool has no holder")
    holder = _typed(raw_holder, "ICWTurnToolHolder", typelib_path)
    result["holder_type_raw"] = _integer(read(holder, "GetHolderType"))
    if result["holder_type_raw"] != 1:
        raise ValueError("Only an existing TURN shank holder is supported")
    result["holder_id_raw"] = _integer(read(holder, "GetHolderId"))
    if result["holder_id_raw"] < 0:
        raise ValueError("Existing TURN shank holder ID must be nonnegative")
    result["orientation_for_operation_raw"] = _integer(read(holder, "GetToolOrientationForOperation", operation))
    result["insert_offsets_native"] = {}
    for field in ("XInsertOffset", "ZInsertOffset"):
        result["insert_offsets_native"][field] = _number(read(holder, field))
    result["holder_shape_raw"] = _integer(read(holder, "HolderShape"))
    result["holder_dimensions_native"] = {}
    for field in ("GetHolderThickness", "ShankLength", "ShankWidth", "Protrusion",
                  "LeadAngle", "BackClearAngle", "FrontClearAngle"):
        result["holder_dimensions_native"][field] = _number(read(holder, field))
    for label,owner,method,args in (("insert_profile",tool,"GetToolProfile",()),
                                  ("holder_profile",holder,"GetHolderProfile",(operation,))):
        profile = dict(source_method=method)
        result[label] = profile
        raw_chain = read(owner, method, *args)
        _segment_profile(raw_chain, typelib_path, read, profile)
        if not profile.get("available") or not profile.get("parameters_complete"):
            raise ValueError("Complete bounded line/arc contour required: " + label)
    result["complete"] = True


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _allowances(raw):
    """Installed TLB: four VARIANT OUT parameters plus BOOL retval; no shape guessing."""
    if not isinstance(raw,(tuple,list)) or len(raw)!=5 or type(raw[4]) is not bool:
        raise ValueError('GetAllVariableAllowances requires four OUT values and Boolean return')
    names,x,z,count,success=raw
    if not success: raise ValueError('GetAllVariableAllowances native returned false; OUT values not interpreted')
    if type(count) is not int or not 0<=count<=512: raise ValueError('Native segment count must be integer 0..512')
    if any(not isinstance(a,(tuple,list)) or len(a)!=count for a in (names,x,z)):
        raise ValueError('Native names/X/Z arrays must all match exact segment count')
    if any(type(n) is not str or not n.strip() or len(n)>1000 or any(c in n for c in '\x00\r\n') for n in names):
        raise ValueError('Exact bounded nonempty native names required')
    if len(set(names))!=count: raise ValueError('Native segment names must be unique')
    for value in (*x,*z):
        if type(value) not in (int,float) or not math.isfinite(value): raise ValueError('Allowances must be finite native numbers, not Boolean')
    return {'native_success':True,'segment_count':count,
            'entries':[{'name':n,'radial_x_native':float(a),'axial_z_native':float(b)} for n,a,b in zip(names,x,z)],
            'native_variant_metadata_preserved':False,
            'converted_arrays_type_checked':True,
            'units_verified':False,'radius_vs_diameter_scaling_verified':False,
            'name_to_profile_segment_mapping':'unqualified_do_not_infer_from_array_order'}


def _snapshot(sw,clsid,typelib_path,config,read,check,identity,diagnostic=None):
    result={} if diagnostic is None else diagnostic
    result['capture_complete']=False
    check(); current_doc=identity()
    result.update(document=current_doc,saved_file_sha256=config['expected_source_sha256'])
    _,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
    if config['action']=='read':
        result['inventory']=_inventory(machine,typelib_path,read)
        if config.get('inspection_scope')=='turn_setup_context':
            from scripts.sw_cam_turn_setup_context import verify_counts
            verify_counts(result['inventory'],config['setup_context_config'])
    setups=_items(read(machine,'IGetEnumOpSetups'),typelib_path,read)
    si=config['setup_index']; oi=config['operation_index']
    if si>=len(setups): raise ValueError('Selected setup absent')
    setup=_typed(setups[si],'ICWBaseOpSetup',typelib_path)
    operations=_items(read(setup,'IGetEnumOperations'),typelib_path,read)
    if oi>=len(operations): raise ValueError('Selected operation absent')
    raw=operations[oi]; operation=_typed(raw,'ICWOperation',typelib_path)
    turn=_typed(raw,'ICWTurnOperation',typelib_path)
    native_id=_object_id(doc,operation,read)
    if config['expected_operation_native_id'] is not None and native_id!=config['expected_operation_native_id']:
        raise ValueError('Exact native operation ID mismatch')
    kind=_integer(read(turn,'OpernType'))
    if kind!=config['expected_operation_type']: raise ValueError('Exact TURN operation type mismatch')
    suppressed=read(operation,'Suppressed')
    if type(suppressed) is not bool: raise ValueError('Operation suppression state is not Boolean')
    linked=_items(read(operation,'IGetAllFeatures'),typelib_path,read,limit=64)
    ids=[]; profiles=[]; budget=[0]
    result['selected_operation']={'setup_index':si,'operation_index':oi,'native_id':native_id,
        'turn_operation_type':kind,'suppressed':suppressed,'linked_feature_ids':ids}
    result['linked_features']=profiles
    for value in linked:
        fid=_object_id(doc,value,read)
        if fid in ids: raise ValueError('Duplicate linked feature ID')
        ids.append(fid)
    if config['action']=='identify':
        # 身份发现仅使用已有对象的正原生 ID；不进入轮廓、模式或余量链。
        check()
        if identity()!=current_doc: raise ValueError('Document or saved file changed during capture')
        result['capture_complete']=True
        return result
    if not ids or sorted(ids)!=config['expected_linked_feature_ids']:
        raise ValueError('Exact linked feature IDs changed')
    if config.get('inspection_scope')=='turn_setup_context':
        from scripts.sw_cam_turn_setup_context import read_setup_context
        result['setup_context']={}
        read_setup_context(doc,machine,setups,si,typelib_path,config['setup_context_config'],
            result['selected_operation'],read,check,result['setup_context'])
        check()
        if identity()!=current_doc or _inventory(machine,typelib_path,read)!=result['inventory']:
            raise ValueError('Document, saved file or complete inventory changed during setup read')
        result['capture_complete']=True
        return result
    if config.get('inspection_scope') in ('bore_rough_options', 'tool_contours'):
        if config['inspection_scope'] == 'bore_rough_options':
            result['bore_options_native'] = {}
            if config.get("include_leftover_control"):
                _read_bore_options(raw,typelib_path,read,result['bore_options_native'],include_leftover_control=True)
            else:
                _read_bore_options(raw,typelib_path,read,result['bore_options_native'])
        if config.get('include_tool_contours'):
            result['tool_contours'] = {}
            reader = _read_cutoff_tool_contours if kind == 13 else _read_bore_tool_contours
            reader(doc,operation,typelib_path,config['expected_tool_native_id'],read,result['tool_contours'])
        check()
        if identity()!=current_doc or _inventory(machine,typelib_path,read)!=result['inventory']:
            raise ValueError('Document, saved file or complete inventory changed during bore read')
        result['capture_complete']=True
        return result
    if config.get("inspection_scope") == "cutoff_options":
        from scripts.sw_cam_turn_cutoff_options import _read_cutoff_options
        result["cutoff_options_native"] = {}
        _read_cutoff_options(raw,typelib_path,read,result["cutoff_options_native"])
        check()
        if identity()!=current_doc or _inventory(machine,typelib_path,read)!=result["inventory"]:
            raise ValueError("Document, saved file or complete inventory changed during CutOff read")
        result["capture_complete"] = True
        return result
    for fid,value in zip(ids,linked):
        profile={}
        profiles.append({'native_id':fid,'profile':profile})
        _read_profile(value,typelib_path,read,budget,profile,
                      collection_reader=lambda v,limit:_items(v,typelib_path,read,limit=limit))
    if any(not p['profile'].get('segment_count') or any(not seg.get('curve_parameters_available')
           for seg in p['profile'].get('segments',[])) for p in profiles):
        raise ValueError('Complete line/arc profile geometry is required for this qualification')
    mode=read(_typed(raw,_MODE_INTERFACES[kind],typelib_path),'GetAllowanceMethodVariable')
    if type(mode) is not int or not -(2**31)<=mode<2**31: raise ValueError('Variable mode must be exact native LONG')
    result.update(variable_mode_native=mode,variable_mode_meaning_qualified=False)
    allowance=_allowances(read(turn,'GetAllVariableAllowances'))
    result['allowances']=allowance
    check()
    if identity()!=current_doc: raise ValueError('Document or saved file changed during capture')
    result['capture_complete']=True
    return result


def _inspect_turn_operation_parameters(sw,clsid,typelib_path,*,process_id,expected_document_path,
        setup_index,operation_index,expected_operation_type,expected_source_sha256,
        expected_operation_native_id=None,expected_linked_feature_ids=None,
        action='read',message_policy='vendor_default',inspection_scope='profile_and_variable_allowance',
        expected_process_create_time=None,include_tool_contours=False,expected_tool_native_id=None,
        setup_context_config=None,include_leftover_control=False):
    """Exact current saved part (may contain unchanged unsaved RAM data), one operation.

    Bootstrap obtains add-in/app only so events can be subscribed. All subsequent
    CAM getters, Count and Item calls, including both snapshots, run under active
    CamMessageSession. After disconnect only SW identity and saved file hash read.
    """
    report={'action':action,'inspection_scope':'identity_only' if action=='identify' else inspection_scope,
            'status':'error','phase':'validation','may_continue':False,'mutation_attempted':False,
            'GOP_attempted':False,'GTP_attempted':False,'model_saved':False,'tool_readers_used':False,
            'CL_read_attempted':False,'units_verified':False,'radius_vs_diameter_scaling_verified':False,
            'persistence_verified':False,'name_to_geometry_mapping_verified':False,
            'full_cam_snapshot_scope':'before_event_disconnect','post_cleanup_cam_read_performed':False,
            'bootstrap_scope':'GetAddInObject/GetCWApp only; required before message subscription'}
    session=None
    try:
        for name,value,lo,hi in [('process_id',process_id,1,2**32-1),('setup_index',setup_index,0,511),
               ('operation_index',operation_index,0,511)]:
            if type(value) is not int or not lo<=value<=hi: raise ValueError('Invalid strict selector '+name)
        if action not in ('read','identify'): raise ValueError('Only read or identify action allowed')
        if inspection_scope not in ('profile_and_variable_allowance','bore_rough_options','tool_contours','turn_setup_context','cutoff_options'):
            raise ValueError('Unknown operation parameter inspection scope')
        if inspection_scope=='turn_setup_context':
            from scripts.sw_cam_turn_setup_context import validate_config, setup_abi
            setup_context_config=validate_config(setup_context_config)
            report['setup_getter_abi']=setup_abi(typelib_path)
        elif setup_context_config is not None:
            raise ValueError('Setup context pins only belong to the dedicated setup scope')
        if type(include_leftover_control) is not bool:
            raise ValueError('include_leftover_control must be a strict Boolean')
        if include_leftover_control and inspection_scope != 'bore_rough_options':
            raise ValueError('Leftover control only belongs to bore rough options')
        if type(include_tool_contours) is not bool:
            raise ValueError('include_tool_contours must be a strict Boolean')
        if include_tool_contours:
            if inspection_scope not in ('bore_rough_options','tool_contours') or type(expected_tool_native_id) is not int or not 1<=expected_tool_native_id<2**32:
                raise ValueError('Tool contours require bore scope and an exact native tool ID')
        elif expected_tool_native_id is not None:
            raise ValueError('An expected tool ID is only valid when contours are requested')
        if inspection_scope=='tool_contours' and not include_tool_contours:
            raise ValueError('Tool contour scope requires both contours and an exact tool ID')
        if inspection_scope in ('bore_rough_options','tool_contours','turn_setup_context','cutoff_options'):
            if action!='read' or type(expected_process_create_time) not in (int,float) or not math.isfinite(expected_process_create_time) or expected_process_create_time<=0:
                raise ValueError('Bore options require read-only action and exact process lifetime')
        elif expected_process_create_time is not None:
            raise ValueError('Legacy allowance scope does not accept process lifetime extension')
        if expected_operation_native_id is not None and (type(expected_operation_native_id) is not int or not 1<=expected_operation_native_id<2**32):
            raise ValueError('Invalid strict selector expected_operation_native_id')
        if action=='read' and expected_operation_native_id is None:
            raise ValueError('Allowance read requires exact expected operation native ID')
        if action=='identify' and expected_linked_feature_ids is not None:
            raise ValueError('Identify discovers linked IDs; expected linked IDs belong to strict read only')
        allowed_types=((13,) if inspection_scope=='cutoff_options' else
                       (5,) if inspection_scope=='bore_rough_options' else
                       (5,6,13) if inspection_scope=='tool_contours' else
                       (5,6) if inspection_scope=='turn_setup_context' else _MODE_INTERFACES)
        if type(expected_operation_type) is not int or expected_operation_type not in allowed_types:
            raise ValueError('Exact operation type does not match the parameter inspection scope')
        if type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold()!='.sldprt':
            raise ValueError('Exact absolute saved part path required')
        if type(expected_source_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_source_sha256):
            raise ValueError('Exact saved source SHA required')
        if action=='read' and (not isinstance(expected_linked_feature_ids,list) or not 1<=len(expected_linked_feature_ids)<=64
                or any(type(i) is not int or not 1<=i<2**32 for i in expected_linked_feature_ids)
                or len(set(expected_linked_feature_ids))!=len(expected_linked_feature_ids)):
            raise ValueError('Unique exact linked feature IDs required')
        if message_policy!='vendor_default': raise ValueError('Only vendor_default message policy allowed')
        config=dict(action=action,setup_index=setup_index,operation_index=operation_index,
             expected_operation_native_id=expected_operation_native_id,expected_operation_type=expected_operation_type,
             expected_linked_feature_ids=sorted(expected_linked_feature_ids) if expected_linked_feature_ids is not None else None,
             expected_source_sha256=expected_source_sha256)
        if inspection_scope=='turn_setup_context':
            config.update(inspection_scope=inspection_scope,setup_context_config=setup_context_config)
            report.update(setup_context_requested=True,coordinate_frame_verified=False,
                full_model_geometry_verified=False,production_qualified=False,
                parameter_interpretation='Raw setup links, axes, origin and transform type metadata; no decoded matrix or generic CL frame',
                process_identity=dict(process_id=process_id,expected_process_create_time=expected_process_create_time))
        if inspection_scope in ('bore_rough_options','tool_contours'):
            config['inspection_scope']=inspection_scope
            if inspection_scope=='bore_rough_options':
                if include_leftover_control:
                    config['include_leftover_control'] = True
                    report['leftover_control_requested'] = True
                    report['leftover_enum_mapping_scope'] = 'Declared TLB enum only; no UI-mode correspondence inferred'
                    report['getter_abi']=_bore_options_abi(typelib_path,include_leftover_control=True)
                else:
                    report['getter_abi']=_bore_options_abi(typelib_path)
            if include_tool_contours:
                config.update(include_tool_contours=True,expected_tool_native_id=expected_tool_native_id)
                report['tool_contour_abi'] = _tool_contour_abi(typelib_path)
                report.update(tool_contours_requested=True,
                    program_point_verified=False,coordinate_frame_verified=False,
                    contour_scope=('Selected own Groove insert and operation-specific shank holder; 32 chains/512 curves per contour'
                        if expected_operation_type == 13 else
                        'Selected own diamond insert and operation-specific boring holder; 32 chains/512 curves per contour'))
            report.update(full_model_geometry_verified=False,all_nc_parameters_verified=False,
                tool_geometry_verified=False,production_qualified=False,
                parameter_interpretation='Raw current Boolean/double/LONG values; no undercut, tool access or physical cutting qualification',
                process_identity=dict(process_id=process_id,expected_process_create_time=expected_process_create_time))
            if inspection_scope=='tool_contours':
                report['parameter_interpretation']='Raw selected own-tool contours and dimensions only; no operation options or feature profiles read'
        if inspection_scope == "cutoff_options":
            from scripts.sw_cam_turn_cutoff_options import _cutoff_options_abi
            config["inspection_scope"] = inspection_scope
            report["getter_abi"] = _cutoff_options_abi(typelib_path)
            report.update(full_model_geometry_verified=False,all_nc_parameters_verified=False,
                tool_geometry_verified=False,production_qualified=False,
                parameter_interpretation="Declared ICWTurnCutOffOp scalar values only; no final diameter, feature extension or machining-side mapping inferred",
                unavailable_requested_parameters=["final_diameter","feature_start_end_extension_lengths","machining_side"],
                process_identity=dict(process_id=process_id,expected_process_create_time=expected_process_create_time))
        def identity():
            if expected_process_create_time is not None:
                process=_process_identity(process_id)
                if (process.get('alive') is not True or process.get('process_id')!=process_id
                        or process.get('create_time')!=expected_process_create_time
                        or Path(process.get('executable','')).name.casefold()!='sldworks.exe'):
                    raise ValueError('Exact SOLIDWORKS process lifetime changed')
            if _integer(_member(sw,'GetProcessID'))!=process_id: raise ValueError('Exact PID mismatch')
            state=document_snapshot(sw)
            if state is None or state['type']!=1 or not state['path']: raise ValueError('Saved part required')
            check_document_target(state['path'],state['title'],expected_path=expected_document_path,required=True)
            if _file_hash(state['path'])!=expected_source_sha256: raise ValueError('Saved source SHA changed')
            return state
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial_doc=identity(); report['unsaved_memory_present']=initial_doc['needs_save']
            addin=_member(sw,'GetAddInObject',clsid)
            if addin is None: raise ValueError('CAM add-in must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
            session=CamMessageSession(app,typelib_path)
            def check():
                state=session.summary(); report['messages']=state
                if not state.get('active') or not state.get('subscribed') or any(state.get(k) for k in
                      ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                    raise ValueError('CAM event transport requires review; no further CAM getters')
            def read(obj,name,*args):
                report['phase']=name; check()
                if name == 'IGetTool': report['tool_readers_used'] = True
                value=_member(obj,name,*args); check(); return value
            with session:
                report['before']={}
                before=_snapshot(sw,clsid,typelib_path,config,read,check,identity,report['before'])
                report['state_sha256']=_digest(before)
                report['after']={}
                after=_snapshot(sw,clsid,typelib_path,config,read,check,identity,report['after'])
                if before!=after or before['document']!=initial_doc: raise ValueError('Operation/profile/allowance/document changed during read')
                check()
            summary=session.summary(); report['messages']=summary
            if summary.get('disconnected') is not True or summary.get('active') or any(summary.get(k) for k in
                  ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                raise ValueError('CAM event cleanup not cleanly confirmed')
            if identity()!=initial_doc: raise ValueError('SW document changed after event cleanup')
            report.update(status='ok',phase='finished',readback_verified=True,post_cleanup_document_file_verified=True,
                          interpretation=('Current document-scoped IDs only; no profiles, tools, mode or allowances read' if action=='identify'
                            else 'Raw operation-owned values only; no safe parameter write or units/mode mapping claimed'))
    except Exception as error:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(error),readback_verified=False)
    finally:
        if session is not None: report['messages']=session.summary()
    return report


def inspect_turn_variable_allowance(sw,clsid,typelib_path,*,process_id,expected_document_path,
        setup_index,operation_index,expected_operation_type,expected_source_sha256,
        expected_operation_native_id=None,expected_linked_feature_ids=None,
        action='read',message_policy='vendor_default'):
    """Existing OD allowance interface; its inputs and read/identify scopes are unchanged."""
    return _inspect_turn_operation_parameters(sw,clsid,typelib_path,process_id=process_id,
        expected_document_path=expected_document_path,setup_index=setup_index,operation_index=operation_index,
        expected_operation_type=expected_operation_type,expected_source_sha256=expected_source_sha256,
        expected_operation_native_id=expected_operation_native_id,expected_linked_feature_ids=expected_linked_feature_ids,
        action=action,message_policy=message_policy)


def inspect_turn_bore_options(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,setup_index,operation_index,
        expected_operation_native_id,expected_operation_type,expected_linked_feature_ids,
        action='read',message_policy='vendor_default',include_tool_contours=False,expected_tool_native_id=None,
        include_leftover_control=False):
    """Read bore scalars and optional exact own-tool contours twice under the same guards."""
    return _inspect_turn_operation_parameters(sw,clsid,typelib_path,process_id=process_id,
        expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,setup_index=setup_index,operation_index=operation_index,
        expected_operation_native_id=expected_operation_native_id,expected_operation_type=expected_operation_type,
        expected_linked_feature_ids=expected_linked_feature_ids,action=action,message_policy=message_policy,
        inspection_scope='bore_rough_options',include_tool_contours=include_tool_contours,
        expected_tool_native_id=expected_tool_native_id,include_leftover_control=include_leftover_control)


def inspect_turn_tool_contours(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,setup_index,operation_index,
        expected_operation_native_id,expected_operation_type,expected_linked_feature_ids,
        expected_tool_native_id,action='read',message_policy='vendor_default'):
    """两次读取已有镗削或 CutOff 操作的自有刀片和夹持器轮廓。"""
    return _inspect_turn_operation_parameters(sw,clsid,typelib_path,process_id=process_id,
        expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,setup_index=setup_index,operation_index=operation_index,
        expected_operation_native_id=expected_operation_native_id,expected_operation_type=expected_operation_type,
        expected_linked_feature_ids=expected_linked_feature_ids,action=action,message_policy=message_policy,
        inspection_scope='tool_contours',include_tool_contours=True,expected_tool_native_id=expected_tool_native_id)
