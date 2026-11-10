"""@brief 拉伸起始偏移、独立实体与特征外观的离线回归测试。"""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import sw_part

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
import server  # noqa: E402


class FakeFeatureManager:
    """@brief 记录 FeatureExtrusion3 / FeatureCut4 的实参。"""

    def __init__(self):
        self.boss = None
        self.cut = None

    def FeatureExtrusion3(self, *args):
        self.boss = args
        return object()

    def FeatureCut4(self, *args):
        self.cut = args
        return object()


class FakeModel:
    def __init__(self):
        self.FeatureManager = FakeFeatureManager()


class FakeFace:
    def __init__(self, box):
        self._box = box

    def GetBox(self):
        return self._box


class FakeFeature:
    def __init__(self, name="Boss-Extrude1", boxes=()):
        self.Name = name
        self._faces = [FakeFace(box) for box in boxes]

    def GetFaces(self):
        return self._faces


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(0.0, (0, 0.0, False)), (0.0125, (3, 0.0125, False)), (-0.004, (3, 0.004, True))],
)
def test_start_condition_maps_sign_to_flip(offset, expected) -> None:
    assert sw_part._start_condition(offset) == expected


def test_extrude_boss_passes_offset_and_merge(monkeypatch) -> None:
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda model, name: None)
    model = FakeModel()

    sw_part.extrude_boss(model, "Sketch1", 0.01)
    assert model.FeatureManager.boss[17] is True
    assert model.FeatureManager.boss[20:] == (0, 0.0, False)

    sw_part.extrude_boss(model, "Sketch1", 0.01, merge=False, start_offset=-0.002)
    assert len(model.FeatureManager.boss) == 23
    assert model.FeatureManager.boss[17] is False
    assert model.FeatureManager.boss[20:] == (3, 0.002, True)


def test_extrude_cut_passes_offset(monkeypatch) -> None:
    monkeypatch.setattr(sw_part, "_ensure_sketch_selected", lambda model, name: None)
    model = FakeModel()

    sw_part.extrude_cut(model, "Sketch1", 0.001, start_offset=0.015)

    assert len(model.FeatureManager.cut) == 27
    assert model.FeatureManager.cut[23:26] == (3, 0.015, False)


def _member(obj, name):
    """@brief 与 get_com_member 一致：成员可调用则调用，否则按属性返回。"""
    member = getattr(obj, name)
    return member() if callable(member) else member


def _patch_tool(monkeypatch, feature, calls):
    @contextmanager
    def fake_sketch(model, plane_name):
        yield "Sketch1"

    server._load_automation_modules()
    monkeypatch.setattr(server, "_run_locked", lambda op, fmt: json.dumps(op()))
    monkeypatch.setattr(server, "_active_part_required", lambda params: (None, object()))
    monkeypatch.setattr(server, "sketch", fake_sketch)
    monkeypatch.setattr(server, "sketch_circle", lambda *args: None)
    monkeypatch.setattr(
        server, "extrude_boss",
        lambda model, ref, depth, **kwargs: calls.append(("boss", depth, kwargs)) or feature,
    )
    monkeypatch.setattr(
        server, "extrude_cut",
        lambda model, ref, depth, **kwargs: calls.append(("cut", depth, kwargs)) or feature,
    )
    monkeypatch.setattr(
        server, "set_feature_appearance",
        lambda target, color: calls.append(("paint", target.Name, color)) or True,
    )
    monkeypatch.setattr(server, "get_com_member", _member)
    monkeypatch.setattr(server, "_model_summary", lambda model: {})


def test_tool_builds_offset_separate_coloured_boss(monkeypatch) -> None:
    calls = []
    feature = FakeFeature(boxes=[(-0.008, 0.001, -0.008, 0.008, 0.001, 0.008),
                                 (-0.008, 0.001, -0.008, 0.008, 0.004, 0.008)])
    _patch_tool(monkeypatch, feature, calls)

    result = json.loads(server.solidworks_sketch_and_extrude(server.SolidWorksSketchOnPlaneInput(
        shape="circle", radius_mm=8, depth_mm=3, start_offset_mm=1, merge=False,
        color="#1F4E9A", feature_name="Sleeve")))

    assert calls[0] == ("boss", pytest.approx(0.003), {"start_offset": pytest.approx(0.001), "merge": False})
    assert calls[1] == ("paint", "Sleeve", "#1F4E9A")
    assert result["feature_name"] == "Sleeve" and result["merged"] is False
    assert result["appearance_ok"] is True and result["start_offset_mm"] == 1
    assert result["feature_box_mm"] == [-8.0, 1.0, -8.0, 8.0, 4.0, 8.0]


def test_tool_keeps_legacy_call_shape_without_options(monkeypatch) -> None:
    calls = []
    _patch_tool(monkeypatch, FakeFeature(), calls)

    result = json.loads(server.solidworks_sketch_and_extrude(server.SolidWorksSketchOnPlaneInput(
        shape="circle", radius_mm=8, depth_mm=3)))

    assert calls == [("boss", pytest.approx(0.003), {})]
    assert "feature_box_mm" not in result and "appearance_ok" not in result


def test_tool_passes_offset_to_cut(monkeypatch) -> None:
    calls = []
    _patch_tool(monkeypatch, FakeFeature(), calls)

    server.solidworks_sketch_and_extrude(server.SolidWorksSketchOnPlaneInput(
        shape="circle", radius_mm=3, depth_mm=0.2, cut=True, start_offset_mm=-15.3))

    assert calls == [("cut", pytest.approx(0.0002), {"start_offset": pytest.approx(-0.0153)})]


def test_extrude_options_reject_inconsistent_combinations() -> None:
    with pytest.raises(ValueError, match="midplane"):
        server.SolidWorksSketchOnPlaneInput(shape="circle", radius_mm=1, depth_mm=1, midplane=True, start_offset_mm=2)
    with pytest.raises(ValueError, match="merge=False"):
        server.SolidWorksSketchOnPlaneInput(shape="circle", radius_mm=1, depth_mm=1, cut=True, merge=False)


def test_feature_box_is_none_without_faces() -> None:
    assert server._feature_box_mm(FakeFeature()) is None


class FakeDocument:
    def __init__(self, features):
        self._features = features
        self.rebuilt = False

    def FeatureByName(self, name):
        return self._features.get(name)

    def ForceRebuild3(self, top_only):
        self.rebuilt = True


def test_set_appearance_paints_named_feature(monkeypatch) -> None:
    painted = []
    document = FakeDocument({"Fillet1": FakeFeature("Fillet1")})
    server._load_automation_modules()
    monkeypatch.setattr(server, "_run_locked", lambda op, fmt: json.dumps(op()))
    monkeypatch.setattr(server, "_active_model_required", lambda params: (None, document))
    monkeypatch.setattr(server, "set_feature_appearance",
                        lambda target, color: painted.append((target.Name, color)) or True)
    monkeypatch.setattr(server, "_model_summary", lambda model: {})

    result = json.loads(server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(
        target="feature", feature_name="Fillet1", color="#101010")))

    assert painted == [("Fillet1", "#101010")] and document.rebuilt
    assert result["status"] == "ok" and result["feature_name"] == "Fillet1"

    with pytest.raises(ValueError, match="Feature not found"):
        server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(
            target="feature", feature_name="Missing", color="#101010"))
    with pytest.raises(ValueError, match="feature_name is required"):
        server.solidworks_set_appearance(server.SolidWorksSetAppearanceInput(target="feature", color="#101010"))


class FakeSketchManager:
    def __init__(self):
        self.AddToDB = False


class FakeSketchModel:
    def __init__(self):
        self.SketchManager = FakeSketchManager()


def test_exact_sketch_entry_disables_inference_and_restores() -> None:
    model = FakeSketchModel()
    with pytest.raises(RuntimeError):
        with server._exact_sketch_entry(model):
            assert model.SketchManager.AddToDB is True
            raise RuntimeError("draw failed")
    assert model.SketchManager.AddToDB is False

    with server._exact_sketch_entry(object()):
        pass


class FakePaintedFeature:
    """@brief 仅提供带配置参数的材质读取接口，与 IFeature 一致。"""

    def GetMaterialPropertyValues2(self, option, names):
        assert option == 1 and names is None
        return (0.125, 0.25, 0.5, 1.0, 1.0, 0.45, 0.35, 0.0, 0.0)


def test_feature_colour_reads_back_through_configuration_getter() -> None:
    from scripts import sw_appearance

    assert sw_appearance.get_material_property_values(FakePaintedFeature())[:3] == (0.125, 0.25, 0.5)
    assert sw_appearance.verify_appearance(FakePaintedFeature(), (0.125, 0.25, 0.5))["ok"]
