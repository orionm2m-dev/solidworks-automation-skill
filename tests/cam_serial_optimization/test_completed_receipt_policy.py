from types import SimpleNamespace
import pytest
from scripts import sw_cam_saved18_serial_completed as m

@pytest.mark.parametrize('fault',[None,'relative','suffix','parent','missing','symlink','network'])
def test_existing_receipt_path_policy(monkeypatch,fault):
    state=dict(absolute=True,suffix='.json',parent=True,file=True,symlink=False,drive='C:')
    if fault=='relative':state['absolute']=False
    elif fault=='suffix':state['suffix']='.txt'
    elif fault=='parent':state['parent']=False
    elif fault=='missing':state['file']=False
    elif fault=='symlink':state['symlink']=True
    elif fault=='network':state['drive']=r'\\server\share'
    fake=SimpleNamespace(is_absolute=lambda:state['absolute'],suffix=state['suffix'],parent=SimpleNamespace(is_dir=lambda:state['parent']),is_file=lambda:state['file'],is_symlink=lambda:state['symlink'],resolve=lambda:SimpleNamespace(drive=state['drive']))
    monkeypatch.setattr(m,'Path',lambda value:fake)
    if fault is None:assert m.existing_receipt('synthetic') is fake
    else:
        with pytest.raises(ValueError):m.existing_receipt('synthetic')

def test_changed_installed_producer_rejected_before_receipt_read(monkeypatch):
    monkeypatch.setattr(m.common,'_pin',lambda path:dict(sha256='0'*64))
    monkeypatch.setattr(m.opt.prior,'read_json_pin',lambda *args:pytest.fail('must reject producer before reading receipt'))
    with pytest.raises(ValueError,match='Exact unchanged executed V2 producer required'):
        m.load_completed_rebind('synthetic','a'*64)
