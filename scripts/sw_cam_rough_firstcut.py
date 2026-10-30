"""One bounded first-cut reference change for a saved, ungenerated rough operation."""
from copy import deepcopy
from pathlib import Path
import hashlib

from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_mill_inventory import validate_inventory_request, _same_inventory
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_selected_plan_context import capture_selected_plan
from scripts.sw_cam_defined_rough_levels import validate_defined_rough, BINDING_KEYS
from scripts.sw_cam_mill_levels import read_mill_level_values, _toolpath_parameters
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_operation_guard import check_document_target

SCOPE = "MILL_ROUGH_FIRSTCUT_STOCK_V1"
FIELD = "first_cut_Z_type_raw"
PARAM_KEYS = (
    "use_setup_definition_for_top_Z", "use_minimum_Z", "adjust_feature_height", FIELD,
    "use_setup_definition_for_bottom_Z", "minimum_Z_native", "start_Z_native",
)
TARGET_KEYS = ("target_feature_native_id", "target_operation_native_id",
               "target_operation_setup_native_id")
PRIMARY_HASHES = {
    "setter": "936ceb16a6edc9c52683408e8b1eba236e0af9ee6e7fff51b9930597d926c947",
    "enum": "635bd6ab4bd3cc7d4e4dc88c78b0c2bfa83298167f2427490009d71a631cd95f",
    "typelib": "359e2d39a970d2362fa1b44750963b9a64e1fa819d2d046e38174affa37eb3c4",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def _strict_settings(value, expected_type):
    require(type(value) is dict and set(value) == {"direct_type", "toolpath_parameters"},
            "Complete direct and parameter observations required")
    require(type(value["direct_type"]) is int and value["direct_type"] == expected_type,
            "Exact direct first-cut enumeration required")
    params = value["toolpath_parameters"]
    require(type(params) is dict and set(params) == set(PARAM_KEYS), "Exact seven fields required")
    decoded = _toolpath_parameters(tuple(params[k] for k in PARAM_KEYS))
    require(decoded == params and type(params[FIELD]) is int and params[FIELD] == expected_type,
            "Direct and aggregate first-cut enumerations differ")
    require(params["use_setup_definition_for_top_Z"] is False,
            "Setup top override must remain disabled")
    return value


def read_firstcut_settings(raw_operation, read, typed):
    """Read documented getter14 and all seven aggregate parameters; no mutations."""
    op3 = typed(raw_operation, "ICWMillOperation3")
    direct = read(op3, "GetTypeOfFirstCutZ")
    require(type(direct) is int and direct in (0, 1, 2), "Known strict first-cut enum required")
    raw = read(op3, "GetToolpathParam")
    param = typed(raw, "ICWToolpathParam")
    result = dict(direct_type=direct,
                  toolpath_parameters=_toolpath_parameters(read(param, "GetToolpathParameters")))
    return _strict_settings(result, direct)


def verify_transition(before, after):
    _strict_settings(before, 1)
    _strict_settings(after, 0)
    expected = deepcopy(before)
    expected["direct_type"] = 0
    expected["toolpath_parameters"][FIELD] = 0
    require(after == expected, "Only the first-cut reference may change")
    return True


def attempt_marker(document_path, source_sha256, operation_id):
    source = Path(document_path).resolve()
    key = _digest(dict(scope=SCOPE, source=str(source).casefold(), sha256=source_sha256,
                       operation=operation_id, from_value=1, to_value=0))
    return source.parent / ("firstcut_attempt_" + key + ".json")


def load_primary_contract(path, sha256):
    data, pin = read_pin(path, sha256)
    require(data.get("scope") == "FIRSTCUT_PRIMARY_BINDING_V1", "Exact primary contract required")
    require(data.get("setter") == dict(interface="ICWMillOperation3",
        member="SetTypeOfFirstCutZ", dispid=15, argument=0, **{"return": "HRESULT_no_out"}),
        "Exact reviewed setter required")
    require(data.get("getter") == dict(member="GetTypeOfFirstCutZ", dispid=14),
            "Exact reviewed getter required")
    require(data.get("enum_values") == dict(TOP_OF_STOCK=0, TOP_OF_FEATURE=1, USER_DEFINED=2),
            "Reviewed enum mapping required")
    pins = [pin]
    require(set(data["sources"]) == set(PRIMARY_HASHES), "Exact primary source set required")
    for name, digest in PRIMARY_HASHES.items():
        source = data["sources"][name]
        p = Path(source["path"])
        require(source["sha256"] == digest and p.is_absolute() and p.is_file()
                and not p.is_symlink() and _file_hash(p) == digest,
                "Primary source identity changed: " + name)
        pins.append(dict(path=str(p.resolve()), sha256=digest))
    return pins


def _bindings(report, values):
    require(type(report.get("process_id")) is int and report["process_id"] == values["process_id"],
            "Exact recorded process required")
    for key in TARGET_KEYS:
        require(type(report.get(key)) is int and report[key] == values[key], "Exact target ID required")
    require(report.get("saved_file_sha256") == values["expected_source_sha256"],
            "Exact unchanged saved source required")
    for phase in ("before", "after"):
        state = report[phase]
        require(state["saved_file_sha256"] == values["expected_source_sha256"],
                "Phase saved source differs")
        doc = state["document"]
        require(type(doc.get("needs_save")) is bool and type(doc.get("type")) is int
                and doc["type"] == 1, "Strict part identity required")
        check_document_target(doc["path"], doc["title"],
                              expected_path=values["expected_document_path"], required=True)


def load_levels_anchor(path, sha256, *, anchor, bindings):
    report, pin = read_pin(path, sha256)
    require(report.get("scope") == "MILL_DEFINED_ROUGH_LEVELS_V1"
            and report.get("phase") == "finished" and report.get("readback_verified") is True
            and report.get("levels_read_complete") is True and report.get("read_only") is True,
            "Completed stable definition levels required")
    require(report.get("native_dispatch_pending") is False
            and all(report.get(k) is False for k in ("mutation_attempted", "save_attempted",
                "GTP_attempted", "GOP_attempted", "AFR_attempted", "tool_edit_attempted")),
            "Levels anchor must have no native mutation")
    clean_events(report)
    _bindings(report, bindings)
    for phase in ("before", "after"):
        anchor.verify(report[phase])
    require(_same_inventory(report["before"], report["after"])
            and report["before_details"] == report["after_details"], "Unstable levels anchor")
    observed = report["before_details"]["levels_observation"]
    require(report["levels"] == observed["levels"] and report["setup"] == observed["setup"],
            "Levels summary differs from native observations")
    _strict_settings(dict(direct_type=1, toolpath_parameters=report["levels"]["toolpath_parameters"]), 1)
    require(report["before"]["document"]["needs_save"] is False, "Saved clean initial part required")
    return report, pin


def load_firstcut_receipt(path, sha256, *, process_id, expected_document_path,
        expected_source_sha256, target_feature_native_id, target_operation_native_id,
        target_operation_setup_native_id):
    """Validate the exact completed RAM checkpoint for later read-only preservation."""
    report, _ = read_pin(path, sha256)
    values = dict(process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=expected_source_sha256, target_feature_native_id=target_feature_native_id,
        target_operation_native_id=target_operation_native_id,
        target_operation_setup_native_id=target_operation_setup_native_id)
    require(report.get("scope") == SCOPE and report.get("phase") == "finished"
            and report.get("status") == "review_required" and report.get("readback_verified") is True
            and report.get("setter_returned") is True and report.get("setter_attempted") is True
            and report.get("native_dispatch_pending") is False,
            "Completed exact first-cut checkpoint required")
    require(type(report.get("setter_return_value")) is int and report["setter_return_value"] == 0,
            "Exact successful HRESULT required")
    require(report.get("setter_call_count") == 1 and type(report["setter_call_count"]) is int,
            "Exactly one setter required")
    require(all(report.get(k) is False for k in
                ("save_attempted", "model_saved", "GTP_attempted", "GOP_attempted",
                 "AFR_attempted", "tool_edit_attempted", "operation_assignment_attempted")),
            "Unexpected action in first-cut checkpoint")
    clean_events(report)
    _bindings(report, values)
    require(report.get("after_document") == report["after"]["document"], "Final document alias differs")
    verify_transition(report["before_settings"], report["after_settings"])
    expected = deepcopy(report["before"])
    expected["document"]["needs_save"] = report["after"]["document"]["needs_save"]
    require(_same_inventory(expected, report["after"]), "Sibling or saved context changed")
    expected_levels = deepcopy(report["before_levels"])
    expected_levels["levels"]["toolpath_parameters"][FIELD] = 0
    require(report["after_levels"] == expected_levels, "Depth/setup/other fields changed")
    marker = attempt_marker(expected_document_path, expected_source_sha256, target_operation_native_id)
    mark, _ = read_pin(report["dispatch_marker"]["path"], report["dispatch_marker"]["sha256"])
    require(Path(report["dispatch_marker"]["path"]).resolve() == marker.resolve()
            and mark.get("scope") == SCOPE and mark.get("status") == "readback_verified"
            and type(mark.get("setter_call_count")) is int and mark["setter_call_count"] == 1
            and mark.get("request") == values and mark.get("from_value") == 1
            and mark.get("to_value") == 0, "Durable single-attempt marker required")
    return report


def run_firstcut_change(*, observe, dispatch, persist, report):
    """Small one-shot state machine. The dispatch callback owns the durable guard."""
    before = observe("before")
    _strict_settings(before, 1)
    report["before_settings"] = deepcopy(before)
    persist()
    result = dispatch()
    report.update(setter_returned=True, native_dispatch_pending=False,
                  setter_return_value=result, phase="readback")
    persist()
    require(type(result) is int and result == 0,
            "Documented HRESULT/no-out call must return integer S_OK")
    after = observe("after")
    verify_transition(before, after)
    report["after_settings"] = deepcopy(after)
    persist()


def set_rough_first_cut_to_stock(sw, clsid, typelib_path, *, levels_receipt_path,
        levels_receipt_sha256, primary_contract_path, primary_contract_sha256,
        target_feature_native_id, target_operation_native_id, target_operation_setup_native_id, **args):
    from scripts.sw_cam_events import CamMessageSession

    bindings = dict(process_id=args["process_id"], expected_document_path=args["expected_document_path"],
        expected_source_sha256=args["expected_source_sha256"],
        target_feature_native_id=target_feature_native_id, target_operation_native_id=target_operation_native_id,
        target_operation_setup_native_id=target_operation_setup_native_id)
    report = dict(scope=SCOPE, status="error", phase="preflight", **bindings,
        readback_verified=False, setter_attempted=False, setter_returned=False, setter_call_count=0,
        native_dispatch_pending=False, mutation_attempted=False, automatic_retry=False,
        save_attempted=False, model_saved=False, GTP_attempted=False, GOP_attempted=False,
        AFR_attempted=False, tool_edit_attempted=False, operation_assignment_attempted=False,
        units_verified=False, physical_depth_verified=False, incoming_stock_verified=False,
        production_qualified=False, entry_strategy_qualified=False,
        snapshot_diagnostics=[], saved_file_sha256=args["expected_source_sha256"])
    anchor = levels = session = marker = receipt = None
    created = marker_created = False
    native_before = None

    def persist():
        if created:
            _write_receipt(receipt, report)

    def events(active=True):
        s = session.summary(); report["messages"] = s
        require(s.get("subscribed") is True and s.get("active") is active
                and (active or s.get("disconnected") is True)
                and not any(s.get(k) for k in ("event_count", "overflow", "callback_errors",
                    "callback_error_count", "subscription_error", "disconnect_errors")),
                "CAM event/transport requires stop")

    def identity():
        pid = _member(sw, "GetProcessID")
        require(type(pid) is int and pid == args["process_id"], "Selected process changed")
        anchor.check_runtime_identity()
        doc = raw_part_identity(sw)
        check_document_target(doc["path"], doc["title"], expected_path=args["expected_document_path"], required=True)
        require(_file_hash(args["expected_document_path"]) == args["expected_source_sha256"],
                "Saved source changed")
        return doc

    def check_pins():
        anchor.check_files()
        for pin in extra_pins:
            require(_file_hash(pin["path"]) == pin["sha256"], "Pinned evidence changed")

    def details(state, native, read, typed, diag, boundary):
        row = next(r for r in state["operations"] if r["native_id"] == target_operation_native_id)
        require(row == report["selected_definition"], "Target operation definition changed")
        found = read(native["doc"], "GetCWObjectFromID", 1, target_feature_native_id)
        require(isinstance(found, (tuple, list)) and len(found) == 2 and found[1] is True,
                "Exact feature lookup failed")
        feature = typed(found[0], "ICWFeature")
        require(_object_id(native["doc"], feature, read) == target_feature_native_id,
                "Feature identity changed")
        op = native["operations"][target_operation_native_id]
        require(_object_id(native["doc"], op, read) == target_operation_native_id,
                "Operation identity changed")
        def native_read(label, invoke, decoder=None, interface=False, validator=None):
            boundary(); value = invoke(); boundary()
            if interface: require(value is not None and bool(value), "Non-null interface required")
            if validator: validator(value)
            return decoder(value) if decoder else value
        def getter(raw, interface_name, name, *params, **kw):
            return native_read(interface_name + "." + name, lambda: read(raw, name, *params), **kw)
        diag["levels_observation"] = {}
        read_mill_level_values(feature, op, native_read=native_read, typed=typed,
                               getter=getter, report=diag["levels_observation"])
        diag["firstcut_settings"] = read_firstcut_settings(op, read, typed)

    def observe(phase):
        nonlocal native_before
        check_pins()
        report["phase"] = phase; diag = dict(phase=phase)
        report["snapshot_diagnostics"].append(diag); persist()
        state, native = capture_selected_plan(sw, clsid, typelib_path, args["expected_document_path"],
            process_id=args["process_id"], expected_source_sha256=args["expected_source_sha256"],
            evidence=anchor, check=events, diagnostic=diag, progress=persist,
            operation_details_reader=details)
        normalized = deepcopy(state)
        normalized["document"]["needs_save"] = levels["before"]["document"]["needs_save"]
        anchor.verify(normalized)
        report[phase] = state
        report[phase + "_levels"] = deepcopy(diag["operation_details"]["levels_observation"])
        if phase == "before":
            require(state["document"] == levels["before"]["document"], "Initial clean document changed")
            require(report["before_levels"] == dict(levels=levels["levels"], setup=levels["setup"]),
                    "Levels no longer match the pinned observation")
            native_before = native
        else:
            expected = deepcopy(report["before_levels"])
            expected["levels"]["toolpath_parameters"][FIELD] = 0
            require(report["after_levels"] == expected, "Depth, setup or another parameter changed")
        persist()
        return diag["operation_details"]["firstcut_settings"]

    def dispatch():
        nonlocal marker_created
        doc = identity()
        require(doc == report["before"]["document"], "Document changed before setter")
        with ScopedCamDispatchGuard(sw, typelib_path, process_id=args["process_id"], expected_document=doc,
                source_sha256=args["expected_source_sha256"], evidence_pins=anchor.pins + extra_pins,
                verify_evidence=check_pins, verify_owned_process=anchor.check_runtime_identity,
                check_events=events) as guard:
            op = native_before["operations"][target_operation_native_id]
            require(_object_id(native_before["doc"], op, guard.read) == target_operation_native_id,
                    "Exact setter operation pointer changed")
            require(read_firstcut_settings(op, guard.read, guard.typed) == report["before_settings"],
                    "Settings changed immediately before setter")
            op3 = guard.typed(op, "ICWMillOperation3")
            def pending():
                nonlocal marker_created
                claim = dict(scope=SCOPE, status="dispatch_pending", request=bindings,
                    receipt_path=str(receipt), setter_call_count=1, automatic_retry=False)
                _write_receipt(marker, claim, create=True); marker_created = True
                report.update(setter_attempted=True, setter_call_count=1,
                    mutation_attempted=True, native_dispatch_pending=True, phase="setter_pending")
                persist()
            result = guard.dispatch_once(lambda: _member(op3, "SetTypeOfFirstCutZ", 0),
                                         persist_pending=pending)
            report["dispatch_guard"] = guard.summary()
            return result

    try:
        validate_inventory_request(**{k: args[k] for k in ("process_id", "expected_document_path",
            "expected_source_sha256", "qualification_only", "acknowledge_disposable_copy",
            "receipt_path", "message_policy")})
        anchor = load_saved_plan_tools_evidence(args["saved_plan_receipt_path"],
            args["saved_plan_receipt_sha256"], **{k: args[k] for k in BINDING_KEYS})
        report["selected_definition"] = validate_defined_rough(anchor, target_feature_native_id,
            target_operation_native_id, target_operation_setup_native_id)
        levels, level_pin = load_levels_anchor(levels_receipt_path, levels_receipt_sha256,
                                               anchor=anchor, bindings=bindings)
        extra_pins = [level_pin] + load_primary_contract(primary_contract_path, primary_contract_sha256)
        marker = attempt_marker(args["expected_document_path"], args["expected_source_sha256"],
                                target_operation_native_id)
        require(not marker.exists() and not marker.is_symlink(),
                "Existing attempt marker; inspect result, never replay")
        receipt = Path(args["receipt_path"])
        require(all(receipt.resolve() != Path(p["path"]).resolve() for p in anchor.pins + extra_pins)
                and receipt.resolve() != marker.resolve(), "Distinct output required")
        _write_receipt(receipt, report, create=True); created = True
        report["anchor"] = anchor.summary()
        report["levels_receipt"] = level_pin
        report["primary_sources"] = extra_pins[1:]
        baseline = identity()
        require(baseline == levels["before"]["document"], "Pinned initial document required")
        app = _bootstrap(sw, clsid, typelib_path, args["expected_document_path"])
        require(identity() == baseline, "Document changed acquiring native host")
        session = CamMessageSession(app, typelib_path)
        with session:
            run_firstcut_change(observe=observe, dispatch=dispatch, persist=persist, report=report)
            events()
            require(identity() == report["after"]["document"], "Identity changed after readback")
        events(active=False)
        check_pins()
        report["after_document"] = identity()
        require(report["after_document"] == report["after"]["document"], "Identity changed during event cleanup")
        final_marker = dict(scope=SCOPE, status="readback_verified", request=bindings,
            receipt_path=str(receipt), setter_call_count=1, from_value=1, to_value=0,
            saved_file_unchanged=True, model_saved=False, automatic_retry=False)
        _write_receipt(marker, final_marker)
        report["dispatch_marker"] = dict(path=str(marker), sha256=_file_hash(marker))
        report.update(status="review_required", phase="finished", readback_verified=True,
            reason="FIRST_CUT_REFERENCE_TOP_OF_STOCK_READ_BACK_RAM_ONLY",
            verification_scope="One enum changed; remaining levels, setup, operation assignments, stock and CAD fingerprints preserved. Existing cutter profiles reused from the prior read-only checkpoint.")
    except Exception as exc:
        report.update(status="error", failed_phase=report["phase"], phase="finished",
                      issue=_error(exc), readback_verified=False)
    finally:
        if session is not None: report["messages"] = session.summary()
        try: persist()
        except Exception as exc:
            report.update(status="error", receipt_write_error=_error(exc), readback_verified=False)
    return report
