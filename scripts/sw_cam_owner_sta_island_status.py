"""Read-only lookup of the existing fixed island companion after a load receipt.

No host loading, registration, COM activation, CAM getter, or mutation is exposed.
The only lookup aliases are the companion's fixed CLSID and registered ProgID;
one typed GetHostStatus call is permitted after the first non-null lookup.
"""
from copy import deepcopy
from pathlib import Path
import json
import time
from scripts import sw_cam_owner_sta_island as shared

SCOPE = "MILL_OWNER_STA_ISLAND_EXISTING_HOST_STATUS_V1"
HOST_PROGID = "CadStudio.SolidWorks.CamIslandQualification"
FIELDS = (shared.LOAD_FIELDS - {"acknowledge_host_load"}) | {
    "status_module_sha256", "previous_load_receipt_path", "previous_load_receipt_sha256"}
require = shared.require


def prepare(params):
    require(type(params) is dict and set(params) == FIELDS, "Exact read-only status fields required")
    p = deepcopy(params)
    q = {k: v for k, v in p.items() if k in shared.LOAD_FIELDS}
    q["acknowledge_host_load"] = True  # Reuse only the existing offline field validator.
    shared.load_parameters(q)
    shared.sha(p["status_module_sha256"])
    require(shared.digest(__file__) == p["status_module_sha256"], "Exact status implementation pin required")
    shared.absolute(p["previous_load_receipt_path"])
    shared.sha(p["previous_load_receipt_sha256"])
    previous, pin = shared.read_pin(p["previous_load_receipt_path"], p["previous_load_receipt_sha256"])
    require(type(previous) is dict and previous.get("scope") == "MILL_ISLAND_OWNER_STA_HOST_LOAD_V1"
            and previous.get("phase") == "finished"
            and previous.get("native_dispatch_pending") is False
            and previous.get("loaded_mvid_verified") is False
            and type(previous.get("CAM_calls")) is int and previous["CAM_calls"] == 0
            and previous.get("Save_attempted") is False
            and previous.get("GOP_attempted") is False and previous.get("GTP_attempted") is False,
            "Exact completed non-CAM load observation required")
    absent_after_load = (previous.get("status") == "uncertain"
        and previous.get("host_load_attempted") is True
        and type(previous.get("load_calls")) is int and previous["load_calls"] == 1
        and type(previous.get("load_result")) is int and previous["load_result"] == 0
        and previous.get("issue", {}).get("message") == "Loaded fixed sidecar object absent")
    already_loaded = (previous.get("status") == "error"
        and previous.get("host_load_attempted") is False
        and type(previous.get("load_calls")) is int and previous["load_calls"] == 0
        and type(previous.get("status_calls")) is int and previous["status_calls"] == 0
        and previous.get("readback_verified") is False
        and previous.get("automatic_retry") is False
        and "load_result" not in previous and "host_status" not in previous
        and previous.get("issue", {}).get("type") == "ValueError"
        and previous.get("issue", {}).get("message") == "Sidecar already loaded; no repeat load")
    require(absent_after_load or already_loaded,
            "Exact absent-after-load or already-loaded preflight receipt required")
    if already_loaded:
        shared.load_owner(previous.get("owner_before"), q)
        shared.load_document(previous.get("document_before"), q)
    before = previous["request"]
    for name in shared.LOAD_FIELDS - {"receipt_path", "acknowledge_host_load"}:
        require(shared.same_path(before[name], q[name]) if name.endswith("_path")
                else type(before[name]) is type(q[name]) and before[name] == q[name],
                "Status request differs from original load: " + name)
    pins = shared.load_pins(q) + [pin, {"path": str(Path(__file__).resolve()),
                                     "sha256": p["status_module_sha256"]}]
    require(len({shared.key(x["path"]) for x in pins}) == len(pins), "Status pins may not alias")
    shared.check_pins(pins)
    out = Path(p["receipt_path"])
    require(out.parent.is_dir() and not out.exists() and not out.is_symlink()
            and shared.key(out) not in {shared.key(x["path"]) for x in pins},
            "Fresh nonaliased read-only receipt required")
    return p, pins


class StatusBackend:
    def __init__(self, p):
        self.p = p
        # Only the read-only owner/application/document helpers are reused.
        self.reader = shared.LoaderBackend(p)
        self.raw = None

    def owner(self):
        return self.reader.owner()

    def document(self):
        return self.reader.document()

    def lookup(self, alias):
        from scripts.sw_cam import _member
        require(alias in (shared.HOST_CLSID, HOST_PROGID), "Only two fixed companion aliases are allowed")
        self.raw = _member(self.reader.application(), "GetAddInObject", alias)
        return self.raw is not None

    def status_once(self):
        from ctypes import POINTER
        from comtypes import BSTR, typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        require(self.raw is not None, "Existing companion object required")
        library = typeinfo.LoadTypeLibEx(self.p["host_tlb_path"], typeinfo.REGKIND_NONE)
        attr = library.GetLibAttr()
        require(str(attr.guid).upper() == shared.HOST_LIBID
                and (attr.wMajorVerNum, attr.wMinorVerNum) == (1, 0), "Exact companion TLB required")
        interface = GetModule(library).ICamExplicitIslandQualification
        require(str(interface._iid_).upper() == shared.INTERFACE_IID, "Fixed companion IID required")
        methods = [m for m in interface._methods_ if m.name == "GetHostStatus"]
        require(len(methods) == 1, "Unique fixed read-only status method required")
        require_abi(methods[0], 1, (POINTER(BSTR),), (10,))
        return _marshal_pywin32_unknown(self.raw).QueryInterface(interface).GetHostStatus()


def run_read(params, *, backend=None):
    from scripts.sw_cam_generation import _write_receipt
    p, pins = prepare(params)
    engine = backend or StatusBackend(p)
    out = Path(p["receipt_path"])
    r = {"scope": SCOPE, "status": "prepared", "phase": "prepared", "request": p,
         "pins": pins, "read_only": True, "mutation_attempted": False,
         "CAM_calls": 0, "load_calls": 0, "status_calls": 0, "lookup_attempts": [],
         "native_status_pending": False, "model_saved": False, "Save_attempted": False,
         "GOP_attempted": False, "GTP_attempted": False, "automatic_retry": False,
         "readback_verified": False, "loaded_mvid_verified": False,
         "document_unchanged_verified": False}
    _write_receipt(out, r, create=True)
    started = time.perf_counter()
    try:
        owner = engine.owner()
        shared.load_owner(owner, p)
        r["owner_before"] = owner
        document = engine.document()
        shared.load_document(document, p)
        r["document_before"] = document
        found = False
        for alias in (shared.HOST_CLSID, HOST_PROGID):
            shared.check_pins(pins)
            row = {"alias": alias, "attempted": True, "returned": False,
                   "object_present": False}
            r["lookup_attempts"].append(row)
            r["phase"] = "fixed_alias_lookup"
            _write_receipt(out, r)
            present = engine.lookup(alias)
            require(type(present) is bool, "Strict object-presence result required")
            row.update(returned=True, object_present=present)
            _write_receipt(out, r)
            if present:
                found = True
                r.update(phase="read_fixed_status", status_calls=1, native_status_pending=True,
                         resolved_alias=alias)
                _write_receipt(out, r)
                status = shared.decode(engine.status_once())
                r.update(host_status=status, native_status_pending=False)
                shared.validate_status(status, p)
                break
        after_owner = engine.owner()
        shared.load_owner(after_owner, p)
        require(after_owner == owner, "Owned process identity changed during read")
        after_document = engine.document()
        shared.load_document(after_document, p)
        require(after_document == document, "Current document changed during status read")
        shared.check_pins(pins)
        r.update(owner_after=after_owner, document_after=after_document, phase="finished",
                 status="observed" if found else "not_found", readback_verified=found,
                 loaded_mvid_verified=found, document_unchanged_verified=True)
    except Exception as exc:
        r.update(status="error", phase="finished", readback_verified=False,
                 issue={"type": type(exc).__name__, "message": str(exc)})
    r["elapsed_seconds"] = time.perf_counter()-started
    _write_receipt(out, r)
    return r


def read_existing_owner_sta_island_host(params):
    from scripts.sw_operation_guard import solidworks_operation_lock
    p, _ = prepare(params)
    with solidworks_operation_lock(timeout_seconds=1, process_id=p["process_id"]):
        return run_read(p)

