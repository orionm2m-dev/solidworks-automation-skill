import ast,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,server,CLSID
from scripts import sw_cam_circular_nc_read as core

def args(context):return dict(addin_clsid=CLSID,process_id=731,expected_process_create_time=100.25,expected_document_path=context.document,expected_source_sha256='a'*64,reconciliation_path='review.json',reconciliation_sha256='b'*64,operation_native_id=361,receipt_path='r.json')

@pytest.fixture
def fake(context,monkeypatch):
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock()));monkeypatch.setattr(core,'validate',Mock());fn=Mock(return_value=dict(status='review_required',readback_verified=True));monkeypatch.setattr(core,'run_read',fn);return fn

def test_schema_wrapper_passes_exact_read_fields(context,fake):
    p=server.SolidWorksCamCircularNCReadInput(**args(context));r=json.loads(server.solidworks_cam_read_circular_cutting_context(p));assert r['readback_verified'] and fake.call_count==1
    v=p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'});core.validate.assert_called_once_with(v);actual=fake.call_args.kwargs;assert callable(actual.pop('runtime_check')) and actual==v

@pytest.mark.parametrize('update',[{'process_id':True},{'operation_native_id':True},{'qualification_only':False},{'set_feed':2.}])
def test_schema_rejects_nonread_or_coerced_scope(context,fake,update):
    v=args(context);v.update(update)
    with pytest.raises(ValueError):server.SolidWorksCamCircularNCReadInput(**v)
    fake.assert_not_called()

def test_wrong_pid_before_native_or_history(context,fake,monkeypatch):
    monkeypatch.setattr(server,'_selected_process_id',732);r=json.loads(server.solidworks_cam_read_circular_cutting_context(server.SolidWorksCamCircularNCReadInput(**args(context))));assert r['status']=='error';fake.assert_not_called();core.validate.assert_not_called();context.connect.assert_not_called()
