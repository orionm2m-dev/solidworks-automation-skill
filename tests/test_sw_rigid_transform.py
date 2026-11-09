"""@brief 组件刚体变换：纯数学校验与 Transform2 写入回读（假对象，不连接 SolidWorks）。"""

import math

import pytest

from scripts.sw_rigid_transform import build_rigid_transform_data, transform_matches


def test_identity_layout_matches_solidworks_array_data() -> None:
    data = build_rigid_transform_data((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.01, -0.02, 0.03))

    assert data == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.01, -0.02, 0.03, 1.0, 0.0, 0.0, 0.0)


def test_rows_are_local_axes_in_assembly_coordinates() -> None:
    # 局部 X → 装配体 -Y，局部 Y → 装配体 Z，局部 Z = X × Y → 装配体 -X
    data = build_rigid_transform_data((0, -1, 0), (0, 0, 1), (-1, 0, 0), (0, 0, 0))

    assert data[0:3] == (0.0, -1.0, 0.0)
    assert data[3:6] == (0.0, 0.0, 1.0)
    assert data[6:9] == (-1.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "axes,message",
    [
        (((1, 0, 0), (0, 1, 0), (0, 0, -1)), "右手系"),
        (((2, 0, 0), (0, 1, 0), (0, 0, 1)), "单位向量"),
        (((1, 0, 0), (0.7071068, 0.7071068, 0), (0, 0, 1)), "不正交"),
        (((1, 0, 0), (0, 1, 0), (0, 0, float("nan"))), "有限数"),
        (((1, 0), (0, 1, 0), (0, 0, 1)), "有限数"),
    ],
)
def test_invalid_axes_are_rejected(axes, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_rigid_transform_data(*axes, (0, 0, 0))


def test_rotated_axes_accept_small_numeric_noise() -> None:
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    data = build_rigid_transform_data((c, s, 0), (-s, c, 0), (0, 0, 1), (0, 0, 0))

    assert transform_matches(data, data)
    assert not transform_matches(data[:9] + (0.001, 0.0, 0.0) + data[12:], data)


class FakeTransform:
    """@brief 模拟 MathTransform，仅保存 ArrayData。"""

    def __init__(self, data):
        self.ArrayData = tuple(data)


class FakeComponent:
    """@brief 模拟 IComponent2：可选择让 SetTransformAndSolve2 失败或回读被覆盖。"""

    def __init__(self, solve_ok=True, override=None):
        self._transform = FakeTransform((1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0))
        self.solve_ok = solve_ok
        self.override = override

    @property
    def Transform2(self):
        if self.override is not None:
            return FakeTransform(self.override)
        return FakeTransform(self._transform.ArrayData)

    @Transform2.setter
    def Transform2(self, value):
        self._transform = FakeTransform(value.ArrayData)

    def SetTransformAndSolve2(self, value):
        if self.solve_ok:
            self._transform = FakeTransform(value.ArrayData)
        return self.solve_ok


def _sw_assembly():
    return pytest.importorskip("scripts.sw_assembly", reason="需要 pywin32 才能导入 COM 装配体模块")


def test_apply_uses_solve_and_reads_back() -> None:
    target = build_rigid_transform_data((0, -1, 0), (0, 0, 1), (-1, 0, 0), (0.096, -0.004, 0.024))
    result = _sw_assembly().apply_component_rigid_transform(FakeComponent(), target)

    assert result["method"] == "SetTransformAndSolve2"
    assert transform_matches(result["array_data"], target)


def test_apply_falls_back_to_transform2_assignment() -> None:
    target = build_rigid_transform_data((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.01, 0, 0))
    result = _sw_assembly().apply_component_rigid_transform(FakeComponent(solve_ok=False), target)

    assert result["method"] == "Transform2"


def test_apply_rejects_readback_overridden_by_constraints() -> None:
    target = build_rigid_transform_data((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.01, 0, 0))
    component = FakeComponent(override=(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0))

    with pytest.raises(RuntimeError, match="回读"):
        _sw_assembly().apply_component_rigid_transform(component, target)


class NamedComponent:
    """@brief 仅带实例名的假组件。"""

    def __init__(self, name):
        self.Name2 = name


class FakeAssembly:
    """@brief 模拟 IAssemblyDoc.GetComponents。"""

    def __init__(self, names):
        self._components = [NamedComponent(name) for name in names]

    def GetComponents(self, top_level_only):
        assert top_level_only is True
        return self._components


def test_exact_name_lookup_does_not_match_by_substring() -> None:
    assembly = FakeAssembly(["Board-1", "Board-10", "Body-1"])

    assert _sw_assembly().find_component_by_exact_name(assembly, "Board-1").Name2 == "Board-1"


@pytest.mark.parametrize("names", [["Body-1"], ["Board-1", "Board-1"]])
def test_exact_name_lookup_requires_single_match(names) -> None:
    with pytest.raises(RuntimeError, match="应唯一"):
        _sw_assembly().find_component_by_exact_name(FakeAssembly(names), "Board-1")


class PlacedComponent:
    """@brief 带变换与包围盒的假组件。"""

    def __init__(self, name, origin_m):
        self.Name2 = name
        self._data = (0.0, -1.0, 0.0, 0.0, 0.0, 1.0, -1.0, 0.0, 0.0, *origin_m, 1.0, 0.0, 0.0, 0.0)

    @property
    def Transform2(self):
        return FakeTransform(self._data)

    def GetBox(self, include_ref_planes, include_sketches):
        return (0.0, 0.0, 0.0, 0.01, 0.02, 0.03)

    def GetPathName(self):
        return "C:/models/" + self.Name2 + ".SLDPRT"

    def IsFixed(self):
        return True

    def IsSuppressed(self):
        return False


class PlacedAssembly:
    """@brief 记录 GetComponents 的 top_level_only 参数。"""

    def __init__(self, components):
        self._components = components
        self.requested = None

    def GetComponents(self, top_level_only):
        self.requested = top_level_only
        return self._components


def test_list_component_transforms_reports_axes_origin_and_box_in_mm() -> None:
    assembly = PlacedAssembly([PlacedComponent("Board-1", (0.096, -0.004, 0.024)), PlacedComponent("Body-1", (0, 0, 0))])

    listing = _sw_assembly().list_component_transforms(assembly, top_level_only=False, name_contains="board")

    assert assembly.requested is False
    assert listing["matched"] == 1
    row = listing["rows"][0]
    assert row["x_axis"] == [0.0, -1.0, 0.0] and row["z_axis"] == [-1.0, 0.0, 0.0]
    assert row["origin_mm"] == [96.0, -4.0, 24.0]
    assert row["box_mm"] == [0.0, 0.0, 0.0, 10.0, 20.0, 30.0]
    assert row["fixed"] is True and row["suppressed"] is False


def test_list_component_transforms_counts_beyond_limit() -> None:
    assembly = PlacedAssembly([PlacedComponent(f"R{i}-1", (0, 0, 0)) for i in range(5)])

    listing = _sw_assembly().list_component_transforms(assembly, limit=2)

    assert listing["matched"] == 5 and len(listing["rows"]) == 2


class VisibilityComponent:
    """@brief 可选择忽略隐藏请求的假组件。"""

    def __init__(self, sticky=False):
        self._visible = 1
        self.sticky = sticky

    @property
    def Visible(self):
        return self._visible

    @Visible.setter
    def Visible(self, value):
        if not self.sticky:
            self._visible = value


def test_set_component_visibility_hides_and_reads_back() -> None:
    component = VisibilityComponent()

    assert _sw_assembly().set_component_visibility(component, False) is False
    assert _sw_assembly().set_component_visibility(component, True) is True


def test_set_component_visibility_reports_ignored_request() -> None:
    with pytest.raises(RuntimeError, match="可见性"):
        _sw_assembly().set_component_visibility(VisibilityComponent(sticky=True), False)


class FrozenIdentityComponent(FakeComponent):
    """@brief 模拟单位变换组件：Transform2 返回的对象忽略 ArrayData 赋值。"""

    class _Frozen:
        ArrayData = property(lambda self: (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
                             lambda self, value: None)

    def __init__(self):
        super().__init__()
        self._applied = None

    @property
    def Transform2(self):
        return FakeTransform(self._applied) if self._applied is not None else self._Frozen()

    def SetTransformAndSolve2(self, value):
        self._applied = tuple(value.ArrayData)
        return True


class FakeMathUtility:
    """@brief 记录 CreateTransform 收到的数组。"""

    def CreateTransform(self, data):
        return FakeTransform(getattr(data, "value", data))


class FakeApplication:
    """@brief 提供 GetMathUtility 的假应用对象。"""

    def GetMathUtility(self):
        return FakeMathUtility()


def test_apply_creates_new_transform_when_component_is_at_identity() -> None:
    target = build_rigid_transform_data((0, 1, 0), (0, 0, -1), (-1, 0, 0), (0.102778984, -0.090459134, 0.045272916))
    result = _sw_assembly().apply_component_rigid_transform(FrozenIdentityComponent(), target, sw=FakeApplication())

    assert result["method"] == "SetTransformAndSolve2"
    assert transform_matches(result["array_data"], target)


def test_apply_without_application_reports_ignored_assignment() -> None:
    target = build_rigid_transform_data((0, 1, 0), (0, 0, -1), (-1, 0, 0), (0.1, 0, 0))

    with pytest.raises(RuntimeError, match="回读"):
        _sw_assembly().apply_component_rigid_transform(FrozenIdentityComponent(), target)


class CopyExtension:
    """@brief 记录 SaveAs 参数并按需写出文件。"""

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = []

    def SaveAs(self, path, version, options, export_data, errors, warnings):
        self.calls.append((path, version, options))
        if self.succeed:
            with open(path, "wb") as handle:
                handle.write(b"copy")
        return self.succeed


class CopyModel:
    """@brief 带文档类型与 Extension 的假模型。"""

    def __init__(self, doc_type=1, succeed=True):
        self._doc_type = doc_type
        self.Extension = CopyExtension(succeed)

    def GetType(self):
        return self._doc_type


class CopyComponent:
    """@brief 返回假模型的假组件。"""

    def __init__(self, name, model):
        self.Name2 = name
        self._model = model

    def GetModelDoc2(self):
        return self._model


class CopyAssembly:
    """@brief GetComponents(False) 返回全部层级组件。"""

    def __init__(self, components):
        self._components = components

    def GetComponents(self, top_level_only):
        assert top_level_only is False
        return self._components


def test_save_component_copy_uses_silent_copy_option(tmp_path) -> None:
    model = CopyModel()
    assembly = CopyAssembly([CopyComponent("Box-1/Gland-1", model), CopyComponent("Box-1/Gland-2", CopyModel())])
    target = tmp_path / "gland.SLDPRT"

    result = _sw_assembly().save_component_model_copy(assembly, "Box-1/Gland-1", str(target))

    assert target.is_file() and result["doc_type"] == 1
    assert model.Extension.calls == [(str(target), 0, 3)]


def test_save_component_copy_rejects_wrong_extension_and_failed_save(tmp_path) -> None:
    assembly = CopyAssembly([CopyComponent("Gland-1", CopyModel(succeed=False))])

    with pytest.raises(RuntimeError, match="扩展名"):
        _sw_assembly().save_component_model_copy(assembly, "Gland-1", str(tmp_path / "gland.SLDASM"))
    with pytest.raises(RuntimeError, match="保存失败"):
        _sw_assembly().save_component_model_copy(assembly, "Gland-1", str(tmp_path / "gland.SLDPRT"))
    with pytest.raises(RuntimeError, match="应唯一"):
        _sw_assembly().save_component_model_copy(assembly, "Missing-1", str(tmp_path / "x.SLDPRT"))
