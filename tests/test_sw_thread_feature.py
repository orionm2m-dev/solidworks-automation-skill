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


class LibraryData:
    """防御性模拟：赋值 Size 时立即回落到库的第一个规格。SOLIDWORKS 2026 实测未见这种行为（回落发生在生成特征时），此处只验证提前检查这条兜底路径。"""

    KNOWN = ("#0-80", "0.2500-28")

    def __init__(self):
        self._size = self.KNOWN[0]

    def InitializeThreadData(self):
        return None

    @property
    def Size(self):
        return self._size

    @Size.setter
    def Size(self, value):
        self._size = value if value in self.KNOWN else self.KNOWN[0]


class LibraryFeatureManager(FakeFeatureManager):
    def CreateDefinition(self, type_id):
        assert type_id == 87
        self.data = LibraryData()
        return self.data


def _library_model(edge):
    model = FakeModel([FakeBody([edge], volume=2e-6, faces=10)])
    model.FeatureManager = LibraryFeatureManager()
    return model


class LateFallbackFeature(FakeFeature):
    def __init__(self, selectable):
        self.selectable = selectable
        self.selected = False

    def Select2(self, append, mark):
        self.selected = self.selectable
        return self.selectable


class LateFallbackModel(FakeModel):
    """SOLIDWORKS 2026 实测行为：赋值 Size 不报错，生成特征时才回落到库的第一个规格。"""

    def __init__(self, edge, selectable=True, delete_works=True):
        super().__init__([FakeBody([edge], volume=2e-6, faces=10)])
        self.delete_works = delete_works
        self.feature = LateFallbackFeature(selectable)
        self.deleted = False
        self.FeatureManager.CreateFeature = self._create

    def _create(self, data):
        data.Size = "#0-80"
        body = self._bodies[0]
        body._volume, body._faces = body._volume * 0.9, body._faces + 5
        return self.feature

    def EditDelete(self):
        self.deleted = True
        if self.delete_works:
            body = self._bodies[0]
            body._volume, body._faces = 2e-6, 10

    def ForceRebuild3(self, top_only):
        self.rebuilt = True


def test_add_thread_feature_deletes_feature_created_with_fallback_size() -> None:
    edge = FakeEdge(SHANK)
    model = LateFallbackModel(edge)

    with pytest.raises(ValueError, match="特征已删除"):
        thread.add_thread_feature(model, edge, thread_type="Inch Die", size="0.2500-36", depth_m=0.01)
    assert model.feature.selected and model.deleted and model.rebuilt
    assert thread.count_faces(model) == 10 and thread.body_volume_m3(model) == pytest.approx(2e-6)


def test_add_thread_feature_reports_fallback_feature_it_cannot_remove() -> None:
    edge = FakeEdge(SHANK)

    unselectable = LateFallbackModel(edge, selectable=False)
    with pytest.raises(RuntimeError, match="无法选中"):
        thread.add_thread_feature(unselectable, edge, thread_type="Inch Die", size="0.2500-36", depth_m=0.01)
    assert not unselectable.deleted

    stuck = LateFallbackModel(edge, delete_works=False)
    with pytest.raises(RuntimeError, match="未能删除"):
        thread.add_thread_feature(stuck, edge, thread_type="Inch Die", size="0.2500-36", depth_m=0.01)


def test_add_thread_feature_reads_size_from_created_feature_definition() -> None:
    edge = FakeEdge(SHANK)
    model = LateFallbackModel(edge)
    model.FeatureManager.CreateFeature = lambda data: model.feature
    model.feature.GetDefinition = lambda: type("Definition", (), {"Size": "#0-80"})()

    with pytest.raises(ValueError, match="回落到 #0-80"):
        thread.add_thread_feature(model, edge, thread_type="Inch Die", size="0.2500-36", depth_m=0.01)


@pytest.mark.parametrize("bad", [0, -1e-3, float("nan"), float("inf")])
def test_add_thread_feature_rejects_bad_diameter(bad) -> None:
    edge = FakeEdge(SHANK)
    model = _library_model(edge)
    with pytest.raises(ValueError, match="diameter_m"):
        thread.add_thread_feature(model, edge, thread_type="Inch Die", size="0.2500-28", depth_m=0.01, diameter_m=bad)
    assert model.FeatureManager.data is None


def test_add_thread_feature_keeps_library_sizes_without_overrides(monkeypatch) -> None:
    monkeypatch.setattr(LibraryData, "KNOWN", ("M1.2x0.25", "M10x1.5", "M12x1.5"))
    for size in ("M10x1.5", "M12x1.5"):
        edge = FakeEdge(SHANK)
        model = _library_model(edge)
        result = thread.add_thread_feature(model, edge, thread_type="Metric Die", size=size, depth_m=0.007)
        data = model.FeatureManager.data
        assert result["size"] == size
        assert not hasattr(data, "PitchOverride") and not hasattr(data, "DiameterOverride")


def test_add_thread_feature_rejects_size_missing_from_library() -> None:
    edge = FakeEdge(SHANK)
    model = _library_model(edge)

    with pytest.raises(ValueError, match="没有规格 0.2500-36"):
        thread.add_thread_feature(model, edge, thread_type="Inch Die", size="0.2500-36", depth_m=0.01)
    assert not model.rebuilt


def test_add_thread_feature_overrides_pitch_and_diameter() -> None:
    edge = FakeEdge(SHANK)
    model = _library_model(edge)

    result = thread.add_thread_feature(model, edge, thread_type="Inch Die", size="0.2500-28", depth_m=0.01,
                                       pitch_m=0.0254 / 36, diameter_m=0.00635)

    data = model.FeatureManager.data
    assert data.Size == "0.2500-28"
    assert data.PitchOverride is True and data.Pitch == pytest.approx(0.0254 / 36)
    assert data.DiameterOverride is True and data.Diameter == pytest.approx(0.00635)
    assert result["pitch_mm"] == pytest.approx(0.705556, abs=1e-6) and result["diameter_mm"] == pytest.approx(6.35)

    plain = thread.add_thread_feature(_library_model(edge), edge, thread_type="Inch Die", size="0.2500-28", depth_m=0.01)
    assert plain["pitch_mm"] is None and plain["diameter_mm"] is None
    with pytest.raises(ValueError, match="pitch_m"):
        thread.add_thread_feature(_library_model(edge), edge, thread_type="Inch Die", size="0.2500-28", depth_m=0.01, pitch_m=0)
