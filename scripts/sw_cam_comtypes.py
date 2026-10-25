"""Typed CAM vtable interfaces bridged from the already PID-bound COM object.

Only standard COM marshaling is used; no ROT lookup, server activation, pointer
address extraction, file-backed OBJREF or late-bound IDispatch invocation.
The caller remains responsible for selecting and verifying its SOLIDWORKS PID.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_LIBID = "{FE488661-0BD8-11D6-2012-2018CE99E55F}"
_INTERFACES = {
    "ICWApp": "{6015E884-0B0D-11D6-A982-00062999E55F}",
    "ICWEventGenerator": "{02D82A41-3BF6-11D6-A9B0-00062999E55F}",
    "_IDialogEvents": "{7532C711-3BC4-11D6-A9AF-00062999E55F}",
    "ICWTurnOperation": "{4EDDCA75-325A-11D6-A9A7-00062999E55F}",
    "ICWTurnWorkpiece": "{BC1C864D-A0FE-4FEC-A008-99CB97EC993D}",
    "ICWDoc": "{43FFF506-0F02-11D6-A985-00062999E55F}",
    "ICWDoc3": "{EF023226-D383-42DA-84FC-FC9243897FA7}",
    "ICWPartDoc": "{CFE63007-1934-11D6-A990-00062999E55F}",
    "ICWMachine": "{FB4CC0D1-2AA4-11D6-A99F-00062999E55F}",
    "ICWMachine5": "{3767818E-318E-4F18-BBD2-572DB04B45F0}",
    "ICWDispatchCollection": "{670DD771-2C33-11D6-A9A1-00062999E55F}",
    "ICWObject": "{A417C671-34BD-11D6-A9A8-00062999E55F}",
    "ICWApp3": "{40CA99D8-2F65-4AA2-93E0-1762DD31FAAD}",
    "ICWApp4": "{9AC68D6D-746D-42D5-90F0-47628261BAD9}",
    "ICWBaseSetup": "{FB4CC0DA-2AA4-11D6-A99F-00062999E55F}",
    "ICWBaseOpSetup": "{FB4CC0E1-2AA4-11D6-A99F-00062999E55F}",
    "ICWOperation": "{4EDDCA73-325A-11D6-A9A7-00062999E55F}",
    "ICWToolpath": "{69265252-35B8-11D6-A9A9-00062999E55F}",
    "ICWTool": "{7532C760-3BC4-11D6-A9AF-00062999E55F}",
    "ICWTurnTool": "{C1742CB3-FAC3-4613-9967-C9E9C871E299}",
    "ICWFeature": "{682686E4-3685-11D6-A9AA-00062999E55F}",
    "ICWTurnFeature": "{DF79BF0A-F181-4610-A92B-E7AE3CC5BE6E}",
    "ICWTurnSegment": "{7949965C-9304-4D3B-B6B0-258DD52C88AD}",
    "ICWPosition": "{E7807F27-04D2-48A3-91AF-6DB704DBCC9C}",
    "ICWTurnToolHolder": "{47334698-4948-457C-A580-B5E12E33ED9A}",
    "ICWToolStation": "{5A962777-E77D-48A9-8805-5F3CC3085A68}",
}
_MAX_MARSHAL_BYTES = 1024 * 1024


@lru_cache(maxsize=4)
def _load_type_library(typelib_path: str):
    """Read and generate exact 2026 declarations, without registration or activation."""
    import comtypes.client
    from comtypes import typeinfo

    path = Path(typelib_path)
    if not path.is_absolute() or path.suffix.casefold() != ".tlb" or not path.is_file():
        raise ValueError("An existing absolute CAM type-library path is required")
    library = typeinfo.LoadTypeLibEx(str(path), typeinfo.REGKIND_NONE)
    attr = library.GetLibAttr()
    if str(attr.guid).upper() != _LIBID or (attr.wMajorVerNum, attr.wMinorVerNum) != (25, 0):
        raise ValueError("Only the verified SOLIDWORKS CAM 2026 type library is supported")
    if library.GetDocumentation(-1)[1] != "SOLIDWORKS CAM 2026 Type Library":
        raise ValueError("Unexpected CAM type-library description")
    return comtypes.client.GetModule(library)


def _interface_class(interface_name: str, typelib_path: str):
    if interface_name not in _INTERFACES:
        raise ValueError("Unsupported CAM interface")
    module = _load_type_library(str(typelib_path))
    interface = getattr(module, interface_name)
    if str(interface._iid_).upper() != _INTERFACES[interface_name]:
        raise ValueError("CAM generated interface does not match the verified IID")
    return interface


def _is_comtypes_pointer(obj) -> bool:
    from comtypes import IUnknown
    # comtypes pointer classes inherit their interface and IUnknown, then
    # ctypes.c_void_p. Their _type_ is the scalar code "P", not an interface.
    return isinstance(obj, IUnknown)


@lru_cache(maxsize=1)
def _stream_interface():
    from ctypes import HRESULT, POINTER, c_longlong, c_ulong, c_ulonglong
    from comtypes import COMMETHOD, GUID
    from comtypes.stream import ISequentialStream

    class IStreamPrefix(ISequentialStream):
        # Standard IStream IID and its first added method. The remaining standard
        # methods are never invoked; no private vtable offsets are constructed.
        _iid_ = GUID("{0000000C-0000-0000-C000-000000000046}")
        _methods_ = [COMMETHOD([], HRESULT, "Seek",
                              (["in"], c_longlong, "offset"),
                              (["in"], c_ulong, "origin"),
                              (["out"], POINTER(c_ulonglong), "position"))]
    return IStreamPrefix


def _unmarshal_unknown(payload: bytes):
    """Consume only the fresh trusted OBJREF created by this module in memory."""
    from ctypes import HRESULT, OleDLL, POINTER, byref, c_int, c_ubyte, c_void_p
    from comtypes import GUID, IUnknown

    stream_type = _stream_interface()
    ole32 = OleDLL("ole32")
    create_stream = ole32.CreateStreamOnHGlobal
    create_stream.argtypes = [c_void_p, c_int, POINTER(POINTER(stream_type))]
    create_stream.restype = HRESULT
    stream = POINTER(stream_type)()
    create_stream(None, 1, byref(stream))  # Stream owns and releases the HGLOBAL.
    buffer = (c_ubyte * len(payload)).from_buffer_copy(payload)
    if stream.RemoteWrite(buffer, len(payload)) != len(payload):
        raise OSError("Incomplete in-memory COM stream write")
    stream.Seek(0, 0)
    unmarshal = ole32.CoUnmarshalInterface
    unmarshal.argtypes = [POINTER(stream_type), POINTER(GUID), POINTER(POINTER(IUnknown))]
    unmarshal.restype = HRESULT
    unknown = POINTER(IUnknown)()
    unmarshal(stream, byref(IUnknown._iid_), byref(unknown))
    if not unknown:
        raise RuntimeError("COM unmarshaling returned a null interface")
    return unknown


class CamComBridgeError(RuntimeError):
    """Sanitized stage information only; never stores exception text or OBJREF."""
    def __init__(self, code, stage, exc, *, source=None, original=None):
        self.code = code
        self.bridge_stage = stage
        self.error_type = type(exc).__name__
        self.hresult = getattr(exc, "hresult", None)
        self.source_type = type(source).__name__ if source is not None else None
        self.input_type = type(original).__name__ if original is not None else None
        super().__init__(f"{code} at {stage} ({self.error_type})")


def _unwrap_pywin32_object(obj):
    """Unwrap stored pywin32 coclass/dispatch fields without COM property lookup.

    Installed win32com.client.CoClassBaseClass stores `_dispobj_`; its generated
    DispatchBaseClass stores `_oleobj_`. Neither step queries an application.
    """
    current = obj
    seen = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            raise ValueError("Null or cyclic pywin32 wrapper")
        seen.add(id(current))
        try:
            data = object.__getattribute__(current, "__dict__")
        except AttributeError:
            return current
        if "_oleobj_" in data:
            current = data["_oleobj_"]
        elif "_dispobj_" in data:
            current = data["_dispobj_"]
        else:
            return current
    raise ValueError("Excessively nested pywin32 wrapper")


def _marshal_pywin32_unknown(obj):
    """Transfer one existing object; NORMAL marshal is consumed exactly once."""
    import pythoncom

    try:
        source = _unwrap_pywin32_object(obj)
    except Exception as exc:
        raise CamComBridgeError("CAM_COM_SOURCE_INVALID", "source_unwrap", exc,
                                original=obj) from None
    try:
        stream = pythoncom.CreateStreamOnHGlobal()
    except Exception as exc:
        raise CamComBridgeError("CAM_COM_STREAM_CREATE_FAILED", "stream_create", exc,
                                source=source, original=obj) from None
    try:
        # pywin32 312 PythonCOM.cpp: (stream, iid, object, dest_context, flags).
        pythoncom.CoMarshalInterface(stream, pythoncom.IID_IUnknown, source,
                                    pythoncom.MSHCTX_INPROC, pythoncom.MSHLFLAGS_NORMAL)
    except Exception as exc:
        raise CamComBridgeError("CAM_COM_MARSHAL_FAILED", "marshal", exc,
                                source=source, original=obj) from None
    consumed = False
    stage = "stream_read"
    try:
        size = int(stream.Seek(0, 2))
        if not 0 < size <= _MAX_MARSHAL_BYTES:
            raise ValueError("Unexpected COM marshal stream length")
        stream.Seek(0, 0)
        payload = stream.Read(size)
        if len(payload) != size:
            raise OSError("Incomplete COM marshal stream read")
        stage = "unmarshal"
        result = _unmarshal_unknown(payload)
        consumed = True
        return result
    except Exception as exc:
        raise CamComBridgeError("CAM_COM_" + stage.upper() + "_FAILED", stage, exc,
                                source=source, original=obj) from None
    finally:
        if not consumed:
            try:
                stream.Seek(0, 0)
                pythoncom.CoReleaseMarshalData(stream)
            except Exception:
                pass


def query_cam_interface(obj, interface_name: str, typelib_path: str):
    """Return a true typed dual-vtable pointer for the supplied existing object.

    Accepts a pywin32 wrapper/raw interface or a typed comtypes pointer returned
    by a previous native getter. Does not discover or create application objects.
    """
    if obj is None:
        raise ValueError("Cannot query a null CAM object")
    interface = _interface_class(interface_name, typelib_path)
    if _is_comtypes_pointer(obj):
        if not obj:
            raise ValueError("Cannot query a null typed CAM interface")
        unknown = obj
    else:
        unknown = _marshal_pywin32_unknown(obj)
    # This is comtypes' native IUnknown::QueryInterface followed by generated
    # COMMETHOD vtable calls, not win32com.Dispatch / IDispatch.Invoke.
    try:
        return unknown.QueryInterface(interface)
    except Exception as exc:
        raise CamComBridgeError("CAM_COM_NATIVE_QI_FAILED", "native_query_interface", exc,
                                source=unknown, original=obj) from None
