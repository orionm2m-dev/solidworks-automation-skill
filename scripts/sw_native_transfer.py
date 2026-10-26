"""限定副本的原生实体迁移与关闭文件引用替换；不接触源文件或自动重试。"""
from __future__ import annotations

from copy import deepcopy
import math
import json
from pathlib import Path
import re
import shutil

from scripts.sw_cam import _error, _member
from scripts.sw_cam_feature_sketch import _call_method as call
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_operation_guard import absolute_document_path, _path_identity

# 已安装 swconst.tlb 与既有 STEP 导入验证的设置；仅作用于本次导入并恢复。
_IMPORT_PREFS = (("Toggle", 691, False), ("Toggle", 161, True),
    ("Toggle", 686, True), ("IntegerValue", 12, 3), ("IntegerValue", 207, 1),
    ("IntegerValue", 577, 0), ("IntegerValue", 140, 1),
    ("Toggle", 290, True), ("Toggle", 291, False), ("Toggle", 111, True))


def _path(value, extensions=None, *, new=False):
    if type(value) is not str or not absolute_document_path(value):
        raise ValueError("Exact absolute path required")
    path = Path(value)
    if extensions and path.suffix.lower() not in extensions:
        raise ValueError("Unexpected file type")
    if path.is_symlink() or (new and (path.exists() or not path.parent.is_dir())):
        raise ValueError("Output must be new, nonsymlink, with an existing parent")
    if not new and not path.is_file():
        raise ValueError("Required input file is absent")
    return path


def _hash(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Exact lower-case SHA256 required")
    return value


def _frozen(rows):
    if type(rows) is not list or len(rows) > 512:
        raise ValueError("Bounded frozen file list required")
    result = {}
    for row in rows:
        if type(row) is not dict or set(row) != {"path", "sha256"}:
            raise ValueError("Frozen file requires exact path and sha256")
        path = _path(row["path"])
        key = _path_identity(path)
        if key in result:
            raise ValueError("Duplicate canonical source")
        digest = _hash(row["sha256"])
        if _file_hash(path) != digest:
            raise ValueError("Frozen file SHA changed: " + str(path))
        result[key] = dict(path=str(path), sha256=digest)
    return result


def _check_files(rows):
    for row in rows.values():
        if _file_hash(row["path"]) != row["sha256"]:
            raise ValueError("Frozen file SHA changed: " + row["path"])


def _documents(sw):
    models = list(call(sw, "GetDocuments") or [])
    if len(models) > 256:
        raise ValueError("Too many open documents")
    result = []
    for model in models:
        result.append(dict(path=str(call(model, "GetPathName") or ""),
            title=str(call(model, "GetTitle")), needs_save=bool(call(model, "GetSaveFlag")),
            visible=bool(_member(model, "Visible")), type=int(call(model, "GetType"))))
    return result



def inspect_open_documents(sw, *, process_id):
    """只读枚举指定已连接进程的文档与活动路径；允许没有活动文档。"""
    if type(process_id) is not int or process_id <= 0 or call(sw, "GetProcessID") != process_id:
        raise ValueError("Exact owned PID required")
    documents = _documents(sw)
    model = _member(sw, "ActiveDoc")
    active = None if model is None else dict(path=str(call(model, "GetPathName") or ""),
        title=str(call(model, "GetTitle")), type=int(call(model, "GetType")))
    return dict(status="ok", process_id=process_id, active_document=active,
        documents=documents, document_count=len(documents),
        user_control=_member(sw, "UserControl"), mutation_attempted=False)


def _session(sw, process_id, expected_document_path, closed_paths):
    if type(process_id) is not int or process_id <= 0 or call(sw, "GetProcessID") != process_id:
        raise ValueError("Exact owned PID required")
    if _member(sw, "UserControl") is not True:
        raise ValueError("UserControl must already be true; do not mutate an existing session")
    model = _member(sw, "ActiveDoc")
    if model is None or _path_identity(call(model, "GetPathName")) != _path_identity(expected_document_path):
        raise ValueError("Active saved anchor differs from the explicit target")
    documents = _documents(sw)
    if any(row["needs_save"] or not row["path"] for row in documents):
        raise ValueError("All existing documents must be saved and clean")
    if sum(row["visible"] for row in documents) != 1 or not _member(model, "Visible"):
        raise ValueError("Exactly the explicit anchor must be visible")
    closed = {_path_identity(value) for value in closed_paths}
    if any(_path_identity(row["path"]) in closed for row in documents):
        raise ValueError("Source, donor, output and replacement references must be closed")
    return dict(process_id=process_id, anchor=expected_document_path, documents=documents), model


def _common(sw, values, extension, additional_closed=()):
    if values["qualification_only"] is not True or values["action"] not in {"prepare", "apply"}:
        raise ValueError("Explicit qualification prepare/apply required")
    source = _path(values["source_path"], {extension})
    output = _path(values["output_path"], {extension}, new=values.get("prior_transfer_receipt_path") is None)
    anchor = _path(values["expected_document_path"], {".sldprt", ".sldasm"})
    if _file_hash(source) != _hash(values["source_sha256"]):
        raise ValueError("Native source SHA changed")
    frozen = _frozen(values["frozen_files"])
    source_key = _path_identity(source)
    if source_key in frozen and frozen[source_key]["sha256"] != values["source_sha256"]:
        raise ValueError("Contradictory frozen source SHA")
    frozen[source_key] = dict(path=str(source), sha256=values["source_sha256"])
    if _path_identity(output) in frozen or _path_identity(output) == _path_identity(anchor):
        raise ValueError("Output aliases an existing source or anchor")
    session, model = _session(sw, values["process_id"], str(anchor), [source, output, *additional_closed])
    state = dict(config={key: deepcopy(value) for key, value in values.items()
        if key not in {"action", "expected_state_sha256", "receipt_path"}}, session=session,
        frozen_files=frozen, anchor_sha256=_file_hash(anchor))
    return state, model, source, output


def _receipt(report, values, state):
    if values["action"] == "prepare":
        if values["expected_state_sha256"] is not None or values["receipt_path"] is not None:
            raise ValueError("Prepare cannot accept mutation inputs")
        return None
    if _hash(values["expected_state_sha256"]) != _digest(state):
        raise ValueError("Prepared transfer state changed")
    path = _path(values["receipt_path"], {".json"}, new=True)
    _write_receipt(path, report, create=True)
    return path


def _copy_exclusive(source, target):
    with Path(source).open("rb") as incoming, Path(target).open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    digest = _file_hash(target)
    if digest != _file_hash(source):
        raise ValueError("Byte-copy SHA mismatch")
    return digest


def _dispatch(obj):
    # 对具有显式 by-ref OUT 的方法选用同一原生对象的动态包装，调用前选择，绝不重放。
    ole = getattr(obj, "__dict__", {}).get("_oleobj_")
    if ole is None:
        return obj
    from win32com.client.dynamic import DumbDispatch
    return DumbDispatch(ole)


def _open(sw, path, *, step=False, observed=None):
    import pythoncom
    from win32com.client import VARIANT
    error = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warning = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    app = _dispatch(sw)
    document_type = 1 if step or Path(path).suffix.lower() == ".sldprt" else 2
    titles_before = {row["title"] for row in _documents(sw)}
    call(app, "DocumentVisible", False, document_type)
    try:
        if step:
            data = call(app, "GetImportFileData", str(path))
            if data is None: raise ValueError("STEP import data unavailable")
            model = call(app, "LoadFile4", str(path), "r", data, error)
        else:
            model = call(app, "OpenDoc6", str(path), document_type, 1, "", error, warning)
        if model is None or error.value != 0:
            raise ValueError(f"Native open failed: errors={error.value}, warnings={warning.value}")
        actual_path = str(call(model, "GetPathName") or "")
        title = str(call(model, "GetTitle"))
        actual_type = int(call(model, "GetType"))
        metadata = dict(errors=error.value, warnings=warning.value, path=actual_path, title=title,
            type=actual_type, expected_type=document_type, native_open_returned=True)
        # 先持久记录实际返回的文档，即使多实体 STEP 被导入为意外装配，也不丢失所有权证据。
        if observed is not None: observed(metadata)
        model.Visible = False
        if actual_type != document_type:
            raise ValueError("Opened document type differs from the explicit file")
        if ((actual_path and _path_identity(actual_path) != _path_identity(path))
                or (not actual_path and not step) or title in titles_before):
            raise ValueError("Native open returned an unexpected or pre-existing document")
        return model, metadata
    finally:
        call(app, "DocumentVisible", True, document_type)


def _stats(model):
    solids = list(call(model, "GetBodies2", 0, False) or [])
    sheets = list(call(model, "GetBodies2", 1, False) or [])
    if not 1 <= len(solids) <= 9 or sheets:
        raise ValueError("Expected one to nine bounded solids and no sheets")
    rows = []
    for body in solids:
        check = _member(body, "Check3")
        errors = int(_member(check, "Count"))
        mass = list(call(body, "GetMassProperties", 1))
        if len(mass) != 12 or any(type(x) not in (int, float) or not math.isfinite(x) for x in mass):
            raise ValueError("Invalid native body mass properties")
        if errors != 0 or mass[3] <= 0:
            raise ValueError("Invalid native solid")
        rows.append(dict(check3=errors, volume_m3=mass[3], mass_properties_native=mass,
            box_model_m=list(call(body, "GetBodyBox"))))
    return dict(solid_count=len(solids), sheet_count=len(sheets), bodies=rows), solids


def _features(model):
    result = []
    feature = call(model, "FirstFeature")
    while feature is not None:
        if len(result) >= 512: raise ValueError("Feature tree exceeds qualification bound")
        result.append(dict(name=str(_member(feature, "Name")), type=str(call(feature, "GetTypeName2"))))
        feature = call(feature, "GetNextFeature")
    return result


def _save(model, path=None):
    import pythoncom
    from win32com.client import VARIANT
    from scripts.sw_connect import create_empty_dispatch_variant
    error = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warning = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    if path is None:
        ok = call(_dispatch(model), "Save3", 1, error, warning)
    else:
        ok = call(_dispatch(_member(model, "Extension")), "SaveAs", str(path), 0, 1,
            create_empty_dispatch_variant(), error, warning)
    if ok is not True or error.value != 0:
        raise ValueError(f"Native save/export failed: return={ok}, errors={error.value}, warnings={warning.value}")
    return dict(native_return=ok, errors=error.value, warnings=warning.value)


def _close_owned(sw, model, allowed_paths, *, imported_title=None):
    path = str(call(model, "GetPathName") or "")
    title = str(call(model, "GetTitle"))
    if not (not path and imported_title == title) and _path_identity(path) not in {_path_identity(value) for value in allowed_paths}:
        raise ValueError("Refuse to close a document outside the exact owned paths")
    matches = [row for row in _documents(sw) if row["title"] == title]
    if len(matches) != 1 or _path_identity(matches[0]["path"]) != _path_identity(path):
        raise ValueError("Owned close title is ambiguous")
    call(sw, "CloseDoc", title)
    if any(row["title"] == title for row in _documents(sw)):
        raise ValueError("Owned document close was not confirmed")



def _find_document(sw, path):
    # 跨 CloseDoc/OpenDoc 不保留 IModelDoc2；每次使用前按完整路径重新获取。
    model = call(sw, "GetOpenDocumentByName", str(Path(path)))
    if model is not None and _path_identity(call(model, "GetPathName")) != _path_identity(path):
        raise ValueError("Fresh document lookup returned a different path")
    return model


def _anchor_document(sw, path, sha256, native):
    if _file_hash(path) != sha256:
        raise ValueError("Saved anchor SHA changed")
    model = _find_document(sw, path)
    if model is None:
        model, _ = native("reopen_exact_anchor", lambda: _open(sw, path))
    if call(model, "GetSaveFlag") or _file_hash(path) != sha256:
        raise ValueError("Exact saved anchor is dirty or changed")
    return model


def _owned_donor(sw, staged, imported):
    model = _find_document(sw, staged)
    if model is not None:
        return model
    # 无路径的导入文档仅接受本次导入回执中的唯一标题，不猜测其它文档。
    if imported.get("path"):
        return None
    models = list(call(sw, "GetDocuments") or [])
    if len(models) > 256:
        raise ValueError("Too many open documents")
    matches = [model for model in models if str(call(model, "GetTitle")) == imported["title"]]
    if len(matches) > 1:
        raise ValueError("Owned donor title is ambiguous")
    if matches and str(call(matches[0], "GetPathName") or ""):
        raise ValueError("Imported donor acquired an unrecognized saved path")
    return matches[0] if matches else None

def qualify_part_transfer(sw, *, process_id, expected_document_path, action, mode, source_path,
        source_sha256, donor_step_path, donor_sha256, output_path, roundtrip_step_path,
        qualification_only, acknowledge_delta_only=False, delta_volume_policy="strict", frozen_files=None,
        expected_state_sha256=None, receipt_path=None, prior_transfer_receipt_path=None,
        prior_transfer_receipt_sha256=None):
    """在原文件的独占副本上插入完整替换体或已批准增量；返回保存/重开和回导证据。"""
    values = dict(locals()); values.pop("sw"); values["frozen_files"] = [] if frozen_files is None else frozen_files
    report = dict(status="error", phase="preflight", mutation_attempted=False, may_continue=False,
        body_transfer_verified=False, reopened_verified=False, source_files_unchanged=False,
        internal_document_id_verified=False, topology_ids_preserved=False,
        independent_geometry_equivalence_verified=False, production_release=False, native_calls=[])
    receipt = None; preferences = []; anchor = None; completed = False
    def record(phase):
        report["phase"] = phase
        if receipt: _write_receipt(receipt, report)
    def native(phase, operation):
        if call(sw, "GetProcessID") != process_id:
            raise ValueError("Owned process identity changed")
        if phase in {"CreateFeatureFromBody3", "InsertDeleteBody2", "Save3", "export_roundtrip_step"} or phase.startswith("InsertCombineFeature_"):
            if _path_identity(call(model, "GetPathName")) != _path_identity(output):
                raise ValueError("Owned output identity changed before native mutation")
        if phase in {"CreateFeatureFromBody3", "InsertDeleteBody2", "export_roundtrip_step"} or phase.startswith("InsertCombineFeature_"):
            if _path_identity(call(_member(sw, "ActiveDoc"), "GetPathName")) != _path_identity(output):
                raise ValueError("Exact output copy must be active before body/selection/export operation")
        report["native_calls"].append(dict(name=phase, attempted=True, returned=False))
        record(phase)
        value = operation()
        report["native_calls"][-1]["returned"] = True
        record(phase + "_returned")
        return value
    try:
        if delta_volume_policy not in {"strict", "diagnostic"}:
            raise ValueError("Explicit supported delta volume policy required")
        if mode not in {"replace_body", "add_delta", "subtract_delta"} or type(acknowledge_delta_only) is not bool:
            raise ValueError("Explicit supported body transfer mode required")
        if acknowledge_delta_only != (mode in {"add_delta", "subtract_delta"}):
            raise ValueError("ADD/CUT requires explicit donor-is-delta-only acknowledgement")
        donor = _path(donor_step_path, {".step", ".stp"})
        if _file_hash(donor) != _hash(donor_sha256): raise ValueError("Donor SHA changed")
        roundtrip = _path(roundtrip_step_path, {".step", ".stp"}, new=True)
        output = Path(output_path)
        prior = None
        if (prior_transfer_receipt_path is None) != (prior_transfer_receipt_sha256 is None):
            raise ValueError("Continuation requires both exact prior receipt path and SHA")
        if prior_transfer_receipt_path is not None:
            if mode == "replace_body": raise ValueError("Only local delta steps may continue a qualified copy")
            prior_path = _path(prior_transfer_receipt_path, {".json"})
            if prior_path.stat().st_size > 10 * 1024 * 1024 or _file_hash(prior_path) != _hash(prior_transfer_receipt_sha256):
                raise ValueError("Prior receipt is too large or its SHA changed")
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            config = prior.get("before", {}).get("config", {})
            if (prior.get("status") != "review_required" or not prior.get("body_transfer_verified")
                    or not prior.get("reopened_verified") or not prior.get("source_files_unchanged")
                    or prior.get("preference_restore_errors") or not prior.get("native_source_copied_before_mutation")
                    or _path_identity(prior.get("output_path", "")) != _path_identity(output)
                    or _path_identity(config.get("source_path", "")) != _path_identity(source_path)
                    or config.get("source_sha256") != source_sha256
                    or prior.get("copied_source_sha256") != source_sha256
                    or _file_hash(output) != prior.get("output_sha256")):
                raise ValueError("Continuation does not identify the exact verified owned copy")
        staged = _path(str(output.with_name(output.stem + "_donor_" + donor_sha256[:12] + ".step")), {".step"}, new=True)
        outputs = [output, roundtrip, staged]
        if len({_path_identity(value) for value in outputs + [donor, Path(source_path)]}) != 5:
            raise ValueError("Input/output canonical paths overlap")
        if any(len(str(value)) >= 240 for value in outputs):
            raise ValueError("Use a shorter explicit output directory for native import/export paths")
        state, anchor, source, output = _common(sw, values, ".sldprt", [donor, staged, roundtrip])
        state["frozen_files"][_path_identity(donor)] = dict(path=str(donor), sha256=donor_sha256)
        if prior is not None:
            state["prior_output_sha256"] = prior["output_sha256"]
            state["frozen_files"][_path_identity(prior_path)] = dict(path=str(prior_path),sha256=prior_transfer_receipt_sha256)
        for value in outputs:
            if _path_identity(value) in state["frozen_files"]:
                raise ValueError("Output aliases frozen file")
        template = str(call(sw, "GetUserPreferenceStringValue", 8) or "")
        if not template or not Path(template).is_file():
            raise ValueError("A valid native default part template must already be configured")
        state["import_preferences_before"] = [dict(kind=kind, number=num,
            value=call(sw, "GetUserPreference" + kind, num)) for kind, num, _ in _IMPORT_PREFS]
        report.update(before=state, state_sha256=_digest(state), mode=mode,
            donor_stage_path=str(staged), output_path=str(output), roundtrip_step_path=str(roundtrip))
        receipt = _receipt(report, values, state)
        if action == "prepare": report.update(status="ok", phase="prepared", apply_eligible=True); return report
        _session(sw, process_id, expected_document_path, [source, output, donor, staged])
        _check_files(state["frozen_files"])
        report["mutation_attempted"] = True; record("copy_sources")
        if prior is None:
            report["copied_source_sha256"] = _copy_exclusive(source, output)
        else:
            if _file_hash(output) != state["prior_output_sha256"]:
                raise ValueError("Owned copy changed before continuation")
            report["copied_source_sha256"] = prior["copied_source_sha256"]
            report["continuation_of_verified_copy"] = dict(receipt_path=str(prior_path),
                receipt_sha256=prior_transfer_receipt_sha256, input_sha256=prior["output_sha256"])
        report["staged_donor_sha256"] = _copy_exclusive(donor, staged)
        if report["copied_source_sha256"] != source_sha256 or report["staged_donor_sha256"] != donor_sha256:
            raise ValueError("Source changed while making verified copies; no native operation allowed")
        report["native_source_copied_before_mutation"] = True; record("copies_verified")
        for row, (_, _, desired) in zip(state["import_preferences_before"], _IMPORT_PREFS):
            preferences.append(row)
            if row["value"] != desired:
                native("set_import_preference", lambda row=row, desired=desired:
                    call(sw, "SetUserPreference" + row["kind"], row["number"], desired))
                if call(sw, "GetUserPreference" + row["kind"], row["number"]) != desired:
                    raise ValueError("Import preference readback failed")
        model, report["open_output"] = native("open_copied_part", lambda: _open(sw, output))
        if call(model, "GetSaveFlag"): raise ValueError("Fresh native source copy opened dirty")
        before, old = _stats(model)
        if len(old) != 1: raise ValueError("Source must have exactly one solid")
        report["body_before"] = before; original_features = _features(model)
        def observed_import(metadata):
            report["open_donor"] = metadata
            record("import_staged_step_observed")
        donor_model, report["open_donor"] = native("import_staged_step", lambda:
            _open(sw, staged, step=True, observed=observed_import))
        donor_stats, donors = _stats(donor_model)
        if not 1 <= len(donors) <= 8 or (mode == "replace_body" and len(donors) != 1):
            raise ValueError("Local donor needs one to eight solids; full replacement needs exactly one")
        report["donor_body"] = donor_stats
        from scripts.sw_assembly import _activate_model_document
        anchor = _anchor_document(sw, expected_document_path, state["anchor_sha256"], native)
        anchor.Visible = False; model.Visible = True
        if not _activate_model_document(sw, model): raise ValueError("Cannot activate exact output copy")
        for donor_index, donor_body in enumerate(donors):
            report["donor_body_index"] = donor_index
            copied_body = native("copy_donor_body", lambda: call(donor_body, "Copy"))
            feature = native("CreateFeatureFromBody3", lambda: call(model, "CreateFeatureFromBody3", copied_body, False, 1))
            if feature is None: raise ValueError("Native body insertion returned null; do not replay")
        inserted, bodies = _stats(model)
        if len(bodies) != 1 + len(donors): raise ValueError("Expected exactly retained source and inserted donors")
        report["inserted_bodies"] = inserted
        equality = [call(sw, "IsSame", body, old[0]) for body in bodies]
        if sorted(equality) != [0] * len(donors) + [1]:
            raise ValueError("Cannot identify exactly the retained source and inserted donor bodies")
        inserted_bodies = [body for body, match in zip(bodies, equality) if match == 0]
        call(model, "ClearSelection2", True)
        if _path_identity(call(model, "GetPathName")) != _path_identity(output):
            raise ValueError("Exact output document identity changed")
        manager = _member(model, "FeatureManager")
        if mode == "replace_body":
            selection = _member(model, "SelectionManager")
            data = call(selection, "CreateSelectData"); data.Mark = 0
            if call(old[0], "Select2", False, data) is not True:
                raise ValueError("Could not select the original body alone")
            if (call(selection, "GetSelectedObjectCount2", -1) != 1
                    or call(sw, "IsSame", call(selection, "GetSelectedObject6", 1, -1), old[0]) != 1):
                raise ValueError("DeleteBody selection is not exactly one body")
            result = native("InsertDeleteBody2", lambda: call(manager, "InsertDeleteBody2", False))
        else:
            import pythoncom
            from win32com.client import VARIANT
            from scripts.sw_connect import create_empty_dispatch_variant
            # swBodyOperationType_e: CUT=15902, ADD=15903；CUT 的 main body 只能是旧实体。
            selected_tools = bodies if mode == "add_delta" else inserted_bodies
            tools = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, tuple(selected_tools))
            main = create_empty_dispatch_variant() if mode == "add_delta" else old[0]
            operation_type = 15903 if mode == "add_delta" else 15902
            result = native("InsertCombineFeature_" + mode.upper(), lambda: call(manager,
                "InsertCombineFeature", operation_type, main, tools))
        if result is None: raise ValueError("Native body operation returned null; inspect retained copy, no replay")
        call(model, "ClearSelection2", True)
        report["rebuild_return"] = native("ForceRebuild3", lambda: call(model, "ForceRebuild3", False))
        after, remaining = _stats(model)
        if len(remaining) != 1: raise ValueError("Transfer did not leave exactly one valid solid")
        if mode == "replace_body" and not math.isclose(after["bodies"][0]["volume_m3"],
                donor_stats["bodies"][0]["volume_m3"], rel_tol=1e-9, abs_tol=0):
            raise ValueError("Replacement volume differs from donor")
        if mode in {"add_delta", "subtract_delta"}:
            sign = 1 if mode == "add_delta" else -1
            expected_volume = before["bodies"][0]["volume_m3"] + sign * sum(body["volume_m3"] for body in donor_stats["bodies"])
            actual_volume = after["bodies"][0]["volume_m3"]
            matched = expected_volume > 0 and math.isclose(actual_volume, expected_volume, rel_tol=1e-7, abs_tol=0)
            report["delta_volume_diagnostic"] = dict(policy=delta_volume_policy,
                before_m3=before["bodies"][0]["volume_m3"],
                donor_m3=[body["volume_m3"] for body in donor_stats["bodies"]],
                after_m3=actual_volume, expected_m3=expected_volume,
                relative_error=abs(actual_volume-expected_volume)/abs(expected_volume) if expected_volume else None)
            report["local_volume_delta_verified"] = matched
            report["volume_comparison_relative_tolerance"] = 1e-7
            report["independent_step_comparison_required"] = True
            if not matched and delta_volume_policy == "strict":
                raise ValueError("Boolean volume delta does not match the explicit local donor")
        features_after = _features(model)
        if features_after[:len(original_features)] != original_features:
            raise ValueError("Original feature/datum history changed")
        report.update(body_after=after, original_features=original_features, features_after=features_after)
        report["save"] = native("Save3", lambda: _save(model))
        if call(model, "GetSaveFlag"): raise ValueError("Output remained dirty after native save")
        report["output_sha256"] = _file_hash(output); record("native_output_saved")
        native("close_saved_copy", lambda: _close_owned(sw, model, [output]))
        model, report["reopen"] = native("reopen_saved_copy", lambda: _open(sw, output))
        reopened, remaining = _stats(model)
        if len(remaining) != 1 or call(model, "GetSaveFlag") or _features(model) != features_after:
            raise ValueError("Saved output did not reopen cleanly with identical feature history")
        if not math.isclose(reopened["bodies"][0]["volume_m3"], after["bodies"][0]["volume_m3"], rel_tol=1e-10, abs_tol=0):
            raise ValueError("Reopened output body volume changed")
        report.update(body_reopened=reopened, reopened_verified=True); record("reopened_copy_verified")
        _path(str(roundtrip), {".step", ".stp"}, new=True)
        anchor = _anchor_document(sw, expected_document_path, state["anchor_sha256"], native)
        anchor.Visible = False; model.Visible = True
        if not _activate_model_document(sw, model): raise ValueError("Cannot activate exact reopened output for STEP export")
        report["step_export"] = native("export_roundtrip_step", lambda: _save(model, roundtrip))
        if not roundtrip.is_file() or roundtrip.stat().st_size == 0:
            raise ValueError("Native roundtrip STEP absent or empty")
        report["roundtrip_sha256"] = _file_hash(roundtrip)
        if _file_hash(output) != report["output_sha256"]: raise ValueError("Output native file changed during roundtrip")
        native("close_reopened_copy", lambda: _close_owned(sw, model, [output]))
        donor_model = _owned_donor(sw, staged, report["open_donor"])
        if donor_model is not None:
            native("close_owned_donor", lambda: _close_owned(sw, donor_model, [staged],
                imported_title=report["open_donor"]["title"]))
        anchor = _anchor_document(sw, expected_document_path, state["anchor_sha256"], native)
        anchor.Visible = True
        if not _activate_model_document(sw, anchor): raise ValueError("Cannot restore exact original anchor")
        _check_files(state["frozen_files"])
        report.update(status="review_required", phase="finished", body_transfer_verified=True,
            reopened_verified=True, body_reopened=reopened, source_files_unchanged=True,
            reason="NATIVE_COPY_TRANSFER_REQUIRES_INDEPENDENT_STEP_AND_ASSEMBLY_IDENTITY_AUDIT")
        completed = True
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"], phase="finished", issue=_error(exc))
    finally:
        restore_errors = []
        for row in reversed(preferences):
            try:
                call(sw, "SetUserPreference" + row["kind"], row["number"], row["value"])
                if call(sw, "GetUserPreference" + row["kind"], row["number"]) != row["value"]:
                    raise ValueError("Preference restoration readback failed")
            except Exception as exc: restore_errors.append(_error(exc))
        report["preference_restore_errors"] = restore_errors
        if restore_errors: report.update(status="uncertain", body_transfer_verified=False)
        if completed:
            try:
                _session(sw, process_id, expected_document_path, [source, output, donor, staged])
            except Exception as exc: report.update(status="uncertain", final_session_issue=_error(exc), body_transfer_verified=False)
        if receipt:
            try: _write_receipt(receipt, report)
            except Exception as exc: report.update(status="uncertain", receipt_write_error=_error(exc), body_transfer_verified=False)
    return report



def finalize_part_transfer(sw, *, process_id, expected_document_path, transfer_receipt_path,
        transfer_receipt_sha256, expected_output_sha256, expected_anchor_sha256, receipt_path):
    """只完成已保存且重开的副本回读/STEP 导出；不重放实体操作、重建或原生保存。"""
    report = dict(status="error", phase="preflight", mutation_attempted=False,
        geometry_mutation_attempted=False, may_continue=False, body_transfer_verified=False,
        reopened_verified=False, source_files_unchanged=False, native_calls=[],
        internal_document_id_verified=False, independent_geometry_equivalence_verified=False,
        production_release=False)
    receipt = None
    receipt_created = False
    def record(phase):
        report["phase"] = phase
        _write_receipt(receipt, report)
    def native(name, operation):
        if call(sw, "GetProcessID") != process_id or _member(sw, "UserControl") is not True:
            raise ValueError("Owned process or UserControl changed")
        report["mutation_attempted"] = True
        step = dict(name=name, attempted=True, returned=False)
        report["native_calls"].append(step); record(name)
        value = operation()
        step["returned"] = True; record(name + "_returned")
        return value
    try:
        prior_path = _path(transfer_receipt_path, {".json"})
        if prior_path.stat().st_size > 10 * 1024 * 1024 or _file_hash(prior_path) != _hash(transfer_receipt_sha256):
            raise ValueError("Transfer receipt is too large or its SHA changed")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        before = prior["before"]; config = before["config"]
        output = _path(prior["output_path"], {".sldprt"})
        anchor_path = _path(config["expected_document_path"], {".sldprt", ".sldasm"})
        staged = _path(prior["donor_stage_path"], {".step", ".stp"})
        roundtrip = _path(prior["roundtrip_step_path"], {".step", ".stp"}, new=True)
        active_path = _path(expected_document_path, {".sldprt", ".sldasm"})
        if (type(process_id) is not int or process_id <= 0 or config["process_id"] != process_id
                or call(sw, "GetProcessID") != process_id or _member(sw, "UserControl") is not True):
            raise ValueError("Exact original owned process and UserControl required")
        calls = prior.get("native_calls", [])
        for name in ("Save3", "close_saved_copy", "reopen_saved_copy"):
            rows = [row for row in calls if row.get("name") == name]
            if len(rows) != 1 or rows[0].get("attempted") is not True or rows[0].get("returned") is not True:
                raise ValueError("Receipt does not confirm exactly one completed save/close/reopen")
        if any(row.get("name") == "export_roundtrip_step" and row.get("attempted") for row in calls):
            raise ValueError("STEP export was already attempted; no automatic replay")
        if (prior.get("native_source_copied_before_mutation") is not True
                or prior.get("copied_source_sha256") != config["source_sha256"]
                or prior.get("save", {}).get("native_return") is not True
                or prior["save"].get("errors") != 0 or prior.get("reopen", {}).get("errors") != 0
                or prior.get("preference_restore_errors") != []
                or _path_identity(config["output_path"]) != _path_identity(output)
                or _path_identity(config["roundtrip_step_path"]) != _path_identity(roundtrip)
                or _path_identity(prior["reopen"]["path"]) != _path_identity(output)):
            raise ValueError("Receipt lacks exact saved owned-copy provenance")
        if (prior["output_sha256"] != _hash(expected_output_sha256)
                or _file_hash(output) != expected_output_sha256
                or _file_hash(anchor_path) != _hash(expected_anchor_sha256)):
            raise ValueError("Saved output or anchor SHA changed")
        if before.get("anchor_sha256", expected_anchor_sha256) != expected_anchor_sha256:
            raise ValueError("Anchor SHA differs from original checkpoint")
        if _path_identity(active_path) not in {_path_identity(output), _path_identity(anchor_path)}:
            raise ValueError("Recovery target must be the exact output or original anchor")
        active = _member(sw, "ActiveDoc")
        if active is None or _path_identity(call(active, "GetPathName")) != _path_identity(active_path):
            raise ValueError("Explicit active document changed")
        for row in _documents(sw):
            is_donor = (_path_identity(row["path"]) == _path_identity(staged)
                or (not row["path"] and row["title"] == prior["open_donor"]["title"]
                    and not prior["open_donor"]["path"]))
            if not is_donor and (row["needs_save"] or not row["path"]):
                raise ValueError("A non-donor document is dirty or unsaved")
        _check_files(before["frozen_files"])
        if _file_hash(staged) != config["donor_sha256"]:
            raise ValueError("Staged donor SHA changed")
        model = _find_document(sw, output)
        if model is None or call(model, "GetSaveFlag"):
            raise ValueError("Confirmed output must already be open and clean")
        current, bodies = _stats(model)
        if (len(bodies) != 1 or _features(model) != prior["features_after"]
                or not math.isclose(current["bodies"][0]["volume_m3"],
                    prior["body_after"]["bodies"][0]["volume_m3"], rel_tol=1e-10, abs_tol=0)):
            raise ValueError("Saved output body or feature history changed")
        receipt = _path(receipt_path, {".json"}, new=True)
        report.update(before=before, output_path=str(output), output_sha256=expected_output_sha256,
            roundtrip_step_path=str(roundtrip), donor_stage_path=str(staged),
            recovery_of=dict(receipt_path=str(prior_path), receipt_sha256=transfer_receipt_sha256,
                status=prior.get("status"), failed_phase=prior.get("failed_phase"), issue=prior.get("issue")),
            copied_source_sha256=prior["copied_source_sha256"], native_source_copied_before_mutation=True,
            original_native_calls=calls, body_after=prior["body_after"], body_reopened=current,
            features_after=prior["features_after"], save=prior["save"], reopen=prior["reopen"],
            preference_restore_errors=[], expected_anchor_sha256=expected_anchor_sha256)
        _write_receipt(receipt, report, create=True)
        receipt_created = True
        from scripts.sw_assembly import _activate_model_document
        anchor = _anchor_document(sw, anchor_path, expected_anchor_sha256, native)
        model = _find_document(sw, output)
        if model is None or call(model, "GetSaveFlag"):
            raise ValueError("Output disappeared or became dirty while reacquiring anchor")
        report["mutation_attempted"] = True; record("activate_export_output")
        anchor.Visible = False; model.Visible = True
        if not _activate_model_document(sw, model):
            raise ValueError("Cannot activate exact output for export")
        if (_path_identity(call(_member(sw, "ActiveDoc"), "GetPathName")) != _path_identity(output)
                or _file_hash(output) != expected_output_sha256):
            raise ValueError("Exact output identity or SHA changed before export")
        _path(str(roundtrip), {".step", ".stp"}, new=True)
        report["step_export"] = native("export_roundtrip_step", lambda: _save(model, roundtrip))
        if not roundtrip.is_file() or roundtrip.stat().st_size == 0:
            raise ValueError("Native roundtrip STEP absent or empty")
        report["roundtrip_sha256"] = _file_hash(roundtrip)
        if _file_hash(output) != expected_output_sha256:
            raise ValueError("Native output changed during export")
        model = _find_document(sw, output)
        if model is None or call(model, "GetSaveFlag"):
            raise ValueError("Export output is absent or dirty; refuse close")
        native("close_reopened_copy", lambda: _close_owned(sw, model, [output]))
        donor = _owned_donor(sw, staged, prior["open_donor"])
        if donor is not None:
            native("close_owned_donor", lambda: _close_owned(sw, donor, [staged],
                imported_title=prior["open_donor"]["title"]))
        anchor = _anchor_document(sw, anchor_path, expected_anchor_sha256, native)
        anchor.Visible = True
        if not _activate_model_document(sw, anchor):
            raise ValueError("Cannot restore exact original anchor")
        _session(sw, process_id, str(anchor_path), [output, staged, config["source_path"], config["donor_step_path"]])
        _check_files(before["frozen_files"])
        if _file_hash(prior_path) != transfer_receipt_sha256 or _file_hash(output) != expected_output_sha256:
            raise ValueError("Original receipt or native output changed")
        report.update(status="review_required", phase="finished", source_files_unchanged=True,
            body_transfer_verified=True, reopened_verified=True, finalization_verified=True,
            reason="SAVED_COPY_FINALIZED_WITHOUT_GEOMETRY_REPLAY_INDEPENDENT_STEP_AUDIT_REQUIRED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"], phase="finished", issue=_error(exc))
    finally:
        if receipt_created:
            try: _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", body_transfer_verified=False, receipt_write_error=_error(exc))
    return report




def _unexpected_import_assembly(sw, prior, staged):
    # 只接受未开始实体编辑的本次失败导入；通过装配实际组件关系证明子文档归属。
    attempts = [row for row in prior["native_calls"] if row.get("name") == "import_staged_step"]
    if (len(attempts) != 1 or attempts[0].get("attempted") is not True or attempts[0].get("returned") is not False
            or any(row.get("name", "").startswith(("copy_donor_body", "CreateFeatureFromBody3", "Insert", "ForceRebuild3", "Save3"))
                and row.get("attempted") for row in prior["native_calls"])):
        raise ValueError("Unexpected-import cleanup requires exactly one import and no geometry/save attempt")
    title = staged.with_suffix(".SLDASM").name
    models = list(call(sw, "GetDocuments") or [])
    if len(models) > 256: raise ValueError("Too many open documents")
    matches = [model for model in models if str(call(model,"GetTitle")) == title]
    if len(matches) != 1: raise ValueError("Exact staged import assembly is not uniquely present")
    assembly = matches[0]
    if str(call(assembly,"GetPathName") or "") or call(assembly,"GetType") != 2:
        raise ValueError("Unexpected import must be the exact unsaved assembly")
    previous = prior["before"]["session"]["documents"]
    pre_titles = {row["title"] for row in previous}
    pre_paths = {_path_identity(row["path"]) for row in previous if row["path"]}
    if title in pre_titles: raise ValueError("Import title was already open before the transfer")
    components = list(call(assembly,"GetComponents",False) or [])
    if not 1 <= len(components) <= 8: raise ValueError("Unexpected import needs one to eight loaded child parts")
    children = []; keys = set()
    for component in components:
        model = call(component,"GetModelDoc2")
        if model is None or call(model,"GetType") != 1: raise ValueError("Every import child must be a loaded part")
        path = str(call(model,"GetPathName") or ""); child_title = str(call(model,"GetTitle"))
        key = _path_identity(path)
        if (not absolute_document_path(path) or Path(path).suffix.lower() != ".sldprt"
                or Path(path).exists() or key in pre_paths or child_title in pre_titles
                or key in prior["before"]["frozen_files"] or key in keys
                or child_title in {row["title"] for row in children}):
            raise ValueError("Import child must be unique, never saved, and absent from the original session")
        rows = [row for row in _documents(sw) if row["title"] == child_title]
        if len(rows) != 1 or _path_identity(rows[0]["path"]) != key:
            raise ValueError("Import child does not uniquely match a current document")
        keys.add(key); children.append(dict(path=path,title=child_title,type=1))
    return assembly, dict(path="",title=title,type=2), children


def cleanup_part_transfer(sw, *, process_id, transfer_receipt_path, transfer_receipt_sha256,
        expected_output_current_sha256, receipt_path, acknowledge_discard_unexpected_import=False):
    """仅关闭回执限定且已单独保存的副本/导入 donor，恢复原 anchor；不保存或导出。"""
    report = dict(status="error", phase="preflight", mutation_attempted=False,
        geometry_mutation_attempted=False, cleanup_verified=False, may_continue=False,
        geometry_verified=False, native_calls=[])
    receipt = None; receipt_created = False
    def native(name, operation):
        if call(sw, "GetProcessID") != process_id or _member(sw, "UserControl") is not True:
            raise ValueError("Owned process or UserControl changed")
        row = dict(name=name, attempted=True, returned=False)
        report["native_calls"].append(row)
        report.update(phase=name, mutation_attempted=True); _write_receipt(receipt, report)
        result = operation()
        row["returned"] = True; report["phase"] = name + "_returned"; _write_receipt(receipt, report)
        return result
    try:
        if type(acknowledge_discard_unexpected_import) is not bool:
            raise ValueError("Unexpected-import acknowledgement must be a strict boolean")
        prior_path = _path(transfer_receipt_path, {".json"})
        if prior_path.stat().st_size > 10 * 1024 * 1024 or _file_hash(prior_path) != _hash(transfer_receipt_sha256):
            raise ValueError("Transfer receipt is too large or its SHA changed")
        prior = json.loads(prior_path.read_text(encoding="utf-8")); before = prior["before"]; config = before["config"]
        output = _path(prior["output_path"], {".sldprt"})
        anchor_path = _path(config["expected_document_path"], {".sldprt", ".sldasm"})
        staged = _path(prior["donor_stage_path"], {".step", ".stp"})
        anchor_sha = _hash(before["anchor_sha256"])
        if (type(process_id) is not int or process_id <= 0 or config["process_id"] != process_id
                or call(sw, "GetProcessID") != process_id or _member(sw, "UserControl") is not True):
            raise ValueError("Exact original owned PID and UserControl required")
        if (prior.get("native_source_copied_before_mutation") is not True
                or prior.get("copied_source_sha256") != config["source_sha256"]
                or prior.get("preference_restore_errors") != []
                or _path_identity(config["output_path"]) != _path_identity(output)
                or _path_identity(output) in {_path_identity(anchor_path), _path_identity(config["source_path"])}):
            raise ValueError("Receipt does not identify an isolated owned output")
        if (_file_hash(output) != _hash(expected_output_current_sha256)
                or _file_hash(anchor_path) != anchor_sha or _file_hash(staged) != config["donor_sha256"]):
            raise ValueError("Saved output, original anchor or staged donor SHA changed")
        _check_files(before["frozen_files"])
        model = _find_document(sw, output)
        if model is not None and call(model, "GetSaveFlag"):
            raise ValueError("Owned output must be separately saved and clean before cleanup")
        children = []
        if acknowledge_discard_unexpected_import:
            if expected_output_current_sha256 != prior["copied_source_sha256"]:
                raise ValueError("Unexpected-import output must remain the unmodified native byte-copy")
            donor, imported, children = _unexpected_import_assembly(sw, prior, staged)
        else:
            imported = prior["open_donor"]
            donor = _owned_donor(sw, staged, imported)
        donor_identity = None if donor is None else (str(call(donor,"GetPathName") or ""), str(call(donor,"GetTitle")))
        child_identities = {(row["path"],row["title"]) for row in children}
        for row in _documents(sw):
            if donor_identity == (row["path"], row["title"]) or (row["path"],row["title"]) in child_identities: continue
            if row["needs_save"] or not row["path"]:
                raise ValueError("Other documents must be saved and clean")
            if _path_identity(row["path"]) in {_path_identity(config["source_path"]), _path_identity(config["donor_step_path"])}:
                raise ValueError("Original source or donor must remain closed")
        receipt = _path(receipt_path, {".json"}, new=True)
        report.update(transfer_receipt_path=str(prior_path), transfer_receipt_sha256=transfer_receipt_sha256,
            output_path=str(output), output_sha256=expected_output_current_sha256,
            anchor_path=str(anchor_path), anchor_sha256=anchor_sha,
            output_already_closed=model is None, donor_already_closed=donor is None,
            unexpected_import_children=children, imported_document=imported)
        _write_receipt(receipt, report, create=True); receipt_created = True
        _anchor_document(sw, anchor_path, anchor_sha, native)
        model = _find_document(sw, output)
        if model is not None:
            if call(model, "GetSaveFlag") or _file_hash(output) != expected_output_current_sha256:
                raise ValueError("Owned output changed before close")
            native("close_saved_owned_output", lambda: _close_owned(sw, model, [output]))
        if acknowledge_discard_unexpected_import:
            donor, fresh_imported, fresh_children = _unexpected_import_assembly(sw, prior, staged)
            if fresh_imported != imported or fresh_children != children:
                raise ValueError("Unexpected import component ownership changed before close")
        else:
            donor = _owned_donor(sw, staged, imported)
        if donor is not None:
            native("close_owned_donor", lambda: _close_owned(sw, donor, [staged], imported_title=imported["title"]))
        for child in children:
            model = _find_document(sw, child["path"])
            if model is not None:
                if str(call(model,"GetTitle")) != child["title"] or call(model,"GetType") != 1 or Path(child["path"]).exists():
                    raise ValueError("Import child identity or unsaved status changed before close")
                native("close_owned_import_child", lambda model=model,child=child: _close_owned(sw, model, [child["path"]]))
            if Path(child["path"]).exists(): raise ValueError("Unexpected import child was saved during cleanup")
        anchor = _anchor_document(sw, anchor_path, anchor_sha, native)
        from scripts.sw_assembly import _activate_model_document
        def restore():
            anchor.Visible = True
            if not _activate_model_document(sw, anchor): raise ValueError("Cannot restore original anchor")
        native("restore_exact_anchor", restore)
        _session(sw, process_id, str(anchor_path), [output, staged, config["source_path"], config["donor_step_path"], *[row["path"] for row in children]])
        _check_files(before["frozen_files"])
        if _file_hash(output) != expected_output_current_sha256 or _file_hash(prior_path) != transfer_receipt_sha256:
            raise ValueError("Saved output or original receipt changed during cleanup")
        report.update(status="review_required", phase="finished", cleanup_verified=True,
            source_files_unchanged=True, reason="OWNED_DOCUMENTS_CLEANED_WITHOUT_SAVE_OR_GEOMETRY_QUALIFICATION")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"], phase="finished", issue=_error(exc))
    finally:
        if receipt_created:
            try: _write_receipt(receipt, report)
            except Exception as exc: report.update(status="uncertain", cleanup_verified=False, receipt_write_error=_error(exc))
    return report


def qualify_reference_copy(sw, *, process_id, expected_document_path, action, source_path,
        source_sha256, output_path, replacements, qualification_only, frozen_files=None,
        expected_state_sha256=None, receipt_path=None):
    """只替换关闭的独占装配副本中的明确引用；BOOL 返回不等同于身份或动画验证。"""
    values = dict(locals()); values.pop("sw"); values["frozen_files"] = [] if frozen_files is None else frozen_files
    report = dict(status="error", phase="preflight", mutation_attempted=False, may_continue=False,
        reference_replacements_verified=False, native_reference_calls_returned=False, assembly_identity_verified=False,
        animation_verified=False, production_release=False, replacements=[])
    receipt = None
    try:
        if type(replacements) is not list or not 1 <= len(replacements) <= 8:
            raise ValueError("One to eight exact reference replacements required")
        paths = []; old_keys = set()
        for row in replacements:
            if type(row) is not dict or set(row) != {"old_path", "old_sha256", "new_path", "new_sha256"}:
                raise ValueError("Exact old/new path+SHA required")
            old = _path(row["old_path"], {".sldprt", ".sldasm"})
            new = _path(row["new_path"], {old.suffix.lower()})
            key = _path_identity(old)
            if key == _path_identity(new) or key in old_keys: raise ValueError("Ambiguous replacement map")
            old_keys.add(key); paths.extend([old, new])
            if _file_hash(old) != _hash(row["old_sha256"]) or _file_hash(new) != _hash(row["new_sha256"]):
                raise ValueError("Replacement source/target SHA changed")
        if old_keys.intersection(_path_identity(row["new_path"]) for row in replacements):
            raise ValueError("Chained/cyclic replacement maps are not allowed")
        state, _anchor, source, output = _common(sw, values, ".sldasm", paths)
        if _path_identity(source) in {_path_identity(p) for p in paths} or _path_identity(output) in {_path_identity(p) for p in paths}:
            raise ValueError("Assembly source/output cannot alias replacement references")
        for row in replacements:
            for prefix in ("old", "new"):
                state["frozen_files"][_path_identity(row[prefix+"_path"])] = dict(path=row[prefix+"_path"], sha256=row[prefix+"_sha256"])
        report.update(before=state, state_sha256=_digest(state), output_path=str(output))
        receipt = _receipt(report, values, state)
        if action == "prepare": report.update(status="ok", phase="prepared", apply_eligible=True); return report
        _session(sw, process_id, expected_document_path, [source, output, *paths]); _check_files(state["frozen_files"])
        report.update(mutation_attempted=True, phase="copy_native_assembly"); _write_receipt(receipt, report)
        report["copied_source_sha256"] = _copy_exclusive(source, output)
        for row in replacements:
            _session(sw, process_id, expected_document_path, [source, output, *paths]); _check_files(state["frozen_files"])
            step = dict(**row, attempted=True, returned=False, native_return=None)
            report["replacements"].append(step); report["phase"] = "ReplaceReferencedDocument"; _write_receipt(receipt, report)
            value = call(sw, "ReplaceReferencedDocument", str(output), row["old_path"], row["new_path"])
            step.update(returned=True, native_return=value); report["phase"] = "ReplaceReferencedDocument_returned"; _write_receipt(receipt, report)
            if value is not True: raise ValueError("Native reference replacement did not return true; no next replacement")
        _session(sw, process_id, expected_document_path, [source, output, *paths]); _check_files(state["frozen_files"])
        report.update(status="review_required", phase="finished", output_sha256=_file_hash(output),
            source_files_unchanged=True, native_reference_calls_returned=True,
            reason="CLOSED_REFERENCE_RETURNS_ONLY_REOPEN_ROSTER_AXES_AND_ANIMATION_UNVERIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"], phase="finished", issue=_error(exc))
    finally:
        if receipt:
            try: _write_receipt(receipt, report)
            except Exception as exc: report.update(status="uncertain", receipt_write_error=_error(exc), reference_replacements_verified=False)
    return report
