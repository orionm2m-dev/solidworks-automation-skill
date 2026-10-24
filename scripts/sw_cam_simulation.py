"""独立试件的整文档 CAM 仿真与证据导出；不保存零件、不输出 NC。"""
from __future__ import annotations

import hashlib
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
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest(), "content_reviewed": False}


def _prepare_output(*, expected_document_path, expected_feature_count, expected_operation_count,
                    expected_operation_setup_count, expected_generated_operation_count, output_dir,
                    qualification_only, acknowledge_document_wide_simulation, message_policy):
    """校验显式试件范围并独占创建目录，禁止重放或覆盖已有证据。"""
    if (qualification_only is not True or acknowledge_document_wide_simulation is not True
            or message_policy != "vendor_default"):
        raise ValueError("Explicit qualification/document-wide acknowledgement and vendor_default policy are required")
    counts = {"feature_count": expected_feature_count, "operation_count": expected_operation_count,
              "operation_setup_count": expected_operation_setup_count,
              "generated_operation_count": expected_generated_operation_count}
    for key, value in counts.items():
        maximum = 262144 if key == "feature_count" else 512
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f"expected_{key} must be an integer in [1, {maximum}]")
    if expected_generated_operation_count > expected_operation_count:
        raise ValueError("Generated operation count exceeds operation count")
    if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
            or Path(expected_document_path).suffix.casefold() != ".sldprt"):
        raise ValueError("An exact absolute saved qualification SLDPRT path is required")
    directory = Path(output_dir)
    if not directory.is_absolute() or not directory.parent.is_dir():
        raise ValueError("A new absolute output directory with an existing parent is required")
    directory.mkdir()  # 不复用旧目录；超时或失败不能重放已有任务。
    directory = directory.resolve()
    return counts, directory


def run_simulation(sw, clsid, typelib_path, *, expected_document_path, expected_feature_count,
                   expected_operation_count, expected_operation_setup_count, expected_generated_operation_count,
                   output_dir, qualification_only, acknowledge_document_wide_simulation, message_policy):
    """在调用方的 PID 锁内执行一次整文档仿真和 JPG/STL 导出。

    仅接受明确确认的独立已保存试件、精确清单和新的绝对输出目录。
    返回持久回执及文件证据；方法返回不等于异步完成或制造质量已验证。
    """
    counts, directory = _prepare_output(
        expected_document_path=expected_document_path, expected_feature_count=expected_feature_count,
        expected_operation_count=expected_operation_count, expected_operation_setup_count=expected_operation_setup_count,
        expected_generated_operation_count=expected_generated_operation_count, output_dir=output_dir,
        qualification_only=qualification_only, acknowledge_document_wide_simulation=acknowledge_document_wide_simulation,
        message_policy=message_policy)
    receipt = directory / "receipt.json"
    image_path, stl_path = directory / "simulation.jpg", directory / "simulation.stl"
    report = {"status": "started", "phase": "preflight", "scope": "entire_active_cam_document",
              "qualification_only": True, "acknowledge_document_wide_simulation": True,
              "expected_document_path": expected_document_path, "expected_counts": counts,
              "output_dir": str(directory), "receipt_path": str(receipt),
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
            if image_path.exists():
                raise FileExistsError("Image output path already exists")
            report.update(phase="ActiveDocSaveSimulationImage", image_export_attempted=True)
            _write_receipt(receipt, report)
            guard()
            saved = _member(app, "ActiveDocSaveSimulationImage", str(image_path))
            report["image_export_return"] = {"saved": saved if type(saved) is bool else None,
                                             "contract_valid": type(saved) is bool}
            if saved is not True:
                raise ValueError("CAM image export did not return boolean True")
            report["exports"]["image"] = _file_evidence(image_path)
            _write_receipt(receipt, report)
            guard()
            if stl_path.exists():
                raise FileExistsError("STL output path already exists")
            report.update(phase="ActiveDocSaveStlFileFromSimulation", stl_export_attempted=True)
            _write_receipt(receipt, report)
            guard()
            # 已安装类型库的 out 顺序为 error code, retval BOOL，不能反转。
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
    """通过 CAM API 单独打开并播放仿真，或导出已存在的仿真状态。

    每次动作使用新的持久目录；不关闭预览、不重新调用静默仿真或生成刀路。
    原生方法返回不证明播放完成或窗口可见，图像与 STL 分别记录结果。
    """
    if action not in {"launch_play", "export_state"}:
        raise ValueError("Unsupported CAM preview action")
    counts, directory = _prepare_output(
        expected_document_path=expected_document_path, expected_feature_count=expected_feature_count,
        expected_operation_count=expected_operation_count, expected_operation_setup_count=expected_operation_setup_count,
        expected_generated_operation_count=expected_generated_operation_count, output_dir=output_dir,
        qualification_only=qualification_only, acknowledge_document_wide_simulation=acknowledge_document_wide_simulation,
        message_policy=message_policy)
    receipt = directory / "receipt.json"
    report = {"status": "started", "phase": "preflight", "action": action,
              "scope": "entire_active_cam_document", "qualification_only": True,
              "acknowledge_document_wide_simulation": True, "expected_document_path": expected_document_path,
              "expected_counts": counts, "output_dir": str(directory), "receipt_path": str(receipt),
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

        def prepare_call(name):
            guard()
            if not report["native_calls"] and guard() != before:
                raise ValueError("Document changed before the first preview action")
            report.update(phase=name, mutation_attempted=True)
            call = {"method": name, "returned": False}
            report["native_calls"].append(call)
            _write_receipt(receipt, report)
            current = guard()
            if len(report["native_calls"]) == 1 and current != before:
                raise ValueError("Document changed before the first native preview call")
            return call

        with messages:
            if guard() != before or _inventory(machine, typelib_path) != initial or guard() != before:
                raise ValueError("Document or CAM plan changed during preview preflight")
            if action == "launch_play":
                for name in ("ActiveDocLaunchSimulation", "ActiveDocPlaySimulation"):
                    call = prepare_call(name)
                    _member(app, name)
                    call["returned"] = True
                    _write_receipt(receipt, report)
                    guard()
                    report["inventory_after_" + ("launch" if name == "ActiveDocLaunchSimulation" else "play")] = _inventory(machine, typelib_path)
                    guard()
                report.update(status="review_required", reason="CAM_PREVIEW_REQUIRES_OBSERVATION")
            else:
                for kind, name, suffix in (("image", "ActiveDocSaveSimulationImage", ".jpg"),
                                           ("stl", "ActiveDocSaveStlFileFromSimulation", ".stl")):
                    guard()
                    path = directory / ("simulation" + suffix)
                    # 单项导出失败不代表另一种格式不可用；守卫失败仍停止所有后续调用。
                    if path.exists():
                        report["export_errors"][kind] = {"type": "FileExistsError", "message": "Output already exists"}
                        _write_receipt(receipt, report)
                        continue
                    call = prepare_call(name)
                    try:
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
