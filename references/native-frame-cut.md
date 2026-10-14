# 任意坐标系的原生圆角矩形切除

`solidworks_create_frame_cut` 接受 `spec_path`（JSON）和精确文档路径。
JSON：`origin_mm`、单位正交 `x_axis/y_axis`、`center_mm`、`width_mm`、`height_mm`、`radius_mm`、`depth_mm`、`along_normal`、唯一 `feature_name`。
默认沿坐标系法向的反方向切除。半径必须小于宽高的一半。

工具创建固定参考平面、八段完全固定草图及原生 Cut-Extrude，不替换基体。参考平面使用 SOLIDWORKS CreatePlaneFixed2，位置为固定定义；草图与切除可在 SOLIDWORKS 中编辑。只允许当前已保存可写零件；不保存模型，不自动回滚失败的特征。
必须复核导出体积、切除方向、壁厚、装配干涉与预览。不得以成功返回代替制造可行性确认。

状态：pilot。离线测试覆盖坐标系、退化轮廓、非法字段及 MCP 目标保护；实机验证：SOLIDWORKS 2026 SP4.1（34.4.1）、Windows、Python 3.10，两个已保存零件上分别测试沿法向和反法向、倾斜坐标系切除。原生特征保存并回读，STEP 与预期差集一致；装配位置和干涉另行核对。未验证所有版本、任意曲面和自动制造放行。
API：[CreatePlaneFixed2](https://help.solidworks.com/2021/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~CreatePlaneFixed2.html)。
