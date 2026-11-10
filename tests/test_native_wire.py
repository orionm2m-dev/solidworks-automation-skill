"""原生扫描输入的拒绝边界；不启动 CAD。"""
import unittest
from pydantic import ValidationError
from scripts.sw_native_wire import BuildSpec, Sweep, Box, Target, DecalInput, FaceColorInput
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
    def test_decal_requires_face_point_and_finite_values(self):
        base=dict(expected_document_path='C:/part.SLDPRT',feature_name='Label',image_path='C:/label.png')
        self.assertEqual(DecalInput(**base,point_mm=[1,2,3],rotation_deg=90).rotation_deg,90)
        with self.assertRaises(ValidationError): DecalInput(**base)
        with self.assertRaises(ValidationError): DecalInput(**base,point_mm=[1,2])
        with self.assertRaises(ValidationError): DecalInput(**base,point_mm=[1,2,float('inf')])
        with self.assertRaises(ValidationError): DecalInput(**base,point_mm=[1,2,3],rotation_deg=720)
        with self.assertRaises(ValidationError): DecalInput(**base,point_mm=[1,2,3],script='arbitrary')
    def test_face_colour_requires_point_and_unit_rgb(self):
        base=dict(expected_document_path='C:/part.SLDPRT',feature_name='Fillet1',point_mm=[0,1,2])
        self.assertEqual(FaceColorInput(**base,color=[0,.5,1]).color,(0,.5,1))
        with self.assertRaises(ValidationError): FaceColorInput(**base,color=[0,128,255])
        with self.assertRaises(ValidationError): FaceColorInput(**base)
        from pathlib import Path
        source=Path(__file__).resolve().parents[1].joinpath('scripts','sw_native_wire.cs').read_text(encoding='utf-8')
        self.assertIn('Face colour readback mismatch',source)
    def test_decal_binds_one_face_and_reads_counts_back(self):
        # 贴图只绑定经过给定点的面，并回读文档与面的贴图数量
        from pathlib import Path
        source=Path(__file__).resolve().parents[1].joinpath('scripts','sw_native_wire.cs').read_text(encoding='utf-8')
        block=source[source.index('static object AddFaceDecal'):source.index('public static string Run')]
        self.assertIn('PickFace(d,r.feature_name,r.point_mm)',block)
        self.assertIn('Decal count readback mismatch',block)
        self.assertIn('swStoreImagesWithModel',block)
        self.assertIn('No face of the feature passes through the point',source)
    def test_replace_compares_top_level_components(self):
        # 子装配体替换为零件时嵌套组件数会变化，替换前后只能比较顶层组件
        from pathlib import Path
        source=Path(__file__).resolve().parents[1].joinpath('scripts','sw_native_wire.cs').read_text(encoding='utf-8')
        block=source[source.index('r.action=="replace"'):source.index('Unsupported operation')]
        self.assertIn('GetComponents(true)',source)
        self.assertIn('TopComponents(d)',block)
        self.assertNotIn('Components(d)',block.replace('TopComponents(d)',''))
if __name__=='__main__':unittest.main()