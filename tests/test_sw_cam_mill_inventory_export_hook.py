from unittest.mock import Mock
from test_sw_cam_mill_inventory import native,probe
from scripts import sw_cam_mill_inventory as cam

def test_default_stock_parser_remains_strict(native,monkeypatch):
    strict=Mock(side_effect=ValueError('False offset'))
    monkeypatch.setattr(cam,'_stock',strict)
    import pytest
    with pytest.raises(ValueError,match='False offset'):native.run()
    strict.assert_called_once()

def test_only_explicit_internal_observer_overrides_stock(native,monkeypatch):
    strict=Mock(side_effect=ValueError('False offset'));observer=Mock(return_value=({'offset_read_status':'unavailable_native_false'},object()))
    monkeypatch.setattr(cam,'_stock',strict)
    result=cam.capture_mill_inventory(native.sw,'clsid','tlb','C:/part.sldprt',check=lambda:None,diagnostic={},stock_reader=observer)
    assert result['stock']=={'offset_read_status':'unavailable_native_false'}
    observer.assert_called_once();strict.assert_not_called()

def test_guarded_capture_forwards_observer_and_closes_source_handles(probe,monkeypatch):
    observer=object();seen=[];status=[]
    original=cam.capture_mill_inventory
    def inner(*args,**kw):
        seen.append(kw['stock_reader']);assert status==['open']
        return original(*args,**kw)
    class Files:
        def __init__(self,*args):pass
        def __enter__(self):status.append('open');return self
        def check(self):assert status==['open']
        def __exit__(self,*args):status.append('closed')
    monkeypatch.setattr(cam,'_CaptureReadFiles',Files)
    monkeypatch.setattr(cam,'capture_mill_inventory',inner)
    probe.flags.update(active=True,subscribed=True)
    result=cam.capture_guarded_mill_inventory(probe.sw,'clsid','tlb',str(probe.part),process_id=731,expected_source_sha256=cam._file_hash(probe.part),check=lambda:None,diagnostic={},stock_reader=observer)
    assert seen==[observer] and status==['open','closed']
