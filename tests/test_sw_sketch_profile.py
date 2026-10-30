"""@brief 闭合直线/圆弧轮廓（shape='profile'）的离线回归测试。"""
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import sw_part

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
import server  # noqa: E402


class FakeSketchManager:
    """@brief 记录 CreateLine / CreateArc 调用和 AddToDB 状态。"""

    def __init__(self):
        self.AddToDB = False
        self.calls = []

    def CreateLine(self, *args):
        self.calls.append(("line", args, self.AddToDB))
        return object()

    def CreateArc(self, *args):
        self.calls.append(("arc", args, self.AddToDB))
        return object()


class FakeModel:
    def __init__(self):
        self.SketchManager = FakeSketchManager()


@pytest.mark.parametrize(
    ("start", "end", "bulge", "center"),
    [
        ((1.0, 0.0), (0.0, 1.0), math.tan(math.pi / 8), (0.0, 0.0)),    # 逆时针 1/4 圆
        ((0.0, 1.0), (1.0, 0.0), -math.tan(math.pi / 8), (0.0, 0.0)),   # 顺时针 1/4 圆
        ((-2.0, 0.0), (2.0, 0.0), 1.0, (0.0, 0.0)),                      # 半圆：圆心在弦中点
        ((3.0, 5.0), (5.0, 3.0), math.tan(math.pi / 8), (5.0, 5.0)),
    ],
)
def test_profile_arc_center_follows_dxf_bulge(start, end, bulge, center) -> None:
    assert sw_part.profile_arc_center(*start, *end, bulge) == pytest.approx(center, abs=1e-12)


def test_sketch_profile_closes_loop_and_restores_add_to_db() -> None:
    model = FakeModel()
    vertices = [(0.0, 0.0, 0.0), (0.02, 0.0, 1.0), (0.02, 0.01, 0.0), (0.0, 0.01, 0.0)]

    segments = sw_part.sketch_profile(model, vertices)

    calls = model.SketchManager.calls
    assert len(segments) == 4
    assert [kind for kind, _args, _db in calls] == ["line", "arc", "line", "line"]
    assert all(db is True for _kind, _args, db in calls)
    assert model.SketchManager.AddToDB is False
    # 半圆 (0.02,0)->(0.02,0.01) 逆时针：圆心为弦中点，方向 +1
    assert calls[1][1] == pytest.approx((0.02, 0.005, 0, 0.02, 0.0, 0, 0.02, 0.01, 0, 1))
    # 最后一段连回第一点
    assert calls[3][1] == pytest.approx((0.0, 0.01, 0, 0.0, 0.0, 0))


def test_profile_vertices_validate_and_convert_to_metres() -> None:
    assert server._profile_vertices_m([[0, 0], [10, 0, 0.5], [10, 5]]) == [
        (0.0, 0.0, 0.0), (0.01, 0.0, 0.5), (0.01, 0.005, 0.0)]
    with pytest.raises(ValueError, match="at least 3"):
        server._profile_vertices_m([[0, 0], [1, 0]])
    with pytest.raises(ValueError, match=r"\[1\] must be"):
        server._profile_vertices_m([[0, 0], [1], [1, 1]])
    with pytest.raises(ValueError, match="repeats the next vertex"):
        server._profile_vertices_m([[0, 0], [0, 0], [1, 1]])


def test_sketch_and_extrude_builds_profile_boss(monkeypatch) -> None:
    drawn, extruded = [], []

    @contextmanager
    def fake_sketch(model, plane_name):
        yield "Sketch1"

    server._load_automation_modules()
    monkeypatch.setattr(server, "_run_locked", lambda op, fmt: json.dumps(op()))
    monkeypatch.setattr(server, "_active_part_required", lambda params: (None, object()))
    monkeypatch.setattr(server, "sketch", fake_sketch)
    monkeypatch.setattr(server, "sketch_profile", lambda model, vertices: drawn.append(vertices))
    monkeypatch.setattr(server, "extrude_boss", lambda model, ref, depth: extruded.append((ref, depth)) or object())
    monkeypatch.setattr(server, "get_com_member", lambda obj, name: "Boss-Extrude1")
    monkeypatch.setattr(server, "_model_summary", lambda model: {})

    result = json.loads(server.solidworks_sketch_and_extrude(server.SolidWorksSketchOnPlaneInput(
        shape="profile", profile_points_mm=[[0, 0], [20, 0, 1], [20, 10], [0, 10]], depth_mm=6)))

    assert result["status"] == "ok" and result["shape"] == "profile"
    assert drawn == [[(0.0, 0.0, 0.0), (0.02, 0.0, 1.0), (0.02, 0.01, 0.0), (0.0, 0.01, 0.0)]]
    assert extruded == [("Sketch1", pytest.approx(0.006))]
