"""Portable metadata/QI adapter tests; no installed CAM or application needed."""
import ctypes
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import pytest


@pytest.fixture
def env(monkeypatch):
    if not hasattr(ctypes, 'HRESULT'):
        monkeypatch.setattr(ctypes, 'HRESULT', ctypes.c_int32, raising=False)
    def require(ok, message):
        if not ok: raise ValueError(message)
    class BridgeError(RuntimeError):
        def __init__(self, code, stage, exc, **kwargs):
            self.code, self.stage, self.error_type = code, stage, type(exc).__name__
            super().__init__(code)
    package = ModuleType('scripts'); package.__path__ = []
    monkeypatch.setitem(sys.modules, 'scripts', package)
    for name, values in (
        ('sw_cam_comtypes', dict(_load_type_library=lambda path:None,
            _is_comtypes_pointer=lambda value:False, CamComBridgeError=BridgeError)),
        ('sw_cam_face_interfaces', dict(_verify_generated_class=lambda *args:None)),
        ('sw_cam_rough_firstcut', dict(require=require))):
        module = ModuleType('scripts.' + name); module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, 'scripts.' + name, module)
    path=Path(__file__).parents[1]/'scripts/sw_cam_taper_interfaces.py'
    spec=importlib.util.spec_from_file_location('taper_adapter_portable', path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    class Interface:
        _iid_=m.TAPER_IID
    methods=[]
    for name,(dispid,kind,writable) in m.PROPERTIES.items():
        ctype=ctypes.c_int if kind=='int' else ctypes.c_double
        setattr(Interface,name,property(lambda self:None,(lambda self,v:None) if writable else None))
        for access,prefix,arg,direction in (
            ('propget','_get_',ctypes.POINTER(ctype),10),('propput','_set_',ctype,1)):
            if access=='propput' and not writable:continue
            methods.append(SimpleNamespace(name=prefix+name,restype=ctypes.HRESULT,
                argtypes=(arg,),paramflags=((direction,'pVal'),),idlflags=(dispid,'description',access)))
    Interface._methods_=methods
    log=[]
    monkeypatch.setattr(m,'_load_type_library',lambda path:(log.append(('load',path)) or SimpleNamespace(ICWTaperTool=Interface)))
    def verify(interface,iid,pin):
        log.append(('verify',iid,pin))
        require(interface._iid_==iid and pin=={'path':'generated.py','sha256':'a'*64},'Generated pin or IID differs')
        return interface
    monkeypatch.setattr(m,'_verify_generated_class',verify)
    return SimpleNamespace(m=m,interface=Interface,log=log,pin={'path':'generated.py','sha256':'a'*64},BridgeError=BridgeError)


def test_audit_resolves_all_properties_without_native_calls(env):
    r=env.m.audit_taper_interface('camworks.tlb',generated_pin=env.pin)
    assert r['all_resolved'] is True and r['property_signatures_verified'] is True
    assert len(r['properties'])==13
    assert all(r[k]==0 for k in ('application_connections','native_query_interface_calls','native_getters_called','native_setters_called'))
    assert r['interface_runtime_support_qualified'] is False
    assert env.log[0][0]=='load' and env.log[1][0]=='verify'
    assert next(v for v in r['properties'] if v['name']=='MaxDia')['setter'] is False


@pytest.mark.parametrize('name',['ICWTool','Unknown','',None,True])
def test_only_exact_extension_name(env,name):
    with pytest.raises(ValueError):env.m.taper_interface_class(name,'camworks.tlb',generated_pin=env.pin)
    assert env.log==[]


@pytest.mark.parametrize('alter',['missing_getter','missing_setter','duplicate','wrong_arg','wrong_direction','wrong_hresult','wrong_dispid','bool_dispid','wrong_access','readonly_setter','missing_descriptor'])
def test_bad_metadata_rejected_before_application(env,alter):
    rows=env.interface._methods_;row=next(v for v in rows if v.name=='_get_EndDia')
    if alter=='missing_getter':rows.remove(row)
    elif alter=='missing_setter':rows.remove(next(v for v in rows if v.name=='_set_EndDia'))
    elif alter=='duplicate':rows.append(row)
    elif alter=='wrong_arg':row.argtypes=(ctypes.POINTER(ctypes.c_int),)
    elif alter=='wrong_direction':row.paramflags=((1,'pVal'),)
    elif alter=='wrong_hresult':row.restype=ctypes.c_double
    elif alter=='wrong_dispid':row.idlflags=(99,'description','propget')
    elif alter=='bool_dispid':
        first=next(v for v in rows if v.name=='_get_TaperToolType');first.idlflags=(True,'description','propget')
    elif alter=='wrong_access':row.idlflags=(2,'description','propput')
    elif alter=='readonly_setter':env.interface.MaxDia=property(lambda s:None,lambda s,v:None)
    else:delattr(env.interface,'EndDia')
    with pytest.raises(ValueError):env.m.audit_taper_interface('camworks.tlb',generated_pin=env.pin)


def test_real_dispid_int_subclass_supported(env):
    class Dispid(int):pass
    for row in env.interface._methods_:row.idlflags=(Dispid(row.idlflags[0]),*row.idlflags[1:])
    assert env.m.audit_taper_interface('camworks.tlb',generated_pin=env.pin)['all_resolved'] is True


@pytest.mark.parametrize('pin',[{}, {'path':'other.py','sha256':'a'*64}])
def test_generated_provenance_failure_propagates(env,pin):
    with pytest.raises(ValueError,match='pin'):env.m.audit_taper_interface('camworks.tlb',generated_pin=pin)


def test_iid_failure_propagates(env):
    env.interface._iid_='{00000000-0000-0000-0000-000000000000}'
    with pytest.raises(ValueError,match='IID'):env.m.audit_taper_interface('camworks.tlb',generated_pin=env.pin)


@pytest.mark.parametrize('value',[None,0,1,False,'object'])
def test_query_rejects_non_native_pointer_without_resolving(env,value):
    with pytest.raises(ValueError):env.m.query_taper_interface(value,'ICWTaperTool','camworks.tlb',generated_pin=env.pin)
    assert env.log==[]


def test_query_uses_one_exact_native_qi(env,monkeypatch):
    result=env.interface();calls=[]
    class Native:
        def QueryInterface(self,interface):calls.append(interface);return result
    obj=Native()
    monkeypatch.setattr(env.m,'_is_comtypes_pointer',lambda value:value is obj or value is result)
    assert env.m.query_taper_interface(obj,'ICWTaperTool','camworks.tlb',generated_pin=env.pin) is result
    assert calls==[env.interface]


@pytest.mark.parametrize('mode',['null','wrong_class','exception'])
def test_failed_native_qi_stops_without_retry(env,monkeypatch,mode):
    calls=[]
    class Native:
        def QueryInterface(self,interface):
            calls.append(interface)
            if mode=='exception':raise RuntimeError('private detail')
            return None if mode=='null' else object()
    obj=Native();monkeypatch.setattr(env.m,'_is_comtypes_pointer',lambda value:value is not None)
    with pytest.raises((ValueError,env.BridgeError)) as found:
        env.m.query_taper_interface(obj,'ICWTaperTool','camworks.tlb',generated_pin=env.pin)
    assert calls==[env.interface] and 'private detail' not in str(found.value)
