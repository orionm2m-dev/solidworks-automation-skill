"""Save one completed virtual toolpath using the existing single-save engine."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_completed_sandvik_saved import load_saved_sandvik
from scripts.sw_cam_completed_sandvik_save import read_feature_counts
from scripts.sw_cam_completed_sandvik_assignment import capture_assignment_snapshot, read_assignment_candidate
from scripts.sw_cam_sandvik_gtp_evidence import load_completed_assignment
from scripts.sw_cam_generated_plan_cl import load_completed_gtp
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_operation_guard import check_document_target

SCOPE = "MILL_COMPLETED_GTP_WORKING_SAVE_V1"


def completed_gtp_save_marker(document_path, source_sha256, gtp_sha256, operation_id, candidate_id):
    source = Path(document_path).resolve()
    identity = dict(scope=SCOPE, document=str(source).casefold(), source_sha256=source_sha256,
        gtp_sha256=gtp_sha256, operation_id=operation_id, candidate_id=candidate_id)
    return source.parent / ("completed_gtp_save_" + _digest(identity) + ".json")


def stable_save_payload(state, reference, candidate, levels, entry, *, saved):
    """Only document dirty state and saved SHA may change during this Save."""
    expected = deepcopy(reference)
    if saved:
        require(state["document"].get("needs_save") is False, "Save left document dirty")
        expected["document"]["needs_save"] = False
        expected["saved_file_sha256"] = state["saved_file_sha256"]
    require(state == expected, "Save context differs beyond dirty state and saved source")
    normalized = deepcopy(state)
    normalized["document"]["needs_save"] = reference["document"]["needs_save"]
    normalized["saved_file_sha256"] = reference["saved_file_sha256"]
    return dict(context=normalized, candidate=deepcopy(candidate), levels=deepcopy(levels), entry=deepcopy(entry))


def verify_saved_transition(report, marker_data, expected_marker, *, source_before, source_after,
        expected_process_id, current_document, reference_document):
    """Validate one completed local Save before reusing a qualified read engine."""
    require(type(report.get("process_id")) is int and report["process_id"]==expected_process_id,
        "Save transition PID differs")
    for flag in ("save_attempted", "native_call_attempted", "native_call_returned", "mutation_attempted"):
        require(report.get(flag) is True,"Incomplete native Save transition: "+flag)
    require(report.get("save_pending") is False and report.get("native_return_type")=="int"
        and type(report.get("native_return_value")) is int and report["native_return_value"]==0,
        "Strict completed Save required for source transition")
    require(report.get("source_before_sha256")==source_before
        and report.get("saved_file_sha256")==source_after,"Save transition source differs")
    require(not any(k in report for k in ("issue", "failed_phase", "receipt_write_error")),"Failed Save transition")
    require(current_document.get("needs_save") is False
        and dict(current_document,needs_save=reference_document["needs_save"])==reference_document,
        "Exact clean saved document required for transition")
    require(marker_data==expected_marker,"Claimed post-GTP Save marker differs")
    return dict(source_before_sha256=source_before,source_after_sha256=source_after,
        process_id=expected_process_id,document=deepcopy(current_document),strict_save_hresult=0,
        original_qualification_rebound=False,native_scope="read-only after one completed Save")


def save_completed_gtp(sw, clsid, typelib_path, *, saved_draft_receipt_path,
        saved_draft_receipt_sha256, assignment_receipt_path, assignment_receipt_sha256,
        gtp_receipt_path, gtp_receipt_sha256, expected_candidate_tool_native_id,
        read_mode="strong", batch_qualification_receipt_path=None,
        batch_qualification_receipt_sha256=None, **args):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight",
        process_id=args.get("process_id"), expected_document_path=args.get("expected_document_path"),
        source_before_sha256=args.get("expected_source_sha256"),
        candidate_id=expected_candidate_tool_native_id, mutation_attempted=False,
        save_attempted=False, save_pending=False, native_call_attempted=False, native_call_returned=False,
        model_saved=False, save_readback_verified=False, readback_verified=False,
        reopen_persistence_verified=False, assignment_attempted=False, GTP_attempted=False,
        GOP_attempted=False, AFR_attempted=False, tool_edit_attempted=False, simulation_attempted=False,
        CL_export_attempted=False, close_attempted=False, automatic_retry=False, automatic_replay=False,
        automatic_rollback=False, post_cleanup_CAM_getters=False, full_geometry_rechecked=False,
        full_context_rechecked=False, production_qualified=False, physical_units_verified=False,
        actual_poses_verified=False, may_simulate=False, may_continue=False,
        capture_count=0, capture_diagnostics=[], guard_diagnostics=[], read_mode=read_mode)
    source=args.get("expected_document_path"); receipt=args.get("receipt_path")
    current_sha=args.get("expected_source_sha256"); started=monotonic()
    created=claimed=False; anchor=session=loaded=saved=assigned=marker=save_app=None
    qualification=None; pins=[]; active_transition_pins=[]
    def marker_state():
        return dict(scope=SCOPE,status=report["status"],phase=report["phase"],document=source,
            source_before_sha256=args["expected_source_sha256"],gtp_pin=loaded["pin"],
            operation_id=args["target_operation_native_id"],candidate_id=expected_candidate_tool_native_id,
            receipt_path=receipt,save_pending=report["save_pending"],
            native_call_attempted=report["native_call_attempted"],native_call_returned=report["native_call_returned"],
            saved_file_sha256=report.get("saved_file_sha256"),readback_verified=report["readback_verified"],
            automatic_replay=False)
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:
            if claimed:_write_receipt(marker,marker_state())
            _write_receipt(receipt,report)
    def files():
        anchor.check_files()
        for pin in canonical_evidence_pins(pins,active_transition_pins):require(_file_hash(pin["path"])==pin["sha256"],"Pinned Save evidence changed")
    def identity():
        pid=_member(sw,"GetProcessID")
        require(type(pid) is int and pid==args["process_id"],"Owned process changed")
        anchor.check_runtime_identity();doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=source,required=True)
        require(_file_hash(source)==current_sha,"Current saved source changed")
        baseline=loaded["state"]["document"]
        require(type(doc.get("needs_save")) is bool
            and dict(doc,needs_save=baseline["needs_save"])==baseline,"Current document identity changed")
        return doc
    def events(active=True):
        value=session.summary();report["messages"]=value
        require(value.get("subscribed") is True and value.get("active") is active
            and (active or value.get("disconnected") is True)
            and not any(value.get(k) for k in ("event_count","overflow","callback_errors",
                "callback_error_count","subscription_error","disconnect_errors")),"CAM event or transport requires stop")
    def guard():
        return ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
            expected_document=identity(),source_sha256=current_sha,evidence_pins=canonical_evidence_pins(anchor.pins,pins,active_transition_pins),
            verify_evidence=files,verify_owned_process=anchor.check_runtime_identity,check_events=events)
    def boundary():
        files();events();doc=identity()
        dirty=False if report.get("saved_file_sha256") else loaded["state"]["document"]["needs_save"]
        require(doc["needs_save"] is dirty,"Unexpected Save dirty transition")
    def capture(label):
        nonlocal save_app
        boundary();report["capture_count"]+=1
        require(report["capture_count"]<=2,"Exactly one before/after capture permitted")
        diagnostic=dict(phase=label,geometry_reference_pin=loaded["pin"],fresh_full_snapshot=False)
        report["capture_diagnostics"].append(diagnostic);persist()
        common=dict(reference_state=loaded["state"],current_document=identity(),source_sha256=current_sha,
            target_feature_native_id=args["target_feature_native_id"],
            target_operation_native_id=args["target_operation_native_id"],diagnostic=diagnostic)
        if read_mode=="qualified_batch":
            from scripts.sw_cam_route_batch_qualified_capture import qualified_route_capture
            batch_args=dict(strong_guard_factory=guard,expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                reference_candidate=assigned["candidate_payload"],observation_pin=saved["observation_pin"],**common)
            if label=="before":
                state,native,levels,firstcut,entry,payload=qualified_route_capture(app,sw,typelib_path,
                    qualification=qualification,process_id=args["process_id"],evidence_pins=canonical_evidence_pins(anchor.pins,pins,active_transition_pins),
                    verify_evidence=files,verify_owned_process=anchor.check_runtime_identity,check_events=events,**batch_args)
            else:
                from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch, capture_route_batch
                marker_data,marker_pin=read_pin(str(marker),_file_hash(marker))
                saved_report,report_pin=read_pin(receipt,_file_hash(receipt))
                require(saved_report==report,"Persisted Save report differs before after-capture")
                transition=verify_saved_transition(saved_report,marker_data,marker_state(),
                    source_before=qualification["binding"]["expected_source_sha256"],source_after=current_sha,
                    expected_process_id=args["process_id"],current_document=common["current_document"],
                    reference_document=loaded["state"]["document"])
                active_transition_pins.extend([marker_pin,report_pin])
                transition.update(save_marker_pin=marker_pin,save_report_pin=report_pin,
                    original_qualification_pin=qualification["pin"])
                diagnostic.update(read_mode="qualified_batch_after_completed_save",saved_source_transition=transition)
                def batch_factory(native,reference):
                    return ScopedCamRouteReadBatch(sw,typelib_path,native_context=native,reference_state=reference,
                        process_id=args["process_id"],expected_document=common["current_document"],source_sha256=current_sha,
                        evidence_pins=canonical_evidence_pins(anchor.pins,pins,active_transition_pins),verify_evidence=files,
                        verify_owned_process=anchor.check_runtime_identity,check_events=events,max_native_calls=900)
                try:
                    state,native,levels,firstcut,entry,payload=capture_route_batch(app,sw,
                        batch_factory=batch_factory,check_events=events,**batch_args)
                finally:
                    active_transition_pins.clear()
        else:
            with guard() as current_guard:
                state,native,levels,firstcut,entry=capture_assignment_snapshot(app,
                    read=current_guard.read,typed=current_guard.typed,boundary=boundary,**common)
                payload=read_assignment_candidate(native,app,sw,read=current_guard.read,typed=current_guard.typed,
                    expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                    reference=assigned["candidate_payload"],observation_pin=saved["observation_pin"],
                    firstcut=firstcut,diagnostic=diagnostic.setdefault("candidate",{}))
            report["guard_diagnostics"].append(current_guard.summary())
        with guard() as count_guard:
            counts=read_feature_counts(native,count_guard.read,count_guard.typed)
            save_app=count_guard.typed(app,"ICWApp")
        report["guard_diagnostics"].append(count_guard.summary())
        expected_counts=[dict(native_id=r["native_id"],feature_count=r["feature_count"])
                         for r in loaded["state"]["feature_setups"]]
        require(counts==expected_counts,"Feature/setup counts changed")
        require(payload==assigned["candidate_payload"] and levels==assigned["levels"]
            and entry==assigned["entry"],"Assigned tool, levels or entry settings changed")
        require(state["document"]==identity() and state["saved_file_sha256"]==current_sha,"Snapshot source changed")
        report[label+"_context"]=deepcopy(state)
        diagnostic.update(capture_complete=True,fresh_feature_counts=counts)
        boundary()
        return stable_save_payload(state,loaded["state"],payload,levels,entry,saved=label=="after")
    def verify(payload):
        expected=stable_save_payload(loaded["state"],loaded["state"],assigned["candidate_payload"],
            assigned["levels"],assigned["entry"],saved=False)
        require(payload==expected,"Protected post-GTP payload changed")
    def claim():
        nonlocal claimed
        _write_receipt(marker,marker_state(),create=True);claimed=True
    def native_save():
        boundary();return _member(save_app,"SaveActiveDocument")
    def saved_hash():
        nonlocal current_sha
        events();files();current_sha=_file_hash(source);identity();events();return current_sha
    try:
        require(read_mode in ("strong","qualified_batch"),"Explicit supported read mode required")
        require((read_mode=="qualified_batch") == (batch_qualification_receipt_path is not None
            and batch_qualification_receipt_sha256 is not None),"Batch mode requires exact qualification pin")
        if read_mode=="strong":require(batch_qualification_receipt_path is None
            and batch_qualification_receipt_sha256 is None,"No unused batch pin")
        saved=load_saved_sandvik(saved_draft_receipt_path=saved_draft_receipt_path,
            saved_draft_receipt_sha256=saved_draft_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        assigned=load_completed_assignment(saved,assignment_receipt_path=assignment_receipt_path,
            assignment_receipt_sha256=assignment_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        loaded=load_completed_gtp(assigned,gtp_receipt_path=gtp_receipt_path,gtp_receipt_sha256=gtp_receipt_sha256,**args)
        anchor=saved["anchor"];pins=canonical_evidence_pins(loaded["pins"])
        if read_mode=="qualified_batch":
            from scripts.sw_cam_route_batch_qualified_capture import load_route_batch_qualification
            qualification=load_route_batch_qualification(batch_qualification_receipt_path,batch_qualification_receipt_sha256,
                saved=saved,expected_candidate_tool_native_id=expected_candidate_tool_native_id,caller_path=__file__,
                **{k:args[k] for k in ("process_id","expected_document_path","expected_source_sha256",
                    "target_feature_native_id","target_operation_native_id","target_operation_setup_native_id")})
            pins=canonical_evidence_pins(pins,qualification["pins"])
        marker=completed_gtp_save_marker(source,current_sha,loaded["pin"]["sha256"],
            args["target_operation_native_id"],expected_candidate_tool_native_id)
        require(not marker.exists() and not marker.is_symlink(),"Prior post-GTP Save attempt exists; no replay")
        blocked={str(Path(p["path"]).resolve()).casefold() for p in pins}
        outputs=[str(Path(p).resolve()).casefold() for p in (source,receipt,marker)]
        require(len(set(outputs))==3 and not blocked.intersection(outputs),"Source/output/evidence overlap")
        report.update(gtp_pin=loaded["pin"],assignment_pin=assigned["pin"],saved_draft_pin=saved["pin"],
            evidence_pins=deepcopy(pins),save_marker_path=str(marker),
            target_feature_native_id=args["target_feature_native_id"],target_operation_native_id=args["target_operation_native_id"],
            target_operation_setup_native_id=args["target_operation_setup_native_id"],
            geometry_provenance=dict(reference_pin=loaded["pin"],full_geometry_rechecked=False),
            snapshot_scope="Six fresh operations and target settings; nineteen-feature geometry and profiles reused")
        _write_receipt(receipt,report,create=True);created=True
        require(identity()==loaded["state"]["document"],"Exact completed GTP document required")
        app=_bootstrap(sw,clsid,typelib_path,source)
        require(identity()==loaded["state"]["document"],"Document changed acquiring CAM host")
        session=CamMessageSession(app,typelib_path)
        with session:
            run_one_existing_save(report,capture=capture,verify=verify,guard=boundary,claim=claim,
                persist=persist,save=native_save,saved_hash=saved_hash)
            report["after_document"]=identity();events()
        events(active=False);report["after_cleanup_document"]=identity();files()
        require(report["after_cleanup_document"]==report["after_document"]==report["after_context"]["document"]
            and report["after_document"]["needs_save"] is False,"Final clean saved document required")
        report.update(status="review_required",phase="finished",model_saved=True,readback_verified=True,
            working_progress_saved=True,source_after_sha256=current_sha,
            continuation_state=deepcopy(report["after_context"]),state_sha256=_digest(report["after_context"]),
            reason="WORKING_VIRTUAL_TOOLPATH_SAVED_PHYSICAL_FRAME_AND_MANUFACTURING_REVIEW_REMAIN")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),
            model_saved=False,save_readback_verified=False,readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),
            model_saved=False,save_readback_verified=False,readback_verified=False)
    return report
