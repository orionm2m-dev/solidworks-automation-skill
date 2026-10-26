"""原生装配结构及既有动画回读；不保存、重建、播放、计算或创建运动。"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import time

from scripts.sw_cam import _error, _member
from scripts.sw_cam_feature_sketch import _call_method as call
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_native_transfer import _path, _hash
from scripts.sw_operation_guard import check_document_target, _path_identity, absolute_document_path

_IIDS = {
    "IConfiguration": "{83A33D98-27C5-11CE-BFD4-00400513BB57}",
    "IEntity": "{83A33D65-27C5-11CE-BFD4-00400513BB57}",
    "IFace2": "{4A8BA4D8-DA25-4B75-8E2D-4922B74D81ED}",
    "IExplodeStep": "{7241680B-0BC6-11D4-AEEE-00C04F61025C}",
}


def _native_interface(obj, name):
    from win32com.client import gencache
    cls = gencache.GetClassForCLSID(_IIDS[name])
    if cls is None:
        raise ValueError("Installed generated interface unavailable: " + name)
    return cls(obj._oleobj_)


def _array(value, limit, label):
    if value is None:
        return []
    if type(value) not in (list, tuple) or len(value) > limit:
        raise ValueError(label + ": invalid or oversized array")
    return list(value)


def _str(value):
    if type(value) is not str:
        raise ValueError("Native BSTR required")
    return value


def _int(value, minimum=0, maximum=2147483647):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Native bounded LONG required")
    return value


def _bool(value):
    if type(value) is not bool:
        raise ValueError("Native BOOL required")
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite native number required")
    return float(value)


def _vector(value, length):
    values = _array(value, length, "native vector")
    if len(values) != length:
        raise ValueError("Native vector length differs")
    return [_number(item) for item in values]


def _matrix(component):
    transform = call(component, "GetTotalTransform", True)
    if transform is None:
        raise ValueError("Component total transform unavailable")
    return _vector(_member(transform, "ArrayData"), 16)


def _guard(sw, process_id, path, *, clean=False):
    if type(process_id) is not int or process_id <= 0 or _int(call(sw, "GetProcessID"), minimum=1) != process_id:
        raise ValueError("Explicit process identity differs")
    model = _member(sw, "ActiveDoc")
    if model is None:
        raise ValueError("Active document unavailable")
    actual = _str(call(model, "GetPathName"))
    check_document_target(actual, call(model, "GetTitle"), expected_path=str(path), required=True)
    if call(model, "GetType") != 2:
        raise ValueError("Active saved assembly required")
    dirty = _bool(call(model, "GetSaveFlag"))
    if clean and dirty:
        raise ValueError("Initial assembly must be clean")
    return model, {"path": actual, "needs_save": dirty}


def _motion_manager(model):
    from scripts.sw_motion import ensure_motion_type_library
    ensure_motion_type_library(raise_on_error=True)
    manager = call(_member(model, "Extension"), "GetMotionStudyManager")
    if manager is None:
        raise ValueError("Motion study manager unavailable")
    return manager


def _components(model):
    rows, objects = [], {}
    for component in _array(call(model, "GetComponents", False), 1024, "components"):
        name = _str(_member(component, "Name2"))
        if not name or name in objects:
            raise ValueError("Component instance names must be nonempty and unique")
        objects[name] = component
        rows.append({"name": name, "reference": _str(_member(component, "ComponentReference")),
            "path": _str(call(component, "GetPathName")),
            "configuration": _str(_member(component, "ReferencedConfiguration")),
            "native_id": _int(call(component, "GetID")),
            "loaded": call(component, "GetModelDoc2") is not None,
            "suppressed": _bool(call(component, "IsSuppressed")),
            "fixed": _bool(call(component, "IsFixed")), "matrix": _matrix(component)})
    return sorted(rows, key=lambda row: row["name"]), objects


def _axis(step, method, known):
    returned = call(step, method)
    if type(returned) not in (tuple, list) or len(returned) != 2:
        raise ValueError("Axis native OUT tuple must be (entity, index)")
    raw, index = returned
    result = {"index": _int(index, -2147483648), "entity_present": raw is not None,
              "owner": None, "surface_available": False, "is_cylinder": None, "cylinder_parameters": None}
    if raw is None:
        return result
    entity = _native_interface(raw, "IEntity")
    result["entity_type"] = _int(call(entity, "GetType"))
    owner = call(entity, "GetComponent")
    if owner is not None:
        result["owner"] = {"name": _str(_member(owner, "Name2")),
            "path": _str(call(owner, "GetPathName")), "reference": _str(_member(owner, "ComponentReference"))}
        matched = next((row for row in known if row["name"] == result["owner"]["name"]), None)
        if matched is None or any(matched[key] != result["owner"][key] for key in ("path", "reference")):
            raise ValueError("Axis owner differs from an actual assembly instance")
    if result["entity_type"] == 2:  # swSelectType_e.swSelFACES，已安装主类型库。
        surface = call(_native_interface(raw, "IFace2"), "GetSurface")
        if surface is None:
            raise ValueError("Face surface unavailable")
        result["surface_available"] = True
        result["is_cylinder"] = _bool(call(surface, "IsCylinder"))
        if result["is_cylinder"]:
            result["cylinder_parameters"] = _vector(_member(surface, "CylinderParams"), 7)
    return result


def _snapshot(model, result):
    result["document_path"] = _str(call(model, "GetPathName"))
    cfg = _native_interface(_member(_member(model, "ConfigurationManager"), "ActiveConfiguration"), "IConfiguration")
    result["active_configuration"] = _str(_member(cfg, "Name"))
    result["configuration_names"] = [_str(v) for v in _array(call(model, "GetConfigurationNames"), 512, "configurations")]
    result["explode_views"] = [_str(v) for v in _array(call(model, "GetExplodedViewNames2", result["active_configuration"]), 512, "explode views")]
    result["explode_step_scope"] = "active_configuration_only"
    result["components"], _ = _components(model)
    result["native_step_sequence"] = []
    count = _int(call(cfg, "GetNumberOfExplodeSteps"), maximum=512)
    first = call(cfg, "GetExplodeStep", 0) if count else None
    start = 0 if first is not None else 1
    for index in range(start, start + count):
        raw = first if index == 0 else call(cfg, "GetExplodeStep", index)
        if raw is None:
            raise ValueError("Missing explode step")
        step = _native_interface(raw, "IExplodeStep")
        row = {"index": index, "name": _str(_member(step, "Name")),
            "distance_m": _number(_member(step, "ExplodeDistance")),
            "angle_rad": _number(_member(step, "RotationAngle")),
            "components": sorted(_str(_member(item, "Name2")) for item in _array(call(step, "GetComponents"), 1024, "step components")), "axes": {}}
        result["native_step_sequence"].append(row)
        if any(name not in {item["name"] for item in result["components"]} for name in row["components"]):
            raise ValueError("Explode step references an unknown component")
        for method in ("GetExplodeDirection", "GetRotationAxis"):
            row["axes"][method] = _axis(step, method, result["components"])
    manager = _motion_manager(model)
    result["studies"] = []
    for name in _array(call(manager, "GetMotionStudyNames"), 512, "studies"):
        name = _str(name)
        study = call(manager, "GetMotionStudy", name)
        if study is None:
            raise ValueError("Existing motion study unavailable")
        result["studies"].append({"name": name, "duration_seconds": _number(call(study, "GetDuration"))})
    return result


def _load_json(path, digest):
    path = _path(path, {".json"})
    if _file_hash(path) != _hash(digest):
        raise ValueError("Evidence file SHA differs")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Evidence file exceeds bounded size")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _path_map(value):
    if value is None:
        return {}
    if type(value) is not dict or len(value) > 32:
        raise ValueError("Bounded old-to-new path dictionary required")
    result = {}
    for old, new in value.items():
        if type(old) is not str or type(new) is not str or not absolute_document_path(old) or not absolute_document_path(new):
            raise ValueError("Replacement paths must be absolute strings")
        key, target = _path_identity(old), _path_identity(new)
        if key in result or target in result.values() or key == target:
            raise ValueError("Ambiguous replacement paths")
        result[key] = target
    if set(result).intersection(result.values()):
        raise ValueError("Path replacement chains or cycles are forbidden")
    return result


def _mapped_snapshot(value, replacements, key=None):
    if type(value) is dict:
        return {name: _mapped_snapshot(item, replacements, name) for name, item in value.items()}
    if type(value) is list:
        return [_mapped_snapshot(item, replacements, key) for item in value]
    if key in {"path", "document_path"} and type(value) is str and value:
        normalized = _path_identity(value)
        return replacements.get(normalized, normalized)
    return value


def _report():
    return dict(status="error", phase="preflight", may_continue=False, mutation_attempted=False,
        model_saved=False, production_release=False, collision_verified=False,
        internal_document_id_verified=False)


def inspect_native_assembly(sw, *, process_id, expected_document_path, expected_file_sha256,
        receipt_path, expected_snapshot_path=None, expected_snapshot_sha256=None, path_replacements=None):
    """读取当前已保存装配及轴所属实例；可与带哈希基线和明确路径映射逐项比较。"""
    report = _report(); receipt = None
    try:
        path = _path(expected_document_path, {".sldasm"})
        if _file_hash(path) != _hash(expected_file_sha256):
            raise ValueError("Assembly file SHA differs")
        mapping = _path_map(path_replacements)
        if (expected_snapshot_path is None) != (expected_snapshot_sha256 is None):
            raise ValueError("Baseline path and SHA must be paired")
        baseline = _load_json(expected_snapshot_path, expected_snapshot_sha256) if expected_snapshot_path is not None else None
        if baseline is None and mapping:
            raise ValueError("Path replacements require a baseline")
        receipt_candidate = _path(receipt_path, {".json"}, new=True)
        _write_receipt(receipt_candidate, report, create=True); receipt = receipt_candidate
        model, report["document_before"] = _guard(sw, process_id, path, clean=True)
        report["phase"] = "reading_structure"; report["snapshot"] = {}
        _snapshot(model, report["snapshot"])
        _, report["document_after"] = _guard(sw, process_id, path)
        if report["document_before"] != report["document_after"] or _file_hash(path) != expected_file_sha256:
            raise ValueError("Document or saved file changed during inspection")
        report["source_file_unchanged"] = True
        report["snapshot_matches_expected"] = None
        if baseline is not None:
            expected = baseline.get("snapshot", baseline)
            report["snapshot_matches_expected"] = _mapped_snapshot(expected, mapping) == _mapped_snapshot(report["snapshot"], {})
            if not report["snapshot_matches_expected"]:
                raise ValueError("Native assembly snapshot differs from the explicit baseline")
        report.update(status="review_required", phase="complete", readback_complete=True,
            reason="NATIVE_READBACK_REQUIRES_ENGINEERING_REVIEW")
    except Exception as exc:
        report.update(status="error", error=_error(exc))
    finally:
        if receipt is not None:
            _write_receipt(receipt, report)
    return report


def _set_time(study, target, guard, *, timeout_seconds=10.0, clock=time.monotonic, sleeper=time.sleep):
    # 只重试已验证幂等的时间游标；任何 COM 异常立即离开，不重放原生动作。
    started = clock(); attempt = 0
    while True:
        guard(); attempt += 1
        active = _bool(_member(study, "IsActive")); playing = _bool(_member(study, "IsPlaying"))
        if playing:
            raise ValueError("Existing study is playing; no Stop or takeover is permitted")
        returned = _bool(call(study, "SetTime", target)) if active else False
        actual = _number(call(study, "GetTime"))
        if returned and abs(actual - target) <= 1e-8:
            return {"requested_time": target, "actual_time": actual, "attempt": attempt}
        if clock() - started >= timeout_seconds:
            raise TimeoutError("Study time was not confirmed before the bounded deadline")
        sleeper(min(.1, max(0, timeout_seconds - (clock() - started))))


def _samples(baseline, tracked):
    if type(baseline) is not dict:
        raise ValueError("Baseline object required")
    rows = _array(baseline.get("sampled_transforms"), 1001, "sampled transforms")
    if not rows or rows[0].get("time") != 0:
        raise ValueError("Baseline must start at time zero")
    previous = -1.0; result = []
    for row in rows:
        timestamp = _number(row["time"])
        if timestamp <= previous or type(row.get("transforms")) is not dict or set(row["transforms"]) != set(tracked):
            raise ValueError("Baseline requires ascending times and exact logical keys")
        previous = timestamp
        result.append({"time": timestamp, "transforms": {key: _vector(value, 16) for key, value in row["transforms"].items()}})
    return result


def _max_delta(actual, expected):
    return max(abs(a-b) for a, b in zip(actual, expected))


def audit_native_animation(sw, *, process_id, expected_document_path, expected_file_sha256,
        receipt_path, study_name, explode_view_name, baseline_samples_path, baseline_samples_sha256,
        tracked_components, matrix_tolerance=1e-8):
    """只调整明确既有算例的展示/时间，逐帧比较原生矩阵并确认回到零时刻；绝不计算或保存。"""
    report = _report(); receipt = None; study = None; ready = False
    report.update(sampled_transforms=[], sampled_transforms_complete=False, time_zero_restored=False,
                  closed_poses_verified=False, animation_comparison_verified=False)
    try:
        path = _path(expected_document_path, {".sldasm"})
        if _file_hash(path) != _hash(expected_file_sha256):
            raise ValueError("Assembly file SHA differs")
        tolerance = _number(matrix_tolerance)
        if not 0 < tolerance <= 1e-6:
            raise ValueError("Matrix tolerance must be positive and at most 1e-6")
        if not _str(study_name) or not _str(explode_view_name):
            raise ValueError("Exact study and explode view names required")
        if type(tracked_components) is not list or not 1 <= len(tracked_components) <= 16:
            raise ValueError("One to sixteen tracked instances required")
        tracked = {}; signatures = set()
        for row in tracked_components:
            if type(row) is not dict or set(row) != {"key", "reference", "path"}:
                raise ValueError("Exact key/reference/path tracking fields required")
            if not _str(row["key"]) or not _str(row["reference"]) or not absolute_document_path(_str(row["path"])):
                raise ValueError("Exact tracked component identity required")
            signature = (row["reference"], _path_identity(row["path"]))
            if row["key"] in tracked or signature in signatures:
                raise ValueError("Duplicate tracked component")
            tracked[row["key"]] = row; signatures.add(signature)
        baseline = _load_json(baseline_samples_path, baseline_samples_sha256)
        samples = _samples(baseline, tracked)
        closed = baseline.get("initial_closed_poses")
        if closed is not None:
            if type(closed) is not dict or len(closed) > 1024:
                raise ValueError("Invalid full closed-pose baseline")
            closed = {_str(name): _vector(value, 16) for name, value in closed.items()}
        candidate = _path(receipt_path, {".json"}, new=True)
        _write_receipt(candidate, report, create=True); receipt = candidate
        model, report["document_before"] = _guard(sw, process_id, path, clean=True)
        def guard():
            _guard(sw, process_id, path)
        cfg = _member(_member(model, "ConfigurationManager"), "ActiveConfiguration")
        views = _array(call(model, "GetExplodedViewNames2", _member(cfg, "Name")), 512, "explode views")
        if explode_view_name not in views:
            raise ValueError("Requested explode view absent")
        component_rows, components = _components(model)
        selected = {}
        for key, specification in tracked.items():
            matches = [row for row in component_rows if row["reference"] == specification["reference"]
                and _path_identity(row["path"]) == _path_identity(specification["path"])]
            if len(matches) != 1:
                raise ValueError("Tracked component identity is absent or ambiguous: " + key)
            selected[key] = components[matches[0]["name"]]
        if closed is not None and set(closed) != set(components):
            raise ValueError("Closed-pose baseline does not cover every actual instance")
        manager = _motion_manager(model)
        if study_name not in _array(call(manager, "GetMotionStudyNames"), 512, "studies"):
            raise ValueError("Requested existing motion study absent")
        study = call(manager, "GetMotionStudy", study_name)
        if study is None or _bool(_member(study, "IsPlaying")):
            raise ValueError("Study unavailable or already playing")
        duration = _number(call(study, "GetDuration"))
        if duration <= 0 or samples[-1]["time"] > duration:
            raise ValueError("Sample times exceed existing duration")
        report.update(study_name=study_name, explode_view_name=explode_view_name, duration_seconds=duration,
            tracked_components=deepcopy(tracked_components), matrix_tolerance=tolerance,
            baseline_samples_sha256=baseline_samples_sha256, baseline_sample_count=len(samples))
        report.update(phase="collapse_explode_intent", mutation_attempted=True)
        _write_receipt(receipt, report)
        _guard(sw, process_id, path, clean=True)
        if _file_hash(path) != expected_file_sha256:
            raise ValueError("Saved assembly changed before presentation mutation")
        if call(model, "ShowExploded2", False, explode_view_name) is not True:
            raise ValueError("Native collapse was not confirmed")
        report["explode_presentation_collapsed"] = True
        report["phase"] = "activate_existing_study_intent"
        _write_receipt(receipt, report); guard()
        if call(study, "Activate") is not True:
            raise ValueError("Existing study activation failed")
        ready = True
        report.update(phase="sample_existing_study_intent", requested_times=[row["time"] for row in samples],
                      final_time_zero_intent=True)
        _write_receipt(receipt, report)
        def request_time(target):
            nonlocal ready
            try:
                return _set_time(study, target, guard)
            except Exception:
                # 原生失败或未确认的时间请求后不再在 finally 重放同一请求。
                ready = False
                raise
        report["nonzero_preload"] = request_time(min(.05, duration/2))
        report["maximum_matrix_delta"] = {key: 0.0 for key in tracked}
        for index, expected in enumerate(samples):
            state = request_time(expected["time"])
            actual = {"time": state["actual_time"], "transforms": {key: _matrix(component) for key, component in selected.items()}}
            report["sampled_transforms"].append(actual)
            for key in tracked:
                delta = _max_delta(actual["transforms"][key], expected["transforms"][key])
                report["maximum_matrix_delta"][key] = max(report["maximum_matrix_delta"][key], delta)
                if delta > tolerance:
                    raise ValueError("Animation matrix differs from baseline: " + key)
            if index == 0:
                report["initial_closed_poses"] = {name: _matrix(component) for name, component in components.items()}
                if closed is not None and any(_max_delta(report["initial_closed_poses"][name], value) > tolerance for name, value in closed.items()):
                    raise ValueError("Initial full assembly pose differs from baseline")
            if index % 25 == 0:
                _write_receipt(receipt, report)
        report["sampled_transforms_complete"] = True
        report["phase"] = "restore_time_zero_intent"; _write_receipt(receipt, report)
        report["time_zero_readback"] = request_time(0.0)
        report["time_zero_restored"] = True; ready = False
        final_rows, final_components = _components(model)
        identities = lambda rows: [{key: value for key, value in row.items() if key != "matrix"} for row in rows]
        report["component_identities_unchanged"] = identities(component_rows) == identities(final_rows)
        if not report["component_identities_unchanged"]:
            raise ValueError("Assembly instances changed during animation sampling")
        report["final_closed_poses"] = {row["name"]: row["matrix"] for row in final_rows}
        if closed is not None:
            if any(_max_delta(report["final_closed_poses"][name], value) > tolerance for name, value in closed.items()):
                raise ValueError("Final full assembly pose differs from baseline")
            report["closed_poses_verified"] = True
        _, report["document_after"] = _guard(sw, process_id, path)
        if _file_hash(path) != expected_file_sha256:
            raise ValueError("Saved assembly changed during animation audit")
        report.update(status="review_required", phase="complete", animation_comparison_verified=True,
            source_file_unchanged=True, reason="SAMPLED_ANIMATION_ONLY_NO_COLLISION_OR_PRODUCTION_APPROVAL")
    except Exception as exc:
        report.update(status="error", error=_error(exc))
    finally:
        # 仅在已激活且身份仍一致时恢复自己的时间游标；不 Stop 或关闭任何文档。
        if ready and receipt is not None:
            try:
                report["phase"] = "error_restore_time_zero_intent"; _write_receipt(receipt, report)
                report["time_zero_readback"] = _set_time(study, 0.0, guard)
                report["time_zero_restored"] = True
            except Exception as exc:
                report["restore_error"] = _error(exc)
        if receipt is not None:
            _write_receipt(receipt, report)
    return report
