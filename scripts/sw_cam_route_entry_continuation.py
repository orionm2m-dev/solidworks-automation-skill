"""Explicit GTP, generic CL and working Save from a completed rough-entry edit."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require, read_firstcut_settings
from scripts.sw_cam_route_checkpoint import (RouteCheckpointContext, capture_route_checkpoint,
    snapshot_payload, load_completed_entry_checkpoint)
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_route_entry_evidence import (SCOPES, IDS, selected, verify_gtp_delta,
    verify_save_delta, continuation_marker, marker_state, make_checkpoint, load_continuation_checkpoint)
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_generated_plan_cl import validate_project_output


def _implementation_pins():
    root = Path(__file__).resolve().parent
    return [dict(path=str(root/name), sha256=_file_hash(root/name)) for name in
        ("sw_cam_route_entry_evidence.py", "sw_cam_route_entry_continuation.py")]


def _load(path, sha, action, args):
    if action == "entry":
        loaded = load_completed_entry_checkpoint(path, sha, **args)
    else:
        loaded = load_continuation_checkpoint(path, sha, action=action, **args)
    result = dict(loaded)
    result["implementation_pins"] = _implementation_pins()
    result["pins"] = canonical_evidence_pins(loaded["pins"], result["implementation_pins"])
    return result


def _report(action, loaded, parent_action, args):
    marker = continuation_marker(args["expected_document_path"], action, loaded["pin"], args["target_operation_native_id"])
    return dict(schema_version=1, scope=SCOPES[action], action=action, status="error", phase="preflight",
        **{k:args[k] for k in IDS}, process_id=args["process_id"], expected_document_path=args["expected_document_path"],
        source_before_sha256=args["expected_source_sha256"], source_after_sha256=args["expected_source_sha256"],
        receipt_path=args["receipt_path"], parent_checkpoint_pin=deepcopy(loaded["pin"]), parent_action=parent_action,
        marker_path=str(marker), evidence_pins=deepcopy(loaded["pins"]),
        implementation_pins=deepcopy(loaded.get("implementation_pins") or _implementation_pins()), native_dispatch_pending=False,
        native_call_attempted=False, native_call_returned=False, mutation_attempted=False, GTP_attempted=False,
        GOP_attempted=False, AFR_attempted=False, assignment_attempted=False, tool_edit_attempted=False,
        simulation_attempted=False, NC_export_attempted=False,
        GTP_call_count=0, GTP_returned=False, save_attempted=False, save_pending=False, model_saved=False,
        readback_verified=False, save_readback_verified=False, full_geometry_rechecked=False,
        automatic_retry=False, automatic_replay=False, automatic_rollback=False, reopen_persistence_verified=False,
        production_qualified=False, actual_poses_verified=False, physical_units_verified=False, may_continue=False,
        snapshot_diagnostics=[], before_context=deepcopy(loaded["state"]), before_payload=deepcopy(loaded["payload"]),
        geometry_provenance=dict(reference_pin=deepcopy(loaded["pin"]), full_geometry_rechecked=False))


def _preflight(loaded, report, args):
    require(args.get("qualification_only") is True and args.get("acknowledge_disposable_copy") is True
            and args.get("software_only_experiment") is True and args.get("message_policy", "vendor_default") == "vendor_default",
            "Explicit software-only disposable qualification required")
    selected(loaded["state"], args)
    marker, receipt = Path(report["marker_path"]), Path(args["receipt_path"])
    require(not marker.exists() and not marker.is_symlink(), "Prior action attempt exists; no replay")
    require(receipt.is_absolute() and receipt.suffix.lower() == ".json" and receipt.parent.is_dir()
            and not receipt.exists() and not receipt.is_symlink(), "Fresh absolute JSON receipt required")
    blocked = {str(Path(p["path"]).resolve()).casefold() for p in loaded["pins"]}
    targets = [str(Path(p).resolve()).casefold() for p in (args["expected_document_path"], receipt, marker)]
    require(len(set(targets)) == 3 and not blocked.intersection(targets), "Source/output/evidence overlap")


def _finished(report, state, payload):
    checkpoint = make_checkpoint(state, payload)
    report.update(status="review_required", phase="finished", readback_verified=True,
        after_context=deepcopy(state), after_payload=deepcopy(payload), checkpoint=checkpoint,
        checkpoint_sha256=_digest(checkpoint), source_after_sha256=state["saved_file_sha256"])


def _events(session, report, active=True):
    value = session.summary(); report["messages"] = value
    require(value.get("subscribed") is True and value.get("active") is active
        and (active or value.get("disconnected") is True)
        and not any(value.get(k) for k in ("event_count", "overflow", "callback_errors",
            "callback_error_count", "subscription_error", "disconnect_errors")), "CAM event/transport requires stop")


def _native_action(action, sw, clsid, typelib_path, *, checkpoint_receipt_path,
        checkpoint_receipt_sha256, checkpoint_action, **args):
    from scripts.sw_cam_events import CamMessageSession
    require((action == "gtp" and checkpoint_action == "entry") or
            (action == "save" and checkpoint_action in {"gtp", "cl"}), "Explicit action lineage required")
    loaded = _load(checkpoint_receipt_path, checkpoint_receipt_sha256, checkpoint_action, args)
    report = _report(action, loaded, checkpoint_action, args); _preflight(loaded, report, args)
    created = claimed = False; session = ctx = save_app = None; started = monotonic()
    state_after = payload_after = None
    def persist():
        report["elapsed_seconds"] = monotonic() - started
        if created:
            if claimed: _write_receipt(report["marker_path"], marker_state(report))
            _write_receipt(args["receipt_path"], report)
    def claim():
        nonlocal claimed
        _write_receipt(report["marker_path"], marker_state(report), create=True); claimed = True
    def events(): _events(session, report)
    def boundary(): ctx.files(); events(); ctx.identity()
    def capture(label):
        nonlocal state_after, payload_after, save_app
        boundary(); report["phase"] = label + "_capture"
        diag = dict(phase=label); report["snapshot_diagnostics"].append(diag); persist()
        result = capture_route_checkpoint(ctx, loaded["state"], diag)
        state, native, levels, firstcut, entry, candidate = result
        payload = dict(candidate=candidate, levels=levels, entry=entry)
        require(payload == loaded["payload"], "Protected candidate/levels/entry changed")
        if label == "before": require(state == loaded["state"], "Current checkpoint changed")
        elif action == "gtp": verify_gtp_delta(loaded["state"], state, args)
        else: verify_save_delta(loaded["state"], state, args, report["saved_file_sha256"])
        report[label + "_context"] = deepcopy(state); report[label + "_payload"] = deepcopy(payload)
        state_after, payload_after = state, payload
        if action == "save":
            with ctx.guard() as guard: save_app = guard.typed(ctx.app, "ICWApp")
            normalized = deepcopy(state)
            normalized["document"]["needs_save"] = loaded["state"]["document"]["needs_save"]
            normalized["saved_file_sha256"] = loaded["state"]["saved_file_sha256"]
            return dict(context=normalized, **deepcopy(payload))
        return native
    def saved_hash():
        # Called by the unchanged Save engine only after strict integer S_OK.
        require(report.get("native_call_returned") is True and report.get("save_pending") is False
                and report.get("native_return_type") == "int" and type(report.get("native_return_value")) is int
                and report["native_return_value"] == 0, "No source transition before strict Save return")
        from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
        events(); ctx.files(); ctx.owned()
        doc = raw_part_identity(sw); expected = deepcopy(ctx.expected_document); expected["needs_save"] = False
        require(doc == expected, "Save must leave exact clean document")
        new_sha = _file_hash(args["expected_document_path"])
        ctx.args = dict(ctx.args, expected_source_sha256=new_sha); ctx.expected_document = deepcopy(doc)
        ctx.allow_dirty_transition = False
        report["source_transition"] = dict(source_before_sha256=args["expected_source_sha256"],
            source_after_sha256=new_sha, strict_native_save_return=0, clean_document=deepcopy(doc))
        ctx.identity(); return new_sha
    try:
        _write_receipt(args["receipt_path"], report, create=True); created = True
        ctx = RouteCheckpointContext(loaded, dict(args), sw, typelib_path, None, events)
        require(ctx.identity() == loaded["state"]["document"], "Exact current document required")
        app = _bootstrap(sw, clsid, typelib_path, args["expected_document_path"]); ctx.app = app
        require(ctx.identity() == loaded["state"]["document"], "Document changed acquiring CAM host")
        session = CamMessageSession(app, typelib_path)
        with session:
            if action == "gtp":
                native = capture("before")
                with ctx.guard() as guard:
                    op_id = args["target_operation_native_id"]; raw = native["operations"][op_id]
                    require(_object_id(native["doc"], raw, guard.read) == op_id, "Target operation changed")
                    summary, _ = read_generic_tool(raw, native["doc"], guard.read, guard.typed)
                    require(summary == selected(report["before_context"], args)["assigned_tool"], "Assigned tool changed")
                    require(read_firstcut_settings(raw, guard.read, guard.typed) == loaded["payload"]["candidate"]["firstcut"], "Firstcut changed")
                    op = guard.typed(raw, "ICWMillOperation")
                    def pending():
                        report.update(phase="GenerateToolpath", native_dispatch_pending=True,
                            native_call_attempted=True, mutation_attempted=True, GTP_attempted=True, GTP_call_count=1)
                        claim(); persist()
                    returned = guard.dispatch_once(lambda:_member(op, "GenerateToolpath"), persist_pending=pending)
                    report.update(native_call_returned=True, GTP_returned=True, native_dispatch_pending=False,
                        native_return_type=type(returned).__name__, native_return_value=returned if type(returned) in (int,bool,float,str,type(None)) else None)
                    persist()
                report["dispatch_guard"] = guard.summary()
                require(type(returned) is int and returned == 0, "Strict successful GenerateToolpath HRESULT required")
                ctx.allow_dirty_transition = True
                capture("after")
            else:
                selected(loaded["state"], args, generated=True)
                expected = dict(context=deepcopy(loaded["state"]), **deepcopy(loaded["payload"]))
                def verify(value): require(value == expected, "Protected Save payload changed")
                def native_save(): boundary(); return _member(save_app, "SaveActiveDocument")
                run_one_existing_save(report, capture=capture, verify=verify, guard=boundary, claim=claim,
                    persist=persist, save=native_save, saved_hash=saved_hash)
        _events(session, report, False); ctx.files()
        report["after_cleanup_document"] = ctx.identity()
        require(report["after_cleanup_document"] == state_after["document"], "Cleanup document changed")
        if action == "save": report["model_saved"] = True
        _finished(report, state_after, payload_after)
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error", failed_phase=report["phase"],
            phase="finished", issue=_error(exc), readback_verified=False, model_saved=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc: report.update(status="uncertain", receipt_write_error=_error(exc), readback_verified=False)
    return report


def generate_route_after_entry(sw, clsid, typelib_path, **args):
    return _native_action("gtp", sw, clsid, typelib_path, checkpoint_action="entry", **args)


def save_route_after_entry(sw, clsid, typelib_path, *, checkpoint_action, **args):
    return _native_action("save", sw, clsid, typelib_path, checkpoint_action=checkpoint_action, **args)


class RouteEntryCLContext:
    """Adapter only: the existing SaveCLFile core and three captures are unchanged."""
    def __init__(self, loaded, args, project_root, sw, typelib_path):
        self.loaded, self.args, self.project_root = loaded, args, project_root
        self.report = _report("cl", loaded, "gtp", args); self.claimed = False
        self.ctx = RouteCheckpointContext(loaded, dict(args), sw, typelib_path, None, lambda:None)
    def report_fields(self): return deepcopy(self.report)
    def identity(self, sw): return self.ctx.identity()
    def validate(self, **request):
        _preflight(self.loaded, self.report, self.args)
        require(request["action"] == "apply" and request["acknowledge_machine_scope"] is True, "Explicit machine export required")
        selected(self.loaded["state"], self.args, generated=True)
        validate_project_output(request["output_path"], self.project_root, request["receipt_path"],
            self.args["expected_document_path"], self.loaded["pins"])
    def selected(self, state, feature_id, operation_id, operation_type): return selected(state, self.args, generated=True)
    def verify_before(self, snapshot): require(snapshot["mill_state"] == self.loaded["state"], "Current GTP checkpoint changed")
    def capture(self, sw, clsid, typelib_path, app, check, diagnostic):
        self.ctx.app, self.ctx.events = app, check
        result = capture_route_checkpoint(self.ctx, self.loaded["state"], diagnostic)
        snap = snapshot_payload(result)
        require(snap == dict(context=self.loaded["state"], **self.loaded["payload"]), "CL capture changed route/settings")
        return result[0], result[1]
    def claim(self, report):
        self.ctx.files(); _write_receipt(self.report["marker_path"], marker_state(report), create=True); self.claimed = True
    def persist(self, report):
        if self.claimed: _write_receipt(self.report["marker_path"], marker_state(report))


def export_route_after_entry_cl(sw, clsid, typelib_path, *, checkpoint_receipt_path,
        checkpoint_receipt_sha256, project_root, output_path, acknowledge_machine_scope, **args):
    from scripts.sw_cam_mill_generic_cl import export_mill_generic_cl
    loaded = _load(checkpoint_receipt_path, checkpoint_receipt_sha256, "gtp", args)
    context = RouteEntryCLContext(loaded, args, project_root, sw, typelib_path)
    row = selected(loaded["state"], args, generated=True)
    report = export_mill_generic_cl(sw, clsid, typelib_path,
        **{k:args[k] for k in ("process_id", "expected_document_path", "expected_source_sha256",
            "qualification_only", "acknowledge_disposable_copy", "message_policy", "receipt_path")},
        expected_feature_native_id=args["target_feature_native_id"], expected_operation_native_id=args["target_operation_native_id"],
        expected_mill_operation_type=0, expected_toolpath_record_counts=row["toolpath_record_counts"],
        expected_ungenerated_operation_ids=[r["native_id"] for r in loaded["state"]["operations"] if r is not row],
        action="apply", acknowledge_machine_scope=acknowledge_machine_scope, output_path=output_path, _context_adapter=context)
    if report.get("phase") == "finished" and report.get("readback_verified") is True and report.get("output_verified") is True:
        try:
            report["after_cleanup_document"] = context.ctx.identity()
            _finished(report, loaded["state"], loaded["payload"])
            context.persist(report); _write_receipt(args["receipt_path"], report)
        except Exception as exc:
            report.update(status="uncertain", failed_phase="continuation_finalize", issue=_error(exc), readback_verified=False)
            try:
                context.persist(report); _write_receipt(args["receipt_path"], report)
            except Exception as write_exc: report["receipt_write_error"] = _error(write_exc)
    return report
