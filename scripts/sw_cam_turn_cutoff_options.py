"""Read declared ICWTurnCutOffOp scalars; no setters, profile extension guesses or tool reads."""
from __future__ import annotations
from scripts.sw_cam_comtypes import _interface_class
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_operation_profile import _number

_INTERFACE = "ICWTurnCutOffOp"
_IID = "{253B0F7E-2C2D-47CB-B422-2442F806D931}"
_FIELDS = (
    ("CutOff_GrvType",1,"long"), ("FirstPeckAmt",2,"double"),
    ("SubPeckAmt",3,"double"), ("MinPeckAmt",4,"double"),
    ("PercentPeckAmt",5,"double"), ("DepthClearance",6,"double"),
    ("CornerBreakType",7,"long"), ("CornerBreakChamferLength",8,"double"),
    ("CornerBreakChamferAngle",9,"double"), ("CornerBreakChamferExt",10,"double"),
    ("CornerBreakRadius",11,"double"), ("CornerBreakStepover",12,"double"),
    ("MirrorAboutCenterline",13,"bool"), ("GenerateLeftOver",14,"bool"),
    ("CNCCompMethod",15,"long"), ("ProgramPoint_GrooveTool_Shift",16,"long"),
    ("RadialStockAmt",17,"double"), ("AxialStockAmt",18,"double"),
)

def _cutoff_options_abi(typelib_path):
    """Validate installed declared IID and all requested zero-input property getters, no QI."""
    from ctypes import HRESULT, POINTER, c_int, c_double
    from ctypes.wintypes import VARIANT_BOOL
    interface = _interface_class(_INTERFACE,typelib_path)
    if str(interface._iid_).upper() != _IID:
        raise ValueError("Exact CutOff interface IID differs")
    types={"long":c_int,"double":c_double,"bool":VARIANT_BOOL}
    for name,dispid,kind in _FIELDS:
        methods=[m for m in interface._methods_ if m.name=="_get_"+name]
        if len(methods)!=1:
            raise ValueError("Unique exact CutOff getter required: "+name)
        m=methods[0]
        if (m.restype is not HRESULT or m.idlflags[0]!=dispid or "propget" not in m.idlflags
            or m.argtypes!=(POINTER(types[kind]),) or tuple(x[0] for x in m.paramflags)!=(10,)):
            raise ValueError("Exact CutOff getter ABI differs: "+name)
    return dict(interface=_INTERFACE,iid=_IID,getter_count=len(_FIELDS),native_calls=0)

def _read_cutoff_options(raw,typelib_path,read,result):
    interface=_typed(raw,_INTERFACE,typelib_path)
    for name,_dispid,kind in _FIELDS:
        value=read(interface,name)
        if kind=="bool":
            if type(value) is not bool:
                raise ValueError("CutOff option must be a strict Boolean: "+name)
        elif kind=="long":
            if type(value) is not int or not -(2**31)<=value<2**31:
                raise ValueError("CutOff option must be a native LONG: "+name)
        else:
            value=_number(value)
        result[name]=value

def inspect_turn_cutoff_options(sw,clsid,typelib_path,*,process_id,expected_process_create_time,
        expected_document_path,expected_source_sha256,setup_index,operation_index,
        expected_operation_native_id,expected_operation_type,expected_linked_feature_ids,
        action="read",message_policy="vendor_default"):
    """Read an existing exact type13 operation twice under the common PID/source/ID/event guards."""
    from scripts.sw_cam_turn_variable_allowance import _inspect_turn_operation_parameters
    return _inspect_turn_operation_parameters(sw,clsid,typelib_path,process_id=process_id,
        expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,setup_index=setup_index,operation_index=operation_index,
        expected_operation_native_id=expected_operation_native_id,expected_operation_type=expected_operation_type,
        expected_linked_feature_ids=expected_linked_feature_ids,action=action,message_policy=message_policy,
        inspection_scope="cutoff_options")
