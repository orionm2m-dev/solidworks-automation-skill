"""One software-only all-setups WIP export from a completed MILL route Save."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import re
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_inventory import validate_inventory_request
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_saved_plan_rebind import load_owned_startup
from scripts.sw_executable_launch import _process_identity, _same_path
from scripts.sw_cam_completed_gtp_save import SCOPE as SAVE_SCOPE, stable_save_payload, completed_gtp_save_marker
from scripts.sw_cam_completed_sandvik_save import read_feature_counts
from scripts.sw_cam_completed_sandvik_assignment import capture_assignment_snapshot, read_assignment_candidate
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins, load_route_batch_qualification
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch, capture_route_batch
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target

SCOPE = "MILL_COMPLETED_GTP_WIP_EXPORT_V1"
TARGET_KEYS = ("target_feature_native_id", "target_operation_native_id", "target_operation_setup_native_id")

def same_path(actual, expected):
    check_document_target(actual, None, expected_path=str(expected), required=True)

def route_scope(state, args):
    require(len(state["features"]) == 19 and len(state["feature_setups"]) == 3
        and len(state["operation_setups"]) == 3 and len(state["operations"]) == 6,
        "Exact nineteen-feature, three-setup, six-operation route required")
    ids = [row["native_id"] for row in state["operations"]]
    require(all(type(n) is int and n > 0 for n in ids) and len(set(ids)) == 6, "Unique operation IDs required")
    generated = [row for row in state["operations"] if row["toolpath_generated"] is True]
    require(len(generated) == 1, "Exactly one existing generated operation required")
    row = generated[0]
    require(row["native_id"] == args["target_operation_native_id"]
        and row["linked_feature_ids"] == [args["target_feature_native_id"]]
        and row["setup_native_id"] == args["target_operation_setup_native_id"]
        and row["assigned_tool"]["native_id"] == args["expected_candidate_tool_native_id"]
        and row["suppressed"] is False and row["mill_operation_type"] == 0,
        "Exact existing unsuppressed rough operation and assigned tool required")
    counts = args["expected_toolpath_record_counts"]
    require(type(counts) is list and 1 <= len(counts) <= 32
        and all(type(n) is int and n > 0 for n in counts)
        and row["toolpath_record_counts"] == counts, "Exact positive existing record counts required")
    require(all(r["toolpath_generated"] is False and r["toolpath_record_counts"] == []
        for r in state["operations"] if r["native_id"] != row["native_id"]),
        "The five protected operations must remain ungenerated")

def load_completed_route_save(path, sha256, *, owned_startup_receipt_path,
        owned_startup_receipt_sha256, read_mode, batch_qualification_receipt_path=None,
        batch_qualification_receipt_sha256=None, **args):
    """Load a finished Save without running historical current-source loaders."""
    data, pin = read_pin(path, sha256)
    require(data.get("scope") == SAVE_SCOPE and data.get("status") == "review_required"
        and data.get("phase") == "finished", "Completed exact route Save required")
    for key in ("save_attempted", "native_call_attempted", "native_call_returned", "mutation_attempted",
                "model_saved", "save_readback_verified", "readback_verified", "working_progress_saved"):
        require(data.get(key) is True, "Incomplete Save flag: " + key)
    for key in ("save_pending", "reopen_persistence_verified", "assignment_attempted", "GTP_attempted",
        "GOP_attempted", "AFR_attempted", "tool_edit_attempted", "simulation_attempted", "CL_export_attempted",
        "close_attempted", "automatic_retry", "automatic_replay", "automatic_rollback", "post_cleanup_CAM_getters",
        "full_geometry_rechecked", "full_context_rechecked", "production_qualified", "physical_units_verified",
        "actual_poses_verified", "may_simulate", "may_continue"):
        require(data.get(key) is False, "Unexpected Save flag: " + key)
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error")), "Failed Save cannot anchor WIP")
    require(data.get("native_return_type") == "int" and type(data.get("native_return_value")) is int
        and data["native_return_value"] == 0 and type(data.get("capture_count")) is int
        and data["capture_count"] == 2, "Strict successful Save and two captures required")
    require(type(data.get("process_id")) is int and data["process_id"] == args["process_id"]
        and type(data.get("candidate_id")) is int and data["candidate_id"] == args["expected_candidate_tool_native_id"],
        "Save process or candidate differs")
    for key in TARGET_KEYS:
        require(type(data.get(key)) is int and data[key] == args[key], "Save target differs: " + key)
    same_path(data["expected_document_path"], args["expected_document_path"])
    clean_events(data)
    state = data["after_context"]
    require(data["saved_file_sha256"] == data["source_after_sha256"] == args["expected_source_sha256"]
        == state["saved_file_sha256"] == _file_hash(args["expected_document_path"]), "Current post-Save source differs")
    require(state["document"]["needs_save"] is False and data["continuation_state"] == state
        and data["state_sha256"] == _digest(state) and data["after_document"] == data["after_cleanup_document"] == state["document"],
        "Exact clean saved continuation required")
    payload = data["after"]
    require(data["before"] == payload == stable_save_payload(state, data["before_context"],
        payload["candidate"], payload["levels"], payload["entry"], saved=True), "Save changed protected payload")
    route_scope(state, args)
    gtp, gtp_pin = read_pin(data["gtp_pin"]["path"], data["gtp_pin"]["sha256"])
    require(gtp_pin == data["gtp_pin"] and gtp.get("scope") == "MILL_ASSIGNED_SANDVIK_INITIAL_GTP_V1"
        and gtp.get("status") == "review_required" and gtp.get("phase") == "finished"
        and gtp.get("readback_verified") is True and gtp.get("protected_operations_verified") is True
        and gtp.get("GTP_returned") is True and gtp.get("native_dispatch_pending") is False
        and type(gtp.get("GTP_call_count")) is int and gtp["GTP_call_count"] == 1
        and gtp.get("native_return_type") == "int" and type(gtp.get("native_return_value")) is int
        and gtp["native_return_value"] == 0 and not any(k in gtp for k in ("issue", "failed_phase", "receipt_write_error")),
        "Exact completed original GTP required")
    require(gtp["after"] == data["before_context"] and gtp["source_sha256"] == data["source_before_sha256"]
        and gtp["assignment_pin"] == data["assignment_pin"] and gtp["saved_draft_pin"] == data["saved_draft_pin"]
        and gtp["after_candidate"] == payload["candidate"] and gtp["after_levels"] == payload["levels"]
        and gtp["after_entry_parameters"] == payload["entry"], "Saved GTP lineage differs")
    clean_events(gtp)
    require(type(gtp.get("process_id")) is int and gtp["process_id"] == args["process_id"]
        and type(gtp.get("candidate_id")) is int and gtp["candidate_id"] == args["expected_candidate_tool_native_id"]
        and all(type(gtp.get(k)) is int and gtp[k] == args[k] for k in TARGET_KEYS), "GTP process/targets differ")
    same_path(gtp["expected_document_path"], args["expected_document_path"])
    marker = completed_gtp_save_marker(args["expected_document_path"], data["source_before_sha256"],
        gtp_pin["sha256"], args["target_operation_native_id"], args["expected_candidate_tool_native_id"])
    same_path(data["save_marker_path"], marker)
    marker_data, marker_pin = read_pin(str(marker), _file_hash(marker))
    expected_marker = dict(scope=SAVE_SCOPE, status="review_required", phase="finished",
        document=data["expected_document_path"], source_before_sha256=data["source_before_sha256"],
        gtp_pin=gtp_pin, operation_id=args["target_operation_native_id"], candidate_id=args["expected_candidate_tool_native_id"],
        receipt_path=path, save_pending=False, native_call_attempted=True, native_call_returned=True,
        saved_file_sha256=args["expected_source_sha256"], readback_verified=True, automatic_replay=False)
    for key in ("document", "receipt_path"):
        same_path(marker_data[key], expected_marker[key]); expected_marker[key] = marker_data[key]
    require(marker_data == expected_marker, "Exact completed Save marker required")
    draft, draft_pin = read_pin(data["saved_draft_pin"]["path"], data["saved_draft_pin"]["sha256"])
    require(draft_pin == data["saved_draft_pin"] and draft.get("status") == "review_required"
        and draft.get("phase") == "finished" and draft.get("model_saved") is True
        and draft.get("save_readback_verified") is True and draft.get("readback_verified") is True
        and draft.get("save_pending") is False and draft["before"] == draft["after"]
        and draft["after_context"]["document"]["needs_save"] is False
        and draft["after_context"]["saved_file_sha256"] == draft["saved_file_sha256"]
        and not any(k in draft for k in ("issue", "failed_phase", "receipt_write_error")), "Historical saved draft differs")
    clean_events(draft)
    ownership, ownership_pin = load_owned_startup(owned_startup_receipt_path, owned_startup_receipt_sha256, args["process_id"])
    qualification = None
    require(read_mode in ("strong", "qualified_batch"), "Explicit supported read mode required")
    if read_mode == "qualified_batch":
        require(type(batch_qualification_receipt_path) is str and type(batch_qualification_receipt_sha256) is str,
            "Original qualification pin required")
        qualification = load_route_batch_qualification(batch_qualification_receipt_path, batch_qualification_receipt_sha256,
            saved=dict(pin=draft_pin, state=draft["after_context"], payload=draft["after"]),
            expected_source_sha256=draft["saved_file_sha256"], caller_path=__file__,
            **{k:args[k] for k in ("process_id", "expected_document_path", *TARGET_KEYS, "expected_candidate_tool_native_id")})
    else:
        require(batch_qualification_receipt_path is None and batch_qualification_receipt_sha256 is None, "Unused batch pin")
    pins = canonical_evidence_pins(data["evidence_pins"], [pin, marker_pin, gtp_pin, draft_pin, ownership_pin],
        qualification["pins"] if qualification else [], [dict(path=str(Path(__file__).resolve()), sha256=_file_hash(__file__))])
    keys = {(str(Path(p["path"]).resolve()).casefold(), p["sha256"]) for p in pins}
    for required in (data["assignment_pin"], draft["observation_pin"]):
        require((str(Path(required["path"]).resolve()).casefold(), required["sha256"]) in keys, "Missing saved lineage pin")
    for evidence in pins:
        require(_file_hash(evidence["path"]) == evidence["sha256"], "Post-Save immutable evidence changed")
    return dict(data=data, pin=pin, state=deepcopy(state), payload=deepcopy(payload), pins=pins,
        observation_pin=draft["observation_pin"], ownership=ownership, qualification=qualification, read_mode=read_mode)



def wip_marker(source, source_sha, operation_id, candidate_id):
    path = Path(source).resolve()
    key = _digest(dict(scope=SCOPE, source=str(path).casefold(), source_sha256=source_sha,
        operation_id=operation_id, candidate_id=candidate_id))
    return path.parent / ("completed_gtp_wip_" + key + ".json")

def output_plan(output_dir, project_root, receipt_path, source, pins, marker):
    directory, root, receipt = Path(output_dir), Path(project_root), Path(receipt_path)
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(), "Existing explicit project root required")
    require(directory.is_absolute() and bool(re.fullmatch(r"[A-Za-z]:", directory.drive))
        and ".." not in directory.parts and not directory.exists() and not directory.is_symlink()
        and directory.parent.is_dir(), "Fresh drive-letter WIP directory required")
    canonical_root, canonical = root.resolve(), directory.resolve()
    require(canonical.is_relative_to(canonical_root) and canonical != canonical_root, "WIP output escapes project root")
    require(receipt.is_absolute() and receipt.suffix.casefold() == ".json" and receipt.parent.is_dir()
        and not receipt.exists() and not receipt.is_symlink() and receipt.resolve().is_relative_to(canonical_root)
        and not receipt.resolve().is_relative_to(canonical), "Fresh separate project receipt required")
    protected = {str(Path(p["path"]).resolve()).casefold() for p in pins}
    protected.add(str(Path(source).resolve()).casefold())
    outputs = [str(p.resolve()).casefold() for p in (directory, receipt, marker)]
    require(len(set(outputs)) == 3 and not protected.intersection(outputs), "Output aliases source/evidence")
    require(not marker.exists() and not marker.is_symlink(), "Prior WIP attempt exists; no replay")
    return directory, canonical

def collect_wip_files(directory, canonical):
    require(not directory.is_symlink() and directory.resolve(strict=True) == canonical, "WIP directory changed")
    rows = []; total = 0
    for count, path in enumerate(sorted(directory.rglob("*"), key=str), 1):
        require(count <= 1024 and not path.is_symlink() and path.resolve(strict=True).is_relative_to(canonical),
            "WIP output tree exceeds boundary")
        if path.is_file():
            size = path.stat().st_size; total += size
            require(len(rows) < 512 and size <= 128*1024*1024 and total <= 512*1024*1024, "WIP byte bound exceeded")
            row = dict(path=str(path), native_path=str(path), canonical_path=str(path.resolve(strict=True)),
                bytes=size, sha256=_file_hash(path), content_reviewed=False,
                stl_extension=path.suffix.casefold() == ".stl")
            require(path.stat().st_size == size, "WIP file changed during hashing")
            rows.append(row)
    return rows

class SavedRouteWipContext:
    def __init__(self, loaded, args, sw, typelib_path, app, events):
        self.loaded, self.args, self.sw, self.typelib_path, self.app, self.events = loaded, args, sw, typelib_path, app, events
    def files(self):
        for pin in self.loaded["pins"]:
            require(_file_hash(pin["path"]) == pin["sha256"], "Pinned WIP evidence changed")
    def owned(self):
        current = _process_identity(self.args["process_id"]); expected = self.loaded["ownership"]
        require(type(current.get("process_id")) is int and current["process_id"] == self.args["process_id"]
            and current.get("alive") is True and current.get("create_time") == expected["create_time"]
            and _same_path(current.get("executable", ""), expected["executable"]), "Owned process exited or PID was reused")
    def identity(self):
        pid = _member(self.sw, "GetProcessID")
        require(type(pid) is int and pid == self.args["process_id"], "Owned process changed")
        self.owned(); doc = raw_part_identity(self.sw)
        require(doc == self.loaded["state"]["document"] and doc["needs_save"] is False
            and _file_hash(self.args["expected_document_path"]) == self.args["expected_source_sha256"], "Exact saved document changed")
        return doc
    def guard(self):
        return ScopedCamDispatchGuard(self.sw, self.typelib_path, process_id=self.args["process_id"],
            expected_document=self.identity(), source_sha256=self.args["expected_source_sha256"], evidence_pins=self.loaded["pins"],
            verify_evidence=self.files, verify_owned_process=self.owned, check_events=self.events)
    def capture(self, diagnostic):
        self.events(); self.identity(); reference = self.loaded["state"]; payload = self.loaded["payload"]
        common = dict(reference_state=reference, current_document=reference["document"],
            source_sha256=self.args["expected_source_sha256"], target_feature_native_id=self.args["target_feature_native_id"],
            target_operation_native_id=self.args["target_operation_native_id"], diagnostic=diagnostic)
        if self.loaded["read_mode"] == "qualified_batch":
            def batch_factory(native, ref):
                return ScopedCamRouteReadBatch(self.sw, self.typelib_path, native_context=native, reference_state=ref,
                    process_id=self.args["process_id"], expected_document=reference["document"],
                    source_sha256=self.args["expected_source_sha256"], evidence_pins=self.loaded["pins"],
                    verify_evidence=self.files, verify_owned_process=self.owned, check_events=self.events, max_native_calls=900)
            state, native, levels, firstcut, entry, candidate = capture_route_batch(self.app, self.sw,
                strong_guard_factory=self.guard, batch_factory=batch_factory, check_events=self.events,
                expected_candidate_tool_native_id=self.args["expected_candidate_tool_native_id"],
                reference_candidate=payload["candidate"], observation_pin=self.loaded["observation_pin"], **common)
            diagnostic.update(read_mode="qualified_batch_after_completed_save", original_qualification_rebound=False,
                original_qualification_pin=self.loaded["qualification"]["pin"], completed_save_pin=self.loaded["pin"])
        else:
            with self.guard() as guard:
                state, native, levels, firstcut, entry = capture_assignment_snapshot(self.app,
                    read=guard.read, typed=guard.typed, boundary=self.events, **common)
                candidate = read_assignment_candidate(native, self.app, self.sw, read=guard.read, typed=guard.typed,
                    expected_candidate_tool_native_id=self.args["expected_candidate_tool_native_id"],
                    reference=payload["candidate"], observation_pin=self.loaded["observation_pin"], firstcut=firstcut,
                    diagnostic=diagnostic.setdefault("candidate", {}))
            diagnostic["strong_guard"] = guard.summary()
        with self.guard() as count_guard:
            counts = read_feature_counts(native, count_guard.read, count_guard.typed)
        require(counts == [dict(native_id=r["native_id"], feature_count=r["feature_count"]) for r in reference["feature_setups"]],
            "Feature/setup counts changed")
        require(state == reference and candidate == payload["candidate"] and levels == payload["levels"]
            and entry == payload["entry"], "Saved route/tool/settings changed")
        route_scope(state, self.args); self.events(); self.identity()
        diagnostic.update(capture_complete=True, fresh_feature_counts=counts, geometry_reference_pin=self.loaded["pin"],
            full_geometry_rechecked=False)
        return state, native

def run_one_wip_export(report, *, capture, guard_factory, persist, claim, invoke, collect):
    """One existing-path export; a failed native return permits no CAM readback."""
    report["phase"] = "before_capture"; persist()
    before, native = capture("before"); report["before"] = before; persist()
    with guard_factory() as guard:
        machine = guard.typed(native["machine"], "ICWMachine5")
        def pending():
            report.update(phase="CreateSTLOfWIPs2", native_dispatch_pending=True, mutation_attempted=True)
            claim(); persist()
        def call():
            report["native_call_attempted"] = True; report["native_call_count"] += 1; persist()
            return invoke(machine)
        result = guard.dispatch_once(call, persist_pending=pending)
    report.update(native_call_returned=True, native_dispatch_pending=False, native_return_type=type(result).__name__,
        native_return_value=result if type(result) in (bool, int, float, str) or result is None else None,
        dispatch_guard=guard.summary(), phase="export_returned")
    persist()
    report["files"] = collect(); persist()
    require(type(result) is bool and result is True, "Native WIP export must return strict True; no replay")
    require(report["files"] and all(r["stl_extension"] and r["bytes"] > 0 for r in report["files"]), "Nonempty STL-only output required")
    report["phase"] = "after_capture"; persist()
    after, _ = capture("after"); report["after"] = after
    require(after == before, "WIP export changed the protected route")
    require(collect() == report["files"], "WIP files changed during readback")
    report.update(readback_verified=True, export_files_verified=True); persist()

def export_completed_gtp_wip(sw, clsid, typelib_path, *, saved_gtp_receipt_path, saved_gtp_receipt_sha256,
        owned_startup_receipt_path, owned_startup_receipt_sha256, project_root, output_dir, acknowledge_machine_scope,
        read_mode="strong", batch_qualification_receipt_path=None, batch_qualification_receipt_sha256=None, **args):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight", process_id=args.get("process_id"),
        expected_document_path=args.get("expected_document_path"), source_sha256=args.get("expected_source_sha256"),
        mutation_attempted=False, native_dispatch_pending=False, native_call_attempted=False, native_call_returned=False,
        native_call_count=0, readback_verified=False, export_files_verified=False, files=[], capture_diagnostics=[],
        GTP_attempted=False, simulation_attempted=False, model_saved=False, NC_export_attempted=False,
        automatic_retry=False, automatic_replay=False, post_cleanup_CAM_getters=False, production_qualified=False,
        physical_units_verified=False, frame_verified=False, material_removal_verified=False, may_continue=False,
        native_scope="all_wip_parts_all_setups", single_operation_scope_claimed=False, read_mode=read_mode,
        full_route_snapshot_qualified=False, full_geometry_rechecked=False)
    started = monotonic(); created = claimed = False; session = context = marker = loaded = None
    def marker_state():
        return dict(scope=SCOPE, saved_gtp_pin=loaded["pin"], source_sha256=args["expected_source_sha256"],
            status=report["status"], phase=report["phase"], receipt_path=args["receipt_path"], output_dir=output_dir,
            native_call_attempted=report["native_call_attempted"], native_call_returned=report["native_call_returned"],
            native_dispatch_pending=report["native_dispatch_pending"], readback_verified=report["readback_verified"], automatic_replay=False)
    def persist():
        report["elapsed_seconds"] = monotonic() - started
        if created:
            if claimed: _write_receipt(marker, marker_state())
            _write_receipt(args["receipt_path"], report)
    def events(active=True):
        value = session.summary(); report["messages"] = value
        require(value.get("subscribed") is True and value.get("active") is active
            and (active or value.get("disconnected") is True) and not any(value.get(k) for k in
            ("event_count", "overflow", "callback_errors", "callback_error_count", "subscription_error", "disconnect_errors")),
            "CAM event/transport requires stop")
    def claim():
        nonlocal claimed
        require(directory.resolve(strict=True) == canonical and not any(directory.iterdir()), "Output changed before WIP dispatch")
        _write_receipt(marker, marker_state(), create=True); claimed = True
    def capture(label):
        diagnostic = dict(phase=label); report["capture_diagnostics"].append(diagnostic); persist()
        require(len(report["capture_diagnostics"]) <= 2, "Only before/after capture permitted")
        return context.capture(diagnostic)
    try:
        validate_inventory_request(**{k:args[k] for k in ("process_id", "expected_document_path", "expected_source_sha256",
            "qualification_only", "acknowledge_disposable_copy", "receipt_path", "message_policy")})
        require(acknowledge_machine_scope is True, "Explicit all-setups WIP scope required")
        loaded = load_completed_route_save(saved_gtp_receipt_path, saved_gtp_receipt_sha256,
            owned_startup_receipt_path=owned_startup_receipt_path, owned_startup_receipt_sha256=owned_startup_receipt_sha256,
            read_mode=read_mode, batch_qualification_receipt_path=batch_qualification_receipt_path,
            batch_qualification_receipt_sha256=batch_qualification_receipt_sha256, **args)
        marker = wip_marker(args["expected_document_path"], args["expected_source_sha256"],
            args["target_operation_native_id"], args["expected_candidate_tool_native_id"])
        directory, canonical = output_plan(output_dir, project_root, args["receipt_path"], args["expected_document_path"], loaded["pins"], marker)
        report.update(saved_gtp_pin=loaded["pin"], evidence_pins=loaded["pins"], marker_path=str(marker), output_dir=output_dir,
            canonical_output_dir=str(canonical), expected_toolpath_record_counts=args["expected_toolpath_record_counts"],
            target_operation_native_id=args["target_operation_native_id"], target_feature_native_id=args["target_feature_native_id"],
            target_operation_setup_native_id=args["target_operation_setup_native_id"], candidate_id=args["expected_candidate_tool_native_id"],
            native_method="CreateSTLOfWIPs2", native_parameters=[str(directory)+"\\", "wip.stl", "", 0, 0],
            snapshot_scope="Six fresh operation rows and target settings; nineteen-feature geometry reused from completed Save")
        _write_receipt(args["receipt_path"], report, create=True); created = True
        context = SavedRouteWipContext(loaded, args, sw, typelib_path, None, lambda: None)
        context.files(); context.identity()
        app = _bootstrap(sw, clsid, typelib_path, args["expected_document_path"]); context.identity()
        session = CamMessageSession(app, typelib_path)
        context.app, context.events = app, events
        with session:
            events(); directory.mkdir()
            require(directory.resolve(strict=True) == canonical, "Output directory identity changed")
            run_one_wip_export(report, capture=capture, guard_factory=context.guard, persist=persist, claim=claim,
                invoke=lambda machine: _member(machine, "CreateSTLOfWIPs2", *report["native_parameters"]),
                collect=lambda: collect_wip_files(directory, canonical))
            events(); report["after_document"] = context.identity()
        events(active=False); context.files(); report["after_cleanup_document"] = context.identity()
        require(report["after_cleanup_document"] == report["after_document"] == loaded["state"]["document"], "Cleanup document changed")
        require(collect_wip_files(directory, canonical) == report["files"], "Output changed during cleanup")
        report.update(status="review_required", phase="finished", reason="SOFTWARE_WIP_REQUIRES_FRAME_UNITS_AND_REMOVAL_REVIEW")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error", failed_phase=report["phase"],
            phase="finished", issue=_error(exc), readback_verified=False, export_files_verified=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc:
            report.update(status="uncertain", receipt_write_error=_error(exc), readback_verified=False, export_files_verified=False)
    return report

