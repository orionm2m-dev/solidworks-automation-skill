# Plastics 空会话隔离

能力等级：`pilot`。软件回归与注册表读取已验证；真实 `UnloadAddIn` 的成功必须由每次原生回执证明。

## 工具

- `solidworks_plastics_installation(year)`：只读当前版本的系统加载项注册、有效 COM DLL/ProgID 和两个 DLL 的 SHA256；不启动 SOLIDWORKS，不访问加载项对象。
- `solidworks_unload_plastics_addin(action=prepare|apply, ...)`：只允许已连接的新 owned PID、精确创建时间及已验证的启动回执；所有可见与隐藏文档必须为空。

范围仅限注册为 `SOLIDWORKS Plastics` 的 CLSID `{B4D933F9-F4A9-4555-B4C7-8A06D0115CDC}`。卸载参数是已注册 `SimpoeWorks.dll` 的完整路径；同一安装中的 `SimpoeMV/SimpoeMoldWorks.DLL` 单独校验并观察。用户 COM 注册覆盖、文件变化、异路径的同名模块或无法完整读取的状态均拒绝执行。

## 流程与证据

1. 在已有原生启动工具生成的新进程回执中确认 `status=ok`、`phase=connected`、`new_process_verified=true`、PID 与创建时间；不要用历史进程号推断所有权。
2. 使用 installation 返回的完整路径与 SHA 调用 `prepare`，提供新的 JSON 回执路径。该阶段没有卸载操作。
3. 只有 `apply_eligible=true` 时才可提交 `apply`，携带原 prepare 文件及其 SHA，并使用另一新 JSON 回执路径。若两个目标模块本来就未映射，prepare 记录 `already_unmapped`，无需 apply。
4. apply 在原生调用前持久记录一次性标记和意图；同一个 PID 生命周期不能通过改回执文件名重试。唯一变更调用是 `ISldWorks.UnloadAddIn(完整 DLL 路径)`。
5. 原生返回值在后置检查前单独持久化。只有返回整数 `0`、两个目标 DLL 均不再映射、进程/空文档范围未变且 HKCU 启动项及注册信息未变时，才记录 `unloaded_verified=true`。`0` 但 DLL 仍映射属于 `uncertain`，不宣称隔离成功。

工具不调用 `GetAddInObject`、加载 DLL、关闭/保存文档、重启进程、改变许可证或修改自动加载注册表。用户启动项读取前后完整比较；变化时只报告，不自动恢复。OS 模块列表不能证明所有加载项内部回调状态，成功也不等同于后续导入、几何或制造验证。

## API 与验证

官方文档：[ISldWorks.UnloadAddIn](https://help.solidworks.com/2025/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~UnloadAddIn.html)。完整文件路径参数；整数 `0` 表示返回成功，`-1` 表示失败。

实现：`scripts/sw_plastics_session_isolation.py`。离线回归：`tests/test_plastics_session_isolation.py`，覆盖所有权、创建时间、隐藏文档、注册/DLL 漂移、同名异路径模块、一次性标记、返回值类型、回读失败和持久化顺序。测试中的 COM 对象为替身，不构成真机卸载验证。
## 启动超时后的独立延迟连接

若原始启动回执仅停在 `status=uncertain / phase=waiting_for_exact_pid_rot`，但已证明新 PID 的创建时间和可执行文件，可保留该回执不变，另外通过 exact-PID connect 与空文档 inventory 取得完整的两步结果。卸载工具的可选 `late_attach_receipt_path` 与 `late_attach_receipt_sha256` 必须成对提供，并绑定这份独立结果。

此路径严格校验两个工具的成功结果、固定 PID、无活动/隐藏文档及 `UserControl=true`。运行时仍重新校验原进程身份、空文档、UserControl 和两份证据哈希。其它启动失败阶段、被改写的原始回执或单独的旧 inventory 不被接受；不重新启动、不终止进程，也不将原始超时改写为启动成功。
