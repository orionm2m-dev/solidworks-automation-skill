# SolidWorks MCP Server

本目录提供一个本地 `stdio` MCP Server，同时暴露无 CAD 开放格式工具和 SolidWorks COM 白名单工具。MCP 与 CAD Studio、Skill、CLI 共用能力清单和数据协议。

SolidWorks 是 Windows 桌面 COM 应用，因此本 server 默认使用 `stdio`。每个 server 可以绑定一个已运行的 SOLIDWORKS 进程；原生操作按目标 PID 使用跨进程 Windows mutex 串行执行。两个独立的 server 分别绑定不同 PID 时可以并行工作。

## 绑定指定的 SOLIDWORKS 进程

多个 SOLIDWORKS 进程同时运行时，默认 COM 活动对象不一定是当前任务需要的实例。先调用无参数的 `solidworks_list_instances`，只读枚举已经向 Running Object Table 注册且可通过 COM 连接的实例；返回 `selected_process_id` 及 `instances`，每项包含 `process_id`、`revision`、`moniker` 和 `active_document`，不会激活文档或启动应用。此清单不保证包含尚未完成 COM 注册的所有操作系统进程。

使用 `solidworks_connect` 的 `process_id` 选择一个已运行的进程：

```json
{
  "params": {
    "process_id": 12345
  }
}
```

连接成功后，返回值中的 `process_id` 是实际回读的进程号，`session_target` 为 `{ "process_id": 12345, "scope": "mcp_server", "strict": true }`。首次未指定 PID 的成功连接也会固定实际选中的 PID。该 `stdio` server 的后续原生操作继续连接同一个 PID；省略 `process_id` 不会清除已经建立的绑定。再次显式连接其他 PID 时，只有连接成功才更新绑定，失败则保留原目标。

也可以在 MCP 子进程环境中设置 `SOLIDWORKS_MCP_PROCESS_ID`，提供首次连接时读取的默认目标。环境值必须是正整数；格式错误时连接失败，不代表 server 在启动时已经验证目标。以下是两个独立 server 配置的示例；路径和 PID 都需要替换为本机实际值：

```json
{
  "mcpServers": {
    "solidworks_design_a": {
      "command": "python",
      "args": ["C:\\path\\to\\solidworks-automation-skill\\mcp-server\\server.py"],
      "env": {
        "SOLIDWORKS_MCP_PROCESS_ID": "12345",
        "SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET": "1"
      }
    },
    "solidworks_design_b": {
      "command": "python",
      "args": ["C:\\path\\to\\solidworks-automation-skill\\mcp-server\\server.py"],
      "env": {
        "SOLIDWORKS_MCP_PROCESS_ID": "23456",
        "SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET": "1"
      }
    }
  }
}
```

指定 PID 不存在、尚未向 COM 注册或无法确认身份时，连接失败，不会退回默认活动实例，也不会自动启动替代进程。此工具不负责创建新的独立 SOLIDWORKS 实例。应用退出或重启后，重新确认进程号并显式绑定；修改环境配置需要重启 MCP 连接。

绑定后，原生 CAD 工具的结构化成功响应也带有 `process_id`；客户端应同时检查进程号和文档身份。恢复窗口工具在已确定目标 PID 时只枚举和处理该进程的窗口；没有已绑定或明确配置的 PID 时，允许诊断，但拒绝自动关闭模态对话框。

PID 模式下，预览辅助流程先核对文档的 COM 身份属于所选进程，再按完整路径激活已保存文档；装配辅助连接和类型库版本探测也继承目标。`comtypes` 的 Pack and Go 兜底尚未实现 PID 选择，因此在访问 COM 前拒绝执行，不会连接默认实例。此限制不表示原生 pywin32 Pack and Go 不可用；现有文件暂存策略仍按其明确的交付状态报告，不能把暂存包宣称为原生 Pack and Go 验证通过。

绑定范围是一个 MCP server 进程，不是聊天线程、文档或 Windows 用户会话。同一 server 被多个客户端任务共享时，显式更改绑定会影响它们；需要分别使用独立 server 配置，并核对连接返回的 PID。两个 server 指向同一 PID 时会共用 `Local\SolidWorksAutomation.Operation.v1.PID.<pid>` 并串行执行；不同 PID 使用不同 mutex，可并行执行。未绑定 PID 的旧式/诊断调用仍使用兼容全局锁 `Local\SolidWorksAutomation.Operation.v1`。PID 选择不会代替下面的文档路径保护，也不提供多步骤事务隔离。

验证范围：Windows / Python 3.10，SOLIDWORKS 2026 SP4.1（Revision 34.4.1）。全新 MCP `stdio` 进程已完成真实端到端验证：列出两个同时运行的实例、绑定指定实例、拒绝不存在的 PID 并保留原绑定、在原目标中以只读方式打开装配体并回读相同 PID；检查未修改模型内容。该只读装配体的预览激活也验证了所属进程及激活前后完整路径一致，未保存文档。底层连接分别回读两个实例的正确 PID 和活动文档。离线单元测试覆盖 PID 锁命名及不同 PID 的跨进程锁互不阻塞；尚未在两个真实 SolidWorks 会话中同时运行 MCP 操作，因此该并行路径仍为 `pilot`，不提供多步骤事务隔离。

## 文档目标保护与跨客户端互斥

活动窗口可能被另一个任务切换。对已保存文档的调用应携带 `expected_document_path`；路径不符时返回 `SW_DOCUMENT_MISMATCH`，不自动切换窗口，也不执行操作。同名文件必须按完整路径区分。需要切换目标时，显式调用 `solidworks_open_document`；已加载的原生文件也会被激活并回读路径。首次保存前可以使用 `expected_document_title`，但它只允许匹配尚未保存的文档。

```json
{
  "params": {
    "expected_document_path": "C:\\work\\part.SLDPRT",
    "color": "#F5A623"
  }
}
```

在 MCP 进程环境中设置 `SOLIDWORKS_MCP_REQUIRE_DOCUMENT_TARGET=1` 后，活动文档工具缺少目标校验参数也会拒绝执行。默认保持旧客户端兼容。新建、按明确路径打开、批量导出和无 CAD 工具保留自身的路径语义。首次保存使用创建操作返回的精确标题，保存后改用完整路径。启用目标保护时不能将单个目标与 `close_all` 混用。

Windows 下原生 COM 操作会持有按 PID 命名的 mutex `Local\SolidWorksAutomation.Operation.v1.PID.<pid>`，让使用本版本的多个 MCP 进程对同一 SolidWorks 实例串行执行，同时允许不同 PID 并行。CLI 可复用 `scripts.sw_operation_guard.solidworks_operation_lock()`；在 MCP 子进程设置 `SOLIDWORKS_MCP_PROCESS_ID` 时会自动采用相同的 PID 锁。C# 或 PowerShell 包装器应按相同规则构造锁名；未绑定进程的兼容路径仍用全局 mutex。异常退出、超时和未释放的句柄都有明确的失败路径。旧版客户端仍使用原全局锁，因此混用旧版 MCP 与新版 MCP 时不能保证同一 PID 的互斥；并行任务须使用已更新的 server。

此锁只覆盖一次操作，不预订整个多步骤任务。旧版客户端、未使用此锁的脚本、人工操作及加载项不受它约束；执行期间不要手动切换窗口，也不要并行运行旧控制脚本。目标检查发生在取得活动文档引用时，不能保证阻止长操作中的外部窗口切换。等待锁超时不会取消已经运行的 COM 调用。新代码和输入 schema 需要重启 MCP 客户端连接后才能生效。

验证范围：Windows / Python 3.10，文档误匹配的零写入测试、未保存标题、同名异路径、旧模式兼容、严格模式与真实跨进程 Windows mutex。SOLIDWORKS 2026 SP4.1（Revision 34.4.1）已通过全新 stdio MCP 进程验证：错误路径和缺失目标均在写入前拒绝，匹配路径的包围盒读取成功，原活动文档、保存标志及外观保持不变；该控制路径作为 `pilot`，不宣称提供事务回滚或隔离人工操作。

## 环境要求

- Windows 10/11
- 仅调用 `cadstudio_write_open_format` 时不需要安装 SolidWorks/AutoCAD
- 调用 `solidworks_*` 原生工具时需要 SolidWorks 已安装并至少启动过一次，完成 COM 注册
- Python 3.8+
- Python 依赖：

```powershell
pip install -r mcp-server\requirements.txt
```

## 启动

在仓库根目录运行：

```powershell
python mcp-server\server.py
```

该命令通常由 MCP 客户端作为子进程启动，不需要手动长期运行。

## Smithery 发布

根目录 `manifest.json` 遵循 MCPB 规范，并使用 `tools_generated: true`。先用 `mcpb pack` 生成标准包，再运行以下命令生成包含 FastMCP 实际 `inputSchema` 的 Smithery 发布包：

```powershell
mcpb pack . .\dist\solidworks-automation-skill-1.3.0.mcpb
python .\scripts\build_smithery_mcpb.py `
  .\dist\solidworks-automation-skill-1.3.0.mcpb `
  .\dist\solidworks-automation-skill-1.3.0-smithery.mcpb
smithery mcp publish .\dist\solidworks-automation-skill-1.3.0-smithery.mcpb `
  -n wzyn20051216/solidworks-automation-skill
```

Smithery 当前发布接口要求工具卡包含 `inputSchema`，而 MCPB 0.4 的静态 `tools` 项不允许该字段，因此发布包由脚本从 MCP Server 注册表自动生成，避免手工维护两套 schema。

## 多客户端自动注册

本仓库提供多客户端注册器，会自动尝试把 `solidworks` MCP Server 注册到：

- Codex
- Claude Code
- Claude Desktop
- Cursor
- Windsurf

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies
```

只注册指定客户端：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies -Clients codex,claude-code,cursor
```

Node.js 版本可直接用于 `npx` 安装器或 CI：

```powershell
node .\mcp-server\register_all_ai_mcp.js --install-dependencies
```

注册后可按客户端检查：

```powershell
codex mcp list
claude mcp list
```

> 通过本仓库 `npx` 安装时会自动运行多客户端注册器。某些 AI 客户端的纯 skill 导入不会执行安装脚本，需要在本地运行上述注册命令。

## Codex 专用注册

如果只想注册 Codex：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_codex_mcp.ps1 -InstallDependencies
```

## 手动配置

把路径替换为你的本地仓库路径：

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": [
        "C:\\path\\to\\solidworks-automation-skill\\mcp-server\\server.py"
      ]
    }
  }
}
```

如果你的客户端支持命令行注册，也可以使用类似命令：

```powershell
codex mcp add solidworks -- python C:\path\to\solidworks-automation-skill\mcp-server\server.py
claude mcp add --scope user solidworks -- python C:\path\to\solidworks-automation-skill\mcp-server\server.py
```

## 已暴露工具

| 工具 | 说明 | 是否修改 SolidWorks |
|---|---|---|
| `cadstudio_resolve_backend` | 按能力真源、接口语义、可用运行时、Revision 和加载项条件选择 Python/C#/C++/SWBasic/OCCT 等后端 | 否 |
| `cadstudio_write_open_format` | 从本地 `.cadstudio.json` 白名单写出 STEP/IGES/BREP/STL/OBJ/GLB/DXF/SVG/PDF/PNG、Preview Manifest/Scene 和几何/哈希证据 | 否 |
| `cadstudio_build_dxf_preview_scene` | 只读 DXF 白名单转换为不覆盖旧文件的 `.scene.json` | 否 |
| `cadstudio_check_dfm` | 对 NeutralCadDocument 执行机加工、钣金、激光切割或 3D 打印 DFM 规则检查，支持 supplier profile 与 B-Rep 证据；缺关键输入返回 blocked，规则通过仍需人工复核 | 否 |
| `cadstudio_check_routing` | 校验中性 Routing 端点、分段、长度、弯曲半径、碰撞/间隙、支撑和 Routing BOM | 否 |
| `cadstudio_routing_preflight` | 探测 SOLIDWORKS Routing 类型库、加载项注册和许可证证据；缺证据返回 blocked | 否 |
| `solidworks_addin_host_status` | 只读检查 C# Add-in 程序集、HKCU/HKLM 注册层级、进程内 UI/事件诊断和阻塞码 | 否 |
| `cadstudio_fea_preflight` | 探测 CalculiX/Elmer 求解器，不执行任意命令 | 否 |
| `cadstudio_prepare_fea` | 从 FEA 1.0/1.1 请求生成版本化 CalculiX `.inp`，不运行任意脚本 | 否 |
| `cadstudio_run_fea` | 运行白名单 CalculiX 线性或受限非线性静力任务并解析位移、应力和收敛证据 | 否 |
| `cadstudio_run_fea_convergence` | 运行 3-8 档白名单网格并比较末两档位移/应力变化 | 否 |
| `cadstudio_review_advanced_geometry` | 校验复杂曲面/模具中性计划并返回 pilot/blocked 门禁证据 | 否 |
| `cadstudio_create_ocp_loft` | 从白名单封闭截面生成真实直纹 Loft STEP/BREP/STL，并重开验证 B-Rep | 否 |
| `cadstudio_create_ocp_surface` | 从严格 JSON 生成平滑 Loft、直线/圆弧 Sweep、闭壳 Knit 或开放面 Thicken，并返回连续性采样证据 | 否 |
| `solidworks_health_check` | 检查 Python 依赖、SolidWorks 检测、Motion 类型库和可选实时连接 | 否 |
| `solidworks_connect` | 连接/启动 SolidWorks，或按 `process_id` 绑定已运行实例；返回实际 PID、绑定状态和活动文档摘要 | 否 |
| `solidworks_list_instances` | 无参数，只读枚举可通过 ROT 连接的实例、PID、版本和活动文档，不启动或激活文档 | 否 |
| `solidworks_new_document` | 新建零件/装配体/工程图 | 是 |
| `solidworks_create_basic_part` | 创建基础盒体/圆柱零件，可保存并设置文档颜色 | 是 |
| `solidworks_open_document` | 打开已有 SolidWorks 文档 | 是 |
| `solidworks_add_component` | 向活动装配体添加零件/子装配体，可选固定组件 | 是 |
| `solidworks_set_component_fixed` | 按组件名关键字固定或浮动装配体组件 | 是 |
| `solidworks_save_document` | 保存或另存为活动文档 | 是 |
| `solidworks_close_documents` | 关闭活动文档或全部文档 | 是，可能丢弃未保存修改 |
| `solidworks_add_coincident_mate` | 在两个组件的指定基准面/特征之间添加重合 Mate | 是 |
| `solidworks_add_distance_mate` | 在两个组件的指定基准面/特征之间添加距离 Mate | 是 |
| `solidworks_add_concentric_mate` | 按圆柱面半径范围添加同心 Mate，可选择是否锁转 | 是 |
| `solidworks_set_appearance` | 设置活动文档或指定组件外观颜色 | 是 |
| `solidworks_export_active` | 导出活动文档为 STEP/STL/IGES/Parasolid/PDF/DXF | 是，写输出文件 |
| `solidworks_inspect_configurations` | 读取配置清单和当前活动配置 | 否 |
| `solidworks_create_configuration` | 用 AddConfiguration3 创建/复用配置，可激活、重建、保存并回读 | 是 |
| `solidworks_activate_configuration` | 切换配置并用活动配置名和重建结果回读验证 | 是 |
| `solidworks_update_dimension` | 按准确尺寸名修改参数，返回修改前后、重建和保存证据 | 是 |
| `solidworks_set_custom_properties` | 写入并回读文件级或配置级自定义属性 | 是 |
| `solidworks_batch_export_files` | 多文件、多格式批量导出并核验本轮产物 | 是，写输出文件 |
| `solidworks_export_assembly_bom` | 导出装配组件/属性 BOM CSV，强制人工复核 | 是，写输出文件 |
| `solidworks_pack_and_go` | 使用原生 Pack and Go 打包文档与引用 | 是，写输出文件 |
| `solidworks_review_active` | 导出多视角 BMP 预览和 JSON 审查报告 | 是，写输出文件 |
| `solidworks_generate_drawing` | 按 DrawingSpec v1 生成 GB/T/ISO 工程图、SLDDRW、PDF、预览和审查报告；将 COM 尺寸位置与最终 PDF 文字框关联 | 是，写输出文件 |
| `solidworks_review_drawing` | 按 DrawingSpec 审查工程图结构、布局、尺寸链、孔槽和最终 PDF 尺寸文字边界 | 否，写审查输出 |
| `solidworks_inspect_drawing` | 只读读取工程图页、视图、尺寸、注释、表格和 BMP 预览证据 | 否，写审查输出 |
| `solidworks_create_hole_feature` | 创建盲孔、通孔、沉孔、沉头孔或半圆端槽，并返回参数证据 | 是 |
| `solidworks_inspect_hole_features` | 读取 B-Rep 孔段、复合孔、槽端圆弧并验证孔位 | 否 |
| `solidworks_add_rotary_motor` | 在活动装配体中新建 Motion Study 并添加匀速旋转马达 | 是 |
| `solidworks_inspect_motion_studies` | 读取算例、马达/外力数量和结果新鲜度 | 否 |
| `solidworks_validate_motion_study` | 对时长、类型、马达数量、结果存在性和过期状态执行交付门禁 | 否 |

## 基础装配工具示例

创建圆柱零件：

```json
{
  "shape": "cylinder",
  "radius_mm": 25,
  "depth_mm": 50,
  "output_path": "C:\\temp\\cylinder.SLDPRT",
  "color": "#BFC4C8"
}
```

向活动装配体添加组件并固定：

```json
{
  "path": "C:\\temp\\base.SLDPRT",
  "x_mm": 0,
  "y_mm": 0,
  "z_mm": 0,
  "fix_component": true
}
```

添加保留旋转自由度的同心 Mate：

```json
{
  "component_a_keyword": "stand",
  "component_b_keyword": "impeller",
  "radius_a_min_mm": 4.5,
  "radius_a_max_mm": 5.5,
  "radius_b_min_mm": 11,
  "radius_b_max_mm": 13,
  "lock_rotation": false
}
```

添加轴向距离 Mate：

```json
{
  "component_a_keyword": "stand",
  "component_b_keyword": "impeller",
  "feature_a_name": "Front Plane",
  "feature_b_name": "Front Plane",
  "distance_mm": 42
}
```

## Motion Study 示例

前提：活动文档是装配体，里面有一个静止轴/立柱组件和一个叶轮组件；叶轮的同心 Mate 未锁定旋转，且叶轮组件未固定。

调用参数示例：

```json
{
  "shaft_component_keyword": "stand",
  "rotor_component_keyword": "impeller",
  "shaft_radius_min_mm": 4.5,
  "shaft_radius_max_mm": 5.5,
  "rotor_radius_min_mm": 10.5,
  "rotor_radius_max_mm": 11.5,
  "rpm": 60,
  "study_name": "叶轮_60RPM_循环转动",
  "motor_name": "叶轮旋转马达_60RPM",
  "duration_seconds": 4,
  "calculate": true,
  "play": false
}
```

创建复杂沉孔：

```json
{
  "feature_kind": "counterbore",
  "center_x_mm": 20,
  "center_y_mm": 15,
  "diameter_mm": 6,
  "secondary_diameter_mm": 12,
  "secondary_depth_mm": 4,
  "plane_name": "Front Plane",
  "feature_name": "H1_沉孔"
}
```

验证 Motion Study：

```json
{
  "study_name": "叶轮_60RPM_循环转动",
  "expected_study_type": 1,
  "minimum_duration_seconds": 4,
  "minimum_motor_count": 1,
  "require_results": true
}
```

## 设计原则

- 不开放任意 Python/VBA 执行工具，避免 MCP 客户端直接执行不受控脚本。
- CAD Studio 无头/门禁工具使用 `cadstudio_` 前缀，SolidWorks 原生工具使用 `solidworks_` 前缀，避免与其他 MCP server 冲突。
- 同一 SolidWorks PID 的 COM 操作通过跨 MCP 进程的 Windows mutex 串行执行；不同 PID 可并行执行。
- 错误返回包含建议动作，方便 LLM 自行纠错。

## 已知限制

- MCP 已覆盖基础盒体/圆柱、复杂孔槽、添加组件、常用 Mate、固定/浮动、外观、导出、审查、旋转马达、Motion 结果门禁，以及 DFM/Routing/FEA/复杂几何的受控入口。
- 受限封闭直纹 Loft 可生成并重开真实 STEP/BREP；平滑 Loft、扫描、自由曲面、G1/G2 和模具仍只开放结构化计划门禁。
- SolidWorks Motion / Simulation 许可证差异可能影响计算能力；缺少合法加载项或授权时返回 `blocked`，不尝试绕过。

`solidworks_translate_faces`: bounds_mm、translation_mm、expected_face_count、feature_name；先 dry_run，详见 [原生面平移](../references/face-translation.md)。
