# 原生工程图布局（pilot）

`solidworks_create_drawing_layout` 从严格 JSON 布局创建新图纸。它只操作明确绑定的 SOLIDWORKS 进程，先验证当前已保存零件/装配体的完整路径，再创建独立工程图；输出已存在时拒绝覆盖。

支持原生命名视图、全深剖视、矩形裁剪、独立视图比例、图框、注释、投影参考尺寸、PDF/DXF。剖视引用实际模型，裁剪不修改零件。必须先使用 `dry_run=true` 检查模型视图名称（名称可能本地化）。布局坐标、尺寸均为毫米，纸面原点为左下角；剖切线及尺寸测点为模型坐标。

参考尺寸是图纸视图草图点之间的原生 `IDimension`，不是文本伪装尺寸。它们不关联模型拓扑；模型改变后须重新创建和核验，不能宣称自动更新。结果明确记录 `associative_to_model=false`，并按 `SystemValue` 验证调用者期望的数值，不覆盖显示值。生产放行仍需尺寸覆盖、基准、尺寸链及 PDF 视觉复核。此工具不自动签发标准符合性或生产批准。

尺寸创建期间暂时关闭“输入尺寸值”提示，结束后恢复设置。`solidworks_cancel_dimension_prompt` 仅取消绑定 PID 的已识别尺寸输入窗体，不处理保存或覆盖确认。

每次创建在 `.audit.json` 记录原生视图引用、比例、剖视/裁剪状态、尺寸值和文档路径。工具遇错可能留下部分工程图：不要重试覆盖，先核对路径并显式关闭或保留该图纸，再选择新输出路径。混合比例的 DXF 不能直接作为整页刀路；加工轮廓和放大解释视图必须分别确认比例。

实机验证：SOLIDWORKS 2026 SP4.1（34.4.1）、Windows、Python 3.10；1:1 和 5:1 剖视参考尺寸、PDF/DXF 输出已核验。2020–2025 未验证。每张图纸均须人工/视觉复核，能力等级保持 `pilot`。


## 装配剖视核验

全深剖视使用 `CreateSectionViewAt5`（深度参数 0）。剖切线应覆盖被切模型的完整投影范围，包括外露电缆等延伸零件。只有视图名称/类型是剖视不代表实际剖切成功；对必须切穿实体的视图设置 `minimum_hatched_faces`（例如 1），没有足够填充面时在导出前报错。文档级剖视标签统一为非斜体，避免模板字体意外放大。

`solidworks_inspect_drawing_sections` 是受文档路径保护的只读检查：返回排除组件、局部/仅剖面状态、实际填充数量、轻化状态和非零特征错误。应结合保存后重新打开的检查与 PDF 视觉复核；不能仅凭 API 返回的深度默认值断言剖切正常。

新增实机核验：SOLIDWORKS 2026 SP4.1，装配体全深剖视保存后重新打开，16 个填充面、无排除组件、剖视特征错误码 0；PDF 已视觉复核。此证据不扩展其他版本的支持范围。

## 同一编号的多页工程图

`solidworks_create_drawing_book` 读取 `DrawingBook` JSON：`output_path` 与有序 `sheets`；每页提供唯一 `name` 和既有 `DrawingLayout` 的 `layout`。全部页必须共享输出文件，工具继续按完整路径保护一个已保存源模型。支持 1–20 页；已有原生或导出文件时拒绝覆盖。

先运行 `dry_run=true`。实建时先保存首张图纸，再设置页名，避免本地化初始标题异步变化导致文档保护误报。后续页使用原生 `NewSheet3`，最终用 PDF `SetSheets` 导出全部页。DXF 暂设 `swDxfMultiSheetOption=swDxfMultiSheet`，并在 finally 中恢复原设置；首张图在 Model 空间，后续图在纸空间 layouts，验证不能只遍历 Model。每个页面的视图和参考尺寸审计保存在统一 `.audit.json`。

实机验证：SOLIDWORKS 2026 SP4.1（34.4.1），四个文档、共七页；页数、原生模型引用、剖视填充、原生尺寸与全部 DXF layouts 的测量值、PDF 文字边界及重叠已检查，PDF 已视觉复核。能力保持 pilot；参考尺寸仍非模型拓扑关联，模型修改后必须重新生成并复核。


### 裁剪视图边界检查

工程图创建会显示已选定的 SOLIDWORKS 实例，并在读取裁剪视图边界前重绘。隐藏会话可能返回完整模型的旧范围，按此范围居中会使局部视图和尺寸移出预期位置。工具拒绝越出图幅的视图；裁剪视图范围不得大于投影裁剪矩形加 25 mm 标签/边距余量。此门禁不能替代 PDF 图像复核，也不保证所有文字不重叠。

离线回归覆盖越界、无效边界、陈旧完整模型范围和正常标签余量。公开 API 依据：[IView.GetOutline](https://help.solidworks.com/2018/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IView~GetOutline.html)。实机验证结果在后续记录中补充。
