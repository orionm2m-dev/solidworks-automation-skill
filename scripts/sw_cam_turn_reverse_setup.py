"""One reverse TURN setup insertion; no generation, Save, retry or rollback."""
from copy import deepcopy
from ctypes import HRESULT, POINTER
from ctypes.wintypes import VARIANT_BOOL
import math
from pathlib import Path

from scripts import sw_cam_turn_feature_regenerate as guard
from scripts import sw_cam_turn_setup_context as frame
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_operation_profile import _integer, _position
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_cam_turn_holder_dimensions import files
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import absolute_document_path, check_document_target

SCOPE = "TURN_REVERSE_SETUP_INSERTION_QUALIFICATION_V1"
AXIS_TOLERANCE = 1e-9
require = guard.require


def validate_request(config, protected_part_pins, action, expected_state_sha256,
                     receipt_path, qualification_only, message_policy):
    for name in ("process_id", "expected_operation_native_id", "expected_feature_setup_native_id",
                 "expected_operation_setup_native_id"):
        require(type(config[name]) is int and 0 < config[name] < 2**32, "Exact native identity required: " + name)
    lifetime = config["expected_process_create_time"]
    require(type(lifetime) in (int, float) and math.isfinite(lifetime) and lifetime > 0, "Exact process lifetime required")
    require(type(config["expected_document_path"]) is str and absolute_document_path(config["expected_document_path"])
        and Path(config["expected_document_path"]).suffix.casefold() == ".sldprt"
        and guard.sha(config["expected_source_sha256"]), "Exact saved qualification part required")
    for name in ("setup_index", "operation_index"):
        require(type(config[name]) is int and 0 <= config[name] < 512, "Strict bounded operation reference required")
    require(type(config["expected_operation_type"]) is int and config["expected_operation_type"] in (5, 6), "Only rough/finish bore witnesses supported")
    ids = config["expected_linked_feature_ids"]
    require(type(ids) is list and 1 <= len(ids) <= 64 and all(type(x) is int and 0 < x < 2**32 for x in ids)
        and len(set(ids)) == len(ids), "Exact unique linked feature IDs required")
    frame.validate_config({key: config[key] for key in (*frame._COUNTS, *frame._SETUP_IDS)})
    require(config["expected_feature_setup_count"] == config["expected_operation_setup_count"] == 1
        and config["setup_index"] == 0, "Qualification starts with exactly one linked setup pair")
    require(type(protected_part_pins) is list and 2 <= len(protected_part_pins) <= 16, "Protect the original and an independent saved archive")
    for pin in protected_part_pins:
        require(type(pin) is dict and set(pin) == {"path", "sha256"} and type(pin["path"]) is str
            and absolute_document_path(pin["path"]) and Path(pin["path"]).suffix.casefold() == ".sldprt"
            and guard.sha(pin["sha256"]), "Exact protected part pin required")
    require(len({guard.key(x["path"]) for x in protected_part_pins}) == len(protected_part_pins), "Duplicate protected paths")
    require(all(guard.key(x["path"]) != guard.key(config["expected_document_path"]) for x in protected_part_pins), "Protected source aliases target")
    require(any(x["sha256"] == config["expected_source_sha256"] for x in protected_part_pins), "An independent archive of the exact saved state is required")
    require(qualification_only is True and message_policy == "vendor_default", "Explicit qualification and default event policy required")
    require(action in ("prepare", "apply"), "Only prepare/apply supported")
    if action == "prepare":
        require(expected_state_sha256 is None and receipt_path is None, "Prepare rejects apply guards")
    else:
        require(guard.sha(expected_state_sha256), "Exact prepared state digest required")
        require(type(receipt_path) is str and absolute_document_path(receipt_path)
            and Path(receipt_path).suffix.casefold() == ".json", "Fresh absolute JSON receipt required")


def insertion_abi(typelib_path):
    """Metadata-only two-IN/one-retval contract; no native activation."""
    from comtypes.automation import IDispatch
    interface = _interface_class("ICWTurnMachine", typelib_path)
    require(str(interface._iid_).upper() == _INTERFACES["ICWTurnMachine"], "Unexpected TURN machine IID")
    methods = [method for method in interface._methods_ if method.name == "InsertTurnSetup1"]
    require(len(methods) == 1, "Unique InsertTurnSetup1 signature required")
    method = methods[0]
    require(method.restype is HRESULT and method.idlflags[0] == 25
        and method.argtypes == (VARIANT_BOOL, POINTER(IDispatch), POINTER(POINTER(IDispatch)))
        and tuple(value[0] for value in method.paramflags) == (1, 1, 10), "Unexpected InsertTurnSetup1 ABI")
    frame.setup_abi(typelib_path)


def _feature_frame(setup, typelib_path, read):
    result = {"axis_native": frame._vector(read(setup, "Axis"))}
    reverse = read(setup, "IsReverseDirection")
    require(type(reverse) is bool, "Native reverse flag must be Boolean")
    result["is_reverse_direction"] = reverse
    position = read(setup, "IGetRefPoint")
    result["reference_point_type"] = frame._metadata(position, read)
    require(result["reference_point_type"]["guid"] == _INTERFACES["ICWPosition"], "Unknown reference point type")
    result["reference_point_native"] = _position(position, typelib_path, read)
    result["xy_transform"] = {}
    frame._transform(setup, typelib_path, read, result["xy_transform"])
    return result


def _operation_frame(setup, typelib_path, read):
    result = {"axis_native": frame._vector(read(setup, "Axis")),
        "origin_in_fcs_native": frame._vector(read(setup, "GetSetupOriginInFCSSpace")), "xy_transform": {}}
    frame._transform(setup, typelib_path, read, result["xy_transform"])
    return result


def _capture(sw, clsid, typelib_path, config, read, check, identity, *, after=False, diagnostic=None):
    """Reuse the qualified inventory/link/frame reader, with independent coherence checks."""
    result = {} if diagnostic is None else diagnostic
    result["capture_complete"] = False
    document = identity()
    result["document"] = document
    _, doc, _, machine, _ = _context(sw, clsid, typelib_path, read)
    inventory = _inventory(machine, typelib_path, read)
    result["inventory"] = inventory
    counts = {key: config[key] for key in (*frame._COUNTS, *frame._SETUP_IDS)}
    if after:
        require(inventory["feature_setup_count"] == 2 and inventory["operation_setup_count"] in (1, 2), "Only one new feature setup and at most one operation setup permitted")
        counts.update(expected_feature_setup_count=2, expected_operation_setup_count=inventory["operation_setup_count"])
    frame.verify_counts(inventory, counts)
    setups = _items(read(machine, "IGetEnumOpSetups"), typelib_path, read, limit=2)
    setup_ids = [_object_id(doc, _typed(raw, "ICWBaseOpSetup", typelib_path), read) for raw in setups]
    require(setup_ids.count(config["expected_operation_setup_native_id"]) == 1, "Pinned original operation setup missing")
    si = setup_ids.index(config["expected_operation_setup_native_id"])
    if not after: require(si == config["setup_index"], "Original operation setup index changed")
    selected_setup = _typed(setups[si], "ICWBaseOpSetup", typelib_path)
    operations = _items(read(selected_setup, "IGetEnumOperations"), typelib_path, read, limit=512)
    oi = config["operation_index"]
    require(oi < len(operations), "Pinned operation absent")
    operation = _typed(operations[oi], "ICWOperation", typelib_path)
    selected = dict(setup_index=si, operation_index=oi, native_id=_object_id(doc, operation, read),
        linked_feature_ids=[_object_id(doc, value, read) for value in _items(read(operation, "IGetAllFeatures"), typelib_path, read, limit=64)])
    require(selected["native_id"] == config["expected_operation_native_id"]
        and sorted(selected["linked_feature_ids"]) == sorted(config["expected_linked_feature_ids"])
        and _integer(read(_typed(operation, "ICWTurnOperation", typelib_path), "OpernType")) == config["expected_operation_type"], "Pinned operation/feature/type changed")
    context = {}
    frame.read_setup_context(doc, machine, setups, si, typelib_path, counts, selected, read, check, context)
    result.update(stock=inventory["stock"], feature_setups=context["feature_setups"],
        operation_setups=context["operation_setups"])
    raw_features = _items(read(machine, "IGetEnumSetups"), typelib_path, read, limit=2)
    require(len(raw_features) == len(result["feature_setups"]), "Repeated feature setup count changed")
    feature_handles = {}
    for raw, row in zip(raw_features, result["feature_setups"]):
        setup = _typed(raw, "ICWBaseSetup", typelib_path)
        require(_object_id(doc, setup, read) == row["native_id"], "Repeated feature setup identity changed")
        feature_handles[row["native_id"]] = setup
        row["frame"] = _feature_frame(setup, typelib_path, read)
    observed = context["selected_setup"]
    original_frame = next(row["frame"] for row in result["feature_setups"] if row["native_id"] == config["expected_feature_setup_native_id"])
    require(original_frame == dict(axis_native=observed["feature_axis_native"], is_reverse_direction=observed["is_reverse_direction"],
        reference_point_type=observed["reference_point_type"], reference_point_native=observed["reference_point_native"],
        xy_transform=observed["feature_xy_transform"]), "Repeated original feature frame changed")
    for raw, row in zip(setups, result["operation_setups"]):
        setup = _typed(raw, "ICWBaseOpSetup", typelib_path)
        require(_object_id(doc, setup, read) == row["native_id"], "Repeated operation setup identity changed")
        row["frame"] = _operation_frame(setup, typelib_path, read)
        raw_ops = _items(read(setup, "IGetEnumOperations"), typelib_path, read, limit=512)
        require(len(raw_ops) == len(row["operations"]), "Repeated operation count changed")
        for raw_op, op in zip(raw_ops, row["operations"]):
            own = _typed(raw_op, "ICWOperation", typelib_path)
            require(_object_id(doc, own, read) == op["native_id"], "Repeated operation native identity changed")
            matching = [item for item in inventory["operations"] if (item["setup_index"], item["operation_index"]) == (row["index"], op["index"])]
            require(len(matching) == 1, "Operation inventory mapping differs")
            op.update({key: value for key, value in matching[0].items() if key not in ("setup_index", "operation_index")})
            op["tool_native_id"] = _object_id(doc, _typed(read(own, "IGetTool"), "ICWTool", typelib_path), read)
            suppressed = read(own, "Suppressed")
            require(type(suppressed) is bool, "Operation suppression must be Boolean")
            op["suppressed"] = suppressed
    original_op_frame = next(row["frame"] for row in result["operation_setups"] if row["native_id"] == config["expected_operation_setup_native_id"])
    require(original_op_frame == dict(axis_native=observed["operation_axis_native"], origin_in_fcs_native=observed["origin_in_fcs_native"],
        xy_transform=observed["operation_xy_transform"]), "Repeated original operation frame changed")
    require(identity() == document and _inventory(machine, typelib_path, read) == inventory, "Document or full inventory changed during capture")
    check(); result["capture_complete"] = True
    return result, dict(doc=doc, machine=machine, feature_handles=feature_handles)


def _without_index(value):
    return {key: deepcopy(item) for key, item in value.items() if key != "index"}


def verify_insertion(before, after, returned_id, anchor_id):
    old = {row["native_id"]: row for row in before["feature_setups"]}
    new = {row["native_id"]: row for row in after["feature_setups"]}
    require(set(new) - set(old) == {returned_id} and set(old) <= set(new), "Returned object must match exactly one additional feature setup")
    require([row["native_id"] for row in after["feature_setups"] if row["native_id"] in old]
        == [row["native_id"] for row in before["feature_setups"]], "Original feature setup order changed")
    for sid, row in old.items(): require(_without_index(new[sid]) == _without_index(row), "Original feature setup changed")
    require([row["native_id"] for row in after["feature_setups"]] == [anchor_id, returned_id], "New feature setup must follow the exact anchor")
    created = new[returned_id]
    require(created["feature_native_ids"] == [], "New feature setup must be empty")
    require(created["frame"]["is_reverse_direction"] is True, "New setup reverse flag is not true")
    original_axis = old[anchor_id]["frame"]["axis_native"]
    new_axis = created["frame"]["axis_native"]
    magnitudes = [math.hypot(*axis) for axis in (original_axis, new_axis)]
    require(all(math.isfinite(value) and value > 0 for value in magnitudes), "Nonzero finite setup axes required")
    require(all(abs(a / magnitudes[0] + b / magnitudes[1]) <= AXIS_TOLERANCE
        for a, b in zip(original_axis, new_axis)), "New setup axis is not opposite the original direction")
    old_ops = {row["native_id"]: row for row in before["operation_setups"]}
    new_ops = {row["native_id"]: row for row in after["operation_setups"]}
    require(set(old_ops) <= set(new_ops) and len(set(new_ops) - set(old_ops)) <= 1, "Unexpected operation setup inventory")
    require([row["native_id"] for row in after["operation_setups"] if row["native_id"] in old_ops]
        == [row["native_id"] for row in before["operation_setups"]], "Original operation setup order changed")
    for sid, row in old_ops.items(): require(_without_index(new_ops[sid]) == _without_index(row), "Original operation setup or operation changed")
    for sid in set(new_ops) - set(old_ops):
        require(new_ops[sid]["operations"] == [] and new_ops[sid]["feature_setup_native_id"] == returned_id,
            "Additional operation setup must be empty and link only the new feature setup")
    require(before["stock"] == after["stock"], "Observed stock type changed")
    first, last = deepcopy(before["document"]), deepcopy(after["document"])
    require(type(last.get("needs_save")) is bool, "Native dirty state must be Boolean")
    first.pop("needs_save", None); last.pop("needs_save", None)
    require(first == last, "Document identity changed")
    return dict(new_feature_setup_native_id=returned_id,
        new_operation_setup_native_ids=sorted(set(new_ops) - set(old_ops)), axis_tolerance=AXIS_TOLERANCE)


def marker_path(identity):
    return local_evidence_root() / ("turn_reverse_setup_" + _digest(dict(scope=SCOPE, copy_file_identity=identity)) + ".json")


def qualify_turn_reverse_setup(sw, clsid, typelib_path, *, process_id, expected_process_create_time,
        expected_document_path, expected_source_sha256, setup_index, operation_index, expected_operation_type,
        expected_operation_native_id, expected_linked_feature_ids, expected_feature_count, expected_operation_count,
        expected_feature_setup_count, expected_operation_setup_count, expected_generated_operation_count,
        expected_toolpath_record_count, expected_feature_setup_native_id, expected_operation_setup_native_id,
        protected_part_pins, qualification_only, message_policy, action="prepare", expected_state_sha256=None, receipt_path=None):
    config = {key: value for key, value in locals().copy().items() if key not in
        ("sw", "clsid", "typelib_path", "protected_part_pins", "qualification_only", "message_policy", "action", "expected_state_sha256", "receipt_path")}
    report = dict(scope=SCOPE, status="error", phase="preflight", mutation_attempted=False,
        native_dispatch_pending=False, native_call_count=0, native_calls_returned_count=0,
        readback_verified=False, apply_eligible=False, model_saved=False, GOP_attempted=False, GTP_attempted=False,
        automatic_retry=False, automatic_rollback=False, feature_movement_attempted=False, operation_creation_attempted=False,
        persistence_verified=False, protected_CL_bytes_compared=False, full_model_geometry_verified=False,
        raw_transform_matrix_preserved=False, coordinate_frame_verified=False, physical_access_qualified=False,
        production_qualified=False, captures=[])
    receipt = None; created = False; session = None
    def persist():
        if created: _write_receipt(receipt, report)
    try:
        validate_request(config, protected_part_pins, action, expected_state_sha256, receipt_path, qualification_only, message_policy)
        insertion_abi(typelib_path)
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
            require(before["feature_setups"][0]["frame"]["is_reverse_direction"] is False, "Original setup must have forward direction")
            magnitude = math.hypot(*before["feature_setups"][0]["frame"]["axis_native"])
            require(math.isfinite(magnitude) and magnitude > 0, "Original setup axis must be nonzero and finite")
            confirm, native = observe("confirm_before")
            require(confirm == before, "Two complete initial captures must agree")
            report["before"] = before; current = before
            digest = _digest(dict(scope=SCOPE, config=config, protected_part_pins=protected_part_pins,
                copy_file_identity=identity_pin, state=before))
            report["state_sha256"] = digest
            if action == "apply":
                require(digest == expected_state_sha256, "Prepared source, request or state changed")
                # Resolve only from the independently enumerated FEATURE setups.
                anchor = native["feature_handles"][expected_feature_setup_native_id]
                require(_object_id(native["doc"], anchor, read) == expected_feature_setup_native_id, "Retained feature setup changed")
                machine = _typed(native["machine"], "ICWTurnMachine", typelib_path)
                require(identity() == before["document"], "Document changed before claim")
                report["marker_path"] = str(marker)
                _write_receipt(marker, dict(scope=SCOPE, status="claimed_no_replay", copy_file_identity=identity_pin,
                    source_sha256=expected_source_sha256, state_sha256=digest, receipt_path=str(receipt)), create=True)
                report.update(phase="InsertTurnSetup1", mutation_attempted=True, native_dispatch_pending=True, native_call_count=1)
                persist()
                dispatch_state, dispatch_native = observe("dispatch_guard")
                require(dispatch_state == before, "Full original state changed after pending receipt")
                anchor = dispatch_native["feature_handles"][expected_feature_setup_native_id]
                require(_object_id(dispatch_native["doc"], anchor, read) == expected_feature_setup_native_id, "Fresh feature setup identity changed before dispatch")
                machine = _typed(dispatch_native["machine"], "ICWTurnMachine", typelib_path)
                require(identity() == before["document"], "Document changed after pending receipt")
                check()
                returned = _member(machine, "InsertTurnSetup1", True, anchor)
                report.update(native_dispatch_pending=False, native_calls_returned_count=1, phase="InsertTurnSetup1_returned")
                persist(); check()
                require(returned is not None and bool(returned), "InsertTurnSetup1 returned no setup object")
                returned_setup = _typed(returned, "ICWBaseSetup", typelib_path)
                returned_id = _object_id(native["doc"], returned_setup, read)
                report["returned_feature_setup_native_id"] = returned_id; persist()
                current, _ = observe("after", after=True)
                report["verification"] = verify_insertion(before, current, returned_id, expected_feature_setup_native_id)
                final, _ = observe("confirm_after", after=True)
                require(final == current, "Two complete post-insertion captures must agree")
                verify_insertion(before, final, returned_id, expected_feature_setup_native_id)
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
            final_state_sha256=_digest(current), reason="RAM_ONLY_EMPTY_REVERSE_SETUP_OBSERVED_NO_PERSISTENCE_OR_MACHINING_QUALIFICATION")
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
