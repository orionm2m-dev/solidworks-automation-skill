# SolidWorks C# Add-in 宿主

## 定位

`dotnet/CadStudio.SolidWorks.AddinHost` 是面向长期事件回调和原生 UI 生命周期的
`net48/x64` 进程内宿主。它不替代 Python 的短生命周期建模脚本，也不冒充仅非托管
C++ 可用的 `I*` 指针接口；路由由 `capabilities.yaml::solidworks_addin_ui_events` 决定。

当前宿主包含：

- `ISwAddin.ConnectToSW/DisconnectFromSW` 与 `SetAddinCallbackInfo2`；
- `SldWorks` coclass 的活动文档、新建、打开和特殊关闭事件；
- 三命令 `CommandGroup`；
- WinForms `TaskPane`，使用 64 位窗口句柄；
- 完整实现 SW2026 `IPropertyManagerPage2Handler9` 的 37 个回调；
- `%LOCALAPPDATA%\CAD Studio\SolidWorksAddin\host-status.json` 诊断证据；
- 强名称程序集身份、CurrentUser COM 冒烟和 Machine 正式注册两条部署路径。

## 构建

本机 PIA 目录必须显式给出，避免误引用另一个 SolidWorks 主版本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sw_addin_host.ps1 `
  -Action Build `
  -SolidWorksApiDir 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist'
```

Build 生成并验证同目录的 x64 DLL 与 TLB；构建本身不执行注册：

```text
dotnet\CadStudio.SolidWorks.AddinHost\bin\Release\net48\CadStudio.SolidWorks.AddinHost.dll
dotnet\CadStudio.SolidWorks.AddinHost\bin\Release\net48\CadStudio.SolidWorks.AddinHost.tlb
```

## 注册与验证

CurrentUser 模式只验证 CLR/COM 激活，不会写入虚假的 SolidWorks Add-ins 发现项：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sw_addin_host.ps1 -Action Register -RegistrationScope CurrentUser -SolidWorksApiDir '<api\redist>'
powershell -ExecutionPolicy Bypass -File scripts\sw_addin_host.ps1 -Action ComSmoke -RegistrationScope CurrentUser
```

首次安装的 SolidWorks 发现项需要 Machine 注册；已经存在的发现项不需要每次更新重复创建。普通 PowerShell 会自动弹出一次 UAC，
提升后的子进程只执行固定 GUID 的构建/注册动作：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sw_addin_host.ps1 -Action Register -RegistrationScope Machine -SolidWorksApiDir '<api\redist>'
powershell -ExecutionPolicy Bypass -File scripts\sw_addin_host.ps1 -Action Probe -RegistrationScope Machine
```

Machine 模式使用 64 位 `.NET Framework RegAsm /codebase /tlb`，同时写入 COM 类、类型库、
`HKLM\SOFTWARE\SOLIDWORKS\Addins\{GUID}` 和当前用户启动项。卸载时使用同一程序集路径：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sw_addin_host.ps1 -Action Unregister -RegistrationScope Machine
```

## 验收门禁

`ISldWorks.LoadAddIn()` 返回 `swSuccess=0` 仍不单独算通过。真实 Probe 还必须读取诊断文件并同时满足：

1. `status == connected`；
2. `callbackRegistered == true`；
3. CommandGroup、TaskPane、PropertyManagerPage 三项均为 `true`；
4. 新建临时零件后 `file_new` 与活动文档事件计数增长，`CloseDoc` 后 `GetDocumentCount()==0`；
5. `errors` 为空。

可调用 `python scripts/sw_addin_host.py` 或 MCP `solidworks_addin_host_status` 查看程序集、TLB、注册层级、
诊断内容和精确阻塞码。当前用户 COM 注册不能替代上述 Machine 门禁。

## SW2026 真机证据

本机 SW2026 SP1.1（Revision `34.1.1`）已经通过完整回归：

- Add-in 由 `SLDWORKS.exe` 进程实例化，`LoadAddIn=0`；
- `SetAddinCallbackInfo2`、应用事件、三命令 CommandGroup、TaskPane、PropertyManagerPage 全部就绪；
- `IPropertyManagerPage2Handler9` 的 37 个回调由公开、COM 可见并提供 `AutoDispatch` 的处理器承载；
- 新建事件计数为 1，临时零件关闭后打开文档数为 0，诊断错误列表为空；
- 回归结果写入 `output/addin-host-real/addin_host_regression_result.json`。

该回归还验证了两个门禁：缺少 TLB 时，SW2026 可能装入 DLL 并返回 `LoadAddIn=0`，但不会实例化
`ISwAddin`；PMP Handler 只有 `IUnknown` 而不提供 `IDispatch` 时，`ICreatePropertyManagerPage`
会抛 `InvalidCastException`。

## 已知限制

- 当前仓库程序集做了强名称签名，用于稳定程序集身份；它不是可信发布者的 Authenticode
  代码签名。企业分发仍应由发布流水线签署 DLL/安装包。
- SolidWorks 会锁定已加载 DLL；重建前应先 `UnloadAddIn` 或正常退出 SolidWorks，不要强行覆盖。
- 应用级 `FileCloseNotify` 只在工程图 `CloseAndReopen` 后触发；普通零件/装配体关闭应检查文档数，或订阅对应文档事件。
- CommandManager 布局会进入用户配置。GUID、命令组 ID 和命令用户 ID 发布后应保持稳定。
- Add-in 适合 UI、事件和长期驻留回调；常规建模仍优先现有 Python Automation 封装。

## 官方依据

- [ISwAddin Members（SOLIDWORKS API Help 2026）](https://help.solidworks.com/2026/english/api/swpublishedapi/SolidWorks.Interop.swpublished~SolidWorks.Interop.swpublished.ISwAddin_members.html)
- [Using the C# Add-in Wizard（SOLIDWORKS API Help 2026）](https://help.solidworks.com/2026/English/api/sldworksapiprogguide/Overview/Using_SolidWorks_C__Add-In_Wizard_to_Create_C__Add-In.htm)
- [IPropertyManagerPage2Handler9 Members（SOLIDWORKS API Help 2026）](https://help.solidworks.com/2026/English/api/swpublishedapi/SolidWorks.Interop.swpublished~SolidWorks.Interop.swpublished.IPropertyManagerPage2Handler9_members.html)
- [LoadAddIn Method（SOLIDWORKS API Help 2026）](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~LoadAddIn.html)
- [FileCloseNotify Delegate（SOLIDWORKS API Help 2026）](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.DSldWorksEvents_FileCloseNotifyEventHandler.html)

## Updating an existing CAM host

`Build` produces a strong-named assembly and exports its corresponding x64 type library. Inspect both artifacts before `RegisterBuilt`; the latter requires their exact SHA-256 values and does not rebuild them. Set `-RequiredCamInterface` to each needed command interface, including the bore builder when applicable. A strong name is an assembly identity, not Authenticode publisher certification.

Use an unpackaged 64-bit PowerShell process for registration and its readback. The Microsoft Store distribution of Python can read and write a private registry view. A virtual environment based on that distribution retains its package identity. Its apparent registration success therefore does not establish that an ordinary SOLIDWORKS process can see the interface. Python may still inspect the actual DLL/TLB file metadata. Do not clear private package hives or weaken Windows security to resolve the difference.

The CurrentUser installer uses `Get-AddinCodeBase` to preserve the .NET Framework/RegAsm-compatible assembly location. It first uses `AssemblyName.GetAssemblyName(...).CodeBase`; when that metadata value is unavailable, it constructs an unescaped absolute file URI. Spaces remain literal, for example `file:///C:/Program Files/Host/host.dll`. The same value is written to the class and assembly-version `InprocServer32` entries. Do not substitute `[Uri].AbsoluteUri`, which escapes spaces, or apply blanket `%20` replacements that could change a literal filename. The offline formatter tests cover drive paths, UNC paths, spaces and literal `%20`/`#` characters.

A registered file existing on disk and a successful `LoadAddIn` return do not establish COM activation. For a bounded constructor check, `ComSmoke` accepts `-ComSmokeDiagnosticPath` with a fresh, fully qualified output file. It records a limited exception chain, including `FileName`, `FusionLog` and loader exceptions, and preserves a failed exit status. These properties may be empty; their absence does not locate the binding failure. This command activates the host once outside CAD and may update the host diagnostic file; it does not connect to SOLIDWORKS or change Fusion logging settings. The synthetic diagnostic test driver performs no real activation.

When the existing machine registration already names the canonical assembly path and identity, an update can reuse that path. Verify the existing registration instead of assuming a machine-wide rewrite is needed. Keep backups of replaced files and changed own registration values. An obsolete version is not an archive while it remains an active registration; any retirement must target an exact reviewed own leaf after a durable rollback record. Do not retire entries based on a different process's virtual registry view.

Before invoking a new command, confirm the actual loaded assembly path and MVID in the intended owned SOLIDWORKS process. A file hash, `LoadAddIn=0`, or a connected diagnostic file alone is insufficient. Reuse an existing clean saved checkpoint, close only the owned session, and do not repeat failed unload/reload attempts without changed evidence.

The host exposes `ReadTurnSnapshot` and a separate `QualifyCreateBoundTurnBore` command. See [the bounded bore qualification contract](cam-turn-bore-qualification.md). Software tests and metadata validation do not establish native execution, persistence, or machining suitability.

Public COM-visible classes and interfaces use explicit stable GUIDs. In particular, the callback class GUID is fixed independently of strong-name signing; its outgoing event interface remains the vendor's `_IDialogEvents` interface.

References: [Microsoft Store Python known issues](https://docs.python.org/3.10/using/windows.html#known-issues), [MSIX registry virtualization](https://learn.microsoft.com/en-us/windows/msix/desktop/flexible-virtualization).
