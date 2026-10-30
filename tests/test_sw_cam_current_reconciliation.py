"""历史模块只校验字节；限制为一个已审查的运行时身份替换。"""
from copy import deepcopy
from pathlib import Path
import importlib.util
import hashlib
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('current_reconciliation_test_candidate', ROOT/'scripts/sw_cam_current_reconciliation.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def pin(path):
    return dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    current=tmp_path/'current.py';current.write_bytes(b'current synthetic runtime')
    archive=tmp_path/'archive.py';archive.write_bytes(b'raise AssertionError("archive must never execute")')
    now=pin(current);old=pin(archive);old['path']=now['path']
    monkeypatch.setattr(m,'CURRENT_MOVE_SHA256',now['sha256'])
    monkeypatch.setattr(m,'HISTORICAL_MOVE_SHA256',old['sha256'])
    monkeypatch.setattr(m.move,'_self_pin',lambda:pin(current))
    data=dict(module_pin=old)
    return data,current,archive,now


def bind(runtime):
    data,current,archive,now=runtime
    return m.bind_move_runtime(data,str(archive),data['module_pin']['sha256'])


def test_archive_is_not_executed_and_current_is_explicit(runtime):
    result=bind(runtime)
    assert result['archived_code_executed'] is False
    assert result['allowed_runtime_replacement_count']==1
    assert result['archive_pin']['path']==str(runtime[2].resolve())
    assert result['historical_module_pin']==runtime[0]['module_pin']
    assert result['current_module_pin']==runtime[3]


@pytest.mark.parametrize('kind',['archive_bytes','current_bytes','old_sha','old_path','provided_sha','same_path'])
def test_runtime_binding_rejects_unapproved_identity(runtime,kind):
    data,current,archive,now=runtime
    if kind=='archive_bytes':archive.write_bytes(b'changed historical code')
    elif kind=='current_bytes':current.write_bytes(b'changed current code')
    elif kind=='old_sha':data['module_pin']['sha256']='0'*64
    elif kind=='old_path':data['module_pin']['path']=str(current.with_name('other.py'))
    with pytest.raises(ValueError):
        m.bind_move_runtime(data,str(current if kind=='same_path' else archive),
            '0'*64 if kind=='provided_sha' else data['module_pin']['sha256'])


def authority(runtime):
    data,current,archive,now=runtime
    companion=current.with_name('companion.py');companion.write_bytes(b'unchanged companion')
    extra=pin(companion)
    data.update(live_pins=[extra,deepcopy(data['module_pin'])],
        dependency_roles=[dict(pin=extra,role='native_runtime_helper'),dict(pin=deepcopy(data['module_pin']),role='native_runtime_helper')],
        predecessor_validation=dict(verified=True))
    loaded=dict(pins=[deepcopy(extra),deepcopy(now)],dependency_roles=[dict(pin=deepcopy(extra),role='native_runtime_helper'),
        dict(pin=deepcopy(now),role='native_runtime_helper')],predecessor_validation=dict(verified=True))
    return data,loaded


def test_only_known_move_pin_is_backbound_without_mutating_evidence(runtime):
    data,loaded=authority(runtime);before=deepcopy((data,loaded))
    m.require_historical_authority(data,loaded)
    assert (data,loaded)==before


@pytest.mark.parametrize('kind',['other_pin','other_role','missing_move','duplicate_move','changed_move',
                                  'missing_role','role_changed','proof_changed','old_pin_changed'])
def test_second_change_or_missing_role_cannot_hide_in_migration(runtime,kind):
    data,loaded=authority(runtime)
    if kind=='other_pin':loaded['pins'][0]['sha256']='f'*64
    elif kind=='other_role':loaded['dependency_roles'][0]['pin']['sha256']='f'*64
    elif kind=='missing_move':loaded['pins'].pop()
    elif kind=='duplicate_move':loaded['pins'].append(deepcopy(loaded['pins'][-1]))
    elif kind=='changed_move':loaded['pins'][-1]['sha256']='f'*64
    elif kind=='missing_role':loaded['dependency_roles'].pop()
    elif kind=='role_changed':loaded['dependency_roles'][-1]['role']='archive'
    elif kind=='proof_changed':loaded['predecessor_validation']['verified']=False
    elif kind=='old_pin_changed':data['module_pin']['sha256']='f'*64
    with pytest.raises(ValueError):m.require_historical_authority(data,loaded)


def test_request_rejects_mutation_action_before_any_connection():
    with pytest.raises(ValueError):m.validate_request(dict(action='move_existing_face_after196',params={}))
