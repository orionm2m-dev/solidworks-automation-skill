# 原位草图圆半径（pilot）

`solidworks_resize_sketch_circles` 通过草图局部毫米 `centers_mm`、`expected_radius_mm` 明确选择完整圆；`radius_mm` 指定新半径。默认 `dry_run=true` 读取圈数、圆心、半径、约束与实体检查。编辑保留原有圆实体，不重建其他线段，不保存。

要求单配置二维零件、没有活动编辑、目标草图无尺寸或关系、非构造圆。重复或模糊匹配失败关闭。改变后重建并核对所有圆心、半径、草图段数、实体数与 Check2。恢复失败时 `rollback_verified=false`，停止并使用备份恢复。

已核查安装版 SOLIDWORKS 2026 SP4.1 Interop: `ISketchArc.IsCircle(): int`、`GetRadius(): double`、`SetRadius(double): bool`；使用半径米值。`EditSketch`/`InsertSketch` 复用既有模式。特征投影、面颜色与段级外部引用仍须真实 CAD 审查；这里的匹配测试不代替真实模型验证。

真实验证：Windows / Python 3.12 / SOLIDWORKS 2026 SP4.1 (34.4.1)。四个圆由 R1.0 改为 R1.2，3891 条直线批量数据哈希不变，两实体体积不变且 Check2=0。DXF 参考草图必须显式 make_reference_editable=true，经 ISketch.SetSketchEditable(true) 转为普通草图；模型仍保留原投影与实体。

GetArcs2 的 16 值记录和 GetLines2 批量读取用于避免大型 DXF 逐段 COM 开销；几何选中后验证圆心、半径和 ISldWorks.IsSame 所属草图。API 来源：[SetSketchEditable](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISketch~SetSketchEditable.html)、[GetArcs2](https://help.solidworks.com/2018/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.isketch~getarcs2.html)。
