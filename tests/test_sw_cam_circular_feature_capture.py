"""The shared capture remains explicit; old callers cannot silently accept circles."""
from copy import deepcopy
from types import SimpleNamespace as N
import pytest
from test_sw_cam_circular_mill_qualification import case,cam
from scripts import sw_cam_mill_feature_process as process

@pytest.fixture
def ready(case,monkeypatch):
    created=case.apply();assert created['status']=='review_required'
    case.status.update(active=True,subscribed=True,disconnected=False)
    case.native['machine']=N(IGetEnumOpSetups=lambda:[])
    snapshot=cam._mill_snapshot
    def capture(sw,clsid,tlb,path,**kwargs):
        return snapshot(sw,clsid,tlb,path,check=kwargs['check'])
    monkeypatch.setattr(process,'_mill_snapshot',capture)
    monkeypatch.setattr(process,'_typed',cam._typed)
    monkeypatch.setattr(process,'_items',cam._items)
    monkeypatch.setattr(process,'document_snapshot',lambda sw:deepcopy(case.document))
    return case,created

def test_shared_capture_circle_explicit_only(ready):
    case,created=ready
    state,native=process.capture_mill_feature_state(case.sw,'clsid','tlb',str(case.part),
        expected_feature_native_id=99,check=lambda:None,feature_kind='circular_pocket')
    assert state['selected_feature']==created['observed_feature']
    assert state['feature_kind']=='circular_pocket'
    assert state['operations']==[] and native['selected_feature'] is case.feature

def test_default_capture_refuses_circle_before_top_contours(ready):
    case,_=ready
    with pytest.raises(ValueError,match='OPEN_POCKET'):
        process.capture_mill_feature_state(case.sw,'clsid','tlb',str(case.part),
            expected_feature_native_id=99,check=lambda:None)
