"""原生扫描输入的拒绝边界；不启动 CAD。"""
import re
import unittest
from pathlib import Path
from pydantic import ValidationError
from scripts.sw_native_wire import BuildSpec, Sweep, Box, Target, DecalInput, FaceColorInput, MAX_NATIVE_REQUEST_BYTES
SCRIPTS=Path(__file__).resolve().parents[1].joinpath('scripts')
def source(suffix): return SCRIPTS.joinpath('sw_native_wire'+suffix).read_text(encoding='utf-8')
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
        self.assertIn('Face colour readback mismatch',source('.cs'))
    def test_decal_binds_one_face_and_reads_counts_back(self):
        # 贴图只绑定经过给定点的面，并回读文档与面的贴图数量
        cs=source('.cs')
        block=cs[cs.index('static object AddFaceDecal'):cs.index('public static string Run')]
        self.assertIn('PickFace(d,r.feature_name,r.point_mm)',block)
        self.assertIn('Decal count readback mismatch',block)
        self.assertIn('swStoreImagesWithModel',block)
        self.assertIn('No face of the feature passes through the point',cs)
    def test_replace_compares_top_level_components(self):
        # 子装配体替换为零件时嵌套组件数会变化，替换前后只能比较顶层组件
        cs=source('.cs')
        block=cs[cs.index('r.action=="replace"'):cs.index('Unsupported operation')]
        self.assertIn('GetComponents(true)',cs)
        self.assertIn('TopComponents(d)',block)
        self.assertNotIn('Components(d)',block.replace('TopComponents(d)',''))
    def test_every_python_action_is_handled_natively(self):
        # Python 注册的每个操作都必须在 C# 子进程中有对应分支，避免落到 Unsupported operation
        actions=set(re.findall(r"run\(params,'([a-z_]+)'",source('.py')))
        self.assertEqual(actions,{'inspect','build','import','replace','paint_face','decal','clear_decals','exclude'})
        handled=set(re.findall(r'r\.action=="([a-z_]+)"',source('.cs')))
        self.assertLessEqual(actions,handled)
    def test_only_import_requests_save(self):
        # 未请求保存的操作不能返回 saved=false 冒充保存失败；只有导入在真正保存后写 saved=true
        cs=source('.cs')
        self.assertIn('{"save_requested",r.action=="import"}',cs)
        self.assertNotIn('{"saved",false}',cs)
        self.assertEqual(cs.count('result["saved"]=true'),1)
        block=cs[cs.index('r.action=="import"){'):cs.index('r.action=="exclude"')]
        self.assertIn('result["saved"]=true',block)
    def test_active_object_fallback_requires_same_pid(self):
        # 2026 实例可能只注册标准活动对象；回退时仍须核对 PID，拒绝连接其他实例
        cs=source('.cs')
        block=cs[cs.index('static ISldWorks Bind(int pid)'):cs.index('static IModelDoc2 Guard(')]
        self.assertIn('if(pid<=0)throw',block)
        self.assertIn('"!SolidWorks_PID_"+pid',block)
        self.assertIn('if(sw.GetProcessID()!=pid)throw new Exception("PID mismatch")',block)
        self.assertIn('Marshal.GetActiveObject("SldWorks.Application");if(active.GetProcessID()==pid)return active;',block)
    def test_powershell_reads_bounded_utf8_stdin(self):
        # 请求走 UTF-8 标准输入，两端字节上限一致；短 Base64 入口保留兼容
        ps,py=source('.ps1'),source('.py')
        self.assertNotIn('[Parameter(Mandatory=$true)][string]$InputBase64',ps)
        self.assertIn('[Console]::In.ReadToEnd()',ps)
        self.assertIn('[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)',ps)
        self.assertIn('-gt %d'%MAX_NATIVE_REQUEST_BYTES,ps)
        self.assertIn('[NativeWireTools]::Run($request)',ps)
        self.assertNotIn("'-InputBase64'",py)
        self.assertIn('input=request',py)
if __name__=='__main__':unittest.main()
