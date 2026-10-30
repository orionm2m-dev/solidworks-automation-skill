"""One native draft save after verified first-cut and Sandvik qualification steps.

No creation, parameter edit, assignment, toolpath generation, close or reopen.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_mill_selected_tool_details import read_selected_operation_tool_details
from scripts.sw_cam_mill_compound_strategy import read_compound_strategy
from scripts.sw_cam_compound_plan_evidence import verify_protected_details
from scripts.sw_cam_compound_plan_delta import same_observed_context
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_ud14_qualification import read_ud14_tool, capture_local_tools
from scripts.sw_cam_ud14_probe_core import verify_one_new_tool
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains
from scripts.sw_cam_shared_holder_geometry import verify_holder_profile
from scripts.sw_cam_sandvik_mt import validate_native_profiles
from scripts.sw_cam_sandvik_phase1 import (
    SCOPE as PHASE1_SCOPE, BINDING_KEYS, FIELDS, field_equal, attempt_marker,
    holder_objects, com_identity, reject_holder_alias)
from scripts.sw_cam_rough_firstcut import load_firstcut_receipt, read_firstcut_settings
from scripts.sw_operation_guard import check_document_target

SCOPE = "MILL_FIRSTCUT_SANDVIK_DRAFT_SAVE_V1"
MAX_READS = 6000
TRUE_FLAGS = ("readback_verified", "exact_one_tool_created", "protected_context_unchanged",
              "numeric_profile_verified", "holder_profile_verified", "exports_verified")
FALSE_FLAGS = ("native_dispatch_pending", "operation_assignment_attempted", "GTP_attempted",
    "GOP_attempted", "AFR_attempted", "simulation_attempted", "model_saved", "save_attempted",
    "TechDB_write_attempted", "automatic_replay", "automatic_rollback", "post_cleanup_CAM_getters",
    "units_verified", "cutting_partition_verified", "physical_tool_qualified", "production_qualified")


def save_marker(document_path, phase1_sha, new_id):
    source = Path(document_path).resolve()
    key = _digest(dict(scope=SCOPE, document=str(source).casefold(),
                       phase1_sha256=phase1_sha, tool_native_id=new_id))
    return source.parent / ("sandvik_draft_save_" + key + ".json")


def stable_payload(data):
    """No volatile body-mass, saved SHA or document dirty state in this projection."""
    return deepcopy(dict(tool=data["tool"], holder_profile=data["holder_profile"],
        holder_file=data["holder_recipe"]["file_path"], firstcut=data["after_firstcut"],
        tools=data["after_tools"], metric_scope=data["metric_scope"]))


def verify_context(reference, observed, *, after_save=False):
    if not same_observed_context(reference, observed, allow_dirty=after_save,
                                 allow_saved_source=after_save):
        raise ValueError("Full protected CAM/CAD context changed")
    if after_save and observed["document"]["needs_save"] is not False:
        raise ValueError("Native save left document dirty")


def load_stage1_for_save(*, phase1_receipt_path, phase1_receipt_sha256,
        expected_candidate_tool_native_id, **args):
    """Pinned successful stage1 only; physical qualification may remain pending."""
    validate_inventory_request(**{k:args[k] for k in ("process_id", "expected_document_path",
        "expected_source_sha256", "qualification_only", "acknowledge_disposable_copy",
        "receipt_path", "message_policy")})
    new_id = expected_candidate_tool_native_id
    if type(new_id) is not int or not 0 < new_id < 2**32:
        raise ValueError("Strict positive existing candidate tool ID required")
    data, pin = read_pin(phase1_receipt_path, phase1_receipt_sha256)
    if (data.get("scope") != PHASE1_SCOPE or data.get("status") != "review_required"
            or data.get("phase") != "finished" or data.get("new_tool_native_id") != new_id
            or type(data.get("new_tool_native_id")) is not int):
        raise ValueError("Completed exact stage1 candidate required")
    for k in TRUE_FLAGS:
        if data.get(k) is not True:raise ValueError("Incomplete stage1: " + k)
    for k in FALSE_FLAGS:
        if data.get(k) is not False:raise ValueError("Unexpected stage1 flag: " + k)
    if any(k in data for k in ("issue", "failed_phase", "receipt_write_error")):
        raise ValueError("Failed stage1 never authorizes save")
    clean_events(data)
    binding = {k:args[k] for k in BINDING_KEYS + ("saved_plan_receipt_path", "saved_plan_receipt_sha256")}
    bound = data.get("request_binding", {})
    for k, v in binding.items():
        if type(bound.get(k)) is not type(v) or bound[k] != v:
            raise ValueError("Stage1 request binding differs: " + k)
    if (data.get("process_id") != args["process_id"] or type(data.get("process_id")) is not int
            or data.get("source_before_sha256") != args["expected_source_sha256"]
            or data.get("expected_source_sha256") != args["expected_source_sha256"]):
        raise ValueError("Stage1 process/source differs")
    check_document_target(data.get("expected_document_path"), None,
        expected_path=args["expected_document_path"], required=True)
    anchor = load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],
        args["saved_plan_receipt_sha256"], **{k:args[k] for k in BINDING_KEYS})
    if (anchor.data.get("scope") != "MILL_ADDED_CIRCULAR_POCKET_PLAN_V1"
            or len(anchor.state["features"]) != 19 or len(anchor.state["operations"]) != 6
            or data["anchor"] != anchor.summary()):
        raise ValueError("Exact saved nineteen-feature six-operation scope required")
    if any(o["toolpath_generated"] is not False or o["toolpath_record_counts"] != []
           for o in anchor.state["operations"]):
        raise ValueError("Only zero-path definitions may be saved here")
    rough = [o for o in anchor.data["new_operations"] if o["mill_operation_type"] == 0]
    if len(rough) != 1:raise ValueError("One exact added rough operation required")
    target = rough[0]
    firstcut_pin = dict(path=bound["firstcut_receipt_path"], sha256=bound["firstcut_receipt_sha256"])
    firstcut = load_firstcut_receipt(firstcut_pin["path"], firstcut_pin["sha256"],
        process_id=args["process_id"], expected_document_path=args["expected_document_path"],
        expected_source_sha256=args["expected_source_sha256"],
        target_feature_native_id=anchor.data["new_feature_native_id"],
        target_operation_native_id=target["native_id"],
        target_operation_setup_native_id=target["setup_native_id"])
    if (data["firstcut_anchor"] != dict(pin=firstcut_pin, after_settings=firstcut["after_settings"])
            or data["before_firstcut"] != firstcut["after_settings"]
            or data["after_firstcut"] != firstcut["after_settings"]
            or firstcut["after_settings"].get("direct_type") != 0
            or data["before_document"] != firstcut["after_document"]):
        raise ValueError("Exact completed first-cut continuation required")
    if not same_observed_context(data["before"], data["after"], allow_dirty=True):
        raise ValueError("Stage1 protected context changed")
    # The source has not been saved in either prior stage.
    if (data["before"]["saved_file_sha256"] != args["expected_source_sha256"]
            or data["after"]["saved_file_sha256"] != args["expected_source_sha256"]
            or data["after_document"] != data["after"]["document"]):
        raise ValueError("Unexpected prior save or cleanup document change")
    normalized = deepcopy(data["after"])
    normalized["document"]["needs_save"] = anchor.state["document"]["needs_save"]
    anchor.verify(normalized)
    verify_one_new_tool(data["before_tools"], data["after_tools"], new_id)
    tool = data["tool"]
    if (tool.get("native_id") != new_id or tool.get("tool_type_raw") != 14
            or tool.get("profile_complete") is not True
            or data["final_scalar_observation"] != tool["parameters"]):
        raise ValueError("Complete final candidate readback required")
    if not all(field_equal(k, tool["parameters"][k], v) for k, v in FIELDS):
        raise ValueError("Exact coherent candidate fields required")
    check_document_target(tool["mt_path_raw"], None,
        expected_path=data["candidate_asset"]["path"], required=True)
    validate_native_profiles(data["candidate_contract"], tool["profiles"])
    verify_holder_profile(data["holder_profile"], data["holder_recipe"], 25)
    creation = attempt_marker(args["expected_document_path"], args["expected_source_sha256"],
                              data["candidate_asset"]["sha256"])
    check_document_target(data["dispatch_marker_path"], None, expected_path=str(creation), required=True)
    creation_sha = _file_hash(creation)
    creation_data, creation_pin = read_pin(str(creation), creation_sha)
    if (creation_data.get("scope") != PHASE1_SCOPE or creation_data.get("phase") != "finished"
            or creation_data.get("status") != "review_required"
            or creation_data.get("native_dispatch_pending") is not False
            or creation_data.get("new_tool_native_id") != new_id
            or creation_data.get("source_sha256") != args["expected_source_sha256"]
            or creation_data.get("candidate_sha256") != data["candidate_asset"]["sha256"]
            or creation_data.get("dispatches") != data["dispatches"]
            or creation_data.get("automatic_replay") is not False):
        raise ValueError("Successful original creation marker required")
    check_document_target(creation_data.get("document"), None,
        expected_path=args["expected_document_path"], required=True)
    check_document_target(creation_data.get("receipt_path"), None,
        expected_path=phase1_receipt_path, required=True)
    dispatches = data["dispatches"]
    if (type(dispatches) is not list or not 5 <= len(dispatches) <= 14
            or sum(d.get("label") == "AddNewTool3" for d in dispatches) != 1
            or any(d.get("attempted") is not True or d.get("returned") is not True
                   or d.get("pending") is not False for d in dispatches)):
        raise ValueError("Complete single creation dispatch history required")
    pins = [pin, creation_pin, firstcut_pin] + data["candidate_contract"]["pins"] + data["holder_recipe"]["pins"]
    pins.append(data["candidate_asset"])
    for portion in ("cutting", "noncutting"):
        mesh = data["exports"][portion]
        if mesh.get("mesh_health_verified") is not True or mesh.get("portion") != portion:
            raise ValueError("Completed native portion export required")
        pins.append(mesh["pin"])
    for p in pins:
        if _file_hash(p["path"]) != p["sha256"]:raise ValueError("Immutable prior evidence changed")
    marker = save_marker(args["expected_document_path"], phase1_receipt_sha256, new_id)
    if marker.exists() or marker.is_symlink():raise ValueError("Prior save attempt exists; no replay")
    paths = [args["expected_document_path"], args["receipt_path"], str(marker)] + [p["path"] for p in pins]
    protected = {str(Path(p).resolve()).casefold() for p in paths[3:]}
    outputs = {str(Path(p).resolve()).casefold() for p in paths[:3]}
    if len(outputs) != 3 or outputs & protected:
        raise ValueError("Source, output, attempt marker and evidence must be distinct")
    return dict(data=data, pin=pin, anchor=anchor, rough_id=target["native_id"],
                pins=pins, creation_pin=creation_pin, marker=marker)


def save_sandvik_draft(sw, clsid, typelib_path, *, phase1_receipt_path,
        phase1_receipt_sha256, expected_candidate_tool_native_id, **args):
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
        cutting_partition_verified=False, physical_tool_qualified=False, may_continue=False,
        capture_count=0, native_read_count=0, capture_diagnostics=[], guard_diagnostics=[])
    started=monotonic(); created=claimed=False; session=anchor=None
    baseline=None; active_guard=None; save_app=None; current_sha=args.get("expected_source_sha256")
    source=args.get("expected_document_path"); receipt=args.get("receipt_path"); loaded=None
    def marker_state():
        return dict(scope=SCOPE, phase=report["phase"], status=report["status"], document=source,
            source_before_sha256=args["expected_source_sha256"], phase1_receipt_sha256=phase1_receipt_sha256,
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
    def details(state,native,read,typed,diag,boundary):
        read_selected_operation_tool_details(state,native,read,typed,diag,
            feature_native_id=args["expected_feature_native_id"],boundary=boundary)
        request=anchor.data["request"]
        for mode in ("three_step_profile","strategy"):
            read_compound_strategy(state,native,read,typed,diag.setdefault(mode,{}),
                feature_id=request["reference_feature_native_id"],owner_id=request["owner_setup_native_id"],
                step_count=3,expected_header=anchor.profile["header"],boundary=boundary,observation=mode)
        verify_protected_details(anchor,state,diag)
        if any(diag[k]!=anchor.data["saved_details"][k] for k in ("three_step_profile","strategy")):
            raise ValueError("Protected compound metadata changed")
    def capture(label):
        nonlocal save_app
        verify_files(); identity(); events()
        report["capture_count"]+=1
        if report["capture_count"]>2:raise ValueError("One capture before and after only")
        diagnostic=dict(phase=label); report["capture_diagnostics"].append(diagnostic); persist()
        state,native=capture_selected_plan(sw,clsid,typelib_path,source,
            process_id=args["process_id"],expected_source_sha256=current_sha,evidence=anchor,
            check=events,diagnostic=diagnostic,progress=persist,operation_details_reader=details)
        report[label+"_context"]=state
        reference=data["after"] if label=="before" else report["before_context"]
        verify_context(reference,state,after_save=label=="after")
        with reads():
            crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
            tools=capture_local_tools(crib,native["doc"],read,typed)
            matches=[raw for raw in _items(read(crib,"GetAllTools"),typed,read,128)
                     if _object_id(native["doc"],raw,read)==expected_candidate_tool_native_id]
            if len(matches)!=1:raise ValueError("Exact existing candidate required")
            raw=matches[0]; tool=typed(raw,"ICWTool")
            observed=read_ud14_tool(raw,doc=native["doc"],read=read,typed=typed,
                                   diagnostic=diagnostic.setdefault("candidate",{}))
            holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
            identities=holder_objects(crib,native["doc"],read,typed)
            old_holders={k:v for k,v in identities.items() if k!=expected_candidate_tool_native_id}
            reject_holder_alias(holder,old_holders,identity=lambda obj:com_identity(obj,read))
            holder_file=read(holder,"GetName")
            check_document_target(holder_file,None,expected_path=data["holder_recipe"]["file_path"],required=True)
            hp={}; read_segment_chains(holder,"GetHolderProfile",read=read,typed=typed,
                diagnostic={"state":hp},budget=dict(curves=0,chains=0,islands=0))
            verify_holder_profile(hp,data["holder_recipe"],25)
            validate_native_profiles(data["candidate_contract"],observed["profiles"])
            firstcut=read_firstcut_settings(native["operations"][loaded["rough_id"]],read,typed)
            units=read_document_cam_unit_scope(sw.ActiveDoc,app,sw_read=lambda o,n:read(o,n),cam_read=read)
            save_app=typed(app,"ICWApp")
            payload=dict(tool=observed,holder_profile=hp,holder_file=data["holder_recipe"]["file_path"],
                         firstcut=firstcut,tools=tools,metric_scope=units)
        verify_files(); identity(); events()
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
        loaded=load_stage1_for_save(phase1_receipt_path=phase1_receipt_path,
            phase1_receipt_sha256=phase1_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        anchor=loaded["anchor"]; data=loaded["data"]
        report.update(phase1_pin=loaded["pin"],creation_pin=loaded["creation_pin"],
            firstcut_anchor=data["firstcut_anchor"],anchor=anchor.summary(),
            request_binding=deepcopy(data["request_binding"]),save_marker_path=str(loaded["marker"]),
            stage1_physical_flags={k:data[k] for k in ("units_verified","cutting_partition_verified",
                                                    "physical_tool_qualified","production_qualified")})
        _write_receipt(receipt,report,create=True); created=True
        baseline=identity()
        if baseline!=data["after_document"]:raise ValueError("Exact completed stage1 document required")
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
            source_after_sha256=current_sha,continuation_state=deepcopy(report["after_context"]),
            state_sha256=_digest(report["after_context"]),readback_verified=True,
            reason="ONE_NATIVE_DRAFT_SAVE_VERIFIED_NO_CLOSE_REOPEN_PHYSICAL_QUALIFICATION_PENDING")
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

