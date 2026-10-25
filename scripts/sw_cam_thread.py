"""独立工作副本中的 THREAD 单操作插入资格验证；不配置螺纹、不生成、不保存。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _collection, _context, _inventory, _typed, _write_receipt
from scripts.sw_cam_operation_profile import _integer, _number, _read_profile
from scripts.sw_cam_qualification_context import _catalog
from scripts.sw_cam_turn_tool import _digest, _reference
from scripts.sw_operation_guard import absolute_document_path, check_document_target

_DOUBLE_METHODS = ("GetPitchValue", "GetDepthPerCutValue", "GetLastDepthPerCutValue",
    "GetStartLengthValue", "GetEndLengthValue", "GetEntryAngleValue", "GetWithdrawAngleValue",
    "GetActualPitchValue", "GetLeadinAmtValue", "GetLeadinAngleValue", "GetLeadoutAmtValue",
    "GetLeadoutAngleValue")
_INT_METHODS = ("GetNumFinalPassValue", "GetNumStartThreadsValue", "GetLeadinTypeValue",
    "GetLeadoutTypeValue")
_UNAVAILABLE_THREAD_GETTERS = {
    "GetMinZLimit": {"reason": "observed_CAM_SERVERFAULT", "hresult": -2147417851},
    "GetMaxZTurnMethod": {"reason": "observed_CAM_SERVERFAULT", "hresult": -2147417851},
    **{name: {"reason": "untested_disabled_after_CAM_SERVERFAULT"} for name in (
        "GetMaxZLimit", "GetMinZTurnMethod", "IsMultiStartThread", "GetMaxZUseSetupDefn",
        "GetMinZUseSetupDefn", "CutType_ConstantCutDepth", "InfeedType", "ReverseCut",
        "MirrorAboutCenterline", "Chamfer", "CannedCycleOutput")},
}



def _boolean(value):
    if type(value) is not bool:
        raise ValueError("Native thread flag must be a Boolean")
    return value


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object_id(doc, obj, read):
    value = read(doc, "GetCWObjectID", obj)
    if (not isinstance(value, (tuple, list)) or len(value) != 2 or type(value[1]) is not bool
            or not value[1] or type(value[0]) is not int or not 0 < value[0] <= 4294967295):
        raise ValueError("A positive native CAM object ID with status=true is required")
    return value[0]


def _capture(sw, clsid, typelib_path, selected, linked_feature_index, expected_document_path,
             *, check=lambda: None, diagnostic=None):
    diagnostic = {} if diagnostic is None else diagnostic
    diagnostic["stage"] = "context"
    check()
    before, doc, _part, machine, app = _context(sw, clsid, typelib_path)
    diagnostic["document"] = before
    check_document_target(before["path"], before["title"], expected_path=expected_document_path, required=True)
    doc = _typed(doc, "ICWDoc3", typelib_path)
    def read(obj, name, *args):
        diagnostic["stage"] = name
        check()
        value = _member(obj, name, *args)
        check()
        return value
    diagnostic["stage"] = "inventory"
    inventory = _inventory(machine, typelib_path)
    check()
    diagnostic["inventory"] = inventory
    records, handles = [], {}
    diagnostic["operations"] = records
    feature_total = 0
    setups = _collection(read(machine, "IGetEnumOpSetups"), typelib_path)
    for si, raw_setup in enumerate(setups):
        setup = _typed(raw_setup, "ICWBaseOpSetup", typelib_path)
        for oi, raw in enumerate(_collection(read(setup, "IGetEnumOperations"), typelib_path)):
            if len(records) >= 512:
                raise ValueError("Operation inventory exceeds the qualification limit")
            operation = _typed(raw, "ICWOperation", typelib_path)
            turn = _typed(raw, "ICWTurnOperation", typelib_path)
            native_id = _object_id(doc, operation, read)
            if native_id in handles:
                raise ValueError("Native operation IDs must be unique")
            linked = _collection(read(operation, "IGetAllFeatures"), typelib_path)
            feature_total += len(linked)
            if feature_total > 1024:
                raise ValueError("Operation feature references exceed the qualification limit")
            feature_ids = [_object_id(doc, feature, read) for feature in linked]
            kind = _integer(read(turn, "OpernType"))
            record = {"setup_index": si, "operation_index": oi, "native_id": native_id,
                      "turn_operation_type": kind, "linked_feature_ids": feature_ids}
            records.append(record)
            handles[native_id] = {"raw": raw, "operation": operation, "linked": linked}
    target = next((record for record in records if record["setup_index"] == selected["setup_index"]
        and record["operation_index"] == selected["operation_index"]
        and record["turn_operation_type"] == selected["expected_operation_type"]), None)
    if target is None:
        raise ValueError("Selected insertion-after operation identity/type is absent")
    selected_handle = handles[target["native_id"]]
    linked = selected_handle["linked"]
    if not 0 <= linked_feature_index < len(linked):
        raise ValueError("Selected linked feature index is outside the operation")
    raw_feature = linked[linked_feature_index]
    feature = _typed(raw_feature, "ICWTurnFeature", typelib_path)
    profile, catalog = {}, {}
    diagnostic["selected_profile"] = profile
    diagnostic["catalog"] = catalog
    _read_profile(raw_feature, typelib_path, read, [0], profile)
    _catalog(feature, read, catalog, [0])
    diagnostic["stage"] = "saved_file_hash"
    saved_hash = _file_hash(before["path"])
    check()
    diagnostic["stage"] = "inventory_after_read"
    after_inventory = _inventory(machine, typelib_path)
    check()
    after = document_snapshot(sw)
    check()
    if before != after or inventory != after_inventory:
        raise ValueError("Document or inventory changed during qualification snapshot")
    state = {"document": before, "saved_file_sha256": saved_hash, "inventory": inventory,
        "operations": records, "selected_operation": selected, "selected_operation_id": target["native_id"],
        "linked_feature_index": linked_feature_index,
        "selected_feature_id": target["linked_feature_ids"][linked_feature_index],
        "selected_profile": profile, "thread_catalog": catalog,
        "native_id_scope": "current_document_requires_fresh_prepare_after_reopen"}
    diagnostic["stage"] = "complete"
    return state, {"doc": doc, "app": app, "feature": feature,
                   "after_operation": selected_handle["operation"], "operations": handles}


def _verify_addition(before, after, new_id):
    if type(new_id) is not int or new_id <= 0:
        raise ValueError("Inserted operation must have a positive native ID")
    old_ids = [item["native_id"] for item in before["operations"]]
    if new_id in old_ids:
        raise ValueError("InsertOperation returned a pre-existing native operation")
    rows = after["operations"]
    new = next((item for item in rows if item["native_id"] == new_id), None)
    si = before["selected_operation"]["setup_index"]
    insertion = before["selected_operation"]["operation_index"] + 1
    if (new is None or new["setup_index"] != si or new["operation_index"] != insertion
            or new["turn_operation_type"] != 12 or new["linked_feature_ids"] != [before["selected_feature_id"]]):
        raise ValueError("New THREAD operation is not exactly after the selected operation/on the selected feature")
    expected = deepcopy(before)
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    for item in expected["operations"]:
        if item["setup_index"] == si and item["operation_index"] >= insertion:
            item["operation_index"] += 1
    at = next(i for i, item in enumerate(expected["operations"]) if item["native_id"] == before["selected_operation_id"]) + 1
    expected["operations"].insert(at, deepcopy(new))
    native_new = next((item for item in after["inventory"]["operations"]
        if item["setup_index"] == si and item["operation_index"] == insertion), None)
    if (native_new is None or native_new["turn_operation_type"] != 12 or
            native_new["toolpath_generated"] or native_new["toolpath_record_counts"]):
        raise ValueError("New THREAD operation must not have a generated toolpath")
    expected["inventory"]["operation_count"] += 1
    for item in expected["inventory"]["operations"]:
        if item["setup_index"] == si and item["operation_index"] >= insertion:
            item["operation_index"] += 1
    expected["inventory"]["operations"].insert(at, deepcopy(native_new))
    if expected != after:
        raise ValueError("Insertion changed more than one new THREAD operation or changed existing toolpaths/profile/file")


def _read_thread_operation(raw, doc, typelib_path, read, result):
    result["unavailable_getters"] = deepcopy(_UNAVAILABLE_THREAD_GETTERS)
    result["declared_parameter_count"] = 29
    result["parameter_metadata_complete"] = False
    operation = _typed(raw, "ICWOperation", typelib_path)
    turn = _typed(raw, "ICWTurnOperation", typelib_path)
    result["native_id"] = _object_id(doc, operation, read)
    result["operation_type"] = _integer(read(turn, "OpernType"))
    if result["operation_type"] != 12:
        raise ValueError("Returned operation is not native THREAD type 12")
    result["toolpath_generated"] = _boolean(read(operation, "GetIsToolpathGenerated"))
    if result["toolpath_generated"]:
        raise ValueError("Metadata qualification must not generate a toolpath")
    thread = _typed(raw, "ICWTurnThreadOp", typelib_path)
    values = {}
    result["parameters_native"] = values
    for name in _DOUBLE_METHODS:
        values[name] = _number(read(thread, name))
    for name in _INT_METHODS:
        values[name] = _integer(read(thread, name))
    result["ancillary_metadata"] = {
        "status": "unavailable",
        "reason": "unqualified_THREAD_additional_getters_disabled",
        "IGetTool": {"observed_hresult": -2147220990, "presence_verified": False},
        "linked_profiles_read": False, "tool_read": False, "holder_read": False,
    }
    result["readback_scope"] = "identity_and_16_confirmed_thread_scalars"
    result.update(units_verified=False, thread_span_verified=False, full_thread_depth_verified=False,
                  major_minor_diameters_verified=False, iso_form_verified=False,
                  physical_tool_qualified=False, parameter_metadata_complete=False,
                  supported_parameter_reads_complete=True, read_parameter_count=len(values))


def qualify_thread_operation(sw, clsid, typelib_path, *, expected_document_path,
        setup_index, operation_index, expected_operation_type, linked_feature_index, action,
        qualification_only, message_policy, expected_state_sha256=None, default_name=None,
        expected_default_id=None, receipt_path=None):
    """准备或插入一项 THREAD，仅供新保存的独立工作副本读取默认参数；不生成或保存。"""
    from scripts.sw_cam_events import CamMessageSession
    selected = _reference({"setup_index": setup_index, "operation_index": operation_index,
                           "expected_operation_type": expected_operation_type})
    if action not in {"prepare", "apply"} or qualification_only is not True or message_policy != "vendor_default":
        raise ValueError("Explicit prepare/apply qualification-only/vendor-default policy is required")
    if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("An exact absolute saved qualification part is required")
    if type(linked_feature_index) is not int or not 0 <= linked_feature_index <= 63:
        raise ValueError("linked_feature_index must be a strict integer in [0, 63]")
    receipt = None
    mutation_inputs = (expected_state_sha256, default_name, expected_default_id, receipt_path)
    if action == "prepare":
        if any(value is not None for value in mutation_inputs):
            raise ValueError("Prepare does not accept insertion inputs or a receipt")
    else:
        if (not isinstance(expected_state_sha256, str) or len(expected_state_sha256) != 64 or
                any(char not in "0123456789abcdef" for char in expected_state_sha256)):
            raise ValueError("The exact prepare state SHA-256 is required")
        if not isinstance(default_name, str) or not default_name or len(default_name) > 1000:
            raise ValueError("An exact observed BSTR default name is required")
        if type(expected_default_id) is not int or not 0 < expected_default_id <= 2147483647:
            raise ValueError("Qualification requires an observed positive LONG default ID; no guessed zero")
        receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
        if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json"
                or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink()):
            raise ValueError("A new absolute JSON receipt with an existing parent is required")
    report = {"status": "started", "action": action, "phase": "preflight", "desired_operation_type": 12,
        "mutation_attempted": False, "native_call_returned": False, "insertion_readback_verified": False,
        "generation_attempted": False, "model_saved": False, "may_continue": False,
        "thread_process_qualified": False, "thread_span_verified": False,
        "full_thread_depth_verified": False, "major_minor_diameters_verified": False,
        "units_verified": False, "physical_tool_qualified": False, "snapshot_diagnostics": [],
        "parameter_metadata_complete": False, "metadata_limits": deepcopy(_UNAVAILABLE_THREAD_GETTERS),
        "attempt_marker_meaning": "durable_intent_before_InsertOperation_not_proof_of_entry"}
    if receipt:
        _write_receipt(receipt, report, create=True)
    session = None
    def capture(phase, check=lambda: None):
        diagnostic = {"phase": phase}
        report["snapshot_diagnostics"].append(diagnostic)
        return _capture(sw, clsid, typelib_path, selected, linked_feature_index, expected_document_path,
                        check=check, diagnostic=diagnostic)
    try:
        before, native = capture("initial")
        report["before"] = before
        if before["document"]["needs_save"]:
            raise ValueError("THREAD insertion qualification requires a clean saved working copy")
        if not before["thread_catalog"].get("names_resolved"):
            raise ValueError("Selected feature THREAD catalog shape is not qualified")
        report["state_sha256"] = _digest(before)
        report["feature_profile_sha256"] = _digest(before["selected_profile"])
        report["positive_default_id_policy"] = "client_qualification_bound_not_vendor_failure_sentinel"
        if action == "prepare":
            report.update(status="ok", phase="prepared")
            return report
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Prepared native feature/operation/catalog/file state changed")
        if not any(item["name"] == default_name and item.get("tdb_id_raw") == expected_default_id
                   for item in before["thread_catalog"]["entries"]):
            raise ValueError("Default name/ID does not exactly match the observed selected-feature catalog")
        session = CamMessageSession(native["app"], typelib_path)
        def check_messages():
            summary = session.summary()
            report["messages"] = summary
            if (not summary.get("subscribed") or summary.get("event_count") or summary.get("overflow")
                    or summary.get("callback_errors") or summary.get("callback_error_count")
                    or summary.get("subscription_error") or summary.get("disconnect_errors")):
                raise ValueError("CAM messages require review; no further native calls")
        def read(obj, name, *args):
            report["native_stage"] = name
            check_messages()
            value = _member(obj, name, *args)
            check_messages()
            return value
        with session:
            check_messages()
            current, native = capture("pre_insert", check_messages)
            if current != before:
                raise ValueError("Prepared state changed immediately before insertion")
            report.update(phase="InsertOperation", mutation_attempted=True)
            _write_receipt(receipt, report)
            if document_snapshot(sw) != before["document"]:
                raise ValueError("Document changed before insertion")
            check_messages()
            raw_new = _member(native["feature"], "InsertOperation", 12, expected_default_id, native["after_operation"])
            report.update(native_call_returned=True, phase="InsertOperation_returned",
                          native_result_present=raw_new is not None and bool(raw_new))
            _write_receipt(receipt, report)
            check_messages()
            if not report["native_result_present"]:
                raise ValueError("InsertOperation returned no operation")
            now = document_snapshot(sw)
            if now is None or any(now[key] != before["document"][key] for key in ("path", "title", "type")):
                raise ValueError("Active document changed after insertion")
            new_id = _object_id(native["doc"], raw_new, read)
            report["new_operation_id"] = new_id
            after, after_native = capture("after_insert", check_messages)
            report["after"] = after
            _verify_addition(before, after, new_id)
            report["new_operation"] = {}
            _read_thread_operation(after_native["operations"][new_id]["raw"], after_native["doc"],
                                   typelib_path, read, report["new_operation"])
            report["readback_before_cleanup_verified"] = True
            _write_receipt(receipt, report)
        check_messages()
        if not session.summary().get("disconnected"):
            raise ValueError("CAM event cleanup was not confirmed")
        report["phase"] = "post_cleanup_readback"
        final, final_native = capture("after_cleanup", check_messages)
        report["after_cleanup"] = final
        _verify_addition(before, final, new_id)
        report["new_operation_after_cleanup"] = {}
        _read_thread_operation(final_native["operations"][new_id]["raw"], final_native["doc"],
                               typelib_path, read, report["new_operation_after_cleanup"])
        if report["new_operation"] != report["new_operation_after_cleanup"]:
            raise ValueError("New operation metadata changed during event cleanup")
        # 最后一次 metadata getter 也可能处理 COM 消息，完成标志必须在最终目标/清单核对之后。
        final_check, _native = capture("after_metadata", check_messages)
        report["final_state"] = final_check
        _verify_addition(before, final_check, new_id)
        if final_check != final:
            raise ValueError("Document, plan or saved file changed during the final metadata read")
        report.update(status="review_required", phase="finished", insertion_readback_verified=True,
                      reason="THREAD_INSERTION_WITH_INCOMPLETE_PARAMETER_METADATA_NOT_M60_CONFIGURATION",
                      verification_scope="one_operation_added_existing_toolpaths_and_saved_file_unchanged")
    except Exception as exc:
        diagnostic = report["snapshot_diagnostics"][-1] if report["snapshot_diagnostics"] else {}
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
                      reason="CAM_THREAD_QUALIFICATION_FAILED", failed_phase=report["phase"],
                      failed_stage=report.get("native_stage", diagnostic.get("stage", report["phase"])),
                      issue=_error(exc), phase="finished")
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if receipt:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=_error(exc), insertion_readback_verified=False)
    return report


def inspect_thread_operation(sw, clsid, typelib_path, *, expected_document_path, setup_index,
        operation_index, expected_operation_type, expected_thread_native_id):
    """只读恢复已有 THREAD 的可用默认参数；允许未保存工作副本，不重放插入或保存。

    明确绑定当前文档、操作索引、类型12和正向 native ID。仅读取已确认的16项；
    故障与未验证成员保留为 unavailable，不尝试探测；读取后的文档、清单和文件必须不变。
    """
    report = {"status": "error", "mutation_attempted": False, "generation_attempted": False,
        "model_saved": False, "may_continue": False, "thread_process_qualified": False,
        "parameter_metadata_complete": False, "metadata_limits": deepcopy(_UNAVAILABLE_THREAD_GETTERS)}
    stage = "validate_inputs"
    def read(obj, name, *args):
        nonlocal stage
        stage = name
        return _member(obj, name, *args)
    try:
        _reference({"setup_index": setup_index, "operation_index": operation_index,
                    "expected_operation_type": expected_operation_type})
        if expected_operation_type != 12:
            raise ValueError("Read-only recovery requires native THREAD type 12")
        if type(expected_thread_native_id) is not int or not 0 < expected_thread_native_id <= 4294967295:
            raise ValueError("An exact positive native THREAD operation ID is required")
        if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold() != ".sldprt"):
            raise ValueError("An exact absolute saved working part is required")
        stage = "context"
        before, doc, _part, machine, _app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        check_document_target(before["path"], before["title"], expected_path=expected_document_path, required=True)
        doc = _typed(doc, "ICWDoc3", typelib_path)
        stage = "inventory_before"
        initial = _inventory(machine, typelib_path)
        report["inventory_before"] = initial
        selected = next((item for item in initial["operations"] if item["setup_index"] == setup_index
                         and item["operation_index"] == operation_index), None)
        if selected is None or selected["turn_operation_type"] != 12:
            raise ValueError("Selected inventory operation is not THREAD")
        setups = _collection(read(machine, "IGetEnumOpSetups"), typelib_path)
        setup = _typed(setups[setup_index], "ICWBaseOpSetup", typelib_path)
        operations = _collection(read(setup, "IGetEnumOperations"), typelib_path)
        raw = operations[operation_index]
        operation = _typed(raw, "ICWOperation", typelib_path)
        native_id = _object_id(doc, operation, read)
        report["observed_thread_native_id"] = native_id
        if native_id != expected_thread_native_id:
            raise ValueError("Selected native operation ID differs from the requested existing THREAD")
        stage = "saved_file_hash_before"
        file_before = _file_hash(before["path"])
        report["saved_file_sha256_before"] = file_before
        report["thread_operation"] = {}
        _read_thread_operation(raw, doc, typelib_path, read, report["thread_operation"])
        if _object_id(doc, operation, read) != expected_thread_native_id:
            raise ValueError("Native THREAD identity changed during recovery")
        stage = "inventory_after"
        after_inventory = _inventory(machine, typelib_path)
        stage = "saved_file_hash_after"
        file_after = _file_hash(before["path"])
        stage = "document_after"
        after = document_snapshot(sw)
        report.update(inventory_after=after_inventory, document_after=after,
                      saved_file_sha256_after=file_after, inventory_unchanged=initial == after_inventory,
                      active_document_unchanged=before == after, saved_file_unchanged=file_before == file_after)
        unchanged = initial == after_inventory and before == after and file_before == file_after
        report.update(status="review_required" if unchanged else "error",
                      supported_readback_verified=unchanged,
                      reason=("THREAD_METADATA_GETTERS_UNAVAILABLE_NO_M60_CONFIGURATION" if unchanged
                              else "CAM_STATE_CHANGED_DURING_THREAD_RECOVERY"))
    except Exception as exc:
        report.update(status="error", reason="CAM_THREAD_READONLY_INSPECTION_FAILED",
                      failed_stage=stage, issue=_error(exc))
    return report
