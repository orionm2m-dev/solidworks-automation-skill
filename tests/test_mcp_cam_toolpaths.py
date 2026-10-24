"""MCP toolpath preparation/status routing tests; no CAD, registry or workers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "mcp-server") not in sys.path:
    sys.path.insert(0, str(ROOT / "mcp-server"))

import server  # noqa: E402
from scripts import sw_cam_generation as generation, sw_cam_installation, sw_cam_jobs as jobs  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
PREPARE = "solidworks_cam_prepare_toolpath_job"
STATUS = "solidworks_cam_job_status"


@pytest.fixture
def context(monkeypatch, tmp_path):
    dll = tmp_path / "registered-cam.dll"
    dll.write_bytes(b"fixture only; never loaded")
    document = str(tmp_path / "calibration.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="calibration.sldprt", GetType=1)
    sw = SimpleNamespace(ActiveDoc=model, RevisionNumber="34.1.0")
    installation = {
        "errors": [],
        "addin_registrations": [{"clsid": CLSID,
            "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}"}],
        "com_registrations": [{"clsid": CLSID, "view": "64", "progid": "Fixture.CAM",
            "servers": [{"kind": "inproc", "path": str(dll), "exists": True}]}],
    }
    observed = {"status": "ok", "document_before": {"path": document, "title": "calibration.sldprt",
        "type": 1, "needs_save": False}, "inventory": {
        "feature_count": 3, "operation_count": 2, "operation_setup_count": 1,
        "operations": [
            {"setup_index": 0, "operation_index": 0, "turn_operation_type": 1, "toolpath_generated": False},
            {"setup_index": 0, "operation_index": 1, "turn_operation_type": 2, "toolpath_generated": False},
        ],
    }}
    inspect = Mock(return_value=observed)
    discover = Mock(return_value=installation)
    identity = Mock(return_value={"alive": True, "create_time": 1720000000.25})
    connect = Mock(return_value=(sw, model))
    start = Mock(side_effect=AssertionError("prepare/status must not launch workers"))
    status = Mock(return_value={"status": "pending", "phase": "waiting_native_completion", "may_continue": False})
    runners = []

    def locked(operation, response_format, load_automation=True, **kwargs):
        runners.append({"format": response_format, "automation": load_automation})
        try:
            return server._result(operation(), response_format)
        except Exception as error:
            return server._tool_error(error, response_format)

    monkeypatch.setattr(server, "_run_locked", locked)
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.setattr(server, "connect_solidworks", connect)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name), raising=False)
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discover)
    monkeypatch.setattr(generation, "inspect_machining", inspect)
    monkeypatch.setattr(jobs, "process_identity", identity)
    monkeypatch.setattr(jobs, "start_job", start)
    monkeypatch.setattr(jobs, "inspect_job", status)
    return SimpleNamespace(dll=dll, document=document, model=model, sw=sw, installation=installation,
        observed=observed, inspect=inspect, discover=discover, identity=identity, connect=connect,
        start=start, status=status, runners=runners, directory=str(tmp_path / "existing-job"))


def inputs(context, **changes):
    values = dict(addin_clsid=CLSID, expected_document_path=context.document,
                  expected_feature_count=3, expected_operation_count=2, expected_operation_setup_count=1,
                  setup_index=0, operation_index=0, expected_operation_type=1,
                  qualification_only=True, message_policy="vendor_default")
    values.update(changes)
    return server.SolidWorksCamToolpathInput(**values)


def test_both_tools_registered_and_described_as_readonly():
    for name in (PREPARE, STATUS):
        tool = server.mcp._tool_manager._tools[name]
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.idempotentHint is True
        assert "response_format" in json.dumps(tool.parameters)
    schema = json.dumps(server.mcp._tool_manager._tools[PREPARE].parameters)
    for name in ("expected_document_path", "setup_index", "operation_index", "expected_operation_type",
                 "expected_feature_count", "expected_operation_count", "expected_operation_setup_count",
                 "qualification_only", "message_policy", "attention_seconds"):
        assert name in schema
    assert "job_directory" in json.dumps(server.mcp._tool_manager._tools[STATUS].parameters)


def test_prepare_routes_verified_registry_pid_and_exact_selector_without_start(context):
    result = json.loads(server.solidworks_cam_prepare_toolpath_job(inputs(
        context, operation_index=1, expected_operation_type=2, attention_seconds=120)))
    assert result["status"] == "prepared" and not result["job_started"]
    assert not result["model_saved"] and result["execution_module"] == "scripts.sw_cam_jobs"
    config = result["config"]
    assert set(config) == jobs._CONFIG_FIELDS
    assert config == {
        "addin_clsid": CLSID, "expected_document_path": context.document,
        "expected_feature_count": 3, "expected_operation_count": 2, "expected_operation_setup_count": 1,
        "setup_index": 0, "operation_index": 1, "expected_operation_type": 2,
        "qualification_only": True, "message_policy": "vendor_default", "attention_seconds": 120,
        "process_id": 731, "process_create_time": 1720000000.25,
        "typelib_path": str(context.dll.parent / "camworks.tlb"),
    }
    assert jobs._validate_config(config) == config
    context.inspect.assert_called_once_with(context.sw, CLSID, str(context.dll.parent / "camworks.tlb"))
    context.identity.assert_called_once_with(731)
    context.connect.assert_called_once_with(wait_seconds=1)
    context.start.assert_not_called()
    context.status.assert_not_called()
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("field", ["process_id", "process_create_time", "typelib_path", "job_directory"])
def test_caller_cannot_override_registry_or_process_identity(context, field):
    with pytest.raises(ValueError):
        inputs(context, **{field: "untrusted-input"})
    assert context.runners == []
    context.start.assert_not_called()


@pytest.mark.parametrize("field", ["expected_feature_count", "expected_operation_count",
    "expected_operation_setup_count", "setup_index", "operation_index", "expected_operation_type", "attention_seconds"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_counts_and_selector_fields_require_real_integers(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})
    context.inspect.assert_not_called()
    context.start.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("expected_feature_count", 0), ("expected_feature_count", 262145),
    ("expected_operation_count", 0), ("expected_operation_count", 513),
    ("expected_operation_setup_count", 0), ("expected_operation_setup_count", 513),
    ("setup_index", -1), ("setup_index", 512), ("operation_index", -1), ("operation_index", 512),
    ("expected_operation_type", 0), ("expected_operation_type", 17),
    ("attention_seconds", 4), ("attention_seconds", 3601),
])
def test_bounds_are_enforced_before_native_access(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})
    assert context.runners == []


@pytest.mark.parametrize("value", [False, 0, 1, "true", None])
def test_only_explicit_boolean_qualification_is_accepted(context, value):
    with pytest.raises(ValueError):
        inputs(context, qualification_only=value)


@pytest.mark.parametrize("value", ["approve", "cancel", "default", "", None])
def test_only_documented_message_policy_accepted(context, value):
    with pytest.raises(ValueError):
        inputs(context, message_policy=value)


@pytest.mark.parametrize("field", ["expected_document_path", "expected_feature_count", "expected_operation_count",
    "expected_operation_setup_count", "setup_index", "operation_index", "expected_operation_type",
    "qualification_only", "message_policy"])
def test_required_preconditions_cannot_be_omitted(context, field):
    values = inputs(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamToolpathInput(**values)


@pytest.mark.parametrize("failure", ["unbound", "unknown_clsid", "registry_error", "wrong_document", "wrong_version"])
def test_prepare_target_guards_block_cam_inspection(context, monkeypatch, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_clsid": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "registry_error": context.installation["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document": context.model.GetPathName = str(Path(context.document).with_name("production.sldprt"))
    else: context.sw.RevisionNumber = "33.0.0"
    result = json.loads(server.solidworks_cam_prepare_toolpath_job(inputs(context, **changes)))
    assert result["status"] == "error"
    context.inspect.assert_not_called()
    context.start.assert_not_called()


@pytest.mark.parametrize("identity", [{"alive": False, "create_time": 1720000000.25},
    {"alive": None, "create_time": None}, {"alive": True, "create_time": None}])
def test_process_lifetime_must_be_verified(context, identity):
    context.identity.return_value = identity
    result = json.loads(server.solidworks_cam_prepare_toolpath_job(inputs(context)))
    assert result["status"] == "error"
    context.inspect.assert_not_called()
    context.start.assert_not_called()


@pytest.mark.parametrize("change", [
    {"expected_feature_count": 4}, {"expected_operation_count": 3}, {"expected_operation_setup_count": 2},
    {"setup_index": 1}, {"operation_index": 3}, {"expected_operation_type": 7},
])
def test_prepare_requires_exact_live_inventory_and_operation(context, change):
    result = json.loads(server.solidworks_cam_prepare_toolpath_job(inputs(context, **change)))
    assert result["status"] == "error" and "config" not in result
    context.start.assert_not_called()


@pytest.mark.parametrize("failure", ["dirty", "already_generated", "inspection_error"])
def test_prepare_refuses_dirty_generated_or_failed_inspection(context, failure):
    if failure == "dirty": context.observed["document_before"]["needs_save"] = True
    elif failure == "already_generated": context.observed["inventory"]["operations"][0]["toolpath_generated"] = True
    else: context.observed.update(status="error", reason="CAM_INSPECTION_FAILED")
    result = json.loads(server.solidworks_cam_prepare_toolpath_job(inputs(context)))
    assert result["status"] == "error" and "config" not in result
    context.start.assert_not_called()


def test_status_reads_receipt_without_com_mutex_or_bound_pid(context, monkeypatch):
    lock = Mock(side_effect=AssertionError("status must not take the CAD lock"))
    monkeypatch.setattr(server, "_run_locked", lock)
    monkeypatch.setattr(server, "_selected_process_id", None)
    result = json.loads(server.solidworks_cam_job_status(server.SolidWorksCamJobStatusInput(job_directory=context.directory)))
    assert result["status"] == "pending" and not result["may_continue"]
    context.status.assert_called_once_with(context.directory)
    lock.assert_not_called()
    context.connect.assert_not_called()
    context.identity.assert_not_called()
    context.inspect.assert_not_called()
    context.discover.assert_not_called()
    context.start.assert_not_called()


def test_status_failure_is_reported_without_fallback_to_cam(context, monkeypatch):
    lock = Mock(side_effect=AssertionError("no mutex"))
    monkeypatch.setattr(server, "_run_locked", lock)
    context.status.side_effect = FileNotFoundError("receipt does not exist")
    result = json.loads(server.solidworks_cam_job_status(server.SolidWorksCamJobStatusInput(job_directory=context.directory)))
    assert result["status"] == "error"
    lock.assert_not_called()
    context.connect.assert_not_called()
    context.start.assert_not_called()


@pytest.mark.parametrize("tool", [PREPARE, STATUS])
def test_explicit_response_format_forwarded(context, tool):
    if tool == PREPARE:
        params = inputs(context, response_format="markdown")
    else:
        params = server.SolidWorksCamJobStatusInput(job_directory=context.directory, response_format="markdown")
    result = getattr(server, tool)(params)
    assert result.startswith("# ")
    if tool == PREPARE:
        assert context.runners[0]["format"] == server.ResponseFormat.MARKDOWN
    else:
        assert context.runners == []
