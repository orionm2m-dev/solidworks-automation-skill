"""One virtual initial GTP using the completed assignment's scoped readers."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require, read_firstcut_settings
from scripts.sw_cam_completed_sandvik_saved import load_saved_sandvik
from scripts.sw_cam_completed_sandvik_assignment import (
    capture_assignment_snapshot, read_assignment_candidate)
from scripts.sw_cam_sandvik_gtp_evidence import (
    SCOPE, load_completed_assignment, verify_initial_gtp_delta, initial_gtp_marker)
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_operation_guard import check_document_target


from scripts.sw_cam_route_batch_qualified_capture import (
    load_route_batch_qualification, qualified_route_capture, canonical_evidence_pins)


def generate_assigned_sandvik_once(sw, clsid, typelib_path, *,
        saved_draft_receipt_path, saved_draft_receipt_sha256,
        assignment_receipt_path, assignment_receipt_sha256,
        expected_candidate_tool_native_id, experiment_evidence_path,
        experiment_evidence_sha256, software_only_experiment, read_mode="strong",
        read_batch_qualification_receipt_path=None, read_batch_qualification_receipt_sha256=None, **args):
    """No NC, simulation, setters, Save, global generation, retries or regeneration."""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(schema_version=1,scope=SCOPE,status="error",phase="preflight",
        process_id=args.get("process_id"),expected_document_path=args.get("expected_document_path"),
        source_sha256=args.get("expected_source_sha256"),native_dispatch_pending=False,
        GTP_attempted=False,GTP_returned=False,GTP_call_count=0,mutation_attempted=False,
        save_attempted=False,model_saved=False,assignment_attempted=False,tool_edit_attempted=False,
        GOP_attempted=False,AFR_attempted=False,simulation_attempted=False,NC_export_attempted=False,
        CL_records_accessed=False,automatic_retry=False,automatic_replay=False,automatic_rollback=False,
        readback_verified=False,selected_toolpath_verified=False,protected_operations_verified=False,
        full_geometry_rechecked=False,physical_units_verified=False,actual_poses_verified=False,
        production_qualified=False,may_simulate=False,may_continue=False,snapshot_diagnostics=[],
        protection_scope="Fresh six operations and selected settings/candidate bindings; geometry reused from pinned completed observation.")
    source=args.get("expected_document_path"); receipt=args.get("receipt_path")
    op_id=args.get("target_operation_native_id");fid=args.get("target_feature_native_id")
    sid=args.get("target_operation_setup_native_id")
    created=claimed=False;loaded=saved=anchor=session=marker=None;pins=[];started=monotonic();batch_qualification=None
    def marker_state():
        return dict(scope=SCOPE,status=report["status"],phase=report["phase"],
            document=source,source_sha256=args["expected_source_sha256"],
            assignment_pin=dict(path=assignment_receipt_path,sha256=assignment_receipt_sha256),
            operation_id=op_id,candidate_id=expected_candidate_tool_native_id,receipt_path=receipt,
            GTP_call_count=report["GTP_call_count"],GTP_returned=report["GTP_returned"],
            native_dispatch_pending=report["native_dispatch_pending"],
            readback_verified=report["readback_verified"],automatic_replay=False)
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:
            if claimed:_write_receipt(marker,marker_state())
            _write_receipt(receipt,report)
    def files():
        anchor.check_files()
        for p in pins:require(_file_hash(p["path"])==p["sha256"],"Pinned GTP evidence changed")
    def identity():
        pid=_member(sw,"GetProcessID")
        require(type(pid) is int and pid==args["process_id"],"Exact owned process changed")
        anchor.check_runtime_identity();doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=source,required=True)
        require(_file_hash(source)==args["expected_source_sha256"],"Saved source changed")
        return doc
    def events(active=True):
        v=session.summary();report["messages"]=v
        require(v.get("subscribed") is True and v.get("active") is active
            and (active or v.get("disconnected") is True)
            and not any(v.get(k) for k in ("event_count","overflow","callback_errors",
                "callback_error_count","subscription_error","disconnect_errors")),
            "CAM event or transport requires stop")
    def guard():
        return ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
            expected_document=identity(),source_sha256=args["expected_source_sha256"],
            evidence_pins=canonical_evidence_pins(anchor.pins,pins),verify_evidence=files,
            verify_owned_process=anchor.check_runtime_identity,check_events=events)
    def capture(label):
        files();events();report["phase"]=label+"_capture";diag=dict(phase=label)
        report["snapshot_diagnostics"].append(diag);persist()
        if batch_qualification is not None:
            state,native,levels,firstcut,entry,payload=qualified_route_capture(app,sw,typelib_path,
                qualification=batch_qualification,process_id=args["process_id"],current_document=identity(),
                source_sha256=args["expected_source_sha256"],evidence_pins=canonical_evidence_pins(anchor.pins,pins),
                verify_evidence=files,verify_owned_process=anchor.check_runtime_identity,
                check_events=events,strong_guard_factory=guard,reference_state=loaded["state"],
                target_feature_native_id=fid,target_operation_native_id=op_id,
                expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                reference_candidate=loaded["candidate_payload"],observation_pin=saved["observation_pin"],diagnostic=diag)
        else:
            with guard() as g:
                state,native,levels,firstcut,entry=capture_assignment_snapshot(app,
                    read=g.read,typed=g.typed,reference_state=loaded["state"],current_document=identity(),
                    source_sha256=args["expected_source_sha256"],target_feature_native_id=fid,
                    target_operation_native_id=op_id,boundary=lambda:(files(),events(),identity()),diagnostic=diag)
                payload=read_assignment_candidate(native,app,sw,read=g.read,typed=g.typed,
                    expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                    reference=loaded["candidate_payload"],observation_pin=saved["observation_pin"],
                    firstcut=firstcut,diagnostic=diag.setdefault("candidate",{}))
        require(payload==loaded["candidate_payload"] and levels==loaded["levels"]
                and entry==loaded["entry"],"Candidate, levels/setup or raw entry settings changed")
        require(identity()==state["document"],"Capture document changed")
        report[label]=state;report[label+"_candidate"]=payload
        report[label+"_levels"]=levels;report[label+"_entry_parameters"]=entry
        if label=="before":
            require(same_observed_context(loaded["state"],state),"Current state differs from completed assignment")
        else:
            verify_initial_gtp_delta(report["before"],state,operation_id=op_id,
                feature_id=fid,setup_id=sid,candidate_id=expected_candidate_tool_native_id)
        files();events();persist();return native
    try:
        require(software_only_experiment is True,"Explicit software-only initial experiment required")
        saved=load_saved_sandvik(saved_draft_receipt_path=saved_draft_receipt_path,
            saved_draft_receipt_sha256=saved_draft_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        loaded=load_completed_assignment(saved,assignment_receipt_path=assignment_receipt_path,
            assignment_receipt_sha256=assignment_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        anchor=saved["anchor"];pins=loaded["pins"]
        experiment,epin=read_pin(experiment_evidence_path,experiment_evidence_sha256)
        require(experiment.get("status")=="DECLARED_NUMERICAL_TRANSFORM_FOR_ONE_VIRTUAL_GTP_NOT_NATIVE_POSE_PROOF"
            and experiment.get("production_qualified") is False
            and experiment["one_GTP_scope"]["may_generate_for_observation_with_declared_transform"] is True
            and experiment["candidate_transform"]["verified_by_CAM_pose"] is False,
            "Pinned declared numerical experiment required; not a physical clearance proof")
        pins=pins+[epin]
        require(read_mode in ("strong","qualified_batch"),"Explicit supported snapshot read mode required")
        if read_mode=="qualified_batch":
            require(type(read_batch_qualification_receipt_path) is str
                and type(read_batch_qualification_receipt_sha256) is str,"Explicit qualification pin required")
            batch_qualification=load_route_batch_qualification(read_batch_qualification_receipt_path,
                read_batch_qualification_receipt_sha256,saved=saved,process_id=args["process_id"],
                expected_document_path=source,expected_source_sha256=args["expected_source_sha256"],
                target_feature_native_id=fid,target_operation_native_id=op_id,target_operation_setup_native_id=sid,
                expected_candidate_tool_native_id=expected_candidate_tool_native_id,caller_path=__file__)
            pins+=batch_qualification["pins"]
        else:
            require(read_batch_qualification_receipt_path is None and read_batch_qualification_receipt_sha256 is None,
                "Qualification pin is only accepted with qualified_batch read mode")
        report.update(read_mode=read_mode,batch_qualification=deepcopy(batch_qualification),
            full_route_snapshot_qualified=False)
        marker=initial_gtp_marker(source,args["expected_source_sha256"],op_id,
            expected_candidate_tool_native_id,loaded["data"]["candidate_mt_pin"]["sha256"])
        require(not marker.exists() and not marker.is_symlink(),"Prior initial GTP attempt exists; no replay")
        blocked={str(Path(p["path"]).resolve()).casefold() for p in pins}
        outputs=[str(Path(p).resolve()).casefold() for p in (source,receipt,marker)]
        require(len(set(outputs))==3 and not blocked.intersection(outputs),"Source/output/evidence overlap")
        report.update(assignment_pin=loaded["pin"],saved_draft_pin=saved["pin"],
            experiment_pin=epin,declared_transform=deepcopy(experiment["candidate_transform"]),
            conditional_domain=deepcopy(experiment["conditional_domain"]),
            marker_path=str(marker),candidate_id=expected_candidate_tool_native_id,
            target_operation_native_id=op_id,target_feature_native_id=fid,target_operation_setup_native_id=sid)
        _write_receipt(receipt,report,create=True);created=True
        require(identity()==loaded["state"]["document"],"Exact current assigned document required")
        app=_bootstrap(sw,clsid,typelib_path,source)
        require(identity()==loaded["state"]["document"],"Document changed acquiring CAM host")
        session=CamMessageSession(app,typelib_path)
        with session:
            events();native=capture("before")
            with guard() as g:
                raw=native["operations"][op_id]
                require(_object_id(native["doc"],raw,g.read)==op_id,"Target operation changed")
                row=next(o for o in report["before"]["operations"] if o["native_id"]==op_id)
                summary,_=read_generic_tool(raw,native["doc"],g.read,g.typed)
                require(summary==row["assigned_tool"],"Target tool changed before GTP")
                require(read_firstcut_settings(raw,g.read,g.typed)==loaded["candidate_payload"]["firstcut"],
                        "Firstcut changed before GTP")
                op=g.typed(raw,"ICWMillOperation")
                def pending():
                    nonlocal claimed
                    report.update(phase="GenerateToolpath",native_dispatch_pending=True,
                        GTP_attempted=True,GTP_call_count=1,mutation_attempted=True)
                    _write_receipt(marker,marker_state(),create=True);claimed=True;persist()
                result=g.dispatch_once(lambda:_member(op,"GenerateToolpath"),persist_pending=pending)
                report.update(GTP_returned=True,native_dispatch_pending=False,
                    native_return_type=type(result).__name__,
                    native_return_value=result if type(result) in (int,bool,float,str,type(None)) else None)
                persist()
            report["dispatch_guard"]=g.summary()
            require(type(result) is int and result==0,"Strict successful GenerateToolpath HRESULT required")
            capture("after")
        events(active=False);report["after_cleanup_document"]=identity();files()
        require(report["after_cleanup_document"]==report["after"]["document"],"Cleanup changed document")
        report.update(status="review_required",phase="finished",readback_verified=True,
            selected_toolpath_verified=True,protected_operations_verified=True,
            continuation_state=deepcopy(report["after"]),state_sha256=_digest(report["after"]),
            reason="ONE_VIRTUAL_TARGET_PATH_GENERATED_POSES_FRAME_UNITS_AND_COLLISIONS_REQUIRE_REVIEW")
    except Exception as exc:
        report.update(status="uncertain" if report["GTP_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),
            readback_verified=False,selected_toolpath_verified=False,protected_operations_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False)
    return report
