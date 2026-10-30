"""Read one existing named circle against immutable sketch-creation evidence.

This path never selects, creates, edits, renames, saves or retries a profile.
A successful readback does not rewrite the historical creation outcome.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from scripts import sw_cam_profile_sketch as profile

MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def _hash_value(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Exact SHA256 required")
    return value


def _read_evidence(path, digest, pid, document_path, source_sha, spec):
    _hash_value(digest)
    if (type(path) is not str or not profile.absolute_document_path(path)
            or Path(path).suffix.casefold() != ".json" or not Path(path).is_file()
            or Path(path).is_symlink() or Path(path).stat().st_size > MAX_RECEIPT_BYTES):
        raise ValueError("Bounded immutable creation receipt required")
    raw = Path(path).read_bytes()
    if len(raw) > MAX_RECEIPT_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Creation receipt hash changed")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate creation receipt key")
            result[key] = value
        return result

    data = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite creation receipt")))
    if profile._sha(path) != digest:
        raise ValueError("Creation receipt changed during read")
    if (type(data) is not dict or data.get("status") not in ("ok", "uncertain")
            or any(data.get(key) is not True for key in
                ("mutation_attempted", "plane_create_attempted", "sketch_create_attempted", "sketch_edit_exited"))
            or any(data.get(key) is not False for key in ("saved", "CAD_solid_edit_attempted"))
            or type(data.get("CAM_calls")) is not int or data["CAM_calls"] != 0
            or data.get("cleanup_errors")):
        raise ValueError("Pinned named-plane/circle creation with exited edit and no save required")
    before = data["before"]
    if (type(before.get("pid")) is not int or before["pid"] != pid
            or before.get("needs_save") is not False
            or before.get("saved_file_sha256") != source_sha
            or profile._input(before["spec"]) != spec
            or profile._state_digest(before) != data.get("state_sha256")):
        raise ValueError("Creation baseline PID/source/spec/state mismatch")
    profile.check_document_target(before["path"], Path(before["path"]).name,
        expected_path=document_path, required=True)
    if data.get("created_plane", {}).get("name") != spec["plane_name"]:
        raise ValueError("Exact created plane evidence required")
    if not before.get("solids") or type(before.get("features")) is not list:
        raise ValueError("Creation baseline solids/tree required")
    return data


def _identity(sw, pid, path, source_sha):
    actual = profile.call(sw, "GetProcessID")
    if type(actual) is not int or actual != pid:
        raise ValueError("Exact native process ID changed")
    model = sw.ActiveDoc
    if model is None:
        raise ValueError("Active part required")
    kind = profile.call(model, "GetType")
    dirty = profile.call(model, "GetSaveFlag")
    if type(kind) is not int or kind != 1 or type(dirty) is not bool:
        raise ValueError("Strict native part type and save flag required")
    actual_path = profile.call(model, "GetPathName")
    title = profile.call(model, "GetTitle")
    profile.check_document_target(actual_path, title, expected_path=path, required=True)
    if profile._sha(path) != source_sha:
        raise ValueError("Exact saved source hash changed")
    return dict(process_id=actual, path=actual_path, title=title, type=kind, needs_save=dirty)


def _named_delta(state, evidence, spec):
    baseline = evidence["before"]
    names = [spec["plane_name"], spec["sketch_name"]]
    expected = [{"name": names[0], "type": "RefPlane"},
                {"name": names[1], "type": "ProfileFeature"}]
    if (any(row["name"].casefold() in {n.casefold() for n in names} for row in baseline["features"])
            or [row for row in state["features"] if row["name"] in names] != expected
            or [row for row in state["features"] if row["name"] not in names] != baseline["features"]):
        raise ValueError("Only the two exact named plane/sketch additions are allowed")
    old_planes = [row for row in state["planes"] if row["name"] != spec["plane_name"]]
    new_planes = [row for row in state["planes"] if row["name"] == spec["plane_name"]]
    if old_planes != baseline["planes"] or len(new_planes) != 1:
        raise ValueError("Existing reference planes changed or named plane missing")
    if new_planes[0] != evidence["created_plane"]:
        raise ValueError("Named plane differs from creator readback")
    if not profile._same_bodies(baseline["solids"], state["solids"]):
        raise ValueError("Solid fingerprint differs from creation baseline")
    return expected


def verify_existing_cam_profile_sketch(sw, *, expected_process_id, expected_document_path,
        spec, expected_source_sha256, creation_receipt_path, creation_receipt_sha256,
        receipt_path, qualification_only=True, expected_state_sha256=None):
    report = dict(status="error", action="verify_existing", phase="preflight",
        mutation_attempted=False, saved=False, CAD_solid_edit_attempted=False, CAM_calls=0,
        native_readback_verified=False, creation_replayed=False, selection_attempted=False,
        historical_creation_receipt_rewritten=False, native_read_diagnostics=[])
    created = False

    def persist():
        if created:
            profile._write_receipt(receipt_path, report)

    try:
        if type(expected_process_id) is not int or expected_process_id <= 0:
            raise ValueError("Exact positive process ID required")
        if (type(expected_document_path) is not str
                or not profile.absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold() != ".sldprt"
                or not Path(expected_document_path).is_file()):
            raise ValueError("Exact saved qualification part required")
        if qualification_only is not True or expected_state_sha256 is not None:
            raise ValueError("Read-only qualification action rejects prepared mutation state")
        _hash_value(expected_source_sha256)
        spec = profile._input(spec)
        if spec["profile"]["kind"] != "circle":
            raise ValueError("Existing named-circle verification only")
        if (type(receipt_path) is not str or not Path(receipt_path).is_absolute()
                or Path(receipt_path).suffix.casefold() != ".json"
                or not Path(receipt_path).parent.is_dir() or Path(receipt_path).exists()
                or Path(receipt_path).is_symlink()):
            raise ValueError("Unique absolute read-only verification receipt required")
        evidence = _read_evidence(creation_receipt_path, creation_receipt_sha256,
            expected_process_id, expected_document_path, expected_source_sha256, spec)
        report["creation_evidence"] = dict(path=creation_receipt_path, sha256=creation_receipt_sha256,
            historical_status=evidence["status"])
        profile._write_receipt(receipt_path, report, create=True)
        created = True
        with profile.solidworks_operation_lock(process_id=expected_process_id, timeout_seconds=2):
            initial = _identity(sw, expected_process_id, expected_document_path, expected_source_sha256)

            def check():
                if (_identity(sw, expected_process_id, expected_document_path, expected_source_sha256) != initial
                        or profile._sha(creation_receipt_path) != creation_receipt_sha256):
                    raise ValueError("Document/dirty/source/evidence changed during read-only verification")

            def capture(phase):
                report["phase"] = phase
                persist()
                check()
                state, model, refs = profile._snapshot(sw, expected_process_id, expected_document_path, spec)
                check()
                if (state["needs_save"] is not initial["needs_save"]
                        or state["saved_file_sha256"] != expected_source_sha256):
                    raise ValueError("Snapshot identity disagrees with strict raw identity")
                _named_delta(state, evidence, spec)
                selected = [f for f in refs if f.Name == spec["sketch_name"]]
                if len(selected) != 1 or profile.call(selected[0], "IsSuppressed") is not False:
                    raise ValueError("Exact unsuppressed named sketch required")
                sketch = profile.call(selected[0], "GetSpecificFeature2")
                check()
                diagnostic = {}
                report["native_read_diagnostics"].append(dict(phase=phase, diagnostic=diagnostic))
                persist()
                readback = profile._read_sketch(sw, sketch, spec, diagnostic=diagnostic)
                check()
                transform = sketch.ModelToSketchTransform
                inverse = profile.call(transform, "Inverse")
                profile._rigid_transform(inverse)
                mu = profile.call(sw, "GetMathUtility")
                origin = profile._point(mu, [0., 0., 0.], inverse)
                tip = profile._point(mu, [0., 0., 1.], inverse)
                normal = [b-a for a,b in zip(origin, tip)]
                axis = "XYZ".index(spec["plane_axis"])
                if (abs(origin[axis]-spec["plane_offset_mm"]/1000) > profile.TOL_M
                        or abs(abs(normal[axis])-1) > 1e-9
                        or any(abs(normal[i]) > 1e-9 for i in range(3) if i != axis)):
                    raise ValueError("Actual sketch plane differs from requested named plane geometry")
                state.update(sketch_readback=readback, sketch_plane_geometry=dict(origin_m=origin,normal=normal),
                    strict_identity=deepcopy(initial), native_method_diagnostics=diagnostic)
                check()
                return state

            before = capture("before_readback")
            report["before"] = before
            report["before_state_sha256"] = profile._state_digest(before)
            persist()
            after = capture("after_readback")
            report["after"] = after
            persist()
            comparable = deepcopy(after)
            comparable["solids"] = deepcopy(before["solids"])
            if not profile._same_bodies(before["solids"], after["solids"]) or comparable != before:
                raise ValueError("Read-only verification changed captured state")
            check()
            report.update(status="ok", phase="finished", native_readback_verified=True,
                named_additions_verified=_named_delta(after, evidence, spec),
                after_state_sha256=profile._state_digest(after), source_file_unchanged=True,
                creation_receipt_unchanged=True, dirty_state_unchanged=True,
                limits=["Body box/mass fingerprints are not full BRep equivalence.",
                        "Named plane and sketch geometry verified; no added dimensions/relations or manufacturing readiness.",
                        "No CAM feature, save, close/reopen or toolpath qualification is performed."])
    except Exception as exc:
        report.update(status="error", failed_phase=report["phase"], phase="finished",
            issue={"type":type(exc).__name__,"message":str(exc)}, native_readback_verified=False)
    finally:
        if created:
            try:
                persist()
            except Exception as exc:
                report.update(status="error", native_readback_verified=False,
                    receipt_write_error={"type":type(exc).__name__,"message":str(exc)})
    return report
