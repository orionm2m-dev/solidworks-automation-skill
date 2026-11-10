"""@brief 组件重组与删除：ReorganizeComponents 位置回读、DeleteSelection2 组件列表回读（假对象，不连接 SolidWorks）。"""

import pytest

sw_assembly = pytest.importorskip("scripts.sw_assembly", reason="需要 pywin32 才能导入 COM 装配体模块")

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)


class FakeTransform:
    """@brief 模拟 MathTransform，仅保存 ArrayData。"""

    def __init__(self, data):
        self.ArrayData = tuple(data)


class FakeModel:
    """@brief 仅带文档类型的假模型：1=零件，2=装配体。"""

    def __init__(self, doc_type):
        self._doc_type = doc_type

    def GetType(self):
        return self._doc_type


class FakeComponent:
    """@brief 带名称、变换、包围盒与文档类型的假组件。"""

    def __init__(self, name, origin_m=(0.0, 0.0, 0.0), doc_type=1):
        self.Name2 = name
        self.data = IDENTITY[:9] + tuple(origin_m) + IDENTITY[12:]
        self.model = FakeModel(doc_type)
        self.selected_with_append = None
        self.owner = None

    @property
    def Transform2(self):
        return FakeTransform(self.data)

    def GetBox(self, include_ref_planes, include_sketches):
        x, y, z = self.data[9:12]
        return (x, y, z, x + 0.01, y + 0.02, z + 0.03)

    def GetPathName(self):
        return "C:/models/" + self.Name2.split("/")[-1] + ".SLDPRT"

    def SetSuppression2(self, state):
        return 1

    def GetModelDoc2(self):
        return self.model

    def Select4(self, append, data, show_popup):
        self.selected_with_append = append
        if self.owner is not None:
            if not append:
                self.owner.selection = []
            self.owner.selection.append(self)
        return True


class FakeExtension:
    """@brief 记录 DeleteSelection2 的选项并按假装配体的选择删除组件。"""

    def __init__(self, assembly, succeed=True):
        self.assembly = assembly
        self.succeed = succeed
        self.options = None

    def DeleteSelection2(self, options):
        self.options = options
        if self.succeed:
            self.assembly.components = [c for c in self.assembly.components if c not in self.assembly.selection]
        return self.succeed


class FakeAssembly:
    """@brief 模拟 GetComponents / ReorganizeComponents / 选择与删除；Name2 以 "/" 表示层级。"""

    def __init__(self, components, reorganize_ok=True, shift_on_move=False, delete_ok=True):
        self.components = list(components)
        for component in self.components:
            component.owner = self
        self.reorganize_ok = reorganize_ok
        self.shift_on_move = shift_on_move
        self.selection = []
        self.rebuilt = 0
        self.reorganize_calls = []
        self.Extension = FakeExtension(self, delete_ok)

    def GetComponents(self, top_level_only):
        if top_level_only:
            return [c for c in self.components if "/" not in c.Name2]
        return list(self.components)

    def ClearSelection2(self, all_documents):
        self.selection = []

    def EditRebuild3(self):
        self.rebuilt += 1
        return True

    def ReorganizeComponents(self, source, target):
        sources = list(getattr(source, "value", source))
        target_name = getattr(target, "Name2", None)
        self.reorganize_calls.append(([c.Name2 for c in sources], target_name))
        if not self.reorganize_ok:
            return False
        for component in sources:
            leaf = component.Name2.split("/")[-1]
            moved = FakeComponent(f"{target_name}/{leaf}" if target_name else leaf, component.data[9:12], component.model._doc_type)
            if self.shift_on_move:
                moved.data = moved.data[:9] + (moved.data[9] + 0.001,) + moved.data[10:]
            self.components[self.components.index(component)] = moved
        return True


def _assembly():
    return FakeAssembly([
        FakeComponent("Housing-1", (0.0, 0.0, 0.0), doc_type=2),
        FakeComponent("Body-1", (0.08208, -0.0938, -0.0005)),
        FakeComponent("Detail-1", (0.08471, -0.03635, -0.0005)),
        FakeComponent("Cap-1", (0.0842, 0.0, 0.0)),
    ])


def test_reorganize_moves_components_and_keeps_positions() -> None:
    assembly = _assembly()

    result = sw_assembly.reorganize_components(assembly, ["Body-1", "Detail-1"], "Housing-1")

    assert assembly.reorganize_calls == [(["Body-1", "Detail-1"], "Housing-1")]
    assert assembly.rebuilt == 1
    assert [row["to"] for row in result["moved"]] == ["Housing-1/Body-1", "Housing-1/Detail-1"]
    assert result["moved"][0]["origin_mm_before"] == result["moved"][0]["origin_mm_after"] == [82.08, -93.8, -0.5]
    assert result["moved"][0]["box_mm_after"] == [82.08, -93.8, -0.5, 92.08, -73.8, 29.5]
    assert all(row["position_preserved"] for row in result["moved"])
    assert result["component_count_before"] == 4 and result["component_count_after"] == 2
    assert [c.Name2 for c in assembly.GetComponents(True)] == ["Housing-1", "Cap-1"]


def test_reorganize_to_top_level_passes_empty_target() -> None:
    assembly = FakeAssembly([FakeComponent("Housing-1", doc_type=2), FakeComponent("Housing-1/Body-1", (0.01, 0.0, 0.0))])

    result = sw_assembly.reorganize_components(assembly, ["Housing-1/Body-1"], None)

    assert assembly.reorganize_calls == [(["Housing-1/Body-1"], None)]
    assert result["target"] is None and result["moved"][0]["to"] == "Body-1"
    assert result["component_count_after"] == 2


def test_reorganize_reports_changed_position() -> None:
    assembly = _assembly()
    assembly.shift_on_move = True

    with pytest.raises(RuntimeError, match="位置改变"):
        sw_assembly.reorganize_components(assembly, ["Body-1"], "Housing-1")


def test_reorganize_reports_false_return() -> None:
    assembly = _assembly()
    assembly.reorganize_ok = False

    with pytest.raises(RuntimeError, match="返回 False"):
        sw_assembly.reorganize_components(assembly, ["Body-1"], "Housing-1")


def test_reorganize_requires_subassembly_target() -> None:
    with pytest.raises(RuntimeError, match="不是子装配体"):
        sw_assembly.reorganize_components(_assembly(), ["Body-1"], "Cap-1")


@pytest.mark.parametrize(
    "names,target,message",
    [
        ([], "Housing-1", "不能为空"),
        (["Body-1", "Body-1"], "Housing-1", "重复"),
        (["Housing-1", "Body-1"], "Housing-1", "不能同时"),
        (["Housing-1/Body-1"], "Housing-1", "已在目标"),
    ],
)
def test_reorganize_rejects_invalid_requests(names, target, message) -> None:
    with pytest.raises(ValueError, match=message):
        sw_assembly.reorganize_components(_assembly(), names, target)


def test_reorganize_unknown_component_is_reported_before_moving() -> None:
    assembly = _assembly()

    with pytest.raises(RuntimeError, match="应唯一"):
        sw_assembly.reorganize_components(assembly, ["Body-1", "Missing-1"], "Housing-1")
    assert assembly.reorganize_calls == []


def test_delete_removes_components_with_dependents_and_reports_remaining() -> None:
    assembly = _assembly()
    body, detail = assembly.components[1], assembly.components[2]

    result = sw_assembly.delete_components(assembly, ["Body-1", "Detail-1"])

    assert assembly.selection == [body, detail]
    assert body.selected_with_append is False and detail.selected_with_append is True
    assert assembly.Extension.options == 3
    assert assembly.rebuilt == 1
    assert result["deleted"] == ["Body-1", "Detail-1"]
    assert result["component_count_before"] == 4 and result["component_count_after"] == 2
    assert result["remaining"] == ["Housing-1", "Cap-1"]


def test_delete_reports_failed_deletion() -> None:
    assembly = _assembly()
    assembly.Extension.succeed = False

    with pytest.raises(RuntimeError, match="删除失败.*Body-1"):
        sw_assembly.delete_components(assembly, ["Body-1"])


@pytest.mark.parametrize(
    "names,message",
    [([], "不能为空"), (["Cap-1", "Cap-1"], "重复"), (["Housing-1/Body-1"], "顶层组件")],
)
def test_delete_rejects_invalid_requests(names, message) -> None:
    with pytest.raises(ValueError, match=message):
        sw_assembly.delete_components(_assembly(), names)


def test_delete_unknown_component_leaves_assembly_untouched() -> None:
    assembly = _assembly()

    with pytest.raises(RuntimeError, match="应唯一"):
        sw_assembly.delete_components(assembly, ["Missing-1"])
    assert len(assembly.components) == 4 and assembly.Extension.options is None
