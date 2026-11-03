"""Regenerate one TURN feature recipe once on an isolated copy, without GTP or Save."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re

from scripts import sw_cam_turn_feature_recipe as recipe
from scripts import sw_cam_operation_profile as profile
from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_configuration_binding import read_nc
from scripts.sw_cam_turn_toolcrib_diagnostic import read_tools
from scripts.sw_cam_turn_feature_attribute import _items
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_checkpoint_exports import local_evidence_root
from scripts.sw_operation_guard import absolute_document_path
from scripts.sw_executable_launch import _process_identity

SCOPE = "TURN_FEATURE_RECIPE_REGENERATION_RAM_V1"
POLICY_KEYS = {"protected_part_pins", "techdb_path", "techdb_sha256", "current_attribute",
    "requested_attribute_id", "feature_spindle_type_raw", "stock_attribute_raw", "feature_diameters_native",
    "expected_operation_ids", "replaced_operation_ids", "expected_new_operation_types",
    "expected_default_operations", "expected_new_tool_signatures"}
EVENT_ERRORS = ("event_count", "overflow", "callback_errors", "callback_error_count", "subscription_error", "disconnect_errors")


def require(value, reason):
    if not value:
        raise ValueError(reason)


def key(path):
    return os.path.normcase(str(Path(path).resolve()))


def sha(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def ids(values, *, maximum=64):
    require(type(values) is list and 0 < len(values) <= maximum, "Bounded nonempty ID list required")
    require(all(type(v) is int and 0 < v <= 4294967295 for v in values) and len(set(values)) == len(values),
            "Strict unique positive IDs required")


def validate(config, policy):
    for field, lo, hi in (("process_id", 1, 2**31-1), ("feature_setup_index", 0, 63),
            ("expected_feature_native_id", 1, 4294967295), ("expected_turn_feature_type", 0, 2147483647),
            ("max_features", 1, 64), ("max_operations", 1, 64)):
        recipe._strict_int(config[field], lo, hi, "Invalid " + field)
    require(profile._number(config["expected_process_create_time"]) > 0, "Exact process creation time required")
    require(type(config["expected_document_path"]) is str and absolute_document_path(config["expected_document_path"])
            and Path(config["expected_document_path"]).suffix.lower() == ".sldprt", "Absolute copy SLDPRT required")
    require(sha(config["expected_source_sha256"]), "Exact source digest required")
    recipe._text(config["attribute_name"], 1000, "Exact requested name required")
    require(type(policy) is dict and set(policy) == POLICY_KEYS, "Exact regeneration policy fields required")
    pins = policy["protected_part_pins"]
    require(type(pins) is list and 1 <= len(pins) <= 16, "Protected source pins required")
    for pin in pins:
        require(type(pin) is dict and set(pin) == {"path", "sha256"} and sha(pin["sha256"])
                and type(pin["path"]) is str and absolute_document_path(pin["path"]), "Exact protected pin required")
    require(any(x["sha256"] == config["expected_source_sha256"] for x in pins), "Pinned original source required")
    require(len({key(x["path"]) for x in pins}) == len(pins), "Duplicate protected pins")
    require(absolute_document_path(policy["techdb_path"]) and sha(policy["techdb_sha256"]), "Exact TechDB pin required")
    current = policy["current_attribute"]
    require(type(current) is dict and set(current) == {"native_id", "name"}, "Exact raw current attribute required")
    recipe._strict_int(current["native_id"], 0, 2147483647, "Invalid current attribute")
    recipe._text(current["name"], 1000, "Invalid current attribute name")
    recipe._strict_int(policy["requested_attribute_id"], 1, 2147483647, "Positive native requested lookup required")
    for field in ("feature_spindle_type_raw", "stock_attribute_raw"):
        recipe._strict_int(policy[field], 0, 2147483647, "Invalid condition raw scalar")
    ds = policy["feature_diameters_native"]
    require(type(ds) is dict and set(ds) == {"minimum", "maximum"}, "Exact diameter values required")
    for value in ds.values(): profile._number(value)
    ids(policy["expected_operation_ids"]); ids(policy["replaced_operation_ids"])
    require(set(policy["replaced_operation_ids"]) < set(policy["expected_operation_ids"]), "Protected operations required")
    kinds = policy["expected_new_operation_types"]
    require(type(kinds) is list and 1 <= len(kinds) <= 16 and all(type(x) is int and 1 <= x <= 16 for x in kinds),
            "Bounded exact new operation type sequence required")
    defaults = policy["expected_default_operations"]
    require(type(defaults) is list and 1 <= len(defaults) <= 16, "Reviewed default-operation preflight required")
    seen = set()
    for row in defaults:
        require(type(row) is dict and set(row) == {"operation_type", "name", "native_id"}, "Exact default lookup required")
        recipe._strict_int(row["operation_type"], 1, 16, "Invalid default operation type")
        recipe._strict_int(row["native_id"], 1, 2147483647, "Invalid default native ID")
        recipe._text(row["name"], 1000, "Invalid default name")
        require(row["operation_type"] not in seen, "Duplicate default operation type"); seen.add(row["operation_type"])
    signatures = policy["expected_new_tool_signatures"]
    require(type(signatures) is list and len(signatures) == len(kinds)
            and all(x is None or type(x) is dict and bool(x) for x in signatures), "One explicit tool signature or unqualified null per new operation required")
    json.dumps(policy, allow_nan=False)


def files(config, policy):
    target = Path(config["expected_document_path"])
    require(target.is_file() and not target.is_symlink(), "Existing regular copy required")
    identity = target.stat()
    require(identity.st_ino != 0, "Stable copy file identity required")
    require(_file_hash(target) == config["expected_source_sha256"], "Copy bytes changed")
    for pin in policy["protected_part_pins"]:
        source = Path(pin["path"])
        require(source.is_file() and not source.is_symlink() and key(source) != key(target)
                and not os.path.samefile(source, target), "Qualification copy aliases a protected source")
        require(_file_hash(source) == pin["sha256"], "Protected source bytes changed")
    require(_file_hash(policy["techdb_path"]) == policy["techdb_sha256"], "TechDB bytes changed")
    return dict(device=identity.st_dev, inode=identity.st_ino)


def marker_path(config, identity):
    # File identity and feature bind every receipt spelling to the same once marker.
    token = _digest(dict(scope=SCOPE, identity=identity, feature=config["expected_feature_native_id"]))
    return local_evidence_root() / ("turn_recipe_" + token + ".json")


def isolated(sw, config, check):
    process = _process_identity(config["process_id"])
    require(process.get("alive") is True and process.get("process_id") == config["process_id"]
            and process.get("create_time") == config["expected_process_create_time"]
            and Path(process.get("executable", "")).name.lower() == "sldworks.exe", "Owned process identity changed")
    require(type(_member(sw, "GetProcessID")) is int and _member(sw, "GetProcessID") == config["process_id"], "Connected process differs")
    check(); documents = _member(sw, "GetDocuments"); check()
    require(type(documents) in (tuple, list) and len(documents) == 1, "Only the qualification copy may be loaded")
    check(); path = _member(documents[0], "GetPathName"); check()
    require(type(path) is str and key(path) == key(config["expected_document_path"]), "Loaded copy identity changed")


def capture(sw, clsid, typelib, config, policy, report, *, clean, check=lambda: None):
    native = {}
    isolated(sw, config, check)
    file_identity = files(config, policy)
    state = recipe._capture(sw, clsid, typelib, config, report, require_clean=clean,
                           check=check, native_out=native, extended_metadata=True)
    require(key(state["techdb_path_raw"]) == key(policy["techdb_path"]), "Active TechDB path differs")
    diagnostic = report["snapshots"][-1]
    def read(obj, name, *args):
        diagnostic["stage"] = name; report["guarded_member_reads"] += 1
        check(); value = _member(obj, name, *args); check(); return value
    typed = lambda obj, name: _typed(obj, name, typelib)
    items = lambda raw, limit: _items(raw, typelib, read, limit=limit)
    own = []
    diagnostic["own_operations"] = own
    for row in state["operations"]:
        ident = row["native_id"]; raw = native["operations"][ident]; op = typed(raw, "ICWOperation")
        item = dict(operation_native_id=ident); own.append(item)
        item["suppressed"] = read(op, "Suppressed")
        require(type(item["suppressed"]) is bool, "Strict suppressed flag required")
        tool = read(op, "IGetTool")
        require(tool is not None and bool(tool), "Each operation must have its own readable tool")
        item["tool_native_id"] = _object_id(native["doc"], tool, read)
        item["tool"] = {}
        profile._read_tool(tool, op, typelib, read, item["tool"], include_drill=True)
    handles = {i: typed(raw, "ICWTurnOperation") for i, raw in native["operations"].items()}
    def publish_nc(rows):
        diagnostic["nc"] = deepcopy(rows)
        require(rows[-1]["status"] == "observed", "Own NC read failed; stop immediately")
    nc = read_nc(list(handles), handles, read=read, typed=typed, publish=publish_nc)
    require(all(row["status"] == "observed" for row in nc), "Own NC read failed; no continuation")
    tools = []; diagnostic["toolcrib"] = tools
    read_tools(native["machine"], native["doc"], read=read, typed=typed, items=items, rows=tools, publish=lambda: None)
    tool_ids = {row["native_id"] for row in tools}
    require(all(row["tool_native_id"] in tool_ids for row in own), "Own tool is absent from current crib")
    defaults = []
    for expected in policy["expected_default_operations"]:
        raw = read(native["turn_feature"], "IGetAllDefaultOperations", expected["operation_type"])
        names = [raw] if type(raw) is str else list(raw) if type(raw) in (list, tuple) else None
        require(names is not None and 0 < len(names) <= 64 and all(type(x) is str and 0 < len(x) <= 1000 for x in names)
                and len(set(names)) == len(names) and expected["name"] in names, "Default catalogue name absent or ambiguous")
        ident = read(native["turn_feature"], "GetTdbIdForDefaultOperation", expected["operation_type"], expected["name"])
        require(type(ident) is int and ident == expected["native_id"], "Default catalogue lookup changed")
        defaults.append(dict(expected, names=names))
    state.update(own_operations=own, nc=nc, toolcrib=tools, default_operations=defaults, copy_file_identity=file_identity)
    require(document_snapshot(sw) == state["document"], "Document changed during extended read")
    require(files(config, policy) == file_identity, "Copy file identity changed during read")
    isolated(sw, config, check)
    return state, native


def preflight(state, config, policy):
    require(state["current_attribute"] == policy["current_attribute"], "Raw current attribute changed")
    require(state["catalog"]["requested_id"] == policy["requested_attribute_id"], "Requested native lookup changed")
    for field in ("feature_spindle_type_raw", "stock_attribute_raw", "feature_diameters_native"):
        require(state[field] == policy[field], "Feature condition changed: " + field)
    require([x["native_id"] for x in state["operations"]] == policy["expected_operation_ids"], "Exact old operation order required")
    linked = [x for x in state["operations"] if config["expected_feature_native_id"] in x["linked_feature_ids"]]
    require([x["native_id"] for x in linked] == policy["replaced_operation_ids"]
            and all(x["linked_feature_ids"] == [config["expected_feature_native_id"]] for x in linked), "Exact exclusively linked operations required")
    require(len({x["setup_index"] for x in linked}) == 1, "Replaced operations must share one setup")
    positions = [state["operations"].index(x) for x in linked]
    require(positions == list(range(positions[0], positions[0]+len(positions))), "Replaced operations must form one contiguous block")


def attribute_expected(before, after, config, policy):
    expected = deepcopy(before)
    require(type(after["document"]["needs_save"]) is bool, "Invalid dirty flag")
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    expected["current_attribute"] = dict(native_id=policy["requested_attribute_id"], name=config["attribute_name"])
    expected["current_attribute_lookup_id_raw"] = policy["requested_attribute_id"]
    expected["current_id_matches_lookup"] = True
    row = next(x for x in expected["features"] if x["native_id"] == config["expected_feature_native_id"])
    row.update(attribute_id_raw=policy["requested_attribute_id"], attribute_name=config["attribute_name"])
    require(expected == after, "Attribute write changed more than the exact target strategy/dirty flag")


def subset(expected, actual):
    if type(expected) is dict:
        return type(actual) is dict and all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    return type(expected) is type(actual) and expected == actual


def verify_delta(before, after, config, policy, *, new_position="replace"):
    require(new_position in ("replace", "append_definitions_only"), "Unknown explicit position policy")
    old_ids = set(policy["expected_operation_ids"]); removed = set(policy["replaced_operation_ids"])
    new = [x for x in after["operations"] if x["native_id"] not in old_ids]
    require([x["turn_operation_type"] for x in new] == policy["expected_new_operation_types"], "New operation types/order differ")
    require(not removed.intersection(x["native_id"] for x in after["operations"]), "Old target operation survived regeneration")
    require(all(x["linked_feature_ids"] == [config["expected_feature_native_id"]] for x in new), "New feature links differ")
    old_block = [x for x in before["operations"] if x["native_id"] in removed]
    require(all(x["setup_index"] == old_block[0]["setup_index"] for x in new), "New operation setup changed")
    expected_ids = policy["expected_operation_ids"][:]
    first = expected_ids.index(policy["replaced_operation_ids"][0])
    expected_ids[first:first+len(removed)] = [x["native_id"] for x in new]
    if new_position == "append_definitions_only":
        expected_ids = [i for i in policy["expected_operation_ids"] if i not in removed] + [x["native_id"] for x in new]
    require([x["native_id"] for x in after["operations"]] == expected_ids, "Protected operation order or insertion position changed")
    require(len({x["native_id"] for x in after["operations"]}) == len(after["operations"]), "Duplicate new operation identity")
    after_own = {x["operation_native_id"]: x for x in after["own_operations"]}
    after_nc = {x["operation_native_id"]: x for x in after["nc"]}
    paths = {(x["setup_index"], x["operation_index"]): x for x in after["inventory"]["operations"]}
    for row, signature in zip(new, policy["expected_new_tool_signatures"]):
        inv = paths[(row["setup_index"], row["operation_index"])]
        require(inv["toolpath_generated"] is False and inv["toolpath_record_counts"] == [], "New toolpath generation was not authorized")
        own = after_own[row["native_id"]]
        require(own["suppressed"] is False and after_nc[row["native_id"]]["status"] == "observed", "New own operation readback incomplete")
        require(signature is None or subset(signature, own["tool"]), "New own tool signature differs")
    # Remove only the target blocks, normalize positional indices, then compare all retained fields.
    normalized = []
    for state, excluded in ((before, removed), (after, {x["native_id"] for x in new})):
        value = deepcopy(state)
        kept = [x for x in value["operations"] if x["native_id"] not in excluded]
        positions = {(x["setup_index"], x["operation_index"]) for x in kept}
        value["inventory"]["operations"] = [x for x in value["inventory"]["operations"] if (x["setup_index"], x["operation_index"]) in positions]
        value["operations"] = kept
        for rows in (kept, value["inventory"]["operations"]):
            counters = {}
            for row in rows:
                si = row["setup_index"]; row["operation_index"] = counters.get(si, 0); counters[si] = row["operation_index"]+1
        value["inventory"]["operation_count"] = len(kept)
        value["own_operations"] = [x for x in value["own_operations"] if x["operation_native_id"] not in excluded]
        value["nc"] = [x for x in value["nc"] if x["operation_native_id"] not in excluded]
        value["document"]["needs_save"] = False
        value.pop("toolcrib")
        normalized.append(value)
    require(normalized[0] == normalized[1], "Protected feature/operation/tool/NC/count metadata changed")
    old_tools = {x["native_id"]: x for x in before["toolcrib"]}
    new_tools = {x["native_id"]: x for x in after["toolcrib"]}
    require(all(new_tools.get(i) == row for i, row in old_tools.items()), "Preexisting toolcrib metadata changed or disappeared")
    additions = set(new_tools)-set(old_tools)
    require(additions <= {after_own[x["native_id"]]["tool_native_id"] for x in new}, "Unexplained new crib entries")
    return dict(new_operations=new, added_tool_ids=sorted(additions), protected_operation_ids=sorted(old_ids-removed))


def qualify_turn_feature_recipe(sw, clsid, typelib_path, *, process_id, expected_process_create_time, expected_document_path,
        expected_source_sha256, feature_setup_index, expected_feature_native_id, expected_turn_feature_type,
        attribute_name, policy, action="prepare", expected_state_sha256=None, receipt_path=None,
        max_features=64, max_operations=64):
    report = dict(scope=SCOPE, status="error", phase="preflight", mutation_attempted=False,
        readback_verified=False, native_recipe_ram_verified=False, native_dispatch_pending=False, model_saved=False, GTP_attempted=False,
        tool_assignment_attempted=False, persistence_verified=False, production_qualified=False,
        full_model_geometry_verified=False, toolpath_coordinates_verified=False, protected_CL_bytes_compared=False, all_nc_parameters_verified=False,
        nc_parameter_scope=["ICWTurnNCParam.GetSpndlSpeed", "ICWTurnNCParam.GetFeedRateIPM"],
        tool_geometry_scope="existing_profile_and_diamond_crib_getters_only",
        document_verification_scope="path_title_type_expected_dirty_flag_and_saved_file_hash",
        snapshots=[], guarded_member_reads=0, actions={})
    session = None; created = False; receipt = None
    def persist():
        if created: _write_receipt(receipt, report)
    try:
        config = dict(process_id=process_id, expected_process_create_time=expected_process_create_time, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, feature_setup_index=feature_setup_index,
            expected_feature_native_id=expected_feature_native_id, expected_turn_feature_type=expected_turn_feature_type,
            attribute_name=attribute_name, max_features=max_features, max_operations=max_operations)
        validate(config, policy); require(action in ("prepare", "apply"), "Only prepare/apply supported")
        require(action != "prepare" or expected_state_sha256 is None and receipt_path is None, "Prepare cannot include apply inputs")
        report["request"] = dict(config, policy=deepcopy(policy), action=action,
                                 expected_state_sha256=expected_state_sha256, receipt_path=receipt_path)
        identity = files(config, policy); marker = marker_path(config, identity)
        require(not marker.exists() and not marker.is_symlink(), "Earlier attempt marker exists; no replay")
        if action == "apply":
            require(sha(expected_state_sha256), "Exact prepared state digest required")
            require(type(receipt_path) is str and absolute_document_path(receipt_path), "Absolute fresh receipt required")
            receipt = Path(receipt_path)
            require(receipt.suffix.lower() == ".json" and receipt.parent.is_dir() and not receipt.exists()
                    and not receipt.is_symlink() and key(receipt) != key(marker), "Fresh nonaliased receipt required")
            _write_receipt(receipt, report, create=True); created = True
        report["phase"] = "event_context"
        isolated(sw, config, lambda: None)
        _, _, _, _, app = recipe._context(sw, clsid, typelib_path, _member)
        session = CamMessageSession(app, typelib_path)
        def check():
            summary = session.summary(); report["messages"] = summary
            require(summary.get("active") is True and summary.get("subscribed") is True
                    and not any(summary.get(x) for x in EVENT_ERRORS), "CAM event requires stop")
        with session:
            report["phase"] = "initial"
            before, native = capture(sw, clsid, typelib_path, config, policy, report, clean=True, check=check)
            report["before"] = before; preflight(before, config, policy)
            report["phase"] = "before_write"
            current, native = capture(sw, clsid, typelib_path, config, policy, report, clean=True, check=check)
            require(current == before, "Prepared state changed during preflight")
            digest = _digest(dict(config=config, policy=policy, state=before))
            report["prepared_state_sha256"] = digest
            if action == "apply":
                require(digest == expected_state_sha256, "Prepared state digest changed")
                report["marker_path"] = str(marker)
                _write_receipt(marker, dict(scope=SCOPE, status="claimed_no_replay", copy_file_identity=identity,
                    feature_native_id=expected_feature_native_id, source_sha256=expected_source_sha256,
                    receipt_path=str(receipt), prepared_state_sha256=digest), create=True)
                def invoke(label, fn):
                    check(); isolated(sw, config, check)
                    require(files(config, policy) == identity, "File identity changed before mutation")
                    report.update(phase=label, mutation_attempted=True, native_dispatch_pending=True)
                    report["actions"][label] = dict(attempted=True, returned=False)
                    persist(); check(); fn()
                    report["actions"][label]["returned"] = True
                    report.update(native_dispatch_pending=False, phase=label+"_returned"); persist(); check()
                invoke("Attribute", lambda: setattr(native["turn_feature"], "Attribute", policy["requested_attribute_id"]))
                after_attribute, native = capture(sw, clsid, typelib_path, config, policy, report, clean=False, check=check)
                report["after_attribute"] = after_attribute; persist()
                attribute_expected(before, after_attribute, config, policy)
                feature = _typed(native["turn_feature"], "ICWFeature", typelib_path)
                invoke("GenerateOpPlan", lambda: _member(feature, "GenerateOpPlan", 2))
                after, _ = capture(sw, clsid, typelib_path, config, policy, report, clean=False, check=check)
                report["after"] = after; persist()
                report["delta"] = verify_delta(after_attribute, after, config, policy)
            else:
                after = current
            check()
        summary = session.summary(); report["messages"] = summary
        require(summary.get("subscribed") is True and summary.get("disconnected") is True and not summary.get("active")
                and not any(summary.get(x) for x in EVENT_ERRORS), "Event cleanup uncertain")
        require(document_snapshot(sw) == after["document"] and files(config, policy) == identity, "Post-cleanup document/file changed")
        isolated(sw, config, lambda: None)
        report.update(status="prepared" if action == "prepare" else "review_required", phase="finished",
            readback_verified=True, final_state=after, final_state_sha256=_digest(after), native_recipe_ram_verified=action == "apply",
            reason="RAM_METADATA_ONLY_COORDINATES_FULL_NC_TOOL_GEOMETRY_AND_PERSISTENCE_UNQUALIFIED")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error", failed_phase=report["phase"],
                      phase="finished", readback_verified=False, native_recipe_ram_verified=False, issue=_error(exc))
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc:
            report.update(status="uncertain" if report["mutation_attempted"] else "error",
                          readback_verified=False, native_recipe_ram_verified=False, receipt_write_error=_error(exc))
    return report
