"""add_component: начало координат детали в точке x/y/z и возврат активной сборки (поддельный COM)."""
import pytest

from scripts import sw_assembly


class FakeTransform:
    def __init__(self, data):
        self.ArrayData = tuple(data)


class FakeComponent:
    """Записанное преобразование применяется; locked — его «перебивает» сопряжение."""

    def __init__(self, origin, locked=False):
        rotation = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        self._data = rotation + tuple(origin) + (1.0, 0.0, 0.0, 0.0)
        self.locked = locked
        self.solves = 0

    @property
    def Transform2(self):
        return FakeTransform(self._data)

    @Transform2.setter
    def Transform2(self, transform):
        if not self.locked:
            self._data = tuple(transform.ArrayData)

    def SetTransformAndSolve2(self, transform):
        self.solves += 1
        if not self.locked:
            self._data = tuple(transform.ArrayData)
        return not self.locked


def test_origin_is_moved_to_target_keeping_rotation():
    # AddComponent5 поставил центр габарита в (0, 0, 7,5 мм): начало оказалось на 11,25 мм.
    comp = FakeComponent((0.0, 0.0, 0.01125))
    result = sw_assembly.place_component_origin(comp, 0.0, 0.0, 0.0075)
    assert result["moved"] is True
    assert result["origin_before_mm"] == [0.0, 0.0, 11.25]
    assert result["origin_mm"] == [0.0, 0.0, 7.5]
    assert comp._data[9:12] == (0.0, 0.0, 0.0075)
    assert comp._data[:9] == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def test_origin_already_in_place_is_not_rewritten():
    comp = FakeComponent((0.01, 0.02, 0.03))
    result = sw_assembly.place_component_origin(comp, 0.01, 0.02, 0.03)
    assert result["moved"] is False and comp.solves == 0


def test_overridden_transform_is_reported():
    comp = FakeComponent((0.0, 0.0, 0.01125), locked=True)
    with pytest.raises(RuntimeError):
        sw_assembly.place_component_origin(comp, 0.0, 0.0, 0.0075)


class FakeDoc:
    def __init__(self, path, title):
        self.path, self.title = path, title

    def GetPathName(self):
        return self.path

    def GetTitle(self):
        return self.title


class FakeSw:
    def __init__(self, docs, active, obey=True):
        self.docs = {d.path.rsplit("\\", 1)[-1] if d.path else d.title: d for d in docs}
        self.active = active
        self.obey = obey
        self.calls = []

    @property
    def ActiveDoc(self):
        return self.active

    def ActivateDoc3(self, name, silent, option, errors):
        self.calls.append(name)
        if self.obey and name in self.docs:
            self.active = self.docs[name]
        return self.active


def test_assembly_is_made_active_again_by_file_name():
    asm = FakeDoc("C:\\w\\top.SLDASM", "top.SLDASM")
    part = FakeDoc("C:\\w\\rail.SLDPRT", "rail.SLDPRT")
    sw = FakeSw([asm, part], active=part)
    assert sw_assembly.ensure_active_document(sw, asm) == {"reactivated": True}
    assert sw.calls == ["top.SLDASM"] and sw.active is asm


def test_active_assembly_is_left_alone():
    asm = FakeDoc("C:\\w\\top.SLDASM", "top.SLDASM")
    sw = FakeSw([asm], active=asm)
    assert sw_assembly.ensure_active_document(sw, asm) == {"reactivated": False}
    assert sw.calls == []


def test_failure_to_reactivate_is_an_error():
    asm = FakeDoc("C:\\w\\top.SLDASM", "top.SLDASM")
    other = FakeDoc("C:\\w\\other.SLDASM", "other.SLDASM")
    sw = FakeSw([asm, other], active=other, obey=False)
    with pytest.raises(RuntimeError, match="other.SLDASM"):
        sw_assembly.ensure_active_document(sw, asm)


def test_unsaved_assembly_is_matched_by_title():
    asm = FakeDoc("", "Сборка1")
    part = FakeDoc("C:\\w\\rail.SLDPRT", "rail.SLDPRT")
    sw = FakeSw([asm, part], active=part)
    assert sw_assembly.ensure_active_document(sw, asm) == {"reactivated": True}
    assert sw.calls == ["Сборка1"]
