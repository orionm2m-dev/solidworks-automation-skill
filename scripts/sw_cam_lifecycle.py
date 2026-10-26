"""订阅 CAM 消息后单次保存或关闭指定文档；不回答窗口、不猜测默认响应。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _context, _inventory, _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, check_document_target, _path_identity


class _MessageBlocked(RuntimeError):
    """收到消息或消息订阅失效后禁止继续访问 CAD。"""


def _target(document, expected_path):
    if document is None or document.get("type") != 1:
        raise ValueError("An active saved part is required")
    check_document_target(document.get("path"), document.get("title"),
                          expected_path=expected_path, required=True)


def _snapshot(sw, clsid, typelib_path, expected_path, *, check=lambda: None):
    """对同一保存零件读取稳定 CAM 清单和文件指纹；调用方已持有 PID 锁。"""
    check()
    initial = document_snapshot(sw)
    check()
    _target(initial, expected_path)
    context_document, _doc, _part, machine, app = _context(sw, clsid, typelib_path)
    check()
    if context_document != initial:
        raise ValueError("Document changed before CAM snapshot")
    inventory = _inventory(machine, typelib_path)
    check()
    saved_hash = _file_hash(initial["path"])
    check()
    repeated_inventory = _inventory(machine, typelib_path)
    check()
    final = document_snapshot(sw)
    check()
    if final != initial or inventory != repeated_inventory:
        raise ValueError("Document or inventory changed during lifecycle snapshot")
    if _file_hash(initial["path"]) != saved_hash:
        raise ValueError("Saved file changed during lifecycle snapshot")
    check()
    return {"document": initial, "inventory": inventory, "saved_file_sha256": saved_hash}, app


def _open_documents(sw, expected_path, *, check=lambda: None):
    """关闭后仅访问 SOLIDWORKS 文档元数据，绝不访问自动激活文档的 CAM。"""
    check()
    documents = _member(sw, "GetDocuments")
    check()
    if documents is None:
        documents = ()
    if not isinstance(documents, (tuple, list)) or len(documents) > 256:
        raise ValueError("Open document enumeration is not a bounded array")
    result = []
    target_identity = _path_identity(expected_path)
    for document in documents:
        row = {}
        for key, method in (("path", "GetPathName"), ("title", "GetTitle"), ("type", "GetType")):
            check()
            row[key] = _member(document, method)
            check()
        if not isinstance(row["path"], str) or not isinstance(row["title"], str) or type(row["type"]) is not int:
            raise ValueError("Invalid open document metadata")
        result.append(row)
        if row["path"] and _path_identity(row["path"]) == target_identity:
            raise ValueError("Target document remains open after native close returned")
    return result


def _verify_save(before, after):
    expected = deepcopy(before)
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    expected["saved_file_sha256"] = after["saved_file_sha256"]
    if expected != after:
        raise ValueError("Save changed document identity or CAM inventory")


def document_lifecycle(sw, clsid, typelib_path, *, expected_document_path, action,
                       message_policy="vendor_default", expected_state_sha256=None,
                       receipt_path=None, machine_kind="turn", process_id=None,
                       acknowledge_qualification_copy=False, expected_feature_native_id=None,
                       expected_operation_native_ids=None):
    """准备状态指纹，或显式单次保存/关闭精确工作副本；不自动重试。

    prepare 只读且不接收回执。save/close 要求先前 SHA 和新的绝对 JSON 回执。
    close 要求 SOLIDWORKS 脏标志为假；CAM Save Restore 标志及默认响应仍未知。
    原生方法返回不证明 CAM 数据持久化；本方法从不自动再次关闭、保存或生成。
    """
    if machine_kind == "mill_single_feature_qualification":
        from scripts.sw_cam_mill_feature_lifecycle import mill_feature_document_lifecycle
        return mill_feature_document_lifecycle(sw, clsid, typelib_path,
            expected_document_path=expected_document_path, action=action,
            process_id=process_id, acknowledge_qualification_copy=acknowledge_qualification_copy,
            expected_feature_native_id=expected_feature_native_id,
            expected_operation_native_ids=expected_operation_native_ids,
            message_policy=message_policy, expected_state_sha256=expected_state_sha256,
            receipt_path=receipt_path)
    if expected_feature_native_id is not None or expected_operation_native_ids is not None:
        raise ValueError("Feature/operation selectors require mill_single_feature_qualification")
    if machine_kind == "mill_qualification":
        from scripts.sw_cam_mill_lifecycle import mill_document_lifecycle
        return mill_document_lifecycle(sw, clsid, typelib_path,
            expected_document_path=expected_document_path, action=action,
            process_id=process_id, acknowledge_qualification_copy=acknowledge_qualification_copy,
            message_policy=message_policy, expected_state_sha256=expected_state_sha256,
            receipt_path=receipt_path)
    if machine_kind != "turn" or process_id is not None or acknowledge_qualification_copy is not False:
        raise ValueError("TURN lifecycle rejects MILL qualification options")
    from scripts.sw_cam_events import CamMessageSession

    report = {"status": "error", "action": action, "phase": "preflight", "may_continue": False,
        "mutation_attempted": False, "native_call_attempted": False, "native_call_returned": False,
        "native_save_call_returned": False, "native_close_call_returned": False,
        "save_readback_verified": False, "close_verified": False, "persistence_verified": False,
        "generation_attempted": False, "native_outcome": "not_called", "response": "default_unknown",
        "cam_save_restore_flag": "unknown", "cam_dirty_state": "unknown", "message_policy": message_policy}
    receipt = None
    receipt_created = False
    session = None
    try:
        if (not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold() != ".sldprt"):
            raise ValueError("An exact absolute saved .sldprt path is required")
        if action not in {"prepare", "save", "close"} or message_policy != "vendor_default":
            raise ValueError("Explicit prepare/save/close and vendor_default policy are required")
        if action == "prepare":
            if expected_state_sha256 is not None or receipt_path is not None:
                raise ValueError("Prepare cannot accept mutation inputs")
        else:
            if not isinstance(expected_state_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_state_sha256):
                raise ValueError("An exact prepared state SHA-256 is required")
            receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
            if (receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json"
                    or not receipt.parent.is_dir()):
                raise ValueError("A new absolute JSON receipt in an existing directory is required")
            _write_receipt(receipt, report, create=True)
            receipt_created = True
        before, app = _snapshot(sw, clsid, typelib_path, expected_document_path)
        report.update(before=before, state_sha256=_digest(before), phase="prepared")
        if action == "prepare":
            report.update(status="ok")
            return report
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Prepared document, saved file or CAM state changed")
        if action == "close" and before["document"]["needs_save"] is not False:
            raise ValueError("Close requires SOLIDWORKS needs_save=false; CAM dirty state remains unknown")
        def require_user_control():
            # 官方 CloseDoc 文档：后台会话关闭最后一份文档时可结束整个应用。
            # 不接管现有会话；仅允许明确回读为 True 的 UserControl。
            value = _member(sw, "UserControl")
            report["user_control_before_close"] = value if type(value) is bool else "unverified"
            if value is not True:
                raise ValueError("Close requires verified UserControl=true; existing session is not modified")
        if action == "close":
            require_user_control()
        session = CamMessageSession(app, typelib_path)

        def check_messages():
            summary = session.summary()
            report["messages"] = summary
            if not summary.get("subscribed") or any(summary.get(key) for key in (
                    "event_count", "overflow", "callback_errors", "callback_error_count",
                    "subscription_error", "disconnect_errors")):
                raise _MessageBlocked("CAM message/default response requires review; no further CAD calls")

        with session:
            report["phase"] = "before_native_action"
            check_messages()
            current, app = _snapshot(sw, clsid, typelib_path, expected_document_path, check=check_messages)
            if current != before:
                raise ValueError("Lifecycle state changed before native action")
            app = _typed(app, "ICWApp", typelib_path)
            check_messages()
            report.update(phase="SaveActiveDocument" if action == "save" else "CloseActiveDocument",
                          mutation_attempted=True, native_call_attempted=True, native_outcome="unknown")
            _write_receipt(receipt, report)
            check_messages()
            current_document = document_snapshot(sw)
            check_messages()
            if current_document != before["document"]:
                raise ValueError("Document changed immediately before native action")
            # 消息检查在最终文档 getter 后执行；不根据 S_OK 猜测对话框的选择。
            check_messages()
            if action == "close":
                require_user_control()
                check_messages()
            _member(app, "SaveActiveDocument" if action == "save" else "CloseActiveDocument")
            report.update(native_call_returned=True, phase="native_returned")
            report["native_save_call_returned" if action == "save" else "native_close_call_returned"] = True
            _write_receipt(receipt, report)
            check_messages()
            if action == "save":
                after, _ = _snapshot(sw, clsid, typelib_path, expected_document_path, check=check_messages)
                report["after"] = after
                _verify_save(before, after)
            else:
                report["open_documents_after"] = _open_documents(sw, expected_document_path, check=check_messages)
        report["phase"] = "after_cleanup"
        check_messages()
        if session.summary().get("disconnected") is not True:
            raise _MessageBlocked("CAM event cleanup was not confirmed")
        if action == "save":
            final, _ = _snapshot(sw, clsid, typelib_path, expected_document_path, check=check_messages)
            report["final_state"] = final
            if final != after:
                raise ValueError("Document or inventory changed during event cleanup")
            report.update(state_sha256=_digest(final), save_readback_verified=True,
                          native_outcome="save_returned_readback_verified",
                          saved_file_changed=before["saved_file_sha256"] != final["saved_file_sha256"],
                          reason="SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN")
        else:
            final_documents = _open_documents(sw, expected_document_path, check=check_messages)
            report["open_documents_after_cleanup"] = final_documents
            if final_documents != report["open_documents_after"]:
                raise ValueError("Open documents changed during event cleanup")
            report.update(close_verified=True, native_outcome="target_absent_from_open_documents",
                          reason="CLOSE_VERIFIED_CAM_PERSISTENCE_UNVERIFIED")
        check_messages()
        report.update(status="review_required", phase="finished")
    except Exception as exc:
        report.update(status="review_required" if isinstance(exc, _MessageBlocked) else
                      ("uncertain" if report["mutation_attempted"] else "error"),
                      failed_phase=report["phase"], phase="finished",
                      reason="CAM_LIFECYCLE_MESSAGE_REQUIRES_REVIEW" if isinstance(exc, _MessageBlocked)
                      else "CAM_DOCUMENT_LIFECYCLE_FAILED", issue=_error(exc))
        report.update(save_readback_verified=False, close_verified=False)
        if report["mutation_attempted"]:
            report["native_outcome"] = "unknown"
    finally:
        if session is not None:
            report["messages"] = session.summary()
        if receipt_created:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=_error(exc),
                              save_readback_verified=False, close_verified=False, native_outcome="unknown")
    return report
