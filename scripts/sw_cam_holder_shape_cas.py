"""Single existing-holder shape selection with raw geometry readback; no Save."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member,_error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_holder_mode_query import load_holder_query,HOLDER_FIELDS,SCOPE as QUERY_SCOPE,_finite_scalar
from scripts.sw_cam_existing_sandvik import resolve_existing_context
from scripts.sw_cam_sandvik_phase1 import FIELDS,field_equal,holder_objects,reject_holder_alias,com_identity
from scripts.sw_cam_holder_observation import complete_holder_profile,observe_holder_nominal
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains
from scripts.sw_cam_mill_tool_geometry import _text,_integer
from scripts.sw_operation_guard import check_document_target

SCOPE="EXISTING_HOLDER_SHAPE_SINGLE_CAS_V1"
DESIRED_INPUT="User Defined"
MAX_READS=1600


def shape_marker(document,creation_sha,tool_id):
    source=Path(document).resolve()
    key=_digest(dict(scope=SCOPE,document=str(source).casefold(),creation_receipt_sha256=creation_sha,
        tool_native_id=tool_id,desired_input=DESIRED_INPUT))
    return source.parent/("sandvik_holder_shape_"+key+".json")


def load_shape_change(*,holder_query_receipt_path,holder_query_receipt_sha256,
        expected_candidate_tool_native_id,expected_holder_shape_raw,desired_holder_shape,**args):
    if (type(expected_holder_shape_raw) is not str or not expected_holder_shape_raw
        or len(expected_holder_shape_raw)>4096 or desired_holder_shape!=DESIRED_INPUT):
        raise ValueError("Exact observed raw mode and documented single desired input required")
    query,pin=read_pin(holder_query_receipt_path,holder_query_receipt_sha256)
    if (query.get("scope")!=QUERY_SCOPE or query.get("status")!="observed" or query.get("phase")!="finished"
        or query.get("readback_verified") is not True or query.get("raw_dimensions") is not True
        or type(query.get("tool_native_id")) is not int or query["tool_native_id"]!=expected_candidate_tool_native_id):
        raise ValueError("Completed stable exact holder query required")
    for flag in ("mutation_attempted","export_attempted","save_attempted","assignment_attempted","GTP_attempted",
                 "profile_read_attempted","manufacturing_qualified","may_mutate","full_context_rechecked","units_verified"):
        if query.get(flag) is not False:raise ValueError("Unexpected query flag: "+flag)
    if any(k in query for k in ("issue","receipt_write_error")):raise ValueError("Failed query cannot authorize shape selection")
    clean_events(query)
    gd=query.get("guard_diagnostic",{})
    if gd.get("invalid") is not False or gd.get("native_call_attempted") is not False:
        raise ValueError("Successful read-only query guard required")
    if (query.get("process_id")!=args["process_id"] or type(query.get("process_id")) is not int
        or query.get("source_sha256")!=args["expected_source_sha256"]):raise ValueError("Query process/source differs")
    check_document_target(query["expected_document_path"],None,expected_path=args["expected_document_path"],required=True)
    observation=query["observation_pin"]
    loaded=load_holder_query(observation_receipt_path=observation["path"],observation_receipt_sha256=observation["sha256"],
        expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
    if (query["before_document"]!=loaded["data"]["before_document"] or query["after_document"]!=query["before_document"]
        or query["before_tool_parameters"]!=loaded["candidate"]["tool"]["parameters"]
        or query["after_tool_parameters"]!=query["before_tool_parameters"]
        or query["holder"]!=query["after_holder"] or query["holder"]["GetHolderShape"]!=expected_holder_shape_raw):
        raise ValueError("Exact query snapshot or expected raw mode differs")
    if expected_holder_shape_raw==DESIRED_INPUT:raise ValueError("Requested shape already observed; no replay")
    check_document_target(query["holder"]["GetName"],None,expected_path=loaded["holder"]["file_path"],required=True)
    marker=shape_marker(args["expected_document_path"],loaded["data"]["prior_receipt_pin"]["sha256"],expected_candidate_tool_native_id)
    if marker.exists() or marker.is_symlink():raise ValueError("Prior holder-shape attempt exists; never replay")
    pins=loaded["pins"]+[pin]
    blocked={Path(p["path"]).resolve() for p in pins+loaded["anchor"].pins}
    if marker.resolve() in blocked|{Path(args["receipt_path"]).resolve()}:raise ValueError("Shape marker aliases evidence/output")
    loaded.update(query=query,query_pin=pin,pins=pins,marker=marker)
    return loaded


def change_existing_holder_shape(sw,clsid,typelib_path,*,holder_query_receipt_path,holder_query_receipt_sha256,
        expected_candidate_tool_native_id,expected_holder_shape_raw,desired_holder_shape,**args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(scope=SCOPE,status="error",phase="preflight",process_id=args.get("process_id"),
        tool_native_id=expected_candidate_tool_native_id,expected_document_path=args.get("expected_document_path"),
        source_sha256=args.get("expected_source_sha256"),expected_holder_shape_raw=expected_holder_shape_raw,
        desired_input=desired_holder_shape,mutation_attempted=False,setter_attempted=False,native_dispatch_pending=False,
        native_call_returned=False,readback_verified=False,holder_profile_verified=False,mode_changed=False,
        assignment_attempted=False,GTP_attempted=False,save_attempted=False,export_attempted=False,
        file_reference_setter_attempted=False,tool_creation_attempted=False,TechDB_write_attempted=False,
        automatic_replay=False,automatic_rollback=False,full_context_rechecked=False,protected_context_unchanged=False,
        production_qualified=False,physical_holder_qualified=False,may_continue=False,native_read_count=0,guard_diagnostics=[])
    created=claimed=False;loaded=None;session=None;active=None;started=monotonic();baseline=None
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:
            if claimed:_write_receipt(loaded["marker"],dict(scope=SCOPE,receipt_path=args["receipt_path"],
                tool_native_id=expected_candidate_tool_native_id,query_pin=loaded["query_pin"],
                status=report["status"],phase=report["phase"],native_dispatch_pending=report["native_dispatch_pending"],
                native_call_returned=report["native_call_returned"],automatic_replay=False))
            _write_receipt(args["receipt_path"],report)
    def events(active_state=True):
        value=session.summary();report["messages"]=value
        if (value.get("subscribed") is not True or value.get("active") is not active_state
            or (not active_state and value.get("disconnected") is not True)
            or any(value.get(k) for k in ("event_count","overflow","callback_errors","callback_error_count",
                    "subscription_error","disconnect_errors"))):raise ValueError("CAM event/transport requires stop")
    def files():
        loaded["anchor"].check_files()
        for p in loaded["pins"]:
            if _file_hash(p["path"])!=p["sha256"]:raise ValueError("Immutable shape-selection evidence changed")
    def identity():
        pid=_member(sw,"GetProcessID")
        if type(pid) is not int or pid!=args["process_id"]:raise ValueError("Owned process changed")
        loaded["anchor"].check_runtime_identity();doc=raw_part_identity(sw)
        if dict(doc,needs_save=baseline["needs_save"])!=baseline or type(doc.get("needs_save")) is not bool:
            raise ValueError("Document identity changed")
        if not report["setter_attempted"] and doc!=baseline:raise ValueError("Dirty flag changed before setter")
        if _file_hash(args["expected_document_path"])!=args["expected_source_sha256"]:raise ValueError("Saved source changed")
        return doc
    @contextmanager
    def guarded():
        with ScopedCamDispatchGuard(sw,typelib_path,process_id=args["process_id"],expected_document=identity(),
                source_sha256=args["expected_source_sha256"],evidence_pins=loaded["anchor"].pins+loaded["pins"],
                verify_evidence=files,verify_owned_process=loaded["anchor"].check_runtime_identity,check_events=events) as guard:
            try:yield guard
            finally:report["guard_diagnostics"].append(guard.summary())
    @contextmanager
    def reads():
        nonlocal active
        if active is not None:raise ValueError("Nested read scope")
        with guarded() as guard:
            active=guard
            try:yield
            finally:active=None
    def read(o,n,*v):
        report["native_read_count"]+=1
        if active is None or report["native_read_count"]>MAX_READS:raise ValueError("Bounded active read scope required")
        return active.read(o,n,*v)
    def typed(o,n):
        report["native_read_count"]+=1
        if active is None or report["native_read_count"]>MAX_READS:raise ValueError("Bounded active query scope required")
        return active.typed(o,n)
    def snapshot(phase,with_profile=False):
        with reads():
            native=resolve_existing_context(app,read,typed,loaded["prior"])
            crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
            matches=[]
            for raw in _items(read(crib,"GetAllTools"),typed,read,128):
                tool=typed(raw,"ICWTool")
                if _object_id(native["doc"],tool,read)==expected_candidate_tool_native_id:matches.append(tool)
            if len(matches)!=1:raise ValueError("Existing candidate is not unique")
            tool=matches[0];ud=typed(tool,"ICWMillUDTool");kind=read(tool,"ToolType")
            if type(kind) is not int or kind!=14 or read(tool,"IsMillTool") is not True:raise ValueError("Exact UD14 candidate required")
            mt=read(ud,"GetToolName");check_document_target(mt,None,expected_path=loaded["candidate"]["tool"]["mt_path_raw"],required=True)
            values={k:read(tool if k in ("CutDiameter","Protrusion") else ud,k) for k,_ in FIELDS}
            if any(not field_equal(k,values[k],loaded["candidate"]["tool"]["parameters"][k]) for k,_ in FIELDS):raise ValueError("Candidate fields changed")
            holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
            all_holders=holder_objects(crib,native["doc"],read,typed)
            reject_holder_alias(holder,{k:v for k,v in all_holders.items() if k!=expected_candidate_tool_native_id},
                identity=lambda o:com_identity(o,read))
            state=dict(tool_parameters=values,mt_path_raw=mt,holder={});report[phase]=state
            for name in HOLDER_FIELDS:
                value=read(holder,name);state["holder"][name]=value
                if name in ("GetHolderShape","GetHolderNumber","GetName"):_text(value,name)
                elif name=="GetHolderId":_integer(value,name)
                else:_finite_scalar(value,name)
            check_document_target(state["holder"]["GetName"],None,expected_path=loaded["holder"]["file_path"],required=True)
            persist()
            if with_profile:
                hd=dict(state={},capture_complete=False);state["holder_diagnostic"]=hd;persist()
                read_segment_chains(holder,"GetHolderProfile",read=read,typed=typed,diagnostic=hd,budget=dict(curves=0,chains=0,islands=0))
                state["holder_profile"]=deepcopy(hd["state"]);persist()
                complete_holder_profile(state["holder_profile"])
                state["nominal_verification"]=observe_holder_nominal(state["holder_profile"],loaded["holder"],25);persist()
            return holder,state
    try:
        loaded=load_shape_change(holder_query_receipt_path=holder_query_receipt_path,
            holder_query_receipt_sha256=holder_query_receipt_sha256,expected_candidate_tool_native_id=expected_candidate_tool_native_id,
            expected_holder_shape_raw=expected_holder_shape_raw,desired_holder_shape=desired_holder_shape,**args)
        _write_receipt(args["receipt_path"],report,create=True);created=True
        baseline=loaded["query"]["after_document"]
        report.update(query_pin=loaded["query_pin"],original_observation_pin=loaded["observation_pin"],
            marker_path=str(loaded["marker"]),before_document=identity(),holder_recipe=loaded["holder"],
            expected_nominal_curve_count=len(loaded["holder"]["records"]))
        files();app=_bootstrap(sw,clsid,typelib_path,args["expected_document_path"]);identity()
        session=CamMessageSession(app,typelib_path)
        with session:
            events();holder,before=snapshot("before")
            if before["holder"]!=loaded["query"]["after_holder"] or before["holder"]["GetHolderShape"]!=expected_holder_shape_raw:
                raise ValueError("Current holder differs from exact compare-and-set expectation")
            report.update(phase="SetHolderShape")
            def pending():
                nonlocal claimed
                _write_receipt(loaded["marker"],dict(scope=SCOPE,status="dispatch_pending",receipt_path=args["receipt_path"],
                    tool_native_id=expected_candidate_tool_native_id,query_pin=loaded["query_pin"],automatic_replay=False),create=True)
                claimed=True;report.update(mutation_attempted=True,setter_attempted=True,native_dispatch_pending=True);persist()
            with guarded() as guard:
                report["native_read_count"]+=2
                if (guard.read(holder,"GetHolderShape")!=expected_holder_shape_raw
                    or guard.read(holder,"GetName")!=before["holder"]["GetName"]):
                    raise ValueError("Holder compare-and-set precondition changed immediately before dispatch")
                result=guard.dispatch_once(lambda:_member(holder,"SetHolderShape",DESIRED_INPUT),persist_pending=pending)
            report.update(native_dispatch_pending=False,native_call_returned=True,setter_return_type=type(result).__name__,
                setter_return_value=result if type(result) in (int,bool,str,float,type(None)) else None);persist()
            if type(result) is not int or not -2**31<=result<2**31:raise ValueError("Strict signed32 HRESULT required")
            report["hresult_succeeded"]=result>=0
            if result<0:raise ValueError("Failed HRESULT; no replay")
            report["phase"]="after";_,after=snapshot("after",with_profile=True)
            observed_mode=after["holder"]["GetHolderShape"]
            report["mode_changed"]=type(observed_mode) is str and bool(observed_mode) and observed_mode!=expected_holder_shape_raw
            report["holder_profile_verified"]=after["nominal_verification"]["native_holder_shape_verified"]
            report["mode_and_profile_verified"]=report["mode_changed"] and report["holder_profile_verified"]
            metadata=("GetHolderId","GetHolderNumber","GetHolderTopDia","GetHolderBottomDia","GetHolderOverallLength","GetHolderBottomLength")
            report["holder_metadata_changes"]={k:dict(before=before["holder"][k],after=after["holder"][k])
                for k in metadata if before["holder"][k]!=after["holder"][k]}
            report["holder_metadata_changes_qualified"]=False
            if (after["holder"]["GetName"]!=before["holder"]["GetName"]
                or after["holder"]["GetProtrusion"]!=before["holder"]["GetProtrusion"]
                or after["tool_parameters"]!=before["tool_parameters"] or after["mt_path_raw"]!=before["mt_path_raw"]):
                raise ValueError("Unexpected shape-selection invariant change")
        events(False);report["after_document"]=identity();files()
        report.update(status="review_required",phase="finished",readback_verified=True,
            reason="SINGLE_HOLDER_SHAPE_RESULT_OBSERVED_FULL_CONTEXT_CHECK_STILL_REQUIRED")
    except Exception as exc:
        report.update(status="uncertain" if report["setter_attempted"] else "error",phase="finished",readback_verified=False,issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain",readback_verified=False,receipt_write_error=_error(exc))
    return report