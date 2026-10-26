from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from scripts import sw_cam_material_catalogue as cam
from scripts import sw_cam_events as events

VALID=([10,11],['304L','316S'],[8,8],['Stainless Steel','Stainless Steel'],2)

def test_exact_native_names_not_alloy_substitution():
    rows=cam._parse_catalogue(VALID)
    assert rows[1]['material_name']=='316S' and rows[0]['group_name']=='Stainless Steel'

@pytest.mark.parametrize('raw',[None,(),((),(),(),(),True),((),(),(),(),-1),((),(),(),(),4097),([1],[],[2],['g'],1),([1,1],['a','b'],[2,2],['g','g'],2),([True],['a'],[2],['g'],1),([1],[''],[2],['g'],1),([1],['a'],[-1],['g'],1),([1],['a'],[2],['g\x00'],1)])
def test_bad_native_shape_fails_closed(raw):
    with pytest.raises(ValueError):cam._parse_catalogue(raw)


def test_empty_catalogue_supported():assert cam._parse_catalogue((None,None,None,None,0))==[]

@pytest.fixture
def probe(monkeypatch,tmp_path):
    path=tmp_path/'test.sldprt';path.write_bytes(b'part')
    doc=dict(path=str(path),title=path.name,type=1,needs_save=False)
    data=dict(subscribed=False,active=False,disconnected=False,event_count=0,overflow=0,callback_errors=[],disconnect_errors=[])
    hook={'exit':None}
    class Session:
        def __enter__(self):data.update(subscribed=True,active=True);return self
        def __exit__(self,*_):
            data.update(active=False,disconnected=True)
            if hook['exit']:hook['exit']()
        def summary(self):return deepcopy(data)
    app=SimpleNamespace(GetWorkpieceMaterials=Mock(return_value=VALID),GetUseDocumentUnit=Mock(return_value=False))
    addin=SimpleNamespace(GetCWApp=Mock(return_value=app));sw=SimpleNamespace(GetAddInObject=Mock(return_value=addin))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(cam,'document_snapshot',lambda *_:deepcopy(doc))
    monkeypatch.setattr(events,'CamMessageSession',lambda *_:Session())
    def run():return cam.inspect_material_catalogue(sw,'clsid','tlb',expected_document_path=str(path))
    return SimpleNamespace(**locals())


def test_readonly_catalogue_and_cleanup(probe):
    out=probe.run()
    assert out['status']=='ok' and out['material_count']==2 and not out['mutation_attempted']
    assert not out['material_mapping_qualified'] and not out['native_getter_units_qualified']
    assert probe.app.GetWorkpieceMaterials.call_count==2
    assert out['messages']['disconnected'] and not out['post_cleanup_CAM_getters']


def test_message_stops_next_getter(probe):
    def read():probe.data['event_count']=1;return VALID
    probe.app.GetWorkpieceMaterials.side_effect=read
    assert probe.run()['status']=='error'
    probe.app.GetUseDocumentUnit.assert_not_called()
    assert probe.app.GetWorkpieceMaterials.call_count==1


def test_catalogue_change_detected(probe):
    probe.app.GetWorkpieceMaterials.side_effect=[VALID,([10],['304L'],[8],['Stainless Steel'],1)]
    assert probe.run()['status']=='error'

@pytest.mark.parametrize('kind',['file','document','event','disconnect'])
def test_cleanup_has_no_native_read_and_checks_state(probe,kind):
    def finish():
        if kind=='file':probe.path.write_bytes(b'changed')
        if kind=='document':probe.doc['title']='other'
        if kind=='event':probe.data['event_count']=1
        if kind=='disconnect':probe.data['disconnected']=False
    probe.hook['exit']=finish
    assert probe.run()['status']=='error'
    assert probe.app.GetWorkpieceMaterials.call_count==2

@pytest.mark.parametrize('flag',[None,0,1,'true'])
def test_document_unit_flag_not_inferred(probe,flag):
    probe.app.GetUseDocumentUnit.return_value=flag
    assert probe.run()['status']=='error'
