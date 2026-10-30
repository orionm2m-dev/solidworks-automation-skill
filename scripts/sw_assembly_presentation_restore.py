"""Restore one existing exploded-view presentation after a pinned axis-repair readback."""
from __future__ import annotations

from copy import deepcopy

from scripts import sw_native_assembly_audit as audit
from scripts import sw_explode_axis_rebind as axes
from scripts.sw_cam_generation import _write_receipt


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    return axes._digest(left) == axes._digest(right)


def _without_poses(snapshot):
    result = deepcopy(snapshot)
    for row in result["components"]:
        row.pop("matrix")
    return result


def _flags(value, snapshot):
    _require(type(value) is list and len(value) == len(snapshot["native_step_sequence"]),
             "Reverse flags must cover every existing step")
    for row, step in zip(value, snapshot["native_step_sequence"]):
        _require(type(row) is dict and set(row) == {
            "index", "name", "reverse_translation", "reverse_rotation"},
            "Exact reverse-flag record required")
        _require(type(row["index"]) is int and row["index"] == step["index"]
                 and row["name"] == step["name"], "Reverse-flag step identity differs")
        _require(type(row["reverse_translation"]) is bool
                 and type(row["reverse_rotation"]) is bool, "Strict Boolean reverse flags required")
    return value


def _prior_context(prior, process_id, source_sha, view_name):
    """Accept only a fully returned repair whose final difference is component poses."""
    _require(type(prior) is dict, "Pinned rebind receipt required")
    _require(prior.get("status") == "uncertain" and prior.get("phase") == "failed"
             and prior.get("failed_phase") == "setter_verified",
             "Only a completed-setter final-verification mismatch is supported")
    _require(prior.get("mutation_attempted") is True
             and prior.get("native_dispatch_pending") is False
             and prior.get("model_saved") is False
             and prior.get("repair_verified") is False,
             "Prior mutation/return/save state is not eligible")
    _require(prior.get("error") == {
        "type": "ValueError", "message": "Final structure, reverse flags or dependencies differ"},
        "Unrelated prior error cannot authorize a presentation change")
    state = prior.get("prepared_state")
    _require(type(state) is dict and prior.get("state_sha256") == axes._digest(state),
             "Prior prepared-state digest differs")
    _require(type(state.get("process_id")) is int and state["process_id"] == process_id
             and state.get("source_sha256") == source_sha, "Prior PID or source SHA differs")
    targets = axes._targets(state["targets"])
    count = len(targets) * len(axes.AXES)
    _require(type(prior.get("completed_setters")) is int and prior["completed_setters"] == count,
             "Every bounded axis setter must have completed")
    _require(prior.get("change_budget") == {
        "steps": len(targets), "missing_axes": count, "maximum_setters": count},
        "Prior change budget differs")
    entries = prior.get("setters")
    _require(type(entries) is list and len(entries) == count, "Complete setter journal required")
    for entry, (target, (_getter, setter, _index)) in zip(
            entries, ((target, axis) for target in targets for axis in axes.AXES)):
        _require(type(entry) is dict and type(entry.get("index")) is int
                 and entry["index"] == target["index"] and entry.get("name") == target["name"]
                 and entry.get("method") == setter and type(entry.get("argument_index")) is int
                 and entry["argument_index"] == -1, "Setter journal identity differs")
        _require(all(entry.get(key) is True for key in ("attempted", "returned", "readback_verified"))
                 and "return_value" in entry and entry["return_value"] is None,
                 "All native VT_VOID setters must have verified readback")
    baseline_path = audit._path(state["baseline_path"], {".json"})
    baseline_sha = audit._hash(state["baseline_sha256"])
    baseline = audit._load_json(str(baseline_path), baseline_sha)
    expected, missing = axes._expected(
        baseline.get("snapshot", baseline), state["path_replacements"],
        state["owner"], state["cylinder_parameters"], targets)
    _require(_same(state["snapshot"], missing), "Prior before-snapshot is not the missing-axis baseline")
    after = prior["after_snapshot"]
    _require(_same(_without_poses(after), _without_poses(expected)),
             "Prior final mismatch contains non-presentation changes")
    _require(not _same(after, expected), "Prior snapshot already matches; no collapse is authorized")
    _require(expected["explode_views"] == [view_name] and after["explode_views"] == [view_name],
             "Exactly one explicitly named existing explode view required")
    before_flags = _flags(state["reverse_flags"], state["snapshot"])
    after_flags = _flags(prior["after_reverse_flags"], after)
    _require(_same(before_flags, after_flags), "Prior reverse flags changed")
    _require(prior["before_document"] == state["document"]
             and prior["before_document"].get("needs_save") is False
             and prior["after_document"].get("needs_save") is True,
             "Only the pinned clean-to-dirty repair state is supported")
    _require(prior["after_document"]["active_configuration"] == expected["active_configuration"]
             == state["document"]["active_configuration"], "Prior configuration changed")
    owner_identity = state["owner"]["path"]
    return dict(state=state, expected=expected, after=after, flags=before_flags,
                baseline_path=baseline_path, baseline_sha=baseline_sha,
                owner_identity=owner_identity)


def _file_guards(source, source_sha, prior_path, prior_sha, context):
    _require(audit._file_hash(source) == source_sha, "Saved assembly SHA changed")
    _require(audit._file_hash(prior_path) == prior_sha, "Pinned prior receipt changed")
    _require(audit._file_hash(context["baseline_path"]) == context["baseline_sha"],
             "Frozen baseline changed")


def _capture(sw, process_id, source, context, *, expected_snapshot):
    model, document = axes._document_guard(
        sw, process_id, source, configuration_name=context["expected"]["active_configuration"])
    _require(document["needs_save"] is True, "Pinned unsaved repair must remain dirty")
    raw, flags, _steps = axes._structure(model)
    current = audit._mapped_snapshot(raw, {})
    _require(_same(current, expected_snapshot), "Current full snapshot differs from pinned state")
    _require(_same(flags, context["flags"]), "Current reverse flags differ")
    dependencies = axes._dependency_hashes(raw)
    _require(_same(dependencies, context["state"]["dependency_hashes"]), "Dependency hashes differ")
    owner_rows = [row for row in raw["components"]
                  if audit._mapped_snapshot(row, {})["path"] == context["owner_identity"]
                  and row["name"] == context["state"]["owner"]["name"]]
    _require(len(owner_rows) == 1, "Exact owner instance absent")
    owner_path = audit._path(owner_rows[0]["path"], {".sldprt"})
    _require(audit._file_hash(owner_path) == context["state"]["owner_sha256"], "Owner part SHA changed")
    _, document_after = axes._document_guard(
        sw, process_id, source, configuration_name=document["active_configuration"])
    _require(_same(document, document_after), "Document changed during structural capture")
    return model, dict(document=document, snapshot=current, reverse_flags=flags,
                       dependency_hashes=dependencies)


def restore_assembly_presentation(sw, *, process_id, expected_document_path,
        expected_file_sha256, action, prior_rebind_receipt_path, prior_rebind_receipt_sha256,
        explode_view_name, receipt_path, expected_state_sha256=None,
        prepare_receipt_path=None, prepare_receipt_sha256=None):
    """Prepare or perform one collapse; never save, replay axes, or activate a study."""
    report = dict(status="error", phase="preflight", mutation_attempted=False,
                  native_dispatch_pending=False, model_saved=False, may_continue=False,
                  presentation_restored=False, production_release=False)
    receipt = None
    try:
        _require(type(process_id) is int and process_id > 0 and action in ("prepare", "apply"),
                 "Exact PID and prepare/apply action required")
        _require(type(explode_view_name) is str and 0 < len(explode_view_name) <= 1000,
                 "Exact existing explode view name required")
        source = audit._path(expected_document_path, {".sldasm"})
        source_sha = audit._hash(expected_file_sha256)
        prior_path = audit._path(prior_rebind_receipt_path, {".json"})
        prior_sha = audit._hash(prior_rebind_receipt_sha256)
        prior = audit._load_json(str(prior_path), prior_sha)
        context = _prior_context(prior, process_id, source_sha, explode_view_name)
        _require(audit._mapped_snapshot(prior["after_document"], {})["path"]
                 == audit._mapped_snapshot({"path": str(source)}, {})["path"], "Prior document path differs")
        _file_guards(source, source_sha, prior_path, prior_sha, context)
        candidate = audit._path(receipt_path, {".json"}, new=True)
        prep = marker = None
        if action == "prepare":
            _require(all(v is None for v in (
                expected_state_sha256, prepare_receipt_path, prepare_receipt_sha256)),
                "Prepare cannot accept apply credentials")
        else:
            token = audit._hash(expected_state_sha256)
            prep_path = audit._path(prepare_receipt_path, {".json"})
            prep_sha = audit._hash(prepare_receipt_sha256)
            prep = audit._load_json(str(prep_path), prep_sha)
            _require(prep.get("status") == "ok" and prep.get("phase") == "prepared"
                     and prep.get("state_sha256") == token
                     and axes._digest(prep.get("prepared_state")) == token,
                     "Exact complete prepared receipt required")
            marker = audit._path(str(prep_path) + ".apply_attempt.json", {".json"}, new=True)
        _write_receipt(candidate, report, create=True); receipt = candidate
        report["phase"] = "reading_structure"; _write_receipt(receipt, report)
        model, capture = _capture(sw, process_id, source, context, expected_snapshot=context["after"])
        _require(_same(capture["document"], prior["after_document"]), "Current dirty document differs from prior receipt")
        _file_guards(source, source_sha, prior_path, prior_sha, context)
        state = dict(process_id=process_id, source_sha256=source_sha,
                     prior_receipt_path=str(prior_path), prior_receipt_sha256=prior_sha,
                     explode_view_name=explode_view_name, **capture)
        report.update(before=capture, prepared_state=state, state_sha256=axes._digest(state),
                      expected_after_snapshot=context["expected"])
        if action == "prepare":
            report.update(status="ok", phase="prepared", apply_eligible=True)
            return report
        _require(report["state_sha256"] == expected_state_sha256, "Fresh state differs from prepare")
        _write_receipt(marker, dict(prepare_receipt=str(prep_path), prepare_sha256=prep_sha,
            state_sha256=expected_state_sha256, apply_receipt=str(receipt), no_replay=True), create=True)
        report["attempt_marker"] = str(marker)
        _, before_call = axes._document_guard(
            sw, process_id, source, configuration_name=context["expected"]["active_configuration"])
        _require(_same(before_call, capture["document"]), "Document changed before collapse")
        _file_guards(source, source_sha, prior_path, prior_sha, context)
        report.update(phase="collapse_intent", mutation_attempted=True, native_dispatch_pending=True)
        _write_receipt(receipt, report)
        returned = audit.call(model, "ShowExploded2", False, explode_view_name)
        report.update(phase="collapse_returned", native_dispatch_pending=False, return_value=returned)
        _write_receipt(receipt, report)
        _require(returned is True, "Native collapse did not return strict True")
        model_after, document_after = axes._document_guard(
            sw, process_id, source, configuration_name=context["expected"]["active_configuration"])
        after_raw, after_flags, _steps = axes._structure(model_after)
        after_snapshot = audit._mapped_snapshot(after_raw, {})
        after_dependencies = axes._dependency_hashes(after_raw)
        report.update(after_document=document_after, after_snapshot=after_snapshot,
                      after_reverse_flags=after_flags, after_dependency_hashes=after_dependencies)
        _write_receipt(receipt, report)
        _file_guards(source, source_sha, prior_path, prior_sha, context)
        _require(_same(after_snapshot, context["expected"]), "Collapsed snapshot differs from frozen baseline")
        _require(_same(after_flags, context["flags"]), "Reverse flags changed after collapse")
        _require(_same(after_dependencies, context["state"]["dependency_hashes"]), "Dependencies changed after collapse")
        _require(_same(document_after, capture["document"]), "Document identity/dirty state changed after collapse")
        _, final_document = axes._document_guard(
            sw, process_id, source, configuration_name=context["expected"]["active_configuration"])
        _require(_same(final_document, document_after), "Document changed during final capture")
        report.update(status="review_required", phase="complete", presentation_restored=True,
                      snapshot_matches_expected=True, reverse_flags_unchanged=True,
                      source_files_unchanged=True,
                      reason="UNSAVED_RESTORATION_REQUIRES_EXPLICIT_SAVE_REOPEN_AND_MOTION_REVIEW")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
                      failed_phase=report["phase"], phase="failed",
                      error=dict(type=type(exc).__name__, message=str(exc)))
    finally:
        if receipt is not None:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=str(exc), presentation_restored=False)
    return report
