"""原生扫描输入的拒绝边界；不启动 CAD。"""
import unittest
from pydantic import ValidationError
from scripts.sw_native_wire import BuildSpec, Sweep, Box, Target
class NativeWireInputTests(unittest.TestCase):
    def test_line_and_bezier(self):
        s=BuildSpec(sweeps=[dict(name='Wire1',control_points_mm=[[0,0,0],[1,1,0]],diameter_mm=.9)])
        self.assertEqual(s.sweeps[0].diameter_mm,.9)
    def test_code_is_not_a_spec(self):
        with self.assertRaises(ValidationError): BuildSpec(sweeps=[],script='arbitrary')
    def test_duplicate_names(self):
        s=dict(name='Wire1',control_points_mm=[[0,0,0],[1,1,0]],diameter_mm=.9)
        with self.assertRaises(ValidationError): BuildSpec(sweeps=[s,s])
    def test_closed_path(self):
        with self.assertRaises(ValidationError): Sweep(name='Wire1',control_points_mm=[[0,0,0],[0,0,0]],diameter_mm=.9)
    def test_nan(self):
        with self.assertRaises(ValidationError): Sweep(name='Wire1',control_points_mm=[[0,0,0],[float('nan'),1,0]],diameter_mm=.9)
    def test_invalid_color(self):
        with self.assertRaises(ValidationError): Sweep(name='Wire1',control_points_mm=[[0,0,0],[1,1,0]],diameter_mm=.9,color=[1,2,0])
    def test_negative_box(self):
        with self.assertRaises(ValidationError): Box(name='Solid',bounds_mm=[0,0,0,1,-1,1])
    def test_explicit_target_required(self):
        with self.assertRaises(ValidationError): Target()
    def test_replace_compares_top_level_components(self):
        # 子装配体替换为零件时嵌套组件数会变化，替换前后只能比较顶层组件
        from pathlib import Path
        source=Path(__file__).resolve().parents[1].joinpath('scripts','sw_native_wire.cs').read_text(encoding='utf-8')
        block=source[source.index('r.action=="replace"'):source.index('Unsupported operation')]
        self.assertIn('GetComponents(true)',source)
        self.assertIn('TopComponents(d)',block)
        self.assertNotIn('Components(d)',block.replace('TopComponents(d)',''))
if __name__=='__main__':unittest.main()