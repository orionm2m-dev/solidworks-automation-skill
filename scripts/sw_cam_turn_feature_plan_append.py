"""One append-only TURN feature plan; fixed RETAIN preference, no toolpath or Save."""
from copy import deepcopy
from ctypes import HRESULT, c_long
from pathlib import Path
import math

from scripts import sw_cam_turn_feature_copy as copying
from scripts import sw_cam_turn_reverse_setup as reverse
from scripts import sw_cam_turn_setup_context as frame
from scripts import sw_cam_turn_feature_regenerate as guard
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_operation_profile import _read_tool
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_turn_feature_attribute import _items, _inventory
from scripts.sw_cam_turn_holder_dimensions import files
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import check_document_target

SCOPE = "TURN_FEATURE_PLAN_APPEND_RETAIN_QUALIFICATION_V1"
PLAN_KEYS = ("expected_copied_feature_native_id", "expected_copied_feature_sha256", "expected_new_operation_types")
require = guard.require


def validate_request(config, protected_part_pins, action, expected_state_sha256,
                     receipt_path, qualification_only, message_policy):
    copying.validate_request({k:v for k,v in config.items() if k not in PLAN_KEYS},
        protected_part_pins, action, expected_state_sha256, receipt_path, qualification_only, message_policy)
    copied = config["expected_copied_feature_native_id"]
    require(type(copied) is int and 0 < copied < 2**32
        and copied != config["expected_source_feature_native_id"], "Distinct exact copied feature ID required")
    require(guard.sha(config["expected_copied_feature_sha256"]), "Exact copied feature observation digest required")
    kinds = config["expected_new_operation_types"]
    require(type(kinds) is list and 1 <= len(kinds) <= 4
        and all(type(kind) is int and kind in (14,9,5,6) for kind in kinds)
        and len(set(kinds)) == len(kinds), "Explicit distinct reviewed bore plan type sequence required")
    require(config["expected_operation_count"] + len(kinds) <= 512, "Append exceeds bounded operation count")


def gop_abi(typelib_path):
    """Exact HRESULT-only GenerateOpPlan(IN LONG); no Boolean OUT result."""
    interface = _interface_class("ICWFeature", typelib_path)
    require(str(interface._iid_).upper() == _INTERFACES["ICWFeature"], "Unexpected feature IID")
    methods = [method for method in interface._methods_ if method.name == "GenerateOpPlan"]
    require(len(methods) == 1, "Unique GenerateOpPlan signature required")
    method = methods[0]
    require(method.restype is HRESULT and method.idlflags[0] == 3
        and not any(flag in method.idlflags for flag in ("propget", "propput", "propputref"))
        and method.argtypes == (c_long,) and tuple(p[0] for p in method.paramflags) == (1,),
        "Unexpected GenerateOpPlan ABI")
    frame.setup_abi(typelib_path)


def _capture(sw, clsid, typelib_path, config, read, check, identity, *, after=False, diagnostic=None):
    capture_config = {k:v for k,v in config.items() if k not in (*copying.COPY_KEYS, *PLAN_KEYS)}
    if after: capture_config["expected_operation_count"] += len(config["expected_new_operation_types"])
    # Both setup pairs already exist. Keep the exact reverse reader in its non-insertion mode.
    state, native = reverse._capture(sw, clsid, typelib_path, capture_config, read, check, identity,
        after=False, diagnostic=diagnostic)
    state["capture_complete"] = False
    target_id = config["target_feature_setup_native_id"]
    target_rows = [row for row in state["feature_setups"] if row["native_id"] == target_id]
    target_ops = [row for row in state["operation_setups"] if row["native_id"] == config["target_operation_setup_native_id"]]
    require(len(target_rows) == len(target_ops) == 1, "Exact target setup pair absent")
    target, target_op = target_rows[0], target_ops[0]
    copied_id = config["expected_copied_feature_native_id"]
    require(target["feature_native_ids"] == [copied_id], "Target must contain only the exact copied feature")
    require(target_op["feature_setup_native_id"] == target_id and target_op["feature_setup_canonical_identity_equal"] is True,
        "Target operation setup link changed")
    if not after: require(target_op["operations"] == [], "Append requires an empty operation setup")
    source = next(row for row in state["feature_setups"] if row["native_id"] == config["expected_feature_setup_native_id"])
    require(source["frame"]["is_reverse_direction"] is False and target["frame"]["is_reverse_direction"] is True,
        "Forward source and reverse target required")
    axes = source["frame"]["axis_native"], target["frame"]["axis_native"]
    magnitudes = [math.hypot(*axis) for axis in axes]
    require(all(math.isfinite(x) and x > 0 for x in magnitudes)
        and all(abs(a/magnitudes[0] + b/magnitudes[1]) <= reverse.AXIS_TOLERANCE for a,b in zip(*axes)),
        "Target axis must remain opposite the source")
    handles = {}
    for row in (source, target):
        features = _items(read(native["feature_handles"][row["native_id"]], "IGetEnumFeatures"), typelib_path, read, limit=64)
        ids = [_object_id(native["doc"], raw, read) for raw in features]
        require(ids == row["feature_native_ids"], "Repeated feature enumeration changed")
        handles.update(zip(ids, features))
    source_id = config["expected_source_feature_native_id"]
    require(source_id in source["feature_native_ids"], "Source feature moved or absent")
    budget = [0]
    state["source_feature"] = copying._profile(native["doc"], handles[source_id], source["native_id"], typelib_path, read, budget)
    state["copied_feature"] = copying._profile(native["doc"], handles[copied_id], target_id, typelib_path, read, budget)
    source_profile = state["source_feature"]["profile"]
    copied_profile = state["copied_feature"]["profile"]
    require(source_profile["feature_type_raw"] == copied_profile["feature_type_raw"] == 2
        and source_profile["turn_feature_type_raw"] == copied_profile["turn_feature_type_raw"] == 2,
        "Only a TURN internal-profile source and its copied bore feature are supported")
    for field in ("attribute_id_raw", "attribute_name", "segment_count"):
        require(source_profile[field] == copied_profile[field], "Copied/source feature metadata differs")
    require(_digest(state["copied_feature"]) == config["expected_copied_feature_sha256"], "Pinned copied feature profile or attribute changed")
    if not after:
        require(not any(copied_id in op["linked_feature_ids"] for row in state["operation_setups"] for op in row["operations"]),
            "Copied feature already has operations")
    # Read each operation's own tool, avoiding the default-operation or tool-crib catalogs.
    setups = _items(read(native["machine"], "IGetEnumOpSetups"), typelib_path, read, limit=2)
    require(len(setups) == len(state["operation_setups"]), "Own-tool setup count changed")
    for raw_setup, row in zip(setups, state["operation_setups"]):
        setup = _typed(raw_setup, "ICWBaseOpSetup", typelib_path)
        require(_object_id(native["doc"], setup, read) == row["native_id"], "Own-tool setup identity changed")
        operations = _items(read(setup, "IGetEnumOperations"), typelib_path, read, limit=512)
        require(len(operations) == len(row["operations"]), "Own-tool operation count changed")
        for raw, op in zip(operations, row["operations"]):
            own = _typed(raw, "ICWOperation", typelib_path)
            require(_object_id(native["doc"], own, read) == op["native_id"], "Own-tool operation identity changed")
            tool = read(own, "IGetTool")
            require(_object_id(native["doc"], _typed(tool, "ICWTool", typelib_path), read) == op["tool_native_id"], "Own-tool identity changed")
            op["observed_own_tool"] = _read_tool(tool, own, typelib_path, read, include_drill=True)
    require(identity() == state["document"] and _inventory(native["machine"], typelib_path, read) == state["inventory"],
        "Document or inventory changed during bounded profile/tool reads")
    check(); state["capture_complete"] = True
    native["copied_feature"] = _typed(handles[copied_id], "ICWFeature", typelib_path)
    return state, native


def verify_append(before, after, config):
    target_id = config["target_operation_setup_native_id"]
    target = next(row for row in after["operation_setups"] if row["native_id"] == target_id)
    created = target["operations"]
    kinds = config["expected_new_operation_types"]
    require([op["turn_operation_type"] for op in created] == kinds, "New operation types or order differ from reviewed sequence")
    old_ids = {op["native_id"] for row in before["operation_setups"] for op in row["operations"]}
    require(len({op["native_id"] for op in created}) == len(kinds)
        and all(op["native_id"] not in old_ids for op in created), "New plan must have distinct new operation IDs")
    require(all(op["linked_feature_ids"] == [config["expected_copied_feature_native_id"]]
        and op["toolpath_generated"] is False and op["toolpath_record_counts"] == []
        and op["suppressed"] is False for op in created), "New plan links, suppression or generated paths differ")
    expected = deepcopy(before)
    expected_target = next(row for row in expected["operation_setups"] if row["native_id"] == target_id)
    require(expected_target["operations"] == [], "Prepared operation setup was not empty")
    expected_target["operations"] = deepcopy(created)
    expected["inventory"]["operation_count"] += len(kinds)
    new_inventory = [row for row in after["inventory"]["operations"] if row["setup_index"] == target["index"]]
    require(len(new_inventory) == len(kinds), "Appended inventory differs")
    expected["inventory"]["operations"].extend(deepcopy(new_inventory))
    expected["inventory"]["operations"].sort(key=lambda row:(row["setup_index"], row["operation_index"]))
    require(type(after["document"].get("needs_save")) is bool, "Native dirty state must be Boolean")
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    require(expected == after, "Unexpected delta in old operations, observed tools, source/copied profiles, stock or setup metadata")
    return dict(new_operation_native_ids=[op["native_id"] for op in created], new_operation_types=kinds,
        copied_feature_native_id=config["expected_copied_feature_native_id"], observed_old_operation_fields_preserved=True,
        source_and_copied_profiles_preserved=True, observed_own_tool_scalars_preserved=True,
        all_feature_profiles_preserved=False, tool_holder_content_preserved=False, toolpath_coordinates_preserved=False)


def marker_path(identity, feature_id):
    return local_evidence_root() / ("turn_feature_plan_append_" + _digest(dict(scope=SCOPE,
        copy_file_identity=identity, copied_feature_native_id=feature_id)) + ".json")


def qualify_turn_feature_plan_append(sw, clsid, typelib_path, *, process_id, expected_process_create_time,
        expected_document_path, expected_source_sha256, setup_index, operation_index, expected_operation_type,
        expected_operation_native_id, expected_linked_feature_ids, expected_feature_count, expected_operation_count,
        expected_feature_setup_count, expected_operation_setup_count, expected_generated_operation_count,
        expected_toolpath_record_count, expected_feature_setup_native_id, expected_operation_setup_native_id,
        expected_source_feature_native_id, target_feature_setup_native_id, target_operation_setup_native_id,
        expected_copied_feature_native_id, expected_copied_feature_sha256, expected_new_operation_types,
        protected_part_pins, qualification_only, message_policy, action="prepare", expected_state_sha256=None, receipt_path=None):
    config = {key: value for key, value in locals().copy().items() if key not in
        ("sw", "clsid", "typelib_path", "protected_part_pins", "qualification_only", "message_policy", "action", "expected_state_sha256", "receipt_path")}
    report = dict(scope=SCOPE, status="error", phase="preflight", mutation_attempted=False,
        native_dispatch_pending=False, native_call_count=0, native_calls_returned_count=0,
        receipt_created=False, receipt_path=None,
        readback_verified=False, apply_eligible=False, model_saved=False, GOP_attempted=False, GTP_attempted=False,
        automatic_retry=False, automatic_rollback=False, feature_movement_attempted=False, operation_creation_attempted=False,
        persistence_verified=False, protected_CL_bytes_compared=False, full_model_geometry_verified=False,
        raw_transform_matrix_preserved=False, coordinate_frame_verified=False, physical_access_qualified=False,
        production_qualified=False, profile_geometry_equivalence_verified=False,
        feature_copy_attempted=False, attribute_write_attempted=False,
        tool_holder_content_preserved=False, toolpath_coordinates_preserved=False,
        preservation_scope="source_and_copied_profiles_operation_order_links_observed_tool_scalars_and_path_record_counts", captures=[])
    receipt = None; created = False; session = None
    def persist():
        if created: _write_receipt(receipt, report)
    try:
        validate_request(config, protected_part_pins, action, expected_state_sha256, receipt_path, qualification_only, message_policy)
        gop_abi(typelib_path)
        identity_pin = files(config, protected_part_pins); marker = marker_path(identity_pin, expected_copied_feature_native_id)
        require(not marker.exists() and not marker.is_symlink(), "Earlier feature plan attempt exists; no replay")
        report["request"] = dict(config, protected_part_pins=deepcopy(protected_part_pins), qualification_only=True,
            message_policy=message_policy, action=action)
        if action == "apply":
            receipt = Path(receipt_path)
            require(receipt.parent.is_dir() and not receipt.exists() and not receipt.is_symlink()
                and guard.key(receipt) != guard.key(marker), "Fresh nonaliased receipt required")
            _write_receipt(receipt, report, create=True); created = True
            report.update(receipt_created=True, receipt_path=str(receipt))
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
                feature = native["copied_feature"]
                require(_object_id(native["doc"], feature, read) == expected_copied_feature_native_id,
                    "Retained copied feature changed")
                require(identity() == before["document"], "Document changed before claim")
                report["marker_path"] = str(marker)
                _write_receipt(marker, dict(scope=SCOPE, status="claimed_no_replay", copy_file_identity=identity_pin,
                    source_sha256=expected_source_sha256, state_sha256=digest, receipt_path=str(receipt),
                    copied_feature_native_id=expected_copied_feature_native_id,
                    target_feature_setup_native_id=target_feature_setup_native_id), create=True)
                report.update(phase="GenerateOpPlan", mutation_attempted=True, GOP_attempted=True,
                    operation_creation_attempted=True, native_dispatch_pending=True, native_call_count=1)
                persist()
                dispatch_state, dispatch_native = observe("dispatch_guard")
                require(dispatch_state == before, "Full original state changed after pending receipt")
                feature = dispatch_native["copied_feature"]
                require(_object_id(dispatch_native["doc"], feature, read) == expected_copied_feature_native_id,
                    "Fresh copied feature changed before dispatch")
                require(identity() == before["document"], "Document changed after pending receipt")
                check()
                # HRESULT-only, no OUT arguments: None has no Boolean success meaning.
                returned = _member(feature, "GenerateOpPlan", 1)
                report.update(native_dispatch_pending=False, native_calls_returned_count=1,
                    phase="GenerateOpPlan_returned", native_return_type=type(returned).__name__)
                persist(); check()
                current, _ = observe("after", after=True)
                report["verification"] = verify_append(before, current, config)
                final, _ = observe("confirm_after", after=True)
                require(final == current, "Two complete post-plan captures must agree")
                verify_append(before, final, config)
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
            final_state_sha256=_digest(current), reason="RAM_ONLY_FEATURE_PLAN_APPEND_OBSERVED_NO_TOOLPATH_SAVE_OR_MACHINING_QUALIFICATION")
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

