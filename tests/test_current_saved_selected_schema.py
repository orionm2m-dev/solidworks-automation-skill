import ast,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import server
from test_current_saved_selected_insert import packet
from test_current_saved_append_save import saving
from test_current_saved_append import planning
from test_current_saved_compound import env
from scripts import sw_cam_mill_append_operations as old

SOURCE=Path(__file__).resolve().parents[1]/'server_nodes.py'
if SOURCE.is_file():
 server.mcp._tool_manager._tools.pop('solidworks_cam_append_mill_operations',None)
 exec(compile(ast.parse(SOURCE.read_text(encoding='utf-8')),str(SOURCE),'exec'),server.__dict__)


def values(e,**kw):return dict(e['planning_args'],addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',**kw)


def test_same_endpoint_typed_selected_mode_internal_runtime_guard(packet,monkeypatch):
 e=packet;p=server.SolidWorksCamCurrentSavedAppendInput(**values(e));fake=Mock(return_value=dict(status='review_required',mutation_attempted=False,receipt_created=False,marker_created=False))
 guard=Mock();monkeypatch.setattr(old,'append_current_saved_operations',fake);monkeypatch.setattr(server,'_selected_process_id',123)
 monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=guard));monkeypatch.setattr(server,'_cam_target',lambda p:('sw',dict(clsid='clsid',addin_path=r'C:\test\cam.dll')))
 monkeypatch.setattr(server,'_run_locked',lambda op,fmt:json.dumps(op()))
 r=json.loads(server.solidworks_cam_append_mill_operations(p));assert r['runtime_unchanged'] and guard.call_count==2
 assert fake.call_args.kwargs['definition_mode']=='selected_insert' and fake.call_args.kwargs['runtime_check'] is guard
 assert 'solidworks_cam_append_mill_operations' in server.mcp._tool_manager._tools

@pytest.mark.parametrize('change',[{'suppress_operation_native_ids':['300',302]},{'suppress_operation_native_ids':[True,302]},{'insert_operations':[{'operation_type':False,'default_operation_name':'Default','default_operation_id':100},{'operation_type':1,'default_operation_name':'Default','default_operation_id':101}]},{'runtime_check':'override'},{'definition_mode':'unknown'}])
def test_strict_schema_rejects_coercion_and_extra_fields(packet,change):
 args=values(packet);args.update(change)
 with pytest.raises((ValueError,TypeError)):server.SolidWorksCamCurrentSavedAppendInput(**args)
 assert not packet['calls']
