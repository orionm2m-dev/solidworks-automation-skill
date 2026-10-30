"""Exact typed tapered-tool extension; no application discovery or activation.

The class and its required property signatures are checked before connecting.
Runtime QI accepts only an existing native object; the caller owns its guard.
The common interface registry is never changed.
"""
from pathlib import Path
from scripts.sw_cam_comtypes import _load_type_library, _is_comtypes_pointer, CamComBridgeError
from scripts.sw_cam_face_interfaces import _verify_generated_class
from scripts.sw_cam_rough_firstcut import require

TAPER_IID = '{7532C756-3BC4-11D6-A9AF-00062999E55F}'
PROPERTIES = {
    'TaperToolType': (1, 'int', True),
    'EndDia': (2, 'double', True),
    'EndRadius': (3, 'double', True),
    'ShankDia': (4, 'double', True),
    'TaperAngle': (5, 'double', True),
    'TaperLength': (6, 'double', True),
    'OverallLength': (7, 'double', True),
    'ShoulderLength': (8, 'double', True),
    'NoOfFlutes': (9, 'int', True),
    'MillToolShankType': (12, 'int', True),
    'ShoulderDia': (13, 'double', True),
    'ShankLength': (14, 'double', True),
    'MaxDia': (15, 'double', False),
}


def _verify_property_signatures(interface):
    from ctypes import HRESULT, POINTER, c_int, c_double
    methods = getattr(interface, '_methods_', ())
    rows = []
    for name, (dispid, kind, writable) in PROPERTIES.items():
        value_type = c_int if kind == 'int' else c_double
        descriptor = vars(interface).get(name)
        require(isinstance(descriptor, property) and descriptor.fget is not None
                and (descriptor.fset is not None) is writable,
                'Exact generated property access required: ' + name)
        for access, prefix, arg_type, direction in (
                ('propget', '_get_', POINTER(value_type), 10),
                ('propput', '_set_', value_type, 1)):
            matching = [v for v in methods if v.name == prefix + name]
            if access == 'propput' and not writable:
                require(not matching, 'Calculated property must remain read-only: ' + name)
                continue
            require(len(matching) == 1, 'Unique generated property method required: ' + name)
            method = matching[0]
            require(method.restype is HRESULT and tuple(method.argtypes) == (arg_type,)
                    and tuple(method.paramflags) == ((direction, 'pVal'),)
                    and method.idlflags[0] == dispid and isinstance(method.idlflags[0], int)
                    and type(method.idlflags[0]) is not bool
                    and access in method.idlflags,
                    'Exact generated property signature required: ' + name)
        rows.append(dict(name=name, dispid=dispid, value_type=kind,
                         getter=True, setter=writable, result_type='HRESULT'))
    return rows


def taper_interface_class(name, typelib_path, *, generated_pin):
    require(type(name) is str and name == 'ICWTaperTool', 'Only the reviewed tapered-tool interface is supported')
    module = _load_type_library(str(typelib_path))
    interface = getattr(module, name)
    _verify_generated_class(interface, TAPER_IID, generated_pin)
    _verify_property_signatures(interface)
    return interface


def query_taper_interface(obj, name, typelib_path, *, generated_pin):
    require(_is_comtypes_pointer(obj) and bool(obj), 'Existing non-null native comtypes interface required')
    interface = taper_interface_class(name, typelib_path, generated_pin=generated_pin)
    try:
        result = obj.QueryInterface(interface)
    except Exception as exc:
        raise CamComBridgeError('CAM_TAPER_NATIVE_QI_FAILED', 'native_query_interface', exc,
                               source=obj, original=obj) from None
    require(_is_comtypes_pointer(result) and bool(result) and isinstance(result, interface),
            'QueryInterface returned no exact native interface')
    return result


def audit_taper_interface(typelib_path, *, generated_pin):
    """Resolve declarations and property metadata without connecting or querying an app."""
    interface = taper_interface_class('ICWTaperTool', typelib_path, generated_pin=generated_pin)
    return dict(scope='OFFLINE_CAM_TAPER_INTERFACE_COMPATIBILITY_V1',
                type_library_path=str(Path(typelib_path).resolve()), generated_pin=dict(generated_pin),
                name='ICWTaperTool', iid=str(interface._iid_).upper(),
                properties=_verify_property_signatures(interface), all_resolved=True,
                property_signatures_verified=True, application_connections=0,
                native_query_interface_calls=0, native_getters_called=0, native_setters_called=0,
                interface_runtime_support_qualified=False)
