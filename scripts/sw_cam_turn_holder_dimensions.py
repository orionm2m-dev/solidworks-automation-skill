"""Bounded in-place dimensions for an existing TURN diamond boring-bar holder.

Only BoringBarDiameter, ShankLength and LeadAngle are writable. No tool rebinding,
creation, generation, Save or retry. Equal catalogue IDs do not prove COM identity.
"""
from copy import deepcopy
from pathlib import Path
import math
import os

from scripts import sw_cam_turn_tool as single
from scripts import sw_cam_turn_feature_regenerate as guard
from scripts import sw_cam_operation_profile as profile
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_toolcrib_diagnostic import read_tools
from scripts.sw_cam_turn_feature_attribute import _context, _items
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import absolute_document_path

SCOPE = "TURN_DIAMOND_BORING_HOLDER_DIMENSIONS_V1"
FIELDS = frozenset({"BoringBarDiameter", "ShankLength", "LeadAngle"})
COMMON = ("ShankLength", "LeadAngle", "BackClearAngle", "FrontClearAngle", "ZInsertOffset", "XInsertOffset", "Protrusion")
require = guard.require


def validate(config, values, protected):
    for key in ("process_id", "expected_operation_native_id", "expected_tool_native_id"):
        require(type(config[key]) is int and 0 < config[key] < 2**32, "Strict native identity required: " + key)
    require(type(config["expected_holder_id"]) is int and 0 <= config["expected_holder_id"] < 2**31, "Exact holder catalogue ID required")
    single._reference({k:config[k] for k in ("setup_index", "operation_index", "expected_operation_type")})
    require(config["expected_operation_type"] in (5, 6), "Only TURN rough/finish bore operations supported")
    require(type(config["expected_process_create_time"]) in (int,float) and math.isfinite(config["expected_process_create_time"])
        and config["expected_process_create_time"] > 0, "Exact process lifetime required")
    require(type(config["expected_document_path"]) is str and absolute_document_path(config["expected_document_path"])
        and Path(config["expected_document_path"]).suffix.casefold() == ".sldprt" and guard.sha(config["expected_source_sha256"]), "Exact saved copy pin required")
    require(type(values) is dict and 1 <= len(values) <= 3 and set(values) <= FIELDS, "Only three documented holder dimensions supported")
    result = {}
    for field in sorted(values):
        value = profile._number(values[field])
        require(field == "LeadAngle" or value > 0, "Bar diameter and length must be positive")
        result[field] = value
    require(type(protected) is list and 1 <= len(protected) <= 16, "Protected original part pins required")
    for pin in protected:
        require(type(pin) is dict and set(pin) == {"path", "sha256"} and type(pin["path"]) is str
            and absolute_document_path(pin["path"]) and guard.sha(pin["sha256"]), "Exact protected pin required")
    require(len({guard.key(x["path"]) for x in protected}) == len(protected), "Duplicate protected paths")
    return result


def files(config, protected):
    target = Path(config["expected_document_path"])
    require(target.is_file() and not target.is_symlink() and _file_hash(target) == config["expected_source_sha256"], "Saved copy changed")
    stat = target.stat(); require(stat.st_ino != 0, "Stable copy file identity required")
    for pin in protected:
        path = Path(pin["path"])
        require(path.is_file() and not path.is_symlink() and guard.key(path) != guard.key(target)
            and not os.path.samefile(path,target), "Copy aliases protected source")
        require(_file_hash(path) == pin["sha256"], "Protected source changed")
    return dict(device=stat.st_dev,inode=stat.st_ino)


def _holder_dimensions(holder, kind, read):
    if kind not in (1,2):
        return dict(available=False,reason="unsupported_holder_kind")
    values = {k:profile._number(read(holder,k)) for k in COMMON}
    values["HolderShape"] = profile._integer(read(holder,"HolderShape"))
    values["GetHolderThickness"] = profile._number(read(holder,"GetHolderThickness"))
    field = "BoringBarDiameter" if kind == 2 else "ShankWidth"
    values[field] = profile._number(read(holder,field))
    return dict(available=True,dimensions_native=values)


def snapshot(sw, clsid, typelib, config, report, check):
    selected = {k:config[k] for k in ("setup_index","operation_index","expected_operation_type")}
    diagnostic = {}; report["snapshot_diagnostics"].append(diagnostic)
    state,native = single._snapshot(sw,clsid,typelib,selected,check=check,diagnostics=diagnostic,guarded_readers=True)
    def read(obj,name,*args):
        check(); value = _member(obj,name,*args); check(); return value
    assignment = next(x for x in state["operation_tools"] if x["operation"] == selected)
    require(assignment["operation_native_id"] == config["expected_operation_native_id"]
        and assignment["tool_native_id"] == config["expected_tool_native_id"], "Selected own operation/tool IDs differ")
    tool = state["selected_tool"]
    require(tool.get("tool_type_raw") == 15 and tool.get("turn_tool_type_raw") == 1 and tool.get("insert_type_raw") == 1
        and tool.get("parameters_status") == "available", "Only existing TURN diamond insert supported")
    holder = _typed(read(native["turn_tool"],"IGetTurnToolHolder"),"ICWTurnToolHolder",typelib)
    holder_identity = single._identity(holder)
    require(profile._integer(read(holder,"GetHolderType")) == 2 and profile._integer(read(holder,"GetHolderId")) == config["expected_holder_id"], "Exact existing boring holder required")
    _,_,_,machine,_ = _context(sw,clsid,typelib,read)
    rows=[];holders={};identities={}
    diagnostic["holder_inventory_stage"] = "collecting_crib"
    diagnostic["holder_profile_observed"] = deepcopy(tool["holder"])
    diagnostic["holder_crib_rows"] = rows
    diagnostic["retained_own_holder_classification_verified"] = dict(
        holder_type_raw=2,holder_id_raw=config["expected_holder_id"])
    def typed(obj,name):
        result = _typed(obj,name,typelib)
        if name == "ICWTurnToolHolder":
            ident=rows[-1]["native_id"];holders[ident]=result;identities[ident]=single._identity(result)
        return result
    read_tools(machine,native["native_doc"],read=read,typed=typed,
        items=lambda raw,limit:_items(raw,typelib,read,limit=limit),rows=rows,publish=lambda:None)
    target = config["expected_tool_native_id"]
    # These groups are local comparison labels, never native IDs or storage proof.
    group_identities=[holder_identity];group_rows=[]
    for ident,canonical in sorted(identities.items()):
        group=next((i for i,value in enumerate(group_identities) if canonical == value),None)
        if group is None:
            group=len(group_identities);group_identities.append(canonical)
        group_rows.append(dict(tool_native_id=ident,canonical_identity_group=group))
    diagnostic["holder_identity_observation"] = dict(
        scope="canonical_IUnknown_equality_within_this_snapshot_only",
        selected_tool_native_id=target,own_retained_holder_identity_group=0,
        selected_crib_holder_present=target in holders,
        selected_crib_same_canonical_identity=(identities[target] == holder_identity) if target in identities else None,
        crib_holder_identity_groups=group_rows,
        all_com_references_retained_during_comparison=True,
        scalar_equality_proves_identity=False,storage_independence_verified=False)
    diagnostic["holder_inventory_stage"] = "canonical_identity_guards"
    require(target in holders and identities[target] == holder_identity, "Own holder differs from its current crib holder")
    aliases = sorted(i for i,v in identities.items() if v == holder_identity)
    require(aliases == [target], "Selected holder COM object is shared by different tool IDs")
    catalogue_aliases=[]
    for row in rows:
        ident=row["native_id"]
        if ident in holders:
            row["observed_holder"] = _holder_dimensions(holders[ident],row["holder_type_raw"],read)
            if ident != target and (row["holder_type_raw"],row["holder_id_raw"]) == (2,config["expected_holder_id"]):
                catalogue_aliases.append(ident)
    require({x["cam_object_id"] for x in state["tool_groups"]} <= {x["native_id"] for x in rows}, "Assigned tool absent from current crib")
    own_row=next(x for x in rows if x["native_id"] == target)
    require(own_row.get("candidate") is True, "Selected crib row is not a diamond boring holder")
    require(own_row["insert_dimensions_native"] == state["selected_tool"]["dimensions_native"], "Own insert/crib dimensions differ")
    require(all(state["selected_tool"]["holder"]["dimensions_native"].get(k) == v
        for k,v in own_row["observed_holder"]["dimensions_native"].items() if k != "HolderShape"), "Own holder/crib dimensions differ")
    require(state["selected_tool"]["holder"]["shape_raw"] == own_row["observed_holder"]["dimensions_native"]["HolderShape"], "Own holder/crib shape differs")
    state["toolcrib"] = rows
    state["holder_alias_observation"] = dict(selected_same_com_tool_ids=aliases,
        equal_catalogue_other_tool_ids=sorted(catalogue_aliases),catalogue_alias_storage_independence_verified=False,
        excluded_tool_ids=[r["native_id"] for r in rows if r["native_id"] not in holders],all_holder_sharing_qualified=False)
    native.update(holder=holder,holder_identity=holder_identity,held_crib_holders=holders,held_crib_identities=identities)
    require(document_snapshot(sw) == state["document"], "Document changed during holder inventory")
    diagnostic["holder_inventory_stage"] = "complete"
    return state,native


def verify_changes(before, after, changes, tool_id):
    expected=deepcopy(before)
    require(type(after["document"]["needs_save"]) is bool, "Strict observed save flag required")
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    expected["selected_tool"]["info_raw"] = after["selected_tool"]["info_raw"]
    row=next(x for x in expected["toolcrib"] if x["native_id"] == tool_id)
    actual=next(x for x in after["toolcrib"] if x["native_id"] == tool_id)
    row["info_raw"] = actual["info_raw"]
    for field,value in changes.items():
        expected["selected_tool"]["holder"]["dimensions_native"][field] = value
        row["holder_dimensions_native"][field] = value
        row["observed_holder"]["dimensions_native"][field] = value
    require(expected == after, "Holder write changed more than explicitly requested scalar fields")


def marker_path(identity, tool_id):
    return local_evidence_root()/("turn_holder_dimensions_"+single._digest(dict(scope=SCOPE,copy_file_identity=identity,tool_native_id=tool_id))+".json")


def configure_turn_holder_dimensions(sw,clsid,typelib_path,*,process_id,expected_process_create_time,expected_document_path,
        expected_source_sha256,setup_index,operation_index,expected_operation_type,expected_operation_native_id,expected_tool_native_id,
        expected_holder_id,protected_part_pins,values_native,action="prepare",expected_state_sha256=None,
        allowed_affected_operations=None,receipt_path=None,qualification_only,message_policy):
    config=dict(process_id=process_id,expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,setup_index=setup_index,operation_index=operation_index,
        expected_operation_type=expected_operation_type,expected_operation_native_id=expected_operation_native_id,
        expected_tool_native_id=expected_tool_native_id,expected_holder_id=expected_holder_id)
    report=dict(scope=SCOPE,status="error",phase="preflight",readback_verified=False,apply_eligible=False,mutation_attempted=False,
        native_dispatch_pending=False,native_calls_returned_count=0,model_saved=False,GOP_attempted=False,GTP_attempted=False,
        tool_assignment_attempted=False,automatic_retry=False,automatic_rollback=False,physical_tool_qualified=False,
        native_units_verified=False,all_holder_sharing_qualified=False,storage_independence_verified=False,
        protected_CL_bytes_compared=False,all_nc_parameters_verified=False,full_model_geometry_verified=False,persistence_verified=False,production_qualified=False,
        setters=[],snapshot_diagnostics=[])
    session=None;receipt=None;created=False
    def persist():
        if created:_write_receipt(receipt,report)
    try:
        values=validate(config,values_native,protected_part_pins)
        require(qualification_only is True and message_policy == "vendor_default", "Explicit qualification/default-message policy required")
        require(action in ("prepare","apply"), "Only prepare/apply supported")
        require(action == "apply" or all(v is None for v in (expected_state_sha256,allowed_affected_operations,receipt_path)), "Prepare rejects apply inputs")
        identity=files(config,protected_part_pins);marker=marker_path(identity,expected_tool_native_id)
        require(not marker.exists() and not marker.is_symlink(), "Earlier holder attempt exists; no replay")
        if action == "apply":
            require(guard.sha(expected_state_sha256), "Exact prepared state required")
            require(type(allowed_affected_operations) is list and 1 <= len(allowed_affected_operations) <= 512, "Exact shared-operation references required")
            refs=[single._reference(x) for x in allowed_affected_operations]
            require(len({single._ref_key(x) for x in refs}) == len(refs), "Duplicate shared-operation reference")
            require(type(receipt_path) is str and absolute_document_path(receipt_path), "Fresh absolute JSON receipt required")
            receipt=Path(receipt_path)
            require(receipt.suffix.casefold() == ".json" and receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink()
                and guard.key(receipt) != guard.key(marker), "Fresh nonaliased receipt required")
            _write_receipt(receipt,report,create=True);created=True
        report["request"]=dict(config,protected_part_pins=deepcopy(protected_part_pins),values_native=values,action=action)
        guard.isolated(sw,config,lambda:None)
        app=_bootstrap(sw,clsid,typelib_path,expected_document_path);session=CamMessageSession(app,typelib_path)
        def check():
            m=session.summary();report["messages"]=m
            require(m.get("subscribed") is True and m.get("active") is True and not any(m.get(k) for k in guard.EVENT_ERRORS), "CAM event requires stop")
        def boundary(reference=None):
            check();guard.isolated(sw,config,check)
            require(files(config,protected_part_pins) == identity,"Copy/protected file identity changed")
            if reference is not None:require(document_snapshot(sw) == reference,"Document changed before holder write")
        with session:
            boundary();report["phase"]="before"
            before,native=snapshot(sw,clsid,typelib_path,config,report,check);original_native=native
            require(before["document"]["needs_save"] is False,"Initially clean saved qualification copy required")
            report["before"]=before;boundary(before["document"])
            affected=before["affected_operations"];generated=[x for x in before["inventory"]["operations"] if x["toolpath_generated"]
                and any((x["setup_index"],x["operation_index"]) == (r["setup_index"],r["operation_index"]) for r in affected)]
            old=before["selected_tool"]["holder"]["dimensions_native"]
            changes={k:v for k,v in values.items() if old[k] != v}
            digest=single._digest(dict(config=config,protected_part_pins=protected_part_pins,values_native=values,state=before))
            report.update(state_sha256=digest,affected_operations=affected,affected_generated_operations=generated,
                changed_fields=list(changes),no_changes_required=not changes)
            current=before;applied={}
            if action == "apply":
                require(digest == expected_state_sha256,"Prepared holder state/recipe changed")
                require(sorted(refs,key=single._ref_key) == sorted(affected,key=single._ref_key),"All and only sharing operations must be explicitly allowed")
                require(not generated and bool(changes),"Generated sharing or no-op recipe forbids holder writes")
                report["marker_path"]=str(marker)
                _write_receipt(marker,dict(scope=SCOPE,status="claimed_no_replay",copy_file_identity=identity,
                    tool_native_id=expected_tool_native_id,source_sha256=expected_source_sha256,state_sha256=digest,
                    receipt_path=str(receipt)),create=True)
                for field,value in changes.items():
                    boundary(current["document"])
                    def read(obj,name,*args):
                        check();v=_member(obj,name,*args);check();return v
                    require(_object_id(native["native_doc"],native["operation"],read) == expected_operation_native_id,"Selected operation changed")
                    tool=_typed(read(native["operation"],"IGetTool"),"ICWTool",typelib_path)
                    require(_object_id(native["native_doc"],tool,read) == expected_tool_native_id,"Own tool assignment changed")
                    turn=_typed(tool,"ICWTurnTool",typelib_path)
                    holder=_typed(read(turn,"IGetTurnToolHolder"),"ICWTurnToolHolder",typelib_path)
                    require(single._identity(holder) == original_native["holder_identity"],"Selected holder COM identity changed before write")
                    require(profile._integer(read(holder,"GetHolderType")) == 2 and profile._integer(read(holder,"GetHolderId")) == expected_holder_id,"Holder classification changed")
                    for key in values:require(profile._number(read(holder,key)) == current["selected_tool"]["holder"]["dimensions_native"][key],"Holder values changed before write")
                    item=dict(field=field,old_value_native=old[field],value_native=value,attempted=True,returned=False,readback_verified=False)
                    report["setters"].append(item);report.update(phase="property_put",mutation_attempted=True,native_dispatch_pending=True);persist();boundary(current["document"])
                    setattr(holder,field,value)
                    item["returned"]=True;report["native_calls_returned_count"]+=1;report.update(native_dispatch_pending=False,phase="property_put_returned");persist();check()
                    observed=profile._number(read(holder,field));item["observed_value_native"]=observed
                    require(observed == value,"Immediate holder scalar readback differs")
                    after,native=snapshot(sw,clsid,typelib_path,config,report,check);item["after"]=after;persist()
                    applied[field]=value;verify_changes(before,after,applied,expected_tool_native_id)
                    require(native["holder_identity"] == original_native["holder_identity"],"Holder identity changed during readback")
                    item["readback_verified"]=True;current=after;boundary(current["document"]);persist()
            report["after"]=current;check()
        m=session.summary();report["messages"]=m
        require(m.get("subscribed") is True and m.get("disconnected") is True and m.get("active") is False
            and not any(m.get(k) for k in guard.EVENT_ERRORS),"Event cleanup uncertain")
        require(document_snapshot(sw) == current["document"] and files(config,protected_part_pins) == identity,"Post-cleanup document/source changed")
        guard.isolated(sw,config,lambda:None)
        report.update(status="prepared" if action == "prepare" else "review_required",phase="finished",readback_verified=action == "apply",
            apply_eligible=action == "prepare" and not generated and bool(changes),final_state=current,final_state_sha256=single._digest(current),
            reason="SCALAR_HOLDER_DEFINITION_ONLY_PHYSICAL_ASSEMBLY_UNITS_CL_AND_PERSISTENCE_UNQUALIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],phase="finished",
            readback_verified=False,apply_eligible=False,issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain" if report["mutation_attempted"] else "error",readback_verified=False,apply_eligible=False,receipt_write_error=_error(exc))
    return report
