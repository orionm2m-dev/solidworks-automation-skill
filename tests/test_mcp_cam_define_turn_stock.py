"""显式原生车削棒料定义 MCP 的严格输入、路由与目标门禁；不连接真实 CAD。"""
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
from scripts import sw_cam_generation as generation, sw_cam_installation  # noqa: E402

CLSID = "{00000000-0000-0000-0000-000000000001}"
TOOL = "solidworks_cam_define_turn_stock"


@pytest.fixture
def context(tmp_path, monkeypatch):
    """保留真实目标门禁，替换注册表、连接和只读核心。"""
    dll = tmp_path / "registered.dll"
    dll.write_bytes(b"fixture; never loaded")
    document = str(tmp_path / "qualification.sldprt")
    model = SimpleNamespace(GetPathName=document, GetTitle="qualification.sldprt", GetType=1)
    sw = SimpleNamespace(ActiveDoc=model, RevisionNumber="34.1.0")
    inventory = {"errors": [],
        "addin_registrations": [{"clsid": CLSID,
            "registry_key": rf"SOFTWARE\SOLIDWORKS\SOLIDWORKS 2026\AddIns\{CLSID}"}],
        "com_registrations": [{"clsid": CLSID, "view": "64", "progid": "Fixture.CAM",
            "servers": [{"kind": "inproc", "path": str(dll), "exists": True}]}]}
    inspect = Mock(return_value={"status": "review_required", "native_error_code": 0, "may_continue": False})
    connect = Mock(return_value=(sw, model))
    discovery = Mock(return_value=inventory)
    forbidden = Mock(side_effect=AssertionError("No operation generation in stock inspection"))
    runners = []

    def locked(operation, response_format, load_automation=True, **kwargs):
        runners.append({"format": response_format, "automation": load_automation})
        try:
            return server._result(operation(), response_format)
        except Exception as exc:
            return server._tool_error(exc, response_format)

    monkeypatch.setattr(server, "_run_locked", locked)
    monkeypatch.setattr(server, "_selected_process_id", 731)
    monkeypatch.setattr(server, "connect_solidworks", connect)
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: getattr(obj, name), raising=False)
    monkeypatch.setattr(sw_cam_installation, "discover_cam_installations", discovery)
    monkeypatch.setattr(generation, "define_turn_stock", inspect, raising=False)
    monkeypatch.setattr(generation, "run_qualification_step", forbidden)
    yield SimpleNamespace(dll=dll, document=document, model=model, sw=sw, inventory=inventory,
                          inspect=inspect, connect=connect, discovery=discovery, runners=runners, receipt=str(tmp_path / "new-stock-receipt.json"))
    forbidden.assert_not_called()


EXPECTED = {"startZ": 1, "length": 12.5, "odOff": 3, "idOff": 0, "attribute": 0}
NEW = {"startZ": -4.0, "length": 15, "odOff": 40.5, "idOff": 0, "attribute": 1}


def inputs(context, **changes):
    values = {"addin_clsid": CLSID, "expected_document_path": context.document,
              "expected_bar_parameters_native": dict(EXPECTED), "bar_parameters_native": dict(NEW),
              "receipt_path": context.receipt, "qualification_only": True, "message_policy": "vendor_default"}
    values.update(changes)
    return server.SolidWorksCamDefineTurnStockInput(**values)


def test_tool_is_explicit_mutation_and_protocol_validation_requires_it():
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    schema = server.SolidWorksCamDefineTurnStockInput.model_json_schema()
    assert set(schema["required"]) == {"addin_clsid", "expected_document_path",
        "expected_bar_parameters_native", "bar_parameters_native", "receipt_path",
        "qualification_only", "message_policy"}
    assert schema["properties"]["response_format"]["default"] == "json"
    from scripts.validate_mcp import REQUIRED_TOOLS
    assert TOOL in REQUIRED_TOOLS


@pytest.mark.parametrize("attribute", [1, 2])
def test_routes_exact_raw_parameters_under_target_guard_without_unit_conversion(context, attribute):
    new = dict(NEW, attribute=attribute)
    result = json.loads(server.solidworks_cam_define_turn_stock(inputs(context, bar_parameters_native=new)))
    assert result == context.inspect.return_value and result["native_error_code"] == 0
    context.inspect.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"), expected_document_path=context.document,
        expected_bar_parameters_native=EXPECTED, bar_parameters_native=new,
        receipt_path=context.receipt, qualification_only=True, message_policy="vendor_default")
    context.connect.assert_called_once_with(wait_seconds=1)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    assert not Path(context.receipt).exists()


@pytest.mark.parametrize("group", ["expected_bar_parameters_native", "bar_parameters_native"])
@pytest.mark.parametrize("field", ["startZ", "length", "odOff", "idOff"])
@pytest.mark.parametrize("value", [True, False, "1", None, float("nan"), float("inf"), -float("inf")])
def test_raw_parameters_reject_non_json_numbers_and_nonfinite_values(context, group, field, value):
    values = dict(EXPECTED if group.startswith("expected") else NEW)
    values[field] = value
    with pytest.raises(ValueError):
        inputs(context, **{group: values})
    context.inspect.assert_not_called()
    assert context.runners == []


def test_raw_numbers_reject_non_json_numeric_objects_and_double_overflow(context):
    from decimal import Decimal
    for value in (Decimal("1.0"), 10 ** 400):
        with pytest.raises(ValueError):
            inputs(context, bar_parameters_native=dict(NEW, length=value))
    context.inspect.assert_not_called()


@pytest.mark.parametrize("group", ["expected_bar_parameters_native", "bar_parameters_native"])
@pytest.mark.parametrize("value", [True, False, "1", 1.0, -1, 3, None])
def test_attributes_are_strict_known_integer_enums(context, group, value):
    values = dict(EXPECTED if group.startswith("expected") else NEW, attribute=value)
    with pytest.raises(ValueError):
        inputs(context, **{group: values})
    context.inspect.assert_not_called()


def test_unknown_is_allowed_only_for_expected_attribute(context):
    assert inputs(context).expected_bar_parameters_native.attribute == 0
    with pytest.raises(ValueError, match="SOLID"):
        inputs(context, bar_parameters_native=dict(NEW, attribute=0))


@pytest.mark.parametrize("group", ["expected_bar_parameters_native", "bar_parameters_native"])
@pytest.mark.parametrize("field", ["startZ", "length", "odOff", "idOff", "attribute"])
def test_nested_native_objects_require_every_exact_key(context, group, field):
    values = dict(EXPECTED if group.startswith("expected") else NEW)
    del values[field]
    with pytest.raises(ValueError):
        inputs(context, **{group: values})


@pytest.mark.parametrize("group", ["expected_bar_parameters_native", "bar_parameters_native"])
def test_nested_native_objects_reject_extra_or_misnamed_fields(context, group):
    values = dict(EXPECTED if group.startswith("expected") else NEW, diameter_mm=50)
    with pytest.raises(ValueError):
        inputs(context, **{group: values})


@pytest.mark.parametrize("value", [False, 0, 1, 1.0, "true", None])
def test_qualification_requires_literal_true(context, value):
    with pytest.raises(ValueError):
        inputs(context, qualification_only=value)
    context.inspect.assert_not_called()


@pytest.mark.parametrize("value", ["auto_yes", "cancel", None])
def test_only_vendor_default_message_policy_is_accepted(context, value):
    with pytest.raises(ValueError):
        inputs(context, message_policy=value)


@pytest.mark.parametrize("value", ["relative.sldprt", "", None, 1, True])
def test_saved_part_path_is_required_strict_absolute(context, value):
    with pytest.raises(ValueError):
        inputs(context, expected_document_path=value)


def test_saved_part_extension_is_required(context):
    with pytest.raises(ValueError):
        inputs(context, expected_document_path=str(Path(context.document).with_suffix(".sldasm")))


@pytest.mark.parametrize("case", ["relative", "wrong_suffix", "existing_file", "existing_directory", "missing_parent", "coercion"])
def test_receipt_is_new_absolute_json_with_existing_parent(context, case):
    path = Path(context.receipt)
    value = str(path)
    if case == "relative": value = "relative.json"
    elif case == "wrong_suffix": value = str(path.with_suffix(".txt"))
    elif case == "existing_file": path.write_text("previous receipt", encoding="utf-8")
    elif case == "existing_directory": path.mkdir()
    elif case == "missing_parent": value = str(path.parent / "missing" / "receipt.json")
    else: value = 123
    with pytest.raises(ValueError):
        inputs(context, receipt_path=value)
    context.inspect.assert_not_called()


@pytest.mark.parametrize("field", ["expected_document_path", "expected_bar_parameters_native", "bar_parameters_native",
                                    "receipt_path", "qualification_only", "message_policy"])
def test_safety_fields_cannot_be_omitted(context, field):
    values = inputs(context).model_dump()
    del values[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamDefineTurnStockInput(**values)


@pytest.mark.parametrize("failure", ["unbound", "unknown_registration", "discovery_error", "wrong_document", "wrong_version"])
def test_target_guard_blocks_native_setter_before_core(context, monkeypatch, failure):
    changes = {}
    if failure == "unbound": monkeypatch.setattr(server, "_selected_process_id", None)
    elif failure == "unknown_registration": changes["addin_clsid"] = "{00000000-0000-0000-0000-000000000002}"
    elif failure == "discovery_error": context.inventory["errors"] = [{"stage": "registry"}]
    elif failure == "wrong_document": context.model.GetPathName = str(Path(context.document).with_name("other.sldprt"))
    else: context.sw.RevisionNumber = "33.1.0"
    result = json.loads(server.solidworks_cam_define_turn_stock(inputs(context, **changes)))
    assert result["status"] == "error"
    context.inspect.assert_not_called()
    if failure not in {"wrong_document", "wrong_version"}: context.connect.assert_not_called()


def test_core_exception_and_response_format_use_existing_runner(context):
    context.inspect.side_effect = RuntimeError("bar precondition changed")
    result = server.solidworks_cam_define_turn_stock(inputs(context, response_format="markdown"))
    assert result.startswith("# error") and "bar precondition changed" in result
    assert context.runners == [{"format": server.ResponseFormat.MARKDOWN, "automation": True}]


@pytest.mark.parametrize("field", ["generate_toolpaths", "save_model", "recognize_features", "coordinate_system"])
def test_unexposed_downstream_or_frame_mutations_are_rejected(context, field):
    with pytest.raises(ValueError):
        inputs(context, **{field: True})
    context.inspect.assert_not_called()
