"""Absent optional evidence may skip; explicitly bad evidence must fail."""
import importlib.util
from pathlib import Path
import pytest

CASES=[
 ('test_factory_guard_partition.py','actual','SW_CAM_FACTORY_FAILURE_FIXTURE'),
 ('test_long_cut_context.py','actual','SW_CAM_ROOT_REST_EVIDENCE_ROOT'),
 ('test_mixed_profile.py','actual','SW_CAM_MIXED_ROOT_EVIDENCE_ROOT'),
 ('test_mixed_root_pockets.py','specs','SW_CAM_MIXED_ROOT_EVIDENCE_ROOT'),
 ('test_mixed_root_pockets.py','current_context','SW_CAM_MIXED_ROOT_EVIDENCE_ROOT'),
 ('test_saved_long_cut_reopen.py','actual','SW_CAM_LONG_CUT_REOPEN_EVIDENCE_ROOT'),
 ('test_completed_deep_save.py','actual','SW_CAM_COMPLETED_DEEP_SAVE_EVIDENCE_ROOT'),
 ('test_deep_long_tool_gtp_continue.py','actual','SW_CAM_LONG_TOOL_CONTINUATION_EVIDENCE_ROOT'),
 ('test_deep_long_tool_gtp_recover.py','actual','SW_CAM_LONG_TOOL_CONTINUATION_EVIDENCE_ROOT'),
 ('test_long_cut_reconciliation.py','actual','SW_CAM_LONG_CUT_EVIDENCE_ROOT'),
]


def load(filename):
    path=Path(__file__).parent/filename
    spec=importlib.util.spec_from_file_location('optional_policy_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('filename,fixture,env',CASES)
@pytest.mark.parametrize('value',['absent','empty','relative','missing','empty_directory'])
def test_optional_fixture_configuration_is_strict(tmp_path,monkeypatch,filename,fixture,env,value):
    monkeypatch.delenv(env,raising=False)
    if value=='empty':monkeypatch.setenv(env,'')
    elif value=='relative':monkeypatch.setenv(env,'relative-evidence')
    elif value=='missing':monkeypatch.setenv(env,str(tmp_path/'missing'))
    elif value=='empty_directory':monkeypatch.setenv(env,str(tmp_path))
    module=load(filename)
    callback=getattr(module,fixture).__wrapped__
    if value=='absent':
        with pytest.raises(pytest.skip.Exception):callback()
    else:
        with pytest.raises((ValueError,FileNotFoundError,pytest.fail.Exception)):callback()
