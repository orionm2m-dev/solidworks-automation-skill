"""Read-only strong/batch/strong qualification of a retained CAM route graph."""
from pathlib import Path
from time import monotonic
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_completed_sandvik_saved import load_saved_sandvik, TARGET_KEYS
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch
from scripts.sw_cam_existing_sandvik import resolve_existing_context
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_sandvik_phase1 import FIELDS, field_equal
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_operation_guard import check_document_target

SCOPE="CAM_ROUTE_READ_BATCH_QUALIFICATION_V1"
HOLDER_MODE_FIELDS=("GetHolderShape", "GetHolderId", "GetName")


def read_qualification_fields(native, *, read, typed, feature_id, operation_id,
        candidate_id, reference_candidate, reference_operation):
    """Same fixed field sequence for both guards; no whole geometry or CL records."""
    from scripts.sw_cam_rough_entry_parameters import bounded_raw_observation
    doc=native["doc"]
    raw=native["operations"][operation_id]
    operation=typed(raw,"ICWOperation")
    mill=typed(raw,"ICWMillOperation")
    oid=_object_id(doc,operation,read)
    kind=read(mill,"OpernType")
    suppressed=read(operation,"Suppressed")
    generated=read(operation,"GetIsToolpathGenerated")
    require(oid==operation_id and type(kind) is int and kind==0 and suppressed is False
        and generated is False,"Exact ungenerated unsuppressed rough operation required")
    links=[_object_id(doc,f,read) for f in _items(read(operation,"IGetAllFeatures"),typed,read,64)]
    require(links==[feature_id],"Selected rough feature link changed")
    assigned=typed(read(operation,"IGetTool"),"ICWTool")
    assigned_id=_object_id(doc,assigned,read)
    require(assigned_id==reference_operation["assigned_tool"]["native_id"]
        and assigned_id!=candidate_id,"Read-only pre-assignment binding changed")
    found=read(doc,"GetCWObjectFromID",1,feature_id)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,
        "Target feature lookup failed")
    require(_object_id(doc,found[0],read)==feature_id,"Target feature ID changed")
    crib=typed(read(native["machine"],"IGetToolcrib"),"ICWToolcrib4")
    indexed=[(_object_id(doc,obj,read),obj) for obj in _items(read(crib,"GetAllTools"),typed,read,128)]
    require([i for i,obj in indexed]==[r["native_id"] for r in reference_candidate["tools"]],
        "Exact existing tool inventory required")
    matches=[obj for i,obj in indexed if i==candidate_id]
    require(len(matches)==1,"Unique candidate tool required")
    tool=typed(matches[0],"ICWTool")
    tool_kind=read(tool,"ToolType")
    require(type(tool_kind) is int and tool_kind==14 and read(tool,"IsMillTool") is True,
        "Exact MILL UD14 candidate required")
    ud=typed(tool,"ICWMillUDTool")
    values={key:read(tool if key in ("CutDiameter","Protrusion") else ud,key) for key,_ in FIELDS}
    require(all(field_equal(key,values[key],value) for key,value in FIELDS),"Candidate scalar changed")
    mt=read(ud,"GetToolName")
    check_document_target(mt,None,expected_path=reference_candidate["tool"]["mt_path_raw"],required=True)
    holder=typed(read(tool,"IGetMillToolHolder"),"ICWMillToolHolder")
    holder_fields={name:read(holder,name) for name in HOLDER_MODE_FIELDS}
    require(all(type(v) is type(reference_candidate["holder_fields"][k])
        and v==reference_candidate["holder_fields"][k] for k,v in holder_fields.items()),
        "Holder mode, ID or path changed")
    rough=typed(raw,"ICWRghMillOp")
    entry={name:bounded_raw_observation(read(rough,name,found[0]))
        for name in ("GetEntryStartPtX","GetEntryStartPtY")}
    return dict(operation_id=oid,operation_type=kind,suppressed=suppressed,
        toolpath_generated=generated,linked_feature_ids=links,assigned_tool_id=assigned_id,
        candidate_tool_id=candidate_id,candidate_type=tool_kind,tool_parameters=values,
        mt_path_raw=mt,holder_mode_fields=holder_fields,entry_returned_raw=entry)


def qualify_route_read_batch(sw, clsid, typelib_path, *, saved_draft_receipt_path,
        saved_draft_receipt_sha256, expected_candidate_tool_native_id, **args):
    from scripts.sw_cam_events import CamMessageSession
    report=dict(schema_version=1,scope=SCOPE,status="error",phase="preflight",
        read_only=True,mutation_attempted=False,setter_attempted=False,save_attempted=False,
        model_saved=False,GTP_attempted=False,GOP_attempted=False,AFR_attempted=False,
        automatic_replay=False,post_cleanup_CAM_getters=False,readback_verified=False,
        batch_qualified=False,snapshot_scope_qualified=False,full_route_snapshot_qualified=False,
        full_geometry_rechecked=False,production_qualified=False,may_continue=False,
        atomic_snapshot=False,transient_active_document_excursion_excluded=False,
        process_id=args.get("process_id"),expected_document_path=args.get("expected_document_path"),
        source_sha256=args.get("expected_source_sha256"),target_elapsed_seconds=120,
        timing_target_is_not_hard_timeout=True,phases=[],observations={})
    report.update({k:args.get(k) for k in TARGET_KEYS})
    started=monotonic();created=False;session=loaded=None
    receipt=args.get("receipt_path");source=args.get("expected_document_path")
    pins=[];anchor=None
    def persist():
        report["elapsed_seconds"]=monotonic()-started
        if created:_write_receipt(receipt,report)
    def files():
        anchor.check_files()
        for pin in pins:
            require(_file_hash(pin["path"])==pin["sha256"],"Qualification evidence changed")
    def identity():
        pid=_member(sw,"GetProcessID")
        require(type(pid) is int and pid==args["process_id"],"Exact owned process changed")
        anchor.check_runtime_identity()
        doc=raw_part_identity(sw)
        check_document_target(doc["path"],doc["title"],expected_path=source,required=True)
        require(doc==loaded["state"]["document"] and _file_hash(source)==args["expected_source_sha256"],
            "Saved clean document identity changed")
        return doc
    def events(active=True):
        state=session.summary();report["messages"]=state
        require(state.get("subscribed") is True and state.get("active") is active
            and (active or state.get("disconnected") is True)
            and not any(state.get(k) for k in ("event_count","overflow","callback_errors",
                "callback_error_count","subscription_error","disconnect_errors")),"CAM events require stop")
    def common():
        return dict(process_id=args["process_id"],expected_document=identity(),
            source_sha256=args["expected_source_sha256"],evidence_pins=anchor.pins+pins,
            verify_evidence=files,verify_owned_process=anchor.check_runtime_identity,check_events=events)
    def strong():return ScopedCamDispatchGuard(sw,typelib_path,**common())
    def units(g):
        return read_document_cam_unit_scope(g.read(sw,"ActiveDoc"),app,
            sw_read=lambda obj,name:g.read(obj,name),cam_read=g.read)
    def observe(g,native):
        calls={"getters":0,"interfaces":0}
        def read(obj,name,*params):calls["getters"]+=1;return g.read(obj,name,*params)
        def typed(obj,name):calls["interfaces"]+=1;return g.typed(obj,name)
        value=read_qualification_fields(native,read=read,typed=typed,
            feature_id=args["target_feature_native_id"],operation_id=args["target_operation_native_id"],
            candidate_id=expected_candidate_tool_native_id,reference_candidate=loaded["payload"],
            reference_operation=next(o for o in loaded["state"]["operations"]
                if o["native_id"]==args["target_operation_native_id"]))
        return value,calls
    try:
        loaded=load_saved_sandvik(saved_draft_receipt_path=saved_draft_receipt_path,
            saved_draft_receipt_sha256=saved_draft_receipt_sha256,
            expected_candidate_tool_native_id=expected_candidate_tool_native_id,**args)
        anchor=loaded["anchor"];pins=list(loaded["pins"])
        for filename in ("sw_cam_route_read_batch_qualification.py","sw_cam_route_read_batch.py",
                "sw_cam_read_batch_guard.py","sw_cam_dispatch_guard.py","sw_cam_rough_entry_parameters.py"):
            path=Path(__file__).parent/filename
            pins.append(dict(path=str(path.resolve()),sha256=_file_hash(path)))
        report.update(saved_draft_pin=loaded["pin"],evidence_pins=pins,
            qualified_snapshot_fields=["target IDs/link/type/suppression/generated flag/assigned tool ID",
                "candidate UD14 type/ID and nine scalar fields/MT path",
                "holder mode/ID/path", "GetEntryStartPtX and Y bounded raw return"],
            binding_method="strong-resolved retained roots plus native IDs and owned SW PID/path",
            reacquired_wrapper_identity_comparison=False)
        _write_receipt(receipt,report,create=True);created=True
        identity();app=_bootstrap(sw,clsid,typelib_path,source);identity()
        session=CamMessageSession(app,typelib_path)
        with session:
            events();report["phase"]="acquire_retained_roots";persist()
            t=monotonic()
            with strong() as g:
                native=resolve_existing_context(app,g.read,g.typed,{"before":loaded["state"]})
                before_units=units(g)
            report["root_acquisition_seconds"]=monotonic()-t
            for label in ("strong_before","batch","strong_after"):
                report["phase"]=label;persist();t=monotonic()
                g=(ScopedCamRouteReadBatch(sw,typelib_path,native_context=native,
                    reference_state=loaded["state"],max_native_calls=200,**common())
                    if label=="batch" else strong())
                try:
                    with g:value,calls=observe(g,native)
                    if label=="batch":g.require_complete()
                finally:
                    report["phases"].append(dict(name=label,elapsed_seconds=monotonic()-t,guard=g.summary()))
                    persist()
                report["phases"][-1]["field_native_calls"]=calls
                report["observations"][label]=value;persist()
            with strong() as g:after_units=units(g)
            require(before_units==after_units,"Global unit scope changed")
            values=report["observations"]
            require(values["strong_before"]==values["batch"]==values["strong_after"],
                "Strong/batch/strong raw observations differ")
            report.update(document_after=identity(),units_before=before_units,units_after=after_units,
                raw_values_equal=True)
            files();events()
        events(active=False);report["document_after_cleanup"]=identity();files()
        report.update(status="observed",phase="finished",readback_verified=True,
            batch_qualified=True,snapshot_scope_qualified=True,
            qualification_limit="Same fixed scalar/raw field subset only; full route snapshot and machining are not qualified")
    except Exception as exc:
        report.update(status="error",failed_phase=report["phase"],phase="finished",issue=_error(exc),
            batch_qualified=False,snapshot_scope_qualified=False,readback_verified=False)
    finally:
        if session is not None:report["messages"]=session.summary()
        report["target_elapsed_seconds_met"]=monotonic()-started<=120
        try:persist()
        except Exception as exc:
            report.update(status="error",receipt_write_error=_error(exc),batch_qualified=False,
                snapshot_scope_qualified=False,readback_verified=False)
    return report
