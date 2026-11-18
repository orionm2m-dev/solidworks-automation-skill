"""展示渲染模块的纯计算与入参校验测试（不连接 SOLIDWORKS）。"""
import math

import pytest

from scripts.sw_render_view import _validate, view_rotation_data


def test_front_view_is_identity():
    assert view_rotation_data(0, 0) == pytest.approx([1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])


def test_yaw_brings_positive_x_side_towards_viewer():
    data = view_rotation_data(30, 0)
    # 第一行是模型 X 轴在视图坐标中的像；右偏相机时其 Z 分量为正。
    assert data[0:3] == pytest.approx([math.cos(math.radians(30)), 0, math.sin(math.radians(30))])


def test_pitch_brings_top_towards_viewer():
    data = view_rotation_data(0, 20)
    assert data[3:6] == pytest.approx([0, math.cos(math.radians(20)), math.sin(math.radians(20))])


def test_rotation_rows_are_orthonormal():
    data = view_rotation_data(37, -11)
    rows = [data[0:3], data[3:6], data[6:9]]
    for i in range(3):
        for j in range(3):
            assert sum(a * b for a, b in zip(rows[i], rows[j])) == pytest.approx(1.0 if i == j else 0.0)


@pytest.mark.parametrize("yaw,pitch", [(float("nan"), 0), (0, 181), ("20", 0), (True, 0)])
def test_rejects_bad_angles(yaw, pitch):
    with pytest.raises(ValueError):
        view_rotation_data(yaw, pitch)


def test_validate_rejects_existing_and_relative_outputs(tmp_path):
    existing = tmp_path / "a.png"
    existing.write_bytes(b"x")
    for bad in (str(existing), "relative.png", str(tmp_path / "a.jpg"), str(tmp_path / "missing" / "a.png")):
        with pytest.raises(ValueError):
            _validate(bad, 3200, 2000, None, (255, 255, 255), "shaded")


def test_validate_accepts_new_png_and_box(tmp_path):
    path, box = _validate(str(tmp_path / "new.png"), 3200, 2000, [0, 0, 0, 1, 2, 3], (255, 255, 255), "shaded")
    assert path.name == "new.png" and box == [0.0, 0.0, 0.0, 1.0, 2.0, 3.0]


@pytest.mark.parametrize("kwargs", [
    {"width": 100}, {"height": 9000}, {"zoom_box_mm": [0, 0, 0, 0, 1, 1]},
    {"background_rgb": (255, 255, 256)}, {"display_mode": "wireframe"}])
def test_validate_rejects_bad_values(tmp_path, kwargs):
    args = {"width": 3200, "height": 2000, "zoom_box_mm": None,
            "background_rgb": (255, 255, 255), "display_mode": "shaded"}
    args.update(kwargs)
    with pytest.raises(ValueError):
        _validate(str(tmp_path / "new.png"), args["width"], args["height"], args["zoom_box_mm"],
                  args["background_rgb"], args["display_mode"])
