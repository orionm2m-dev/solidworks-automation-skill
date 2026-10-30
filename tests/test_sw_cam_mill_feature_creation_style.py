import ast
from pathlib import Path
import pytest
from test_sw_cam_mill_inventory import native,probe
from scripts import sw_cam_mill_inventory as cam

@pytest.mark.parametrize('value,name',[(0,'AFR'),(1,'MFGVIEW')])
def test_declared_native_style_is_observed_without_assignment(native,value,name):
    native.doc.FeatureCreationStyle=value
    result=native.run()
    assert result['recognition_method']==dict(value=value,name=name,status='observed_via_ICWDoc3_FeatureCreationStyle')
    assert native.doc.FeatureCreationStyle==value

@pytest.mark.parametrize('value',[False,True,None,-1,2,0.,1.,'0'])
def test_unknown_or_noninteger_native_style_stops(native,value):
    native.doc.FeatureCreationStyle=value
    with pytest.raises(ValueError,match='FeatureCreationStyle'):native.run()
    assert native.diagnostic['last_native_method']=='FeatureCreationStyle'
    assert native.diagnostic['capture_complete'] is False


def test_missing_property_is_not_relabelled_unknown(native):
    del native.doc.FeatureCreationStyle
    with pytest.raises(AttributeError):native.run()
    assert native.diagnostic['last_native_method']=='FeatureCreationStyle'
    assert native.diagnostic['capture_complete'] is False


def test_native_getter_error_is_not_hidden_by_fallback(native,monkeypatch):
    original=cam._member
    def member(obj,name,*args):
        if name=='FeatureCreationStyle':raise RuntimeError('native getter unavailable')
        return original(obj,name,*args)
    monkeypatch.setattr(cam,'_member',member)
    with pytest.raises(RuntimeError,match='native getter unavailable'):native.run()
    assert native.diagnostic['capture_complete'] is False


def test_style_drift_invalidates_stable_readonly_inventory(probe):
    probe.state['recognition_method']=dict(value=0,name='AFR',status='observed_via_ICWDoc3_FeatureCreationStyle')
    def drift():
        if len(probe.calls)==2:probe.state['recognition_method'].update(value=1,name='MFGVIEW')
    probe.knobs['on_capture']=drift
    result=probe.run()
    assert result['status']=='error' and not result['readback_verified']
    assert not result['mutation_attempted']


def test_reader_has_no_style_setter():
    p=Path(cam.__file__);tree=ast.parse(p.read_text(encoding='utf-8'))
    writes=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='setattr']
    assert not writes
