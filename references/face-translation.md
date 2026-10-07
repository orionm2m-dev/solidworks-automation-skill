# 原生面平移（pilot）

`solidworks_translate_faces` 使用零件坐标下的六值完整面包围盒选择目标；调用方必须提供 `expected_face_count`，先执行默认 `dry_run=true` 核对选择，再设为 false。新增 Move Face 特征，保留已有实体和特征树，不自动保存。需单配置零件、无活动草图；同名特征阻止重复执行。

输入 `translation_mm=[dx,dy,dz]` 为毫米。校验面数、实体 Check2、重建及位移回读。失败后仅删除本次创建的特征并验证体积与面数；`rollback_verified=false` 必须停止，不可当作恢复成功。

API: [InsertMoveFace3](https://help.solidworks.com/2015/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeatureManager~InsertMoveFace3.html)，平移类型 1，mark 1 选择面，VT_ARRAY|VT_R8 三向量，Distance=0，Blind=0。不选择方向参考，官方示例支持直接三向量。

包围盒不表示加工语义；边界必须排除邻接外表面。工具不能证明干涉、壁厚或装配公差，修改后必须检查原生预览与导出。当前自动回归为输入、选择及只读预检测试；真实 CAD 验证另行记录。
