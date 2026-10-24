"""SOLIDWORKS CAM 的受限原生检查；不生成刀路、不保存模型或修改许可证。"""
from __future__ import annotations

from pathlib import Path
import ntpath
import re
import traceback

# 来自 SOLIDWORKS CAM 2026 的 camworks.tlb；调用前 QueryInterface 确认支持。
_INTERFACES = {"doc": "ICWDoc3", "part": "ICWPartDoc", "machine": "ICWMachine",
               "collection": "ICWDispatchCollection"}


def _interface(obj, name, typelib_path=None):
    """通过标准 COM 封送取得类型化 vtable；不使用默认 IDispatch。"""
    from scripts.sw_cam_comtypes import query_cam_interface
    if not typelib_path:
        raise ValueError("The registered installation's CAM type library is required")
    return query_cam_interface(obj, _INTERFACES[name], typelib_path)


def _member(obj, name, *args):
    """只供本模块明确列出的 API 使用，不接受客户端方法名称。"""
    value = getattr(obj, name)
    # IDispatch 对象可能被 Python 视为可调用；不能调用对象的默认成员。
    if not args and {"_oleobj_", "_dispobj_"}.intersection(getattr(value, "__dict__", {})):
        return value
    return value(*args) if callable(value) else value


def document_snapshot(sw):
    """记录活动文档及脏标志；无文档时不创建或激活文档。"""
    model = _member(sw, "ActiveDoc")
    if model is None:
        return None
    return {
        "path": _member(model, "GetPathName"),
        "title": _member(model, "GetTitle"),
        "type": int(_member(model, "GetType")),
        "needs_save": bool(_member(model, "GetSaveFlag")),
    }


def select_registration(inventory, clsid):
    """只接受实际发现的 CAM 加载项 CLSID；禁止任意 COM 服务器路径。"""
    if not isinstance(clsid, str) or not re.fullmatch(
        r"\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}", clsid
    ):
        raise ValueError("CAM add-in CLSID must be a GUID in braces")
    rows = [row for row in inventory.get("addin_registrations", [])
            if str(row.get("clsid", "")).casefold() == clsid.casefold()]
    if not rows:
        raise ValueError("Requested CLSID is not a discovered SOLIDWORKS CAM add-in")
    registrations = [row for row in inventory.get("com_registrations", [])
                     if str(row.get("clsid", "")).casefold() == clsid.casefold()
                     and row.get("view") != "32"]
    identities = set()
    resolved = []
    for entry in registrations:
        for server in entry.get("servers", []):
            if server.get("kind") != "inproc":
                continue
            path = server.get("path")
            if path:
                if server.get("exists") is False:
                    raise ValueError("Registered CAM DLL does not exist")
                identities.add((ntpath.normcase(ntpath.normpath(path)),
                                str(entry.get("progid") or "").casefold(),
                                str(entry.get("typelib_id") or "").casefold()))
                resolved.append((path, entry))
    if len(identities) != 1:
        raise ValueError("CAM COM registration is missing or conflicting; no server selected")
    path, entry = resolved[0]
    if not Path(path).is_absolute() or Path(path).suffix.lower() != ".dll" or not Path(path).is_file():
        raise ValueError("Registered CAM in-process DLL is missing or invalid")
    return {**rows[0], "addin_path": path, "com_registration": entry}


def _error(exc):
    """保留错误类型及 HRESULT，不输出可能包含许可证内容的错误文本。"""
    frames = traceback.extract_tb(exc.__traceback__)[-3:]
    return {"type": type(exc).__name__, "hresult": getattr(exc, "hresult", None),
            **{key: getattr(exc, key) for key in ("code", "bridge_stage", "error_type",
                                                "input_type", "source_type") if hasattr(exc, key)},
            "actual_return_type": getattr(exc, "actual_return_type", None),
            "locations": [{"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
                          for f in frames]}


def _snapshot_error(exc, stage):
    """状态不可读时拒绝继续，不把未知状态当作未改变。"""
    return {"status": "error", "reason": "CAM_DOCUMENT_STATE_UNREADABLE",
            "active_document_unchanged": None,
            "issues": [{"stage": stage, **_error(exc)}]}


def inspect_cam(sw, clsid):
    """读取已加载 CAM；缺失时不自动 LoadAddIn 或创建其它 COM 实例。"""
    try:
        before = document_snapshot(sw)
    except Exception as exc:
        return _snapshot_error(exc, "document_before")
    report = {
        "status": "ok", "addin_clsid": clsid, "addin_available": False,
        "api_available": False, "turning_entitlement": "unknown",
        "license_activation_attempted": False, "model_saved": False,
        "document_before": before, "issues": [],
    }
    stage = "GetAddInObject"
    try:
        addin = sw.GetAddInObject(clsid)
        if addin is None:
            report.update(status="unavailable", reason="CAM_ADDIN_NOT_LOADED")
        else:
            report["addin_available"] = True
            stage = "GetCWApp"
            app = _member(addin, "GetCWApp")
            if app is None:
                report.update(status="unavailable", reason="CAM_API_OBJECT_UNAVAILABLE")
            else:
                report["api_available"] = True
                for key, name in (("version", "GetVersion"),
                                  ("service_pack", "GetServicePack"),
                                  ("build_date", "GetBuildDate"),
                                  ("demo_mode", "GetIsCAMWorksInDemoMode")):
                    try:
                        value = _member(app, name)
                        report[key] = bool(value) if key == "demo_mode" else str(value)
                    except Exception as exc:
                        report[key] = None
                        report["issues"].append({"stage": name, **_error(exc)})
                if report["issues"]:
                    report["status"] = "partial"
    except Exception as exc:
        report.update(status="unavailable", reason="CAM_API_CALL_FAILED")
        report["issues"].append({"stage": stage, **_error(exc)})
    try:
        after = document_snapshot(sw)
    except Exception as exc:
        report.update(_snapshot_error(exc, "document_after"))
        return report
    report["document_after"] = after
    report["active_document_unchanged"] = before == after
    if before != after:
        report.update(status="error", reason="CAM_DOCUMENT_STATE_CHANGED")
    report["scope"] = "Application getters only; no CAM document, machine, toolpath or simulation created"
    return report


def load_cam_addin(sw, clsid, addin_path):
    """显式加载登记的 CAM 扩展并回读；不改变启动设置，不保存文档。"""
    try:
        before = document_snapshot(sw)
    except Exception as exc:
        return {**_snapshot_error(exc, "document_before_load"), "load_attempted": False}
    try:
        existing = sw.GetAddInObject(clsid)
    except Exception as exc:
        return {"status": "unavailable", "reason": "CAM_ADDIN_QUERY_FAILED",
                "load_attempted": False, "issue": _error(exc)}
    if existing is not None:
        report = inspect_cam(sw, clsid)
        report["load_attempted"] = False
        return report
    try:
        result = sw.LoadAddIn(str(addin_path))
    except Exception as exc:
        report = {"status": "unavailable", "reason": "CAM_ADDIN_LOAD_FAILED",
                  "load_attempted": True, "issue": _error(exc),
                  "document_before_load": before}
        try:
            report["document_after"] = document_snapshot(sw)
            report["active_document_unchanged"] = before == report["document_after"]
            if not report["active_document_unchanged"]:
                report.update(status="error", reason="CAM_DOCUMENT_STATE_CHANGED")
        except Exception as snapshot_exc:
            report.update(_snapshot_error(snapshot_exc, "document_after_load"))
        return report
    report = inspect_cam(sw, clsid)
    report.update(load_attempted=True, load_result=result,
                  document_before_load=before)
    if "document_after" not in report:
        return report
    if before != report["document_after"]:
        report.update(status="error", reason="CAM_DOCUMENT_STATE_CHANGED",
                      active_document_unchanged=False)
    # LoadAddIn 的单个返回码不是 API、许可证或刀路验证证据。
    return report


def _turning_context(sw, clsid, typelib_path=None):
    """取得已有 CAM 零件与车床目录，不修改配置。"""
    before = document_snapshot(sw)
    if before is None or before["type"] != 1 or not before["path"]:
        raise ValueError("CAM machine inspection requires an active saved part")
    addin = sw.GetAddInObject(clsid)
    if addin is None:
        raise ValueError("CAM add-in must already be loaded")
    app = _member(addin, "GetCWApp")
    if app is None:
        raise ValueError("CAM API is unavailable")
    active = _member(app, "IGetActiveDoc")
    if active is None:
        raise ValueError("No active CAM document")
    doc = _interface(active, "doc", typelib_path)
    doc_type = _member(doc, "GetDocType")
    if not isinstance(doc_type, int):
        error = TypeError("CAM GetDocType did not return its declared LONG")
        error.actual_return_type = type(doc_type).__name__
        raise error
    if doc_type != 1:
        raise ValueError("Active CAM document is not a part")
    part = _interface(active, "part", typelib_path)
    machine = _interface(_member(part, "IGetMachine"), "machine", typelib_path)
    candidates = _interface(_member(app, "GetMachines", 3), "collection", typelib_path)
    count = int(_member(candidates, "Count"))
    if not 0 <= count <= 10000:
        raise ValueError("Unexpected CAM machine collection size")
    return before, doc, part, machine, candidates, count


def inspect_turning(sw, clsid, typelib_path=None):
    """读取车床配置；目录中存在机器不代表许可证已验证。"""
    try:
        before, _doc, _part, machine, _candidates, count = _turning_context(sw, clsid, typelib_path)
        machine_type = int(_member(machine, "MachType"))
        after = document_snapshot(sw)
        return {"status": "ok" if before == after else "error",
                "current_machine_type": machine_type, "turn_machine_count": count,
                "turning_entitlement": "unknown", "document_before": before,
                "document_after": after, "active_document_unchanged": before == after,
                "model_saved": False}
    except Exception as exc:
        return {"status": "unavailable", "reason": "CAM_TURN_INSPECTION_FAILED",
                "issue": _error(exc), "turning_entitlement": "unknown"}


def set_turn_machine(sw, clsid, machine_index, expected_machine_type, expected_catalog_count,
                     typelib_path=None):
    """在空 CAM 配置中显式选取目录中的车床；回读类型，不生成或保存刀路。"""
    stage = "preflight"
    attempted = False
    try:
        before, doc, part, machine, candidates, count = _turning_context(sw, clsid, typelib_path)
        if before["needs_save"]:
            raise ValueError("Save the qualification part before changing its CAM machine")
        old_type = int(_member(machine, "MachType"))
        if old_type != expected_machine_type or count != expected_catalog_count:
            raise ValueError("CAM machine precondition changed; inspect again")
        if not 0 <= machine_index < count:
            raise ValueError("CAM machine index is out of range")
        for getter in ("IGetEnumSetups", "IGetEnumOpSetups"):
            collection = _interface(_member(machine, getter), "collection", typelib_path)
            if int(_member(collection, "Count")) != 0:
                raise ValueError("Refusing to replace a machine with existing setups or operations")
        chosen = _member(candidates, "Item", machine_index)
        if chosen is None:
            raise ValueError("CAM machine candidate is null")
        now = document_snapshot(sw)
        if before != now:
            raise ValueError("Document changed before CAM machine assignment")
        stage = "SetMachine2"
        attempted = True
        _member(doc, "SetMachine2", chosen)
        stage = "readback"
        actual = _interface(_member(part, "IGetMachine"), "machine", typelib_path)
        machine_type = int(_member(actual, "MachType"))
        after = document_snapshot(sw)
        same = after is not None and all(before[k] == after[k] for k in ("path", "title", "type"))
        return {"status": "ok" if same and machine_type == 3 else "error",
                "machine_assignment_verified": same and machine_type == 3,
                "machine_index": machine_index, "current_machine_type": machine_type,
                "previous_machine_type": old_type, "document_before": before,
                "document_after": after, "model_saved": False,
                "turning_entitlement": "unknown", "toolpath_verified": False,
                "scope": "Machine assignment only; no machining or simulation performed"}
    except Exception as exc:
        return {"status": "error", "reason": "CAM_MACHINE_ASSIGNMENT_FAILED",
                "stage": stage, "assignment_attempted": attempted, "issue": _error(exc),
                "model_saved": False, "turning_entitlement": "unknown"}
