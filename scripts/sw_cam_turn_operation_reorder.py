"""Move a reviewed set of existing TURN operations once; no copy, GOP, GTP or Save."""
from copy import deepcopy
import json
from pathlib import Path

from scripts import sw_cam_turn_feature_regenerate as capture
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_turn_feature_attribute import _items
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import absolute_document_path
from scripts.sw_cam_raw_mill_face_move import native_return_observation, require_move_return

SCOPE = "REVIEWED_TURN_OPERATION_REORDER_V1"
require = capture.require
CONFIG_KEYS = ("process_id", "expected_process_create_time", "expected_document_path", "expected_source_sha256",
    "feature_setup_index", "expected_feature_native_id", "expected_turn_feature_type", "attribute_name", "max_features", "max_operations")


def validate(config, policy, plan, expected_metadata_sha256):
    for key, low, high in (("process_id",1,2**31-1),("feature_setup_index",0,63),
            ("expected_feature_native_id",1,2**32-1),("expected_turn_feature_type",0,2**31-1),("max_features",1,64),("max_operations",1,64)):
        capture.recipe._strict_int(config[key],low,high,"Invalid "+key)
    require(type(config["expected_process_create_time"]) in (int,float)
            and capture.profile._number(config["expected_process_create_time"]) > 0,"Exact process creation time required")
    require(type(config["expected_document_path"]) is str and absolute_document_path(config["expected_document_path"])
            and Path(config["expected_document_path"]).suffix.casefold()==".sldprt","Absolute qualification copy required")
    require(capture.sha(config["expected_source_sha256"]) and (expected_metadata_sha256 is None or capture.sha(expected_metadata_sha256)),"Explicit source and reviewed metadata digests required")
    capture.recipe._text(config["attribute_name"],1000,"Exact feature attribute name required")
    require(type(policy) is dict and set(policy)=={"protected_part_pins","techdb_path","techdb_sha256","expected_default_operations"},"Exact capture policy fields required")
    pins=policy["protected_part_pins"]
    require(type(pins)is list and 1<=len(pins)<=16,"Protected original part pins required")
    for pin in pins:
        require(type(pin)is dict and set(pin)=={"path","sha256"} and type(pin["path"])is str
                and absolute_document_path(pin["path"]) and capture.sha(pin["sha256"]),"Exact protected pin required")
    require(len({capture.key(x["path"])for x in pins})==len(pins),"Duplicate protected paths")
    require(type(policy["techdb_path"])is str and absolute_document_path(policy["techdb_path"])
            and capture.sha(policy["techdb_sha256"]),"Exact TechDB pin required")
    defaults=policy["expected_default_operations"]
    require(type(defaults)is list and 1<=len(defaults)<=16,"Reviewed default operation catalog required")
    for row in defaults:
        require(type(row)is dict and set(row)=={"operation_type","name","native_id"},"Exact default operation lookup required")
        capture.recipe._strict_int(row["operation_type"],1,16,"Invalid operation type")
        capture.recipe._strict_int(row["native_id"],1,2**31-1,"Invalid catalog native ID")
        capture.recipe._text(row["name"],1000,"Invalid catalog name")
    require(len({x["operation_type"]for x in defaults})==len(defaults),"Duplicate default operation type")
    require(type(plan)is dict and set(plan)=={"setup_index","expected_operation_ids","expected_final_order","moves"},"Exact reorder plan fields required")
    capture.recipe._strict_int(plan["setup_index"],0,63,"Invalid operation setup index")
    capture.ids(plan["expected_operation_ids"]);capture.ids(plan["expected_final_order"])
    require(set(plan["expected_operation_ids"])==set(plan["expected_final_order"]),"Reorder cannot add or remove operations")
    moves=plan["moves"]
    require(type(moves)is list and 1<=len(moves)<=16,"Bounded explicit move sequence required")
    seen=set();order=plan["expected_operation_ids"][:];stages=[]
    for move in moves:
        require(type(move)is dict and set(move)=={"moving_native_id","after_native_id","make_copy"},"Exact move selectors required")
        moving,anchor=move["moving_native_id"],move["after_native_id"]
        require(type(moving)is int and type(anchor)is int and moving!=anchor and moving in order and anchor in order,"Distinct existing move/anchor IDs required")
        require(moving not in seen and move["make_copy"]is False,"Each operation may be moved once; copies forbidden")
        seen.add(moving);changed=order[:];changed.remove(moving);changed.insert(changed.index(anchor)+1,moving)
        require(changed!=order,"No-op moves are not dispatched")
        stages.append(dict(before_order=order[:],after_order=changed[:],**move));order=changed
    require(order==plan["expected_final_order"],"Move sequence does not produce reviewed final order")
    json.dumps(dict(config=config,policy=policy,plan=plan),allow_nan=False)
    return stages


def _normalized(state):
    """Ignore only operation positions and the observed strict Boolean save flag."""
    result=deepcopy(state)
    require(type(result["document"]["needs_save"])is bool,"Strict observed save flag required")
    result["document"]["needs_save"]=False
    rows=result["operations"];paths=result["inventory"]["operations"]
    require(len(rows)==len(paths)==result["inventory"]["operation_count"],"Complete operation metadata required")
    require(len({x["native_id"]for x in rows})==len(rows),"Duplicate operation identities")
    for row,path in zip(rows,paths):
        require(all(row[key]==path[key]for key in("setup_index","operation_index","turn_operation_type")),"Identity/path order inconsistent")
        path["native_id"]=row["native_id"]
        row.pop("operation_index");path.pop("operation_index")
    result["operations"]=sorted(rows,key=lambda x:x["native_id"])
    result["inventory"]["operations"]=sorted(paths,key=lambda x:x["native_id"])
    expected={x["native_id"]for x in rows}
    for key in("own_operations","nc"):
        values=result[key]
        require(len(values)==len(expected)and {x["operation_native_id"]for x in values}==expected,"Complete unique own tool/NC metadata required")
        result[key]=sorted(values,key=lambda x:x["operation_native_id"])
    return result


def verify_reorder(before,after,expected_order):
    require([row["native_id"]for row in after["operations"]]==expected_order,"Exact intermediate operation order differs")
    require(_normalized(before)==_normalized(after),"Move changed protected operation/feature/tool/NC/path metadata")


def _setups(native,typelib,read):
    raws=_items(read(native["machine"],"IGetEnumOpSetups"),typelib,read,limit=64)
    typed=[_typed(raw,"ICWBaseOpSetup",typelib)for raw in raws]
    ids=[_object_id(native["doc"],raw,read)for raw in typed]
    require(len(ids)==len(set(ids))and all(type(x)is int and x>0 for x in ids),"Distinct native setup identities required")
    return typed,ids


def _resolve(native,typelib,read,setup_index,move,expected_setup_ids):
    from comtypes.automation import IDispatch
    setups,ids=_setups(native,typelib,read)
    require(ids==expected_setup_ids and setup_index<len(setups),"Current setup identity changed")
    dispatch=[]
    for ident in(move["moving_native_id"],move["after_native_id"]):
        op=_typed(native["operations"][ident],"ICWOperation",typelib)
        require(_object_id(native["doc"],op,read)==ident,"Current operation handle identity differs")
        value=read(op,"QueryInterface",IDispatch)
        require(_object_id(native["doc"],value,read)==ident,"Current dispatch identity differs")
        dispatch.append(value)
    return setups[setup_index],dispatch


def marker_path(identity):
    return local_evidence_root()/("turn_reorder_"+_digest(dict(scope=SCOPE,copy_file_identity=identity))+".json")


def reorder_turn_operations(sw,clsid,typelib_path,*,process_id,expected_process_create_time,expected_document_path,
        expected_source_sha256,feature_setup_index,expected_feature_native_id,expected_turn_feature_type,attribute_name,
        policy,plan,expected_metadata_sha256=None,action="prepare",expected_state_sha256=None,receipt_path=None,
        max_features=64,max_operations=64):
    report=dict(scope=SCOPE,status="error",phase="preflight",readback_verified=False,order_verified=False,apply_eligible=False,
        mutation_attempted=False,native_call_attempted=False,native_dispatch_pending=False,move_call_count=0,
        model_saved=False,GOP_attempted=False,GTP_attempted=False,tool_assignment_attempted=False,
        operation_creation_attempted=False,make_copy=False,automatic_retry_permitted=False,
        persistence_verified=False,protected_CL_bytes_compared=False,full_model_geometry_verified=False,
        physical_sequence_qualified=False,production_qualified=False,all_nc_parameters_verified=False,
        nc_parameter_scope=["ICWTurnNCParam.GetSpndlSpeed","ICWTurnNCParam.GetFeedRateIPM"],
        tool_geometry_scope="existing_profile_and_diamond_crib_getters_only",
        document_verification_scope="path_title_type_expected_dirty_flag_and_saved_file_hash",
        snapshots=[],guarded_member_reads=0,actions=[])
    config=dict(process_id=process_id,expected_process_create_time=expected_process_create_time,expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256,feature_setup_index=feature_setup_index,expected_feature_native_id=expected_feature_native_id,
        expected_turn_feature_type=expected_turn_feature_type,attribute_name=attribute_name,max_features=max_features,max_operations=max_operations)
    created=False;receipt=None;session=None;claimed=False
    def persist():
        if created:_write_receipt(receipt,report)
    try:
        stages=validate(config,policy,plan,expected_metadata_sha256)
        require(action in("inspect","prepare","apply"),"Only inspect/prepare/apply supported")
        require((expected_metadata_sha256 is None if action=="inspect" else capture.sha(expected_metadata_sha256)),"Inspect obtains a snapshot; prepare/apply require its reviewed digest")
        require(action=="apply"or expected_state_sha256 is None and receipt_path is None,"Inspect/prepare reject apply inputs")
        report["request"]=dict(config,policy=deepcopy(policy),plan=deepcopy(plan),expected_metadata_sha256=expected_metadata_sha256,
            action=action,expected_state_sha256=expected_state_sha256,receipt_path=receipt_path)
        identity=capture.files(config,policy);marker=marker_path(identity)
        require(not marker.exists()and not marker.is_symlink(),"Earlier reorder attempt exists; no replay")
        if action=="apply":
            require(capture.sha(expected_state_sha256),"Exact prepared digest required")
            require(type(receipt_path)is str and absolute_document_path(receipt_path),"Absolute unused JSON receipt required")
            receipt=Path(receipt_path)
            require(receipt.suffix.casefold()==".json"and receipt.parent.is_dir()and not receipt.exists()and not receipt.is_symlink()
                    and capture.key(receipt)!=capture.key(marker),"Fresh nonaliased receipt required")
            _write_receipt(receipt,report,create=True);created=True
        capture.isolated(sw,config,lambda:None)
        _,_,_,_,app=capture.recipe._context(sw,clsid,typelib_path,_member)
        session=CamMessageSession(app,typelib_path)
        def check():
            value=session.summary();report["messages"]=value
            require(value.get("active")is True and value.get("subscribed")is True
                and not any(value.get(k)for k in capture.EVENT_ERRORS),"CAM event requires stop")
        def read(obj,name,*args):
            report["phase"]=name;check();value=_member(obj,name,*args);check();return value
        def boundary():
            check();capture.isolated(sw,config,check)
            require(capture.files(config,policy)==identity,"Copy/protected file identity changed")
        def observe(label,clean):
            report["phase"]=label
            try:
                state,native=capture.capture(sw,clsid,typelib_path,config,policy,report,clean=clean,check=check)
                _,setup_ids=_setups(native,typelib_path,read)
                return state,native,setup_ids
            finally:persist()
        with session:
            before,native,setup_ids=observe("initial",True);report["before"]=before;report["setup_ids"]=setup_ids
            if action!="inspect":
                require(_digest(before)==expected_metadata_sha256,"Current metadata differs from reviewed saved snapshot")
            require([row["native_id"]for row in before["operations"]]==plan["expected_operation_ids"],"Reviewed initial operation order differs")
            require(before["document"]["needs_save"]is False,"Initially clean saved qualification copy required")
            _normalized(before)
            selected={x["native_id"]:x for x in before["operations"]}
            for move in stages:
                require(all(selected[move[key]]["setup_index"]==plan["setup_index"]for key in("moving_native_id","after_native_id")),"Every move and anchor must share the selected setup")
            current,native,current_setups=observe("confirm_initial",True)
            require(current==before and current_setups==setup_ids,"Reviewed metadata changed during preflight")
            digest=_digest(dict(config=config,policy=policy,plan=plan,state=before,setup_ids=setup_ids))
            if action!="inspect":report["prepared_state_sha256"]=digest
            if action=="apply":
                require(digest==expected_state_sha256,"Prepared metadata/plan changed")
                report["marker_path"]=str(marker)
                _write_receipt(marker,dict(scope=SCOPE,status="claimed_no_replay",copy_file_identity=identity,
                    source_sha256=expected_source_sha256,metadata_sha256=expected_metadata_sha256,
                    prepared_state_sha256=digest,receipt_path=str(receipt),plan=plan),create=True);claimed=True
                for index,move in enumerate(stages):
                    boundary()
                    require([x["native_id"]for x in current["operations"]]==move["before_order"],"Intermediate order changed before dispatch")
                    setup,dispatch=_resolve(native,typelib_path,read,plan["setup_index"],move,setup_ids)
                    boundary();require(document_snapshot(sw)==current["document"],"Document changed before move")
                    item=dict(index=index,**move,attempted=True,returned=False,readback_verified=False)
                    report["actions"].append(item)
                    report.update(phase="InsertOperationAfter",mutation_attempted=True,native_call_attempted=True,
                        native_dispatch_pending=True,move_call_count=index+1)
                    persist();boundary()
                    returned=_member(setup,"InsertOperationAfter",dispatch[0],dispatch[1],False)
                    item.update(returned=True,**native_return_observation(returned))
                    report.update(native_dispatch_pending=False,phase="InsertOperationAfter_returned");persist()
                    require_move_return(returned);check()
                    after,native,after_setups=observe("after_move_"+str(index),False)
                    item["after"]=after;persist()
                    require(after_setups==setup_ids,"Setup identity changed during move")
                    verify_reorder(before,after,move["after_order"])
                    item["readback_verified"]=True;current=after;persist()
            report["after"]=current;check()
        value=session.summary();report["messages"]=value
        require(value.get("subscribed")is True and value.get("disconnected")is True and value.get("active")is False
            and not any(value.get(k)for k in capture.EVENT_ERRORS),"CAM event cleanup uncertain")
        require(document_snapshot(sw)==current["document"] and capture.files(config,policy)==identity,"Post-cleanup document/files changed")
        capture.isolated(sw,config,lambda:None)
        report.update(status="inspected"if action=="inspect"else"prepared"if action=="prepare"else"review_required",phase="finished",readback_verified=True,
            order_verified=action=="apply",apply_eligible=action=="prepare",final_state=current,final_state_sha256=_digest(current),
            reason="ORDER_METADATA_ONLY_FULL_CL_PERSISTENCE_AND_PHYSICAL_SEQUENCE_UNQUALIFIED")
    except Exception as exc:
        report.update(status="uncertain"if report["mutation_attempted"]else"error",failed_phase=report["phase"],phase="finished",
            readback_verified=False,order_verified=False,apply_eligible=False,issue=_error(exc))
    finally:
        if session is not None:report["messages"]=session.summary()
        try:persist()
        except Exception as exc:report.update(status="uncertain"if report["mutation_attempted"]else"error",readback_verified=False,order_verified=False,apply_eligible=False,receipt_write_error=_error(exc))
    return report
