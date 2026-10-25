"""从已读直线段验证一个新车削特征；类型映射是假设，不生成 THREAD 或刀路。"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _collection, _inventory, _typed, _write_receipt
from scripts.sw_cam_operation_profile import _number, _read_profile
from scripts.sw_cam_thread import _capture, _object_id
from scripts.sw_cam_turn_tool import _digest, _reference
from scripts.sw_operation_guard import absolute_document_path



# 仅质量属性容纳浮点积分噪声；文件、包围盒、特征和操作仍逐值精确比较。
_MASS_SIGNIFICANT_DIGITS = 12
_MASS_RELATIVE_TOLERANCE = 1e-10


def _state_digest(state):
    canonical = deepcopy(state)
    for body in canonical["solids"]:
        body["mass_properties_native"] = [
            0.0 if _number(value) == 0 else float(format(_number(value), f".{_MASS_SIGNIFICANT_DIGITS}g"))
            for value in body["mass_properties_native"]]
    return _digest(canonical)


def _states_equal(before, after):
    candidate = deepcopy(after)
    if len(before["solids"]) != len(candidate["solids"]):
        return False
    for old_body, new_body in zip(before["solids"], candidate["solids"]):
        old = old_body["mass_properties_native"]
        new = new_body["mass_properties_native"]
        if len(old) != len(new) or any(not math.isclose(_number(a), _number(b),
                rel_tol=_MASS_RELATIVE_TOLERANCE, abs_tol=0.0) for a, b in zip(old, new)):
            return False
        new_body["mass_properties_native"] = deepcopy(old)
    return before == candidate


def _body_state(model):
    bodies = list(_member(model, "GetBodies2", 0, False) or [])
    if not 1 <= len(bodies) <= 64:
        raise ValueError("Qualification requires a bounded solid part")
    return [{"box_model_m": list(map(_number, _member(body, "GetBodyBox"))),
             "mass_properties_native": list(map(_number, _member(body, "GetMassProperties", 1)))}
            for body in bodies]


def _model_features(model):
    rows = []
    feature = _member(model, "FirstFeature")
    while feature is not None:
        if len(rows) >= 512:
            raise ValueError("Model feature traversal exceeds qualification bound")
        rows.append({"name": str(_member(feature, "Name")), "type": str(_member(feature, "GetTypeName2"))})
        feature = _member(feature, "GetNextFeature")
    return rows


def _snapshot(sw, clsid, typelib_path, config, *, check=lambda: None, diagnostic=None):
    from scripts.sw_cam_feature_sketch import inspect_meridional_plane
    diagnostic = {} if diagnostic is None else diagnostic
    selected = {key: config[key] for key in ("setup_index", "operation_index", "expected_operation_type")}
    state, native = _capture(sw, clsid, typelib_path, selected, config["linked_feature_index"],
                            config["expected_document_path"], check=check, diagnostic=diagnostic)
    profile = state["selected_profile"]
    if profile["turn_feature_type_raw"] != config["candidate_feature_type"]:
        raise ValueError("Candidate must equal the explicitly observed source turn-feature type")
    index = config["segment_index"]
    if index >= len(profile["segments"]):
        raise ValueError("Source segment is absent")
    line = profile["segments"][index]
    if line.get("curve_type_raw") != 0 or not line.get("curve_parameters_available"):
        raise ValueError("A confirmed native line segment is required")
    points = [line["start_native"], line["end_native"]]
    if math.dist(*points) <= 0:
        raise ValueError("Source line has zero length")
    model = _member(sw, "ActiveDoc")
    if _member(model, "GetActiveSketch2") is not None:
        raise ValueError("No existing sketch may be in edit mode")
    model_points = [[_number(v) * config["native_to_model_scale"] for v in point] for point in points]
    diagnostic["stage"] = "reference_plane"
    plane, _plane_feature = inspect_meridional_plane(sw, model, model_points)
    # IGetMachine 属于 ICWPartDoc，不能在 ICWDoc3 的重复 DISPID 上调用。
    native_part = _typed(native["doc"], "ICWPartDoc", typelib_path)
    machine = _typed(_member(native_part, "IGetMachine"), "ICWMachine5", typelib_path)
    setups = _collection(_member(machine, "IGetEnumSetups"), typelib_path)
    if config["feature_setup_index"] >= len(setups):
        raise ValueError("Target feature setup is absent")
    features, budget = [], [0]
    def read(obj, name, *args):
        diagnostic["stage"] = name
        check()
        value = _member(obj, name, *args)
        check()
        return value
    for si, raw_setup in enumerate(setups):
        setup = _typed(raw_setup, "ICWBaseSetup", typelib_path)
        for raw in _collection(read(setup, "IGetEnumFeatures"), typelib_path):
            if len(features) >= 64:
                raise ValueError("Too many existing CAM features")
            row = {"setup_index": si, "native_id": _object_id(native["doc"], raw, read), "profile": {}}
            features.append(row)
            _read_profile(raw, typelib_path, read, budget, row["profile"])
    if len({item["native_id"] for item in features}) != len(features):
        raise ValueError("Existing feature IDs must be unique")
    if not any(item["native_id"] == state["selected_feature_id"] and
               item["setup_index"] == config["feature_setup_index"] for item in features):
        raise ValueError("Source feature must belong to the explicitly selected target setup")
    state.update(config=deepcopy(config), source_line=deepcopy(line), endpoints_model_m=model_points,
                 plane=plane, features=features, solids=_body_state(model), model_features=_model_features(model))
    diagnostic["mass_properties_native_raw"] = [deepcopy(body["mass_properties_native"]) for body in state["solids"]]
    check()
    if document_snapshot(sw) != state["document"] or _inventory(machine, typelib_path) != state["inventory"]:
        raise ValueError("Document or inventory changed during feature snapshot")
    native.update(model=model, machine=machine, target_setup=setups[config["feature_setup_index"]])
    diagnostic["stage"] = "complete"
    return state, native


def _verify(before, after, *, sketch_added=False, new_id=None, saving=False):
    expected = deepcopy(before)
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    if saving:
        expected["saved_file_sha256"] = after["saved_file_sha256"]
    if sketch_added:
        name = before["config"]["sketch_name"]
        added = [item for item in after["model_features"] if item["name"] == name]
        if len(added) != 1 or added[0]["type"] != "ProfileFeature":
            raise ValueError("Exactly one new 2D sketch is required")
        if [item for item in after["model_features"] if item["name"] != name] != before["model_features"]:
            raise ValueError("An existing model feature changed")
        expected["model_features"] = deepcopy(after["model_features"])
    if new_id is not None:
        rows = [item for item in after["features"] if item["native_id"] == new_id]
        if len(rows) != 1 or any(item["native_id"] == new_id for item in before["features"]):
            raise ValueError("Returned feature is not exactly one new positive native ID")
        row = rows[0]
        if row["setup_index"] != before["config"]["feature_setup_index"]:
            raise ValueError("New feature belongs to another setup")
        profile = row["profile"]
        if profile["turn_feature_type_raw"] != before["config"]["candidate_feature_type"] or profile["segment_count"] != 1:
            raise ValueError("Candidate mapping or single-segment feature readback did not match")
        line = profile["segments"][0]
        if line.get("curve_type_raw") != 0 or not line.get("curve_parameters_available"):
            raise ValueError("Created feature is not a confirmed line")
        points = [line["start_native"], line["end_native"]]
        source = [before["source_line"]["start_native"], before["source_line"]["end_native"]]
        tolerance = 1e-8 / before["config"]["native_to_model_scale"]
        if not any(all(math.dist(a, b) <= tolerance for a, b in zip(points, order)) for order in (source, source[::-1])):
            raise ValueError("Created native feature endpoints differ from the qualified source line")
        for key in ("start_diameter", "end_diameter", "length_along_axis", "true_length"):
            actual = abs(_number(line["line_native"][key]))
            reference = abs(_number(before["source_line"]["line_native"][key]))
            if abs(actual - reference) > tolerance:
                raise ValueError("Created native line dimensions differ from the source")
        if [item for item in after["features"] if item["native_id"] != new_id] != before["features"]:
            raise ValueError("An existing CAM feature changed")
        expected["features"] = deepcopy(after["features"])
        expected["inventory"]["feature_count"] += 1
        expected["inventory"]["feature_counts_by_setup"][row["setup_index"]] += 1
    if not _states_equal(expected, after):
        raise ValueError("Unexpected change to document, saved file, solids, old features or operation paths")


def qualify_turn_feature(sw, clsid, typelib_path, *, expected_document_path, setup_index,
        operation_index, expected_operation_type, linked_feature_index, segment_index,
        feature_setup_index, candidate_feature_type, native_to_model_scale, sketch_name,
        action, qualification_only, acknowledge_unverified_type_mapping, message_policy,
        expected_state_sha256=None, receipt_path=None, expected_new_feature_native_id=None):
    """准备/执行一次明确假设的直线车削特征创建，或单独试验 CAM 保存。

    必须绑定保存路径、源操作/段、原生到模型米的显式比例和新草图名。apply 需要
    prepare 的 SHA 与新回执；save_candidate 另需新特征 ID。返回始终要求人工复核，
    不创建 THREAD、不生成刀路；保存返回不等于关闭重开持久化已通过。
    """
    from scripts.sw_cam_events import CamMessageSession
    from scripts.sw_cam_feature_sketch import create_single_line_sketch
    config = dict(expected_document_path=expected_document_path, setup_index=setup_index,
        operation_index=operation_index, expected_operation_type=expected_operation_type,
        linked_feature_index=linked_feature_index, segment_index=segment_index,
        feature_setup_index=feature_setup_index, candidate_feature_type=candidate_feature_type,
        native_to_model_scale=native_to_model_scale, sketch_name=sketch_name)
    report = {"status": "error", "action": action, "phase": "preflight", "may_continue": False,
        "mutation_attempted": False, "feature_call_attempted": False, "native_call_returned": False,
        "generation_attempted": False, "thread_created": False, "model_saved": False,
        "persistence_verified": False, "mapping_verified": False, "snapshot_diagnostics": [],
        "mapping_basis": "explicit_observed_type_hypothesis_requires_exact_geometry_readback",
        "mass_comparison": {"raw_values_retained": True, "hash_significant_digits": _MASS_SIGNIFICANT_DIGITS,
            "relative_tolerance": _MASS_RELATIVE_TOLERANCE, "absolute_tolerance": 0.0,
            "scope": "solids.mass_properties_native_only", "other_state_fields": "exact"}}
    receipt = None
    receipt_created = False
    session = None
    try:
        _reference({key: config[key] for key in ("setup_index", "operation_index", "expected_operation_type")})
        for key, upper in (("linked_feature_index",63),("segment_index",511),("feature_setup_index",511),("candidate_feature_type",2147483647)):
            if type(config[key]) is not int or not 0 <= config[key] <= upper:
                raise ValueError("Invalid strict selector: " + key)
        scale = _number(native_to_model_scale)
        if not 0 < scale <= 1 or not isinstance(sketch_name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", sketch_name):
            raise ValueError("Explicit positive scale and an exact simple unique sketch name are required")
        config["native_to_model_scale"] = scale
        if not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold() != ".sldprt":
            raise ValueError("An exact absolute saved part is required")
        if qualification_only is not True or acknowledge_unverified_type_mapping is not True or message_policy != "vendor_default":
            raise ValueError("Explicit qualification/type hypothesis and vendor_default are required")
        if action not in {"inspect", "prepare", "apply", "save_candidate"}:
            raise ValueError("Unknown action")
        if action in {"inspect", "prepare"}:
            if any(value is not None for value in (expected_state_sha256, receipt_path, expected_new_feature_native_id)):
                raise ValueError("Inspect/prepare cannot take mutation inputs")
        else:
            if not isinstance(expected_state_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_state_sha256):
                raise ValueError("Exact prepared/final state SHA-256 required")
            receipt = Path(receipt_path) if isinstance(receipt_path,str) else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json" or not receipt.parent.is_dir():
                raise ValueError("New absolute JSON receipt with an existing parent required")
            if action == "save_candidate":
                if type(expected_new_feature_native_id) is not int or not 0 < expected_new_feature_native_id <= 4294967295:
                    raise ValueError("Save candidate requires the exact new native feature ID")
            elif expected_new_feature_native_id is not None:
                raise ValueError("Apply cannot accept a preexisting new feature ID")
            _write_receipt(receipt, report, create=True)
            receipt_created = True
        def capture(phase, identity_check=lambda:None, read_check=lambda:None):
            diagnostic = {"phase":phase};report["snapshot_diagnostics"].append(diagnostic)
            identity_check()
            value = _snapshot(sw,clsid,typelib_path,config,check=read_check,diagnostic=diagnostic)
            identity_check()
            return value
        before, native = capture("initial")
        report.update(before=before, state_sha256=_state_digest(before))
        if action == "inspect":
            report.update(status="review_required", phase="inspected", prepared=False,
                apply_eligible=False, snapshot_readback_completed=True,
                reason="READ_ONLY_CURRENT_STATE_NOT_PREPARED")
            return report
        if action != "save_candidate":
            if before["document"]["needs_save"] or any(item["name"] == sketch_name for item in before["model_features"]):
                raise ValueError("Creation requires a clean saved copy and a new sketch name")
        elif not any(item["native_id"] == expected_new_feature_native_id for item in before["features"]):
            raise ValueError("Expected created feature ID is absent")
        if action == "prepare":
            report.update(status="ok",phase="prepared");return report
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Prepared feature/document/file state changed")
        session = CamMessageSession(native["app"],typelib_path)
        def check_events():
            # getter 间只检查本地事件；完整身份验证保留在快照边界及每次写入之前。
            summary = session.summary();report["messages"] = summary
            if not summary.get("subscribed") or any(summary.get(key) for key in ("event_count","overflow","callback_errors","callback_error_count","subscription_error","disconnect_errors")):
                raise ValueError("CAM event requires review; stop further calls")
        def check():
            check_events()
            current = document_snapshot(sw)
            if current is None or any(current[key] != before["document"][key] for key in ("path","title","type")):
                raise ValueError("Active document identity changed")
            check_events()
        with session:
            check()
            current, native = capture("before_mutation",check,check_events)
            if not _states_equal(before, current):raise ValueError("State changed before mutation")
            report.update(phase="native_save" if action == "save_candidate" else "create_sketch",mutation_attempted=True)
            _write_receipt(receipt,report)
            if action == "save_candidate":
                app = _typed(native["app"],"ICWApp",typelib_path)
                check();_member(app,"SaveActiveDocument")
                report.update(native_call_returned=True,native_save_call_returned=True,phase="native_save_returned")
                _write_receipt(receipt,report);check()
                after, _ = capture("after_save",check,check_events)
                report["after"] = after;_verify(before,after,saving=True)
            else:
                report["sketch"] = {}
                sketch = create_single_line_sketch(sw,native["model"],endpoints_model_m=before["endpoints_model_m"],
                    sketch_name=sketch_name,expected_plane=before["plane"],diagnostic=report["sketch"],check=check)
                report["sketch"].update(sketch)
                if sketch.get("verified") is not True:raise ValueError("Sketch geometry readback was not verified")
                report["phase"] = "sketch_verified";_write_receipt(receipt,report)
                after_sketch,native = capture("after_sketch",check,check_events)
                _verify(before,after_sketch,sketch_added=True)
                setup = _typed(native["target_setup"],"ICWTurnSetup",typelib_path)
                report.update(phase="CreateTurnFeature",feature_call_attempted=True);_write_receipt(receipt,report)
                check();raw = _member(setup,"CreateTurnFeature",candidate_feature_type,sketch_name)
                report.update(native_call_returned=True,phase="CreateTurnFeature_returned",native_result_present=raw is not None and bool(raw))
                _write_receipt(receipt,report);check()
                if report["native_result_present"]:
                    new_id = _object_id(native["doc"],raw,lambda obj,name,*args:_member(obj,name,*args))
                    report["new_feature_identity_source"] = "returned_object"
                after,_ = capture("after_feature",check,check_events);report["after"] = after
                if not report["native_result_present"]:
                    # 已返回但空对象不等于未创建：只读一次精确增量，绝不重放创建。
                    old_ids = {item["native_id"] for item in before["features"]}
                    added = [item["native_id"] for item in after["features"] if item["native_id"] not in old_ids]
                    if len(added) != 1 or type(added[0]) is not int or not 0 < added[0] <= 4294967295:
                        raise ValueError("Null creator return requires exactly one new positive feature ID")
                    new_id = added[0]
                    report["new_feature_identity_source"] = "snapshot_delta_after_null_return"
                report["new_feature_native_id"] = new_id
                _verify(before,after,sketch_added=True,new_id=new_id)
                report["null_result_recovered_by_exact_delta"] = not report["native_result_present"]
        check()
        if not session.summary().get("disconnected"):raise ValueError("Event cleanup was not verified")
        final,_ = capture("after_cleanup",check,check_events);report["final_state"] = final
        if not _states_equal(after, final):raise ValueError("State changed during cleanup")
        report.update(status="review_required",phase="finished",state_sha256=_state_digest(final),readback_verified=True,
            mapping_verified=action=="apply",model_saved=action=="save_candidate",
            reason="SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN" if action=="save_candidate" else "ONE_LINE_FEATURE_MAPPING_QUALIFIED_NOT_THREAD_CONFIGURATION")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],
            reason="CAM_TURN_FEATURE_QUALIFICATION_FAILED",issue=_error(exc),phase="finished")
    finally:
        if session is not None:report["messages"] = session.summary()
        if receipt_created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False)
    return report
