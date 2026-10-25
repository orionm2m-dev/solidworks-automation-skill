"""只读选定操作的真实夹持器曲线与 THREAD 默认操作目录；不插入或生成。"""
from __future__ import annotations

from ctypes import byref, c_int
import math

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _collection, _context, _inventory, _typed
from scripts.sw_cam_operation_profile import _integer, _number, _position, _read_profile, _read_tool
from scripts.sw_cam_turn_tool import _reference
from scripts.sw_operation_guard import check_document_target

_MAX_CURVES = 512
_MAX_NAMES = 64


def _converted_shape(value, *, depth=0, budget=None):
    """保存 comtypes 已转换结果的 Python 形状，不声称保留原始 VARIANT/SAFEARRAY。"""
    budget = [256] if budget is None else budget
    budget[0] -= 1
    result = {"python_type": type(value).__name__}
    if budget[0] < 0 or depth > 4:
        return result | {"truncated": True}
    if value is None or type(value) in {bool, int}:
        result["value"] = value
    elif type(value) is float:
        result["value"] = value if math.isfinite(value) else "non_finite"
    elif isinstance(value, str):
        result.update(value=value[:1000], truncated=len(value) > 1000)
    elif isinstance(value, (tuple, list)):
        result.update(length=len(value), truncated=len(value) > _MAX_NAMES,
            items=[_converted_shape(item, depth=depth + 1, budget=budget) for item in value[:_MAX_NAMES]])
    else:
        result["unsupported_type"] = True
    return result


def _catalog(feature, read, result, names_budget):
    raw = read(feature, "IGetAllDefaultOperations", 12)
    result["converted_result_shape"] = _converted_shape(raw)
    result["native_variant_metadata_preserved"] = False
    result["operation_type"] = 12
    result["entries"] = []
    names = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, (tuple, list)) else None
    if (names is None or names_budget[0] + len(names) > _MAX_NAMES or
            any(not isinstance(name, str) or not name or len(name) > 1000 for name in names)):
        result.update(names_resolved=False, reason="unsupported_or_oversized_catalog_shape")
        return
    names_budget[0] += len(names)
    for name in names:
        item = {"name": name, "lookup_attempted": True}
        result["entries"].append(item)
        item["tdb_id_raw"] = _integer(read(feature, "GetTdbIdForDefaultOperation", 12, name))
        item["id_validity_assumed"] = False
    result["names_resolved"] = True


def _holder_profile(holder, operation, typelib_path, choice, read, result):
    method = "GetHolderProfile" if choice == "operation" else "GetHolderProfileInDownLeftOrientation"
    result.update(source_method=method, coordinate_frame_verified=False, units_verified=False,
                  solid_geometry_verified=False, chains=[])
    raw_chain = read(holder, method, operation)
    if raw_chain is None or not bool(raw_chain):
        result.update(available=False, reason="native_profile_is_null")
        return
    chain = _typed(raw_chain, "ICWSegChain", typelib_path)
    count = _integer(read(chain, "IGetNumChains"))
    if not 0 <= count <= 32:
        raise ValueError("Holder profile chain count exceeds the read-only limit")
    result["chain_count"] = count
    result["curve_count"] = 0
    result["index_basis"] = "zero_based_vendor_Features_and_Setups_sample"
    complete = count > 0
    for chain_index in range(count):
        data = {"chain_index": chain_index, "curves": []}
        result["chains"].append(data)
        ncurves = _integer(read(chain, "GetNumOfCurves"))
        if ncurves < 0 or result["curve_count"] + ncurves > _MAX_CURVES:
            raise ValueError("Holder profile curve count exceeds the read-only limit")
        data["curve_count"] = ncurves
        result["curve_count"] += ncurves
        complete = complete and ncurves > 0
        for index in range(ncurves):
            item = {"curve_index": index}
            data["curves"].append(item)
            native_index = c_int(index)
            raw_curve = read(chain, "GetCurveAtIndex", byref(native_index))
            curve = _typed(raw_curve, "ICWCurve", typelib_path)
            kind = _integer(read(curve, "GetTypeOfCurve"))
            item["curve_type_raw"] = kind
            item["start_native"] = _position(read(curve, "GetStart"), typelib_path, read)
            item["end_native"] = _position(read(curve, "GetEnd"), typelib_path, read)
            if kind == 0:
                item["parameters_complete"] = True
            elif kind == 1:
                item["mid_native"] = _position(read(curve, "GetMid"), typelib_path, read)
                arc = _typed(raw_curve, "ICWArc", typelib_path)
                item["centre_native"] = _position(read(arc, "CenterPoint"), typelib_path, read)
                item["radius_native"] = _number(read(arc, "IGetRadius"))
                item["sense_raw"] = _integer(read(arc, "IGetSense"))
                item["sense_semantics_verified"] = False
                item["parameters_complete"] = True
            else:
                item["parameters_complete"] = False
                item["reason"] = "curve_type_specific_parameters_not_qualified"
                complete = False
        if chain_index + 1 < count:
            raw_chain = read(chain, "IGetNextChain")
            if raw_chain is None or not bool(raw_chain):
                raise ValueError("Holder profile chain ended before the declared count")
            chain = _typed(raw_chain, "ICWSegChain", typelib_path)
    result.update(available=True, parameters_complete=complete)


def inspect_qualification_context(sw, clsid, typelib_path, *, expected_document_path,
        setup_index, operation_index, expected_operation_type, linked_feature_indices, holder_profile):
    """读取指定关联特征的 THREAD 目录和真实夹持器轮廓，返回原始数据和前后快照。

    holder_profile 明确选择 operation/down_left/none；特征索引为零基。
    未确认单位、坐标变换、刀柄可达性、目录兼容性或完整螺纹工艺。
    """
    report = {"status": "error", "mutation_attempted": False, "generation_attempted": False,
              "model_saved": False, "may_continue": False, "thread_inserted": False,
              "thread_process_qualified": False, "holder_fit_verified": False,
              "units_verified": False, "coordinate_frame_verified": False,
              "thread_catalogs": [], "holder_profile": {"requested": holder_profile}}
    stage = "validate_inputs"
    def read(obj, name, *args):
        nonlocal stage
        stage = name
        return _member(obj, name, *args)
    try:
        selected = _reference({"setup_index": setup_index, "operation_index": operation_index,
                               "expected_operation_type": expected_operation_type})
        if holder_profile not in {"operation", "down_left", "none"}:
            raise ValueError("An explicit holder profile choice is required")
        if (not isinstance(linked_feature_indices, list) or not 1 <= len(linked_feature_indices) <= 64 or
                any(type(i) is not int or not 0 <= i <= 63 for i in linked_feature_indices) or
                len(set(linked_feature_indices)) != len(linked_feature_indices)):
            raise ValueError("Explicit unique linked feature indices must be integers in [0, 63]")
        stage = "context"
        before, _doc, _part, machine, _app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        check_document_target(before["path"], before["title"], expected_path=expected_document_path, required=True)
        stage = "inventory_before"
        initial = _inventory(machine, typelib_path)
        report["inventory_before"] = initial
        chosen = next((item for item in initial["operations"] if item["setup_index"] == setup_index
                       and item["operation_index"] == operation_index), None)
        if chosen is None or chosen["turn_operation_type"] != expected_operation_type:
            raise ValueError("Selected operation does not match the expected native type")
        setups = _collection(read(machine, "IGetEnumOpSetups"), typelib_path)
        setup = _typed(setups[setup_index], "ICWBaseOpSetup", typelib_path)
        raw_operations = _collection(read(setup, "IGetEnumOperations"), typelib_path)
        raw_operation = raw_operations[operation_index]
        operation = _typed(raw_operation, "ICWOperation", typelib_path)
        turning = _typed(raw_operation, "ICWTurnOperation", typelib_path)
        if _integer(read(turning, "OpernType")) != expected_operation_type:
            raise ValueError("Selected native operation type changed")
        report["selected_operation"] = selected
        linked = _collection(read(operation, "IGetAllFeatures"), typelib_path)
        report["linked_feature_count"] = len(linked)
        if any(index >= len(linked) for index in linked_feature_indices):
            raise ValueError("Selected linked feature index is outside the native collection")
        profile_budget, names_budget = [0], [0]
        for index in linked_feature_indices:
            item = {"linked_feature_index": index, "profile": {}, "catalog": {}}
            report["thread_catalogs"].append(item)
            _read_profile(linked[index], typelib_path, read, profile_budget, item["profile"])
            feature = _typed(linked[index], "ICWTurnFeature", typelib_path)
            _catalog(feature, read, item["catalog"], names_budget)
        if holder_profile != "none":
            raw_tool = read(operation, "IGetTool")
            tool = _typed(raw_tool, "ICWTool", typelib_path)
            if _integer(read(tool, "ToolType")) != 15:
                raise ValueError("Holder profile requires an actual turning tool (ToolType=15)")
            report["tool"] = {}
            _read_tool(raw_tool, operation, typelib_path, read, report["tool"])
            turn_tool = _typed(raw_tool, "ICWTurnTool", typelib_path)
            raw_holder = read(turn_tool, "IGetTurnToolHolder")
            if raw_holder is None or not bool(raw_holder):
                report["holder_profile"].update(available=False, reason="native_holder_is_null")
            else:
                holder = _typed(raw_holder, "ICWTurnToolHolder", typelib_path)
                _holder_profile(holder, operation, typelib_path, holder_profile, read, report["holder_profile"])
        else:
            report["holder_profile"].update(available=False, reason="not_requested")
        stage = "inventory_after"
        after_inventory = _inventory(machine, typelib_path)
        stage = "document_after"
        after = document_snapshot(sw)
        report.update(inventory_after=after_inventory, document_after=after,
                      inventory_unchanged=initial == after_inventory, active_document_unchanged=before == after)
        same = initial == after_inventory and before == after
        catalogs = all(item["catalog"].get("names_resolved") for item in report["thread_catalogs"])
        holder = holder_profile == "none" or report["holder_profile"].get("parameters_complete", False)
        report["status"] = "ok" if same and catalogs and holder else "review_required"
        if not same:
            report["reason"] = "CAM_STATE_CHANGED_DURING_CONTEXT_INSPECTION"
        elif not catalogs or not holder:
            report["reason"] = "CAM_CONTEXT_DATA_INCOMPLETE"
    except Exception as exc:
        report.update(status="error", reason="CAM_QUALIFICATION_CONTEXT_INSPECTION_FAILED",
                      failed_stage=stage, issue=_error(exc))
    return report
