"""Exact SOLIDWORKS CAM 2026 FACE interfaces on existing native COM objects.

This extension uses the reviewed generated declarations and real QueryInterface.
It does not alter the shared interface allowlist, activate a COM server, marshal
arbitrary pointers, invoke IDispatch by name, or fabricate interface addresses.
"""
from pathlib import Path
import sys
from scripts.sw_cam_comtypes import (_load_type_library,_interface_class,_INTERFACES,
    _is_comtypes_pointer,CamComBridgeError)
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_rough_firstcut import require

FACE_IIDS={
 'ICWFaceMillOp':'{D86E87F2-8432-4F2C-AD6E-67208E62B5CD}',
 'ICWNCParam2':'{7B7640FD-F53E-4B98-A073-EB4E6992E802}',
}


def _key(value):return str(Path(value).resolve()).casefold()


def _verify_generated_class(interface,expected_iid,generated_pin):
    from comtypes.automation import IDispatch
    require(type(generated_pin) is dict and type(generated_pin.get('path')) is str
      and type(generated_pin.get('sha256')) is str,'Pinned generated interface declaration required')
    declared=sys.modules.get(interface.__module__)
    require(declared is not None and _key(declared.__file__)==_key(generated_pin['path'])
      and _file_hash(generated_pin['path'])==generated_pin['sha256'],'Exact generated declaration file/hash required')
    require(str(interface._iid_).upper()==expected_iid and issubclass(interface,IDispatch)
      and 'dual' in interface._idlflags_ and 'oleautomation' in interface._idlflags_,'Exact documented dual interface IID required')
    return interface


def face_interface_class(name,typelib_path,*,generated_pin):
    require(type(name) is str and name in FACE_IIDS,'Only two reviewed FACE interfaces are supported')
    # Shared loader already checks LIBID,25.0,description and REGKIND_NONE.
    module=_load_type_library(str(typelib_path))
    interface=getattr(module,name)
    return _verify_generated_class(interface,FACE_IIDS[name],generated_pin)


def query_face_interface(obj,name,typelib_path,*,generated_pin):
    require(_is_comtypes_pointer(obj) and bool(obj),'Existing non-null native comtypes interface required')
    interface=face_interface_class(name,typelib_path,generated_pin=generated_pin)
    try:result=obj.QueryInterface(interface)
    except Exception as exc:
        raise CamComBridgeError('CAM_FACE_NATIVE_QI_FAILED','native_query_interface',exc,source=obj,original=obj) from None
    require(_is_comtypes_pointer(result) and bool(result) and isinstance(result,interface),'QueryInterface returned no exact native interface')
    return result


def audit_interfaces(names,typelib_path,*,generated_pin):
    """Offline installed-TLB resolution. No application connection or native QI."""
    require(type(names) in (tuple,list,set,frozenset) and 1<=len(names)<=32 and len(set(names))==len(names),'Bounded unique interface names required')
    rows=[]
    for name in sorted(names):
        require(type(name) is str,'Exact interface name required')
        if name in FACE_IIDS:
            interface=face_interface_class(name,typelib_path,generated_pin=generated_pin);iid=FACE_IIDS[name];route='face_extension'
        else:
            require(name in _INTERFACES,'Observer interface is not supported by either typed adapter')
            interface=_interface_class(name,str(typelib_path));iid=_INTERFACES[name];route='shared_verified_adapter'
            _verify_generated_class(interface,iid,generated_pin)
        rows.append(dict(name=name,iid=str(interface._iid_).upper(),resolution=route))
    return dict(scope='OFFLINE_CAM_FACE_INTERFACE_COMPATIBILITY_V1',type_library_path=str(Path(typelib_path).resolve()),
      generated_pin=dict(generated_pin),interfaces=rows,all_resolved=True,application_connections=0,native_query_interface_calls=0,
      native_getters_called=0,interface_runtime_support_qualified=False)
