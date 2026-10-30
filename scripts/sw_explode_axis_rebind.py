"""Bounded repair of missing axes on existing exploded-view steps."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from scripts import sw_native_assembly_audit as audit
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_operation_guard import _path_identity

AXES = (("GetExplodeDirection", "SetExplodeDirection", 2),
        ("GetRotationAxis", "SetRotationAxis", 0))
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def _document_guard(sw, process_id, path, *, clean=False, configuration_name=None):
    model, document = audit._guard(sw, process_id, path, clean=clean)
    kind = audit.call(model, "GetType")
    if type(kind) is not int or kind != 2:
        raise ValueError("Strict native assembly type required")
    cfg = audit._member(audit._member(model, "ConfigurationManager"), "ActiveConfiguration")
    actual = audit._str(audit._member(cfg, "Name"))
    if not actual or (configuration_name is not None and actual != configuration_name):
        raise ValueError("Active configuration differs from prepared state")
    return model, dict(document, active_configuration=actual)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _missing_axis(index):
    return dict(index=index, entity_present=False, owner=None, surface_available=False,
                is_cylinder=None, cylinder_parameters=None)


def _targets(value):
    if type(value) is not list or not 1 <= len(value) <= 32:
        raise ValueError("One to 32 exact existing steps required")
    indices, names = set(), set()
    for row in value:
        if type(row) is not dict or set(row) != {"index", "name"}:
            raise ValueError("Each step requires only index and name")
        if type(row["index"]) is not int or not 0 <= row["index"] <= 511:
            raise ValueError("Bounded integer step index required")
        if type(row["name"]) is not str or not row["name"] or len(row["name"]) > 1000:
            raise ValueError("Exact step name required")
        if row["index"] in indices or row["name"] in names:
            raise ValueError("Duplicate step target")
        indices.add(row["index"]); names.add(row["name"])
    return deepcopy(value)


def _step_lookup(snapshot, targets):
    rows = snapshot["native_step_sequence"]
    result = {}
    for target in targets:
        matches = [row for row in rows if row["index"] == target["index"] and row["name"] == target["name"]]
        if len(matches) != 1:
            raise ValueError("Exact existing step index/name not found")
        result[target["index"]] = matches[0]
    return result


def _expected(snapshot, mapping, owner, cylinder, targets):
    expected = audit._mapped_snapshot(snapshot, mapping)
    matches = [row for row in expected["components"] if all(
        row[key] == owner[key] for key in ("name", "reference", "path"))]
    if len(matches) != 1 or matches[0]["matrix"] != IDENTITY:
        raise ValueError("A unique identity-transform owner is required")
    if matches[0]["suppressed"] or not matches[0]["loaded"]:
        raise ValueError("Axis owner must be resolved and unsuppressed")
    missing = deepcopy(expected)
    good_rows = _step_lookup(expected, targets)
    missing_rows = _step_lookup(missing, targets)
    for target in targets:
        for getter, _setter, index in AXES:
            row = good_rows[target["index"]]["axes"][getter]
            if row != dict(index=index, entity_present=True, owner=owner,
                           surface_available=True, is_cylinder=True,
                           cylinder_parameters=cylinder, entity_type=2):
                raise ValueError("Frozen target axis is not the exact expected owner/cylinder")
            missing_rows[target["index"]]["axes"][getter] = _missing_axis(index)
    return expected, missing


def _step_record(step, index, known):
    return dict(
        index=index, name=audit._str(audit._member(step, "Name")),
        distance_m=audit._number(audit._member(step, "ExplodeDistance")),
        angle_rad=audit._number(audit._member(step, "RotationAngle")),
        components=sorted(audit._str(audit._member(item, "Name2")) for item in
                          audit._array(audit.call(step, "GetComponents"), 1024, "step components")),
        axes={getter: audit._axis(step, getter, known) for getter, _setter, _index in AXES},
    )


def _reverse_flags(step):
    return dict(
        reverse_translation=audit._bool(audit._member(step, "ReverseTranslationDirection")),
        reverse_rotation=audit._bool(audit._member(step, "ReverseRotationDirection")),
    )


def _structure(model):
    snapshot = {}
    audit._snapshot(model, snapshot)
    cfg = audit._native_interface(audit._member(audit._member(model, "ConfigurationManager"),
                                               "ActiveConfiguration"), "IConfiguration")
    steps, flags = {}, []
    for row in snapshot["native_step_sequence"]:
        raw = audit.call(cfg, "GetExplodeStep", row["index"])
        if raw is None:
            raise ValueError("Existing step disappeared")
        step = audit._native_interface(raw, "IExplodeStep")
        if _step_record(step, row["index"], snapshot["components"]) != row:
            raise ValueError("Step changed during structural capture")
        flags.append(dict(index=row["index"], name=row["name"], **_reverse_flags(step)))
        steps[row["index"]] = step
    return snapshot, flags, steps


def _signed_cylinder_match(actual, expected, distance_tolerance=1e-9, direction_tolerance=1e-8):
    actual = audit._vector(actual, 7); expected = audit._vector(expected, 7)
    if actual[6] <= 0 or expected[6] <= 0:
        return False
    a, b = actual[3:6], expected[3:6]
    na, nb = math.sqrt(sum(v*v for v in a)), math.sqrt(sum(v*v for v in b))
    if abs(na-1) > direction_tolerance or abs(nb-1) > direction_tolerance:
        return False
    if max(abs(a[i]-b[i]) for i in range(3)) > direction_tolerance:
        return False
    delta = [actual[i]-expected[i] for i in range(3)]
    along = sum(delta[i]*b[i] for i in range(3))
    perpendicular = math.sqrt(sum((delta[i]-along*b[i])**2 for i in range(3)))
    return perpendicular <= distance_tolerance and abs(actual[6]-expected[6]) <= distance_tolerance


def _entity_evidence(entity):
    typed = audit._native_interface(entity, "IEntity")
    if audit._int(audit.call(typed, "GetType")) != 2:
        raise ValueError("Corresponding entity must be a face")
    component = audit.call(typed, "GetComponent")
    if component is None:
        raise ValueError("Assembly-context face has no owner")
    owner = dict(name=audit._str(audit._member(component, "Name2")),
                 reference=audit._str(audit._member(component, "ComponentReference")),
                 path=_path_identity(audit._str(audit.call(component, "GetPathName"))))
    surface = audit.call(audit._native_interface(entity, "IFace2"), "GetSurface")
    if surface is None or not audit._bool(audit.call(surface, "IsCylinder")):
        raise ValueError("Corresponding assembly-context surface is not cylindrical")
    return typed, dict(owner=owner, entity_type=2,
                       cylinder_parameters=audit._vector(audit._member(surface, "CylinderParams"), 7))



def _face_group(value):
    if value is None:
        return None
    if type(value) is not list or not 2 <= len(value) <= 32:
        raise ValueError("Explicit equivalent-face group requires two to 32 faces")
    seen = set()
    for item in value:
        if type(item) is not dict or set(item) != {"body_index", "face_index"}:
            raise ValueError("Each equivalent face requires only body_index and face_index")
        body, face = item["body_index"], item["face_index"]
        if (type(body) is not int or not 0 <= body < 64
                or type(face) is not int or not 0 <= face < 8192):
            raise ValueError("Strict bounded body/face indices required")
        if (body, face) in seen:
            raise ValueError("Duplicate equivalent face")
        seen.add((body, face))
    return [dict(body_index=body, face_index=face) for body, face in sorted(seen)]


def _equivalent_group_selection(component, matches, evidence, owner, cylinder, group):
    def fail(message):
        error = ValueError(message)
        error.candidate_evidence = evidence
        raise error

    expected_pairs = [(item["body_index"], item["face_index"]) for item in group]
    actual_pairs = sorted((row["body_index"], row["face_index"]) for _face, row in matches)
    evidence.update(policy="Explicit exact-parameter axis-equivalent face group; lowest body/face index, never area",
                    requested_equivalent_face_group=group,
                    axis_equivalent_group=[],
                    face_surface_sense_verified=False,
                    native_direction_equivalence_verified=False,
                    motion_review_required=True)
    if actual_pairs != expected_pairs:
        fail("Explicit face group must exactly equal all semantic cylinder matches")
    if any(row["cylinder_parameters"] != cylinder for _face, row in matches):
        fail("Every equivalent face must have the exact frozen seven cylinder parameters")
    entities = {}
    for face, row in sorted(matches, key=lambda item: (item[1]["body_index"], item[1]["face_index"])):
        corresponding = audit.call(component, "GetCorresponding", face)
        if corresponding is None:
            fail("Equivalent assembly-context face unavailable")
        try:
            entity, context = _entity_evidence(corresponding)
        except Exception as exc:
            fail("Equivalent face context could not be verified: " + str(exc))
        evidence["axis_equivalent_group"].append(dict(face=deepcopy(row), assembly_context=context))
        if context != dict(owner=owner, entity_type=2, cylinder_parameters=cylinder):
            fail("Equivalent face owner or exact assembly cylinder differs")
        entities[(row["body_index"], row["face_index"])] = entity
    selected_pair = expected_pairs[0]
    selected = evidence["axis_equivalent_group"][0]
    evidence["selected"] = deepcopy(selected["face"])
    evidence["assembly_context"] = deepcopy(selected["assembly_context"])
    evidence["geometric_axis_equivalence_verified"] = True
    return entities[selected_pair], evidence


def _select_cylinder(model, snapshot, owner, cylinder, equivalent_face_group=None):
    group = _face_group(equivalent_face_group)
    rows, objects = audit._components(model)
    if rows != snapshot["components"]:
        raise ValueError("Component state changed before cylinder selection")
    component = objects.get(owner["name"])
    if component is None:
        raise ValueError("Exact owner instance missing")
    owner_row = next(row for row in rows if row["name"] == owner["name"])
    if (audit._mapped_snapshot(owner_row, {})["path"] != owner["path"]
            or owner_row["reference"] != owner["reference"]):
        raise ValueError("Axis owner instance differs")
    part = audit.call(component, "GetModelDoc2")
    if part is None or audit._int(audit.call(part, "GetType")) != 1:
        raise ValueError("Resolved native owner part required")
    cfg = audit._member(audit._member(part, "ConfigurationManager"), "ActiveConfiguration")
    if audit._str(audit._member(cfg, "Name")) != owner_row["configuration"]:
        raise ValueError("Owner part active configuration differs from component reference")
    candidates, matches = [], []
    bodies = audit._array(audit.call(part, "GetBodies2", 0, False), 64, "solid bodies")
    for body_index, body in enumerate(bodies):
        faces = audit._array(audit.call(body, "GetFaces"), 8192, "solid faces")
        for face_index, face in enumerate(faces):
            surface = audit.call(face, "GetSurface")
            if surface is None:
                raise ValueError("Owner face surface unavailable")
            if not audit._bool(audit.call(surface, "IsCylinder")):
                continue
            params = audit._vector(audit._member(surface, "CylinderParams"), 7)
            area = audit._number(audit.call(face, "GetArea"))
            if area < 0:
                raise ValueError("Negative face area")
            matched = _signed_cylinder_match(params, cylinder)
            row = dict(body_index=body_index, face_index=face_index,
                       cylinder_parameters=params, area_m2=area, semantic_match=matched)
            candidates.append(row)
            if matched:
                matches.append((face, row))
    evidence = dict(candidates=candidates, match_count=len(matches),
                    policy="Unique signed axis-line and radius match; never largest-face selection")
    if group is not None:
        return _equivalent_group_selection(component, matches, evidence, owner, cylinder, group)
    if len(matches) != 1:
        error = ValueError("Cylinder selection must have exactly one semantic match")
        error.candidate_evidence = evidence
        raise error
    face, row = matches[0]
    if row["cylinder_parameters"] != cylinder:
        error = ValueError("Semantic cylinder matched but frozen parameterization differs; no setters")
        error.candidate_evidence = evidence
        raise error
    corresponding = audit.call(component, "GetCorresponding", face)
    if corresponding is None:
        raise ValueError("Assembly-context corresponding face unavailable")
    entity, context = _entity_evidence(corresponding)
    evidence["selected"] = row; evidence["assembly_context"] = context
    if context != dict(owner=owner, entity_type=2, cylinder_parameters=cylinder):
        raise ValueError("Corresponding face owner or cylinder differs")
    return entity, evidence


def _dependency_hashes(snapshot):
    paths = {_path_identity(row["path"]): row["path"] for row in snapshot["components"]}
    if not paths or len(paths) > 1024:
        raise ValueError("Bounded saved component files required")
    return {key: audit._file_hash(audit._path(paths[key], {".sldprt", ".sldasm"})) for key in sorted(paths)}


def _unchanged_files(source, source_sha, owner_path, owner_sha, baseline_path, baseline_sha):
    for path, expected in ((source, source_sha), (owner_path, owner_sha), (baseline_path, baseline_sha)):
        if audit._file_hash(path) != expected:
            raise ValueError("Frozen file changed")


def rebind_explode_axes(sw, *, process_id, expected_document_path, expected_file_sha256,
                       action, expected_snapshot_path, expected_snapshot_sha256,
                       path_replacements, owner_name, owner_reference, owner_path, owner_sha256,
                       cylinder_parameters_native, target_steps, receipt_path,
                       expected_state_sha256=None, prepare_receipt_path=None,
                       prepare_receipt_sha256=None, equivalent_face_group=None):
    """Prepare or apply one bounded repair. Never creates steps or saves the model."""
    report = dict(status="error", phase="preflight", mutation_attempted=False,
                  native_dispatch_pending=False, model_saved=False, may_continue=False,
                  repair_verified=False, completed_setters=0, setters=[], production_release=False)
    receipt = None
    try:
        if type(process_id) is not int or process_id <= 0 or action not in ("prepare", "apply"):
            raise ValueError("Exact PID and prepare/apply action required")
        targets = _targets(target_steps)
        group = _face_group(equivalent_face_group)
        source = audit._path(expected_document_path, {".sldasm"})
        source_sha = audit._hash(expected_file_sha256)
        baseline_path = audit._path(expected_snapshot_path, {".json"})
        baseline_sha = audit._hash(expected_snapshot_sha256)
        owner_file = audit._path(owner_path, {".sldprt"})
        owner_sha = audit._hash(owner_sha256)
        for text in (owner_name, owner_reference):
            if type(text) is not str or not text or len(text) > 1000:
                raise ValueError("Exact owner instance name and reference required")
        cylinder = audit._vector(cylinder_parameters_native, 7)
        if not _signed_cylinder_match(cylinder, cylinder):
            raise ValueError("Valid unit cylinder parameters required")
        mapping = audit._path_map(path_replacements)
        owner = dict(name=owner_name, reference=owner_reference, path=_path_identity(owner_path))
        baseline = audit._load_json(str(baseline_path), baseline_sha)
        expected, expected_missing = _expected(baseline.get("snapshot", baseline), mapping, owner, cylinder, targets)
        _unchanged_files(source, source_sha, owner_file, owner_sha, baseline_path, baseline_sha)
        pending_path = audit._path(receipt_path, {".json"}, new=True)
        prep = marker = None
        if action == "prepare":
            if any(value is not None for value in (expected_state_sha256, prepare_receipt_path, prepare_receipt_sha256)):
                raise ValueError("Prepare cannot accept apply credentials")
        else:
            token = audit._hash(expected_state_sha256)
            prep_path = audit._path(prepare_receipt_path, {".json"})
            prep_sha = audit._hash(prepare_receipt_sha256)
            prep = audit._load_json(str(prep_path), prep_sha)
            if (prep.get("status") != "ok" or prep.get("phase") != "prepared"
                    or prep.get("state_sha256") != token or _digest(prep.get("prepared_state")) != token):
                raise ValueError("A complete exact prepared receipt is required")
            marker = audit._path(str(prep_path) + ".apply_attempt.json", {".json"}, new=True)
        _write_receipt(pending_path, report, create=True); receipt = pending_path
        report["phase"] = "reading_structure"; _write_receipt(receipt, report)
        model, before_document = _document_guard(sw, process_id, source, clean=True)
        snapshot, flags, steps = _structure(model)
        current = audit._mapped_snapshot(snapshot, {})
        if snapshot["active_configuration"] != before_document["active_configuration"]:
            raise ValueError("Snapshot configuration differs from active document")
        if current != expected_missing:
            raise ValueError("Current state is not exactly the requested missing-axis baseline")
        dependencies = _dependency_hashes(snapshot)
        report["phase"] = "selecting_cylinder"; _write_receipt(receipt, report)
        if group is None:
            entity, candidate = _select_cylinder(model, snapshot, owner, cylinder)
        else:
            entity, candidate = _select_cylinder(model, snapshot, owner, cylinder, equivalent_face_group=group)
        _model, after_document = _document_guard(sw, process_id, source, clean=True)
        if after_document != before_document:
            raise ValueError("Document changed during preparation")
        _unchanged_files(source, source_sha, owner_file, owner_sha, baseline_path, baseline_sha)
        if _dependency_hashes(snapshot) != dependencies:
            raise ValueError("Dependencies changed during preparation")
        state = dict(process_id=process_id, document=before_document, source_sha256=source_sha,
                     baseline_path=str(baseline_path), baseline_sha256=baseline_sha,
                     path_replacements=mapping, owner=owner, owner_sha256=owner_sha,
                     cylinder_parameters=cylinder, targets=targets, snapshot=current,
                     reverse_flags=flags, dependency_hashes=dependencies, candidate=candidate)
        if group is not None:
            state["equivalent_face_group"] = group
            report.update(face_surface_sense_verified=False,
                          native_direction_equivalence_verified=False, motion_review_required=True)
        report.update(before_document=before_document, prepared_state=state, state_sha256=_digest(state),
                      change_budget=dict(steps=len(targets), missing_axes=2*len(targets), maximum_setters=2*len(targets)),
                      candidate=candidate)
        if action == "prepare":
            report.update(status="ok", phase="prepared", apply_eligible=True)
            return report
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Fresh state differs from prepared digest")
        _write_receipt(marker, dict(prepare_receipt=str(prep_path), prepare_sha256=prep_sha,
                                   state_sha256=expected_state_sha256, apply_receipt=str(receipt),
                                   no_replay=True), create=True)
        report["attempt_marker"] = str(marker)
        working = deepcopy(current)
        expected_rows = _step_lookup(expected, targets)
        working_rows = _step_lookup(working, targets)
        flags_by_index = {row["index"]: row for row in flags}
        for target in targets:
            index = target["index"]; step = steps[index]
            for getter, setter, _axis_index in AXES:
                _document_guard(sw, process_id, source, configuration_name=before_document["active_configuration"])
                _unchanged_files(source, source_sha, owner_file, owner_sha, baseline_path, baseline_sha)
                if audit._mapped_snapshot(_step_record(step, index, snapshot["components"]), {}) != working_rows[index]:
                    raise ValueError("Target step changed before setter")
                if dict(index=index, name=target["name"], **_reverse_flags(step)) != flags_by_index[index]:
                    raise ValueError("Reverse flags changed before setter")
                entry = dict(index=index, name=target["name"], method=setter, argument_index=-1,
                             attempted=True, returned=False, readback_verified=False)
                report["setters"].append(entry)
                report.update(phase="setter_intent", native_dispatch_pending=True, mutation_attempted=True)
                _write_receipt(receipt, report)
                returned = audit.call(step, setter, entity, -1)
                entry.update(returned=True, return_value=returned)
                report.update(phase="setter_returned", native_dispatch_pending=False)
                _write_receipt(receipt, report)
                if returned is not None:
                    raise ValueError("Generated VT_VOID setter returned an unexpected value")
                _document_guard(sw, process_id, source, configuration_name=before_document["active_configuration"])
                working_rows[index]["axes"][getter] = deepcopy(expected_rows[index]["axes"][getter])
                actual = audit._mapped_snapshot(_step_record(step, index, snapshot["components"]), {})
                actual_flags = dict(index=index, name=target["name"], **_reverse_flags(step))
                entry.update(readback=actual, reverse_flags=actual_flags)
                if actual != working_rows[index] or actual_flags != flags_by_index[index]:
                    raise ValueError("Axis setter changed unexpected axis, scalar, component or flag")
                entry["readback_verified"] = True; report["completed_setters"] += 1
                report["phase"] = "setter_verified"; _write_receipt(receipt, report)
        after_raw, after_flags, _steps = _structure(model)
        after = audit._mapped_snapshot(after_raw, {})
        report.update(after_snapshot=after, after_reverse_flags=after_flags)
        _model, report["after_document"] = _document_guard(sw, process_id, source, configuration_name=before_document["active_configuration"])
        _unchanged_files(source, source_sha, owner_file, owner_sha, baseline_path, baseline_sha)
        if after != expected or after_flags != flags or _dependency_hashes(after_raw) != dependencies:
            raise ValueError("Final structure, reverse flags or dependencies differ")
        changes = []
        before_rows = _step_lookup(current, targets)
        after_rows = _step_lookup(after, targets)
        for target in targets:
            for getter, _setter, _axis_index in AXES:
                if before_rows[target["index"]]["axes"][getter] != after_rows[target["index"]]["axes"][getter]:
                    changes.append(dict(**target, getter=getter))
        if len(changes) != 2*len(targets) or report["completed_setters"] != 2*len(targets):
            raise ValueError("Exact missing-axis repair count not established")
        report.update(status="review_required", phase="complete", repair_verified=True,
                      source_files_unchanged=True, changed_axis_references=changes,
                      exact_changed_axis_count=len(changes), snapshot_matches_expected=True,
                      reason="UNSAVED_AXIS_REBIND_REQUIRES_EXPLICIT_SAVE_REOPEN_AND_MOTION_REVIEW")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
                      failed_phase=report["phase"], phase="failed",
                      error=dict(type=type(exc).__name__, message=str(exc)))
        if hasattr(exc, "candidate_evidence"):
            report["candidate"] = exc.candidate_evidence
    finally:
        if receipt is not None:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=str(exc), repair_verified=False)
    return report
