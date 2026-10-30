"""Bounded saved-route evidence cutover; no native or archived-code execution."""
from base64 import b64encode, b64decode
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
import json
import ntpath
import os
from pathlib import Path
import re

from scripts.sw_cam_mill_stock_export_evidence import _decode, _receipt_bytes, _signature
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_route_batch_qualified_capture import canonical_evidence_pins
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_operation_guard import check_document_target

SCOPE = "SAVED_ROUTE_MANIFEST_94_95_96_V1"
MAX_FILES = 64
MAX_BLOB = 4 * 1024 * 1024
MAX_RAW = 8 * 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
CHUNK = 12288
HASH = re.compile(r"[0-9a-f]{64}\Z")
MARKER = re.compile(r".*_[0-9a-f]{64}(?:\.[^.]+)?\.json\Z", re.I)
# These are the current bounded finish/operation-read path, not every imported module.
RUNTIME_NAMES = (
    "sw_cam", "sw_cam_generation", "sw_cam_thread", "sw_cam_turn_tool",
    "sw_cam_comtypes", "sw_cam_dispatch_guard", "sw_cam_read_batch_guard",
    "sw_cam_route_read_batch", "sw_cam_route_read_batch_qualification",
    "sw_cam_route_batch_qualified_capture", "sw_cam_route_checkpoint",
    "sw_cam_completed_gtp_wip", "sw_cam_completed_sandvik_save",
    "sw_cam_completed_sandvik_assignment",
    "sw_cam_mill_route_context", "sw_cam_mill_levels", "sw_cam_rough_entry_parameters",
    "sw_cam_rough_firstcut", "sw_cam_existing_sandvik", "sw_cam_mill_qualification",
    "sw_cam_circle_lifecycle_evidence", "sw_cam_mill_feature_context",
    "sw_cam_stock_mesh_compare", "sw_cam_document_unit_scope", "sw_cam_mill_inventory",
    "sw_cam_events", "sw_cam_route_entry_continuation", "sw_operation_guard",
    "sw_executable_launch", "sw_cam_mill_stock_export_evidence",
    "sw_cam_mill_selected_plan_evidence", "sw_cam_finish_observation",
    "sw_cam_finish_lead_observation",
)
OBS_SCOPE = "SAVED_ROUTE_FINISH_OBSERVATION_V1"
LEAD_SCOPE = "SAVED_ROUTE_FINISH_LEAD_OBSERVATION_V1"
SAVE_SCOPE = "MILL_ENTRY_EDIT_WORKING_SAVE_V1"
NO_ACTION = ("mutation_attempted", "GTP_attempted", "GOP_attempted", "AFR_attempted",
             "save_attempted", "model_saved", "export_attempted", "simulation_attempted",
             "setter_attempted", "native_dispatch_pending", "automatic_retry")
# These completed once engines are unreachable from this cutover's only consumers.
# Their marker bytes remain archived; unknown/uncertain markers remain live.
CONSUMER_SCOPE = "STRAIGHT_FINISH_RECIPE_AND_ROUTE_V1"
HISTORICAL_MARKER_SCOPES = {
    "EXISTING_HOLDER_SHAPE_SINGLE_CAS_V1", "EXISTING_NONCUTTING_EXPORT_CONTINUATION_V1",
    "MILL_COMPLETED_SANDVIK_DRAFT_SAVE_V1", "MILL_SANDVIK_ROUGH_ASSIGNMENT_V1",
    "MILL_ASSIGNED_SANDVIK_INITIAL_GTP_V1", "MILL_COMPLETED_GTP_WORKING_SAVE_V1",
    "MILL_COMPLETED_GTP_WIP_EXPORT_V1", "MILL_ROUGH_ENTRY_CAS_V1",
    "MILL_ENTRY_EDIT_GTP_V1", "MILL_ENTRY_EDIT_GENERIC_CL_V1", "MILL_ENTRY_EDIT_WORKING_SAVE_V1",
}


def _marker_role(raw):
    data = _json_blob(raw)
    completed = (data.get("scope") in HISTORICAL_MARKER_SCOPES
                 and data.get("phase") == "finished"
                 and data.get("status") in ("review_required", "export_observed")
                 and data.get("native_dispatch_pending", False) is False
                 and data.get("save_pending", False) is False
                 and data.get("automatic_replay", False) is False)
    return "historical_replay_marker" if completed else "active_replay_marker"


CURRENT_KEYS = ("state", "payload", "ownership", "qualification", "observation_pin", "read_mode")
PRIMARY_PARENT_FIELDS = {
    SAVE_SCOPE: "parent_checkpoint_pin",
    "MILL_ENTRY_EDIT_GENERIC_CL_V1": "parent_checkpoint_pin",
    "MILL_ENTRY_EDIT_GTP_V1": "parent_checkpoint_pin",
    "MILL_ROUGH_ENTRY_CAS_V1": "saved_gtp_pin",
    OBS_SCOPE: "checkpoint_pin", LEAD_SCOPE: "observation_pin",
    "MILL_COMPLETED_GTP_WORKING_SAVE_V1": "gtp_pin",
    "MILL_ASSIGNED_SANDVIK_INITIAL_GTP_V1": "assignment_pin",
    "MILL_SANDVIK_ROUGH_ASSIGNMENT_V1": "saved_draft_pin",
}


def _lex(path):
    require(type(path) is str and ntpath.isabs(path), "Absolute original evidence path required")
    return ntpath.normcase(ntpath.normpath(path))


def _hash(value):
    require(type(value) is str and HASH.fullmatch(value) is not None, "Exact SHA256 required")
    return value


def _bytes(pin):
    """One bounded original file read, used only while creating the cutover."""
    p = Path(pin["path"])
    require(p.is_absolute() and p.is_file() and not p.is_symlink(), "Regular evidence file required")
    canonical = p.resolve(strict=True); before = p.stat()
    require(0 <= before.st_size <= MAX_BLOB, "Evidence blob exceeds bound")
    with p.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        require(_signature(before)[:-1] == _signature(opened)[:-1], "Evidence path/handle changed")
        raw = stream.read(MAX_BLOB + 1)
        require(_signature(opened) == _signature(os.fstat(stream.fileno())), "Evidence changed during read")
    require(len(raw) == before.st_size and _signature(before)[:-1] == _signature(p.stat())[:-1]
            and canonical == p.resolve(strict=True) and not p.is_symlink(), "Evidence changed while copied")
    require(sha256(raw).hexdigest() == _hash(pin["sha256"]), "Original evidence hash differs")
    return raw, str(canonical)


def _json_blob(raw):
    return _decode(raw)


def _role(pin, raw, owned_path):
    name = ntpath.basename(pin["path"]); suffix = Path(name).suffix.lower()
    if _lex(pin["canonical_path"]) == _lex(owned_path): return "owned_session"
    if MARKER.fullmatch(name): return _marker_role(raw)
    if suffix in (".mt", ".mh"): return "current_profile_input"
    if suffix == ".py": return "historical_implementation"
    if suffix == ".json":
        data = _json_blob(raw)
        require(data.get("scope") != SCOPE and not str(data.get("scope", "")).startswith("SAVED_ROUTE_MANIFEST_"),
                "Nested route manifest is forbidden")
        # Unknown once-marker shapes stay live, never silently become historical.
        if data.get("receipt_path") and "evidence_pins" not in data:
            return "active_replay_marker"
        return "historical_evidence"
    require(suffix in (".stl", ".stp", ".cl"), "Unclassified historical evidence type")
    return "historical_artifact"


def _archive(pins, owned_path):
    require(type(pins) is list and 1 <= len(pins) <= MAX_FILES, "Bounded original pin closure required")
    refs = []; blobs = {}; total = 0
    for pin in pins:
        raw, canonical = _bytes(pin); h = sha256(raw).hexdigest()
        ref = dict(original_pin=deepcopy(pin), path=pin["path"], canonical_path=canonical,
                   sha256=h, bytes=len(raw))
        ref["role"] = _role(ref, raw, owned_path); refs.append(ref)
        if h not in blobs:
            total += len(raw); require(total <= MAX_RAW, "Archive decoded byte bound exceeded")
            blobs[h] = dict(bytes=len(raw), chunks=[b64encode(raw[i:i+CHUNK]).decode("ascii") for i in range(0, len(raw), CHUNK)])
    return dict(references=refs, blobs=blobs, decoded_bytes=total,
                coverage="existing_validated_loader_pin_closure", incidental_links="unexpanded_metadata")


def _unpack(audit):
    require(type(audit) is dict and audit.get("coverage") == "existing_validated_loader_pin_closure"
            and audit.get("incidental_links") == "unexpanded_metadata", "Exact audit coverage required")
    refs, blobs = audit["references"], audit["blobs"]
    require(type(refs) is list and 1 <= len(refs) <= MAX_FILES and type(blobs) is dict
            and 1 <= len(blobs) <= MAX_FILES, "Bounded unique archive required")
    decoded = {}; total = 0; seen = set(); used = set()
    for h, item in blobs.items():
        _hash(h); size = item.get("bytes"); chunks = item.get("chunks")
        require(type(size) is int and 0 <= size <= MAX_BLOB and type(chunks) is list
                and len(chunks) <= (MAX_BLOB + CHUNK - 1) // CHUNK, "Bounded archive blob required")
        parts = []
        for index, chunk in enumerate(chunks):
            require(type(chunk) is str and 0 < len(chunk) <= 16384 and len(chunk) % 4 == 0,
                    "Bounded canonical Base64 chunk required")
            try: part = b64decode(chunk, validate=True)
            except (ValueError, TypeError) as exc: raise ValueError("Invalid archive Base64") from exc
            require(b64encode(part).decode("ascii") == chunk and len(part) <= CHUNK
                    and (index == len(chunks)-1 or len(part) == CHUNK), "Noncanonical archive chunk")
            parts.append(part)
        raw = b"".join(parts); total += len(raw)
        require(len(raw) == size and sha256(raw).hexdigest() == h and total <= MAX_RAW, "Archive blob bytes/hash differ")
        decoded[h] = raw
    for ref in refs:
        h = _hash(ref["sha256"]); key = (_lex(ref["canonical_path"]), h)
        _lex(ref["path"])
        require(key not in seen and h in decoded and ref["bytes"] == len(decoded[h]), "Duplicate/missing archive reference")
        original = ref["original_pin"]
        require(original["sha256"] == h and ref["path"] == original["path"]
                and _lex(ref["canonical_path"]) == _lex(original.get("canonical_path", original["path"]))
                and ("bytes" not in original or (type(original["bytes"]) is int and original["bytes"] == ref["bytes"])),
                "Original pin path/metadata/hash differs")
        require(ref["role"] in {"owned_session", "active_replay_marker", "current_profile_input",
                "historical_implementation", "historical_evidence", "historical_artifact", "historical_replay_marker"}, "Unknown archive role")
        if Path(ntpath.basename(ref["path"])).suffix.lower() == ".json":
            data = _json_blob(decoded[h])
            require(not str(data.get("scope", "")).startswith("SAVED_ROUTE_MANIFEST_"), "Nested route manifest")
        if MARKER.fullmatch(ntpath.basename(ref["path"])):
            require(ref["role"] == _marker_role(decoded[h]), "Replay marker classification differs")
        seen.add(key); used.add(h)
    require(used == set(blobs) and type(audit["decoded_bytes"]) is int and total == audit["decoded_bytes"],
            "Unreferenced blob or aggregate mismatch")
    return decoded


def _record(refs, decoded, pin):
    h = _hash(pin["sha256"])
    matches = [r for r in refs if r["sha256"] == h]
    require(matches and h in decoded, "Required validation edge is outside preserved closure")
    wanted = _lex(pin.get("canonical_path",pin["path"]))
    require(any(wanted in (_lex(r["path"]),_lex(r["canonical_path"])) for r in matches),
            "Validation edge original path differs")
    # SHA binds exact bytes; original/canonical path spelling is preserved separately.
    return _json_blob(decoded[h])


def _lineage(anchors, refs, decoded):
    nodes = {}; edges = []; queue = [anchors[k] for k in ("save", "finish", "leads")]
    while queue:
        pin = queue.pop(); h = pin["sha256"]
        if h in nodes: continue
        data = _record(refs, decoded, pin)
        nodes[h] = dict(sha256=h, scope=data.get("scope"), phase=data.get("phase"))
        field = PRIMARY_PARENT_FIELDS.get(data.get("scope"))
        if field:
            parent = data.get(field)
            require(type(parent) is dict and "sha256" in parent, "Missing known parent edge")
            _record(refs, decoded, parent)
            edges.append(dict(child=h, parent=parent["sha256"], field=field,
                              original_parent_pin=deepcopy(parent)))
            queue.append(parent)
    order = []; remaining = set(nodes)
    while remaining:
        ready = sorted(n for n in remaining if all(e["parent"] in order for e in edges if e["child"] == n))
        require(ready, "Cyclic validation lineage")
        order.extend(ready); remaining.difference_update(ready)
    return dict(order=order, nodes=[nodes[h] for h in order], edges=sorted(edges, key=lambda e:(e["child"],e["parent"])),
                other_archived_references="preserved_validated_pin_closure_not_recursive_link_claim")


def _validate_observation(data, state, args, scope, complete):
    require(data.get("scope") == scope and data.get("status") == "observed" and data.get("phase") == "finished"
            and data.get("read_only") is True and data.get("readback_verified") is True and data.get(complete) is True,
            "Exact finished observation required")
    require(not any(k in data for k in ("issue", "failed_phase", "receipt_write_error"))
            and all(data.get(k) is False for k in NO_ACTION), "Observation incomplete or mutated")
    for key in ("process_id", "finish_operation_native_id", "finish_tool_native_id", "target_feature_native_id"):
        require(type(data.get(key)) is int and data[key] == args[key], "Observation identity differs: " + key)
    require(data["expected_source_sha256"] == args["expected_source_sha256"]
            and data["before_context"] == data["after_context"] == state
            and data["after_cleanup_document"] == state["document"], "Observation current state differs")
    check_document_target(data["expected_document_path"], None, expected_path=args["expected_document_path"], required=True)
    clean_events(data)
    require(len(data["snapshot_diagnostics"]) == 2 and all(d.get("capture_complete") is True for d in data["snapshot_diagnostics"]),
            "Two completed operation snapshots required")


def _lead_values(leads):
    from scripts.sw_cam_finish_lead_observation import LEAD_FIELDS, decode_lead_value
    require(type(leads) is dict and set(leads) == {"lead_in", "lead_out"}, "Two exact lead records required")
    for fields in leads.values():
        require(type(fields) is dict and set(fields) == set(LEAD_FIELDS), "Exact eleven lead fields required")
        for name, row in fields.items():
            require(type(row) is dict and row.get("recorded") is True, "Unrecorded lead value")
            raw = row["raw"]
            if row.get("python_shape", {}).get("python_type") == "tuple": raw = tuple(raw)
            require(decode_lead_value(name, raw) == row, "Lead raw/type/percent mapping differs")


def _derived(anchors, refs, decoded, args):
    save = _record(refs, decoded, anchors["save"])
    finish = _record(refs, decoded, anchors["finish"])
    leads = _record(refs, decoded, anchors["leads"])
    require(save.get("scope") == SAVE_SCOPE and save.get("phase") == "finished" and save.get("status") == "review_required"
            and save.get("model_saved") is True and save.get("save_readback_verified") is True
            and save.get("readback_verified") is True and save.get("save_pending") is False
            and save.get("native_return_type") == "int" and type(save.get("native_return_value")) is int
            and save["native_return_value"] == 0, "Completed saved anchor required")
    clean_events(save)
    checkpoint = save["checkpoint"]; state = checkpoint["state"]
    require(save["checkpoint_sha256"] == _digest(checkpoint) and save["after_context"] == state
            and checkpoint["payload"] == save["after_payload"] and state["document"]["needs_save"] is False
            and checkpoint["source_sha256"] == state["saved_file_sha256"] == args["expected_source_sha256"],
            "Current saved checkpoint differs")
    require(len(state["features"]) == 19 and len(state["feature_setups"]) == 3
            and len(state["operation_setups"]) == 3 and len(state["operations"]) == state["operation_count"] == 6,
            "Exact saved route shape required")
    _validate_observation(finish, state, args, OBS_SCOPE, "detail_observation_complete")
    _validate_observation(leads, state, args, LEAD_SCOPE, "lead_observation_complete")
    require(finish["checkpoint_pin"]["sha256"] == anchors["save"]["sha256"]
            and leads["observation_pin"]["sha256"] == anchors["finish"]["sha256"], "Observation parent differs")
    require(finish["units_before"] == finish["units_after"] == leads["reused_unit_record"]
            and leads["reused_finish_details"] == finish["details"]
            and leads["reused_finish_levels"] == finish["levels"], "Supplement changed previously verified detail")
    _lead_values(leads["leads"])
    cas = [_json_blob(decoded[r["sha256"]]) for r in refs
           if Path(ntpath.basename(r["path"])).suffix.lower() == ".json"
           and _json_blob(decoded[r["sha256"]]).get("scope") == "MILL_ROUGH_ENTRY_CAS_V1"
           and "checkpoint" in _json_blob(decoded[r["sha256"]])]
    require(len(cas) == 1, "One validated entry checkpoint metadata source required")
    metadata = cas[0]["checkpoint"]
    owned = _record(refs, decoded, anchors["owned_startup"])
    require(owned.get("status") == "ok" and owned.get("phase") == "connected"
            and owned.get("process_id") == args["process_id"]
            and metadata["ownership"] == owned["process_identity"], "Copied owned-session identity differs")
    provenance = {k:deepcopy(metadata[k]) for k in CURRENT_KEYS if k not in ("state", "payload")}
    provenance["base_saved_pin"] = deepcopy(metadata.get("base_saved_pin"))
    return dict(**provenance, state=deepcopy(state), payload=deepcopy(checkpoint["payload"]),
                source_sha256=checkpoint["source_sha256"],
                finish=dict(details=deepcopy(finish["details"]), levels=deepcopy(finish["levels"]),
                            tool_summary=deepcopy(finish["tool_summary"]), unit_record=deepcopy(finish["units_after"]),
                            leads=deepcopy(leads["leads"])))


def _legacy_load(finish_pin, args):
    from scripts.sw_cam_finish_lead_observation import load_completed_finish_observation
    return load_completed_finish_observation(finish_pin["path"], finish_pin["sha256"], **args)


def build_saved_route_manifest(*, lead_receipt_path, lead_receipt_sha256, output_path, **args):
    """Offline once-only cutover; old current-source loader runs exactly once."""
    leads, lead_pin = read_pin(lead_receipt_path, lead_receipt_sha256)
    finish_pin = leads["observation_pin"]
    loaded = _legacy_load(finish_pin, args)
    require(loaded.get("historical_only") is False, "Current validated loader required")
    finish = loaded["finish_observation"]
    _, owned_pin = read_pin(args["owned_startup_receipt_path"], args["owned_startup_receipt_sha256"])
    anchors = dict(save=deepcopy(finish["checkpoint_pin"]), finish=deepcopy(finish_pin), leads=lead_pin,
                   owned_startup=owned_pin)
    pins = canonical_evidence_pins(leads["evidence_pins"], [lead_pin])
    closure = {(_lex(p.get("canonical_path", p["path"])), p["sha256"]) for p in pins}
    require(all((_lex(p.get("canonical_path", p["path"])),p["sha256"]) in closure for p in loaded["pins"]),
            "Validated loader dependency omitted by latest observation")
    owned_path = str(Path(args["owned_startup_receipt_path"]).resolve(strict=True))
    audit = _archive(pins, owned_path); decoded = _unpack(audit)
    current = _derived(anchors, audit["references"], decoded, args)
    require(current["state"] == loaded["state"] and current["payload"] == loaded["payload"],
            "Manifest derivation differs from existing validated loader")
    require(all(current[k] == loaded[k] for k in CURRENT_KEYS), "Copied context provenance differs from existing loader")
    require(current["base_saved_pin"] == loaded.get("base_saved_pin"), "Base saved provenance differs")
    binding = {k:deepcopy(args[k]) for k in ("process_id", "expected_document_path", "expected_source_sha256",
               "target_feature_native_id", "target_operation_native_id", "target_operation_setup_native_id",
               "expected_candidate_tool_native_id", "finish_operation_native_id", "finish_tool_native_id")}
    result = dict(schema_version=1, scope=SCOPE, consumer_scope=CONSUMER_SCOPE, status="validated_offline", anchors=anchors,
                  binding=binding, current=current, audit=audit, lineage=_lineage(anchors,audit["references"],decoded),
                  builder_pin=dict(path=str(Path(__file__).resolve()),sha256=_file_hash(__file__)),
                  native_calls=0, native_current_state_verified=False, production_qualified=False,
                  full_geometry_rechecked=False, original_qualification_rebound=False,
                  original_history_authority="immutable_archived_bytes_except_live_roles", automatic_replay=False)
    for p in pins: require(_file_hash(p["path"]) == p["sha256"], "Original history changed before cutover")
    require(_file_hash(args["expected_document_path"]) == args["expected_source_sha256"], "Current source changed before cutover")
    raw = json.dumps(result,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    require(len(raw) <= MAX_JSON, "Manifest exceeds unchanged receipt bound"); _decode(raw)
    target = Path(output_path)
    require(target.is_absolute() and target.suffix.lower() == ".json" and target.parent.is_dir()
            and not target.exists() and not target.is_symlink(), "Fresh absolute project-scoped manifest required")
    project = Path(args["project_root"]).resolve(strict=True)
    require(target.resolve().is_relative_to(project), "Manifest must remain inside explicit project root")
    with target.open("xb") as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    readback, pin = read_pin(str(target), sha256(raw).hexdigest())
    require(readback == result and _unpack(readback["audit"]) == decoded, "Manifest readback differs")
    return dict(pin=pin, historical_file_count=len(pins), decoded_history_bytes=audit["decoded_bytes"],
                manifest_bytes=len(raw), legacy_loader_calls=1, native_calls=0, production_qualified=False)


def _generated_runtime_path(path):
    p = Path(path).resolve(strict=True)
    require(p.stem == "_FE488661_0BD8_11D6_2012_2018CE99E55F_0_25_0", "Exact installed CAM25 typelib module required")
    module = import_module("comtypes.gen." + p.stem)
    require(Path(module.__file__).resolve(strict=True) == p, "Generated typelib path differs from loaded module")
    return p


def runtime_binding(*, generated_typelib_path, extra_runtime_paths=()):
    """Prepare explicit expected pins offline; native callers must supply reviewed output."""
    paths = [Path(__file__)] + [Path(import_module("scripts."+n).__file__) for n in RUNTIME_NAMES]
    runtime_root = Path(import_module("scripts.sw_cam").__file__).resolve().parent.parent
    paths.extend([runtime_root/"mcp-server"/"server.py", _generated_runtime_path(generated_typelib_path)])
    require(type(extra_runtime_paths) in (list,tuple) and len(extra_runtime_paths) <= 8, "Bounded reviewed consumer dependencies required")
    paths.extend(Path(p) for p in extra_runtime_paths)
    return canonical_evidence_pins([dict(path=str(p.resolve(strict=True)),sha256=_file_hash(p)) for p in paths])


def load_saved_route_manifest(path, sha256, *, runtime_pins, generated_typelib_path,
                              extra_runtime_paths=(), check_current_source=True, **args):
    """Load one pinned archive, then expose only current files to unchanged guards."""
    require(type(check_current_source) is bool, "Explicit current/historical mode required")
    data, pin = read_pin(path,sha256)
    require(data.get("schema_version") == 1 and data.get("scope") == SCOPE
            and data.get("consumer_scope") == CONSUMER_SCOPE and data.get("status") == "validated_offline",
            "Exact completed manifest required")
    for k in ("production_qualified","full_geometry_rechecked","native_current_state_verified","original_qualification_rebound","automatic_replay"):
        require(data.get(k) is False, "Unexpected manifest claim: "+k)
    require(type(data.get("native_calls")) is int and data["native_calls"] == 0, "Manifest may not perform native actions")
    for k,v in data["binding"].items():
        if k == "expected_document_path":
            check_document_target(v,None,expected_path=args[k],required=True)
        else: require(type(v) is type(args[k]) and v == args[k], "Manifest request binding differs: "+k)
    decoded = _unpack(data["audit"]); refs = data["audit"]["references"]
    require(data["lineage"] == _lineage(data["anchors"],refs,decoded), "Manifest lineage differs")
    owned_rows = [r for r in refs if r["sha256"] == data["anchors"]["owned_startup"]["sha256"]]
    require(len(owned_rows) == 1 and owned_rows[0]["role"] == "owned_session", "Owned startup must remain live")
    for r in refs:
        require(r["role"] == _role(r, decoded[r["sha256"]], owned_rows[0]["canonical_path"]), "Archive role differs from original record")
    derived = _derived(data["anchors"],refs,decoded,args)
    require(all(data["current"][k] == v for k,v in derived.items()), "Copied current state/settings differ")
    leads = _record(refs,decoded,data["anchors"]["leads"])
    expected = {(p.get("canonical_path",p["path"]).casefold(),p["sha256"]) for p in leads["evidence_pins"]}
    expected.add((data["anchors"]["leads"].get("canonical_path",data["anchors"]["leads"]["path"]).casefold(),data["anchors"]["leads"]["sha256"]))
    actual = {(r["canonical_path"].casefold(),r["sha256"]) for r in refs}
    require(actual == expected, "Manifest archive closure differs from latest verified record")
    expected_runtime = canonical_evidence_pins(runtime_pins)
    actual_runtime = runtime_binding(generated_typelib_path=generated_typelib_path,extra_runtime_paths=extra_runtime_paths)
    require({(_lex(p["path"]),p["sha256"]) for p in actual_runtime}
            == {(_lex(p["path"]),p["sha256"]) for p in expected_runtime}, "Current runtime dependency/path/hash differs")
    require(_file_hash(__file__) == data["builder_pin"]["sha256"], "Manifest validator implementation changed")
    current = deepcopy(data["current"])
    qualification = current.get("qualification")
    if current["read_mode"] == "qualified_batch":
        require(type(qualification) is dict and qualification.get("full_route_snapshot_qualified") is False,
                "Original bounded reader qualification required")
        runtime_hashes = {_lex(p["path"]):p["sha256"] for p in actual_runtime}
        for q in qualification["qualified_core_pins"]:
            require(runtime_hashes.get(_lex(q.get("canonical_path",q["path"]))) == q["sha256"],
                    "Originally qualified reader core changed")
    live = [dict(path=r["canonical_path"],sha256=r["sha256"],bytes=r["bytes"]) for r in refs
            if r["role"] in ("owned_session","active_replay_marker","current_profile_input")]
    require(sum(r["role"] == "owned_session" for r in refs) == 1, "One owned startup reference required")
    pins = canonical_evidence_pins([pin],expected_runtime,live)
    for p in pins: require(_file_hash(p["path"]) == p["sha256"], "Live manifest dependency changed or disappeared")
    if check_current_source:
        require(_file_hash(args["expected_document_path"]) == args["expected_source_sha256"], "Current source differs")
    current.update(pin=pin,pins=pins,historical_only=not check_current_source,
                   checkpoint_scope=SCOPE,source_sha256=args["expected_source_sha256"],
                   audit_provenance=dict(manifest_pin=pin,original_file_count=len(refs),lineage=data["lineage"],
                                        original_history_authority=data["original_history_authority"],
                                        original_qualification_rebound=False))
    return current
