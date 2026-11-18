import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,server,CLSID
from scripts import sw_cam_circular_gtp_save as core


def params(context,**changes):
    v=dict(addin_clsid=CLSID,process_id=731,expected_process_create_time=100.25,expected_document_path=context.document,expected_source_sha256='a'*64,
        failed_receipt_path='failed.json',failed_receipt_sha256='b'*64,old_marker_path='old.json',old_marker_sha256='c'*64,
        operation_native_id=13,expected_xy_feed_before=500.,expected_xy_feed_after=1000.,expected_generated_record_count=31,
        receipt_path='receipt.json',saved_cl_path='after.cl')
    v.update(changes);return server.SolidWorksCamCircularGtpSaveInput(**v)


@pytest.fixture
def fake(context,monkeypatch):
    monkeypatch.setattr(server,'_runtime_identity',SimpleNamespace(assert_current=Mock(return_value=None)))
    monkeypatch.setattr(core,'validate',Mock(return_value={}))
    fn=Mock(return_value=dict(status='review_required',continuation_verified=True,GTP_attempted=False));monkeypatch.setattr(core,'dispatch',fn);return fn


def test_real_schema_and_wrapper_exact_scope_pass_through(context,fake):
    p=params(context);r=json.loads(server.solidworks_cam_save_generated_circular(p))
    assert r['continuation_verified'] and not r['GTP_attempted'] and fake.call_count==1
    values=p.model_dump(exclude={'addin_clsid','expected_document_title','response_format'})
    core.validate.assert_called_once_with(values)
    args,kw=fake.call_args;assert args[0] is context.sw and args[1]==CLSID and callable(kw.pop('runtime_check')) and kw==values
    tool=server.mcp._tool_manager._tools['solidworks_cam_save_generated_circular'];assert tool.annotations.readOnlyHint is False and tool.annotations.idempotentHint is False


@pytest.mark.parametrize('change',[{'process_id':True},{'operation_native_id':True},{'expected_generated_record_count':0},{'expected_xy_feed_after':float('nan')},{'expected_xy_feed_before':True},{'expected_xy_feed_after':500.},{'qualification_only':False},{'qualification_only':1},{'unknown':1}])
def test_strict_schema_rejects_coerced_or_invalid_scope(context,fake,change):
    with pytest.raises(ValueError):params(context,**change)
    fake.assert_not_called()


@pytest.mark.parametrize('pid',[None,True,732])
def test_PID_before_history_or_native_target(context,fake,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid);r=json.loads(server.solidworks_cam_save_generated_circular(params(context)))
    assert r['status']=='error';core.validate.assert_not_called();fake.assert_not_called();context.connect.assert_not_called()


def test_bad_history_before_native_target(context,fake):
    core.validate.side_effect=ValueError('history mismatch');r=json.loads(server.solidworks_cam_save_generated_circular(params(context)))
    assert r['status']=='error';fake.assert_not_called();context.connect.assert_not_called()
