import ast,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import server
from test_current_saved_selected_continue import recovering
from test_current_saved_selected_insert import packet
from test_current_saved_append_save import saving
from test_current_saved_append import planning
from test_current_saved_compound import env
from scripts import sw_cam_mill_append_operations as old

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
 server.mcp._tool_manager._tools.pop('solidworks_cam_append_mill_operations',None)
 exec(compile(SOURCE.read_text(encoding='utf-8'),str(SOURCE),'exec'),server.__dict__)


def test_same_endpoint_readonly_recovery_schema_and_runtime_guard(recovering,monkeypatch):
 e=recovering;args=dict(e['planning_args'],addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}');params=server.SolidWorksCamCurrentSavedAppendInput(**args)
 guard=Mock();fake=Mock(return_value=dict(status='review_required',readback_verified=True,mutation_attempted=False,receipt_created=False,marker_created=False))
 monkeypatch.setattr(old,'append_current_saved_operations',fake);monkeypatch.setattr(server,'_selected_process_id',123);monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=guard));monkeypatch.setattr(server,'_cam_target',lambda p:('sw',dict(clsid='clsid',addin_path=r'C:\test\cam.dll')));monkeypatch.setattr(server,'_run_locked',lambda op,fmt:json.dumps(op()))
 result=json.loads(server.solidworks_cam_append_mill_operations(params));assert result['runtime_unchanged'] and fake.call_count==1
 assert fake.call_args.kwargs['definition_mode']=='selected_continue' and fake.call_args.kwargs['retained_operation_native_id']==400 and fake.call_args.kwargs['runtime_check'] is guard
 assert 'solidworks_cam_append_mill_operations' in server.mcp._tool_manager._tools

@pytest.mark.parametrize('field,value',[('retained_operation_native_id',True),('retained_operation_native_id','400'),('partial_receipt_sha256','a'*64),('partial_attempt_marker_path',None),('runtime_check','override')])
def test_continuation_schema_strict_pins_and_no_runtime_override(recovering,field,value):
 e=recovering;args=dict(e['planning_args'],addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}');args[field]=value
 with pytest.raises((ValueError,TypeError)):server.SolidWorksCamCurrentSavedAppendInput(**args)
 assert not e['calls']
