# SolidWorks MCP Server 设计说明

## 架构

```text
Codex / Claude / 其他 MCP Client
        ↓ stdio MCP
mcp-server/server.py
        ↓ Python COM / pywin32
SolidWorks Desktop
```

SolidWorks 是 Windows 桌面 COM 应用，不是原生 MCP 服务。MCP Server 的职责是把已经验证过的 `scripts/sw_*.py` 封装成受控工具，避免代理每次临时生成大段脚本。

## Transport 选择

默认使用 `stdio`：

- 适合本地桌面软件。
- 客户端作为子进程启动 server，配置简单。
- 不暴露网络端口，减少安全面。

暂不默认使用 HTTP：

- SolidWorks COM 一般绑定当前桌面用户会话。
- 多客户端并发容易让 SolidWorks 文档状态混乱。
- 远程访问还需要身份认证、Origin 校验和桌面会话隔离。

## 多客户端注册策略

安装器会调用 `mcp-server/register_all_ai_mcp.js`，尽量自动注册常见本地 AI 客户端：

- Codex：通过 `codex mcp add solidworks -- <python> <server.py>` 注册。
- Claude Code：通过 `claude mcp add --scope user solidworks -- <python> <server.py>` 注册。
- Claude Desktop：写入用户级 `claude_desktop_config.json`。
- Cursor：写入全局 `~/.cursor/mcp.json`。
- Windsurf：写入全局 `~/.codeium/windsurf/mcp_config.json`。

注意：

1. 只有执行 `npx` 安装器或注册脚本时，才能自动修改本机 MCP 配置；纯 skill 导入通常不会运行安装脚本。
2. 不同客户端可能需要重启或人工确认信任后才会加载新 MCP。
3. 云端网页产品没有本机配置入口时，skill 无法替用户直接安装本地 MCP。
4. JSON 配置写入前会创建 `.bak-*` 备份；命令行客户端会先移除同名 server 再重新注册。

## 进程目标与连接生命周期

`solidworks_connect` 可接收正整数 `process_id`，指定已经运行的 SOLIDWORKS 进程。底层通过 Running Object Table 查找该进程的 COM 对象，并回读应用 PID；无法取得并验证目标时，直接失败，不回退到 `GetActiveObject` 或新建实例。未指定 PID 且 server 尚未绑定目标时，保持原有连接行为。

MCP server 保存一次成功连接确定的进程目标；后续原生工具通过统一连接包装器继续使用该 PID，而不是在每次调用时重新选择默认活动对象。显式连接另一个 PID 必须成功后才替换绑定。`SOLIDWORKS_MCP_PROCESS_ID` 提供首次连接时读取的默认目标，格式错误会使连接失败；`solidworks_connect` 返回实际 `process_id` 和 `session_target: {process_id, scope: "mcp_server", strict: true}`，便于客户端核对。首次默认连接也会固定实际 PID；绑定后，原生 CAD 工具的结构化成功响应带有 `process_id`。

无参数工具 `solidworks_list_instances()` 只读枚举可连接的 ROT 项，返回 `selected_process_id` 与实例列表；每项包含 PID、版本、moniker 和活动文档摘要。不启动应用、不激活文档，也不保证列出尚未注册到 ROT 的进程。恢复窗口工具在 PID 已绑定或明确配置时只枚举和处理该进程；没有目标 PID 时只允许诊断，拒绝自动关闭模态对话框。

此状态只属于当前 `stdio` server 进程。它不会为每个聊天任务分配独立实例，也不会自动启动新的独立 SOLIDWORKS 进程。多个任务应使用不同的 MCP 配置项和进程号；共享一个 server 的任务必须协调显式切换目标。应用重启后 PID 可能变化，必须重新确认和绑定。PID 绑定仍要求文档级 `expected_document_path` / `expected_document_title` 校验。

预览辅助流程在激活前确认文档的规范 IUnknown 身份属于所选应用，并对已保存文档使用完整路径；不能仅凭同名文档或相同磁盘路径判断所属实例。装配辅助连接和类型库版本探测继承环境中的 PID 目标。`comtypes` Pack and Go 兜底不具备 PID 选择能力，绑定模式会在任何 COM 访问前阻断该分支；原生 pywin32 路径及明确标记的文件暂存策略保留原有语义。

真机验证：Windows / Python 3.10 / SOLIDWORKS 2026 SP4.1（Revision 34.4.1）。新的 `stdio` MCP 进程已列出两个实例、绑定指定实例、验证失败重绑保留原目标，并在该进程中以只读方式打开装配体和回读 PID。该只读装配体的预览激活也通过 COM 所有权与前后完整路径回读，未执行保存，未修改模型内容。能力仍为 `pilot`；这些结果不等于全部功能和版本的真机验证。

## 并发策略

`mcp-server/server.py` 使用全局 `RLock` 串行执行所有工具。原因：

- SolidWorks COM 自动化不是线程安全的通用服务。
- 多个工具同时切换活动文档、选择实体或保存文件，会互相破坏状态。
- Motion Study / Mate 创建依赖当前选择集，必须避免并发污染。

每个工具调用前会尝试 `pythoncom.CoInitialize()`，保证当前 MCP worker 线程可使用 COM。原生操作还取得 `Local\SolidWorksAutomation.Operation.v1`，使不同 MCP server 的协作操作串行执行；选择不同 PID 不会关闭此 mutex。锁不覆盖整段多步骤工作流，也不能阻止人工操作或未采用相同锁的控制脚本。

## 工具命名

工具名前缀按能力边界区分：`cadstudio_` 用于无头开放格式、DFM、Routing、FEA 和复杂几何门禁；`solidworks_` 用于真实 SolidWorks COM 操作。

CAD Studio 门禁工具：

- `cadstudio_resolve_backend`
- `cadstudio_write_open_format`
- `cadstudio_build_dxf_preview_scene`
- `cadstudio_check_dfm`
- `cadstudio_check_routing`
- `cadstudio_routing_preflight`
- `cadstudio_fea_preflight`
- `cadstudio_prepare_fea`
- `cadstudio_run_fea`
- `cadstudio_run_fea_convergence`
- `cadstudio_review_advanced_geometry`
- `cadstudio_create_ocp_loft`
- `cadstudio_create_ocp_surface`

SolidWorks 原生工具：

- `solidworks_connect`
- `solidworks_list_instances`
- `solidworks_new_document`
- `solidworks_open_document`
- `solidworks_inspect_configurations`
- `solidworks_create_configuration`
- `solidworks_activate_configuration`
- `solidworks_save_document`
- `solidworks_close_documents`
- `solidworks_export_active`
- `solidworks_review_active`
- `solidworks_add_rotary_motor`

## 安全边界

第一阶段不开放：

- 任意 Python 执行。
- 任意 VBA 宏执行。
- 直接删除文件。
- 批量关闭/覆盖用户文件的隐藏动作。

如需新增危险工具，至少要：

1. 明确工具名含 `delete` / `overwrite` / `close_all` 等动作。
2. 输入 schema 限制路径和参数范围。
3. 返回结构化结果，包含实际影响范围。
4. 在文档中标注 `destructiveHint=True`。

## 扩展顺序建议

优先扩展高价值、低歧义工具：

1. 文档与导出：打开、保存、导出、审查。
2. 装配体：添加组件、按组件名查找、创建同心/重合 Mate。
3. Motion Study：旋转马达、线性马达、计算/播放。
4. 零件建模：受控草图原语和特征原语。
5. 工程图：三视图、BOM、PDF 导出。
6. 无头能力：DFM profile、Routing 中性复核、CalculiX 受限线性/非线性与网格序列、OCP 直纹/平滑 Loft、Sweep/Knit/Thicken 和其余复杂几何计划复核。

暂缓扩展：

- 任意草图约束求解。
- 平滑 Loft、复杂扫描、G1/G2/Class-A 和模具质量 B-Rep 生成。
- 大型接触、自动穿透验收、碰撞等高阶仿真与安全认证。

## 返回格式

工具默认返回 JSON，便于 LLM 继续解析。也支持 `response_format="markdown"` 用于人工阅读。

错误返回应包含：

- `error_type`
- `message`
- `suggestion`

不要把 Python traceback 原样暴露给 MCP 客户端。
