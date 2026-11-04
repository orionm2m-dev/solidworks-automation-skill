from ctypes import HRESULT,POINTER,c_double
from ctypes.wintypes import VARIANT_BOOL
from comtypes.automation import IDispatch
from types import SimpleNamespace
import importlib
import pytest
from scripts import sw_cam_mill_operation_geometry as core
from scripts import sw_cam_comtypes as bridge


def classes():
    result={name:SimpleNamespace() for name in core.INTERFACES}
    def spec(name,disp,args,flags):return SimpleNamespace(name=name,idlflags=[disp],restype=HRESULT,argtypes=args,paramflags=tuple((v,'out') for v in flags))
    result['ICWMillOperation3']=SimpleNamespace(_iid_='{20DEC8D6-8B4F-4876-90CB-F2A8D87A9D78}',_methods_=[spec('GetTpBaseFeature',25,(POINTER(IDispatch),POINTER(POINTER(IDispatch))),(1,10))],**{core.RAW_BASE:lambda:None})
    result['ICWTpBaseFeature']=SimpleNamespace(_iid_='{87B34A84-9E8B-404B-ACC6-85456C7C8E2A}',_methods_=[spec('GetTpFeatParameters',1,(POINTER(c_double),)*3+(POINTER(VARIANT_BOOL),)+(POINTER(POINTER(IDispatch)),)*3,(2,)*7)],**{core.RAW_PARAMS:lambda:None})
    return result


def test_exact_portable_primary_contract(monkeypatch):
    declared=classes();monkeypatch.setattr(core,'_interface_class',lambda name,tlb:declared[name]);r=core.preflight('offline')
    assert r['native_calls']==0 and r['raw_owned_OUT_buffers'] and not r['automatic_interface_discovery']

@pytest.mark.parametrize('defect',['missing_registry','iid','dispid','direction','return','argcount','property','raw_missing'])
def test_metadata_failure_stops_before_any_native(monkeypatch,defect):
    declared=classes();target=declared['ICWTpBaseFeature'];method=target._methods_[0]
    if defect=='missing_registry':declared.pop('ICWToolpath')
    elif defect=='iid':target._iid_='wrong'
    elif defect=='dispid':method.idlflags[0]=2
    elif defect=='direction':method.paramflags=((10,'ret'),)*7
    elif defect=='return':method.restype=c_double
    elif defect=='argcount':method.argtypes=method.argtypes[:-1]
    elif defect=='property':method.idlflags.append('propget')
    else:setattr(target,core.RAW_PARAMS,None)
    monkeypatch.setattr(core,'_interface_class',lambda name,tlb:declared[name])
    with pytest.raises((ValueError,KeyError)):core.preflight('offline')


def test_real_installed_bridge_and_local_typelib_metadata_when_available(monkeypatch):
    try:module=importlib.import_module('comtypes.gen._FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0')
    except ImportError:pytest.skip('Optional local generated CAM type library is not installed')
    monkeypatch.setattr(bridge,'_load_type_library',lambda path:module)
    assert bridge._INTERFACES['ICWTpBaseFeature']=='{87B34A84-9E8B-404B-ACC6-85456C7C8E2A}'
    monkeypatch.setattr(core,'_interface_class',bridge._interface_class)
    assert core.preflight('metadata-only')['native_calls']==0
    monkeypatch.delitem(bridge._INTERFACES,'ICWTpBaseFeature')
    with pytest.raises(ValueError):core.preflight('metadata-only')


def test_owned_null_dispatch_does_not_depend_on_client_wrapping():
    import comtypes.client
    ptr=POINTER(IDispatch)()
    assert ptr.__ctypes_from_outparam__() is None
    assert core.dispatch_presence(ptr)['present'] is False
    for bad in (None,object(),0,False,'pointer'):
        with pytest.raises(ValueError):core.dispatch_presence(bad)
