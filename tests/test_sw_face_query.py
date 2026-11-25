"""Запрос граней в области (поддельный COM)."""
import pytest

from scripts import sw_face_query as m


class Surface:
    def __init__(self, kind, params):
        self.kind, self.params = kind, params

    def IsPlane(self): return self.kind == "plane"
    def IsCylinder(self): return self.kind == "cylinder"
    def IsCone(self): return False
    def IsSphere(self): return False
    def IsTorus(self): return False

    @property
    def PlaneParams(self): return self.params

    @property
    def CylinderParams(self): return self.params


class Face:
    def __init__(self, box, surface, area=1e-4, sense=True):
        self.box, self.surface, self.area, self.sense = box, surface, area, sense

    def GetBox(self): return self.box
    def GetSurface(self): return self.surface
    def GetArea(self): return self.area
    def FaceInSurfaceSense(self): return self.sense


class Body:
    def __init__(self, faces): self.faces = faces
    def GetFaces(self): return self.faces


class Model:
    def __init__(self, faces): self.body = Body(faces)
    def GetBodies2(self, kind, visible_only): return [self.body]


TOP = Face((0.0, 0.0, 0.01, 0.1, 0.02, 0.01), Surface("plane", (0.0, 0.0, 1.0, 0.0, 0.0, 0.01)), sense=False)
HOLE = Face((0.04, 0.005, 0.0, 0.046, 0.011, 0.01), Surface("cylinder", (0.043, 0.008, 0.0, 0.0, 0.0, 1.0, 0.003)), sense=False)
FAR = Face((0.2, 0.2, 0.0, 0.3, 0.3, 0.01), Surface("plane", (0.0, 0.0, -1.0, 0.25, 0.25, 0.0)), sense=False)


def test_faces_meeting_the_box_with_geometry():
    r = m.query_faces(Model([TOP, HOLE, FAR]), [35, 0, 0, 50, 15, 10])
    assert r["matched_count"] == 2 and r["total_face_count"] == 3
    top, hole = r["faces"]
    assert top["type"] == "plane" and top["normal"] == [0.0, 0.0, 1.0] and top["root_point_mm"] == [0.0, 0.0, 10.0]
    assert hole["type"] == "cylinder" and hole["diameter_mm"] == 6.0 and hole["axis_point_mm"] == [43.0, 8.0, 0.0]
    assert hole["face_in_surface_sense"] is False and hole["area_mm2"] == 100.0


def test_inside_mode_and_kinds_filter():
    r = m.query_faces(Model([TOP, HOLE, FAR]), [35, 0, 0, 50, 15, 10], mode="inside")
    assert [f["type"] for f in r["faces"]] == ["cylinder"]
    r = m.query_faces(Model([TOP, HOLE, FAR]), [0, 0, 0, 400, 400, 10], kinds=["plane"])
    assert [f["type"] for f in r["faces"]] == ["plane", "plane"]


def test_sense_true_flips_plane_normal_and_param_order_is_detected():
    # Как в SolidWorks 2026: FaceInSurfaceSense=True — нормаль PlaneParams смотрит в материал.
    # Нормаль во второй тройке, базовая точка в первой (не единичная).
    face = Face((0.0, 0.0, 0.0, 0.1, 0.1, 0.0), Surface("plane", (0.05, 0.05, 0.0, 0.0, 0.0, 1.0)), sense=True)
    r = m.query_faces(Model([face]), [0, 0, -1, 100, 100, 1])
    assert r["faces"][0]["normal"] == [-0.0, -0.0, -1.0]
    assert r["faces"][0]["root_point_mm"] == [50.0, 50.0, 0.0]


def test_sense_false_keeps_plane_normal():
    face = Face((0.06, -0.04, -0.04, 0.06, 0.04, 0.0), Surface("plane", (1.0, 0.0, 0.0, 0.06, -0.04, -0.04)), sense=False)
    r = m.query_faces(Model([face]), [50, -50, -50, 70, 50, 10])
    assert r["faces"][0]["normal"] == [1.0, 0.0, 0.0]


def test_limit_and_bad_box():
    r = m.query_faces(Model([TOP, HOLE, FAR]), [0, 0, 0, 400, 400, 10], limit=1)
    assert r["returned_count"] == 1 and r["truncated"] is True
    with pytest.raises(ValueError):
        m.query_faces(Model([TOP]), [10, 0, 0, 0, 1, 1])
