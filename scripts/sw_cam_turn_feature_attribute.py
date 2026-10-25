"""只对已验证单线车削特征写入一个原生目录策略；不生成或保存。"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_operation_profile import _integer, _read_profile
from scripts.sw_cam_qualification_context import _converted_shape
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature import (_body_state, _model_features,
    _state_digest as _feature_state_digest, _states_equal)
from scripts.sw_operation_guard import absolute_document_path, check_document_target



# 11 位有效数字的最大相对量化步长为 1e-10；原始值及独立语义容差仍保留。
_MASS_HASH_DIGITS = 11


def _state_digest(state):
    return _feature_state_digest(state, mass_significant_digits=_MASS_HASH_DIGITS)


def _context(sw, clsid, typelib_path, read):
    # 本工具只取当前零件；每次原生 CAM 调用均使用同一事件门禁，不读机器目录。
    before = document_snapshot(sw)
    if before is None or before["type"] != 1 or not before["path"]:
        raise ValueError("An active saved part is required")
    addin = read(sw, "GetAddInObject", clsid)
    if addin is None:
        raise ValueError("CAM add-in must already be loaded")
    app = _typed(read(addin, "GetCWApp"), "ICWApp4", typelib_path)
    active = read(app, "IGetActiveDoc")
    if active is None:
        raise ValueError("No active CAM document")
    doc = _typed(active, "ICWDoc3", typelib_path)
    if _integer(read(doc, "GetDocType")) != 1:
        raise ValueError("Active CAM document is not a part")
    part = _typed(active, "ICWPartDoc", typelib_path)
    machine = _typed(read(part, "IGetMachine"), "ICWMachine", typelib_path)
    if _integer(read(machine, "MachType")) != 3:
        raise ValueError("Qualification requires a turning machine")
    return before, doc, part, machine, app


def _items(raw, typelib_path, read, *, limit=512):
    collection = _typed(raw, "ICWDispatchCollection", typelib_path)
    count = _integer(read(collection, "Count"))
    if not 0 <= count <= limit:
        raise ValueError("Native collection exceeds remaining qualification bound")
    return [read(collection, "Item", index) for index in range(count)]


def _inventory(machine, typelib_path, read):
    # 与公共 inventory 同一数据结构；每个 Count/Item/getter 都经过本地事件门禁。
    counts = []
    for raw in _items(read(machine, "IGetEnumSetups"), typelib_path, read):
        setup = _typed(raw, "ICWBaseSetup", typelib_path)
        counts.append(len(_items(read(setup, "IGetEnumFeatures"), typelib_path, read, limit=64-sum(counts))))
    setups = _items(read(machine, "IGetEnumOpSetups"), typelib_path, read)
    operations = []
    for si, raw in enumerate(setups):
        setup = _typed(raw, "ICWBaseOpSetup", typelib_path)
        for oi, value in enumerate(_items(read(setup, "IGetEnumOperations"), typelib_path, read, limit=512-len(operations))):
            operation = _typed(value, "ICWOperation", typelib_path)
            turn = _typed(value, "ICWTurnOperation", typelib_path)
            generated = read(operation, "GetIsToolpathGenerated")
            if type(generated) is not bool:
                raise ValueError("Generated flag must be a native Boolean")
            records = []
            if generated:
                for item in _items(read(operation, "IGetEnumToolpaths"), typelib_path, read):
                    toolpath = _typed(item, "ICWToolpath", typelib_path)
                    count = _integer(read(toolpath, "RecordCount"))
                    if count < 0: raise ValueError("Negative native toolpath record count")
                    records.append(count)
            operations.append(dict(setup_index=si,operation_index=oi,
                turn_operation_type=_integer(read(turn,"OpernType")),toolpath_generated=generated,
                toolpath_record_counts=records))
    stock = _typed(read(machine,"IGetWorkpiece"),"ICWTurnWorkpiece",typelib_path)
    return dict(machine_type=3,feature_setup_count=len(counts),feature_counts_by_setup=counts,
        feature_count=sum(counts),operation_setup_count=len(setups),operation_count=len(operations),
        operations=operations,stock=dict(type=_integer(read(stock,"GetTurnWorkpieceType")),
            parameters_modified=False,length_units="native_API_units_not_assumed"))


def _catalog(turn, desired_name, read):
    raw = read(turn, "IGetAllAttributes")
    result = {"converted_result_shape": _converted_shape(raw), "native_variant_metadata_preserved": False,
              "names": [], "names_resolved": False, "requested_name": desired_name, "requested_id": None}
    names = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (tuple, list)) else None
    if (names is None or len(names) > 64 or any(type(name) is not str or not 1 <= len(name) <= 1000 for name in names)
            or len(set(names)) != len(names)):
        result["reason"] = "unsupported_or_ambiguous_catalog_shape"
        return result
    result.update(names=names, names_resolved=True)
    if desired_name is not None:
        if desired_name not in names:
            result["reason"] = "exact_requested_name_absent"
            return result
        result["requested_id"] = _integer(read(turn, "GetTdbIdForAttribute", desired_name))
        result["lookup_has_native_success_flag"] = False
    return result


def _snapshot(sw, clsid, typelib_path, config, *, check=lambda: None, diagnostic=None):
    diagnostic = {} if diagnostic is None else diagnostic
    def read(obj, name, *args):
        diagnostic["stage"] = name
        check()
        result = _member(obj, name, *args)
        check()
        return result
    diagnostic["stage"] = "context"
    check()
    before, doc, _part, machine, app = _context(sw, clsid, typelib_path, read)
    check_document_target(before["path"], before["title"], expected_path=config["expected_document_path"], required=True)
    if before["type"] != 1:
        raise ValueError("A saved part is required")
    file_hash = _file_hash(before["path"])
    inventory = _inventory(machine, typelib_path, read)
    diagnostic.update(document=before, inventory=inventory, features=[], operations=[])
    doc = _typed(doc, "ICWDoc3", typelib_path)
    features, budget, selected = diagnostic["features"], [0], None
    for si, raw_setup in enumerate(_items(read(machine, "IGetEnumSetups"), typelib_path, read)):
        setup = _typed(raw_setup, "ICWBaseSetup", typelib_path)
        for raw in _items(read(setup, "IGetEnumFeatures"), typelib_path, read, limit=64-len(features)):
            if len(features) >= 64:
                raise ValueError("Feature count exceeds qualification bound")
            native_id = _object_id(doc, raw, read)
            row = {"setup_index": si, "native_id": native_id, "profile": {}}
            features.append(row)
            _read_profile(raw, typelib_path, read, budget, row["profile"],
                collection_reader=lambda value, limit: _items(value, typelib_path, read, limit=limit))
            if native_id == config["expected_feature_native_id"]:
                if si != config["feature_setup_index"] or selected is not None:
                    raise ValueError("Target feature setup/identity mismatch")
                selected = _typed(raw, "ICWTurnFeature", typelib_path)
    if len({row["native_id"] for row in features}) != len(features) or selected is None:
        raise ValueError("Unique exact feature identity is required")
    target = next(row for row in features if row["native_id"] == config["expected_feature_native_id"])
    profile = target["profile"]
    if profile["turn_feature_type_raw"] != config["expected_turn_feature_type"] or profile["segment_count"] != 1:
        raise ValueError("Target must be the exact expected single-line turning feature")
    line = profile["segments"][0]
    if (line.get("curve_type_raw") != 0 or not line.get("curve_parameters_available")
            or math.dist(line["start_native"], line["end_native"]) <= 0):
        raise ValueError("One confirmed nondegenerate native line is required")
    operations = diagnostic["operations"]
    total_links = 0
    for si, raw_setup in enumerate(_items(read(machine, "IGetEnumOpSetups"), typelib_path, read)):
        setup = _typed(raw_setup, "ICWBaseOpSetup", typelib_path)
        for oi, raw in enumerate(_items(read(setup, "IGetEnumOperations"), typelib_path, read, limit=512-len(operations))):
            if len(operations) >= 512:
                raise ValueError("Operation count exceeds qualification bound")
            operation = _typed(raw, "ICWOperation", typelib_path)
            native_id = _object_id(doc, operation, read)
            linked = _items(read(operation, "IGetAllFeatures"), typelib_path, read, limit=min(512,1024-total_links))
            total_links += len(linked)
            if total_links > 1024:
                raise ValueError("Operation feature links exceed qualification bound")
            ids = [_object_id(doc, value, read) for value in linked]
            operations.append({"setup_index": si, "operation_index": oi, "native_id": native_id, "linked_feature_ids": ids})
    if len({row["native_id"] for row in operations}) != len(operations):
        raise ValueError("Operation native IDs must be unique")
    catalog = _catalog(selected, config["attribute_name"], read)
    diagnostic["catalog"] = catalog
    model = _member(sw, "ActiveDoc")
    if _member(model, "GetActiveSketch2") is not None:
        raise ValueError("An active sketch edit cannot be qualified")
    state = dict(document=before, saved_file_sha256=file_hash, inventory=inventory,
        operations=operations, features=features, solids=_body_state(model), model_features=_model_features(model),
        selected_feature_id=config["expected_feature_native_id"], catalog=catalog, config=deepcopy(config))
    check()
    after_document = document_snapshot(sw)
    check()
    after_inventory = _inventory(machine, typelib_path, read)
    check()
    if (after_document != before or after_inventory != inventory or _file_hash(before["path"]) != file_hash):
        raise ValueError("Document, CAM inventory or saved file changed during snapshot")
    check()
    diagnostic["stage"] = "complete"
    return state, {"app": app, "turn_feature": selected}


def _target_profile(state):
    return next(row["profile"] for row in state["features"] if row["native_id"] == state["selected_feature_id"])


def _verify_attribute(before, after):
    expected = deepcopy(before)
    target = _target_profile(expected)
    target["attribute_id_raw"] = before["catalog"]["requested_id"]
    target["attribute_name"] = before["catalog"]["requested_name"]
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    if not _states_equal(expected, after):
        raise ValueError("Only target attribute ID/name and document dirty flag may change")


def configure_turn_feature_attribute(sw, clsid, typelib_path, *, expected_document_path,
        feature_setup_index, expected_feature_native_id, expected_turn_feature_type, action,
        qualification_only, message_policy, attribute_name=None, expected_state_sha256=None,
        receipt_path=None, read_techdb_path=False):
    """读取/准备/单次设置精确单线特征策略；Thread Condition、深度、单位和持久化不作保证。"""
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status="error", phase="preflight", action=action, may_continue=False,
        mutation_attempted=False, native_call_returned=False, readback_verified=False,
        generation_attempted=False, model_saved=False, persistence_verified=False,
        thread_condition_verified=False, thread_depth_verified=False, thread_pitch_verified=False,
        units_verified=False, production_process_qualified=False, snapshot_diagnostics=[],
        verification_scope="feature_profiles_model_file_operation_ids_links_and_toolpath_record_counts",
        toolpath_coordinates_verified=False, full_cam_snapshot_scope="before_event_disconnect",
        post_cleanup_cam_read_performed=False, post_cleanup_document_and_file_verified=False,
        mass_comparison=dict(raw_values_retained=True, hash_significant_digits=_MASS_HASH_DIGITS,
            relative_tolerance=1e-10, absolute_tolerance=0.0,
            scope="solids.mass_properties_native_only", other_state_fields="exact",
            rounding_boundary_mismatch="stop_and_prepare_again_no_automatic_retry"))
    session = None
    receipt = None
    receipt_created = False
    try:
        for key, value, low, high in (("feature_setup_index", feature_setup_index, 0, 511),
                ("expected_feature_native_id", expected_feature_native_id, 1, 4294967295),
                ("expected_turn_feature_type", expected_turn_feature_type, 0, 2147483647)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Invalid strict selector: " + key)
        if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold() != ".sldprt"):
            raise ValueError("An exact absolute saved part path is required")
        if qualification_only is not True or message_policy != "vendor_default" or action not in {"inspect", "prepare", "apply"}:
            raise ValueError("Explicit qualification action and vendor_default are required")
        if type(read_techdb_path) is not bool or (read_techdb_path and action != "inspect"):
            raise ValueError("TechDB path reading is optional for inspect only")
        if attribute_name is not None and (type(attribute_name) is not str or not 1 <= len(attribute_name) <= 1000):
            raise ValueError("Attribute name must be an exact nonempty bounded BSTR")
        if action != "inspect" and attribute_name is None:
            raise ValueError("Prepare/apply require an exact attribute name")
        if action != "apply":
            if expected_state_sha256 is not None or receipt_path is not None:
                raise ValueError("Read-only actions cannot accept mutation inputs")
        else:
            if not isinstance(expected_state_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_state_sha256):
                raise ValueError("Exact prepared state SHA is required")
            receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json" or not receipt.parent.is_dir():
                raise ValueError("A new absolute JSON receipt with an existing parent is required")
            _write_receipt(receipt, report, create=True)
            receipt_created = True
        config = dict(expected_document_path=expected_document_path, feature_setup_index=feature_setup_index,
            expected_feature_native_id=expected_feature_native_id, expected_turn_feature_type=expected_turn_feature_type,
            attribute_name=attribute_name)
        def capture(phase, boundary=lambda: None, local=lambda: None):
            diagnostic = {"phase": phase}; report["snapshot_diagnostics"].append(diagnostic)
            boundary()
            value = _snapshot(sw, clsid, typelib_path, config, check=local, diagnostic=diagnostic)
            boundary()
            return value
        before, native = capture("initial")
        report.update(before=before, state_sha256=_state_digest(before), catalog=before["catalog"],
            selected_profile=_target_profile(before))
        linked = [row for row in before["operations"] if expected_feature_native_id in row["linked_feature_ids"]]
        report["linked_operations"] = linked
        if action == "inspect":
            if read_techdb_path:
                app = _typed(native["app"], "ICWApp4", typelib_path)
                report["phase"] = "IGetTechDBPath"
                path = _member(app, "IGetTechDBPath")
                if type(path) is not str:
                    raise ValueError("TechDB path did not return a BSTR")
                report["techdb"] = {"path_raw": path, "source": "ICWApp4.IGetTechDBPath", "modified": False}
                if document_snapshot(sw) != before["document"]:
                    raise ValueError("Document changed during optional TechDB read")
            report.update(status="ok", phase="inspected", apply_eligible=False)
            return report
        catalog = before["catalog"]
        if (not catalog["names_resolved"] or type(catalog["requested_id"]) is not int
                or not 0 < catalog["requested_id"] <= 2147483647):
            raise ValueError("Exact positive native attribute ID required; nonpositive lookup semantics are unqualified")
        if linked or before["document"]["needs_save"]:
            raise ValueError("Attribute qualification requires a clean saved part and no linked operations")
        old = _target_profile(before)
        if old["attribute_id_raw"] == catalog["requested_id"]:
            raise ValueError("Requested ID is unchanged or ambiguous; no property write is allowed")
        report.update(old_attribute={"id": old["attribute_id_raw"], "name": old["attribute_name"]},
            requested_attribute={"id": catalog["requested_id"], "name": attribute_name})
        if action == "prepare":
            report.update(status="ok", phase="prepared", apply_eligible=True)
            return report
        if expected_state_sha256 != report["state_sha256"]:
            raise ValueError("Prepared feature/file/model state changed")
        session = CamMessageSession(native["app"], typelib_path)
        def local():
            summary = session.summary(); report["messages"] = summary
            if not summary.get("active") or not summary.get("subscribed") or any(summary.get(key) for key in ("event_count", "overflow", "callback_errors",
                    "callback_error_count", "subscription_error", "disconnect_errors")):
                raise ValueError("CAM event requires review; no further native calls")
        def boundary():
            local()
            current = document_snapshot(sw)
            if current is None or any(current[key] != before["document"][key] for key in ("path", "title", "type")):
                raise ValueError("Active document identity changed")
            local()
        with session:
            current, native = capture("before_write", boundary, local)
            if not _states_equal(before, current):
                raise ValueError("State changed before attribute put")
            report.update(phase="Attribute", mutation_attempted=True)
            _write_receipt(receipt, report)
            boundary()
            if document_snapshot(sw) != before["document"]:
                raise ValueError("Document changed immediately before attribute put")
            local()
            setattr(native["turn_feature"], "Attribute", catalog["requested_id"])
            report.update(native_call_returned=True, phase="Attribute_returned")
            _write_receipt(receipt, report)
            local()
            report["phase"] = "attribute_scalar_readback"
            boundary()
            readback = {}
            report["attribute_readback"] = readback
            for key, member in (("id", "Attribute"), ("name", "GetAttributeName")):
                local()
                readback[key] = _member(native["turn_feature"], member)
                local()
            if (type(readback["id"]) is not int or readback["id"] != catalog["requested_id"]
                    or readback["name"] != attribute_name):
                raise ValueError("Immediate native attribute ID/name readback did not match")
            report["scalar_readback_verified"] = True
            _write_receipt(receipt, report)
            after, _ = capture("after_write", boundary, local)
            report["after"] = after
            _verify_attribute(before, after)
        summary = session.summary()
        report["messages"] = summary
        if (summary.get("disconnected") is not True or summary.get("active")
                or any(summary.get(key) for key in ("event_count", "overflow", "callback_errors",
                    "callback_error_count", "subscription_error", "disconnect_errors"))):
            raise ValueError("CAM event cleanup was not confirmed cleanly")
        # 取消订阅后不再调用任何 CAM getter；最后 CAM 快照的证据边界明确为清理前。
        report["phase"] = "post_cleanup_document_and_file"
        final_document = document_snapshot(sw)
        final_file_hash = _file_hash(before["document"]["path"])
        report["post_cleanup"] = dict(document=final_document, saved_file_sha256=final_file_hash)
        if final_document != after["document"] or final_file_hash != after["saved_file_sha256"]:
            raise ValueError("Document or saved file changed during cleanup")
        report["final_state"] = after
        report.update(status="review_required", phase="finished", readback_verified=True,
            post_cleanup_document_and_file_verified=True, state_sha256=_state_digest(after),
            reason="ATTRIBUTE_ONLY_THREAD_CONDITION_AND_PERSISTENCE_UNVERIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error", failed_phase=report["phase"],
            failed_stage=report["snapshot_diagnostics"][-1].get("stage") if report["snapshot_diagnostics"] else None,
            reason="CAM_TURN_FEATURE_ATTRIBUTE_FAILED", issue=_error(exc), phase="finished")
    finally:
        if session is not None: report["messages"] = session.summary()
        if receipt_created:
            try: _write_receipt(receipt, report)
            except Exception as exc: report.update(status="uncertain", receipt_write_error=_error(exc), readback_verified=False)
    return report
