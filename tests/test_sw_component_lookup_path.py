"""组件查找：顶层按 Name2 唯一匹配，嵌套路径在全层级列表中按 Name2 全路径匹配（离线假对象）。"""
import pytest

from scripts import sw_assembly


class _FakeComponent:
    def __init__(self, name):
        self.Name2 = name


class _FakeAssembly:
    def __init__(self):
        self._top = [_FakeComponent("Body-1"), _FakeComponent("Board-1")]
        self._all = self._top + [_FakeComponent("Board-1/XBT1-1"), _FakeComponent("Board-1/C1-1")]

    def GetComponents(self, top_only):
        return list(self._top if top_only else self._all)


def test_top_level_lookup_by_name2():
    assert sw_assembly.find_component_by_exact_name(_FakeAssembly(), "Board-1").Name2 == "Board-1"


def test_nested_path_matches_full_name2():
    found = sw_assembly.find_component_by_exact_name(_FakeAssembly(), "Board-1/XBT1-1")
    assert found.Name2 == "Board-1/XBT1-1"


def test_nested_path_missing_raises():
    with pytest.raises(RuntimeError):
        sw_assembly.find_component_by_exact_name(_FakeAssembly(), "Board-1/Nope-1")
