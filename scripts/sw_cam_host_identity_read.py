"""Identify an already loaded host through its unchanged TURN interface only.

The exact empty request is rejected before any CAM access. Existing lifecycle
receipts and their pending marker are read-only inputs, never replay authority.
"""
from copy import deepcopy
from pathlib import Path
import re
import time
import uuid
from scripts import sw_cam_mill_host_lifecycle as lifecycle
from scripts import sw_cam_inprocess_reader as common
from scripts import sw_cam_inprocess_host_load as loader
from scripts.sw_cam_generation import _write_receipt
from scripts import sw_cam_comtypes, sw_connect, sw_executable_launch, sw_operation_guard, sw_cam, sw_cam_generation

require = common.require
SCOPE = "OWN_HOST_EXISTING_TURN_IDENTITY_V1"
ACTION = "read_existing_host_identity"
PARAMS = {"process_id", "expected_process_creation_time", "expected_document_path",
    "expected_source_sha256", "expected_configuration", "expected_dirty",
    "failed_lifecycle_receipt_pin", "lifecycle_marker_pin", "module_sha256", "receipt_path"}


def failure_contract(r, p):
    require(r.get("scope") == lifecycle.SCOPE and r.get("status") == "uncertain"
        and r.get("phase") == "finished" and r.get("native_dispatch_pending") is True,
        "Exact completed uncertain lifecycle required")
    require(all(r.get(k) is False for k in ("model_saved", "GTP_attempted", "model_change_requested",
        "readback_verified", "loaded_mvid_verified", "automatic_replay")), "Failed host-only scope required")
    names = ["UnloadOwnedHost", "RegisterCurrentUserHost", "LoadVersionedHost", "ReadMillSnapshot"]
    require(list(r["actions"]) == names, "Exact original lifecycle action order required")
    for name in names[:3]:
        row = r["actions"][name]
        require(all(row.get(k) is True for k in ("attempted", "returned", "verified")), "Original host transition incomplete")
    for name in ("UnloadOwnedHost", "LoadVersionedHost"):
        require(type(r["actions"][name].get("result")) is int and r["actions"][name]["result"] == 0,
            "Original host load/unload did not return strict success")
    require(r["actions"]["RegisterCurrentUserHost"].get("result") == dict(typelib_hresult=0,
        scope="CurrentUser", class_mapping="existing_Register_CurrentUser_version_derived"),
        "Original registration result differs")
    require(r["actions"][names[-1]] == dict(attempted=True, returned=False, verified=False),
        "MILL call must have stopped before return")
    issue = r.get("issue", {})
    require(issue.get("type") == "COMError" and issue.get("hresult") == -2147467262,
        "Exact unsupported interface failure required")
    locations = issue.get("locations", [])
    require(any(v.get("file") == "sw_cam_mill_host_lifecycle.py" and v.get("function") == "_read" for v in locations)
        and any(v.get("function") == "QueryInterface" for v in locations), "Failure must be the original interface query")
    oldp = r["request"]
    for name in ("process_id", "expected_process_creation_time", "expected_configuration"):
        require(oldp[name] == p[name], "Original owned session differs")
    require(common.key(oldp["expected_document_path"]) == common.key(p["expected_document_path"]),
        "Original document differs")
    require(oldp["module_sha256"] == common.digest(lifecycle.__file__), "Original lifecycle implementation differs")
    lifecycle.event_check(r["events_after"], closed=True)
    return oldp


def classify_identity(r, p, old, new):
    require(type(r) is dict and type(r.get("schema_version")) is int and r["schema_version"] == 1
        and r.get("scope") == "TURN_INPROCESS_READ_V1" and r.get("engine_version") == "turn-reader-1",
        "Exact unchanged TURN identity protocol required")
    require(r.get("stage") == "request" and r.get("status") == "error" and r.get("message") == "REQUEST_FIELDS"
        and r.get("read_only") is True and r.get("mutation_attempted") is False and r.get("readback_verified") is False,
        "Empty request must stop before CAM reads")
    require(type(r.get("process_id")) is int and r["process_id"] == p["process_id"], "Returned host process differs")
    require(not any(k in r for k in ("document_before", "document_after", "inventory", "tools", "nc_parameters", "cam_configuration")),
        "Unexpected CAM data in identity-only response")
    require(common.finite(r.get("elapsed_ms")) and r["elapsed_ms"] >= 0, "Finite native elapsed time required")
    require(type(r.get("host_module_version_id")) is str and type(r.get("host_assembly_location")) is str,
        "Actual module identity and location required")
    mvid = str(uuid.UUID(r["host_module_version_id"]))
    for label, artifact in (("old", old), ("new", new)):
        if mvid == artifact["mvid"]:
            require(common.key(r["host_assembly_location"]) == common.key(artifact["dll"]["path"]),
                "Known MVID returned from unexpected assembly location")
            return dict(loaded_artifact=label, module_version_id=mvid,
                assembly_location=r["host_assembly_location"], identity_verified=True,
                CAM_getters_requested=False, mill_interface_qualified=False)
    raise ValueError("Unrecognized loaded host identity; no alternate probing is allowed")


def prepare(request):
    require(type(request) is dict and set(request) == {"action", "params"} and request["action"] == ACTION,
        "Only fixed read-only identity action allowed")
    p = deepcopy(request["params"])
    require(type(p) is dict and set(p) == PARAMS, "Exact identity request fields required")
    require(type(p["process_id"]) is int and 0 < p["process_id"] < 2**31
        and common.finite(p["expected_process_creation_time"]) and p["expected_process_creation_time"] > 0,
        "Exact owned process lifetime required")
    require(p["expected_dirty"] is False and type(p["expected_configuration"]) is str
        and 0 < len(p["expected_configuration"]) <= 4096, "Exact clean configuration required")
    require(type(p["expected_document_path"]) is str and Path(p["expected_document_path"]).is_absolute()
        and Path(p["expected_document_path"]).suffix.lower() == ".sldprt", "Exact current part path required")
    require(type(p["expected_source_sha256"]) is str and re.fullmatch("[0-9a-f]{64}", p["expected_source_sha256"]),
        "Exact current source digest required")
    require(p["module_sha256"] == common.digest(__file__), "Sealed diagnostic implementation differs")
    failed = lifecycle.read_pin(p["failed_lifecycle_receipt_pin"])
    oldp = failure_contract(failed, p)
    old = lifecycle.artifact(lifecycle.read_pin(oldp["old_artifact_pin"]), "1.0.0.0")
    new = lifecycle.artifact(lifecycle.read_pin(oldp["new_artifact_pin"]), lifecycle.VERSION)
    marker = lifecycle.read_pin(p["lifecycle_marker_pin"])
    require(common.key(p["lifecycle_marker_pin"]["path"]) == common.key(lifecycle.marker_path(oldp, new)),
        "Original lifecycle marker path differs")
    require(marker == dict(scope=lifecycle.SCOPE, status="uncertain",
        receipt_pin=lifecycle.pin(oldp["receipt_path"]), native_dispatch_pending=True, automatic_replay=False),
        "Original uncertain lifecycle marker changed")
    require(marker["receipt_pin"]["sha256"] == p["failed_lifecycle_receipt_pin"]["sha256"],
        "Archive and original lifecycle receipt differ")
    pins = lifecycle.merge_pins([p["failed_lifecycle_receipt_pin"], p["lifecycle_marker_pin"],
        marker["receipt_pin"], oldp["old_artifact_pin"], oldp["new_artifact_pin"],
        lifecycle.pin(__file__), lifecycle.pin(lifecycle.__file__), lifecycle.pin(common.__file__),
        lifecycle.pin(loader.__file__), dict(path=p["expected_document_path"], sha256=p["expected_source_sha256"])],
        [old["dll"], old["tlb"]] + old["dependencies"], [new["dll"], new["tlb"]] + new["dependencies"],
        [lifecycle.pin(module.__file__) for module in (sw_cam_comtypes, sw_connect, sw_executable_launch,
            sw_operation_guard, sw_cam, sw_cam_generation)])
    common.check_files(pins)
    _, interface, method = lifecycle.type_library(old["tlb"]["path"], mill=False)
    require(str(interface._iid_).upper() == common.READER_IID and method == "ReadTurnSnapshot", "Fixed TURN ABI required")
    out = Path(p["receipt_path"])
    require(out.is_absolute() and out.suffix.lower() == ".json" and out.parent.is_dir()
        and not out.exists() and not out.is_symlink() and common.key(out) not in {common.key(x["path"]) for x in pins},
        "Fresh nonaliased diagnostic receipt required")
    return p, old, new, pins


class NativeBackend:
    """Compose read-only application getters; do not inherit lifecycle mutators."""
    def __init__(self, p, old):
        self.p = p
        self.old = old
        self.reader = loader.LoaderBackend(p)
        self.identity_calls = 0

    def owner(self): return self.reader.owner()
    def application(self): return self.reader.application()
    def document(self): return self.reader.document()

    def identity_once(self):
        require(self.identity_calls == 0, "Identity probe may run once per backend")
        self.identity_calls += 1
        return lifecycle.NativeBackend._read(self, self.old, mill=False, text="{}")


def checked_document(value, p):
    common.validate_document(value, p)
    require(value["needs_save"] is False and value["configuration"] == p["expected_configuration"],
        "Current clean document/configuration differs")


def run_prepared(prepared, *, backend=None):
    p, old, new, pins = prepared
    out = Path(p["receipt_path"])
    require(not out.exists(), "Diagnostic receipt exists; no automatic replay")
    engine = backend or NativeBackend(p, old)
    report = dict(scope=SCOPE, status="prepared", phase="prepared", request=deepcopy(p),
        read_only=True, mutation_attempted=False, CAM_getters_requested=False,
        model_saved=False, GTP_attempted=False, host_load_attempted=False,
        registration_attempted=False, automatic_replay=False, identity_call_attempted=False,
        identity_call_returned=False, readback_verified=False, document_unchanged_verified=False,
        source_sha256=p["expected_source_sha256"], original_lifecycle_marker_pin=p["lifecycle_marker_pin"])
    _write_receipt(out, report, create=True)
    started = time.perf_counter()
    try:
        common.check_files(pins)
        owner = engine.owner(); common.check_owner(owner, p); report["owner_before"] = owner
        before = engine.document(); checked_document(before, p); report["document_before"] = before
        report.update(phase="ReadTurnIdentity", identity_call_attempted=True)
        _write_receipt(out, report)
        raw = engine.identity_once()
        report.update(raw_host_response=raw, identity_call_returned=True)
        _write_receipt(out, report)  # Preserve raw data before decoding or matching.
        result = common.decode(raw); report["host_response"] = result
        _write_receipt(out, report)
        report["identity"] = classify_identity(result, p, old, new)
        after = engine.document(); checked_document(after, p); report["document_after"] = after
        require(before == after, "Document changed during identity read")
        after_owner = engine.owner(); common.check_owner(after_owner, p); report["owner_after"] = after_owner
        require(owner == after_owner, "Owned process lifetime changed")
        common.check_files(pins)
        report.update(status="observed_host_identity", phase="finished", readback_verified=True,
            document_unchanged_verified=True, original_lifecycle_marker_unchanged=True)
    except Exception as exc:
        report.update(status="error", phase="finished", issue=common._error(exc))
    report["elapsed_seconds"] = time.perf_counter() - started
    _write_receipt(out, report)
    return report


def dispatch_request(request, *, validate_only=False):
    prepared = prepare(request)
    if validate_only:
        return dict(status="validated_offline", scope=SCOPE, native_called=False,
            fixed_request="{}", fixed_interface=common.READER_IID, fixed_method="ReadTurnSnapshot",
            full_CAM_read_requested=False, lifecycle_replay=False, file_count=len(prepared[3]))
    with common.solidworks_operation_lock(timeout_seconds=1, process_id=prepared[0]["process_id"]):
        return run_prepared(prepared)
