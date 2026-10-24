"""独立试件的整文档 CAM 仿真与证据导出；不保存零件、不输出 NC。"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
import time

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _context, _inventory, _typed, _write_receipt
from scripts.sw_operation_guard import absolute_document_path, check_document_target


class _ReviewRequired(RuntimeError):
    """已观察到的 CAM 消息或文档变化阻止后续导出。"""


def _messages_problem(value):
    return bool(not value.get("subscribed") or value.get("event_count") or value.get("overflow")
                or value.get("callback_error_count") or value.get("callback_errors")
                or value.get("subscription_error") or value.get("disconnect_errors"))


def _file_evidence(path):
    """只验证新文件存在且非空并计算散列；图像和网格需另行复核。"""
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("CAM did not produce a nonempty regular output file")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    if size <= 0 or path.stat().st_size != size:
        raise ValueError("CAM output changed during hashing")
    return {"path": str(path), "native_path": str(path), "canonical_path": str(path.resolve(strict=True)),
            "bytes": size, "sha256": digest.hexdigest(), "content_reviewed": False}


def _prepare_output(*, expected_document_path, expected_feature_count, expected_operation_count,
                    expected_operation_setup_count, expected_generated_operation_count, output_dir,
                    qualification_only, acknowledge_document_wide_simulation, message_policy, allow_prepath_geometry_counts=False):
    """校验显式试件范围并独占创建目录，禁止重放或覆盖已有证据。"""
    if (qualification_only is not True or acknowledge_document_wide_simulation is not True
            or message_policy != "vendor_default"):
        raise ValueError("Explicit qualification/document-wide acknowledgement and vendor_default policy are required")
    counts = {"feature_count": expected_feature_count, "operation_count": expected_operation_count,
              "operation_setup_count": expected_operation_setup_count,
              "generated_operation_count": expected_generated_operation_count}
    for key, value in counts.items():
        maximum = 262144 if key == "feature_count" else 512
        minimum = 0 if allow_prepath_geometry_counts else 1
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"expected_{key} must be an integer in [{minimum}, {maximum}]")
    if expected_generated_operation_count > expected_operation_count:
        raise ValueError("Generated operation count exceeds operation count")
    if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("An exact absolute saved qualification SLDPRT path is required")
    directory = Path(output_dir)
    if not directory.is_absolute() or not directory.parent.is_dir():
        raise ValueError("A new absolute output directory with an existing parent is required")
    canonical_parent = directory.parent.resolve(strict=True)
    directory.mkdir()  # 不复用旧目录；超时或失败不能重放已有任务。
    canonical_directory = directory.resolve(strict=True)
    if canonical_directory.parent != canonical_parent:
        raise ValueError("Output directory moved outside its verified parent")
    # 保留调用方明确指定的盘符形式给原生 API；规范路径只用于边界和回执。
    return counts, directory, canonical_directory


def _check_output_path(path, directory, canonical_directory):
    """校验目录映射和固定输出边界，不把盘符路径改写为 UNC。"""
    if directory.resolve(strict=True) != canonical_directory or path.parent != directory:
        raise ValueError("Native output directory identity changed")
    if path.exists() or path.is_symlink():
        raise FileExistsError("Native output already exists")
    if path.resolve(strict=False).parent != canonical_directory:
        raise ValueError("Native output escapes the verified output directory")


def run_simulation(sw, clsid, typelib_path, *, expected_document_path, expected_feature_count,
                   expected_operation_count, expected_operation_setup_count, expected_generated_operation_count,
                   output_dir, qualification_only, acknowledge_document_wide_simulation, message_policy):
    """在调用方的 PID 锁内执行一次整文档仿真和 JPG/STL 导出。

    仅接受明确确认的独立已保存试件、精确清单和新的绝对输出目录。
    返回持久回执及文件证据；方法返回不等于异步完成或制造质量已验证。
    """
    counts, directory, canonical_directory = _prepare_output(
        expected_document_path=expected_document_path, expected_feature_count=expected_feature_count,
        expected_operation_count=expected_operation_count, expected_operation_setup_count=expected_operation_setup_count,
        expected_generated_operation_count=expected_generated_operation_count, output_dir=output_dir,
        qualification_only=qualification_only, acknowledge_document_wide_simulation=acknowledge_document_wide_simulation,
        message_policy=message_policy)
    receipt = canonical_directory / "receipt.json"
    image_path, stl_path = directory / "simulation.jpg", directory / "simulation.stl"
    report = {"status": "started", "phase": "preflight", "scope": "entire_active_cam_document",
              "qualification_only": True, "acknowledge_document_wide_simulation": True,
              "expected_document_path": expected_document_path, "expected_counts": counts,
              "output_dir": str(directory), "output_dir_canonical": str(canonical_directory), "receipt_path": str(receipt),
              "mutation_attempted": False, "native_call_returned": False,
              "native_completion_verified": False, "export_files_verified": False,
              "model_saved": False, "nc_exported": False, "explicit_gtp_requested": False,
              "simulation_ui_launched": False, "single_operation_scope_claimed": False,
              "production_process_qualified": False, "may_continue": False,
              "required_reviews": ["simulation_image_visual_review", "stl_mesh_readback"],
              "message_policy": "vendor_default", "default_response_is_not_cancellation": True,
              "exports": {}}
    _write_receipt(receipt, report, create=True)
    messages = None
    started = time.monotonic()
    try:
        before, doc, _part, machine, app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        check_document_target(before["path"], before["title"], expected_path=expected_document_path, required=True)
        if before["type"] != 1 or before["needs_save"]:
            raise ValueError("Simulation requires a clean saved qualification part")
        initial = _inventory(machine, typelib_path)
        report["inventory_before"] = initial
        generated = [op for op in initial["operations"] if op["toolpath_generated"]]
        if (any(initial[key] != counts[key] for key in ("feature_count", "operation_count", "operation_setup_count"))
                or len(generated) != expected_generated_operation_count):
            raise ValueError("CAM inventory differs from the explicit simulation preconditions")
        if any(not op["toolpath_record_counts"] or sum(op["toolpath_record_counts"]) <= 0 for op in generated):
            raise ValueError("Every generated operation must contain toolpath records")
        simulation_doc = _typed(doc, "ICWDoc3", typelib_path)
        messages = CamMessageSession(app, typelib_path)

        def guard():
            snapshot = document_snapshot(sw)
            report["document_after"] = snapshot
            if snapshot is None or any(before[key] != snapshot[key] for key in ("path", "title", "type")):
                raise _ReviewRequired("CAM_DOCUMENT_CHANGED")
            check_document_target(snapshot["path"], snapshot["title"], expected_path=expected_document_path, required=True)
            report["messages"] = messages.summary()
            if _messages_problem(report["messages"]):
                raise _ReviewRequired("CAM_MESSAGES_REQUIRE_REVIEW")
            return snapshot

        with messages:
            if guard() != before or _inventory(machine, typelib_path) != initial:
                raise ValueError("Document or CAM inventory changed before simulation")
            if guard() != before:
                raise ValueError("Document changed during the final simulation preflight")
            report.update(phase="RunSimulationSilent", mutation_attempted=True)
            _write_receipt(receipt, report)
            if guard() != before:
                raise ValueError("Document changed before the native simulation call")
            result = _member(simulation_doc, "RunSimulationSilent", True, False, False)
            report["native_call_returned"] = True
            if (not isinstance(result, (tuple, list)) or len(result) != 2
                    or any(type(value) is not int or value < 0 for value in result)):
                raise ValueError("Unexpected RunSimulationSilent output contract")
            report["simulation_return"] = {"gouges": result[0], "undercuts": result[1],
                                            "meaning_beyond_vendor_labels_verified": False}
            report["phase"] = "native_call_returned"
            _write_receipt(receipt, report)
            guard()
            report["inventory_after_simulation"] = _inventory(machine, typelib_path)
            report["inventory_changed_by_simulation"] = report["inventory_after_simulation"] != initial
            guard()
            _check_output_path(image_path, directory, canonical_directory)
            report.update(phase="ActiveDocSaveSimulationImage", image_export_attempted=True,
                          image_export_native_path=str(image_path))
            _write_receipt(receipt, report)
            guard()
            _check_output_path(image_path, directory, canonical_directory)
            saved = _member(app, "ActiveDocSaveSimulationImage", str(image_path))
            report["image_export_return"] = {"saved": saved if type(saved) is bool else None,
                                             "contract_valid": type(saved) is bool}
            if saved is not True:
                raise ValueError("CAM image export did not return boolean True")
            report["exports"]["image"] = _file_evidence(image_path)
            _write_receipt(receipt, report)
            guard()
            _check_output_path(stl_path, directory, canonical_directory)
            report.update(phase="ActiveDocSaveStlFileFromSimulation", stl_export_attempted=True,
                          stl_export_native_path=str(stl_path))
            _write_receipt(receipt, report)
            guard()
            # 已安装类型库的 out 顺序为 error code, retval BOOL，不能反转。
            _check_output_path(stl_path, directory, canonical_directory)
            result = _member(app, "ActiveDocSaveStlFileFromSimulation", str(stl_path), "", 0)
            if (not isinstance(result, (tuple, list)) or len(result) != 2
                    or type(result[0]) is not int or type(result[1]) is not bool):
                raise ValueError("Unexpected simulation STL export output contract")
            report["stl_export_return"] = {"error_code": result[0], "saved": result[1],
                                           "coordinate_system": "default", "units": "millimeters", "unit_code": 0}
            if result[0] != 0 or result[1] is not True:
                raise ValueError("CAM STL export reported failure")
            report["exports"]["stl"] = _file_evidence(stl_path)
            _write_receipt(receipt, report)
            guard()
            report["inventory_after"] = _inventory(machine, typelib_path)
            report["inventory_changed"] = report["inventory_after"] != initial
            report["export_files_verified"] = True
        report["messages"] = messages.summary()
        # 清理事件连接本身也可能产生消息，之后重新检查文档身份。
        guard()
        if not report["messages"].get("disconnected"):
            raise _ReviewRequired("CAM_EVENT_CLEANUP_NOT_CONFIRMED")
        report.update(status="review_required", reason="SIMULATION_OUTPUTS_REQUIRE_REVIEW")
    except Exception as exc:
        report.update(status="review_required" if isinstance(exc, _ReviewRequired) else
                      ("uncertain" if report["mutation_attempted"] and not report["native_call_returned"] else "error"),
                      reason=str(exc) if isinstance(exc, _ReviewRequired) else "CAM_SIMULATION_OR_EXPORT_FAILED",
                      issue=_error(exc))
    finally:
        if messages is not None:
            report["messages"] = messages.summary()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["phase_at_finish"] = report["phase"]
        report["phase"] = "finished"
        try:
            _write_receipt(receipt, report)
        except Exception as exc:
            report.update(status="uncertain", reason="CAM_RECEIPT_UPDATE_FAILED", receipt_write_error=_error(exc))
    return report


def preview_simulation(sw, clsid, typelib_path, *, action, expected_document_path, expected_feature_count,
                       expected_operation_count, expected_operation_setup_count, expected_generated_operation_count,
                       output_dir, qualification_only, acknowledge_document_wide_simulation, message_policy):
    """通过 CAM API 打开并播放、导出现有状态，或显式关闭仿真预览。

    每次动作使用新的持久目录；只在 close 动作关闭，不重新静默仿真或生成刀路。
    原生方法返回不证明播放完成或窗口可见，图像与 STL 分别记录结果。
    """
    if action not in {"launch_play", "export_state", "close"}:
        raise ValueError("Unsupported CAM preview action")
    counts, directory, canonical_directory = _prepare_output(
        expected_document_path=expected_document_path, expected_feature_count=expected_feature_count,
        expected_operation_count=expected_operation_count, expected_operation_setup_count=expected_operation_setup_count,
        expected_generated_operation_count=expected_generated_operation_count, output_dir=output_dir,
        qualification_only=qualification_only, acknowledge_document_wide_simulation=acknowledge_document_wide_simulation,
        message_policy=message_policy)
    receipt = canonical_directory / "receipt.json"
    report = {"status": "started", "phase": "preflight", "action": action,
              "scope": "entire_active_cam_document", "qualification_only": True,
              "acknowledge_document_wide_simulation": True, "expected_document_path": expected_document_path,
              "expected_counts": counts, "output_dir": str(directory), "output_dir_canonical": str(canonical_directory), "receipt_path": str(receipt),
              "mutation_attempted": False, "native_calls": [], "native_calls_returned": False,
              "native_completion_verified": False, "playback_completion_verified": False,
              "preview_visibility_verified": False, "preview_close_requested": False,
              "silent_simulation_requested": False, "explicit_gtp_requested": False,
              "model_saved": False, "nc_exported": False, "single_operation_scope_claimed": False,
              "production_process_qualified": False, "may_continue": False,
              "message_policy": "vendor_default", "default_response_is_not_cancellation": True,
              "exports": {}, "export_errors": {}, "export_files_verified": False}
    _write_receipt(receipt, report, create=True)
    messages = None
    started = time.monotonic()
    try:
        before, _doc, _part, machine, app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        check_document_target(before["path"], before["title"], expected_path=expected_document_path, required=True)
        if before["type"] != 1 or before["needs_save"]:
            raise ValueError("Preview actions require a clean saved qualification part")
        initial = _inventory(machine, typelib_path)
        report["inventory_before"] = initial
        generated = [op for op in initial["operations"] if op["toolpath_generated"]]
        if (any(initial[key] != counts[key] for key in ("feature_count", "operation_count", "operation_setup_count"))
                or len(generated) != expected_generated_operation_count
                or any(not op["toolpath_record_counts"] or sum(op["toolpath_record_counts"]) <= 0 for op in generated)):
            raise ValueError("CAM inventory differs from the explicit preview preconditions")
        messages = CamMessageSession(app, typelib_path)

        def guard():
            snapshot = document_snapshot(sw)
            report["document_after"] = snapshot
            if snapshot is None or any(snapshot[key] != before[key] for key in ("path", "title", "type")):
                raise _ReviewRequired("CAM_DOCUMENT_CHANGED")
            check_document_target(snapshot["path"], snapshot["title"], expected_path=expected_document_path, required=True)
            report["messages"] = messages.summary()
            if _messages_problem(report["messages"]):
                raise _ReviewRequired("CAM_MESSAGES_REQUIRE_REVIEW")
            return snapshot

        def prepare_call(name, native_path=None):
            guard()
            if not report["native_calls"] and guard() != before:
                raise ValueError("Document changed before the first preview action")
            report.update(phase=name, mutation_attempted=True)
            call = {"method": name, "returned": False}
            if native_path is not None:
                call["native_path"] = native_path
            report["native_calls"].append(call)
            _write_receipt(receipt, report)
            current = guard()
            if len(report["native_calls"]) == 1 and current != before:
                raise ValueError("Document changed before the first native preview call")
            return call

        with messages:
            if guard() != before or _inventory(machine, typelib_path) != initial or guard() != before:
                raise ValueError("Document or CAM plan changed during preview preflight")
            if action in {"launch_play", "close"}:
                methods = ("ActiveDocCloseSimulation",) if action == "close" else ("ActiveDocLaunchSimulation", "ActiveDocPlaySimulation")
                for name in methods:
                    call = prepare_call(name)
                    if action == "close":
                        report["preview_close_requested"] = True
                        _write_receipt(receipt, report)
                    _member(app, name)
                    call["returned"] = True
                    _write_receipt(receipt, report)
                    guard()
                    stage = {"ActiveDocLaunchSimulation": "launch", "ActiveDocPlaySimulation": "play",
                             "ActiveDocCloseSimulation": "close"}[name]
                    report["inventory_after_" + stage] = _inventory(machine, typelib_path)
                    guard()
                report.update(status="review_required", reason="CAM_PREVIEW_CLOSE_RETURNED_REQUIRES_OBSERVATION" if
                              action == "close" else "CAM_PREVIEW_REQUIRES_OBSERVATION")
            else:
                for kind, name, suffix in (("image", "ActiveDocSaveSimulationImage", ".jpg"),
                                           ("stl", "ActiveDocSaveStlFileFromSimulation", ".stl")):
                    guard()
                    path = directory / ("simulation" + suffix)
                    # 单项导出失败不代表另一种格式不可用；守卫失败仍停止所有后续调用。
                    try:
                        _check_output_path(path, directory, canonical_directory)
                    except (ValueError, OSError) as exc:
                        report["export_errors"][kind] = _error(exc)
                        _write_receipt(receipt, report)
                        continue
                    call = prepare_call(name, native_path=str(path))
                    try:
                        _check_output_path(path, directory, canonical_directory)
                        result = _member(app, name, str(path), "", 0) if kind == "stl" else _member(app, name, str(path))
                        call["returned"] = True
                        if kind == "image":
                            call["saved"] = result if type(result) is bool else None
                            if result is not True:
                                raise ValueError("CAM image export did not return boolean True")
                        else:
                            if (not isinstance(result, (tuple, list)) or len(result) != 2
                                    or type(result[0]) is not int or type(result[1]) is not bool):
                                raise ValueError("Unexpected simulation STL export output contract")
                            call.update(error_code=result[0], saved=result[1], units="millimeters", unit_code=0)
                            if result[0] != 0 or result[1] is not True:
                                raise ValueError("CAM STL export reported failure")
                        report["exports"][kind] = _file_evidence(path)
                    except Exception as exc:
                        report["export_errors"][kind] = _error(exc)
                    _write_receipt(receipt, report)
                    guard()
                report["export_files_verified"] = len(report["exports"]) == 2
                report.update(status="review_required", reason="SIMULATION_OUTPUTS_REQUIRE_REVIEW" if report["exports"]
                              else "CAM_SIMULATION_EXPORTS_UNAVAILABLE",
                              required_reviews=["simulation_image_visual_review", "stl_mesh_readback"])
            guard()
            report["inventory_after"] = _inventory(machine, typelib_path)
            report["inventory_changed"] = report["inventory_after"] != initial
        guard()
        if not report["messages"].get("disconnected"):
            raise _ReviewRequired("CAM_EVENT_CLEANUP_NOT_CONFIRMED")
    except Exception as exc:
        report.update(status="review_required" if isinstance(exc, _ReviewRequired) else
                      ("uncertain" if any(not call["returned"] for call in report["native_calls"]) else "error"),
                      reason=str(exc) if isinstance(exc, _ReviewRequired) else "CAM_PREVIEW_FAILED", issue=_error(exc))
    finally:
        if messages is not None:
            report["messages"] = messages.summary()
        report["native_calls_returned"] = bool(report["native_calls"]) and all(call["returned"] for call in report["native_calls"])
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["phase_at_finish"] = report["phase"]
        report["phase"] = "finished"
        try:
            _write_receipt(receipt, report)
        except Exception as exc:
            report.update(status="uncertain", reason="CAM_RECEIPT_UPDATE_FAILED", receipt_write_error=_error(exc))
    return report


def export_geometry(sw, clsid, typelib_path, *, expected_document_path, expected_feature_count,
                    expected_operation_count, expected_operation_setup_count, expected_generated_operation_count,
                    output_dir, qualification_only, acknowledge_document_wide_export, message_policy, export_kinds=None):
    """导出整文档的 WIP、原始毛坯和目标几何；不生成刀路或运行仿真。

    仅限明确确认的独立试件和新的本地目录。WIP 包含全部设置，不代表当前仿真帧；
    返回原生 BOOL、实际文件和散列，坐标、单位及网格内容仍需独立复核。
    """
    kinds = ["wip"] if export_kinds is None else export_kinds
    if (type(kinds) is not list or not 1 <= len(kinds) <= 3
            or any(type(kind) is not str or kind not in {"wip", "stock", "target"} for kind in kinds)
            or len(set(kinds)) != len(kinds)):
        raise ValueError("export_kinds must contain one to three unique wip/stock/target names")
    kinds = list(kinds)
    requested = Path(output_dir)
    if requested.drive.startswith("\\\\") and not re.fullmatch(r"\\\\\?\\[A-Za-z]:", requested.drive):
        raise ValueError("CAM geometry qualification requires a new local output directory")
    if requested.parent.is_dir():
        canonical_drive = requested.parent.resolve(strict=True).drive
        if canonical_drive.startswith("\\\\") and not re.fullmatch(r"\\\\\?\\[A-Za-z]:", canonical_drive):
            raise ValueError("CAM geometry qualification requires a new local output directory")
    counts, directory, canonical_directory = _prepare_output(
        expected_document_path=expected_document_path, expected_feature_count=expected_feature_count,
        expected_operation_count=expected_operation_count, expected_operation_setup_count=expected_operation_setup_count,
        expected_generated_operation_count=expected_generated_operation_count, output_dir=output_dir,
        qualification_only=qualification_only, acknowledge_document_wide_simulation=acknowledge_document_wide_export,
        message_policy=message_policy, allow_prepath_geometry_counts=kinds in (["stock"], ["target"]))
    receipt = canonical_directory / "receipt.json"
    report = {"status": "started", "phase": "preflight", "scope": "entire_active_cam_document",
              "qualification_only": True, "acknowledge_document_wide_export": True,
              "expected_document_path": expected_document_path, "expected_counts": counts,
              "output_dir": str(directory), "output_dir_canonical": str(canonical_directory),
              "receipt_path": str(receipt), "native_calls": [], "mutation_attempted": False,
              "native_calls_returned": False, "export_files_verified": False,
              "attempt_marker_meaning": "durable_intent_before_native_call_not_proof_of_entry",
              "abort_on_export_failure": True, "export_kinds": kinds,
              "exports": {}, "export_errors": {}, "may_continue": False,
              "model_saved": False, "nc_exported": False, "explicit_gtp_requested": False,
              "simulation_requested": False, "simulation_frame_export_claimed": False,
              "production_process_qualified": False, "message_policy": "vendor_default",
              "default_response_is_not_cancellation": True,
              "native_parameters": {"reference_coordinate_system_for_stock_and_wip": "", "unit_code": 0,
                                    "target_reference_frame": "native_FCS",
                                    "wip_quality_code": 0, "wip_quality": "CW_STL_QUALITY_FINE",
                                    "coordinate_system_and_unit_meaning_verified_for_entrypoint": False},
              "required_reviews": ["stl_mesh_readback", "coordinate_system_and_units", "wip_scope_and_removal"]}
    _write_receipt(receipt, report, create=True)
    started = time.monotonic()
    messages = None
    try:
        before, _doc, _part, machine, app = _context(sw, clsid, typelib_path)
        report["document_before"] = before
        check_document_target(before["path"], before["title"], expected_path=expected_document_path, required=True)
        if before["type"] != 1 or before["needs_save"]:
            raise ValueError("Geometry exports require a clean saved qualification part")
        initial = _inventory(machine, typelib_path)
        report["inventory_before"] = initial
        generated = [op for op in initial["operations"] if op["toolpath_generated"]]
        if (any(initial[key] != counts[key] for key in ("feature_count", "operation_count", "operation_setup_count"))
                or len(generated) != expected_generated_operation_count
                or any(not op["toolpath_record_counts"] or sum(op["toolpath_record_counts"]) <= 0 for op in generated)):
            raise ValueError("CAM inventory differs from the explicit geometry export preconditions")
        machine5 = _typed(machine, "ICWMachine5", typelib_path)
        messages = CamMessageSession(app, typelib_path)

        def guard():
            snapshot = document_snapshot(sw)
            report["document_after"] = snapshot
            if snapshot != before:
                raise _ReviewRequired("CAM_DOCUMENT_CHANGED")
            check_document_target(snapshot["path"], snapshot["title"], expected_path=expected_document_path, required=True)
            report["messages"] = messages.summary()
            if _messages_problem(report["messages"]):
                raise _ReviewRequired("CAM_MESSAGES_REQUIRE_REVIEW")
            report["inventory_after"] = _inventory(machine, typelib_path)
            report["inventory_changed"] = report["inventory_after"] != initial
            if report["inventory_changed"]:
                raise _ReviewRequired("CAM_INVENTORY_CHANGED")
            if document_snapshot(sw) != before:
                raise _ReviewRequired("CAM_DOCUMENT_CHANGED")
            # COM getter 本身可能送达事件；最后一次读取之后也必须检查。
            report["messages"] = messages.summary()
            if _messages_problem(report["messages"]):
                raise _ReviewRequired("CAM_MESSAGES_REQUIRE_REVIEW")
            if directory.resolve(strict=True) != canonical_directory:
                raise _ReviewRequired("CAM_OUTPUT_DIRECTORY_CHANGED")

        with messages:
            guard()
            methods = {"wip": ("CreateSTLOfWIPs2", "all_wip_parts_all_setups"),
                       "stock": ("CreateSTLOfStock", "original_workpiece"),
                       "target": ("CreateSTLOfTargetInFCSSpace", "target_part_in_FCS")}
            for index, kind in enumerate(kinds):
                name, source = methods[kind]
                guard()
                path = directory / (kind + ".stl")
                wip_directory = directory / "wip"
                if kind == "wip":
                    _check_output_path(wip_directory, directory, canonical_directory)
                    wip_directory.mkdir()
                    canonical_wip = wip_directory.resolve(strict=True)
                    # 原生实现直接拼接目录与文件名；目录参数必须带 Windows 尾分隔符。
                    args = (str(wip_directory) + os.sep, "wip.stl", "", 0, 0)
                    native_path = str(wip_directory / "wip.stl")
                else:
                    _check_output_path(path, directory, canonical_directory)
                    args = (str(path), 0) if kind == "target" else (str(path), "", 0)
                    native_path = str(path)
                call = {"method": name, "native_path": native_path, "attempted": False, "returned": False}
                if kind == "wip":
                    call["native_folder"] = args[0]
                report["native_calls"].append(call)
                report.update(phase=name, mutation_attempted=True)
                _write_receipt(receipt, report)
                guard()
                # 原生 stock/target 会覆盖文件；紧邻调用再次检查固定输出或空 WIP 目录。
                if kind == "wip":
                    if (wip_directory.is_symlink() or wip_directory.resolve(strict=True) != canonical_wip
                            or any(wip_directory.iterdir())):
                        raise _ReviewRequired("CAM_WIP_OUTPUT_DIRECTORY_CHANGED")
                else:
                    _check_output_path(path, directory, canonical_directory)
                item = {"source": source, "native_return": None, "contract_valid": False,
                        "files": [], "verified": False}
                report["exports"][kind] = item
                try:
                    # 先持久化调用意图；返回后立即持久化 BOOL，期间不访问 CAD。
                    call["attempted"] = True
                    _write_receipt(receipt, report)
                    if kind == "wip":
                        if (wip_directory.is_symlink() or wip_directory.resolve(strict=True) != canonical_wip
                                or any(wip_directory.iterdir())):
                            raise _ReviewRequired("CAM_WIP_OUTPUT_DIRECTORY_CHANGED")
                    else:
                        _check_output_path(path, directory, canonical_directory)
                    report["messages"] = messages.summary()
                    if _messages_problem(report["messages"]):
                        raise _ReviewRequired("CAM_MESSAGES_REQUIRE_REVIEW")
                    result = _member(machine5, name, *args)
                    call["returned"] = True
                    item.update(native_return=result if type(result) is bool else None,
                                contract_valid=type(result) is bool)
                    _write_receipt(receipt, report)
                    # 只读取本次输出文件；原生失败后不得再调用清单/文档或下一种导出。
                    if kind == "wip":
                        if wip_directory.is_symlink() or wip_directory.resolve(strict=True) != canonical_wip:
                            raise _ReviewRequired("CAM_WIP_OUTPUT_DIRECTORY_CHANGED")
                        files = []
                        for count, output in enumerate(wip_directory.rglob("*"), start=1):
                            if count > 1024 or output.is_symlink() or not output.resolve(strict=True).is_relative_to(canonical_wip):
                                raise ValueError("WIP output tree exceeds the verified boundary")
                            if output.is_file():
                                if output.suffix.casefold() != ".stl" or len(files) >= 512:
                                    raise ValueError("Unexpected WIP export file contract")
                                files.append(output)
                        files.sort(key=str)
                    else:
                        files = [path] if path.exists() or path.is_symlink() else []
                    item["files"] = [_file_evidence(output) for output in files]
                    if result is not True or not item["files"]:
                        raise ValueError("CAM geometry export requires boolean True and nonempty STL files")
                    item["verified"] = True
                except _ReviewRequired:
                    raise
                except Exception as exc:
                    report["export_errors"][kind] = _error(exc)
                    report["aborted_after_export"] = kind
                    report["remaining_exports_skipped"] = kinds[index + 1:]
                    # with 只执行事件断开清理；失败不能作为继续探测同一 CAD 会话的依据。
                    raise
                _write_receipt(receipt, report)
                guard()
            report["export_files_verified"] = all(item["verified"] for item in report["exports"].values())
        guard()
        if not report["messages"].get("disconnected"):
            raise _ReviewRequired("CAM_EVENT_CLEANUP_NOT_CONFIRMED")
        report.update(status="review_required", reason="CAM_GEOMETRY_OUTPUTS_REQUIRE_REVIEW" if
                      any(item["files"] for item in report["exports"].values()) else "CAM_GEOMETRY_EXPORTS_UNAVAILABLE")
    except Exception as exc:
        report.update(status="review_required" if isinstance(exc, _ReviewRequired) else
                      ("uncertain" if any(call["attempted"] and not call["returned"] for call in report["native_calls"]) else "error"),
                      reason=str(exc) if isinstance(exc, _ReviewRequired) else "CAM_GEOMETRY_EXPORT_FAILED", issue=_error(exc))
    finally:
        if messages is not None:
            report["messages"] = messages.summary()
        report["native_calls_returned"] = bool(report["native_calls"]) and all(call["returned"] for call in report["native_calls"])
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["phase_at_finish"] = report["phase"]
        report["phase"] = "finished"
        try:
            _write_receipt(receipt, report)
        except Exception as exc:
            report.update(status="uncertain", reason="CAM_RECEIPT_UPDATE_FAILED", receipt_write_error=_error(exc))
    return report
