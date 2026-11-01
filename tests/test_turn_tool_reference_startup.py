"""Exercise the real startup method with portable callbacks, not CAD."""
import importlib.util,os,sys
from pathlib import Path
from copy import deepcopy
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).parents[1])))
sys.path.insert(0,str(ROOT))
P=Path(__file__).parents[1]/'scripts/sw_cam_turn_tool_reference_repair.py'
spec=importlib.util.spec_from_file_location('repair_startup_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_installed_reader_exports_expected_typed_function():
    from scripts.sw_cam_generation import _typed
    assert hasattr(m.reader,'_typed') and m.reader._typed is _typed


@pytest.mark.parametrize('dirty',[False,True])
def test_native_backend_start_follows_observed_dirty_state(monkeypatch,dirty):
    log=[];sw,addin,rawapp,typedapp=object(),object(),object(),object()
    expected={'path':'C:/review/part.sldprt','title':'part.sldprt','type':1,'needs_save':dirty}
    b=m.NativeBackend.__new__(m.NativeBackend);b.sw=sw;b.typelib='metadata.tlb'
    b.plan={'reference':{'document':expected},'pins':[],'catalogue':{'request':{'addin_clsid':'exact'}}}
    b.identity=lambda:deepcopy(expected);b.boundary=lambda:log.append('boundary');b.active=False
    def member(obj,name,*args):
        log.append(name)
        if obj is sw and name=='GetAddInObject' and args==('exact',):return addin
        if obj is addin and name=='GetCWApp' and args==():return rawapp
        raise AssertionError('unexpected native surface')
    def typed(obj,name,typelib):
        assert obj is rawapp and name=='ICWApp4' and typelib=='metadata.tlb'
        log.append('typed');return typedapp
    class Session:
        def __init__(self,app,typelib):assert app is typedapp and typelib=='metadata.tlb'
        def __enter__(self):log.append('subscribe');return self
    monkeypatch.setattr(m,'_member',member);monkeypatch.setattr(m.reader,'_typed',typed)
    monkeypatch.setattr(m.reader.prior.events,'CamMessageSession',Session)
    monkeypatch.setattr(m.common,'_check',lambda _:log.append('pins'))
    b.start()
    assert b.active is True and log==['pins','GetAddInObject','GetCWApp','typed','subscribe','boundary']


def test_native_backend_start_rejects_dirty_drift_before_addin(monkeypatch):
    b=m.NativeBackend.__new__(m.NativeBackend)
    b.plan={'reference':{'document':{'needs_save':False}}};b.identity=lambda:{'needs_save':True}
    monkeypatch.setattr(m,'_member',lambda *_:pytest.fail('No native addin lookup allowed'))
    with pytest.raises(ValueError,match='dirty'):b.start()
