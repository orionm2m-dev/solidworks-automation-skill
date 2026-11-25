"""Тело вращения по профилю: ось, проверка стороны профиля с точками дуг (без SolidWorks)."""
import math

import pytest

from scripts.sw_revolve import arc_points, axis_segment, check_profile_side

MM = 0.001


def verts(points):
    return [(p[0] * MM, p[1] * MM, p[2] if len(p) == 3 else 0.0) for p in points]


# Полупрофиль датчика: ось — Y эскиза, x ≥ 0: дно, конус, сферический купол дугой до оси.
SENSOR = verts([[0, 0], [35, 0], [35, 8], [24, 30, 0.25], [0, 48.5]])


def test_arc_points_follow_bulge_direction():
    pts = arc_points(0.0, 0.0, 2.0, 0.0, 1.0, samples=4)  # полуокружность против часовой: середина снизу
    assert pts[0] == pytest.approx((0.0, 0.0)) and pts[-1] == pytest.approx((2.0, 0.0))
    assert pts[2] == pytest.approx((1.0, -1.0))


def test_sensor_profile_is_on_one_side_of_sketch_y():
    p1, p2 = axis_segment("sketch_y", SENSOR)
    assert p1[0] == 0.0 and p2[0] == 0.0 and p1[1] < 0 < 0.0485 < p2[1]
    assert check_profile_side(SENSOR, p1, p2) in (1, -1)


def test_profile_crossing_axis_is_refused_with_vertex_number():
    crossing = verts([[-5, 0], [35, 0], [35, 10], [-5, 10]])
    p1, p2 = axis_segment("sketch_y", crossing)
    with pytest.raises(ValueError, match=r"profile_points_mm\[\d\]"):
        check_profile_side(crossing, p1, p2)


def test_arc_bulging_over_the_axis_is_refused():
    # Вершины справа от оси, но дуга между ними уходит за ось.
    profile = verts([[2, 0], [10, 0], [10, 10], [2, 10, -1.0]])
    p1, p2 = axis_segment("sketch_y", profile)
    with pytest.raises(ValueError):
        check_profile_side(profile, p1, p2)


def test_axis_points_and_errors():
    (a, b) = axis_segment("points", SENSOR, [(0.0, 0.0), (0.0, 0.01)])
    assert a == (0.0, 0.0) and b == (0.0, 0.01)
    with pytest.raises(ValueError):
        axis_segment("points", SENSOR, [(0.0, 0.0), (0.0, 0.0)])
    with pytest.raises(ValueError):
        axis_segment("points", SENSOR, None)


def test_profile_on_the_axis_only_is_refused():
    flat = verts([[0, 0], [0, 10], [0, 20]])
    with pytest.raises(ValueError, match="on the revolve axis"):
        check_profile_side(flat, (0.0, -1.0), (0.0, 1.0))
