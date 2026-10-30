"""Shared bounded route snapshots for explicit post-edit continuations."""
from copy import deepcopy
from scripts.sw_cam_completed_gtp_wip import SavedRouteWipContext
from scripts.sw_cam_completed_sandvik_assignment import capture_assignment_snapshot, read_assignment_candidate
from scripts.sw_cam_completed_sandvik_save import read_feature_counts
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch, capture_route_batch
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam import _member
from scripts.sw_cam_rough_firstcut import require

class RouteCheckpointContext(SavedRouteWipContext):
    """Reuse ownership/file/dispatch guards, permit only declared dirty-state transitions."""
    def __init__(self, loaded, args, sw, typelib_path, app, events):
        require(loaded.get("historical_only") is not True, "Historical-only checkpoint cannot authorize native access")
        super().__init__(loaded, args, sw, typelib_path, app, events)
        self.expected_document = deepcopy(loaded["state"]["document"])
        self.allow_dirty_transition = False
    def identity(self):
        pid = _member(self.sw, "GetProcessID")
        require(type(pid) is int and pid == self.args["process_id"], "Owned process changed")
        self.owned()
        doc = raw_part_identity(self.sw)
        expected = deepcopy(self.expected_document)
        if self.allow_dirty_transition:
            require(type(doc.get("needs_save")) is bool, "Strict dirty state required")
            expected["needs_save"] = doc["needs_save"]
        require(doc == expected and _file_hash(self.args["expected_document_path"]) == self.args["expected_source_sha256"],
            "Current checkpoint document/source changed")
        return doc

def capture_route_checkpoint(ctx, reference_state, diagnostic):
    """Six-tuple raw snapshot; operation-specific caller must validate its permitted delta."""
    ctx.events(); doc = ctx.identity(); payload = ctx.loaded["payload"]
    common = dict(reference_state=reference_state, current_document=doc,
        source_sha256=ctx.args["expected_source_sha256"], target_feature_native_id=ctx.args["target_feature_native_id"],
        target_operation_native_id=ctx.args["target_operation_native_id"], diagnostic=diagnostic)
    if ctx.loaded["read_mode"] == "qualified_batch":
        require(ctx.loaded.get("qualification") is not None, "Original qualified reader provenance required")
        def factory(native, reference):
            return ScopedCamRouteReadBatch(ctx.sw, ctx.typelib_path, native_context=native, reference_state=reference,
                process_id=ctx.args["process_id"], expected_document=doc, source_sha256=ctx.args["expected_source_sha256"],
                evidence_pins=ctx.loaded["pins"], verify_evidence=ctx.files, verify_owned_process=ctx.owned,
                check_events=ctx.events, max_native_calls=900)
        result = capture_route_batch(ctx.app, ctx.sw, strong_guard_factory=ctx.guard, batch_factory=factory,
            check_events=ctx.events, expected_candidate_tool_native_id=ctx.args["expected_candidate_tool_native_id"],
            reference_candidate=payload["candidate"], observation_pin=ctx.loaded["observation_pin"], **common)
        diagnostic.update(read_mode="qualified_batch_checkpoint", original_qualification_rebound=False,
            original_qualification_pin=ctx.loaded["qualification"]["pin"])
    else:
        with ctx.guard() as guard:
            state, native, levels, firstcut, entry = capture_assignment_snapshot(ctx.app,
                read=guard.read, typed=guard.typed, boundary=ctx.events, **common)
            candidate = read_assignment_candidate(native, ctx.app, ctx.sw, read=guard.read, typed=guard.typed,
                expected_candidate_tool_native_id=ctx.args["expected_candidate_tool_native_id"],
                reference=payload["candidate"], observation_pin=ctx.loaded["observation_pin"], firstcut=firstcut,
                diagnostic=diagnostic.setdefault("candidate", {}))
        result = state, native, levels, firstcut, entry, candidate
        diagnostic["strong_guard"] = guard.summary()
    state, native, levels, firstcut, entry, candidate = result
    with ctx.guard() as guard:
        counts = read_feature_counts(native, guard.read, guard.typed)
    require(counts == [dict(native_id=r["native_id"], feature_count=r["feature_count"]) for r in reference_state["feature_setups"]],
        "Feature/setup counts changed")
    require(state["document"] == ctx.identity() == doc and state["saved_file_sha256"] == ctx.args["expected_source_sha256"],
        "Snapshot document/source changed")
    ctx.events(); ctx.files()
    diagnostic.update(capture_complete=True, fresh_feature_counts=counts,
        geometry_reference_pin=ctx.loaded["pin"], full_geometry_rechecked=False)
    return result

def snapshot_payload(result):
    state, _, levels, _, entry, candidate = result
    return dict(context=deepcopy(state), candidate=deepcopy(candidate), levels=deepcopy(levels), entry=deepcopy(entry))

def checkpoint_from_snapshot(loaded, snapshot, *, pin=None):
    """Keep validated provenance while carrying the caller-verified current snapshot."""
    keys = ("pin", "pins", "ownership", "qualification", "observation_pin", "read_mode", "base_saved_pin")
    result = {key:deepcopy(loaded[key]) for key in keys if key in loaded}
    result["state"] = deepcopy(snapshot["context"])
    result["payload"] = {key:deepcopy(snapshot[key]) for key in ("candidate", "levels", "entry")}
    result["source_sha256"] = snapshot["context"]["saved_file_sha256"]
    if pin is not None: result["pin"] = deepcopy(pin)
    return result



def load_completed_entry_checkpoint(*args, **kwargs):
    """Expose the strict CAS loader without accepting arbitrary checkpoint scopes."""
    from scripts.sw_cam_rough_entry_cas import load_completed_entry_checkpoint as load
    return load(*args, **kwargs)
