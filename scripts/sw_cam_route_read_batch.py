"""Pilot bounded CAM route reads; strong dispatch remains a separate scope.

Roots must come from resolve_existing_context under ScopedCamDispatchGuard.
Binding checks retained objects' documented numeric IDs, never addresses of
reacquired COM wrappers. This does not establish an atomic native snapshot.
"""
from copy import deepcopy
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch

ROUTE_READ_MEMBERS = frozenset({
    "GetCWObjectID", "GetCWObjectFromID", "Count", "Item",
    "IGetEnumOpSetups", "IGetEnumOperations", "OpernType", "Suppressed",
    "GetIsToolpathGenerated", "IGetAllFeatures", "IGetEnumToolpaths", "RecordCount",
    "IGetTool", "IGetToolcrib", "GetAllTools", "IsMillTool", "ToolType",
    "CutDiameter", "Protrusion", "GetToolName", "ShankDia", "CutLength",
    "OverallLength", "TipOffset", "TipLength", "Flutes", "MillUDToolOutputType",
    "IGetMillToolHolder", "GetHolderShape", "GetHolderId", "GetHolderNumber",
    "GetName", "GetHolderTopDia", "GetHolderBottomDia", "GetHolderOverallLength",
    "GetHolderBottomLength", "GetProtrusion", "GetTypeOfFirstCutZ",
    "GetToolpathParam", "GetToolpathParameters", "GetMachiningDepth",
    "GetOverrideMachiningDepth", "GetSetupParameters", "GetCoordinates",
    "GetEntryExitType", "GetEntryHoleAttr", "GetRampAngle", "GetSpiralRadius",
    "GetSpiralPitch", "GetHoleCentreEntry", "GetEntryLengthAngle", "GetEntryLength",
    "GetEntryAngle", "GetAutoCorrectEntryLengthAngle", "GetEntryStartPtX",
    "GetEntryStartPtY", "DepthMethod", "DepthAllow", "FirstDepthAmt",
    "SbsqDepthAmt", "FinCutAmt", "GetStartDepth", "GetSubsequentDepthAmount",
    "PocketMethod", "SideAllow", "GetStepOver", "GetZAllowance", "GetContainType",
    "GetContainAllowance", "GetXYClearance", "GetToolDiameterPercent",
    "IGetNCParam", "GetClrPlaneUseSetupStatus", "GetRpdPlaneUseSetupStatus",
    "GetRetractType",
})
ROUTE_READ_INTERFACES = frozenset({
    "ICWDispatchCollection", "ICWBaseOpSetup", "ICWOperation", "ICWMillOperation",
    "ICWMillOperation3", "ICWToolpath", "ICWFeature", "ICWToolcrib4", "ICWTool",
    "ICWMillUDTool", "ICWMillToolHolder", "ICWToolpathParam", "ICWPosition",
    "ICWUnitVector", "ICWRghMillOp", "ICWNCParam",
})


class RetainedRouteBinding:
    """Recheck a strong-resolved document graph, without global CAM reacquisition."""
    def __init__(self, native, reference_state, check_events):
        if type(native) is not dict or set(native) != {"doc", "machine", "operations"}:
            raise ValueError("Exact existing resolved context required")
        if not callable(check_events):
            raise ValueError("Per-read event verifier required")
        self.check_events = check_events
        rows = reference_state["operations"]
        if type(rows) is not list or not 1 <= len(rows) <= 32:
            raise ValueError("Bounded reference operation inventory required")
        ids = tuple(row["native_id"] for row in rows)
        if (any(type(i) is not int or not 0 < i < 2**32 for i in ids)
                or len(set(ids)) != len(ids) or type(native["operations"]) is not dict
                or tuple(native["operations"]) != ids):
            raise ValueError("Exact ordered unique operation IDs required")
        self.doc, self.machine = native["doc"], native["machine"]
        self.operations = tuple((i, native["operations"][i]) for i in ids)
        self.roots = (self.doc, self.machine) + tuple(v for _, v in self.operations)
        self.check_count = self.native_calls = 0

    def __call__(self):
        def read(obj, name, *params):
            self.check_events()
            self.native_calls += 1
            value = _member(obj, name, *params)
            self.check_events()
            return value
        kind = read(self.doc, "GetDocType")
        machine_kind = read(self.machine, "MachType")
        if type(kind) is not int or kind != 1 or type(machine_kind) is not int or machine_kind != 1:
            raise ValueError("Retained CAM part/MILL binding changed")
        for expected, operation in self.operations:
            if _object_id(self.doc, operation, read) != expected:
                raise ValueError("Retained numeric operation ID changed")
        self.check_count += 1


class ScopedCamRouteReadBatch(ScopedCamReadBatch):
    """Fixed route getter allowlist over the already implemented retained graph."""
    def __init__(self, *args, native_context, reference_state, max_native_calls=900, **kwargs):
        self.route_binding = RetainedRouteBinding(native_context, reference_state, kwargs.get("check_events"))
        super().__init__(*args, retained_objects=self.route_binding.roots,
            verify_retained_binding=self.route_binding, max_native_calls=max_native_calls, **kwargs)

    def read(self, obj, name, *args):
        try:
            if type(name) is not str or name not in ROUTE_READ_MEMBERS:
                raise ValueError("Getter is outside the exact route read scope")
            for arg in args:
                if type(arg) not in (bool, int, float, str, bytes) and id(arg) not in self._known_objects:
                    raise ValueError("Native argument is outside the retained document graph")
            return self._observe_read(obj, "getter", lambda: _member(obj, name, *args))
        except BaseException:
            self._invalid = True
            self._completed = False
            raise

    def typed(self, obj, interface_name):
        try:
            if type(interface_name) is not str or interface_name not in ROUTE_READ_INTERFACES:
                raise ValueError("Interface is outside the exact route read scope")
            return self._observe_read(obj, "qi", lambda: _typed(obj, interface_name, self.typelib_path))
        except BaseException:
            self._invalid = True
            self._completed = False
            raise

    def feature_dispatch(self, obj):
        """Count the existing level reader's standard IDispatch QI; never IUnknown."""
        from comtypes.automation import IDispatch
        return self._observe_read(obj, "qi", lambda: obj.QueryInterface(IDispatch))

    def summary(self):
        result = super().summary()
        result.update(scope="BOUNDED_CAM_ROUTE_READ_BATCH_V1",
            binding_method="retained_doc_machine_and_numeric_operation_ids",
            retained_binding_checks=self.route_binding.check_count,
            binding_native_calls=self.route_binding.native_calls,
            reacquired_wrapper_identity_comparison=False, native_qualified=False)
        return result


def capture_route_batch(app, sw, *, strong_guard_factory, batch_factory,
        reference_state, current_document, source_sha256,
        target_feature_native_id, target_operation_native_id,
        expected_candidate_tool_native_id, reference_candidate, observation_pin,
        check_events, diagnostic):
    """Optional pilot adapter. Caller must first qualify the read-only batch.

    batch_factory(native_context, reference_state) supplies the same pinned files,
    exact SW PID/path/dirty state and event callbacks as strong_guard_factory.
    No dispatch, persistence, geometry refresh or native app discovery in batch.
    Results are returned only after successful strong exit and unit readback.
    """
    from scripts.sw_cam_existing_sandvik import resolve_existing_context
    from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
    from scripts.sw_cam_completed_sandvik_assignment import (
        capture_assignment_snapshot, read_assignment_candidate)
    def units(g):
        return read_document_cam_unit_scope(g.read(sw, "ActiveDoc"), app,
            sw_read=lambda obj, name:g.read(obj, name), cam_read=g.read)
    with strong_guard_factory() as g:
        native = resolve_existing_context(app, g.read, g.typed, {"before":reference_state})
        before_units = units(g)
    batch = batch_factory(native, reference_state)
    try:
        with batch:
            state, native, levels, firstcut, entry = capture_assignment_snapshot(app,
                read=batch.read, typed=batch.typed, reference_state=reference_state,
                current_document=current_document, source_sha256=source_sha256,
                target_feature_native_id=target_feature_native_id,
                target_operation_native_id=target_operation_native_id,
                boundary=check_events, diagnostic=diagnostic, native_context=native,
                feature_dispatch_reader=batch.feature_dispatch)
            payload = read_assignment_candidate(native, app, sw,
                read=batch.read, typed=batch.typed,
                expected_candidate_tool_native_id=expected_candidate_tool_native_id,
                reference=reference_candidate, observation_pin=observation_pin,
                firstcut=firstcut, diagnostic=diagnostic.setdefault("candidate", {}),
                metric_scope=before_units)
        batch.require_complete()
        with strong_guard_factory() as g:
            after_units = units(g)
        if before_units != after_units:
            raise ValueError("Global document/CAM unit scope changed across read batch")
        diagnostic["route_batch_units_stable"] = True
        return state, native, levels, firstcut, entry, payload
    finally:
        diagnostic["route_read_batch"] = deepcopy(batch.summary())
