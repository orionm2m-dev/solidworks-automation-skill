# SolidWorks MCP Server

## SOLIDWORKS CAM

Native CAM discovery, loading and guarded inspection are documented in
[`references/solidworks-cam.md`](../references/solidworks-cam.md). These tools
require an already pinned process and an explicit document target. They do not use UI
automation or infer a machining license from installed files.

Single-operation toolpath qualification uses `solidworks_cam_prepare_toolpath_job`
and the persistent `scripts.sw_cam_jobs` native module. Job status, cooperative
observer cleanup and operation diagnostics have dedicated MCP tools. The
observed turning GTP call has not yet produced a verified path; a false success
flag is not a proven running state, and observer cleanup is not CAM cancellation.

The calibration-step tool supports native feature extraction and
operation-plan generation with event logging, exact inventory preconditions and
exclusive receipts. It does not generate toolpaths, post NC or save the part.
The reusable `scripts/mcp_request.py` client performs sequential protocol calls from JSON
and records results without overwriting existing evidence.

本目录提供一个本地 MCP Server，同时暴露无 CAD 开放格式工具和 SolidWorks COM 白名单工具。MCP 与 CAD Studio、Skill、CLI 共用能力清单和数据协议。

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

除 `stdio` 外，还可用 `--transport streamable-http` 把同一套工具以 HTTP 方式暴露，供**不在同一台机器上**的 MCP 客户端连接（例如 Linux 上的 agent 远程驱动 Windows 上的 SolidWorks）。此时全局串行锁依然生效，请仍然只接一个客户端。

## 环境要求

- Windows 10/11
- 仅调用 `cadstudio_write_open_format` 时不需要安装 SolidWorks/AutoCAD
- 原生 SolidWorks 操作以 SolidWorks 2026 为支持与验收目标；安装后至少启动一次，完成 COM 注册
- Python 3.10+
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

## 工具发现网关（可选，默认关闭）

不设置 `SW_MCP_DISCOVERY` 和 `SW_MCP_APPROVAL` 时不安装网关：`tools/list` 列出全部命名工具，
调用直接执行，PID 绑定、文档目标校验和跨进程 mutex 照常生效。设置任一变量后，服务端在全部
工具注册完成后安装网关：`SW_MCP_DISCOVERY=search` 时 `tools/list` 只暴露三个发现入口，原生工具
按需检索；`SW_MCP_DISCOVERY=full`（或只设置 `SW_MCP_APPROVAL`）时保留全部命名工具，调用同样
经过网关。

网关只执行 `mcp-server/policy.py` 登记了副作用等级的工具，未登记的工具一律拒绝。当前分级只
覆盖通用建模、装配、导出、工程图、CAD Studio 和原生路径工具；CAM、进程列表与运行身份
（`solidworks_list_instances`、`solidworks_runtime_status`）、组件变换、胶囊草图、原生工程图
布局等工具尚未登记，启用网关后会被拒绝。启用前须在 `policy.py` 补齐分级，覆盖情况由
`tests/test_mcp_discovery.py` 的 `test_policy_covers_every_registered_tool` 检查。

发现模式下 `SW_MCP_APPROVAL=auto` 信任客户端已取得当前任务授权，任务内调用不再逐次请求服务端
批准；需要更严格控制时可启用 `server` 模式。初始工具列表体积可通过
`python -m pytest -q tests/test_mcp_discovery_quality.py` 验证。

| 入口 | 作用 |
| --- | --- |
| `sw_search_tools` | 按中英文说法检索候选，返回名称、说明、相关度和副作用等级；不执行操作 |
| `sw_describe_tool` | 读取单个工具的完整输入 Schema、副作用等级和是否需要人工批准 |
| `sw_call_tool` | 按名称执行；经过策略检查，审批行为取决于所选模式及其信任边界 |

直接点名调用被隐藏的原生工具同样会经过网关，未知工具一律拒绝。

网关启用后需要客户端逐工具展示权限提示时，用 `SW_MCP_DISCOVERY=full` 显示全部命名工具。
两种网关模式共用同一套执行检查；`stdio` 和 `--transport streamable-http` 行为一致。

### 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SW_MCP_DISCOVERY` | 未设置（不安装网关） | `search` 发现模式；`full` 原生命名工具经网关调用 |
| `SW_MCP_APPROVAL` | 未设置（网关启用时按 `auto`） | `auto`：发现模式用 `task`、完整模式用 `client`；`task`：信任客户端的任务授权，不逐次确认；`server`：本地逐次审批账本；`client`：交给客户端逐工具审批，仅允许完整模式；`elicit`：走 MCP elicitation（可能被 agent 自动应答）；`off`：关闭服务端审批 |
| `SW_MCP_APPROVAL_DIR` | `%LOCALAPPDATA%\SolidWorksMCP\approvals` | 审批账本目录 |
| `SW_API_LOOKUP_NETWORK` | `on` | 设置 `off` 禁止本项目 API 查证访问官方文档；不控制客户端自己的搜索 |
| `SW_API_LOOKUP_AUTO_INSTALL` | `on` | 设置 `off` 禁止 API 查证自动安装依赖和恢复帮助文件 |
| `SW_AUTO_INSTALL_DEPENDENCIES` | `on` | 设置 `off` 禁止基础 COM 预检和桌面执行器自动安装依赖 |

`solidworks_lookup_api` 支持 `interface` + `member` 或自然语言 `task`，按目标版本查证本机类型库、API Help 和官方文档；直读失败且无缓存时使用匿名 Parallel，仅发送公开版本、接口、成员及官方链接。默认按需自动配置依赖，MCP 注解因此标记为可能修改环境；`auto_install=false` 禁用安装，`offline=true` 禁用联网和安装。服务端会按参数区分副作用，用户配置的服务端审批模式仍然生效。结果区分版本证据、来源和获取时间，不能代替真机验证。多个目标无法确定时不会猜测或启动 SolidWorks。`solidworks_connect` 支持可选 `version` 年份并检查实际连接版本。

### 任务授权和可选逐次审批

网关启用时，`task` 模式（发现模式下 `auto` 的取值）由客户端或用户负责界定任务授权；MCP 服务端**不能验证**客户端是否实际
询问过用户，不提供逐工具权限隔离。服务端仍会拒绝未登记的工具，并沿用参数校验、
目标限制与 SolidWorks 串行执行；具备相同本机权限的进程可以绕过本服务。

已保存文档的活动文档操作可选传入 `document_target`（绝对 `path` 和 `process_id`），
服务端将核对目标；不传时沿用工具原有的活动文档行为，以支持未保存文档和现有工作流。

以下是显式选择 `SW_MCP_APPROVAL=server` 时的逐次审批机制。

**信任边界：**审批账本和命令行运行在同一操作系统用户权限下。TTY 检查不能证明
输入来自真人：具有该用户权限的进程可能模拟终端或直接访问账本和签名密钥。因此，
账本适用于可信本地环境中的操作确认，不是隔离同用户 Agent 或恶意进程的安全边界。
需要可靠逐操作的人审时，应使用经过验证的可信客户端/独立审批机制；`client`、
`elicit` 和 `off` 模式也不能单凭配置名称保证存在人工确认。

工具可能使用活动文档、间接路径或输入文件中的引用。目前范围授权已停用，旧范围授权也不会
被消费。`server` / `elicit` 模式下，支持绑定的活动文档操作必须经 `sw_call_tool` 提供
`document_target`，包含已保存文档的绝对 `path` 和 SolidWorks `process_id`。例如先使用
`solidworks_connect` 读取 `process_id` 与 `document.path`，再把两者放进 `document_target`；
服务端将目标与参数一起展示并绑定到批准，在持锁获取活动文档时复核 PID 和路径。

未保存的文档、关闭文档、文档单位设置、添加组件、模型审查、Pack and Go 及原生子进程
操作暂不支持此绑定并保持阻止。PID 和路径用于定位，
不能证明文档内容或外部引用未变化，也不能隔离具有相同系统用户权限的进程。`full` +
`client` 或 `off` 保持原有客户端控制，但服务端不保证其审批有效。本机制尚未完成真实
SolidWorks 的目标切换验证，不应将其当作已验收的安全边界。

模型传入 `approved: true` 或类似参数不会生效。写操作被阻止时，返回内容会给出审批请求 ID，
需要在能访问本机的终端执行：

```powershell
python scripts\sw_mcp_approve.py list
python scripts\sw_mcp_approve.py approve <请求ID>
```

批准与「工具 + 完整参数摘要 + 服务端会话 + 有效期」绑定，一次性使用（默认 15 分钟）；
参数改变、服务端重启或更换会话后需重新请求批准。显式路径包含在参数中，但不代表
已校验输入文件内容、隐式引用或文档状态；不能将该机制用于不可信环境。
请求记录和授权记录各有 1000 条上限；达到上限时服务端安全拒绝新增记录，不自动删除
历史文件。用户需确认记录归属后自行备份和归档，才能继续使用审批。

### 启用网关

默认不设置变量即保持原有界面：全部原生工具可见、直接调用，由客户端决定是否逐工具审批。
补齐 `policy.py` 分级后，可在 MCP 客户端配置里给 server 进程加环境变量启用发现模式：

```jsonc
{
  "command": "python",
  "args": ["C:\\path\\to\\mcp-server\\server.py"],
  "env": { "SW_MCP_DISCOVERY": "search", "SW_MCP_APPROVAL": "auto" }
}
```

`{ "SW_MCP_DISCOVERY": "full", "SW_MCP_APPROVAL": "client" }` 保留全部命名工具，同时经过网关的
策略检查。修改环境变量后需重启 MCP 连接。

### 协议验证

```powershell
python scripts\validate_mcp.py                # 校验打包注册表、默认界面、full 和 search
python scripts\validate_mcp.py --mode both    # 只校验 full 和 search
python scripts\validate_mcp.py --mode bundle  # 只校验打包注册表
python scripts\validate_mcp.py --mode search
```

默认界面和完整模式校验必需工具全部可见且不暴露发现入口；发现模式校验会确认 3 个入口可见、
每个必需工具都能按名称检索并读到 Schema。打包注册表校验在不设置网关变量的环境中运行
`build_smithery_mcpb.py` 的工具卡收集：search 恰好是 3 个发现入口，full 包含全部必需工具。
每种模式都会先核对服务端输入校验用的螺纹库类型与 `scripts/sw_thread_feature.py` 一致。

## HTTP 传输（streamable-http）

当 MCP 客户端与 SolidWorks 不在同一台机器上时（例如 Linux 上的 agent 驱动 Windows 上的 SolidWorks），无法让客户端直接拉起本机的 stdio 子进程，此时改用 HTTP 传输：

```powershell
python -m pip install uvicorn
$env:SW_MCP_TOKEN = "<替换为随机共享密钥>"
python mcp-server\server.py --transport streamable-http --host 0.0.0.0 --port 8000 `
  --allow-host "192.168.1.10:*" --output-root "C:\cad-output"
```

- 端点：`http://<本机IP>:8000/mcp`（Streamable HTTP，FastMCP 默认路径 `/mcp`）
- `--host` 默认 `127.0.0.1`；局域网访问需显式传 `0.0.0.0`，并放行对应端口的防火墙
- `--port` 默认 `8000`
- 也可用环境变量 `SW_MCP_HOST` / `SW_MCP_PORT` 提供默认值，命令行参数优先
- **`uvicorn` 是可选依赖**：仅在 `--transport streamable-http` 时需要；缺失时会给出明确提示
- 默认值仍是 `stdio`，现有 MCP 客户端配置无需改动
- 非回环监听必须设置 `SW_MCP_TOKEN` 和显式 `--allow-host`；Host 填客户端访问的实际 IP/域名，可重复指定
- 客户端请求携带 `Authorization: Bearer <共享密钥>`；浏览器客户端另需明确 `--allow-origin "https://客户端域名"`
- Host/Origin 校验保持开启；用本机私有测试端点验证过握手、401、错误 Host 与错误 Origin 拒绝
- 通过公网或不可信网络连接时，使用带 TLS 的反向代理或受控隧道保护传输

客户端配置示例（OpenCode / 其他支持 remote MCP 的客户端）：

```jsonc
{
  "mcp": {
    "servers": {
      "solidworks": {
        "type": "remote",
        "url": "http://192.168.1.10:8000/mcp",
        "headers": { "Authorization": "Bearer <共享密钥>" }
      }
    }
  }
}
```

客户端的 URL/headers 配置字段以对应客户端文档为准。该传输使用现有 MCP 进程和 COM 串行锁。

### 取回预览与交付文件

输出文件位于 `--output-root`（或 `SW_MCP_OUTPUT_ROOT`）内时，工具结果附加 `artifact_refs`，包含不透明 `artifact_id`、`uri`、文件大小和 SHA-256。未配置时只允许系统临时目录下的 `solidworks-automation-artifacts`；建议明确指定交付目录。

- 调用 `cadstudio_read_artifact`，参数为 `{"params":{"artifact_id":"<结果中的 ID>"}}`，小图返回标准 PNG 内容块。
- 用 `resources/read` 读取结果中的 `cad-artifact://delivery/...` URI，取回不超过 8 MiB 的原始二进制文件。
- 大文件用 `cadstudio_read_artifact`，设置 `as_preview:false`、`offset`、`max_bytes`，按 `next_offset` 拼接 base64 块；完成后比对 SHA-256。
- 读取适配复用既有 Artifact Ledger；文件改变、目录越界或任意路径参数均不能作为已验证产物读取。

远端输入仍需预先放到 CAD 主机；产物读取接口只服务已有交付文件。
工具数量随版本变化，以 `tools/list` 为准；`scripts/validate_mcp.py` 会输出各模式的可见数量。发现模式下这些工具不出现在 `tools/list` 中，但检索、Schema 读取和执行行为与完整模式一致。`cadstudio_list_drc_rules` 列出设计审计规则；`cadstudio_check_drc` 检查中性文档并写报告，属于写操作，严格模式需要审批。API 查证可按需配置依赖，其权限行为见上文。

## Windows MCPB 扩展

在支持 MCPB 的桌面客户端中导入正式发布的 `SolidWorks-Automation-Skill-<版本>.mcpb`。
例如，在 Claude Desktop 的扩展设置中进入高级设置，选择 **Install Extension…** 并打开该文件。
原生 SolidWorks 工具需要已安装并获得许可的 SolidWorks。扩展沿用 MCP 服务的默认界面；只有在扩展配置中设置 `SW_MCP_DISCOVERY` 或 `SW_MCP_APPROVAL` 时才启用发现网关和写操作审批。

启动器会查找 `uv` 并按包内锁文件准备 Python 3.12 环境。首次运行需要能够获取 Python 和依赖。
如果客户端日志显示缺少 `uv`，请运行下列命令，随后完全退出并重开客户端，再启用扩展。
没有 WinGet 时，请参照 [uv 官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)。

```powershell
winget install --id astral-sh.uv -e
```

从 Git 检出的仓库本地打包时，使用发布脚本生成标准包。Smithery 变体从同一个包生成，并从运行时注册表读取实际的工具输入 Schema。

```powershell
$version = (Get-Content package.json -Raw | ConvertFrom-Json).version
python .\scripts\build_mcpb.py
python .\scripts\build_smithery_mcpb.py `
  ".\release-output\SolidWorks-Automation-Skill-$version.mcpb" `
  ".\release-output\SolidWorks-Automation-Skill-$version-smithery.mcpb" --repo-root .
```

文件名带 `-smithery` 的变体用于 Smithery 的工具清单。桌面扩展请选标准包。
服务端注册表始终包含三个发现入口和全部命名工具，工具卡因此与打包时的环境变量无关。
Smithery 变体会把 `SW_MCP_DISCOVERY=<mode>`（默认 `search`，可用 `--mode full`）写进清单，
运行时即启用网关：`policy.py` 未登记的工具（目前包括 CAM 等工具，见上文“工具发现网关”）
在该变体中会被拒绝执行，补齐分级前只能使用已登记的工具。标准包不设置这些变量。
Windows 正式发布同时提供 MCPB 和带签名的 CAD Studio 安装包。

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
| `cadstudio_read_artifact` | 按交付 ID 返回 PNG 预览或有界二进制块，校验已有 Ledger 的 SHA-256 | 否 |
| `cadstudio_check_dfm` | 对 NeutralCadDocument 执行机加工、钣金、激光切割、3D 打印或注塑声明型 DFM 检查；缺关键输入返回 blocked，规则通过仍需人工复核 | 否 |
| `cadstudio_check_routing` | 校验中性 Routing 端点、分段、长度、弯曲半径、碰撞/间隙、支撑和 Routing BOM | 否 |
| `cadstudio_routing_preflight` | 探测 SOLIDWORKS Routing 类型库、加载项注册和许可证证据；缺证据返回 blocked | 否 |
| `solidworks_addin_host_status` | 只读检查 C# Add-in 程序集、HKCU/HKLM 注册层级、进程内 UI/事件诊断和阻塞码 | 否 |
| `solidworks_lookup_api` | 按目标版本查证 API；默认联网并按需自动安装依赖，不启动或修改 CAD | 按参数：默认可能修改环境；可关闭自动安装 |
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
| `solidworks_list_component_transforms` | 只读列出组件的局部坐标轴方向、原点与包围盒（毫米），可含子装配体 | 否 |
| `solidworks_set_component_transform` | 按局部坐标轴方向与原点（刚体变换）放置顶层组件并回读核对，不保存 | 是 |
| `solidworks_set_component_visibility` | 在当前显示状态中隐藏或显示顶层组件（不压缩），回读核对，不保存 | 是 |
| `solidworks_save_component_copy` | 把组件（含导入装配体的虚拟组件）另存为独立副本文件，装配体引用不变 | 是 |
| `solidworks_set_component_suppression` | 压缩或解压顶层组件（SetSuppression2），回读 IsSuppressed，不保存 | 是 |
| `solidworks_reorganize_components` | 把组件移入已插入的子装配体组件或移回顶层（ReorganizeComponents），移动前后回读变换与包围盒，位置必须不变；SolidWorks 把移入的实例改名为文件名时按文档路径与变换匹配（moved[].renamed），不保存 | 是 |
| `solidworks_delete_components` | 删除顶层组件及依赖它们的配合（DeleteSelection2），回读顶层组件列表核对，不保存 | 是 |
| `solidworks_list_circular_edges` | 只读列出零件圆形边的圆心、轴向与直径（毫米），导入实体同样可用 | 否 |
| `solidworks_add_thread_feature` | 按圆心与直径定位起始边，创建原生螺纹特征（库规格如 M10x1.5；库中没有的规格报错并删除回落生成的特征；可用 `pitch_mm`、`diameter_mm` 覆盖螺距与直径），回读体积与面数变化，不保存 | 是 |
| `solidworks_save_document` | 保存或另存为活动文档；`save_referenced` 同时保存本会话中被修改的引用文档（重组后的子装配体） | 是 |
| `solidworks_close_documents` | 关闭活动文档；或 `close_all` + `allowed_document_roots`：所有打开文档（含隐藏引用）须位于给定目录内且已保存（或显式 `discard_unsaved_changes`），才一次关闭全部 | 是，可能丢弃未保存修改 |
| `solidworks_add_coincident_mate` | 在两个组件的指定基准面/特征之间添加重合 Mate | 是 |
| `solidworks_add_distance_mate` | 在两个组件的指定基准面/特征之间添加距离 Mate | 是 |
| `solidworks_add_concentric_mate` | 按圆柱面半径范围添加同心 Mate，可选择是否锁转 | 是 |
| `solidworks_set_appearance` | 设置活动文档或指定组件外观颜色 | 是 |
| `solidworks_export_active` | 导出活动文档为 STEP/STL/IGES/Parasolid/PDF/DXF | 是，写输出文件 |
| `solidworks_inspect_configurations` | 读取配置清单和当前活动配置 | 否 |
| `solidworks_create_configuration` | 用 AddConfiguration3 创建/复用配置，可激活、重建、保存并回读 | 是 |
| `solidworks_activate_configuration` | 切换配置并用活动配置名和重建结果回读验证 | 是 |
| `solidworks_update_dimension` | 按准确尺寸名修改参数，返回修改前后、重建和保存证据 | 是 |
| `solidworks_read_explode_step_transforms` | Read exact existing single-component step matrices with PID, source and full snapshot guards; pilot | No |
| `solidworks_read_custom_properties` | Read requested file/current-configuration properties with PID, path and state guards; pilot pending native qualification | No |
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

## 已有胶囊草图修改（pilot）

`solidworks_inspect_capsule_sketch` 读取二维四段胶囊的总长、宽度、中心、方向、圆弧/直线、尺寸及关系状态。`solidworks_resize_capsule_sketch` 在原草图内重建两个半圆和两条直线，保留草图名称、位置、方向、原生切除及下游特征树。重建会更换段级身份，不保证外部或工程图引用不变，须人工复核。

仅支持单配置零件、无关系和尺寸的独立四段草图；只读文档、活动草图编辑、原生 Slot 对象、非胶囊或预先损坏的实体均拒绝。已有驱动尺寸应使用 `solidworks_update_dimension`。

调用必须携带 `expected_document_path`，或未保存文档的 `expected_document_title`。示例参数：`sketch_name="AccessProfile", length_mm=12, width_mm=4`，总长必须大于宽度。新尺寸回读、闭合轮廓、特征树、实体数量和 Check2 必须通过；工具不保存文档。先备份源文件；失败返回 `rollback_verified`，若为 false，应停止保存及后续修改。SW2026 某些草图操作不能建立统一撤销记录；成功结果如实返回 `undo_record_created=false`，不承诺事务恢复。

验证：Windows / Python 3.10 / SOLIDWORKS 2026 SP4.1（34.4.1），真实 stdio MCP 在测试副本完成双向尺寸修改，原切除及下游加工特征保留，实体检查无错误。单元测试覆盖旋转/平移、非法轮廓、只读/约束门禁、修改失败、撤销失败、成功但原生统一撤销不可用、文档目标保护。其他版本及尺寸/关系约束草图未验证。
## FeatureWorks 识别提示恢复（pilot）

`solidworks_cancel_featureworks_prompt` 只取消明确绑定 PID 内的 FeatureWorks 特征识别提示。它检查窗口进程、标题、识别提示文字及唯一的“否”按钮，发送该按钮实际命令 ID；不会接受识别、关闭文档或确认保存。当前支持英文、俄文和中文提示，未识别语言只返回诊断。

恢复不执行 COM，也不等待模型操作 mutex，因为被提示阻塞的打开调用可能持有该锁。此例外只用于取消已知提示；返回 `posted` 表示消息已提交，需检查原调用完成及目标文档回读。调用前必须显式绑定进程，或配置 `SOLIDWORKS_MCP_PROCESS_ID`。

实测：Windows / Python 3.10 / SOLIDWORKS 2026 SP4.1（34.4.1），新 stdio MCP 服务取消目标会话的俄文 FeatureWorks 提示，原静默打开调用恢复。第二个 SolidWorks 实例未被操作。单元测试覆盖 PID 隔离、未知对话框/按钮/提示拒绝；其他 SOLIDWORKS 版本和语言尚未实测。
`solidworks_translate_faces`: bounds_mm、translation_mm、expected_face_count、feature_name；先 dry_run，详见 [原生面平移](../references/face-translation.md)。
`solidworks_resize_sketch_circles`: sketch_name、centers_mm、expected_radius_mm、radius_mm，默认 dry_run；[使用说明](../references/sketch-circle-radius.md)。

## 原生工程图布局

`solidworks_create_drawing_layout`、只读 `solidworks_inspect_drawing_sections` 和限定 PID 的 `solidworks_cancel_dimension_prompt`：见[输入规则、尺寸关联限制和实机验证](../references/native-drawing-layout.md)。


## 显式文件命名

`solidworks_pack_and_go_renamed`：受 PID/文档路径保护的原生文件集复制，规则及限制见[原生命名复制](../references/pack-and-go-renamed.md)。

## 运行目录和源代码一致性

生产配置可设置 `SOLIDWORKS_MCP_RUNTIME_ROOT` 为安装仓库的绝对路径。`solidworks_runtime_status` 不访问 COM，返回实际服务路径、服务 PID、启动时及当前源摘要。客户端应先检查 `status=ready`、`runtime_protocol=1` 与期望路径，再发送 CAD 请求；缺少该工具的旧服务必须重新连接。

原生操作在加载 COM 前、等待锁后及取得桌面锁后校验运行身份。目录不符返回 `SW_RUNTIME_ROOT_MISMATCH`，启动后 `.py/.cs/.ps1` 或能力清单改变返回 `SW_RUNTIME_SOURCE_CHANGED`；都不执行该 CAD 操作。成功响应附带 `runtime_identity`。源摘要覆盖 `mcp-server`、`scripts`、`subskills` 下的执行源及 `capabilities.yaml`，不受 README、测试结果和模型文件变化影响。

开发工作树用于开发和独立验证；实际项目命令应使用同一个已安装根目录。不要为获得新工具而另启旧分支服务器。先合入安装副本、测试并重启 MCP，再核对运行身份。已有旧服务没有此保护，首次部署时仍必须重连；此检查不是操作系统安全边界，也不消除校验后并发编辑代码的竞态。安装更新应在无 CAD 操作时进行。多进程 CAD 继续使用不同目标 PID，但共享同一受控代码来源。

验证：Windows / Python 3.10，离线覆盖目录不符、增删改源文件、相对路径拒绝、文档变化不触发以及陈旧源在加载 COM 前阻断；SOLIDWORKS 版本能力不会因身份校验自动扩大。

### 任意平面盲切除

`solidworks_create_frame_cut` 读取严格 JSON 轮廓并创建原生基准面、草图与切除。见 [参数及审核边界](../references/native-frame-cut.md)。必须指定 `expected_document_path`。

## 原生圆截面路径工具

五个受保护的试验性工具支持原生扫描、STEP 导入、实体审查/排除和保持位置的组件替换。规格、限制和审查要求见 [工具说明](../docs/native-wire-tools.md)。

The pilot `solidworks_cam_inspect_mill_operation_levels` reads raw depth, level flags, origin and setup direction from one generated disposable MILL operation. Exact source/inventory guards and a new receipt are required; it performs no generation, edits, saves, exports or CL-record access. See [CAM reference](../references/solidworks-cam.md#bounded-mill-operation-levels-reader).

The offline-tested pilot solidworks_cam_inspect_mill_rough_boundary reads raw roughing boundary settings from one exact generated disposable MILL operation. It preserves source/inventory/event guards, writes a unique receipt and performs no CAD edits or generation. Native qualification and air-edge semantic mapping remain pending. See [CAM reference](../references/solidworks-cam.md#bounded-mill-rough-boundary-reader).

The pilot solidworks_cam_export_mill_generic_cl prepares and exports one bounded generated MILL machine to a new generic CL file. Exact process/source/inventory/controller guards apply. No GTP, simulation, model save or controller assignment is performed. See [CAM reference](../references/solidworks-cam.md#bounded-mill-generic-cl-export).

The pilot solidworks_cam_configure_mill_rough_boundary changes only one explicitly prepared raw tool-diameter percentage on a disposable rough operation. Exact prepared state and receipt credentials are required for apply. It never generates or saves; retained old toolpath records are not proof of a current path. See [CAM reference](../references/solidworks-cam.md#bounded-mill-rough-boundary-percentage-setting).
