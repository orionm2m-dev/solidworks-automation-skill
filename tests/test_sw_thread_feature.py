"""@brief 螺纹特征与圆形边查找：假 COM 对象，不连接 SolidWorks。"""

import pytest

from scripts import sw_thread_feature as thread


class FakeCurve:
    def __init__(self, circle):
        self._circle = circle

    def IsCircle(self):
        return self._circle is not None

    @property
    def CircleParams(self):
        return self._circle


class FakeEdge:
    def __init__(self, circle=None):
        self._curve = FakeCurve(circle)

    def GetCurve(self):
        return self._curve


class FakeBody:
    def __init__(self, edges, volume=1e-6, faces=4):
        self._edges, self._volume, self._faces = edges, volume, faces

    def GetEdges(self):
        return self._edges

    def GetFaces(self):
        return [object()] * self._faces

    def GetMassProperties(self, density):
        return (0.0, 0.0, 0.0, self._volume, 0.0, self._volume * density)


class FakeFeature:
    Name = "Thread1"


class FakeFeatureManager:
    def __init__(self, create_ok=True):
        self.create_ok = create_ok
        self.data = None

    def CreateDefinition(self, type_id):
        assert type_id == 87
        self.data = type("Data", (), {"InitializeThreadData": lambda self: None})()
        return self.data

    def CreateFeature(self, data):
        return FakeFeature() if self.create_ok else None

    def GetCreateFeatureErrors(self, msgs, name):
        return 3


class FakeModel:
    def __init__(self, bodies, create_ok=True):
        self._bodies = bodies
        self.FeatureManager = FakeFeatureManager(create_ok)
        self.rebuilt = False

    def GetBodies2(self, body_type, visible_only):
        return self._bodies

    def ForceRebuild3(self, top_only):
        self.rebuilt = True
        for body in self._bodies:
            body._volume *= 0.9
            body._faces += 2


SHANK = (0.0, 0.007, 0.0, 0.0, 1.0, 0.0, 0.005)
HOLE = (0.0, 0.008, 0.0, 0.0, 1.0, 0.0, 0.0025)


def test_list_circular_edges_reports_mm_and_filters_by_radius() -> None:
    model = FakeModel([FakeBody([FakeEdge(SHANK), FakeEdge(HOLE), FakeEdge()])])

    listing = thread.list_circular_edges(model)
    assert listing["matched"] == 2
    assert listing["rows"][0] == {"body_index": 0, "center_mm": [0.0, 7.0, 0.0], "axis": [0.0, 1.0, 0.0], "diameter_mm": 10.0}

    assert thread.list_circular_edges(model, radius_m=0.0025)["matched"] == 1


def test_find_circular_edge_requires_single_match() -> None:
    shank_edge = FakeEdge(SHANK)
    model = FakeModel([FakeBody([shank_edge, FakeEdge(HOLE), FakeEdge(SHANK)])])

    assert thread.find_circular_edge(FakeModel([FakeBody([shank_edge, FakeEdge(HOLE)])]), (0, 0.007, 0), 0.005)["edge"] is shank_edge
    with pytest.raises(RuntimeError, match="匹配 2 条"):
        thread.find_circular_edge(model, (0, 0.007, 0), 0.005)
    with pytest.raises(RuntimeError, match="匹配 0 条"):
        thread.find_circular_edge(model, (0, 0.0, 0), 0.005)


def test_add_thread_feature_sets_properties_and_reads_back_changes() -> None:
    edge = FakeEdge(SHANK)
    model = FakeModel([FakeBody([edge], volume=2e-6, faces=10)])

    result = thread.add_thread_feature(model, edge, thread_type="Metric Die", size="M10x1.5", depth_m=0.007)

    data = model.FeatureManager.data
    assert data.Edge is edge and data.Type == "Metric Die" and data.Size == "M10x1.5"
    assert data.ThreadMethod == 0 and data.EndCondition == 0 and data.BlindDepth == 0.007
    assert data.RightHanded is True and data.TrimEndFace is True and data.Offset is False
    assert model.rebuilt
    assert result["feature_name"] == "Thread1"
    assert result["volume_after_m3"] < result["volume_before_m3"]
    assert result["face_count_after"] == 12 and result["face_count_before"] == 10


def test_add_thread_feature_reports_failure_and_validates_inputs() -> None:
    edge = FakeEdge(SHANK)
    with pytest.raises(RuntimeError, match="未创建"):
        thread.add_thread_feature(FakeModel([FakeBody([edge])], create_ok=False), edge, thread_type="Metric Die", size="M10x1.5", depth_m=0.007)
    with pytest.raises(ValueError, match="depth_m"):
        thread.add_thread_feature(FakeModel([FakeBody([edge])]), edge, thread_type="Metric Die", size="M10x1.5")
    with pytest.raises(ValueError, match="method"):
        thread.add_thread_feature(FakeModel([FakeBody([edge])]), edge, thread_type="Metric Die", size="M10x1.5", method="weld", depth_m=0.007)
