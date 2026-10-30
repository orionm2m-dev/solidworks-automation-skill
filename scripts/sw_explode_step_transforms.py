"""Read bounded existing explode-step transforms without changing presentation."""
from __future__ import annotations

from copy import deepcopy
import math

from scripts import sw_native_assembly_audit as audit
from scripts import sw_explode_axis_rebind as axes
from scripts.sw_cam_generation import _write_receipt


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    return axes._digest(left) == axes._digest(right)


def _targets(value):
    _require(type(value) is list and 1 <= len(value) <= 32,
             "One to 32 exact existing steps required")
    indices, names = set(), set()
    for row in value:
        _require(type(row) is dict and set(row) == {"index", "name", "component_name"},
                 "Exact index/name/component_name target required")
        _require(type(row["index"]) is int and 0 <= row["index"] <= 511,
                 "Bounded strict integer step index required")
        for key in ("name", "component_name"):
            _require(type(row[key]) is str and 0 < len(row[key]) <= 1000,
                     "Exact nonempty step/component name required")
        _require(row["index"] not in indices and row["name"] not in names,
                 "Duplicate step index or name")
        indices.add(row["index"]); names.add(row["name"])
    return deepcopy(value)


def _matrix(value):
    values = audit._array(value, 16, "native step matrix")
    _require(len(values) == 16, "Native matrix must contain exactly 16 values")
    _require(all(type(v) in (float, int) and math.isfinite(v) for v in values),
             "Native matrix requires finite numeric values, not Boolean/status values")
    return [float(v) for v in values]


def _capture(sw, process_id, source, source_sha):
    _require(audit._file_hash(source) == source_sha, "Saved assembly SHA changed")
    model, document = axes._document_guard(sw, process_id, source, clean=True)
    raw, flags, steps = axes._structure(model)
    dependencies = axes._dependency_hashes(raw)
    _, final_document = axes._document_guard(
        sw, process_id, source, clean=True, configuration_name=document["active_configuration"])
    _require(_same(document, final_document), "Document changed during capture")
    _require(audit._file_hash(source) == source_sha, "Saved assembly SHA changed during capture")
    return model, steps, dict(document=audit._mapped_snapshot(document, {}),
        snapshot=audit._mapped_snapshot(raw, {}), reverse_flags=flags,
        dependency_hashes=dependencies)


def _guard(sw, process_id, source, source_sha, document):
    _require(audit._file_hash(source) == source_sha, "Saved assembly SHA changed during getters")
    _, current = axes._document_guard(
        sw, process_id, source, clean=True, configuration_name=document["active_configuration"])
    _require(_same(audit._mapped_snapshot(current, {}), document),
             "Active document identity/dirty/configuration changed during getters")


def read_explode_step_transforms(sw, *, process_id, expected_document_path,
        expected_file_sha256, targets, receipt_path):
    """Read native matrices of exact existing single-component steps; never move them."""
    report = dict(status="error", phase="preflight", mutation_attempted=False,
        model_saved=False, readback_complete=False, state_unchanged=False,
        production_release=False, motion_verified=False, collision_verified=False,
        native_direction_verified=False, results=[],
        scope="EXACT_EXISTING_SINGLE_COMPONENT_EXPLODE_STEP_GETTERS",
        matrix_contract="Native step transform arrays; delta/cumulative frame semantics require separate qualification.",
        snapshot_scope="Active-configuration components, existing exploded steps and all reverse flags; study metadata and dependency file hashes.")
    receipt = None
    try:
        _require(type(process_id) is int and process_id > 0, "Exact positive integer PID required")
        wanted = _targets(targets)
        source = audit._path(expected_document_path, {".sldasm"})
        source_sha = audit._hash(expected_file_sha256)
        candidate = audit._path(receipt_path, {".json"}, new=True)
        _write_receipt(candidate, report, create=True); receipt = candidate
        report["phase"] = "reading_before"; _write_receipt(receipt, report)
        model, native_steps, before = _capture(sw, process_id, source, source_sha)
        report.update(process_id=process_id, source_sha256=source_sha, targets=wanted,
                      before=before, before_state_sha256=axes._digest(before))
        flags = {row["index"]: row for row in before["reverse_flags"]}
        for target in wanted:
            matches = [row for row in before["snapshot"]["native_step_sequence"]
                       if row["index"] == target["index"] and row["name"] == target["name"]]
            _require(len(matches) == 1, "Exact existing step index/name not found")
            row = matches[0]
            _require(row["components"] == [target["component_name"]],
                     "Reader supports only the exact single-component step")
            step = native_steps[target["index"]]
            report.update(phase="reading_step_identity", current_target=target)
            _write_receipt(receipt, report)
            _guard(sw, process_id, source, source_sha, before["document"])
            count = audit.call(step, "GetNumOfComponents")
            _require(type(count) is int and count == 1, "Native component count must be strict integer one")
            _guard(sw, process_id, source, source_sha, before["document"])
            name = audit.call(step, "GetComponentName", 0)
            _require(type(name) is str and name == target["component_name"],
                     "Native selection index zero does not name the exact component; no alternate index probing")
            report.update(phase="reading_step_matrices", current_target=target)
            _write_receipt(receipt, report)
            _guard(sw, process_id, source, source_sha, before["document"])
            whole = _matrix(audit.call(step, "GetComponentXform"))
            result = dict(**target, component_index=0, native_component_count=count,
                distance_m=row["distance_m"], angle_rad=row["angle_rad"],
                axes=deepcopy(row["axes"]), reverse_flags=deepcopy(flags[target["index"]]),
                step_transform=whole, component_transform=None, readback_complete=False)
            report["results"].append(result)
            report["phase"] = "reading_component_matrix"
            _write_receipt(receipt, report)
            _guard(sw, process_id, source, source_sha, before["document"])
            specific = _matrix(audit.call(step, "GetSpecificComponentXForm", 0))
            _guard(sw, process_id, source, source_sha, before["document"])
            result.update(component_transform=specific, readback_complete=True,
                getter_arrays_identical=whole == specific,
                maximum_getter_array_difference=max(abs(a-b) for a,b in zip(whole, specific)))
            _write_receipt(receipt, report)
        model = native_steps = None
        report["phase"] = "reading_after"; _write_receipt(receipt, report)
        _, after_steps, after = _capture(sw, process_id, source, source_sha)
        after_steps = None
        report.update(after=after, after_state_sha256=axes._digest(after))
        _require(_same(before, after), "Full snapshot, reverse flags, document state or dependencies changed")
        report.update(status="review_required", phase="complete", readback_complete=True,
            state_unchanged=True, source_files_unchanged=True, reverse_flags_unchanged=True,
            reason="NATIVE_STEP_MATRICES_CAPTURED_NO_MOTION_OR_COLLISION_APPROVAL")
    except Exception as exc:
        report.update(failed_phase=report["phase"], phase="failed",
            error=dict(type=type(exc).__name__, message=str(exc)))
    finally:
        if receipt is not None:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status="uncertain", receipt_write_error=str(exc), readback_complete=False)
    return report
