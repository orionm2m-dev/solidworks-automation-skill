"""错误工作树与陈旧源模块必须在 COM 操作前阻断。"""
import json
import sys
from pathlib import Path
import importlib.util
import pytest
from scripts.sw_runtime_identity import RuntimeIdentity, RuntimeIdentityError


def tree(tmp_path):
    (tmp_path / 'mcp-server').mkdir()
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'mcp-server/server.py').write_text('value=1')
    (tmp_path / 'scripts/core.py').write_text('value=1')
    return tmp_path


def test_matching_runtime_is_ready(tmp_path):
    root=tree(tmp_path);r=RuntimeIdentity.capture(root,str(root))
    assert r.assert_current()['status']=='ready'
    assert r.status()['source_file_count']==2


def test_other_worktree_refused(tmp_path):
    root=tree(tmp_path);r=RuntimeIdentity.capture(root,str(root/'other'))
    with pytest.raises(RuntimeIdentityError,match='ROOT_MISMATCH'):r.assert_current()


@pytest.mark.parametrize('change',['edit','add','delete'])
def test_changed_source_refused(tmp_path,change):
    root=tree(tmp_path);r=RuntimeIdentity.capture(root,str(root));p=root/'scripts/core.py'
    if change=='edit':p.write_text('value=2')
    elif change=='add':(root/'scripts/new.py').write_text('value=1')
    else:p.unlink()
    with pytest.raises(RuntimeIdentityError,match='SOURCE_CHANGED'):r.assert_current()


def test_documentation_does_not_invalidate_runtime(tmp_path):
    root=tree(tmp_path);r=RuntimeIdentity.capture(root,str(root))
    (root/'README.md').write_text('notes')
    assert r.assert_current()['status']=='ready'


def test_invalid_relative_policy_root_refused(tmp_path):
    r=RuntimeIdentity.capture(tree(tmp_path),'relative')
    with pytest.raises(RuntimeIdentityError,match='ROOT_INVALID'):r.assert_current()


def test_source_change_blocks_operation_before_loading_com(monkeypatch,tmp_path):
    path=Path(__file__).resolve().parents[1]/'mcp-server/server.py'
    spec=importlib.util.spec_from_file_location('runtime_guard_test_server',path)
    server=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,server)
    spec.loader.exec_module(server)
    root=tree(tmp_path);guard=RuntimeIdentity.capture(root,str(root))
    (root/'scripts/core.py').write_text('value=2')
    monkeypatch.setattr(server,'_runtime_identity',guard)
    monkeypatch.setattr(server,'_load_automation_modules',lambda:pytest.fail('COM loaded'))
    answer=json.loads(server._run_locked(lambda:pytest.fail('operation executed'),server.ResponseFormat.JSON))
    assert answer['status']=='blocked'
    assert answer['error_code']=='SW_RUNTIME_SOURCE_CHANGED'
    assert not answer['com_probe_performed']
