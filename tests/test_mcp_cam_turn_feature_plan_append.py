"""Guarded append-only feature-plan public schema and routing; no native application calls."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_mcp_cam_operation_diagnostics import CLSID, context, server
from scripts import sw_cam_turn_feature_plan_append as cam

TOOL = "solidworks_cam_qualify_turn_feature_plan_append"
RECIPE_FIELDS = {"protected_part_pins", "action", "expected_state_sha256", "receipt_path",
                 "qualification_only", "message_policy"}
TRANSPORT_FIELDS = {"addin_clsid", "expected_document_title", "response_format"}
SETUP_IDS = ("expected_feature_setup_native_id", "expected_operation_setup_native_id")
COPY_IDS = ("target_feature_setup_native_id", "target_operation_setup_native_id",
            "expected_source_feature_native_id", "expected_copied_feature_native_id")
NATIVE_IDS = SETUP_IDS + COPY_IDS
COUNT_FIELDS = ("expected_feature_count", "expected_operation_count", "expected_feature_setup_count",
                "expected_operation_setup_count", "expected_generated_operation_count", "expected_toolpath_record_count")


@pytest.fixture
def native(context, monkeypatch):
    result = Mock(return_value={"status": "prepared", "native_mutation_attempted": False})
    monkeypatch.setattr(cam, "qualify_turn_feature_plan_append", result)
    monkeypatch.setattr(server, "_runtime_identity", SimpleNamespace(assert_current=Mock()))
    return result


def values(context, tmp_path, **changes):
    body = b"saved qualification part fixture"
    Path(context.document).write_bytes(body)
    archive = tmp_path / "protected_archive.sldprt"
    original = tmp_path / "protected_original.sldprt"
    archive.write_bytes(body)
    original.write_bytes(b"protected original fixture")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    result = dict(addin_clsid=CLSID, process_id=731, expected_process_create_time=100.25,
        expected_document_path=context.document, expected_source_sha256=digest(archive),
        setup_index=0, operation_index=0, expected_operation_type=6,
        expected_operation_native_id=19, expected_linked_feature_ids=[23],
        expected_feature_count=3, expected_operation_count=8,
        expected_feature_setup_count=2, expected_operation_setup_count=2,
        expected_generated_operation_count=2, expected_toolpath_record_count=40,
        expected_feature_setup_native_id=43, expected_operation_setup_native_id=44,
        target_feature_setup_native_id=57, target_operation_setup_native_id=58,
        expected_source_feature_native_id=23, expected_copied_feature_native_id=59,
        expected_copied_feature_sha256="cd"*32, expected_new_operation_types=[14,9,5,6],
        protected_part_pins=[dict(path=str(archive), sha256=digest(archive)),
                             dict(path=str(original), sha256=digest(original))],
        qualification_only=True, message_policy="vendor_default")
    result.update(changes)
    return result


def params(context, tmp_path, **changes):
    return server.SolidWorksCamTurnFeaturePlanAppendInput(**values(context, tmp_path, **changes))


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_exact_request_routes_every_reader_pin_and_recipe_under_lock(context, native, tmp_path, action):
    extra = {} if action == "prepare" else dict(expected_state_sha256="bc" * 32,
                                               receipt_path=str(tmp_path / "receipt.json"))
    request = params(context, tmp_path, action=action, **extra)
    result = json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(request))
    assert result == native.return_value
    native.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"),
        **request.model_dump(exclude=TRANSPORT_FIELDS))
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]
    assert server._runtime_identity.assert_current.call_count == 2


def test_schema_has_distinct_destructive_nonidempotent_route(context, native, tmp_path):
    tool = server.mcp._tool_manager._tools[TOOL]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False
    schema = tool.parameters
    model = schema.get("$defs", {}).get("SolidWorksCamTurnFeaturePlanAppendInput", schema)
    assert set(NATIVE_IDS) | {"qualification_only", "message_policy", "protected_part_pins"} <= set(model["required"])
    assert set(COUNT_FIELDS) | set(NATIVE_IDS) | RECIPE_FIELDS <= model["properties"].keys()
    assert not {"copy_source_path", "copy_source_sha256", "direction", "transform_values", "save",
                "retry", "generate_toolpath", "relocate_operations", "pAfter",
                "bMakeCopy", "bCloneOperation", "null_anchor"} & model["properties"].keys()
    assert params(context, tmp_path).action == "prepare"


def test_schema_delegates_pure_request_validation_with_exact_config(context, native, tmp_path, monkeypatch):
    validation = Mock(wraps=cam.validate_request)
    monkeypatch.setattr(cam, "validate_request", validation)
    request = params(context, tmp_path)
    validation.assert_called_once_with(request.model_dump(exclude=TRANSPORT_FIELDS | RECIPE_FIELDS),
        request.protected_part_pins, request.action, request.expected_state_sha256,
        request.receipt_path, request.qualification_only, request.message_policy)
    assert set(COUNT_FIELDS) | set(NATIVE_IDS) <= validation.call_args.args[0].keys()
    context.connect.assert_not_called()
    native.assert_not_called()


@pytest.mark.parametrize("field", [*NATIVE_IDS, "process_id", "expected_process_create_time",
    "expected_document_path", "expected_source_sha256", "expected_operation_native_id",
    "expected_linked_feature_ids", "expected_copied_feature_sha256", "expected_new_operation_types", *COUNT_FIELDS, "protected_part_pins", "qualification_only", "message_policy"])
def test_required_pins_and_acknowledgements_cannot_be_omitted(context, native, tmp_path, field):
    request = values(context, tmp_path)
    del request[field]
    with pytest.raises(ValueError):
        server.SolidWorksCamTurnFeaturePlanAppendInput(**request)
    native.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field", NATIVE_IDS)
@pytest.mark.parametrize("value", [None, True, False, 1., "1", 0, -1, 2**32])
def test_source_and_setup_ids_are_required_strict_positive_ulong(context, native, tmp_path, field, value):
    with pytest.raises(ValueError):
        params(context, tmp_path, **{field: value})
    native.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("process_id", True), ("expected_process_create_time", True),
    ("expected_process_create_time", float("inf")), ("expected_process_create_time", float("nan")),
    ("expected_process_create_time", 0), ("setup_index", True), ("operation_index", 512),
    ("expected_operation_type", True), ("expected_operation_type", 6.), ("expected_operation_type", 7),
    ("expected_operation_native_id", True), ("expected_linked_feature_ids", [True]),
    ("expected_linked_feature_ids", [23, 23]), ("expected_feature_count", "3"),
    ("expected_generated_operation_count", True), ("expected_toolpath_record_count", -1),
    ("expected_document_path", "relative.sldprt"), ("expected_source_sha256", "X" * 64),
    ("qualification_only", False), ("qualification_only", 1), ("qualification_only", "true"),
    ("qualification_only", None), ("message_policy", "accept"), ("message_policy", None),
    ("action", "read"), ("action", "identify"), ("action", "retry"), ("action", True),
    ("protected_part_pins", []), ("protected_part_pins", [{}]),
    ("expected_state_sha256", "bc" * 32), ("receipt_path", "receipt.json"),
    ("direction", [0, 0, -1]), ("transform_values", [1, 0, 0]), ("save", True),
    ("retry", True), ("generate_toolpath", True), ("relocate_operations", True),
    ("copy_source_path", "unused.sldprt"), ("native_setup_id", 99),
    ("pAfter", None), ("bMakeCopy", False), ("bCloneOperation", True), ("null_anchor", True),
    ("expected_feature_setup_count", 1), ("expected_operation_setup_count", 1),
    ("target_feature_setup_native_id", 43), ("target_operation_setup_native_id", 44),
    ("expected_source_feature_native_id", 24),
    ("expected_copied_feature_native_id", 23),
    ("expected_copied_feature_sha256", "bad"),
    ("expected_new_operation_types", []), ("expected_new_operation_types", [True]),
    ("expected_new_operation_types", [5.]), ("expected_new_operation_types", ["5"]),
    ("expected_new_operation_types", [5,5]), ("expected_new_operation_types", [12]),
    ("gop_preference", 2), ("attribute_name", "Rough-Finish"),
])
def test_invalid_or_unbounded_request_never_connects(context, native, tmp_path, field, value):
    with pytest.raises(ValueError):
        params(context, tmp_path, **{field: value})
    native.assert_not_called()
    context.connect.assert_not_called()
    assert context.runners == []


@pytest.mark.parametrize("missing", ["expected_state_sha256", "receipt_path"])
def test_apply_requires_both_preparation_hash_and_fresh_receipt(context, native, tmp_path, missing):
    extra = dict(action="apply", expected_state_sha256="bc" * 32, receipt_path=str(tmp_path / "receipt.json"))
    del extra[missing]
    with pytest.raises(ValueError):
        params(context, tmp_path, **extra)
    native.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("count", [1, 17])
def test_protected_pin_list_is_bounded(context, native, tmp_path, count):
    request = values(context, tmp_path)
    request["protected_part_pins"] = [request["protected_part_pins"][0]] * count
    with pytest.raises(ValueError):
        server.SolidWorksCamTurnFeaturePlanAppendInput(**request)
    native.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("pid", [None, True, 732])
def test_process_binding_mismatch_precedes_connection(context, native, tmp_path, monkeypatch, pid):
    monkeypatch.setattr(server, "_selected_process_id", pid)
    result = json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(params(context, tmp_path)))
    assert result["status"] == "error"
    native.assert_not_called()
    context.connect.assert_not_called()


def test_runtime_drift_before_call_stops_connection(context, native, tmp_path):
    server._runtime_identity.assert_current.side_effect = ValueError("runtime changed before qualification")
    result = json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(params(context, tmp_path)))
    assert result["status"] == "error"
    native.assert_not_called()
    context.connect.assert_not_called()
    assert server._runtime_identity.assert_current.call_count == 1


def test_runtime_drift_after_call_revokes_reported_success(context, native, tmp_path):
    server._runtime_identity.assert_current.side_effect = [None, ValueError("runtime changed during qualification")]
    result = json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(params(context, tmp_path)))
    assert result["status"] == "error"
    native.assert_called_once()
    assert server._runtime_identity.assert_current.call_count == 2


@pytest.mark.parametrize("failure", ["wrong_document", "registration"])
def test_existing_target_guard_stops_qualification(context, native, tmp_path, failure):
    if failure == "wrong_document":
        context.model.GetPathName = str(Path(context.document).with_name("other.sldprt"))
    else:
        context.inventory["errors"] = [dict(stage="registry")]
    result = json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(params(context, tmp_path)))
    assert result["status"] == "error"
    native.assert_not_called()


def test_inherited_generated_count_consistency_guard_is_preserved(context, native, tmp_path):
    with pytest.raises(ValueError):
        params(context, tmp_path, expected_operation_count=1, expected_generated_operation_count=2)
    native.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "apply"])
def test_existing_read_only_setup_schema_still_rejects_new_actions(context, native, tmp_path, action):
    request = params(context, tmp_path).model_dump(exclude=RECIPE_FIELDS | set(COPY_IDS) | {"expected_copied_feature_sha256", "expected_new_operation_types"})
    request["action"] = action
    with pytest.raises(ValueError):
        server.SolidWorksCamTurnSetupContextInput(**request)
    native.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("mutated", [False, True])
def test_post_call_runtime_drift_preserves_native_outcome_and_durably_revokes_own_receipt(context, native, tmp_path, mutated):
    from copy import deepcopy
    from scripts.sw_cam_generation import _write_receipt
    receipt = tmp_path / "append_receipt.json"
    request = params(context,tmp_path,action="apply",expected_state_sha256="bc"*32,receipt_path=str(receipt))
    outcome = dict(status="review_required" if mutated else "error", mutation_attempted=mutated,
        native_call_count=int(mutated),native_calls_returned_count=int(mutated),native_dispatch_pending=False,
        readback_verified=mutated,apply_eligible=False,model_saved=False,receipt_created=True,receipt_path=str(receipt),
        captures=[dict(label="after",state=dict(observed_operation_ids=[90,91,92,93]))],
        reason="RAM_ONLY_RESULT",verification=dict(new_operation_native_ids=[90,91,92,93]) if mutated else {})
    def completed(*args,**kwargs):
        _write_receipt(receipt,outcome,create=True)
        return deepcopy(outcome)
    native.side_effect = completed
    server._runtime_identity.assert_current.side_effect = [None,ValueError("runtime changed during qualification")]
    result=json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(request))
    assert result["status"]==("uncertain" if mutated else "error")
    assert result["runtime_identity_changed"] and result["runtime_drift_receipt_updated"]
    assert not result["readback_verified"] and not result["apply_eligible"]
    assert result["mutation_attempted"] is mutated
    for key in ("native_call_count","native_calls_returned_count","native_dispatch_pending","captures","verification"):
        assert result[key]==outcome[key]
    assert result["outcome_before_runtime_check"]["readback_verified"] is mutated
    assert json.loads(receipt.read_text(encoding="utf-8"))==result
    assert native.call_count==1 and server._runtime_identity.assert_current.call_count==2


@pytest.mark.parametrize("ownership", ["not_created","different_path"])
def test_runtime_drift_never_rewrites_a_receipt_not_owned_by_this_invocation(context,native,tmp_path,ownership):
    receipt=tmp_path/"unowned.json"; body=b'{"status":"unrelated_existing_evidence"}'
    receipt.write_bytes(body)
    native.return_value=dict(status="error",mutation_attempted=False,readback_verified=False,
        receipt_created=ownership=="different_path",receipt_path=str(receipt.with_name("other.json") if ownership=="different_path" else receipt))
    server._runtime_identity.assert_current.side_effect=[None,ValueError("runtime drift")]
    result=json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(params(context,tmp_path,
        action="apply",expected_state_sha256="bc"*32,receipt_path=str(receipt))))
    assert result["status"]=="error" and not result["readback_verified"] and not result["runtime_drift_receipt_updated"]
    assert receipt.read_bytes()==body and not receipt.with_name("other.json").exists()


def test_runtime_drift_receipt_write_failure_is_explicit_and_never_reports_qualification(context,native,tmp_path,monkeypatch):
    from copy import deepcopy
    from scripts import sw_cam_generation as generation
    write=generation._write_receipt
    receipt=tmp_path/"append_receipt.json"
    outcome=dict(status="review_required",mutation_attempted=True,native_call_count=1,native_calls_returned_count=1,
        native_dispatch_pending=False,readback_verified=True,apply_eligible=False,receipt_created=True,receipt_path=str(receipt))
    def completed(*args,**kwargs):
        write(receipt,outcome,create=True)
        return deepcopy(outcome)
    native.side_effect=completed
    def failed(*args,**kwargs): raise OSError("durability unavailable")
    monkeypatch.setattr(generation,"_write_receipt",failed)
    server._runtime_identity.assert_current.side_effect=[None,ValueError("runtime drift")]
    result=json.loads(server.solidworks_cam_qualify_turn_feature_plan_append(params(context,tmp_path,
        action="apply",expected_state_sha256="bc"*32,receipt_path=str(receipt))))
    assert result["status"]=="uncertain" and not result["readback_verified"] and not result["apply_eligible"]
    assert not result["runtime_drift_receipt_updated"] and result["receipt_write_error"]["type"]=="OSError"
    assert result["native_call_count"]==result["native_calls_returned_count"]==1
    assert json.loads(receipt.read_text(encoding="utf-8"))==outcome
    assert native.call_count==1
