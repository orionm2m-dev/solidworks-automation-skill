# SOLIDWORKS CAM native integration

The native CAM tools use the existing PID-bound SOLIDWORKS session and its operation
mutex. They do not automate windows, start another CAD process, activate a
license, or silently save a model. A saved document path (or exact unsaved
title where applicable) is mandatory for live access.
Native CAM tools never select a process themselves. The session must already have a
pinned PID; use `solidworks_connect(process_id=...)` to choose it explicitly.
The separate `solidworks_cam_save_prompt` Windows UI helper is described below;
it is not a native CAM API.

## Discovery and connection

- `solidworks_cam_installation` reads allowlisted uninstall, Addins and CLSID
  registry metadata and installed help/API file locations. Multiple versions
  remain separate candidates. Installation is not a license check.
- `solidworks_cam_status` reads an already loaded add-in and the CAM version,
  service pack, build date and demo flag. It does not auto-load CAM.
- `solidworks_cam_load_addin` explicitly loads the registry-verified DLL with
  `ISldWorks.LoadAddIn(full_path)`, then verifies the API object and document
  state. A load return code alone is not success evidence.

The verified bridge is `ISldWorks.GetAddInObject(registered_clsid)` followed by
`IMWAddin.GetCWApp()`. The latter is documented in the installed add-in's
embedded type library. Do not instantiate a guessed CWApp ProgID or register
an unregistered class to make it work.

## Turning qualification

`solidworks_cam_inspect_turning` inspects a saved part's machine type and the
turning machine catalogue. `solidworks_cam_set_turn_machine` selects an actual
catalogue object with explicit index, expected catalogue count and expected
current machine type. It refuses dirty documents or existing feature/operation
setups and verifies `MachType == 3` after assignment. It does not save the part,
generate operations or claim that a usable toolpath exists.

The CAM interface library reuses DISPIDs between interfaces (for example,
`ICWDoc3.GetDocType` and `ICWPartDoc.IGetMachine`). Do not let a generic dispatch
wrapper select an interface by the object's default type information.
`sw_cam_comtypes.query_cam_interface` transfers the existing PID-bound object
through standard in-memory COM marshaling and queries the generated native
dual interface. It accepts both pywin32 wrappers and native comtypes pointers;
it does not query the ROT, activate a server or extract raw object addresses.
The declarations come from the verified registered installation's
`camworks.tlb` (2026, type-library version 25.0).

`GetLicenseEnabled(BSTR)` requires a module token. The inspected vendor help
does not define those tokens. Do not guess them. `demo_mode=false`, a catalogue
entry, successful machine assignment and the presence of a turning DLL are
separate observations; none is a complete entitlement or simulation test.
`Module(...)` changes activation and is intentionally not exposed.

`solidworks_cam_inspect_machining` reads feature setups, operation setups,
turning operation types, generated-path flags and existing stock type.
`solidworks_cam_inspect_turn_stock` separately reads raw bar-stock and minimum
bounding-cylinder parameters, FCS name and raw SOLIDWORKS document units before
feature recognition. It needs no selected operation or generated toolpath.
Readback does not establish CAM parameter units, the radius/diameter meaning of
OD offset, or a valid machining coordinate frame. It performs no stock setter.
The unqualified turning `GetFCS` getter is disabled after native server error
`0x80010105` in live inspection; `GetFCS1` is not tried as a fallback. The
historical failure remains evidence. A null coordinate-system name is reported
as unset, never as an identity transform. The inspector keeps frame verification
false; separate target-in-FCS geometry checks must establish any part-specific
coordinate mapping.

`solidworks_cam_define_turn_stock` is a separate explicit pre-recognition step.
It requires a clean saved qualification part, current bar-stock type, zero
feature/operation/setup counts, exact `expected_bar_parameters_native`, new
`bar_parameters_native`, `qualification_only=true`, vendor-default messages and
a new exclusive JSON receipt. Both parameter objects have exactly `startZ`,
`length`, `odOff`, `idOff`, `attribute`; numeric values are finite raw CAM numbers
without unit conversion. Expected attribute may be 0/1/2; the new attribute must
be SOLID=1 or CORED=2. `DefineTurnWorkpieceAsBarStock2` returns an integer
`CWErrorCodes_e`: success is 0, not Boolean true. The core records intent/result
and reads back parameters only after that success code. Final verification
rechecks the document, empty CAM plan and raw bar values after clean event
unsubscription; a cleanup change invalidates the final verified flag. It never auto-saves,
recognizes features, generates operations/toolpaths or assigns a coordinate
system. Receipt and readback do not prove units, stock allowance or machining
frame correctness; those need separate qualification. On two separate saved
product-derived copies, explicit bar definitions returned integer zero with
exact requested raw-parameter readback. Independent stock export and analytic
BRep containment subsequently verified the intended nominal cylinders and
placement for those cases. Stock STL with an empty reference-system argument
was in model/world coordinates there, while the bar start position was in CAM
FCS; independently checked target-in-FCS geometry linked the two. This does
not define a universal offset conversion or qualify chucking, saw allowance,
material tolerances or production cutting conditions.

`solidworks_cam_run_qualification_step` supports one of `subscribe`,
`extract_features` or `generate_operations` on a separately saved calibration
part. A strict JSON `qualification_only=true` and the explicit
`message_policy="vendor_default"` are required. It never saves or posts NC.

Native `_IDialogEvents` subscription is held for the whole step. Vendor help
documents that clients may omit `SetResponse`, in which case CAM continues
with its defaults. The calibration policy records that as `default_unknown`;
it is not cancellation or rollback. No numeric response codes are guessed.
Any message, callback error or disconnect failure blocks downstream steps.
A message during a native call cannot undo that call. Client batch execution
stops when a tool reports `may_continue=false`.

Preconditions require a clean saved part and exact observed feature, operation
and operation-setup counts. Extraction requires an empty CAM plan. Operation
generation uses `CW_GOP_REGENERATE=2` only with recognized features and zero
existing operations. Empty operation setups created by native extraction are
allowed only when their count was explicitly observed. Each step creates a new
exclusive JSON receipt before native changes; an existing receipt cannot be
replayed after an uncertain timeout. Source and result inventories are recorded.

GTP and simulation are not exposed by this single-step qualification tool.
The inspected API provides `IsBackgroundProcessForGTPOver` but no verified
setter disabling background GTP.

## Persistent single-operation GTP

`solidworks_cam_prepare_toolpath_job` validates a clean separate saved part,
the selected PID and creation time, registered add-in, observed feature/setup/
operation counts and the selected turning operation type. It returns a config;
it does not start generation. Save the returned config as JSON in the project.

The permanent native module consumes that config:

```text
python -m scripts.sw_cam_jobs --start-config ABS_CONFIG_JSON --job-directory NEW_ABS_DIRECTORY --foreground
```

Its worker owns the PID operation mutex, COM apartment and native event
subscription for the complete calculation. It calls only the selected
`ICWTurnOperation.GenerateToolpath`, refuses existing generated paths, and
waits for the same operation's `GetIsToolpathGenerated` transition from false
to true after the native call returns. The vendor describes this getter as
successful operation generation. The global `IsBackgroundProcessForGTPOver`
flag is diagnostic only: the vendor Process Manager help describes 3-axis and
4/5-axis simultaneous milling, and the global flag was false on an untouched
idle turning calibration. Neither false=running nor true=completion of the
selected turning operation is established. `attention_seconds` marks a long
wait; it is not a cancellation deadline. Receipt, process-query and message-
pump errors do not release the subscription while completion remains unknown.
The worker leaves that wait on verified generation, confirmed target-process
death/reuse, or an explicitly requested observer cleanup as described below.
Observer cleanup and killing the calling session are not native cancellation.

Foreground execution is the verified transport design for short-lived MCP
stdio clients: the Windows MCP SDK puts the server in a kill-on-close Job
Object. A child cannot silently detach from that ownership. The optional
background launcher requests explicit breakaway and refuses if unavailable;
it never retries without breakaway. No window automation, shell command,
arbitrary code payload, license activation or automatic model save is used.

`solidworks_cam_job_status` reads the durable state and worker PID/creation
time without acquiring the CAD lock. Source fingerprints, process identity,
registration and document target are checked again in the worker. New job
directories and exclusive claim files prevent replay. A disappeared worker
without a terminal receipt is uncertain, never a successful calculation.

Success needs the selected generated flag, nonzero path records and finite
positive feed length, plus unchanged other operations and clean message
handling. Native length units are reported as unverified rather than assumed.
Save and reopen the intended calibration separately to check persistence.
This is not proof of production machining, tool clearance or license scope.
In particular, a false generated flag is a success predicate returning false,
not a documented running state. The turning API does not provide a verified
terminal-failure or cancellation channel. Unknown results must not be retried.

`solidworks_cam_stop_observation` requires the strict boolean
`acknowledge_native_not_cancelled=true`. It writes a job-bound request, which
the worker can service only after the current COM call returns. The worker
unsubscribes normally and returns `uncertain`, `observation_stopped=true`,
`native_cancelled=false`, `may_continue=false`. This is observer cleanup,
not cancellation of CAM or proof of completion. `finished=true` in this case
means that the observer finished, not that machining completed.

`solidworks_cam_inspect_operation` reads the selected operation's generated
flag, raw GTP time string, optional object-scoped license getter and stock
parameters. It also reads suppression, linked-feature count, actual tool presence,
raw tool-type values and a bounded tool description. Unknown enum values remain
unresolved; these getters do not qualify machining. Missing interface/getter
support remains explicitly unavailable.
The diagnostic read itself does not establish a terminal CAM execution state.

Live qualification of the direct rough-face call on the simple cylinder
returned without a generated path, timing string or CAM message. A prior
worker incorrectly treated the false success flag as pending indefinitely;
its observer was stopped with the native outcome and Unadvise unconfirmed.
The cooperative stop channel was added afterwards and is unit-tested only.
The raw stock dimensions match that calibration's envelope; absent cutting
allowance is a hypothesis, not a proven cause or a license finding. That attempt
produced no simulation evidence or manufacturing release.

Closing that calibration with ordinary `needs_save=false` nevertheless raised
a CAM save prompt. CAM persistence must be handled explicitly even after a
failed generation attempt. The read-only recovery report now includes modal
text and returns blocked even if COM getters still respond.
Simulation remains a separate stage requiring valid stock and tool/holder data.

`solidworks_cam_save_prompt` is a separate, explicitly authorized Windows UI
helper, not native CAM automation. It requires an already bound matching PID,
an exact SLDPRT basename, and the unique known Russian dialog titled
`Предупреждение SOLIDWORKS CAM` with text `Сохранить изменения в <basename> ?`.
Its default `action="inspect"` is read-only. `action="discard"` additionally
requires strict `acknowledge_discard=true`; it rechecks the dialog and sends
one notification to its identified No button. It does not use COM, acquire the
possibly blocked CAM mutex, activate a window or retry a click. Dismissal and
document save state are reported separately; availability of this helper is
not evidence that a particular prompt was successfully dismissed.


## Document-wide qualification simulation

`solidworks_cam_run_simulation` invokes the native simulation for the entire
active saved calibration part, not an individual selected operation. It
requires `qualification_only=true`, the strict boolean
`acknowledge_document_wide_simulation=true`, `message_policy="vendor_default"`,
the exact saved `expected_document_path`, and observed `expected_feature_count`,
`expected_operation_count`, `expected_operation_setup_count` and
`expected_generated_operation_count`. Counts must be positive bounded integers.
A new absolute `output_dir` with an existing parent holds the exclusive receipt
and exported evidence. An existing output directory is refused; do not replay
an uncertain or timed-out request with a new directory.

The registered add-in and its `camworks.tlb` are verified through the existing
PID/document guard. The whole call uses the shared operation mutex and records
before/after document and CAM inventories. The core refuses an initially dirty
or mismatched document. Document-wide acknowledgement allows inventory changes
on the same part to be recorded while exporting evidence; it is not approval
of those changes. Native messages, callback errors or cleanup failures block
further steps under the vendor-default message policy.

The native sequence is `RunSimulationSilent(True, False, False)`, followed by
JPG and STL evidence export when its guards allow. Gouge and undercut counts
are raw vendor outputs. The typed STL result order is `(error_code, saved_bool)`;
the image exporter returns a save boolean. This tool does not launch CAD,
explicitly generate toolpaths, post NC or save the SOLIDWORKS model.

Verified exports return `status="review_required"`,
`reason="SIMULATION_OUTPUTS_REQUIRE_REVIEW"`, `export_files_verified=true` and
`may_continue=false`. `native_call_returned=true` is separate from
`native_completion_verified=false`. A returned call or exported files do not
establish completion quality, tool clearance, license scope or full DFM.
Review the image and mesh separately before any further manufacturing decision.
The MCP contract is covered by isolated mocks; implementation and passing tests
alone do not establish live native simulation qualification.


`solidworks_cam_preview_simulation` uses the same explicit saved-part,
qualification, document-wide, count and message-policy guards, plus a required
`action`. Each action needs its own new absolute output directory and exclusive
receipt. `launch_play` calls only native `ActiveDocLaunchSimulation()` and
`ActiveDocPlaySimulation()`; their return does not verify playback completion.
`export_state` separately exports the current simulation image and STL. An
image-export failure does not prevent the STL attempt while document identity
and message guards remain valid; each export retains its own result.

Only explicit `action="close"` calls native `ActiveDocCloseSimulation()`
(DISPID 43). Its return does not prove that preview closed; no completion getter
is assumed. Other actions do not close simulation automatically. The preview
tool never calls `RunSimulationSilent`, generates toolpaths, saves the model or
posts NC. Results remain `review_required` with
`may_continue=false`; completion is unverified. Image and mesh evidence require
separate review. Mock coverage is not evidence of live playback qualification.


## Document-wide CAM geometry export

`solidworks_cam_export_geometry` requires the same saved-part, exact observed
counts, strict `qualification_only=true` and vendor-default message policy,
with a separate strict `acknowledge_document_wide_export=true`. Its output
directory must be new, absolute and local after canonical path resolution;
UNC paths, including mapped drives resolving to UNC, are refused.
`export_kinds` is an ordered, unique JSON list of one to three entries from
`"wip"`, `"stock"`, `"target"`; it defaults to `["wip"]`. Only explicitly
selected kinds are called, in the supplied order; there is no default batch
of all three exports.
Only the exact selection `["stock"]` or `["target"]` permits zero feature,
operation, setup and generated-operation counts before feature recognition.
WIP and every mixed selection require all counts to remain positive;
generated-operation count must never exceed operation count. This exception
adds no generation, stock mutation or coordinate-system change.
The target route uses `ICWMachine5.CreateSTLOfTargetInFCSSpace(file, 0)`
(DISPID 34), returns a single Boolean and reports `target_part_in_FCS`.
It takes no coordinate-system string. The inspected vendor declaration states
no feature-recognition prerequisite. This isolated pre-recognition export
returned true with nonempty files on two product-derived copies; document and
CAM inventories remained unchanged and no CAM events were reported. Independent
geometry readback checked each frame against the corresponding source model.
That result does not make the frame mapping universal or validate `GetFCS`.

The typed `ICWMachine5.CreateSTLOfWIPs2(folder, "wip.stl", "", 0, 0)` exports
WIPs across all setups, not the current simulation frame. The native folder
argument includes the trailing Windows separator: the observed implementation
concatenates folder and filename directly. An omitted separator previously
created a sibling file instead of a file inside the expected WIP subdirectory.
The receipt records the actual native folder and path; the tool uses a new,
empty WIP subdirectory and refuses collisions before invocation. WIP, stock and target
export methods return a Boolean only. The empty string and zero parameters
are qualification values; their use does not verify units or coordinate
interpretation. Any failed or invalid native export result, or missing/invalid
output, immediately stops the batch. No subsequent stock/target export or CAD
readback is permitted; only event-subscription cleanup is attempted. Verified
files and hashes require separate mesh review; they do not establish simulation
completion or full DFM, and `may_continue` remains false.

Each attempted-call marker is persisted before entering native code and means
intent, not proof of entry. The returned flag and strict Boolean result are
persisted immediately after return, before any further CAD readback. A receipt
write failure blocks continuation. Failed exports stop the batch; no retry or
alternate export kind is selected automatically.

On the saved stepped calibration in SOLIDWORKS/CAM 2026 SP4, the qualified
sequence is an explicit native preview `action="close"`, then a separate
geometry call with `export_kinds=["wip"]` and a new local output directory.
No save, toolpath regeneration, UI action or NC output is part of this sequence.
Closing preview was necessary for the observed successful sequence; the call's
return does not establish a general vendor prerequisite or a closed-state getter.
The corrected WIP export returned true and wrote the expected 50,384-byte STL.
Independent mesh readback found 1,006 triangles, a watertight mesh and volume
about 6,133.567 mm3, versus about 6,275.214 mm3 for stock: roughly 141.65 mm3
removed by the one generated rough-turn operation. This is partial machining,
not the final target shape or qualification of the four remaining operations.
The corrected file and the earlier misplaced successful WIP had identical
SHA-256 `633fe162f68a54ddcc0bce35bbd67a71d859643f2d1ebcff9a6d22f6436cb248`.

An earlier WIP attempt while preview was open returned false, and SOLIDWORKS
later exited during the old multi-export sequence. A stock file proves that
stock export was entered despite the old receipt's false attempted flag; the
native return and failure origin are unknown. That failed sequence is not
qualified and is not replayed automatically. The single WIP result above does
not establish safe export from an open simulation or make simulation-frame STL
export supported.

## Evidence and tests

Application-level connection and native loading were verified with SOLIDWORKS
2026 Revision 34.4.1, CAM 2026 SP4 build 2026/0619 and Python 3.10.11. The active
document identity and dirty flag were unchanged. On a separate saved calibration
part, native reading found one turning machine. Assignment changed the machine
type from 1 (mill) to 3 (turn), confirmed by immediate readback and again after
explicit save, close and reopen. Only the calibration part was saved; the
original assembly was restored without saving it.

The CAM assignment did not set the SOLIDWORKS dirty flag in that live test.
Do not use `needs_save=false` as proof that CAM data was persisted; callers must
explicitly save an intended CAM change and verify it after reopening.
Machine selection and persistence are verified. In a subsequent calibration,
event subscription/unsubscription succeeded, native extraction produced three
features, and native operation-plan generation produced five operations
supporting `ICWTurnOperation`. All five survived save, close and reopen.
No CAM messages occurred in those live stages; actual delivery of a vendor
message remains unobserved. Callback ABI was separately tested with real
in-memory `IDispatch.Invoke`, both null and non-null result pointers.
On a separate stepped calibration in SOLIDWORKS/CAM 2026 SP4, one selected
rough-turn operation generated 36 toolpath records. Explicit save, close and
reopen confirmed the same 36 records. This verifies generation and persistence
for that selected operation, not all turning operation types.

`RunSimulationSilent` returned raw counters `(0, 0)`, but image export returned
false and produced no evidence files. Native preview launch and play then
returned with unchanged CAM inventory. A separate `export_state` produced a
real 400 x 300 JPG of 10,816 bytes, which was visually reviewed. STL export
returned false with error 7 (`CW_EC_UNKNOWN_ERROR`). Repeating only export to
a shorter project output path produced the same image hash and the same STL
error; simulation was not rerun. Preserving the requested drive-letter form
and exporting to an actual local directory also retained error 7. The path fix
is useful but did not resolve simulation-frame STL export. The supported WIP
workflow above is a different native geometry source, not a silent replacement
claim for the failed simulation exporter.

Native exports preserve the caller's explicit absolute path for native API
arguments. Canonical paths are recorded separately and used to check directory
identity and output boundaries. File existence, nonzero size and SHA-256 are
checked independently of a native success Boolean; mesh content still requires
separate review.

The same permanent workflow was then exercised on two separately saved
product-derived CAM copies, using explicit stock definition and independent
nominal stock containment/frame checks before feature recognition:

| Qualification case | Recognized features | Operation setups | Planned operations | One selected rough operation: persisted records |
|---|---:|---:|---:|---:|
| A | 8 | 2 | 15 | 147 |
| B | 5 | 1 | 9 | 95 |

Each selected operation was generated by the foreground worker, then explicitly
saved, closed and reopened with the same records confirmed. Only one rough-turn
operation per case was generated. Native preview followed by explicit native
close and a separate WIP export returned true for both; the actual WIP files
were independently read and were watertight. This verifies the selected
operation, persistence and WIP-output workflow for those copies. The remaining
operations, final shape, tool/holder clearance, feeds/speeds and production
process were not qualified; no NC was produced. Private source geometry,
paths and complete receipts remain with the project evidence, not this module.

Image export is pilot-verified. Playback completion and the underlying
simulation completion state remain unverified; simulation-frame STL export
still returns error 7 in the tested route and is unsupported. Reviewed native
WIP geometry is a separate evidence source. Raw zero counters, an image or one
rough-operation WIP do not establish complete material removal, general turning
entitlement or full DFM. These results do not qualify a production machining
process.

Protocol validation checks registered tools without calling CAD. Regression
tests use mocks and in-memory COM separately from the live observations above.

The reusable `scripts/mcp_request.py` client executes JSON requests through the
standard MCP protocol against a fresh server and saves a result after each
call. It never imports server functions to perform CAD operations. Existing
output files are not overwritten; a failed call stops dependent requests.
After source changes, reconnect persistent MCP clients. Old servers reject
native operations when their source fingerprint is stale.

Primary references: installed `swcamapihelp.chm`, `camworks.tlb` and the embedded
type library in `cwaddinu.dll` supplied with SOLIDWORKS CAM 2026. Public bridge
documentation: [GetAddInObject](https://help.solidworks.com/2024/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.ISldWorks~GetAddinObject.html),
[LoadAddIn](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~LoadAddIn.html).

Vendor help and extracted type libraries are not redistributed in this repository.

## 只读关联轮廓与刀具尺寸

`solidworks_cam_inspect_operation_profile` 使用既有 PID 绑定和精确文档门禁。
参数为 `addin_clsid`、`expected_document_path`、零基 `setup_index` /
`operation_index` 及必填的 `expected_operation_type`（严格整数 1–16）。
它不生成刀路、不创建或编辑操作、不保存，也不读取已知不支持的对象授权 getter。

原生读取链为 `ICWOperation.IGetAllFeatures` → `ICWFeature` /
`ICWTurnFeature`。它返回名称、原始类型和属性、最小/最大直径、起终点，
并通过 `IGetEnumTurnSegments` 读取至多 64 个关联特征、合计 512 个段。
`ICWTurnSegment.GetLineSegmentParam(feature)` 的 OUT 顺序为
起始直径、结束直径、轴向长度、真实长度、锥角、成功 BOOL；
`GetArcSegmentParam(feature)` 为起始直径、结束直径、轴向长度、半径、
中心位置对象、成功 BOOL。位置对象经 `ICWPosition.GetCoordinates` 返回三个数值。
这些声明来自 CAM 2026 类型库；仅 LINE=0、ARC=1 读取对应参数，
其他曲线类型保留端点，并明确没有专用参数。
GetAllowance 在一次原生资格读取中返回 false；厂商文档未定义此值的含义。
该可选 getter 不属于几何识别的必要输入，当前不调用，也不把缺失值当成零余量。

刀具由 `IGetTool` 取得。必须先区分通用 `ICWTool.ToolType`、
`ICWTurnTool.ToolType` 与 `InsertType`：它们不是同一个枚举。
仅 GROOVE=2 / THREAD=3 读取 Width 和 length；仅 GROOVE 读取两端圆角，
其他插片按类型库限定读取适用尺寸。通过 `IGetTurnToolHolder` 取得
`ICWTurnToolHolder`，DEFAULT=1 读取 ShankWidth，BORE_BAR=2 读取
BoringBarDiameter，同时报告适用的长度、偏置、角度和操作方向原始值。
不依赖工具目录中的显示名称推断几何或用途。

任一原生异常、无效 OUT 形状、非 BOOL 状态或非有限成功输出立即停止后续读取，
报告失败阶段并保留此前已经读取的特征、段、刀具和夹持器字段；没有重试或降级调用。
线/弧参数 getter 的 BOOL=false 单独标为 native_returned_false，不使用其未确认的 OUT
数值；已读端点继续保留。geometry_parameters_complete 表示支持的段参数是否齐全，
不证明几何或加工正确。正常返回时检查前后文档及 CAM 清单相同。
输出始终标记单位、坐标系、刀具适配及生产过程未验证，并设置
`may_continue=false`；读到 profile 或宽度不能直接授权后续 GTP。
已在文档外确定的坐标变换及实体几何应独立用于核对槽口位置、宽度和圆角。
在 SOLIDWORKS CAM 2026 SP4 上，修复后对两个独立产品派生 CAM 副本进行了七次
只读检查，包含粗车、精车及槽操作；每次活动文档与 CAM 清单前后均相同。
一个槽特征的五个原生段与独立实体审查中的槽口位置、直径和两端圆角对应，
同时成功读取了槽刀宽度、圆角、厚度及镗杆式夹持器尺寸。该特征的原始坐标
在这次对照中符合模型世界坐标和毫米数值，而非已单独确定的 FCS 轴向坐标；
这不是所有 CAM getter、零件或刀具的通用坐标/单位规则。完整私有几何及回执
保留在项目证据中。Mock/schema/OUT 检查与这些实际 CAD 观察分开记录。

类型库确认方向枚举 4 为 CW_TURN_TOOL_ORIENT_DOWN_LEFT，5 为
CW_TURN_TOOL_ORIENT_LEFT_UP。枚举名称本身不证明刀具坐标相对模型或 FCS 的
完整变换；Width、Radius1/Radius2 的 getter 声明未给出可用于该证明的轴向映射
或单位。当前没有确认可用 allowance、刀具/夹持器间隙或刀刃与槽底的适配。
不能仅按宽度减去两个圆角计算的名义平直段，宣称该刀具能或不能完成槽底；
须先验证实际刀具方向及几何。以上七次成功只验证读取路径和该案例的轮廓对应，
不验证后续 GTP、螺纹或完整加工过程。

类型库中的车削螺纹操作枚举为 `CW_TURN_OP_THREAD=12`。
没有这种操作时，不得把粗车或切槽结果称为已加工螺纹。
本阶段没有新增螺纹操作 writer。

## 单字段车削刀片定义（资格验证）

`solidworks_cam_configure_turn_tool` 只操作已绑定 PID 中明确指定、已保存且干净的
SLDPRT 工作副本。它具有两个动作：`prepare` 只读；`apply` 只执行一次
`ICWTurnTool` property put，不生成刀路、不保存、不创建工具、不写 TechDB。

共同输入为 `addin_clsid`、精确 `expected_document_path`、
`setup_index`、`operation_index`、`expected_operation_type`、`field`、
`qualification_only=true`、`message_policy="vendor_default"`。
限定字段为 NoseRadius、Width、Radius1、Radius2、Thickness、InscribedCircle。
类型库声明 NoseRadius 不适用于 GROOVE/CIRCULAR/USER_DEFINED；Width 仅用于
GROOVE/THREAD；Radius1/Radius2 仅用于 GROOVE；Thickness 用于已知插片类型。
本工具将 InscribedCircle 写入进一步限定为 DIAMOND。宽度、厚度及内切圆须
为正数，半径允许非负有限 JSON 数值；不自行推断单位或修改 InsertType/holder。

准备结果包含 document（含 needs_save）、完整操作清单、关联旧 profile、旧
tool/holder、station ID、全部受影响操作及 `state_sha256`。单独的
`profile_sha256` 与 `tool_sha256` 用于审查，完整 state 摘要涵盖这些原始数据。
共享关系由 `ICWTool.GetToolStation` →
`ICWToolStation.OperationsUsingThisTool` 和遍历所有操作的原生 CAM document
object ID 交叉核对。`ICWDoc3.GetCWObjectID(object)`（DISPID 33）返回
(ULONG objectID, BOOL status)，每个值必须满足严格 status=true 且 ID>0。
类型库明确合法 ID 大于零。选定工具经站点 GetTool 再取 ID，必须一致；
额外诊断 `GetCWObjectFromID(5, id)`（DISPID 34，CW_OBJ_TOOL=5）使用
已核对的 enum、ULONG 参数顺序。在一次 prepare 中，正向 tool ID 与站点 ID 相同，
该逆向查询仍返回 false；此值明确标为 native_returned_false，不使用其 OUT 对象，
不把逆向查询称为成功。逆向查询不是修改现有操作所持工具的必要接口；若返回
true，则其对象、ID 及 ToolType 仍须有效且一致。OperationsUsingThisTool 的 TLB invocation kind 是 propget；
必须直接读取属性，不能因返回的 COM 集合可调用而再次执行其默认 Item。
usage 中的操作 ID 必须与完整文档
遍历得到的受影响引用相同，不得缺失、重复或出现未知操作。对每个同 ID 工具
wrapper 均独立读取适用尺寸与类型，不一致即阻止修改或判定回读失败。
不同 wrapper 的 IUnknown 身份已在实际 prepare 中观察到不相等，因此该比较
只保留作诊断，不再误认为内部 CAM tool identity。可变名称、TechDBID 或仅
station ID 也不作为对象身份，不用 vendor 内部指针。
GetStationId 的声明只要求 BSTR；一次原生 prepare 返回空字符串，文档没有非空保证。
空字符串保留为实际值，不削弱原生 CAM ID 和完整 usage 交叉检查；非字符串会报
CAM_TOOL_STATION_ID_TYPE_INVALID。失败报告保留读取阶段、原始 station ID 和此前的
文档、清单、分组及 profile/tool 字段，而非丢弃未完成的快照。
先读取通用 ICWTool.ToolType，只有类型 15 才查询 ICWTurnTool；选定工具必须是
此类型。钻头等其他工具只保留身份、类型及分组，不读取其专用尺寸，明确标为
non_turn_dimensions_not_read；不把车床操作清单误认为全是车削刀片。
这些 station/usage/object-ID getter 由 CAM 2026 TLB 声明，其本机返回形状和
跨 wrapper 一致性已在下述两个独立工作副本中确认。ID 仅用于当前 CAM document 快照；
文档未保证保存/重开后的持久性，每次重开必须重新 prepare。失败时保留每次
object-ID 读取的 BOOL/ID、阶段和 round-trip 证据，未知值绝不转成写入授权。

apply 还必须提供准备结果的 `expected_state_sha256`、新的 `value_native`、
完整且唯一的 `allowed_affected_operations`（每项含上述三个操作索引/类型字段），
以及新的绝对 JSON `receipt_path`。所有且仅有共享该工具的操作必须明确允许；
任一受影响操作已有生成刀路则阻止修改。prepare 不接受这些 mutation 输入或回执。
无变化请求、旧状态不匹配、不适用字段、脏文档或已有回执均在写入前被拒绝。

类型库的 setter 是 HRESULT-only propput DOUBLE，没有独立成功 BOOL。
调用前写入 durable intent，正常返回后先落盘返回事实，再读取结果。没有发现
这些接口必须使用 Modified/Update/Commit 的文档依据，因此不猜测调用。
订阅 CAM 消息期间执行一处属性赋值，随后及 Unadvise 后独立重读全部操作引用、
profile、tool/holder 和可写尺寸，要求只有指定字段及派生显示文本/dirty 状态变化。
任何消息、异常或超出范围的变化都会阻止后续处理；不自动重试或回滚。
成功仅返回 CAM 定义已回读，`may_continue=false`、`physical_tool_qualified=false`；
真实刀具、刀柄适配、方向、余量及保存后持久化必须另外审查。每次后续修改前
须由调用方明确保存工作副本并重新 prepare。

SOLIDWORKS CAM 2026 SP4 的两份独立工作副本已完成五次单字段原生修改：
一个 DIAMOND 刀片的 NoseRadius、InscribedCircle、Thickness，以及一个 GROOVE
刀片的 Radius1、Radius2。每次均确认共享操作引用和完整回读，显式保存/关闭/
重开后参数仍相同。调用方另行对每份副本的一项选定精加工操作生成刀路，
分别取得 79 和 29 条记录；这不是本 setter 自动执行的步骤。该 live 资格仅覆盖
上述 CAM 定义、持久化与选定刀路，不证明真实采购刀具、刀柄形状/装夹适配、
完整切削包络、全部加工结果或生产工艺。Mock/schema 与实际 CAD 观察分开记录。

## 只读加工资格上下文

`solidworks_cam_inspect_qualification_context` 读取明确选定操作的关联特征、
THREAD 默认目录和原生夹持器轮廓。必需参数为精确 saved-part path / add-in、
setup_index、operation_index、expected_operation_type、明确的零基
`linked_feature_indices`，以及 `holder_profile`：
`operation` 调用 GetHolderProfile(operation)，`down_left` 调用
GetHolderProfileInDownLeftOrientation(operation)，`none` 跳过夹持器，
只读所选特征和目录。目录和 profile 先读取，因此后续夹持器读取失败时已有证据保留。

目录固定调用 ICWTurnFeature.IGetAllDefaultOperations(12)；12 是 THREAD 枚举。
返回的 `converted_result_shape` 保存 comtypes 已转换后的 Python 类型、结构和
原始字符串，不伪称保留 VARIANT vartype、SAFEARRAY bounds 或 rank。仅对实际
返回的标量 BSTR 或一维纯 BSTR list/tuple 调用
GetTdbIdForDefaultOperation(12, exact_name)，不拆分/修剪字符串，不猜测名称。
最多累计 64 个名称，每个 1000 字符；其他形状或超限结果明确未解析，不调用
lookup。保留实际 LONG ID（包括零/负数），因为失败 sentinel 未被文档说明；
不把目录存在或返回某个 ID 当作 feature 可安全加工完整螺纹的证明。

夹持器路径使用 ICWSegChain、ICWCurve、ICWArc、ICWPosition 的真实数值。
GetCurveAtIndex 的入参是 INT*，必须传 c_int 指针；零基来自 vendor
“Features and Setups” sample。最多读取 32 条 chain、合计 512 条 curve。
直线保存起终点；圆弧保存起点、中点、终点、圆心、半径及未解释的 sense。
其他曲线保留原生端点并明确专用参数不完整，不将 spline/circle 伪装成直线。
实际方法均按 TLB 的 method invocation 调用，不能二次执行返回 COM 对象的默认成员。

输出是 native profile 原始三维数值，没有自动偏置、轴旋转、单位换算或实体挤出。
原生 operation/down_left 选择也不证明 world/FCS 变换；profile 不是已经验证的
完整夹持器实体或碰撞结论。公开 CreateSTL(path) 为另一项 HRESULT-only API，
本工具不在错误后自动尝试它，也不写任何导出文件。发生原生异常时立即停止，
保留已读数据和失败阶段，正常结束后检查文档及操作清单前后一致。
始终 may_continue=false，thread_process_qualified=false，holder_fit_verified=false。
不调用 GetCWObjectFromID、不创建 THREAD 操作、不写参数、不运行 GTP、不保存。
新增读取路径已在 SOLIDWORKS CAM 2026 SP4 的两份独立工作副本上确认：
operation 夹持器 profile 分别返回一条/两条 chain，两例均为七条 curve，
读取结束后文档与操作清单不变。THREAD 默认目录均实际返回 tuple 中的
单个 BSTR “Default”，相应 lookup 原始 ID 为 28；此值是观察结果，不是工具的
硬编码默认值。一个被读 feature 仅是槽口轮廓，另一个是包含多个直径的完整
外形；目录返回名称/ID 不证明这些 feature 本身就是正确的螺纹区段。
读取成功只证明原生曲线和目录路径可用，不证明夹持器实体、碰撞安全、
M60 区段、完整螺纹几何或生产工艺。Mock/schema/指针 ABI 与实际 CAD 观察分开记录。
