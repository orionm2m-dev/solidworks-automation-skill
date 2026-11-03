"""One copy-only TURN feature qualification into an exact empty reverse setup.

NULL insertion-anchor semantics are undocumented; this bounded experiment does
not establish general NULL support, coordinate equivalence or machining validity.
"""
from copy import deepcopy
from ctypes import HRESULT, POINTER
from ctypes.wintypes import VARIANT_BOOL
import math
from pathlib import Path

from scripts import sw_cam_turn_reverse_setup as reverse
from scripts import sw_cam_turn_setup_context as frame
from scripts import sw_cam_turn_feature_regenerate as guard
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_operation_profile import _integer, _read_profile, _MAX_SEGMENTS
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_turn_feature_attribute import _items, _inventory
from scripts.sw_cam_turn_holder_dimensions import files
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import absolute_document_path, check_document_target

SCOPE = "TURN_FEATURE_COPY_EMPTY_REVERSE_SETUP_QUALIFICATION_V1"
COPY_KEYS = ("expected_source_feature_native_id", "target_feature_setup_native_id", "target_operation_setup_native_id")
require = guard.require


def validate_request(config, protected_part_pins, action, expected_state_sha256,
                     receipt_path, qualification_only, message_policy):
    for name in ("process_id", "expected_operation_native_id", "expected_feature_setup_native_id",
                 "expected_operation_setup_native_id", *COPY_KEYS):
        require(type(config[name]) is int and 0 < config[name] < 2**32, "Exact native identity required: " + name)
    lifetime=config["expected_process_create_time"]
    require(type(lifetime) in (int,float) and math.isfinite(lifetime) and lifetime>0, "Exact process lifetime required")
    require(type(config["expected_document_path"]) is str and absolute_document_path(config["expected_document_path"])
        and Path(config["expected_document_path"]).suffix.casefold()==".sldprt"
        and guard.sha(config["expected_source_sha256"]), "Exact saved qualification part required")
    for name in ("setup_index", "operation_index"):
        require(type(config[name]) is int and 0 <= config[name] < 512, "Strict bounded operation reference required")
    require(type(config["expected_operation_type"]) is int and config["expected_operation_type"] in (5,6), "Exact bore witness required")
    ids=config["expected_linked_feature_ids"]
    require(type(ids) is list and 1<=len(ids)<=64 and all(type(x) is int and 0<x<2**32 for x in ids)
        and len(set(ids))==len(ids) and config["expected_source_feature_native_id"] in ids, "Source feature must belong to exact witness links")
    frame.validate_config({key:config[key] for key in (*frame._COUNTS,*frame._SETUP_IDS)})
    require(config["expected_feature_setup_count"]==config["expected_operation_setup_count"]==2
        and config["setup_index"]<2 and config["expected_feature_count"]<64, "Exactly two existing setup pairs with feature capacity required")
    require(len({config[name] for name in ("expected_feature_setup_native_id","expected_operation_setup_native_id",
        "target_feature_setup_native_id","target_operation_setup_native_id")})==4, "Original and target setup IDs must be distinct")
    require(type(protected_part_pins) is list and 2<=len(protected_part_pins)<=16, "Protect the original and a separate current archive")
    for pin in protected_part_pins:
        require(type(pin) is dict and set(pin)=={"path","sha256"} and type(pin["path"]) is str
            and absolute_document_path(pin["path"]) and Path(pin["path"]).suffix.casefold()==".sldprt"
            and guard.sha(pin["sha256"]), "Exact protected part pin required")
    require(len({guard.key(x["path"]) for x in protected_part_pins})==len(protected_part_pins), "Duplicate protected paths")
    require(all(guard.key(x["path"])!=guard.key(config["expected_document_path"]) for x in protected_part_pins), "Protected source aliases target")
    require(any(x["sha256"]==config["expected_source_sha256"] for x in protected_part_pins), "Protect an archive of the exact current saved state")
    require(qualification_only is True and message_policy=="vendor_default", "Explicit isolated qualification and default event policy required")
    require(action in ("prepare","apply"), "Only prepare/apply supported")
    if action=="prepare":
        require(expected_state_sha256 is None and receipt_path is None, "Prepare rejects apply guards")
    else:
        require(guard.sha(expected_state_sha256), "Exact prepared digest required")
        require(type(receipt_path) is str and absolute_document_path(receipt_path)
            and Path(receipt_path).suffix.casefold()==".json", "Fresh absolute JSON receipt required")


def copy_abi(typelib_path):
    """Exact current ABI only; accepting a NULL pointer is not a semantic contract."""
    from comtypes.automation import IDispatch
    interface=_interface_class("ICWBaseSetup",typelib_path)
    require(str(interface._iid_).upper()==_INTERFACES["ICWBaseSetup"], "Unexpected setup IID")
    methods=[method for method in interface._methods_ if method.name=="CopyFeatureToThisSetup"]
    require(len(methods)==1, "Unique CopyFeatureToThisSetup signature required")
    method=methods[0]
    require(method.restype is HRESULT and method.idlflags[0]==13
        and method.argtypes==(POINTER(IDispatch),POINTER(IDispatch),VARIANT_BOOL,VARIANT_BOOL,POINTER(VARIANT_BOOL))
        and tuple(x[0] for x in method.paramflags)==(1,1,1,1,10), "Unexpected CopyFeatureToThisSetup ABI")
    frame.setup_abi(typelib_path)


def _profile(doc, raw, setup_id, typelib_path, read, budget):
    item=dict(native_id=_object_id(doc,raw,read),feature_setup_native_id=setup_id,profile={})
    _read_profile(raw,typelib_path,read,budget,item["profile"],
        collection_reader=lambda value,limit:_items(value,typelib_path,read,limit=min(limit,_MAX_SEGMENTS//2)))
    item["spindle_type_raw"]=_integer(read(_typed(raw,"ICWTurnFeature",typelib_path),"GetSpindleType"))
    profile=item["profile"]
    require(type(profile.get("segment_count")) is int and profile["segment_count"]>0
        and len(profile.get("segments",[]))==profile["segment_count"]
        and all(segment.get("curve_type_raw") in (0,1) and segment.get("curve_parameters_available") is True
            for segment in profile["segments"]), "Complete nonempty line/arc profile required")
    return item


def _capture(sw,clsid,typelib_path,config,read,check,identity,*,after=False,diagnostic=None):
    capture_config={key:value for key,value in config.items() if key not in COPY_KEYS}
    if after:capture_config["expected_feature_count"]+=1
    # Preserve two existing setup pairs; the reverse-insertion after mode is not used.
    state,native=reverse._capture(sw,clsid,typelib_path,capture_config,read,check,identity,
        after=False,diagnostic=diagnostic)
    state["capture_complete"]=False
    target_id=config["target_feature_setup_native_id"];source_setup_id=config["expected_feature_setup_native_id"]
    target_rows=[row for row in state["feature_setups"] if row["native_id"]==target_id]
    target_op_rows=[row for row in state["operation_setups"] if row["native_id"]==config["target_operation_setup_native_id"]]
    require(len(target_rows)==len(target_op_rows)==1, "Exact target setup pair absent")
    target_row=target_rows[0];target_op=target_op_rows[0]
    require(target_op["feature_setup_native_id"]==target_id and target_op["operations"]==[], "Target operation setup must remain empty and linked")
    require(len(target_row["feature_native_ids"])==(1 if after else 0), "Target feature setup has unexpected contents")
    require(target_row["frame"]["is_reverse_direction"] is True, "Target must be the observed reverse setup")
    source_row=next(row for row in state["feature_setups"] if row["native_id"]==source_setup_id)
    require(source_row["frame"]["is_reverse_direction"] is False, "Original feature setup must remain forward")
    axes=(source_row["frame"]["axis_native"],target_row["frame"]["axis_native"])
    magnitudes=[math.hypot(*axis) for axis in axes]
    require(all(math.isfinite(x) and x>0 for x in magnitudes) and
        all(abs(a/magnitudes[0]+b/magnitudes[1])<=reverse.AXIS_TOLERANCE for a,b in zip(*axes)),
        "Target axis must be opposite the original direction")
    handles={}
    for row in (source_row,target_row):
        setup=native["feature_handles"][row["native_id"]]
        features=_items(read(setup,"IGetEnumFeatures"),typelib_path,read,limit=64)
        ids=[_object_id(native["doc"],raw,read) for raw in features]
        require(ids==row["feature_native_ids"], "Repeated feature enumeration changed")
        handles.update(zip(ids,features))
    source_id=config["expected_source_feature_native_id"]
    require(source_id in source_row["feature_native_ids"] and source_id in handles, "Source feature moved or absent")
    budget=[0]
    state["source_feature"]=_profile(native["doc"],handles[source_id],source_setup_id,typelib_path,read,budget)
    state["copied_feature"]=None
    if after:
        new_id=target_row["feature_native_ids"][0]
        require(new_id not in source_row["feature_native_ids"], "Target feature is not a distinct copy")
        state["copied_feature"]=_profile(native["doc"],handles[new_id],target_id,typelib_path,read,budget)
    require(identity()==state["document"] and _inventory(native["machine"],typelib_path,read)==state["inventory"],
        "Document or inventory changed while reading profiles")
    check();state["capture_complete"]=True
    native.update(source_feature=_typed(handles[source_id],"ICWFeature",typelib_path),
        target_feature_setup=native["feature_handles"][target_id])
    return state,native


def verify_copy(before,after,config):
    source=before["source_feature"];copied=after["copied_feature"]
    require(copied is not None and copied["native_id"]!=source["native_id"], "Exactly one distinct copied feature required")
    require(copied["feature_setup_native_id"]==config["target_feature_setup_native_id"], "Copy belongs to wrong setup")
    for field in ("feature_type_raw","turn_feature_type_raw","attribute_id_raw","attribute_name","segment_count"):
        require(copied["profile"][field]==source["profile"][field], "Copied feature type/attribute/segment count differs")
    require(copied["spindle_type_raw"]==source["spindle_type_raw"], "Copied feature spindle metadata differs")
    expected=deepcopy(before)
    expected["copied_feature"]=deepcopy(copied)
    expected["inventory"]["feature_count"]+=1
    target=next(row for row in expected["feature_setups"] if row["native_id"]==config["target_feature_setup_native_id"])
    require(target["feature_native_ids"]==[], "Prepared target was not empty")
    target["feature_native_ids"]=[copied["native_id"]]
    expected["inventory"]["feature_counts_by_setup"][target["index"]]+=1
    require(type(after["document"].get("needs_save")) is bool, "Native dirty state must be Boolean")
    expected["document"]["needs_save"]=after["document"]["needs_save"]
    require(expected==after, "Unexpected delta: old features, profile, setups or operations changed")
    return dict(new_feature_native_id=copied["native_id"],target_feature_setup_native_id=target["native_id"],
        original_source_preserved=True,operation_clone_observed=False,
        profile_geometry_equivalence_verified=False,coordinate_frame_verified=False)


def marker_path(identity):
    return local_evidence_root()/("turn_feature_copy_"+_digest(dict(scope=SCOPE,copy_file_identity=identity))+".json")



def qualify_turn_feature_copy(sw, clsid, typelib_path, *, process_id, expected_process_create_time,
        expected_document_path, expected_source_sha256, setup_index, operation_index, expected_operation_type,
        expected_operation_native_id, expected_linked_feature_ids, expected_feature_count, expected_operation_count,
        expected_feature_setup_count, expected_operation_setup_count, expected_generated_operation_count,
        expected_toolpath_record_count, expected_feature_setup_native_id, expected_operation_setup_native_id,
        expected_source_feature_native_id, target_feature_setup_native_id, target_operation_setup_native_id,
        protected_part_pins, qualification_only, message_policy, action="prepare", expected_state_sha256=None, receipt_path=None):
    config = {key: value for key, value in locals().copy().items() if key not in
        ("sw", "clsid", "typelib_path", "protected_part_pins", "qualification_only", "message_policy", "action", "expected_state_sha256", "receipt_path")}
    report = dict(scope=SCOPE, status="error", phase="preflight", mutation_attempted=False,
        native_dispatch_pending=False, native_call_count=0, native_calls_returned_count=0,
        readback_verified=False, apply_eligible=False, model_saved=False, GOP_attempted=False, GTP_attempted=False,
        automatic_retry=False, automatic_rollback=False, feature_movement_attempted=False, operation_creation_attempted=False,
        persistence_verified=False, protected_CL_bytes_compared=False, full_model_geometry_verified=False,
        raw_transform_matrix_preserved=False, coordinate_frame_verified=False, physical_access_qualified=False,
        production_qualified=False, profile_geometry_equivalence_verified=False,
        null_anchor_semantics_qualified=False, feature_copy_attempted=False, captures=[])
    receipt = None; created = False; session = None
    def persist():
        if created: _write_receipt(receipt, report)
    try:
        validate_request(config, protected_part_pins, action, expected_state_sha256, receipt_path, qualification_only, message_policy)
        copy_abi(typelib_path)
        identity_pin = files(config, protected_part_pins); marker = marker_path(identity_pin)
        require(not marker.exists() and not marker.is_symlink(), "Earlier insertion attempt exists; no replay")
        report["request"] = dict(config, protected_part_pins=deepcopy(protected_part_pins), qualification_only=True,
            message_policy=message_policy, action=action)
        if action == "apply":
            receipt = Path(receipt_path)
            require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink()
                and guard.key(receipt) != guard.key(marker), "Fresh nonaliased receipt required")
            _write_receipt(receipt, report, create=True); created = True
        guard.isolated(sw, config, lambda: None)
        session = CamMessageSession(_bootstrap(sw, clsid, typelib_path, expected_document_path), typelib_path)
        def check():
            messages = session.summary(); report["messages"] = messages
            require(messages.get("active") is True and messages.get("subscribed") is True
                and not any(messages.get(key) for key in guard.EVENT_ERRORS), "CAM event requires stop")
        def read(obj, name, *args):
            report["phase"] = name; check(); value = _member(obj, name, *args); check(); return value
        def identity():
            check(); guard.isolated(sw, config, check)
            require(files(config, protected_part_pins) == identity_pin, "Saved or protected file identity changed")
            document = document_snapshot(sw)
            require(document is not None and document.get("type") == 1, "Active saved part required")
            check_document_target(document["path"], document["title"], expected_path=expected_document_path, required=True)
            return document
        def observe(label, after=False):
            report["phase"] = label
            diagnostic = {}
            report["captures"].append(dict(label=label, state=diagnostic))
            try:
                return _capture(sw, clsid, typelib_path, config, read, check, identity, after=after, diagnostic=diagnostic)
            finally: persist()
        with session:
            before, _ = observe("before")
            require(before["document"]["needs_save"] is False, "Initially clean saved copy required")
            confirm, native = observe("confirm_before")
            require(confirm == before, "Two complete initial captures must agree")
            report["before"] = before; current = before
            digest = _digest(dict(scope=SCOPE, config=config, protected_part_pins=protected_part_pins,
                copy_file_identity=identity_pin, state=before))
            report["state_sha256"] = digest
            if action == "apply":
                require(digest == expected_state_sha256, "Prepared source, request or state changed")
                source = native["source_feature"]
                target = native["target_feature_setup"]
                require(_object_id(native["doc"], source, read) == expected_source_feature_native_id
                    and _object_id(native["doc"], target, read) == target_feature_setup_native_id, "Retained source/target changed")
                require(identity() == before["document"], "Document changed before claim")
                report["marker_path"] = str(marker)
                _write_receipt(marker, dict(scope=SCOPE, status="claimed_no_replay", copy_file_identity=identity_pin,
                    source_sha256=expected_source_sha256, state_sha256=digest, receipt_path=str(receipt),
                    source_feature_native_id=expected_source_feature_native_id,
                    target_feature_setup_native_id=target_feature_setup_native_id), create=True)
                report.update(phase="CopyFeatureToThisSetup", mutation_attempted=True, feature_copy_attempted=True,
                    native_dispatch_pending=True, native_call_count=1)
                persist()
                dispatch_state, dispatch_native = observe("dispatch_guard")
                require(dispatch_state == before, "Full original state changed after pending receipt")
                source = dispatch_native["source_feature"]
                target = dispatch_native["target_feature_setup"]
                require(_object_id(dispatch_native["doc"], source, read) == expected_source_feature_native_id
                    and _object_id(dispatch_native["doc"], target, read) == target_feature_setup_native_id, "Fresh source/target changed before dispatch")
                require(identity() == before["document"], "Document changed after pending receipt")
                check()
                # NULL for an empty target is an explicitly bounded qualification,
                # not documented general insertion semantics. Never try alternatives.
                returned = _member(target, "CopyFeatureToThisSetup", source, None, True, False)
                report.update(native_dispatch_pending=False, native_calls_returned_count=1, phase="CopyFeatureToThisSetup_returned",
                    native_return_type=type(returned).__name__, native_return_boolean=returned if type(returned) is bool else None)
                persist(); check()
                require(type(returned) is bool, "CopyFeatureToThisSetup must return a strict Boolean")
                current, _ = observe("after", after=True)
                report["verification"] = verify_copy(before, current, config)
                final, _ = observe("confirm_after", after=True)
                require(final == current, "Two complete post-copy captures must agree")
                verify_copy(before, final, config)
                require(returned is True, "Native copy returned false; no qualification or retry")
                current = final
            report["after"] = current
            require(identity() == current["document"], "Document changed after final capture")
            check()
        messages = session.summary(); report["messages"] = messages
        require(messages.get("subscribed") is True and messages.get("disconnected") is True
            and messages.get("active") is False and not any(messages.get(key) for key in guard.EVENT_ERRORS), "Event cleanup uncertain")
        require(document_snapshot(sw) == current["document"] and files(config, protected_part_pins) == identity_pin,
            "Document or protected files changed after cleanup")
        guard.isolated(sw, config, lambda: None)
        report.update(status="prepared" if action == "prepare" else "review_required", phase="finished",
            readback_verified=action == "apply", apply_eligible=action == "prepare", final_state=current,
            final_state_sha256=_digest(current), reason="RAM_ONLY_FEATURE_COPY_OBSERVED_NULL_ANCHOR_COORDINATES_PERSISTENCE_AND_MACHINING_UNQUALIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error", failed_phase=report["phase"], phase="finished",
            readback_verified=False, apply_eligible=False, issue=_error(exc))
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc:
            report.update(status="uncertain" if report["mutation_attempted"] else "error", readback_verified=False,
                apply_eligible=False, receipt_write_error=_error(exc))
    return report
