"""整文档 CAM 几何导出的严格输入、目标门禁和路由；不连接 CAD。"""
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
from scripts import sw_cam_installation  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
TOOL = "solidworks_cam_export_geometry"


@pytest.fixture
def context(tmp_path, monkeypatch):
    """保留真实 _cam_target，替换注册表、连接和仿真核心。"""
    dll = tmp_path / "registered.dll"
    dll.write_bytes(b"fixture; never loaded")
    document = str(tmp_path / "calibration.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="calibration.sldprt", GetType=1)
    sw = SimpleNamespace(ActiveDoc=model, RevisionNumber="34.1.0")
    inventory = {
        "errors": [],
        "addin_registrations": [{"clsid": CLSID,
            "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}"}],
        "com_registrations": [{"clsid": CLSID, "view": "64", "progid": "Fixture.CAM",
            "servers": [{"kind": "inproc", "path": str(dll), "exists": True}]}],
    }
    run = Mock(return_value={"status": "review_required", "reason": "SIMULATION_OUTPUTS_REQUIRE_REVIEW",
                            "export_files_verified": True, "may_continue": False})
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_simulation", SimpleNamespace(export_geometry=run))
    discovery = Mock(return_value=inventory)
    connect = Mock(return_value=(sw, model))
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
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discovery)
    return SimpleNamespace(dll=dll, document=document, model=model, sw=sw, inventory=inventory,
                           run=run, discovery=discovery, connect=connect, runners=runners,
                           output_dir=str(tmp_path / "new-simulation"))


def inputs(context, **changes):
    """明确同意整份试件仿真并传入已观察到的数量。"""
    values = {"addin_clsid": CLSID, "expected_document_path": context.document,
              "expected_feature_count": 3, "expected_operation_count": 5,
              "expected_operation_setup_count": 1, "expected_generated_operation_count": 2,
              "output_dir": context.output_dir, "qualification_only": True,
              "acknowledge_document_wide_export": True, "message_policy": "vendor_default"}
    values.update(changes)
    return server.SolidWorksCamExportGeometryInput(**values)


def test_tool_schema_declares_document_wide_scope_and_required_fields():
    tool = server.mcp._tool_manager._tools[TOOL]
    assert "Document-Wide" in tool.title
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False
    schema = server.SolidWorksCamExportGeometryInput.model_json_schema()
    assert set(schema["required"]) == {
        "addin_clsid", "expected_document_path", "expected_feature_count", "expected_operation_count",
        "expected_operation_setup_count", "expected_generated_operation_count", "output_dir",
        "qualification_only", "acknowledge_document_wide_export", "message_policy",
    }
    assert schema["properties"]["response_format"]["default"] == "json"
    assert "setup_index" not in schema["properties"]
    assert "operation_index" not in schema["properties"]


@pytest.mark.parametrize("export_kinds", [None, ["stock"], ["target", "stock"]])
def test_routes_registered_typelib_and_all_explicit_arguments_inside_lock(context, export_kinds):
    changes = {} if export_kinds is None else {"export_kinds": export_kinds}
    expected_kinds = ["wip"] if export_kinds is None else export_kinds
    result = json.loads(server.solidworks_cam_export_geometry(inputs(context, **changes)))
    assert result == context.run.return_value
    assert result["may_continue"] is False
    context.run.assert_called_once_with(
        context.sw, CLSID, str(context.dll.parent / "camworks.tlb"),
        expected_document_path=context.document, expected_feature_count=3,
        expected_operation_count=5, expected_operation_setup_count=1,
        expected_generated_operation_count=2, output_dir=context.output_dir,
        qualification_only=True, acknowledge_document_wide_export=True,
        message_policy="vendor_default", export_kinds=expected_kinds,
    )
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    assert not Path(context.output_dir).exists()


def test_response_format_is_forwarded_to_existing_runner(context):
    result = server.solidworks_cam_export_geometry(inputs(context, response_format="markdown"))
    assert result.startswith("# review_required")
    assert context.runners == [{"format": server.ResponseFormat.MARKDOWN, "automation": True}]


@pytest.mark.parametrize("field", ["expected_feature_count", "expected_operation_count",
                                   "expected_operation_setup_count", "expected_generated_operation_count"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, -1, 0])
def test_counts_reject_coercion_and_nonpositive_values(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})
    context.run.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field,maximum", [("expected_feature_count", 262144),
    ("expected_operation_count", 512), ("expected_operation_setup_count", 512),
    ("expected_generated_operation_count", 512)])
def test_count_upper_bounds_are_exact(context, field, maximum):
    assert getattr(inputs(context, **{field: maximum}), field) == maximum
    with pytest.raises(ValueError):
        inputs(context, **{field: maximum + 1})


@pytest.mark.parametrize("field", ["qualification_only", "acknowledge_document_wide_export"])
@pytest.mark.parametrize("value", [False, 0, 1, 1.0, None, "true", "false"])
def test_document_wide_qualification_acknowledgements_require_literal_true(context, field, value):
    with pytest.raises(ValueError):
        inputs(context, **{field: value})
    context.run.assert_not_called()


@pytest.mark.parametrize("value", ["cancel", "auto_yes", "default", "", None])
def test_message_policy_has_no_implicit_response_choices(context, value):
    with pytest.raises(ValueError):
        inputs(context, message_policy=value)


@pytest.mark.parametrize("field", ["expected_document_path", "expected_feature_count",
    "expected_operation_count", "expected_operation_setup_count", "expected_generated_operation_count",
    "output_dir", "qualification_only", "acknowledge_document_wide_export", "message_policy"])
def test_required_fields_cannot_be_omitted(context, field):
    values = inputs(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamExportGeometryInput(**values)


@pytest.mark.parametrize("value", [None, "", "relative.sldprt", True, 123])
def test_document_path_must_be_explicit_absolute_string(context, value):
    with pytest.raises(ValueError):
        inputs(context, expected_document_path=value)
    context.run.assert_not_called()


@pytest.mark.parametrize("value", [None, "", "relative-output", True, 123])
def test_output_requires_absolute_string(context, value):
    with pytest.raises(ValueError):
        inputs(context, output_dir=value)
    context.run.assert_not_called()


@pytest.mark.parametrize("kind", ["directory", "file", "missing_parent"])
def test_output_must_be_new_with_existing_parent(context, kind):
    path = Path(context.output_dir)
    if kind == "directory":
        path.mkdir()
    elif kind == "file":
        path.write_text("previous evidence", encoding="utf-8")
    else:
        path = path / "missing-parent" / "new"
    with pytest.raises(ValueError):
        inputs(context, output_dir=str(path))
    context.run.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("field", ["setup_index", "operation_index", "start_solidworks", "save_model", "generate_toolpaths"])
def test_unexposed_selection_and_downstream_actions_are_rejected(context, field):
    with pytest.raises(ValueError):
        inputs(context, **{field: 1})
    context.run.assert_not_called()


@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_existing_target_guards_prevent_simulation(context, monkeypatch, failure):
    changes = {}
    if failure == "unbound":
        monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration":
        changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error":
        context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document":
        context.model.GetPathName = str(Path(context.document).with_name("foreign.sldprt"))
    else:
        context.sw.RevisionNumber = "33.1.0"
    result = json.loads(server.solidworks_cam_export_geometry(inputs(context, **changes)))
    assert result["status"] == "error"
    context.run.assert_not_called()
    if failure not in {"wrong_document", "wrong_version"}:
        context.connect.assert_not_called()


def test_core_error_preserves_existing_structured_failure_contract(context):
    context.run.side_effect = RuntimeError("simulation preflight rejected dirty document")
    result = json.loads(server.solidworks_cam_export_geometry(inputs(context)))
    assert result["status"] == "error"
    assert result["error_type"] == "RuntimeError"
    assert "dirty document" in result["message"]

@pytest.mark.parametrize("path", [r"\\fixture-server\share\new-output", r"\\?\UNC\fixture-server\share\new-output"])
def test_direct_unc_is_rejected_before_filesystem_or_core_access(context, monkeypatch, path):
    """仅解析合成 UNC 字符串，不访问网络共享。"""
    from pathlib import PureWindowsPath
    monkeypatch.setattr(server, "Path", PureWindowsPath)
    with pytest.raises(ValueError, match="local"):
        inputs(context, output_dir=path)
    context.run.assert_not_called()
    assert context.runners == []


def test_mapped_drive_resolving_to_unc_is_rejected(context, monkeypatch):
    """模拟本地外观映射盘，规范化后为 UNC 时必须拒绝。"""
    from pathlib import PureWindowsPath
    original = Path.resolve
    target = Path(context.output_dir)

    def resolved(path, *args, **kwargs):
        if path == target:
            return PureWindowsPath(r"\\fixture-server\share\new-output")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolved)
    with pytest.raises(ValueError, match="canonical UNC"):
        inputs(context)
    context.run.assert_not_called()
    assert context.runners == []


def test_local_canonical_check_preserves_explicit_native_output_path(context, monkeypatch):
    """规范路径只作边界校验，不替换调用者传给原生 API 的路径。"""
    original = Path.resolve
    target = Path(context.output_dir)
    canonical = target.with_name("canonical-local-output")

    def resolved(path, *args, **kwargs):
        return canonical if path == target else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolved)
    params = inputs(context)
    assert params.output_dir == context.output_dir
    server.solidworks_cam_export_geometry(params)
    assert context.run.call_args.kwargs["output_dir"] == context.output_dir


@pytest.mark.skipif(sys.platform != "win32", reason="Windows extended local path")
def test_extended_local_drive_path_is_not_misclassified_as_unc(context):
    value = "\\\\?\\" + context.output_dir
    assert inputs(context, output_dir=value).output_dir == value


def test_simulation_acknowledgement_cannot_authorize_geometry_export(context):
    values = inputs(context).model_dump()
    del values["acknowledge_document_wide_export"]
    values["acknowledge_document_wide_simulation"] = True
    with pytest.raises(ValueError):
        server.SolidWorksCamExportGeometryInput(**values)
    context.run.assert_not_called()


def test_protocol_validator_requires_geometry_export():
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert TOOL in REQUIRED_TOOLS

@pytest.mark.parametrize("value", [None, "wip", True, False, 1, ("wip",), {"wip"}, [],
    ["wip", "wip"], ["stock", "target", "stock"], ["wip", "stock", "target", "wip"],
    [True], [None], [1], ["WIP"], ["unknown"], ["wip", " stock"]])
def test_export_selection_rejects_coercion_duplicates_and_unsupported_values(context, value):
    with pytest.raises(ValueError):
        inputs(context, export_kinds=value)
    context.run.assert_not_called()
    assert context.runners == []


def test_export_default_is_only_wip_and_list_defaults_are_independent(context):
    first = inputs(context)
    assert first.export_kinds == ["wip"]
    first.export_kinds.append("stock")
    assert inputs(context).export_kinds == ["wip"]
    schema = server.SolidWorksCamExportGeometryInput.model_json_schema()
    assert "export_kinds" not in schema["required"]


def test_explicit_all_export_kinds_preserve_order(context):
    order = ["target", "wip", "stock"]
    params = inputs(context, export_kinds=order)
    assert params.export_kinds == order
    server.solidworks_cam_export_geometry(params)
    assert context.run.call_args.kwargs["export_kinds"] == order
