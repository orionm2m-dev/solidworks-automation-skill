"""
sw_part 草图选择回归测试。

重点覆盖 SolidWorks 2024 中文版反馈过的问题：
选择集为空且 SelectByID2("SKETCH") 失败时，特征函数应使用创建草图时
缓存的对象引用，而不是依赖残留选择集。
"""
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def fake_get_com_member(obj, attr_name, *args):
    """测试用 COM 成员读取器。"""
    member = getattr(obj, attr_name)
    return member(*args) if args or callable(member) else member


class FakeVariant:
    """测试用 VARIANT 占位类型。"""

    def __init__(self, *_args):
        pass


sys.modules["sw_connect"] = types.SimpleNamespace(get_com_member=fake_get_com_member)
sys.modules["sw_preflight"] = types.SimpleNamespace(
    import_com_dependencies=lambda: (
        types.SimpleNamespace(VT_DISPATCH=9),
        types.SimpleNamespace(),
        FakeVariant,
    )
)

import sw_part  # noqa: E402


class FakeFeature:
    """模拟 SolidWorks Feature 对象。"""

    def __init__(self, name):
        self.Name = name
        self.selected = False

    def Select2(self, append, mark):
        """模拟对象级选择成功。"""
        self.selected = True
        return True


class FakeSketch:
    """模拟 SolidWorks Sketch 对象。"""

    def __init__(self, name):
        self.Name = name
        self.feature = FakeFeature(name)

    def GetFeature(self):
        """返回草图对应特征。"""
        return self.feature


class FakeSketchManager:
    """模拟 SketchManager。"""

    def __init__(self, sketch):
        self.ActiveSketch = None
        self.sketch = sketch

    def InsertSketch(self, _update_edit_rebuild):
        """进入或退出草图。"""
        self.ActiveSketch = self.sketch if self.ActiveSketch is None else None


class FakeSelectionManager:
    """模拟空选择集。"""

    def GetSelectedObjectCount2(self, _mark):
        """始终返回空选择集。"""
        return 0


class FakeExtension:
    """模拟 SelectByID2 对 SKETCH 失败、对 PLANE 成功。"""

    def __init__(self):
        self.calls = []

    def SelectByID2(self, name, entity_type, *_args):
        """记录选择调用，并故意让 SKETCH 名称选择失败。"""
        self.calls.append((name, entity_type))
        return entity_type == "PLANE"


class FakeFeatureManager:
    """模拟拉伸特征管理器。"""

    def __init__(self, model):
        self.model = model

    def FeatureExtrusion3(self, *_args):
        """只有对象级选择发生后才创建特征。"""
        if self.model.sketch.feature.selected:
            return FakeFeature("Boss-Extrude1")
        return None


class FakeModel:
    """模拟最小 IModelDoc2。"""

    def __init__(self):
        self.sketch = FakeSketch("草图1")
        self.Extension = FakeExtension()
        self.SketchManager = FakeSketchManager(self.sketch)
        self.SelectionManager = FakeSelectionManager()
        self.FeatureManager = FakeFeatureManager(self)
        self.clear_calls = 0

    def ClearSelection2(self, _clear_all):
        """记录清空选择集。"""
        self.clear_calls += 1

    def FeatureByName(self, _name):
        """模拟中文 SW 中按名称找不到草图。"""
        return None


class SketchSelectionTests(unittest.TestCase):
    """验证草图选择不依赖残留选择集或 SelectByID2("SKETCH")。"""

    def test_extrude_uses_cached_sketch_object_when_select_by_id_fails(self):
        """选择集为空且 SKETCH 名称选择失败时仍应拉伸成功。"""
        model = FakeModel()

        with sw_part.sketch(model, "Front Plane") as sketch_name:
            self.assertEqual(sketch_name, "草图1")

        feature = sw_part.extrude_boss(model, sketch_name, 0.01)

        self.assertIsNotNone(feature)
        self.assertTrue(model.sketch.feature.selected)
        self.assertNotIn(("草图1", "SKETCH"), model.Extension.calls)


class ReferencePlaneTests(unittest.TestCase):
    """验证多语言别名与只读、有限的实际平面枚举。"""

    def test_standard_aliases_select_russian_plane(self):
        """英语或中文标准名称应落到同一方向的俄语标准名称。"""
        pairs = [("Front Plane", "前视基准面", "Спереди"),
                 ("Top Plane", "上视基准面", "Сверху"),
                 ("Right Plane", "右视基准面", "Справа")]
        for english, chinese, russian in pairs:
            for requested in (english, chinese, russian):
                with self.subTest(requested=requested):
                    model = FakeModel()
                    calls = []

                    def select(name, entity_type, *_args):
                        calls.append(name)
                        return name == russian and entity_type == "PLANE"

                    model.Extension.SelectByID2 = select
                    self.assertEqual(sw_part.start_sketch(model, requested), russian)
                    self.assertIsNotNone(model.SketchManager.ActiveSketch)
                    self.assertEqual(calls[-1], russian)

    def test_custom_name_is_not_replaced_by_standard_plane(self):
        """用户自定义名称必须原样保留，避免选错参考平面。"""
        self.assertEqual(sw_part._get_plane_name_candidates("My datum"), ["My datum"])

    def test_inspection_reads_actual_names_and_skips_other_features(self):
        """检查只读成员，不调用选择、草图或重建接口。"""
        tail = types.SimpleNamespace(Name="Custom datum", GetTypeName2="RefPlane", GetNextFeature=None)
        other = types.SimpleNamespace(Name="Boss", GetTypeName2=lambda: "Boss", GetNextFeature=lambda: tail)
        head = types.SimpleNamespace(Name="Спереди", GetTypeName2=lambda: "RefPlane", GetNextFeature=lambda: other)
        result = sw_part.inspect_reference_planes(types.SimpleNamespace(FirstFeature=lambda: head))
        self.assertEqual(result["planes"], [{"name": "Спереди", "type": "RefPlane"},
                                           {"name": "Custom datum", "type": "RefPlane"}])
        self.assertEqual(result["visited_features"], 3)
        self.assertTrue(result["complete"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["errors"], [])

    def test_feature_limit_is_reported(self):
        """达到特征上限时不得宣称枚举完整。"""
        tail = types.SimpleNamespace(Name="Сверху", GetTypeName2="RefPlane", GetNextFeature=None)
        head = types.SimpleNamespace(Name="Спереди", GetTypeName2="RefPlane", GetNextFeature=tail)
        result = sw_part.inspect_reference_planes(types.SimpleNamespace(FirstFeature=head), limit=1)
        self.assertEqual(len(result["planes"]), 1)
        self.assertEqual(result["truncation_reason"], "feature_limit")
        self.assertTrue(result["truncated"])
        self.assertFalse(result["complete"])

    def test_cycle_and_read_error_remain_bounded(self):
        """循环代理和读取错误必须返回有限的部分结果。"""
        cycle = types.SimpleNamespace(Name="Спереди", GetTypeName2="RefPlane")
        cycle.GetNextFeature = cycle
        result = sw_part.inspect_reference_planes(types.SimpleNamespace(FirstFeature=cycle))
        self.assertEqual(result["truncation_reason"], "feature_cycle")
        self.assertEqual(result["visited_features"], 1)

        def fail():
            raise RuntimeError("mock COM failure")

        cycle.GetNextFeature = fail
        result = sw_part.inspect_reference_planes(types.SimpleNamespace(FirstFeature=cycle))
        self.assertEqual(result["truncation_reason"], "read_error")
        self.assertEqual(result["errors"][0]["member"], "GetNextFeature")

    def test_empty_document_and_invalid_limit(self):
        """空文档不是截断结果，非法上限在访问 COM 前拒绝。"""
        result = sw_part.inspect_reference_planes(types.SimpleNamespace(FirstFeature=None))
        self.assertEqual(result["planes"], [])
        self.assertTrue(result["complete"])
        for limit in (0, -1, True, 1.5, 4097):
            with self.assertRaises(ValueError):
                sw_part.inspect_reference_planes(object(), limit=limit)


if __name__ == "__main__":
    unittest.main()
