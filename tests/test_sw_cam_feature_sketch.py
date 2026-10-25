"""原生草图变换和生命周期的离线回归，不启动 CAD。"""
from types import SimpleNamespace as N
from unittest.mock import Mock
import math
import sys

import pytest

from scripts import sw_cam_feature_sketch as cam


class CallableObject:
    def __call__(self, *args):
        raise AssertionError("COM object property must not invoke its default member")


class Transform(CallableObject):
    def __init__(self, matrix=None, offset=(0, 0, 0)):
        self.matrix = matrix or ((1, 0, 0), (0, 1, 0), (0, 0, 1))
        self.offset = offset
        self.ArrayData = [self.matrix[j][i] for i in range(3) for j in range(3)] + list(offset) + [1, 0, 0, 0]

    def apply(self, p):
        return [sum(a * b for a, b in zip(row, p)) + t for row, t in zip(self.matrix, self.offset)]

    def Inverse(self):
        matrix = tuple(tuple(self.matrix[j][i] for j in range(3)) for i in range(3))
        offset = tuple(-sum(a * b for a, b in zip(row, self.offset)) for row in matrix)
        return Transform(matrix, offset)


class Point(CallableObject):
    def __init__(self, coords):
        self.ArrayData = list(coords)
        self.X, self.Y, self.Z = coords

    def MultiplyTransform(self, transform):
        return Point(transform.apply(self.ArrayData))


class Line(CallableObject):
    ConstructionGeometry = False

    def __init__(self, start, end):
        self.start, self.end = Point(start), Point(end)

    def GetType(self):
        return 0

    def GetStartPoint2(self):
        return self.start

    def GetEndPoint2(self):
        return self.end


class Feature(CallableObject):
    def __init__(self, model, name, kind, obj):
        self.model, self.Name, self.kind, self.obj = model, name, kind, obj
        self.Select2 = Mock(return_value=True)

    def GetTypeName2(self):
        return self.kind

    def GetSpecificFeature2(self):
        return self.obj

    def GetNextFeature(self):
        i = self.model.features.index(self) + 1
        return self.model.features[i] if i < len(self.model.features) else None


class Sketch(CallableObject):
    def __init__(self, transform):
        self.ModelToSketchTransform = transform
        self.segments = []
        self.Is3D = Mock(return_value=False)
        self.GetSketchSegments = Mock(side_effect=lambda: tuple(self.segments))


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(cam, "_double_array", tuple)
    monkeypatch.setattr(cam, "_as_sketch_line", lambda value: value)
    # 规范 +Z 法线映射到 -Y，原点在 XZ 平面中平移；名字故意不是 Top。
    plane_to_model = Transform(((1, 0, 0), (0, 0, -1), (0, 1, 0)), (.1, 0, .2))
    # 草图坐标系与参考平面不同，必须使用实际 ActiveSketch 变换。
    sketch_to_model = Transform(((0, -1, 0), (0, 0, 1), (-1, 0, 0)), (.3, 0, -.4))
    sketch = Sketch(sketch_to_model.Inverse())
    model = N(features=[], ClearSelection2=Mock())
    plane = Feature(model, "Actual meridian", "RefPlane", N(Transform=plane_to_model))
    other = Feature(model, "Top Plane", "RefPlane", N(Transform=Transform()))
    model.features = [other, plane]
    model.FirstFeature = lambda: model.features[0] if model.features else None
    manager = N(ActiveSketch=None, AddToDB=False)
    model.SketchManager = manager
    state = N(sw=N(GetMathUtility=lambda: N(CreatePoint=lambda values: Point(values)),
                   IsSame=lambda a, b: 1 if a is b else 0),
              model=model, manager=manager, plane=plane, sketch=sketch,
              endpoints=[[.03, 0., .0099], [.03, 0., .0052]],
              on_exit=lambda: None)

    def insert(_rebuild):
        if manager.ActiveSketch is None:
            manager.ActiveSketch = sketch
            model.features.append(Feature(model, "NewSketch", "ProfileFeature", sketch))
        else:
            state.on_exit()
            manager.ActiveSketch = None

    def create(*coords):
        line = Line(coords[:3], coords[3:])
        sketch.segments.append(line)
        return line

    manager.InsertSketch = Mock(side_effect=insert)
    manager.CreateLine = Mock(side_effect=create)
    return state


def create(g, **kw):
    return cam.create_single_line_sketch(g.sw, g.model, endpoints_model_m=g.endpoints,
                                         sketch_name="QualifiedLine", **kw)


def test_readonly_plane_uses_transformed_normal_origin_and_actual_name(graph):
    record, plane = cam.inspect_meridional_plane(graph.sw, graph.model, graph.endpoints)
    assert plane is graph.plane
    assert record["name"] == "Actual meridian"
    assert record["normal_model"] == [0., -1., 0.]
    assert record["origin_model_m"] == [.1, 0., .2]
    assert record["frame"] == "model_XZ"
    graph.manager.InsertSketch.assert_not_called()
    graph.plane.Select2.assert_not_called()


def test_creates_one_line_using_actual_sketch_transform_and_inverse(graph):
    plane, _ = cam.inspect_meridional_plane(graph.sw, graph.model, graph.endpoints)
    result = create(graph, expected_plane=plane)
    assert result["verified"] is True
    assert result["sketch_name"] == "QualifiedLine"
    assert result["plane"] == plane
    for actual, expected in zip(result["endpoints_model_m"], graph.endpoints):
        assert actual == pytest.approx(expected)
    assert result["endpoints_sketch_m"][0] == pytest.approx([-.4099, .27, 0.])
    assert graph.manager.CreateLine.call_count == 1
    assert graph.manager.InsertSketch.call_count == 2
    assert graph.manager.AddToDB is False
    assert graph.manager.ActiveSketch is None
    assert result["sketch_exited"] is True
    assert graph.model.features[-1].Name == "QualifiedLine"


@pytest.mark.parametrize("endpoints", [None, [], [[1, 0, 0]], [[True, 0, 1], [2, 0, 1]],
    [[1, 0, float("nan")], [2, 0, 1]], [[1, 0, 1], [1, 0, 1]], [[1, .01, 1], [2, .01, 1]]])
def test_bad_endpoints_rejected_before_mutation(graph, endpoints):
    graph.endpoints = endpoints
    with pytest.raises(ValueError):
        create(graph)
    graph.manager.InsertSketch.assert_not_called()


@pytest.mark.parametrize("tolerance", [True, 0, -1, float("inf"), 1e-3])
def test_tolerance_rejected_before_native_reads(graph, tolerance):
    with pytest.raises(ValueError):
        create(graph, tolerance_m=tolerance)
    graph.manager.InsertSketch.assert_not_called()


def test_near_planar_points_are_bounded_and_roundtrip_verified(graph):
    graph.endpoints[0][1] = 5e-9
    result = create(graph)
    assert result["verified"]
    assert result["endpoints_model_m"][0][1] == 0


def test_off_plane_active_sketch_stops_before_line_and_exits(graph):
    graph.sketch.ModelToSketchTransform = Transform()
    diagnostic = {}
    with pytest.raises(ValueError, match="active sketch plane"):
        create(graph, diagnostic=diagnostic)
    assert diagnostic["stage"] == "transform_endpoints"
    assert diagnostic["sketch_exited"]
    graph.manager.CreateLine.assert_not_called()


def test_bad_inverse_roundtrip_stops_before_line(graph):
    graph.sketch.ModelToSketchTransform.Inverse = lambda: Transform()
    with pytest.raises(ValueError, match="roundtrip"):
        create(graph)
    graph.manager.CreateLine.assert_not_called()
    assert graph.manager.ActiveSketch is None


def test_existing_active_sketch_never_closed(graph):
    graph.manager.ActiveSketch = object()
    with pytest.raises(ValueError, match="existing sketch"):
        create(graph)
    graph.manager.InsertSketch.assert_not_called()


def test_existing_name_casefold_collision_rejected(graph):
    graph.model.features.append(Feature(graph.model, "qualifiedline", "ProfileFeature", object()))
    with pytest.raises(ValueError, match="already exists"):
        create(graph)
    graph.manager.InsertSketch.assert_not_called()


def test_expected_plane_change_rejected_before_selection(graph):
    expected, _ = cam.inspect_meridional_plane(graph.sw, graph.model, graph.endpoints)
    expected["name"] = "Other"
    with pytest.raises(ValueError, match="changed since prepare"):
        create(graph, expected_plane=expected)
    graph.plane.Select2.assert_not_called()


def test_ambiguous_planes_rejected_without_fallback(graph):
    graph.model.features.append(Feature(graph.model, "Duplicate", "RefPlane", graph.plane.obj))
    with pytest.raises(ValueError, match="found 2"):
        create(graph)
    graph.manager.InsertSketch.assert_not_called()


def test_no_matching_plane_does_not_fallback_to_named_top(graph):
    graph.model.features.remove(graph.plane)
    with pytest.raises(ValueError, match="found 0"):
        create(graph)
    graph.manager.InsertSketch.assert_not_called()


def test_create_failure_preserves_partial_and_restores_manager(graph):
    graph.manager.CreateLine.side_effect = RuntimeError("native line fault")
    diagnostic = {}
    with pytest.raises(RuntimeError, match="native line fault"):
        create(graph, diagnostic=diagnostic)
    assert diagnostic["stage"] == "create_line"
    assert "endpoints_sketch_m" in diagnostic
    assert diagnostic["verified"] is False
    assert diagnostic["sketch_exited"] is True
    assert graph.manager.AddToDB is False
    assert len(graph.model.features) == 3  # 不删除失败草图。


def test_guard_failure_before_line_stops_write_but_exits(graph):
    def check():
        if graph.manager.AddToDB:
            raise RuntimeError("messages received")
    with pytest.raises(RuntimeError, match="messages"):
        create(graph, check=check)
    graph.manager.CreateLine.assert_not_called()
    assert graph.manager.ActiveSketch is None
    assert graph.manager.AddToDB is False


def test_solver_drift_after_exit_is_not_verified(graph):
    graph.on_exit = lambda: setattr(graph.sketch.segments[0].end, "X", 999.)
    diagnostic = {}
    with pytest.raises(ValueError, match="endpoints differ"):
        create(graph, diagnostic=diagnostic)
    assert diagnostic["verified"] is False
    assert diagnostic["stage"] == "verify_closed_sketch"
    assert diagnostic["sketch_exited"] is True


@pytest.mark.parametrize("kind,construction", [(1, False), (True, False), (0, True), (0, 0)])
def test_readback_requires_exact_nonconstruction_line(graph, kind, construction):
    original = graph.manager.CreateLine.side_effect
    def create_invalid(*coords):
        line = original(*coords)
        line.GetType = lambda: kind
        line.ConstructionGeometry = construction
        return line
    graph.manager.CreateLine.side_effect = create_invalid
    with pytest.raises(ValueError, match="non-construction"):
        create(graph)
    assert graph.manager.ActiveSketch is None


def test_extra_segment_rejected(graph):
    original = graph.manager.CreateLine.side_effect
    def extra(*coords):
        line = original(*coords)
        graph.sketch.segments.append(line)
        return line
    graph.manager.CreateLine.side_effect = extra
    with pytest.raises(ValueError, match="exactly one"):
        create(graph)


def test_renamed_feature_must_be_new_not_existing_sketch(graph):
    graph.model.features.append(Feature(graph.model, "OldSketch", "ProfileFeature", graph.sketch))
    with pytest.raises(ValueError, match="feature identity"):
        create(graph)
    graph.manager.CreateLine.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SAFEARRAY ABI")
def test_double_array_uses_native_double_safearray():
    import pythoncom
    result = cam._double_array([.1, .2, .3])
    assert result.varianttype == pythoncom.VT_ARRAY | pythoncom.VT_R8
    assert tuple(result.value) == (.1, .2, .3)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows interface wrapper ABI")
def test_sketch_line_uses_explicit_interface_and_dispatch_wrapper(monkeypatch):
    import pythoncom
    import pywintypes
    import win32com.client
    dispatch = object()
    wrapped = object()
    raw = N(_oleobj_=N(QueryInterface=Mock(return_value=dispatch)))
    factory = Mock(return_value=wrapped)
    monkeypatch.setattr(win32com.client, "Dispatch", factory)
    assert cam._as_sketch_line(raw) is wrapped
    raw._oleobj_.QueryInterface.assert_called_once_with(
        pywintypes.IID("{83A33DC1-27C5-11CE-BFD4-00400513BB57}"), pythoncom.IID_IDispatch)
    factory.assert_called_once_with(dispatch)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pywin32 dispatch ABI")
def test_real_dynamic_dispatch_flags_all_methods_before_eager_property_resolution(graph):
    # 真实 CDispatch 将零参读取结果包装成可调用 COM 对象；仅传输层使用离线替身。
    import pythoncom
    from win32com.client.dynamic import CDispatch
    from win32com.client.build import DispatchItem

    methods = {"CreatePoint", "MultiplyTransform", "ClearSelection2", "Select2",
               "InsertSketch", "CreateLine", "IsSame", "GetMathUtility", "FirstFeature", "GetNextFeature", "GetTypeName2",
                 "GetSpecificFeature2", "Is3D", "GetSketchSegments", "Inverse",
                 "GetType", "GetStartPoint2", "GetEndPoint2"}
    cache, defaults, reads, eager = {}, [], [], []

    def unwrap(value):
        if isinstance(value, CDispatch):
            return value.__dict__["_oleobj_"].target
        return value

    def wrap(value):
        if isinstance(value, (tuple, list)):
            return type(value)(wrap(item) for item in value)
        if not isinstance(value, (CallableObject, N)):
            return value
        if id(value) not in cache:
            cache[id(value)] = CDispatch(Raw(value), DispatchItem())
        return cache[id(value)]

    class Raw:
        def __init__(self, target):
            self.target, self.names = target, {}

        def GetIDsOfNames(self, _locale, name):
            if name not in self.names.values():
                self.names[len(self.names) + 1] = name
            return next(key for key, value in self.names.items() if value == name)

        def Invoke(self, dispid, _locale, flags, _result, *args):
            if dispid == 0:
                defaults.append(type(self.target).__name__)
                raise pythoncom.com_error(-2147352573, "Member not found", None, None)
            name = self.names[dispid]
            if flags & pythoncom.DISPATCH_PROPERTYPUT:
                setattr(self.target, name, unwrap(args[0]))
                return None
            value = getattr(self.target, name)
            if name in methods:
                if flags != pythoncom.DISPATCH_METHOD:
                    eager.append(name)
                    return wrap(N())
                reads.append((name, tuple(unwrap(v) for v in args)))
                return wrap(value(*(unwrap(v) for v in args)))
            return wrap(value)

    # 复现旧调用：解析带参数方法名时提前取属性，随后调用返回对象的 DISPID 0。
    bad_math = wrap(graph.sw.GetMathUtility())
    with pytest.raises(pythoncom.com_error) as failure:
        bad_math.CreatePoint((.1, .2, .3))
    assert failure.value.hresult == -2147352573
    assert eager == ["CreatePoint"] and defaults == ["SimpleNamespace"]
    eager.clear()
    defaults.clear()
    sw, model = wrap(graph.sw), wrap(graph.model)
    record, _ = cam.inspect_meridional_plane(sw, model, graph.endpoints)
    result = cam.create_single_line_sketch(sw, model, endpoints_model_m=graph.endpoints,
                                          sketch_name="DynamicLine", expected_plane=record)
    assert result["verified"] is True
    assert {name for name, _ in reads} == methods
    assert eager == []
    assert [args for name, args in reads if name == "InsertSketch"] == [(True,), (True,)]
    assert len([args for name, args in reads if name == "CreateLine"]) == 1
    assert defaults == []
    assert graph.manager.CreateLine.call_count == 1
    assert graph.manager.InsertSketch.call_count == 2
    assert graph.manager.ActiveSketch is None
    assert graph.manager.AddToDB is False


def test_method_flag_failure_does_not_fetch_or_invoke_member():
    class Refused:
        def _FlagAsMethod(self, name):
            raise RuntimeError("method resolution failed")
        def __getattr__(self, name):
            raise AssertionError("member must not be fetched after flag failure")
    with pytest.raises(RuntimeError, match="method resolution failed"):
        cam._call_method(Refused(), "CreatePoint", [1, 2, 3])


def test_real_method_failure_propagates_without_retry(graph):
    graph.sw.GetMathUtility = Mock(side_effect=RuntimeError("native getter failed"))
    with pytest.raises(RuntimeError, match="native getter failed"):
        cam.inspect_meridional_plane(graph.sw, graph.model, graph.endpoints)
    graph.sw.GetMathUtility.assert_called_once_with()
    graph.manager.InsertSketch.assert_not_called()
