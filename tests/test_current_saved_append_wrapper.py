import ast,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import server
from test_current_saved_append import planning
from test_current_saved_compound import env
from scripts import sw_cam_mill_append_operations as old

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
 server.mcp._tool_manager._tools.pop('solidworks_cam_append_mill_operations',None)
 exec(compile(ast.parse(SOURCE.read_text(encoding='utf-8')),str(SOURCE),'exec'),server.__dict__)


@pytest.fixture
def wrapper(planning,monkeypatch):
 guard=Mock();fake=Mock(return_value=dict(status='review_required',readback_verified=True,receipt_created=False,marker_created=False,mutation_attempted=False,before={'actual':1},confirm_before={'actual':1}))
 monkeypatch.setattr(old,'append_current_saved_operations',fake)
 monkeypatch.setattr(server,'_selected_process_id',123)
 monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=guard))
 monkeypatch.setattr(server,'_cam_target',lambda p:('sw',dict(clsid='clsid',addin_path=r'C:\test\cam.dll')))
 monkeypatch.setattr(server,'_run_locked',lambda op,fmt:json.dumps(op()))
 def params(**changes):
  values=dict(planning['planning_args'],addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}');values.update(changes)
  return server.SolidWorksCamCurrentSavedAppendInput(**values)
 return planning,fake,guard,params


def test_existing_endpoint_routes_current_mode_and_internal_guard(wrapper):
 e,f,guard,params=wrapper;p=params();r=json.loads(server.solidworks_cam_append_mill_operations(p))
 assert r['runtime_unchanged'] and f.call_count==1 and guard.call_count==2
 assert f.call_args.kwargs['runtime_check'] is guard
 assert 'solidworks_cam_append_mill_operations' in server.mcp._tool_manager._tools


@pytest.mark.parametrize('changes',[{'save_after_verified':True},{'save_after_verified':0},{'action':'save'},
 {'planning_mode':'historical'},{'observation':'header_and_count'},{'acknowledge_disposable_copy':False},
 {'expected_process_create_time':True},{'current_read_request_sha256':'a'*64},{'runtime_check':'override'}])
def test_schema_rejects_unsafe_or_forged_request_without_native(wrapper,changes):
 e,f,guard,params=wrapper
 with pytest.raises((ValueError,TypeError)):params(**changes)
 f.assert_not_called();guard.assert_not_called()


def test_post_runtime_drift_retains_native_outcome_and_revokes_success(wrapper):
 e,f,guard,params=wrapper;guard.side_effect=[None,RuntimeError('drift')]
 f.return_value.update(mutation_attempted=True,native_call_returned=True,after={'actual_new_op':300})
 r=json.loads(server.solidworks_cam_append_mill_operations(params()))
 assert r['status']=='uncertain' and not r['readback_verified'] and not r['runtime_unchanged']
 assert r['native_call_returned'] and r['after']['actual_new_op']==300 and f.call_count==1
