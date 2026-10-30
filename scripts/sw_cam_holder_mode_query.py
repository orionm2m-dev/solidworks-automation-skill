"""Bounded native holder mode/dimensions query for an existing candidate."""
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import validate_inventory_request, _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_existing_sandvik import (SCOPE as OBSERVATION_SCOPE, COLLECTOR_MODE,
    PHASE1_SHA, WRITER_SHA, resolve_existing_context)
from scripts.sw_cam_existing_sandvik_evidence import load_existing_candidate_evidence
from scripts.sw_cam_holder_observation import complete_holder_profile
from scripts.sw_cam_mill_tool_geometry import _integer, _text
from scripts.sw_cam_ud14_qualification import _scalar as _finite_scalar
from scripts.sw_cam_sandvik_phase1 import BINDING_KEYS, FIELDS, field_equal
from scripts.sw_operation_guard import check_document_target

SCOPE="EXISTING_CANDIDATE_HOLDER_MODE_QUERY_V1"
MAX_READS=256
HOLDER_FIELDS=("GetHolderShape","GetHolderId","GetHolderNumber","GetName",
    "GetHolderTopDia","GetHolderBottomDia","GetHolderOverallLength","GetHolderBottomLength","GetProtrusion")


def load_holder_query(*,observation_receipt_path,observation_receipt_sha256,
        expected_candidate_tool_native_id,**args):
    validate_inventory_request(**{k:args[k] for k in ("process_id","expected_document_path",
        "expected_source_sha256","qualification_only","acknowledge_disposable_copy","receipt_path","message_policy")})
    new_id=expected_candidate_tool_native_id
    if type(new_id) is not int or not 0<new_id<2**32:raise ValueError("Strict existing candidate required")
    data,pin=read_pin(observation_receipt_path,observation_receipt_sha256)
    if (data.get("scope")!=OBSERVATION_SCOPE or data.get("collector_mode")!=COLLECTOR_MODE
        or data.get("phase")!="finished" or data.get("status") not in ("uncertain","review_required")
        or type(data.get("tool_native_id")) is not int or data["tool_native_id"]!=new_id
        or data.get("holder_profile_observed") is not True):
        raise ValueError("Finished collector with complete before-candidate required")
    for flag in ("native_dispatch_pending","mutation_attempted","tool_creation_attempted","MT_load_attempted",
        "field_setter_attempted","holder_setter_attempted","operation_assignment_attempted","GTP_attempted",
        "GOP_attempted","AFR_attempted","model_saved","save_attempted","TechDB_write_attempted"):
        if data.get(flag) is not False:raise ValueError("Prior mutation or pending native action blocks query")
    if "receipt_write_error" in data:raise ValueError("Unpublished collector receipt")
    clean_events(data)
    binding={k:args[k] for k in BINDING_KEYS+("saved_plan_receipt_path","saved_plan_receipt_sha256")}
    if data["request_binding"]!=binding or type(data.get("process_id")) is not int or data["process_id"]!=args["process_id"]:
        raise ValueError("Query process/scope differs from collector")
    if data["source_before_sha256"]!=args["expected_source_sha256"] or data["expected_source_sha256"]!=args["expected_source_sha256"]:
        raise ValueError("Collector source differs")
    check_document_target(data["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    def implementation(sha):
        rows=[p for p in data["evidence_pins"] if p["sha256"]==sha]
        if len(rows)!=1:raise ValueError("One immutable implementation pin required")
        return rows[0]
    backend=implementation(PHASE1_SHA);writer=implementation(WRITER_SHA);prior=data["prior_receipt_pin"]
    loaded=load_existing_candidate_evidence(phase1_receipt_path=prior["path"],phase1_receipt_sha256=prior["sha256"],
        expected_candidate_tool_native_id=new_id,phase1_backend_path=backend["path"],phase1_backend_sha256=backend["sha256"],
        profile_validator_path=writer["path"],profile_validator_sha256=writer["sha256"],**args)
    candidate=data["before_candidate"]
    if (candidate["tool"]!=loaded["data"]["tool"] or candidate["firstcut"]!=loaded["firstcut"]
        or candidate["metric_scope"]!=loaded["data"]["metric_scope"] or data["before_document"]!=loaded["data"]["before_document"]
        or data["prior_receipt_pin"]!=loaded["pin"] or data["prior_creation_marker_pin"]!=loaded["creation_pin"]
        or data["anchor"]!=loaded["anchor"].summary()):raise ValueError("Frozen candidate/anchor differs")
    hp=candidate["holder_profile"];complete_holder_profile(hp)
    hd=data["before_holder_diagnostic"]
    if (hd.get("capture_complete") is not True or hd.get("stage")!="complete" or hd.get("state")!=hp
        or data["before_holder_profile"]!=hp):raise ValueError("Complete retained holder profile required")
    pins={}
    for p in [pin]+loaded["pins"]+data["evidence_pins"]:
        canonical=str(Path(p["path"]).resolve()).casefold()
        if canonical in pins and pins[canonical]["sha256"]!=p["sha256"]:raise ValueError("Conflicting immutable pin")
        if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Query evidence changed")
        pins[canonical]=p
    blocked={Path(p["path"]).resolve() for p in list(pins.values())+loaded["anchor"].pins}
    if Path(args["receipt_path"]).resolve() in blocked|{Path(args["expected_document_path"]).resolve()}:
        raise ValueError("Query receipt aliases immutable source")
    return dict(data=data,candidate=candidate,anchor=loaded["anchor"],pins=list(pins.values()),
        prior=loaded["data"],holder=loaded["holder"],observation_pin=pin)


def query_existing_holder(sw,clsid,typelib_path,*,observation_receipt_path,observation_receipt_sha256,
        expected_candidate_tool_native_id,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status="error",phase="preflight",native_read_count=0,
        mutation_attempted=False,export_attempted=False,save_attempted=False,assignment_attempted=False,
        GTP_attempted=False,profile_read_attempted=False,readback_verified=False,
        manufacturing_qualified=False,may_mutate=False,full_context_rechecked=False,units_verified=False,raw_dimensions=True)
    created=False;loaded=None;session=None;started=monotonic();g=None
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:_write_receipt(args["receipt_path"],report)
    def events(active=True):
        value=session.summary();report["messages"]=value
        if (value.get("subscribed") is not True or value.get("active") is not active
            or (not active and value.get("disconnected") is not True)
            or any(value.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count",
                "subscription_error","disconnect_errors"))):raise ValueError("CAM event/transport changed")
    def identity():
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid!=args["process_id"]:raise ValueError("Owned process differs")
        loaded["anchor"].check_runtime_identity();doc=raw_part_identity(sw)
        if doc!=loaded["data"]["before_document"]:raise ValueError("Current document/dirty identity changed")
        if _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:raise ValueError("Saved source changed")
        return doc
    def files():
        loaded["anchor"].check_files()
        for p in loaded["pins"]:
            if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Immutable query evidence changed")
    def read(o,n,*v):
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Query read budget exceeded")
        return g.read(o,n,*v)
    def typed(o,n):
        report["native_read_count"]+=1
        if report["native_read_count"]>MAX_READS:raise ValueError("Query read budget exceeded")
        return g.typed(o,n)
    def scalars(tool,ud):
        result={k:read(tool if k in ("CutDiameter","Protrusion") else ud,k) for k,_ in FIELDS}
        if any(not field_equal(k,result[k],loaded["candidate"]["tool"]["parameters"][k]) for k,_ in FIELDS):
            raise ValueError("Existing candidate scalar changed")
        return result
    try:
        loaded=load_holder_query(observation_receipt_path=observation_receipt_path,
            observation_receipt_sha256=observation_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        _write_receipt(args["receipt_path"],report,create=True);created=True
        report.update(observation_pin=loaded["observation_pin"],process_id=args["process_id"],
            expected_document_path=args["expected_document_path"],source_sha256=args["expected_source_sha256"],
            tool_native_id=expected_candidate_tool_native_id,before_document=identity())
        files();app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"]);identity()
        session=CamMessageSession(app,typelib_path)
        with session:
            events();report["phase"]="holder_query";persist()
            guard=ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],expected_document=identity(),
                source_sha256=args["expected_source_sha256"],evidence_pins=loaded["anchor"].pins+loaded["pins"],
                verify_evidence=files,verify_owned_process=loaded["anchor"].check_runtime_identity,check_events=events)
            try:
                with guard as g:
                    native=resolve_existing_context(app,read,typed,loaded["prior"])
                    crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
                    matches=[]
                    for raw in _items(read(crib,"GetAllTools"),typed,read,128):
                        t=typed(raw,"ICWTool")
                        if _object_id(native["doc"],t,read)==expected_candidate_tool_native_id:matches.append(t)
                    if len(matches)!=1:raise ValueError("Existing candidate is not unique")
                    tool=matches[0];ud=typed(tool,"ICWMillUDTool")
                    kind=read(tool,"ToolType")
                    if type(kind) is not int or kind!=14 or read(tool,"IsMillTool") is not True:raise ValueError("Exact UD14 MILL candidate required")
                    mt=read(ud,"GetToolName")
                    check_document_target(mt,None,expected_path=loaded["candidate"]["tool"]["mt_path_raw"],required=True)
                    report["before_tool_parameters"]=scalars(tool,ud)
                    holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
                    raw_holder={};report["holder"]=raw_holder
                    for name in HOLDER_FIELDS:
                        value=read(holder,name);raw_holder[name]=value;persist()
                        if name in ("GetHolderShape","GetHolderNumber","GetName"):
                            _text(value,name)
                            if name!="GetHolderNumber" and not value:raise ValueError("Nonempty holder mode/reference required")
                        elif name=="GetHolderId":
                            _integer(value,name)
                        else:_finite_scalar(value,name)
                    check_document_target(raw_holder["GetName"],None,expected_path=loaded["holder"]["file_path"],required=True)
                    report["after_tool_parameters"]=scalars(tool,ud)
                    if report["before_tool_parameters"]!=report["after_tool_parameters"]:raise ValueError("Candidate scalars changed during query")
                    if read(holder,"GetHolderShape")!=raw_holder["GetHolderShape"] or read(holder,"GetName")!=raw_holder["GetName"]:
                        raise ValueError("Holder mode/reference changed during query")
                    if _object_id(native["doc"],tool,read)!=expected_candidate_tool_native_id:
                        raise ValueError("Candidate identity changed during query")
                    final_type=read(tool,"ToolType")
                    if type(final_type) is not int or final_type!=14 or read(tool,"IsMillTool") is not True:
                        raise ValueError("Candidate type changed during query")
                    if read(ud,"GetToolName")!=mt:raise ValueError("Candidate MT reference changed during query")
                    current_holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
                    current_values={};report["after_holder"]=current_values
                    for name in HOLDER_FIELDS:
                        current_values[name]=read(current_holder,name);persist()
                    if any(type(current_values[n]) is not type(raw_holder[n]) or current_values[n]!=raw_holder[n] for n in HOLDER_FIELDS):
                        raise ValueError("Assigned holder fields changed during query")
                    identity();files();events()
            finally:report["guard_diagnostic"]=guard.summary()
        events(active=False);report["after_document"]=identity();files()
        report.update(status="observed",phase="finished",readback_verified=True)
    except Exception as exc:
        report.update(status="error",phase="finished",readback_verified=False,issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="error",readback_verified=False,receipt_write_error=_error(exc))
    return report