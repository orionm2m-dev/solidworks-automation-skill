"""Fixed JSON-only owner-STA qualification client: one pocket plus 1 or 4 islands.

Offline preparation checks the saved five-sketch authority and a fresh physical
copy. Actual dispatch calls one fixed typed add-in method once. No CAM object is
returned to Python; no Save, GOP, GTP, replay, or loader fallback is supported.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import os
import re
import time
import uuid

SCOPE = "MILL_OWNER_STA_EXPLICIT_ISLAND_CLIENT_V1"
NATIVE_SCOPE = "MILL_OWNER_STA_EXPLICIT_ISLAND_QUALIFICATION_V1"
ACTION = "qualify_create_pocket_islands_owner_sta"
# Stable published identities of the separate qualification companion.
HOST_CLSID = "{F69869EF-C175-4A06-9426-E1502BFA8921}"
HOST_LIBID = "{91FE2D85-D19A-4DBB-8BB0-B6D02A948FA5}"
INTERFACE_IID = "{36B207A9-AF3A-4F89-B211-5755E7CF6327}"
NATIVE_FIELDS = {
    "schema_version", "expected_process_id", "expected_process_creation_time",
    "expected_document_path", "expected_source_sha256", "protected_document_path",
    "protected_source_sha256", "qualification_root", "expected_sw_configuration",
    "expected_cam_configuration", "expected_host_module_version_id",
    "native_receipt_path", "expected_cad_fingerprint", "owner_setup_native_id",
    "operation_setup_native_id", "axis_native", "origin_native",
    "outer_sketch_name", "island_sketch_names", "island_count_limit", "depth_native", "expected_shape",
}
PARAM_FIELDS = {
    "native_request", "host_dll_path", "host_dll_sha256", "host_tlb_path",
    "host_tlb_sha256", "module_sha256", "receipt_path", "copy_receipt_path",
    "copy_receipt_sha256", "batch_receipt_path", "batch_receipt_sha256",
    "circle_receipt_path", "circle_receipt_sha256", "circle_save_receipt_path",
    "circle_save_receipt_sha256", "feature_plan_path", "feature_plan_sha256",
    "qualification_only", "acknowledge_ram_only",
}
PIN_NAMES = ("host_dll", "host_tlb", "copy_receipt", "batch_receipt",
             "circle_receipt", "circle_save_receipt", "feature_plan")
MAX_JSON = 2 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(path):
    return str(Path(path).resolve()).replace("/", "\\").casefold()


def same_path(a, b):
    return type(a) is str and type(b) is str and key(a) == key(b)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def duplicate_safe(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "Duplicate JSON key")
        result[name] = value
    return result


def decode(text):
    require(type(text) is str and 0 < len(text.encode("utf-8")) <= MAX_JSON,
            "Bounded JSON text required")
    return json.loads(text, object_pairs_hook=duplicate_safe,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError("Nonfinite JSON value")))


def absolute(path):
    require(type(path) is str and 0 < len(path) <= 32767
            and Path(path).is_absolute(), "Absolute bounded path required")
    return path


def sha(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value),
            "Exact lowercase SHA256 required")
    return value


def under(path, root):
    return key(path).startswith(key(root).rstrip("\\") + "\\")


def check_pin(path, expected):
    q = Path(path)
    require(q.is_file() and not q.is_symlink()
            and 0 < q.stat().st_size <= 128 * 1024 * 1024,
            "Existing bounded regular input required")
    require(digest(q) == expected, "Pinned input changed: " + str(q))
    return {"path": str(q), "sha256": expected}


def read_pin(path, expected):
    pin = check_pin(path, expected)
    return decode(Path(path).read_text(encoding="utf-8-sig")), pin


def marker_path(n):
    q = Path(n["expected_document_path"])
    return q.parent / ("." + q.name + ".owner-sta-explicit-island.once.json")


def client_marker_path(n):
    q = Path(n["expected_document_path"])
    return q.parent / ("." + q.name + ".owner-sta-explicit-island.client-once.json")


def validate_native(n):
    require(type(n) is dict and set(n) == NATIVE_FIELDS,
            "Exact fixed native request required")
    n = deepcopy(n)
    require(type(n["schema_version"]) is int and n["schema_version"] == 1,
            "Schema version 1 required")
    for name in ("expected_process_id", "owner_setup_native_id",
                 "operation_setup_native_id"):
        require(type(n[name]) is int and 0 < n[name] < 2**31,
                "Strict positive process/setup identity required")
    require(n["owner_setup_native_id"] != n["operation_setup_native_id"],
            "Feature and operation setup IDs must differ")
    require(finite(n["expected_process_creation_time"])
            and n["expected_process_creation_time"] > 0, "Exact lifetime required")
    for name in ("expected_document_path", "protected_document_path",
                 "qualification_root", "native_receipt_path"):
        absolute(n[name])
    for name in ("expected_source_sha256", "protected_source_sha256"):
        sha(n[name])
    require(n["expected_source_sha256"] == n["protected_source_sha256"],
            "Qualification copy must match saved protected source")
    for name in ("expected_document_path", "protected_document_path"):
        require(Path(n[name]).suffix.casefold() == ".sldprt", "Part path required")
    require(under(n["expected_document_path"], n["qualification_root"])
            and not under(n["protected_document_path"], n["qualification_root"]),
            "Fresh separate qualification root required")
    require(under(n["native_receipt_path"], n["qualification_root"])
            and Path(n["native_receipt_path"]).suffix.casefold() == ".json",
            "Native receipt must be JSON in qualification root")
    for name in ("expected_sw_configuration", "expected_cam_configuration",
                 "outer_sketch_name"):
        require(type(n[name]) is str and 0 < len(n[name]) <= 1024,
                "Exact bounded configuration/sketch name required")
    require(type(n["island_sketch_names"]) is list
            and len(n["island_sketch_names"]) == 4, "Four source islands required")
    require(type(n["island_count_limit"]) is int and n["island_count_limit"] in (1, 4),
            "Fixed island count 1 or 4 required")
    names = [n["outer_sketch_name"]] + n["island_sketch_names"]
    require(all(type(x) is str and 0 < len(x) <= 1024 for x in names)
            and len({x.casefold() for x in names}) == 5,
            "Five distinct exact sketch names required")
    for name in ("axis_native", "origin_native"):
        require(type(n[name]) is list and len(n[name]) == 3
                and all(finite(x) for x in n[name]), "Finite explicit frame required")
    require(abs(math.dist(n["axis_native"], [0, 0, 0]) - 1) <= 1e-12,
            "Unit setup axis required")
    require(finite(n["depth_native"]) and 0 < n["depth_native"] <= 100,
            "Bounded positive native depth required")
    require(type(n["expected_shape"]) is int and n["expected_shape"] == 2,
            "Pocket Shape 2 required")
    require(type(n["expected_host_module_version_id"]) is str
            and str(uuid.UUID(n["expected_host_module_version_id"]))
            == n["expected_host_module_version_id"], "Canonical host MVID required")
    f = n["expected_cad_fingerprint"]
    require(type(f) is dict and set(f) == {"feature_tree", "solids"},
            "Exact CAD fingerprint required")
    require(type(f["feature_tree"]) is list and 1 <= len(f["feature_tree"]) <= 512,
            "Bounded CAD feature tree required")
    require(all(type(x) is dict and set(x) == {"name", "type"}
                and all(type(x[k]) is str and 0 < len(x[k]) <= 1024
                        for k in ("name", "type")) for x in f["feature_tree"]),
            "Exact CAD tree rows required")
    require(type(f["solids"]) is list and 1 <= len(f["solids"]) <= 32,
            "Bounded solid fingerprint required")
    for body in f["solids"]:
        require(type(body) is dict and set(body) == {"box_m", "mass_raw"},
                "Exact solid fingerprint row required")
        require(type(body["box_m"]) is list and len(body["box_m"]) == 6
                and type(body["mass_raw"]) is list and len(body["mass_raw"]) == 12
                and all(finite(x) for x in body["box_m"] + body["mass_raw"]),
                "Finite native solid fingerprint required")
    return n


def validate_params(params):
    require(type(params) is dict and set(params) == PARAM_FIELDS,
            "Exact qualification wrapper fields required")
    p = deepcopy(params)
    p["native_request"] = validate_native(p["native_request"])
    for name, value in p.items():
        if name.endswith("_path"):
            absolute(value)
        elif name.endswith("_sha256"):
            sha(value)
    require(p["qualification_only"] is True and p["acknowledge_ram_only"] is True,
            "Explicit RAM-only qualification required")
    require(Path(p["host_dll_path"]).suffix.casefold() == ".dll"
            and Path(p["host_tlb_path"]).suffix.casefold() == ".tlb",
            "Pinned native DLL/TLB required")
    require(Path(p["receipt_path"]).suffix.casefold() == ".json",
            "Client receipt must be JSON")
    require(p["module_sha256"] == digest(__file__), "Exact wrapper pin required")
    return p


def verify_copy(copy, n):
    required = {"scope", "source", "target", "exclusive_creation_verified",
                "source_unchanged", "bytes"}
    allowed = required | {"created_utc", "native_calls", "copied_saved_disk_bytes_only"}
    require(type(copy) is dict and required <= set(copy) <= allowed
            and copy["scope"] == "EXCLUSIVE_SAVED_FIVE_SKETCH_CAM_COPY_V1"
            and copy["exclusive_creation_verified"] is True
            and copy["source_unchanged"] is True, "Completed exclusive copy proof required")
    for name, path_name, sha_name in (
        ("source", "protected_document_path", "protected_source_sha256"),
        ("target", "expected_document_path", "expected_source_sha256"),
    ):
        r = copy[name]
        require(type(r) is dict and set(r) == {"path", "sha256"}
                and same_path(r["path"], n[path_name]) and r["sha256"] == n[sha_name],
                "Copy proof identity/hash differs")
    require(type(copy["bytes"]) is int and copy["bytes"] > 0
            and copy["bytes"] == Path(n["expected_document_path"]).stat().st_size
            == Path(n["protected_document_path"]).stat().st_size,
            "Copy proof size differs")
    if "native_calls" in copy:
        require(type(copy["native_calls"]) is int and copy["native_calls"] == 0,
                "File-only copy required")
    if "copied_saved_disk_bytes_only" in copy:
        require(copy["copied_saved_disk_bytes_only"] is True, "Saved disk source required")
    require(not os.path.samefile(n["expected_document_path"],
                                 n["protected_document_path"]),
            "Copy aliases protected source file")


def authority_proof(p):
    """Reuse completed historical producer proofs; never replay their mutations."""
    from scripts import sw_cam_explicit_island_authority as authority
    from scripts import sw_cam_explicit_island_feature as feature
    n = p["native_request"]
    batch = authority.verify_completed_receipt(p["batch_receipt_path"],
                                                p["batch_receipt_sha256"])
    old = batch["receipt"]["request"]
    v = dict(process_id=old["process_id"],
             expected_process_create_time=old["expected_process_create_time"],
             expected_document_path=n["protected_document_path"],
             expected_source_sha256=n["protected_source_sha256"],
             expected_sw_configuration=n["expected_sw_configuration"],
             expected_cam_configuration=n["expected_cam_configuration"])
    # Saved producer identity belongs to its historical process; the new live
    # owner is independently bound before native dispatch and inside the host.
    for name in ("process_id", "expected_process_create_time",
                 "expected_sw_configuration", "expected_cam_configuration"):
        require(old[name] == v[name] and type(old[name]) is type(v[name]),
                "Saved producer identity differs: " + name)
    require(same_path(old["expected_document_path"], n["protected_document_path"]),
            "Saved producer must describe protected source")
    circle, _ = read_pin(p["circle_receipt_path"], p["circle_receipt_sha256"])
    saved, _ = read_pin(p["circle_save_receipt_path"], p["circle_save_receipt_sha256"])
    outer, cad = authority.verify_circle_save(batch, circle, saved, v)
    planned, _ = read_pin(p["feature_plan_path"], p["feature_plan_sha256"])
    planned = feature.plan(planned)
    require(planned["expected_attribute_suffix"] == [],
            "Qualification admits no additional CAD attributes")
    for name in ("owner_setup_native_id", "axis_native", "origin_native",
                 "outer_sketch_name", "island_sketch_names", "depth_native",
                 "expected_shape"):
        require(planned[name] == n[name], "Native request differs from plan: " + name)
    require(n["outer_sketch_name"] == outer["sketch_name"]
            and n["island_sketch_names"] == [x["sketch_name"] for x in batch["specs"]],
            "Exact saved sketch names required")
    feature.empty_baseline(batch["expected_inventory"], planned)
    inventory = batch["expected_inventory"]
    require(len(inventory["operation_setups"]) == 1
            and inventory["operation_setups"][0]["native_id"]
            == n["operation_setup_native_id"], "Operation setup differs")
    require(n["owner_setup_native_id"] == old["expected_setup_native_id"]
            and n["axis_native"] == old["expected_setup_axis_native"]
            and n["origin_native"] == old["expected_setup_origin_native"],
            "Saved setup frame differs")
    expected = {"feature_tree": cad["features"], "solids": cad["solids"]}
    require(n["expected_cad_fingerprint"] == expected, "Saved CAD fingerprint differs")
    extra_pins = [x for x in batch["root_pins"]
                  if not same_path(x["path"], n["protected_document_path"])]
    extra_pins.append(batch["marker_pin"])
    return {"saved_five_sketch_authority_verified": True,
            "historical_producer": {"process_id": old["process_id"],
                "process_creation_time": old["expected_process_create_time"]},
            "intended_current_owner": {"process_id": n["expected_process_id"],
                "process_creation_time": n["expected_process_creation_time"]},
            "expected_cad_fingerprint": expected, "pins": extra_pins}


def check_pins(pins):
    for pin in pins:
        check_pin(pin["path"], pin["sha256"])


def prepare(params):
    p = validate_params(params)
    n = p["native_request"]
    pins = [{"path": p[name + "_path"], "sha256": p[name + "_sha256"]}
            for name in PIN_NAMES]
    pins += [{"path": n["expected_document_path"], "sha256": n["expected_source_sha256"]},
             {"path": n["protected_document_path"], "sha256": n["protected_source_sha256"]},
             {"path": str(Path(__file__).resolve()), "sha256": p["module_sha256"]}]
    require(len({key(x["path"]) for x in pins}) == len(pins), "Input paths may not alias")
    check_pins(pins)
    copy, _ = read_pin(p["copy_receipt_path"], p["copy_receipt_sha256"])
    verify_copy(copy, n)
    proof = authority_proof(p)
    merged = {key(x["path"]): x for x in pins}
    for pin in proof["pins"]:
        k = key(pin["path"])
        require(k not in merged or merged[k]["sha256"] == pin["sha256"],
                "Conflicting protected input pins")
        merged[k] = pin
    pins = list(merged.values())
    check_pins(pins)
    outputs = [p["receipt_path"], n["native_receipt_path"],
               str(marker_path(n)), str(client_marker_path(n))]
    require(len({key(x) for x in outputs}) == 4
            and not {key(x) for x in outputs}.intersection(merged),
            "Qualification outputs alias each other or inputs")
    require(all(Path(x).parent.is_dir() and not Path(x).exists()
                and not Path(x).is_symlink() for x in outputs),
            "Fresh receipts and unused qualification copy required")
    return {"params": p, "native_request": n, "pins": pins,
            "authority": proof, "marker_path": str(marker_path(n)),
            "client_marker_path": str(client_marker_path(n))}


def check_owner(owner, n):
    require(type(owner) is dict and owner.get("alive") is True
            and type(owner.get("process_id")) is int
            and owner["process_id"] == n["expected_process_id"]
            and owner.get("create_time") == n["expected_process_creation_time"],
            "Owned process lifetime changed")
    require(type(owner.get("executable")) is str
            and Path(owner["executable"]).name.casefold() == "sldworks.exe",
            "SOLIDWORKS owner required")


class NativeBackend:
    def __init__(self, p):
        self.p = p

    def owner(self):
        from scripts.sw_executable_launch import _process_identity
        return _process_identity(self.p["native_request"]["expected_process_id"])

    def invoke_once(self, request_json):
        from ctypes import POINTER
        from comtypes import BSTR, typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam import _member
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        from scripts.sw_connect import connect_solidworks
        p = self.p
        library = typeinfo.LoadTypeLibEx(p["host_tlb_path"], typeinfo.REGKIND_NONE)
        attr = library.GetLibAttr()
        require(str(attr.guid).upper() == HOST_LIBID
                and (attr.wMajorVerNum, attr.wMinorVerNum) == (1, 0),
                "Exact sidecar host TLB required")
        module = GetModule(library)
        interface = module.ICamExplicitIslandQualification
        require(str(interface._iid_).upper() == INTERFACE_IID,
                "Fixed qualification IID differs")
        methods = [m for m in interface._methods_
                   if m.name == "QualifyCreatePocketAndIslands"]
        require(len(methods) == 1, "Unique fixed qualification method required")
        require_abi(methods[0], 2, (BSTR, POINTER(BSTR)), (1, 10))
        pid = p["native_request"]["expected_process_id"]
        sw, _ = connect_solidworks(process_id=pid, launch_new_instance=False,
                                   wait_seconds=1)
        require(_member(sw, "GetProcessID") == pid, "Bound SOLIDWORKS PID differs")
        raw = _member(sw, "GetAddInObject", HOST_CLSID)
        require(raw is not None, "Pinned sidecar must already be loaded")
        pointer = _marshal_pywin32_unknown(raw).QueryInterface(interface)
        return pointer.QualifyCreatePocketAndIslands(request_json)



def expected_marker(n):
    return {"scope": NATIVE_SCOPE, "status": "claimed_no_replay",
            "copy": n["expected_document_path"], "sha256": n["expected_source_sha256"],
            "receipt": n["native_receipt_path"], "process_id": n["expected_process_id"],
            "process_creation_time": n["expected_process_creation_time"],
            "island_count_limit": n["island_count_limit"],
            "actions": ["CreateMillFeature2"] +
                ["AddIslandToFeature:" + x for x in n["island_sketch_names"][:n["island_count_limit"]]]}


def verify_native_durable(host, plan):
    n = plan["native_request"]
    recorded = decode(Path(n["native_receipt_path"]).read_text(encoding="utf-8-sig"))
    require(recorded == host, "Durable native receipt differs from return")
    marker = decode(Path(plan["marker_path"]).read_text(encoding="utf-8-sig"))
    expected = expected_marker(n)
    require(type(marker) is dict and set(marker) == set(expected),
            "Exact durable native marker schema required")
    for name, value in expected.items():
        require(same_path(marker[name], value) if name in ("copy", "receipt")
                else type(marker[name]) is type(value) and marker[name] == value,
                "Durable native marker differs: " + name)


def verify_header(h, n, fid, count):
    fields = {"native_id", "owner_setup_native_id", "suppressed", "volume_type",
              "shape", "axis_native", "depth_native", "taper_angle_native",
              "island_count", "sketch_count", "sketch_names"}
    require(type(h) is dict and set(h) == fields, "Exact feature header required")
    for name, value in (("native_id", fid), ("owner_setup_native_id", n["owner_setup_native_id"]),
                        ("volume_type", 2), ("shape", n["expected_shape"]),
                        ("island_count", count), ("sketch_count", count + 1)):
        require(type(h[name]) is int and h[name] == value, "Header differs: " + name)
    require(h["suppressed"] is False and h["axis_native"] == n["axis_native"]
            and finite(h["depth_native"]) and abs(h["depth_native"]-n["depth_native"]) <= 1e-8
            and finite(h["taper_angle_native"]) and h["taper_angle_native"] == 0
            and h["sketch_names"] == [n["outer_sketch_name"]] + n["island_sketch_names"][:count],
            "Feature scalar/frame/sketch readback differs")


def same_fingerprint(actual, expected):
    require(type(actual) is dict and set(actual) == {"feature_tree", "solids"}
            and actual["feature_tree"] == expected["feature_tree"],
            "Unexpected CAD feature tree delta")
    require(type(actual["solids"]) is list
            and len(actual["solids"]) == len(expected["solids"]), "Body count changed")
    for old, new in zip(expected["solids"], actual["solids"]):
        require(type(new) is dict and set(new) == {"box_m", "mass_raw"},
                "Solid fingerprint schema changed")
        for name in ("box_m", "mass_raw"):
            require(type(new[name]) is list and len(new[name]) == len(old[name])
                    and all(finite(v) and (v == w if name == "box_m" else
                            math.isclose(v, w, rel_tol=1e-10, abs_tol=0.0))
                            for v,w in zip(new[name],old[name])),
                    "Solid fingerprint changed")


def verify_snapshot(s, n, fid, *, before):
    fields = {"path", "needs_save", "sw_configuration", "cam_configuration",
              "feature_count", "feature_ids", "operation_count", "cad_fingerprint", "sketches"}
    require(type(s) is dict and set(s) == fields, "Exact native inventory snapshot required")
    require(same_path(s["path"], n["expected_document_path"])
            and type(s["needs_save"]) is bool and (not before or not s["needs_save"])
            and s["sw_configuration"] == n["expected_sw_configuration"]
            and s["cam_configuration"] == n["expected_cam_configuration"],
            "Snapshot document/configuration differs")
    require(type(s["feature_count"]) is int and s["feature_count"] == (0 if before else 1)
            and s["feature_ids"] == ([] if before else [fid])
            and type(s["operation_count"]) is int and s["operation_count"] == 0,
            "Unexpected feature/operation inventory delta")
    same_fingerprint(s["cad_fingerprint"], n["expected_cad_fingerprint"])
    sketches = s["sketches"]
    names = [n["outer_sketch_name"]] + n["island_sketch_names"]
    require(type(sketches) is list and len(sketches) == 5,
            "Five actual source sketches required")
    for index, row in enumerate(sketches):
        require(type(row) is dict and set(row) == {"name", "segment_count", "segment_types",
                                                 "model_to_sketch_transform"}
                and row["name"] == names[index] and type(row["segment_count"]) is int
                and row["segment_count"] == (1 if index == 0 else 4)
                and row["segment_types"] == ([1] if index == 0 else [0,0,1,1]),
                "Source sketch identity/shape changed")
        transform = row["model_to_sketch_transform"]
        require(type(transform) is list and len(transform) == 16
                and all(finite(v) for v in transform), "Finite native sketch transform required")


def verify_chains(chains, n):
    require(type(chains) is dict and set(chains) == {"indexed_chains", "read_complete",
            "physical_geometry_verified", "universal_index_base_verified"}
            and chains["read_complete"] is True
            and chains["physical_geometry_verified"] is False
            and chains["universal_index_base_verified"] is False,
            "Bounded analytic chain readback required")
    rows = chains["indexed_chains"]
    names = [n["outer_sketch_name"]] + n["island_sketch_names"][:n["island_count_limit"]]
    require(type(rows) is list and len(rows) == len(names), "Exact requested chain count required")
    for index, row in enumerate(rows):
        require(type(row) is dict and set(row) == {"native_index", "name", "curves", "read_complete"}
                and type(row["native_index"]) is int and row["native_index"] == index
                and row["name"] == names[index] and row["read_complete"] is True,
                "Indexed chain binding differs")
        curves = row["curves"]
        require(type(curves) is list and len(curves) == (1 if index == 0 else 4),
                "Exact requested curve count required")
        for j, curve in enumerate(curves):
            require(type(curve) is dict and type(curve.get("index")) is int
                    and curve["index"] == j and type(curve.get("curve_type")) is int,
                    "Curve index/type required")
            kind = curve["curve_type"]
            geometry = {0: {"start_native", "end_native"},
                        1: {"start_native", "end_native", "mid_native", "centre_native",
                            "radius_native", "normal_native", "sense_raw"},
                        2: {"centre_native", "radius_native", "normal_native", "direction_raw"}}
            require(kind in geometry and set(curve) == {"index", "curve_type"} | geometry[kind],
                    "Exact analytic curve schema required")
            for name, value in curve.items():
                if name.endswith("_native") and name != "radius_native":
                    require(type(value) is list and len(value) == 3 and all(finite(v) for v in value),
                            "Finite curve vector required")
                elif name == "radius_native":
                    require(finite(value) and value > 0, "Positive curve radius required")
            require(kind != 2 or index == 0, "Circular curve only belongs to outer profile")
        require([c["curve_type"] for c in curves] == [2] if index == 0
                else sorted(c["curve_type"] for c in curves) == [0,0,1,1],
                "Unexpected analytic profile types")

def validate_host(host, plan):
    p, n = plan["params"], plan["native_request"]
    require(type(host) is dict and type(host.get("schema_version")) is int
            and host["schema_version"] == 1 and host.get("scope") == NATIVE_SCOPE
            and host.get("engine_version") == "explicit-island-owner-sta-1",
            "Fixed native protocol differs")
    require(type(host.get("process_id")) is int
            and host["process_id"] == n["expected_process_id"]
            and finite(host.get("process_creation_time"))
            and abs(host["process_creation_time"]-n["expected_process_creation_time"]) <= 0.001
            and host.get("host_module_version_id") == n["expected_host_module_version_id"]
            and same_path(host.get("host_assembly_location"), p["host_dll_path"]),
            "Loaded sidecar identity/lifetime differs")
    require(host.get("status") in ("error", "uncertain", "islands_observed_ram_only"),
            "Unknown native terminal status")
    for name in ("Save_attempted", "GOP_attempted", "GTP_attempted", "AFR_attempted",
                 "model_saved", "production_qualified", "machining_eligible",
                 "physical_depth_verified", "world_profile_placement_verified",
                 "automatic_retry", "persistence_qualified"):
        require(host.get(name) is False, "Native command exceeded scope: " + name)
    if host["status"] != "islands_observed_ram_only":
        require(host.get("readback_verified") is False,
                "Native failure cannot claim verification")
        require(type(host.get("mutation_attempted")) is bool,
                "Native mutation evidence required")
        if host["mutation_attempted"]:
            require(host["status"] == "uncertain", "Dispatched native failure must remain uncertain")
            verify_native_durable(host, plan)
        return False
    require(host.get("stage") == "finished" and host.get("readback_verified") is True
            and host.get("source_unchanged") is True
            and host.get("native_dispatch_pending") is False,
            "Incomplete native observation")
    require(type(host.get("owner_thread_id")) is int and host["owner_thread_id"] > 0
            and type(host.get("current_thread_id")) is int
            and host["current_thread_id"] == host["owner_thread_id"]
            and host.get("apartment") == "STA", "Same actual owner STA required")
    require(host.get("request_binding") == n, "Native result request binding differs")
    require(type(host.get("island_count_limit")) is int
            and host["island_count_limit"] == n["island_count_limit"],
            "Native result count differs from request")
    require(not any(k in host for k in ("hresult", "error_type", "message",
                                        "cleanup_error", "failed_stage")),
            "Native success contains an unresolved error")
    for name in ("mutation_attempted", "create_attempted", "create_returned",
                 "add_attempted", "add_returned", "add_return_value"):
        require(host.get(name) is True, "Missing native stage: " + name)
    actions = host.get("actions")
    expected = expected_marker(n)["actions"]
    require(type(actions) is list and len(actions) == len(expected),
            "Exact bounded native action sequence required")
    for i, action in enumerate(actions):
        fields = {"name", "attempted", "pending", "returned",
                  "return_is_object" if i == 0 else "return_value"}
        require(type(action) is dict and set(action) == fields
                and action["name"] == expected[i] and action["attempted"] is True
                and action["pending"] is False and action["returned"] is True
                and action["return_is_object" if i == 0 else "return_value"] is True,
                "Native action did not return strict success in declared order")
    fid = host.get("new_feature_native_id")
    require(type(fid) is int and 0 < fid < 2**31
            and fid not in (n["owner_setup_native_id"], n["operation_setup_native_id"]),
            "Actual fresh feature identity required")
    verify_header(host["after_create_header"], n, fid, 0)
    headers = host["after_add_headers"]
    require(type(headers) is list and len(headers) == n["island_count_limit"],
            "One header readback per requested island required")
    for index, header in enumerate(headers, 1):
        verify_header(header, n, fid, index)
    verify_snapshot(host["before"], n, fid, before=True)
    verify_snapshot(host["after"], n, fid, before=False)
    require(host["before"]["sketches"] == host["after"]["sketches"],
            "Saved source sketch metadata changed during CAM mutation")
    verify_chains(host["bounded_chain_readback"], n)
    messages = host["messages"]
    require(type(messages) is dict and messages.get("subscribed") is True
            and messages.get("disconnected") is True and messages.get("active") is False
            and type(messages.get("event_count")) is int and messages["event_count"] == 0
            and messages.get("events") == [] and type(messages.get("overflow")) is int
            and messages["overflow"] == 0 and type(messages.get("callback_error_count")) is int
            and messages["callback_error_count"] == 0 and messages.get("cleanup_error") is None
            and messages.get("policy") == "vendor_default", "Quiet closed CAM event transport required")
    require(finite(host.get("elapsed_ms")) and host["elapsed_ms"] >= 0,
            "Native elapsed time required")
    verify_native_durable(host, plan)
    return True


def run(params, *, backend=None):
    from scripts.sw_cam_generation import _write_receipt
    plan = prepare(params)
    p, n = plan["params"], plan["native_request"]
    engine = backend or NativeBackend(p)
    out = Path(p["receipt_path"])
    r = {"scope": SCOPE, "status": "prepared", "phase": "prepared",
         "request": p, "pins": plan["pins"], "native_request": n,
         "mutation_attempted": False, "native_call_attempted": False,
         "native_dispatch_pending": False, "batch_calls": 0,
         "readback_verified": False, "model_saved": False,
         "Save_attempted": False, "GOP_attempted": False, "GTP_attempted": False,
         "automatic_retry": False, "machining_eligible": False,
         "production_qualified": False,
         "attempt_marker_meaning": "Client dispatch intent; native receipt flags establish actual CAM entry."}
    _write_receipt(out, r, create=True)
    started = time.perf_counter()
    try:
        before = engine.owner()
        check_owner(before, n)
        r["owner_before"] = before
        check_pins(plan["pins"])
        require(not Path(plan["marker_path"]).exists(), "Host attempt already exists")
        intent = {"scope": SCOPE, "status": "claimed_no_replay",
                  "copy": n["expected_document_path"], "sha256": n["expected_source_sha256"],
                  "process_id": n["expected_process_id"],
                  "process_creation_time": n["expected_process_creation_time"],
                  "native_receipt_path": n["native_receipt_path"], "receipt_path": str(out)}
        _write_receipt(Path(plan["client_marker_path"]), intent, create=True)
        r.update(phase="single_owner_sta_call", native_call_attempted=True,
                 mutation_attempted=True, native_dispatch_pending=True, batch_calls=1)
        _write_receipt(out, r)
        text = engine.invoke_once(json.dumps(n, ensure_ascii=False, allow_nan=False))
        host = decode(text)
        r["host_response"] = host
        r["native_dispatch_pending"] = False
        accepted = validate_host(host, plan)
        after = engine.owner()
        check_owner(after, n)
        require(after == before, "Owned process identity changed")
        r["owner_after"] = after
        check_pins(plan["pins"])
        r.update(status="islands_observed_ram_only" if accepted else host["status"],
                 phase="finished", readback_verified=accepted)
    except Exception as exc:
        r.update(status="uncertain" if r["native_call_attempted"] else "error",
                 phase="finished", readback_verified=False,
                 issue={"type": type(exc).__name__, "message": str(exc)})
    r["elapsed_seconds"] = time.perf_counter() - started
    try:
        _write_receipt(out, r)
    except Exception:
        r.update(status="uncertain" if r["native_call_attempted"] else "error",
                 readback_verified=False, receipt_write_failed=True)
        raise
    return r


def sealed_payload(path, expected_sha, process_id):
    absolute(path)
    sha(expected_sha)
    raw, _ = read_pin(path, expected_sha)
    require(type(raw) is dict and set(raw) == {"action", "params"}
            and raw["action"] == ACTION, "Exact fixed qualification action required")
    p = validate_params(raw["params"])
    require(type(process_id) is int and process_id == p["native_request"]["expected_process_id"],
            "Sealed request differs from explicitly selected process")
    outputs = [p["receipt_path"], p["native_request"]["native_receipt_path"],
               str(marker_path(p["native_request"])), str(client_marker_path(p["native_request"]))]
    require(all(not same_path(path, x) for x in outputs), "Sealed request aliases output")
    return raw


def dispatch_request(request, *, validate_only=False, backend=None):
    require(type(request) is dict and set(request) == {"action", "params"}
            and request["action"] == ACTION, "Exact fixed qualification action required")
    require(type(validate_only) is bool, "Strict validation flag required")
    if validate_only:
        plan = prepare(request["params"])
        return {"status": "validated_offline", "native_called": False,
                "native_request": plan["native_request"], "pins": plan["pins"],
                "marker_path": plan["marker_path"],
                "client_marker_path": plan["client_marker_path"],
                "source_authority_verified": True, "save_authorized": False,
                "GOP_authorized": False, "GTP_authorized": False}
    from scripts.sw_operation_guard import solidworks_operation_lock
    p = validate_params(request["params"])
    with solidworks_operation_lock(timeout_seconds=1,
                                    process_id=p["native_request"]["expected_process_id"]):
        return run(p, backend=backend)



LOAD_FIELDS = {"process_id", "expected_process_creation_time",
               "expected_document_path", "expected_source_sha256",
               "expected_sw_configuration", "expected_needs_save",
               "host_dll_path", "host_dll_sha256", "host_tlb_path",
               "host_tlb_sha256", "expected_host_module_version_id",
               "module_sha256", "receipt_path", "acknowledge_host_load"}


def load_parameters(params):
    require(type(params) is dict and set(params) == LOAD_FIELDS,
            "Exact fixed host load parameters required")
    p = deepcopy(params)
    require(type(p["process_id"]) is int and 0 < p["process_id"] < 2**31,
            "Strict owned process required")
    require(finite(p["expected_process_creation_time"])
            and p["expected_process_creation_time"] > 0, "Exact lifetime required")
    for name in ("expected_document_path", "host_dll_path", "host_tlb_path",
                 "receipt_path"):
        absolute(p[name])
    for name in ("expected_source_sha256", "host_dll_sha256", "host_tlb_sha256",
                 "module_sha256"):
        sha(p[name])
    require(p["module_sha256"] == digest(__file__), "Exact wrapper pin required")
    require(type(p["expected_host_module_version_id"]) is str
            and str(uuid.UUID(p["expected_host_module_version_id"]))
            == p["expected_host_module_version_id"], "Canonical loaded MVID required")
    require(type(p["expected_sw_configuration"]) is str
            and 0 < len(p["expected_sw_configuration"]) <= 1024
            and type(p["expected_needs_save"]) is bool, "Exact current document required")
    require(p["acknowledge_host_load"] is True, "Explicit fixed sidecar load required")
    require(Path(p["expected_document_path"]).suffix.casefold() == ".sldprt"
            and Path(p["host_dll_path"]).suffix.casefold() == ".dll"
            and Path(p["host_tlb_path"]).suffix.casefold() == ".tlb"
            and Path(p["receipt_path"]).suffix.casefold() == ".json",
            "Exact part/DLL/TLB/JSON extensions required")
    return p


def load_pins(p):
    pins = [{"path": p[a], "sha256": p[b]} for a, b in (
        ("expected_document_path", "expected_source_sha256"),
        ("host_dll_path", "host_dll_sha256"), ("host_tlb_path", "host_tlb_sha256"))]
    pins.append({"path": str(Path(__file__).resolve()), "sha256": p["module_sha256"]})
    require(len({key(x["path"]) for x in pins}) == len(pins), "Load pins may not alias")
    return pins


def load_owner(owner, p):
    check_owner(owner, {"expected_process_id": p["process_id"],
                       "expected_process_creation_time": p["expected_process_creation_time"]})


def load_document(doc, p):
    require(type(doc) is dict and set(doc) == {"path", "title", "type",
                                             "needs_save", "configuration"},
            "Exact load document readback required")
    require(same_path(doc["path"], p["expected_document_path"])
            and type(doc["type"]) is int and doc["type"] == 1
            and type(doc["needs_save"]) is bool
            and doc["needs_save"] == p["expected_needs_save"]
            and doc["configuration"] == p["expected_sw_configuration"]
            and type(doc["title"]) is str and 0 < len(doc["title"]) <= 4096,
            "Current document changed during load")


def validate_status(status, p):
    fields = {"schema_version", "status", "scope", "process_id",
              "process_creation_time", "host_module_version_id",
              "host_assembly_location", "owner_thread_id", "current_thread_id",
              "apartment", "dispatcher_ready", "native_calls", "visible_ui_created"}
    require(type(status) is dict and set(status) == fields
            and type(status["schema_version"]) is int and status["schema_version"] == 1
            and status["status"] == "connected" and status["scope"] == NATIVE_SCOPE,
            "Exact connected sidecar status required")
    require(type(status["process_id"]) is int and status["process_id"] == p["process_id"]
            and finite(status["process_creation_time"])
            and abs(status["process_creation_time"] - p["expected_process_creation_time"]) <= 0.001,
            "Actual sidecar process lifetime differs")
    require(status["host_module_version_id"] == p["expected_host_module_version_id"]
            and same_path(status["host_assembly_location"], p["host_dll_path"]),
            "Actual loaded sidecar MVID/location differs")
    require(type(status["owner_thread_id"]) is int and status["owner_thread_id"] > 0
            and type(status["current_thread_id"]) is int
            and status["current_thread_id"] == status["owner_thread_id"]
            and status["apartment"] == "STA" and status["dispatcher_ready"] is True,
            "Actual owner STA status required")
    require(type(status["native_calls"]) is int and status["native_calls"] == 0
            and status["visible_ui_created"] is False, "Load-only scope differs")


class LoaderBackend:
    """Reusable native LoadAddIn path; no CAM object or CAM call."""
    def __init__(self, p):
        self.p = p
        self.sw = None

    def owner(self):
        from scripts.sw_executable_launch import _process_identity
        return _process_identity(self.p["process_id"])

    def application(self):
        from scripts.sw_cam import _member
        from scripts.sw_connect import connect_solidworks
        if self.sw is None:
            self.sw, _ = connect_solidworks(process_id=self.p["process_id"],
                                            launch_new_instance=False, wait_seconds=1)
        require(_member(self.sw, "GetProcessID") == self.p["process_id"],
                "Bound SOLIDWORKS PID differs")
        return self.sw

    def document(self):
        from scripts.sw_cam import _member
        app = self.application()
        docs = _member(app, "GetDocuments")
        require(type(docs) in (list, tuple) and len(docs) == 1,
                "Exactly one current owned document required")
        doc = _member(app, "ActiveDoc")
        require(doc is not None and same_path(_member(docs[0], "GetPathName"),
                                               self.p["expected_document_path"]),
                "Current sole document differs")
        config = _member(_member(doc, "ConfigurationManager"), "ActiveConfiguration")
        return {"path": _member(doc, "GetPathName"), "title": _member(doc, "GetTitle"),
                "type": _member(doc, "GetType"), "needs_save": bool(_member(doc, "GetSaveFlag")),
                "configuration": _member(config, "Name")}

    def already_loaded(self):
        from scripts.sw_cam import _member
        return _member(self.application(), "GetAddInObject", HOST_CLSID) is not None

    def load_once(self):
        from scripts.sw_cam import _member
        return _member(self.application(), "LoadAddIn", self.p["host_dll_path"])

    def status_once(self):
        from ctypes import POINTER
        from comtypes import BSTR, typeinfo
        from comtypes.client import GetModule
        from scripts.sw_cam import _member
        from scripts.sw_cam_comtypes import _marshal_pywin32_unknown
        from scripts.sw_cam_pocket_rough_apply import require_abi
        library = typeinfo.LoadTypeLibEx(self.p["host_tlb_path"], typeinfo.REGKIND_NONE)
        attr = library.GetLibAttr()
        require(str(attr.guid).upper() == HOST_LIBID
                and (attr.wMajorVerNum, attr.wMinorVerNum) == (1, 0), "Fixed sidecar TLB required")
        interface = GetModule(library).ICamExplicitIslandQualification
        require(str(interface._iid_).upper() == INTERFACE_IID, "Fixed sidecar IID required")
        methods = [m for m in interface._methods_ if m.name == "GetHostStatus"]
        require(len(methods) == 1, "Unique fixed status method required")
        require_abi(methods[0], 1, (POINTER(BSTR),), (10,))
        raw = _member(self.application(), "GetAddInObject", HOST_CLSID)
        require(raw is not None, "Loaded fixed sidecar object absent")
        pointer = _marshal_pywin32_unknown(raw).QueryInterface(interface)
        return pointer.GetHostStatus()


def run_load(params, *, backend=None):
    from scripts.sw_cam_generation import _write_receipt
    p = load_parameters(params)
    pins = load_pins(p)
    check_pins(pins)
    out = Path(p["receipt_path"])
    require(out.parent.is_dir() and not out.exists() and not out.is_symlink()
            and key(out) not in {key(x["path"]) for x in pins},
            "Fresh load receipt required")
    engine = backend or LoaderBackend(p)
    r = {"scope": "MILL_ISLAND_OWNER_STA_HOST_LOAD_V1", "status": "prepared",
         "phase": "prepared", "request": p, "pins": pins, "host_load_attempted": False,
         "load_calls": 0, "status_calls": 0, "native_dispatch_pending": False,
         "readback_verified": False, "loaded_mvid_verified": False,
         "document_unchanged_verified": False, "CAM_calls": 0, "model_saved": False,
         "Save_attempted": False, "GOP_attempted": False, "GTP_attempted": False,
         "automatic_retry": False}
    _write_receipt(out, r, create=True)
    started = time.perf_counter()
    try:
        before_owner = engine.owner()
        load_owner(before_owner, p)
        r["owner_before"] = before_owner
        before = engine.document()
        load_document(before, p)
        r["document_before"] = before
        require(engine.already_loaded() is False, "Sidecar already loaded; no repeat load")
        check_pins(pins)
        r.update(phase="load", host_load_attempted=True, load_calls=1,
                 native_dispatch_pending=True)
        _write_receipt(out, r)
        returned = engine.load_once()
        r.update(load_result=returned, native_dispatch_pending=False)
        require(type(returned) is int and returned == 0, "Exact LoadAddIn int zero required")
        r.update(phase="status", status_calls=1)
        _write_receipt(out, r)
        status = decode(engine.status_once())
        r["host_status"] = status
        validate_status(status, p)
        after_owner = engine.owner()
        load_owner(after_owner, p)
        require(after_owner == before_owner, "Owned process lifetime changed")
        after = engine.document()
        load_document(after, p)
        require(after == before, "Current document changed during load")
        r.update(owner_after=after_owner, document_after=after)
        check_pins(pins)
        r.update(status="observed", phase="finished", readback_verified=True,
                 loaded_mvid_verified=True, document_unchanged_verified=True)
    except Exception as exc:
        r.update(status="uncertain" if r["host_load_attempted"] else "error",
                 phase="finished", readback_verified=False,
                 issue={"type": type(exc).__name__, "message": str(exc)})
    r["elapsed_seconds"] = time.perf_counter() - started
    _write_receipt(out, r)
    return r


def load_owner_sta_island_host(params):
    from scripts.sw_operation_guard import solidworks_operation_lock
    p = load_parameters(params)
    with solidworks_operation_lock(timeout_seconds=1, process_id=p["process_id"]):
        return run_load(p)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--process-id", type=int, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    payload = sealed_payload(args.request, args.request_sha256, args.process_id)
    result = dispatch_request(payload, validate_only=args.validate_only)
    require(sealed_payload(args.request, args.request_sha256, args.process_id) == payload,
            "Sealed request changed during call")
    print(json.dumps({k: result[k] for k in ("status", "phase", "batch_calls",
                     "readback_verified", "native_called", "issue") if k in result},
                     ensure_ascii=False))
    raise SystemExit(0 if result["status"] in
                     ("validated_offline", "islands_observed_ram_only") else 2)

