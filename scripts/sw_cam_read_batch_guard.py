"""Bounded document-object reads with strong entry/exit checks; no dispatch."""
from time import perf_counter
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _typed

# Existing R84 first-cut, local-tool and analytic-profile readers only.
READ_MEMBERS = frozenset({
    "GetTypeOfFirstCutZ", "GetToolpathParam", "GetToolpathParameters",
    "IGetToolcrib", "GetAllTools", "Count", "Item", "GetCWObjectID",
    "ToolType", "CutDiameter", "Protrusion", "StnNo", "IsMillTool",
    "GetToolName", "ShankDia", "CutLength", "OverallLength", "TipOffset",
    "TipLength", "Flutes", "MillUDToolOutputType", "GetToolProfile",
    "GetShankProfile", "IGetMillToolHolder", "GetName", "GetHolderProfile",
    "IGetNumChains", "GetNumOfCurves", "GetCurveAtIndex", "IGetNextChain",
    "GetTypeOfCurve", "GetStart", "GetEnd", "GetMid", "CenterPoint",
    "GetCoordinates", "IGetRadius", "IGetNormal", "IGetSense", "GetRadius",
    "GetDirection", "GetNumOfFacet", "IGetNumControlPoints", "GetDegree",
    "GetOrder", "IGetDimension", "GetIsPeriodic", "IGetIsRational",
    "IGetStartParam", "IGetEndParam", "GetFacetAtIndex", "QueryInterface",
})
READ_INTERFACES = frozenset({
    "ICWMillOperation3", "ICWToolpathParam", "ICWToolcrib4",
    "ICWDispatchCollection", "ICWTool", "ICWMillUDTool", "ICWMillToolHolder",
    "ICWSegChain", "ICWCurve", "ICWPosition", "ICWUnitVector", "ICWArc",
    "ICWCircle", "ICWSpline",
})


class ScopedCamReadBatch(ScopedCamDispatchGuard):
    """Read one retained document graph; completion is not an atomic snapshot.

    The caller acquires roots with the existing verified capture and never
    supplies objects from another document. Global application/unit getters
    stay in the ordinary dispatch guard. No dynamic ActiveDoc lookup belongs
    inside this scope. Strong references prevent redirection of object reads;
    they do not prove the absence of external transient A-to-B-to-A changes.
    """
    def __init__(self, *args, retained_objects, max_native_calls, verify_retained_binding, **kwargs):
        if (type(retained_objects) is not tuple or not 1 <= len(retained_objects) <= 64
                or any(v is None or type(v) in (bool, int, float, str, bytes, list, tuple, dict)
                       for v in retained_objects)):
            raise ValueError("Explicit retained native document-object roots required")
        if type(max_native_calls) is not int or not 1 <= max_native_calls <= 6000:
            raise ValueError("Strict bounded read/QI call budget required")
        if not callable(verify_retained_binding):
            raise ValueError("Explicit retained-document binding verifier required")
        self._verify_retained_binding = verify_retained_binding
        self._retained = list(retained_objects)
        self._known_objects = {id(v) for v in retained_objects}
        self._budget = max_native_calls
        self._read_calls = self._qi_calls = 0
        self._completed = False
        self._timer_start = perf_counter()
        self._seconds = dict(events=0., ownership=0., evidence=0., identity=0.,
                             boundary_inclusive=0., binding=0., getter=0., qi=0.)
        self._timer_counts = {k: 0 for k in self._seconds}
        for key, label in (("verify_owned_process", "ownership"),
                           ("verify_evidence", "evidence"), ("check_events", "events")):
            callback = kwargs.get(key)
            if not callable(callback):
                raise ValueError("Explicit guard callbacks required")
            kwargs[key] = self._timed_callback(label, callback)
        super().__init__(*args, **kwargs)

    def _timed(self, label, callback):
        started = perf_counter()
        self._timer_counts[label] += 1
        try:
            return callback()
        finally:
            self._seconds[label] += perf_counter() - started

    def _timed_callback(self, label, callback):
        return lambda: self._timed(label, callback)

    def _identity(self):
        return self._timed("identity", super()._identity)

    def _boundary(self, **kwargs):
        def boundary():
            super(ScopedCamReadBatch, self)._boundary(**kwargs)
            self._timed("binding", self._verify_retained_binding)
            self._fast(**kwargs)
        return self._timed("boundary_inclusive", boundary)

    def __enter__(self):
        try:
            return super().__enter__()
        except BaseException:
            self._invalid = True
            self._retained.clear()
            self._known_objects.clear()
            raise

    def _retain_result(self, value):
        if value is None or type(value) in (bool, int, float, str, bytes):
            return
        self._retained.append(value)
        if type(value) in (list, tuple):
            for item in value:
                self._retain_result(item)
        elif type(value) is not dict:
            self._known_objects.add(id(value))

    def _observe_read(self, obj, label, callback):
        try:
            self._require_live()
            if id(obj) not in self._known_objects:
                raise ValueError("Native owner was not acquired from the retained document graph")
            if self._read_calls + self._qi_calls >= self._budget:
                raise ValueError("Read-only native call budget exhausted")
            self.check_events()
            self._retained.append(obj)
            if label == "getter": self._read_calls += 1
            else: self._qi_calls += 1
            value = self._timed(label, callback)
            self._retain_result(value)
            self.check_events()
            return value
        except BaseException:
            self._invalid = True
            self._completed = False
            raise

    def read(self, obj, name, *args):
        try:
            if type(name) is not str or name not in READ_MEMBERS:
                raise ValueError("Getter is outside the exact document-bound read scope")
            if name == "QueryInterface":
                from comtypes import IUnknown
                if len(args) != 1 or args[0] is not IUnknown:
                    raise ValueError("Only canonical IUnknown identity query is permitted")
            return self._observe_read(obj, "getter", lambda: _member(obj, name, *args))
        except BaseException:
            self._invalid = True
            self._completed = False
            raise

    def typed(self, obj, interface_name):
        try:
            if type(interface_name) is not str or interface_name not in READ_INTERFACES:
                raise ValueError("Interface is outside the exact read scope")
            return self._observe_read(obj, "qi", lambda: _typed(obj, interface_name, self.typelib_path))
        except BaseException:
            self._invalid = True
            self._completed = False
            raise

    def dispatch_once(self, *args, **kwargs):
        self._invalid = True
        self._completed = False
        raise ValueError("Read-only batch cannot dispatch, export, save or mutate")

    def require_complete(self):
        if not self._completed or self._invalid or self._active:
            raise ValueError("Closed successful read batch required before using its data")
        return True

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is not None:
                self._invalid = True
            if self._invalid:
                if exc_type is None:
                    raise ValueError("Read batch was invalidated; partial data cannot authorize export")
            else:
                self._boundary()
        except BaseException:
            self._invalid = True
            raise
        finally:
            try:
                super().__exit__(exc_type, exc, traceback)
            except BaseException:
                self._invalid = True
                raise
            finally:
                self._retained.clear()
                self._known_objects.clear()
        self._completed = exc_type is None and not self._invalid
        return False

    def summary(self):
        result = super().summary()
        result.update(scope="BOUNDED_CAM_READ_BATCH_V1", read_only=True,
            read_scope_complete=self._completed and not self._invalid and not self._active,
            getter_calls=self._read_calls, query_interface_calls=self._qi_calls,
            max_native_calls=self._budget, retained_reference_count=len(self._retained),
            atomic_snapshot=False, transient_active_document_excursion_excluded=False,
            timer_seconds=dict(self._seconds), timer_counts=dict(self._timer_counts),
            timer_elapsed_seconds=perf_counter()-self._timer_start,
            timer_categories_overlap=True, dispatch_available=False)
        return result