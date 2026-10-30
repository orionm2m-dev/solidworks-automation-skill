"""Save one completed observation draft with fresh bindings and referenced geometry."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id,_file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_route_operations
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_sandvik_phase1 import FIELDS,field_equal
from scripts.sw_cam_rough_firstcut import read_firstcut_settings
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_holder_mode_query import HOLDER_FIELDS
from scripts.sw_cam_existing_sandvik import resolve_existing_context
from scripts.sw_cam_completed_sandvik_evidence import load_completed_for_save
from scripts.sw_operation_guard import check_document_target

SCOPE="MILL_COMPLETED_SANDVIK_DRAFT_SAVE_V1"
MAX_READS=6000

def stable_payload(reference):
    candidate=reference["candidate"]
    return deepcopy(dict(tool=candidate["tool"],holder_profile=candidate["holder_profile"],
        holder_file=reference["holder_recipe"]["file_path"],firstcut=candidate["firstcut"],
        tools=candidate["local_tools"],metric_scope=candidate["metric_scope"],holder_fields=candidate["holder_fields"]))

def read_feature_counts(native,read,typed):
    rows=[]
    for raw in _items(read(native["machine"],"IGetEnumSetups"),typed,read,8):
        setup=typed(raw,"ICWBaseSetup")
        collection=typed(read(setup,"IGetEnumFeatures"),"ICWDispatchCollection")
        count=read(collection,"Count")
        sid=_object_id(native["doc"],setup,read)
        if type(count) is not int or not 0<=count<=256 or type(sid) is not int or sid<=0:
            raise ValueError("Bounded strict feature count and setup ID required")
        rows.append(dict(native_id=sid,feature_count=count))
    if len({r["native_id"] for r in rows})!=len(rows):raise ValueError("Duplicate setup ID")
    return rows

def save_completed_sandvik_draft(sw, clsid, typelib_path, *, observation_receipt_path,
        observation_receipt_sha256, expected_candidate_tool_native_id, **args):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(schema_version=1, scope=SCOPE, status="error", phase="preflight",
        process_id=args.get("process_id"), expected_document_path=args.get("expected_document_path"),
        source_before_sha256=args.get("expected_source_sha256"),
        tool_native_id=expected_candidate_tool_native_id, mutation_attempted=False,
        save_attempted=False, save_pending=False, native_call_attempted=False, native_call_returned=False,
        model_saved=False, save_readback_verified=False, reopen_persistence_verified=False,
        close_attempted=False, creator_attempted=False, MT_load_attempted=False,
        assignment_attempted=False, GTP_attempted=False, GOP_attempted=False, AFR_attempted=False,
        TechDB_write_attempted=False, automatic_replay=False, automatic_rollback=False,
        post_cleanup_CAM_getters=False, production_qualified=False, units_verified=False,
        experimental_draft_saved=False, holder_readback_stable=False,
        cutting_partition_verified=False, physical_tool_qualified=False, may_continue=False,
        capture_count=0, native_read_count=0, capture_diagnostics=[], guard_diagnostics=[])
    started=monotonic(); created=claimed=False; session=anchor=None
    baseline=None; active_guard=None; save_app=None; current_sha=args.get("expected_source_sha256")
    source=args.get("expected_document_path"); receipt=args.get("receipt_path"); loaded=None; phase1_receipt_sha256=None
    def marker_state():
        return dict(scope=SCOPE, phase=report["phase"], status=report["status"], document=source,
            source_before_sha256=args["expected_source_sha256"], phase1_receipt_sha256=phase1_receipt_sha256,
            observation_receipt_sha256=observation_receipt_sha256,
            tool_native_id=expected_candidate_tool_native_id, receipt_path=receipt,
            save_pending=report["save_pending"], native_call_returned=report["native_call_returned"],
            saved_file_sha256=report.get("saved_file_sha256"), automatic_replay=False)
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:
            if claimed:_write_receipt(loaded["marker"], marker_state())
            _write_receipt(receipt, report)
    def claim():
        nonlocal claimed
        _write_receipt(loaded["marker"], marker_state(), create=True); claimed=True
    def events(active=True):
        value=session.summary(); report["messages"]=value
        if (value.get("subscribed") is not True or value.get("active") is not active
                or (not active and value.get("disconnected") is not True)
                or any(value.get(k) for k in ("event_count","overflow","callback_errors",
                   "callback_error_count","subscription_error","disconnect_errors"))):
            raise ValueError("CAM events or transport require stop")
    def identity():
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid != args["process_id"]:raise ValueError("Exact process changed")
        anchor.check_runtime_identity(); value=raw_part_identity(sw)
        check_document_target(value["path"],value["title"],expected_path=source,required=True)
        if _file_hash(source)!=current_sha:raise ValueError("Current saved source changed")
        if baseline is not None and dict(value, needs_save=baseline["needs_save"])!=baseline:
            raise ValueError("Active document identity changed")
        return value
    def verify_files():
        anchor.check_files()
        for pin in loaded["pins"]:
            if _file_hash(pin["path"]) != pin["sha256"]:raise ValueError("Pinned save evidence changed")
    @contextmanager
    def reads():
        nonlocal active_guard
        if active_guard is not None:raise ValueError("Nested read guard")
        with ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],
                expected_document=identity(),source_sha256=current_sha,
                evidence_pins=anchor.pins+loaded["pins"],verify_evidence=verify_files,
                verify_owned_process=anchor.check_runtime_identity,check_events=events) as g:
            active_guard=g
            try:yield
            finally:
                active_guard=None
                report["guard_diagnostics"].append(g.summary())
    def read(obj,name,*values):
        if active_guard is None:raise ValueError("Getter outside bounded scope")
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Native read budget exceeded")
        return active_guard.read(obj,name,*values)
    def typed(obj,name):
        if active_guard is None:raise ValueError("QI outside bounded scope")
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Native read budget exceeded")
        return active_guard.typed(obj,name)
    def capture(label):
        nonlocal save_app
        verify_files();identity();events()
        report["capture_count"]+=1
        if report["capture_count"]>2:raise ValueError("One capture before and after only")
        diagnostic=dict(phase=label,reference_pin=loaded["pin"],fresh_full_snapshot=False,
            reused_fields=["feature_geometry","stock_geometry","tool_profile","shank_profile","holder_profile"],
            fresh_fields=["document","operations","tool_scalars","MT_path","holder_fields","firstcut","metric_scope"])
        report["capture_diagnostics"].append(diagnostic);persist()
        with reads():
            native=resolve_existing_context(app,read,typed,loaded["prior_data"])
            state=deepcopy(data["context"])
            feature_counts=read_feature_counts(native,read,typed)
            expected_counts=[dict(native_id=r["native_id"],feature_count=r["feature_count"]) for r in state["feature_setups"]]
            if feature_counts!=expected_counts:raise ValueError("Feature/setup counts changed")
            diagnostic["fresh_feature_counts"]=feature_counts
            read_route_operations(state,native,read,typed,diagnostic=diagnostic.setdefault("operations",{}))
            if state["operations"]!=data["context"]["operations"]:raise ValueError("Operations, assignments or paths changed")
            state["document"]=identity();state["saved_file_sha256"]=current_sha
            report[label+"_context"]=state
            crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
            matches=[raw for raw in _items(read(crib,"GetAllTools"),typed,read,128)
                if _object_id(native["doc"],raw,read)==expected_candidate_tool_native_id]
            if len(matches)!=1:raise ValueError("Exact existing candidate required")
            tool=typed(matches[0],"ICWTool")
            if read(tool,"IsMillTool") is not True:raise ValueError("MILL tool required")
            kind=read(tool,"ToolType")
            if type(kind) is not int or kind!=14:raise ValueError("Exact UD14 required")
            ud=typed(tool,"ICWMillUDTool")
            values={key:read(tool if key in ("CutDiameter","Protrusion") else ud,key) for key,_ in FIELDS}
            if any(not field_equal(k,values[k],v) for k,v in FIELDS) or values!=data["candidate"]["tool"]["parameters"]:
                raise ValueError("Current tool scalars changed")
            mt=read(ud,"GetToolName")
            check_document_target(mt,None,expected_path=data["candidate"]["tool"]["mt_path_raw"],required=True)
            holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
            holder_fields={name:read(holder,name) for name in HOLDER_FIELDS}
            expected_holder=data["candidate"]["holder_fields"]
            if any(type(holder_fields[k]) is not type(expected_holder[k]) or holder_fields[k]!=expected_holder[k] for k in HOLDER_FIELDS):
                raise ValueError("Current holder fields changed")
            firstcut=read_firstcut_settings(native["operations"][loaded["rough_id"]],read,typed)
            model=read(sw,"ActiveDoc")
            units=read_document_cam_unit_scope(model,app,sw_read=lambda o,n:read(o,n),cam_read=read)
            save_app=typed(app,"ICWApp")
            payload=stable_payload(data)
            payload.update(holder_fields=holder_fields,firstcut=firstcut,metric_scope=units)
            payload["tool"]["parameters"]=values;payload["tool"]["mt_path_raw"]=mt
        verify_files();identity();events()
        diagnostic["capture_complete"]=True
        return payload
    def verify(payload):
        if payload != stable_payload(data):raise ValueError("Candidate, holder, firstcut, crib or units changed")
    def boundary():
        if active_guard is not None:raise ValueError("Read handles must close before save")
        verify_files(); value=identity(); events()
        expected_dirty=False if report.get("saved_file_sha256") else baseline["needs_save"]
        if value["needs_save"] is not expected_dirty:raise ValueError("Unexpected dirty-state transition")
    def native_save():
        boundary()
        return _member(save_app,"SaveActiveDocument")
    def saved_hash():
        nonlocal current_sha
        events(); verify_files(); current_sha=_file_hash(source)
        identity(); events(); return current_sha
    try:
        loaded=load_completed_for_save(observation_receipt_path=observation_receipt_path,
            observation_receipt_sha256=observation_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        anchor=loaded["anchor"]; data=loaded["reference"]; observation=loaded["data"]
        phase1_receipt_sha256=loaded["prior_pin"]["sha256"]
        report.update(observation_pin=loaded["pin"],phase1_pin=loaded["prior_pin"],
            creation_pin=loaded["creation_pin"],firstcut_anchor=loaded["firstcut_anchor"],
            observation_evidence_pins=deepcopy(loaded["pins"]),candidate_contract=deepcopy(data["candidate_contract"]),
            holder_recipe=deepcopy(data["holder_recipe"]),profile_observation=deepcopy(data["candidate"]["profile_observation"]),
            anchor=anchor.summary(),request_binding=deepcopy(observation["request_binding"]),
            holder_shape_pin=deepcopy(observation["holder_shape_pin"]),
            noncutting_marker_pin=deepcopy(loaded["noncutting_marker_pin"]),
            capture_scope="fresh operations/scalars/identity/firstcut; full geometry and profiles reused from completed observation",
            holder_profile_verified=observation["holder_profile_verified"],
            holder_nominal_verification=deepcopy(data["candidate"]["holder_verification"]),
            save_marker_path=str(loaded["marker"]),classification_pending=True,
            observed_physical_flags={k:observation[k] for k in ("units_verified","cutting_partition_verified",
                "physical_tool_qualified","production_qualified","numeric_profile_verified")})
        _write_receipt(receipt,report,create=True); created=True
        baseline=identity()
        if baseline!=data["document"]:raise ValueError("Exact completed observation document required")
        report["before_document"]=baseline; persist()
        app=_bootstrap(sw,clsid,typelib_path,source)
        if identity()!=baseline:raise ValueError("Identity changed acquiring CAM host")
        session=CamMessageSession(app,typelib_path)
        with session:
            events()
            run_one_existing_save(report,capture=capture,verify=verify,guard=boundary,claim=claim,
                persist=persist,save=native_save,saved_hash=saved_hash)
            report["after_document"]=identity()
            if report["after_document"]!=report["after_context"]["document"]:
                raise ValueError("Final saved document differs from capture")
            events()
        events(active=False); report["after_cleanup_document"]=identity(); verify_files()
        if report["after_cleanup_document"]!=report["after_document"]:
            raise ValueError("Cleanup changed saved document")
        report.update(status="review_required",phase="finished",model_saved=True,
            experimental_draft_saved=True,holder_readback_stable=True,
            source_after_sha256=current_sha,continuation_state=deepcopy(report["after_context"]),
            state_sha256=_digest(report["after_context"]),readback_verified=True,
            full_geometry_rechecked=False,full_context_rechecked=False,
            continuation_state_provenance=dict(reference_pin=loaded["pin"],fresh_fields=["document","operations"],
                reused_fields="all remaining context geometry and metadata"),
            reason="ONE_COMPLETED_OBSERVATION_DRAFT_SAVE_VERIFIED_SHAPE_CLASSIFICATION_PENDING")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",
            failed_phase=report["phase"],phase="finished",issue=_error(exc),
            model_saved=False,save_readback_verified=False,readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:
            report.update(status="uncertain",receipt_write_error=_error(exc),
                          model_saved=False,save_readback_verified=False,readback_verified=False)
    return report
