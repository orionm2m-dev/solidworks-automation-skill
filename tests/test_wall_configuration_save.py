from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from scripts import sw_cam_wall_configuration_save as m


def status(generated=False):
    return dict(operation_native_id=144,feature_native_id=79,tool_native_id=273,background_over_before=False,background_over_after=False,generated=generated,generated_for_feature=generated,record_counts=[10] if generated else [])


class Journal:
    def __init__(self):self.report={'actions':{},'initial_source_sha256':'a'*64}
    def persist(self):pass
    def pending(self,label):
        assert label=='SaveActiveDocument' and label not in self.report['actions']
        self.report['actions'][label]={'attempted':True};self.report['phase']=label
    def returned(self,label,value):self.report['actions'][label].update(returned=True,value=value)


def backend(calls,*,generated=False,save_return=0,after=None):
    snapshot={'preserved_streams':[760,191,74,29,31196],'wall_streams':[]}
    def capture(label):calls.append(label);return deepcopy(after if label=='settings_saved' and after is not None else snapshot)
    def save():calls.append('Save');return save_return
    return SimpleNamespace(boundary=lambda:None,outcome=lambda:status(generated),capture_full=capture,save=save,
        saved_hash=lambda _: 'b'*64,finish=lambda:calls.append('finish'))


def equivalent(a,b):
    if a!=b:raise ValueError('Changed saved state')
    return b


@pytest.fixture
def projections():
    with patch.object(m.parent,'verify_capture'),patch.object(m.wall,'save_projection',side_effect=deepcopy),patch.object(m.wall,'equivalent_projection',side_effect=equivalent):yield


def test_only_one_save_preserves_settings_without_generation(projections):
    calls=[];j=Journal();m.preserve(backend(calls),j,{})
    assert calls==['settings_before','Save','settings_saved','finish']
    assert j.report['status']=='saved_configuration_no_toolpath'
    assert j.report['model_saved'] and j.report['readback_verified']
    assert j.report['generated_record_counts']==[] and set(j.report['actions'])=={'SaveActiveDocument'}


@pytest.mark.parametrize('code',[False,None,1,-1])
def test_nonzero_or_noninteger_save_is_not_accepted(projections,code):
    calls=[];j=Journal()
    with pytest.raises(ValueError):m.preserve(backend(calls,save_return=code),j,{})
    assert calls==['settings_before','Save'] and not j.report.get('model_saved')


def test_path_appearing_after_empty_attempt_prevents_settings_only_save(projections):
    calls=[];j=Journal()
    with pytest.raises(ValueError):m.preserve(backend(calls,generated=True),j,{})
    assert calls==[] and j.report['actions']=={}


def test_changed_saved_readback_is_not_success(projections):
    calls=[];j=Journal()
    with pytest.raises(ValueError):m.preserve(backend(calls,after={'changed':True}),j,{})
    assert calls==['settings_before','Save','settings_saved'] and not j.report.get('readback_verified')


def test_runtime_backend_forbids_setters_and_generation():
    b=object.__new__(m.outcome.NativeBackend)
    for method in ('set_field','assign','generate'):
        with pytest.raises(RuntimeError):getattr(b,method)(None)