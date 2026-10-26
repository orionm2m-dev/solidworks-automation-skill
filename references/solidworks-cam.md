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

## THREAD 默认操作插入资格验证

`solidworks_cam_qualify_thread_operation` 用于新保存的独立 CAM 工作副本。
prepare 只读；apply 仅调用一次
`ICWTurnFeature.InsertOperation(12, observed_default_id, verified_after_operation)`。
返回是 IDispatch 操作对象，不是 BOOL。本工具没有螺纹参数 setter，不生成刀路，
不保存模型，不输出 NC，不调用 GetFCS/GetIsLicensed 或逆向对象查询。

共同参数为 exact saved-part path/add-in、setup_index、operation_index、
expected_operation_type（指插入位置之前的已有操作）、linked_feature_index、
qualification_only=true、message_policy=vendor_default。所选关联 feature 可以是完整
外形；这不意味着它已经是正确的 M60 螺纹区段。prepare 返回该 feature 原始
profile、正向 native ID、实际 THREAD 名称/ID 目录、完整操作清单及已保存文件 SHA-256。
每个已有操作的 ID、类型、关联 feature ID 和生成记录都纳入状态；当前 document ID
不能跨重开直接重用，必须重新 prepare。

apply 必须提供 prepare 的 expected_state_sha256、实际返回的 default_name、
expected_default_id，以及新绝对 JSON receipt_path。名称/ID 必须与该 feature
实际目录精确一致；不得写死 ID=28 或默认 ID=0。客户端资格范围只允许正 LONG ID，
这不是在声明厂商已定义零/负值为失败 sentinel。已有回执防止不确定请求重放。
调用前落盘 intent；返回事实先落盘，再检查恰好新增一个正 ID、类型12的操作，
位于指定已有操作之后，并只关联指定 feature。其他操作顺序、类型、关联特征、
生成标志/记录数、selected profile、stock/setup 清单和已保存文件哈希必须保持一致；
允许内存文档变脏，磁盘文件不能被工具隐式保存。

新操作及只读恢复目前仅调用 29 个声明成员中已实际确认的 16 个：12 个
DOUBLE 方法（pitch/actual pitch、每刀及最后一刀深度、起终长度、进入/退出量角）
与 4 个 LONG/enum 方法（GetNumFinalPassValue、GetNumStartThreadsValue、
GetLeadinTypeValue、GetLeadoutTypeValue）。GetMinZLimit 在一次独立副本的
实际插入后读取中返回 CAM SERVERFAULT 0x80010105；随后只读恢复在确认
同一正 ID、类型12、无刀路及 16 项标量后，GetMaxZTurnMethod 再返回该故障。
两次历史回执保留，不重放插入，也不逐个尝试剩余未知成员。
这两个实际失败项记为 observed_CAM_SERVERFAULT；其余 11 个未被实际验证的
声明项记为 untested_disabled_after_CAM_SERVERFAULT。全部 13 项均不调用，
不将未测试项说成已失败。参数完整性始终为 false；unavailable_getters /
metadata_limits 保留具体原因，不用零值代替未知值。
第二次恢复再次读完 16 个标量后，IGetTool 返回另一 HRESULT -2147220990。
这不证明工具不存在。恢复及新操作参数读取均去掉 IGetAllFeatures、关联 profile、
IGetTool 和刀具/夹持器整个后续分支，ancillary_metadata 明确未获资格且未读取。
不会以未知工具状态作为后续 getter 探测的理由。读回范围严格为原生 ID、类型、
无刀路标志与这 16 个标量；严格校验 BOOL、LONG、有限数值及 OUT 形状。
首次原生失败停止后续读取并保留部分结果。writer 原有插入前后操作/关联 ID
清单核对保留，但这不表示已读新 THREAD 的完整 profile 或刀具定义。

SOLIDWORKS CAM 2026 SP4 的一次独立副本试验确认 InsertOperation 返回了新
正 ID、类型12、未生成刀路的操作，恰好增加一个操作的核对通过；后续上述 getter
故障使整个写入路径仅获部分资格验证，不能重放插入。已读默认 pitch=0.4、
actual pitch=0 等原始值不是 M60 配置。没有自动保存、GTP 或 NC。

`solidworks_cam_inspect_thread_operation` 单独恢复已有操作的只读参数。
必需 exact saved-part path/add-in、setup_index、operation_index、
expected_operation_type=12、正 ULONG expected_thread_native_id；没有 prepare SHA、
插入目录或 mutation 参数。允许同一已保存路径当前存在未保存的修改，
先核对原生操作 ID、类型和无刀路标志，再读 16 个已确认的标量；不遍历
关联 profile、工具或夹持器，其余 13 个未获资格参数成员也不调用。结束时核对原生 ID、文档、操作清单及磁盘文件哈希均不变，
不插入、不保存、不生成；发生首次原生异常即停止并保留已读取数据。
成功仍返回 review_required、may_continue=false 与 parameter_metadata_complete=false。

这些工具不表示 M60 已配置。完整螺纹深度、大/小径、ISO牙型、旋向、公差、
正确螺纹区段、参数单位以及物理刀具/退出安全仍未验证。整段 OD profile 不能
因目录包含 THREAD 而直接用于计算螺纹。Mock/schema 与实际 CAD 观察分开记录。

最终的有界恢复已在同一 SOLIDWORKS CAM 2026 SP4 资格副本上实际通过：
精确正 ID / 类型12 / 未生成刀路一致，16 个标量读回成功，文档、操作清单和
已保存文件哈希均保持不变。返回 review_required 是元数据不完整的明确门禁，
不是 M60 已配置或物理工艺通过。随后调用方使用独立的常规保存工具保存检查点；
插入/读取工具本身仍不保存。后续关闭重开未恢复这项默认 THREAD（其余已验证
刀路仍存在），因此该写入路径未通过持久化验证，旧 native ID 已失效；原因未确定。
运行环境为 Windows / Python 3.10.11；116 个 core mock 测试和 108 个 MCP
schema/route 测试覆盖边界与禁用调用，协议列表确认 101 个工具可见。
这些测试数量与实际原生验证范围分开记录，不声明其他 SOLIDWORKS 版本已验证。


## 单条共线车削特征的受控资格试验

厂商 CAM_Help.chm 的 `thrd_drl_cutoff/thread_operation.htm` 要求一个 THREAD
feature 由一个或多个共线 segment 组成；不共线的完整外形不是有效 thread profile。
`thread_tab_machining_parameters_dialog_box.htm` 将 Start/End length 描述为
feature 范围的增量，不能把它们当作独立绝对 Z 边界。Thread depth 与每刀深度不同；
前者与 OD/ID feature 的 major/minor diameter 和 Thread Condition 有关。
之前一次完整外形上的默认 THREAD 插入虽有内存读回，常规保存返回成功后重开却
没有恢复该操作；原因未确定，旧 native ID 不能重用。不得重放该无效插入来试错。

`solidworks_cam_qualify_turn_feature` 的 prepare/apply 只验证一个独立直线 CAM
feature，不插入 THREAD、不设置 pitch/depth、不生成刀路。需要独立保存的干净
试件、精确文档/add-in、source operation/type/linked_feature_index/segment_index、
feature_setup_index、candidate_feature_type、显式 native_to_model_scale（到模型米）、
新的 ASCII sketch_name，以及 qualification_only=true、
acknowledge_unverified_type_mapping=true 和 message_policy=vendor_default。
候选类型必须等于源 feature 实际读到的原始类型，但这是显式待验证的映射假设，
不是声称 CreateTurnFeature 的 LONG 类型参数有已记录的枚举映射。
坐标比例只适用于调用方已有几何证据的 profile，不建立全局 CAM 单位约定。

prepare 只读源直线、全部有界 CAM profile、操作 ID/关联/已有刀路记录、实体
边界/质量属性、模型特征、保存文件哈希及实际参考平面。限定 profile 必须位于
模型 XZ 子午面；从 RefPlane.Transform 验证实际平面，不按 Top/Front 名称猜轴。
apply 绑定完整 prepare SHA 和新独占 JSON 回执；建立单一 2D sketch 时使用实际
ISketch.ModelToSketchTransform 和逆变换验证 model-space 端点。随后仅调用一次
`ICWTurnSetup.CreateTurnFeature(LONG candidate_type, BSTR exact_sketch_name)`，
返回 IDispatch，无 BOOL 成功返回值。要求恰好新增一个正 ID 的预期类型 feature、
一条共线 segment、相同原始端点/尺寸，旧 feature/profile、操作/刀路、实体和磁盘
文件保持不变。CAM 消息、失败或任何额外变化均停止；不自动删对象或重试。

inspect 使用同一组明确目标/源段参数，允许脏文档及已经存在的目标 sketch；
返回完整当前快照而不声明 prepare/apply_eligible，不接收 state SHA、receipt 或新 ID。
原生创建已返回但对象为空时，保留 native_result_present=false，只读完整后快照；
仅当恰好出现一个正 ID 且通过同一套完整几何/旧数据不变检查，才以 snapshot delta
恢复新特征身份并明确标记 null_result_recovered_by_exact_delta。零个或多个新增项、
消息及任何额外变化仍停止；不重放创建。中断后的独立 inspect 也不授权重放 apply。
快照 getter 间只查本地 CAM 消息，快照前后和每次写入前仍核对精确文档。
质量属性保留原始诊断，SHA 使用 12 位有效数字；只对对应质量项允许 1e-10 相对误差
（绝对容差为零）。文件、包围盒、profile、操作和刀路仍精确比较。

save_candidate 是另一次显式 action，必须提供创建后 state SHA、新独占 receipt
及 expected_new_feature_native_id。只调用 `ICWApp.SaveActiveDocument()`；HRESULT
正常返回与内存/文件读回分开报告，persistence_verified 始终 false，必须另行
关闭/重开验证。厂商 `common/saving_machining_data.htm` 要求 Save/Restore part
在保存和打开时启用；本工具不读取/修改未公开的选项、不把该选项猜作既往丢失原因，
也不把更新 CAM 树或 rebuild 猜作 commit。已有正常刀路能恢复不等于每种新对象都
已验证持久化。mock/ABI/协议通过不是生产或 M60 资格。

2026 SP4 已实测一个来自既有 OD profile 的单一直线：模型草图端点回读通过；
CreateTurnFeature 参数候选 1 返回空对象，但随后独立 inspect 确认恰好新增一个
原始类型 1 的单线 feature，完整增量检查通过。独立 CAM 保存后在新实例重新打开，
该 feature 及原有 15 operations、两条既有刀路（147/79 records）均恢复，文件哈希不变。
这只资格化该输入类型/直线几何案例和明确保存后的持久化，不建立通用输入枚举映射，
不配置 THREAD/M60、刀具、螺纹深度或制造公差。新版同调用 null-delta 恢复有离线回归；
活体证据来自分开的 create-null、inspect、save、reopen，不声称新版恢复分支已再运行。


## CAM 原生文档保存与关闭

`solidworks_cam_export_mill_feature_geometry` is an explicit single-feature MILL
qualification branch, preserving the existing TURN exporter. One request exports
one target, original-stock or WIP kind through the existing `ICWMachine5` methods.
The scope remains the entire machine/all setups; it is not a selected-operation
or current simulation-frame export. Exact PID, clean saved source SHA, feature ID,
ordered operation/generated IDs and actual record counts are captured under one
active event session; export must leave this state unchanged. The export interface
is queried in prepare. A new local native output directory, one-use receipt and
single dispatch prevent automatic replay. No GTP, GOP, AFR, simulation, tool/stock
editing or model save is included; cleanup uses only SOLIDWORKS/file checks.
Native BOOL true plus bounded nonempty STL bytes/hash qualify file output only.
Mesh validity, units/frame, initial stock occupancy and actual removed geometry
must be independently established before interpreting pocket depth. Roughing-only
WIP may include remaining allowance. Prior TURN WIP success does not qualify MILL
WIP availability without simulation; failed/unchanged output has no automatic
preview or generation fallback. Native MILL export remains a pilot.

`solidworks_cam_qualify_mill_operation_toolpath` is a separate selected-operation
MILL qualification pilot. It binds the exact PID, saved source SHA, selected
OPEN_POCKET feature ID, operation native ID/type and complete captured state.
Inspect first reports the assigned generic `ICWTool` native ID, `IsMillTool`,
`ToolType`, `CutDiameter` and `Protrusion`; dimensions remain raw, with units,
holder geometry and manufacturing suitability unqualified. No subtype-specific
insert dimensions are read. Prepare/apply requires a clean saved document and
selected generated=false with no calculated records. One typed
`ICWMillOperation.GenerateToolpath()` is permitted. The installed HRESULT/no-OUT
binding was independently checked through a local in-memory COM object (int0),
not native CAM execution. Native return alone is not completion: readback must
observe selected generated=true and positive actual record counts, with the
other operation rows, selected definition/tool, feature/configuration and saved
file unchanged. All CAM reads are event-subscribed. Durable capture phases and
pending-dispatch intent survive an interrupted client; unknown/partial output
never permits automatic GTP replay, cancellation claims, save or fallback.
This does not qualify the motion geometry, depth, units, stock/material/tool
process or persistence. Generic tool reading and selected MILL GTP remain
native pilots until their separate receipts are obtained.

`solidworks_cam_qualify_mill_feature_operation_plan` is a separate disposable MILL
pilot for one exact unsuppressed OPEN_POCKET (volume type 6). Inspect/prepare/apply
bind the saved file SHA, PID, feature ID and full captured state. One
`ICWFeature.GenerateOpPlan(1)` may add 1–32 operations, each linked only to that
feature; every operation ID/type/suppression flag, generated flag and bounded
actual toolpath record counts are read back. No GTP, AFR, stock/tool edits or save
is included. The HRESULT/no-OUT binding was independently checked with the exact
installed interface and a local in-memory COM object (strict integer S_OK=0).
Native MILL GOP, operation-interface QI and toolpath enumeration when the generated
flag is false remain live qualifications: a failed getter stops once, retaining
partial diagnostics, without inventing empty counts or replaying GOP. Zero-record
placeholder containers are permitted; only observed zero counts support the
no-calculated-records claim. Raw after-state is persisted before delta validation.

`machine_kind="mill_single_feature_qualification"` adds a separate lifecycle scope
for the same exact feature and an explicit ordered list of 0–32 operation native
IDs, all solely linked to it. Save and close remain separate guarded native calls;
all CAM reads are subscribed and post-cleanup checks use only SOLIDWORKS/file data.
The default TURN and zero-operation `mill_qualification` scopes are unchanged.
These software checks do not qualify whole RAM BRep invariance, physical pocket
depth, numeric units, material/tool choice, generated motion or reopen persistence.
GTP and WIP are subsequent separate qualifications after actual GOP operations
are known; generic WIP export has whole-machine/all-setups scope.

Explicit `machine_kind="mill_qualification"` adds a separate qualification-only
save/close path, requiring exact `process_id` and
`acknowledge_qualification_copy=true`. It accepts native MILL type 1 with zero
operations and bounded setup/feature counts. All CAM captures run under one active
message subscription; after disconnect only SOLIDWORKS document metadata and the
saved file hash are checked. Save checks unchanged captured machine/catalogue,
setup axes/origins, material and feature counts, plus `needs_save=false`; this is
not complete feature-geometry or reopen/persistence proof. Close is separate and
requires a clean document and `UserControl=true`. One-use receipt/state guards
prevent automatic replay. The default TURN path is unchanged. The installed
`ICWApp` HRESULT/no-OUT save/close binding was checked with an in-memory COM object
(strict integer S_OK=0); native MILL save/close remains pending qualification.

`solidworks_cam_document_lifecycle` 使用已明确绑定的 PID 和完整 saved-part 路径，
分别提供 prepare、save、close 三个 action。prepare 只读文档、CAM inventory 和
磁盘 SHA-256，返回整个状态的 state_sha256。save/close 各自要求这个精确状态哈希
及新的独占 receipt_path；不会自动串联 save 与 close，不重复不确定请求。
message_policy 必须明确为 vendor_default，不能提交猜测的 Yes/No/Cancel 数字。

`welcometopic.htm` 的 Listening to events 与 Open, Close, Save file 段落明确说明：
预先注册的客户端收到原本会显示阻塞消息框的事件；不调用 SetResponse 时 CAM
使用默认值。CloseActiveDocument 在 Save/Restore 关闭时可发出 CAM 数据保存事件。
工具在原生操作之前进入 CamMessageSession，再重新核对文档、inventory 和文件哈希，
持久化 intent，随后只调用一次 ICWApp.SaveActiveDocument（DISPID12）或
CloseActiveDocument（DISPID3）。两者无入参、HRESULT-only；不是带 BOOL 成功返回值的
接口。close 还要求 SW save flag 为 clean，但这不证明 CAM 内部数据也是 clean。

每次原生返回先写回执；任何 CAM message/回调/清理问题均要求 review，停止后续
CAD 读取，不把 default_unknown 解释成已确认保存或已取消。没有消息时，save 检查
同一文档与 inventory，文件变化另列；close 仅用有界 SW 文档列表验证目标已不在
会话中，不在自动激活的其他文档上调用 CAM。清理订阅后再次核对。
输出区分 native_save_call_returned / native_close_call_returned 与实际只读核对；
persistence_verified 始终 false，保存数据是否恢复必须由另一次明确 reopen 证明。

此工具只能在没有已打开模态框的正常状态下预先订阅。文档没有保证晚注册能够接管
现有窗口，也没有保证 SaveActiveDocument 在已阻塞的 CloseDoc 内可安全重入；
它不是已有模态框的 dismiss/answer API，不使用 HWND、Windows 消息或 UI 操作。
厂商没有在已检查页面定义 SetResponse 的响应常量。HRESULT S_OK 和 COM Invoke
结果里的零不是 CAM 的 Yes/No 回答。活体资格仅覆盖下面列出的独立工作副本案例。


### 显式隔离启动与空文档会话寿命

`solidworks_connect({launch_new_instance:true, visible:true})` 明确请求新实例，不能
同时提交 process_id。启动前记录原生进程 PID 集，DispatchEx 后确认应用返回的
实际 PID 不在该集合，再设置并回读 UserControl=true；不对原有实例设置可见性或
用户控制。成功后 MCP 绑定这个精确 PID；后续进程仍应显式携带返回的 process_id。
验证失败不自动关闭/终止任何进程，不回退默认实例；该显式启动 action 非幂等。
PID-bearing ROT moniker 不是必需条件：若只有其注册等待超时，可保留已证明的新实例
COM proxy，重新核对同一 PID/UserControl 后返回，并明确记录 moniker 未验证。
不会为此读取 generic/class alias 或再次启动。后续 explicit-PID 连接仍回读实际 PID。
2026 SP4 实测新实例创建与 UserControl 回读通过，但只有 generic CLSID moniker，旧版
exact-PID-label 等待失败；随后明确 PID 的重新连接、打开与持久化检查成功。
保留自有 proxy 的新版分支有离线回归，尚未再次执行活体启动。

官方 [UserControl](https://help.solidworks.com/2023/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.ISldWorks~UserControl.html)
说明 COM 程序启动的应用可随程序退出，移交 UserControl 后继续运行且可见。
[CloseDoc](https://help.solidworks.com/2024/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.isldworks~closedoc.html)
另明确后台会话关闭最后一个文档时可以结束应用。Visible=true 不能替代 UserControl。
因此 CAM lifecycle close 现在只读检查 UserControl 严格为 true，否则在原生关闭前
拒绝；不会隐式修改现有会话的控制权。

2026 SP4 资格试验中，CAM CloseActiveDocument 返回后一次应用进程退出，后续文档
枚举失败；先前 UserControl 未测量，退出原因未确定，该次 close 不构成成功资格。
独立内存 COM 回归确认 ICWApp 的 CloseActiveDocument/SaveActiveDocument 使用精确
IID 的 vtable 方法，不经过默认 IDispatch.Invoke，不调用 Terminate。
此 ABI 结果不能替代保存文件重新打开和实例存活的实测验证。

后续 2026 SP4 单一工作副本试验中，先确认 UserControl=true，再分别明确调用
native save、native close、重新打开及只读检查。目标确实关闭，自有精确 PID 在
关闭后仍存活；重开后单线特征的 Thread 策略恢复，CAM 消息为零。该案例验证带
UserControl 门禁的保存/关闭/重开流程，不证明旧实例退出原因，不验证所有模型、
Save/Restore 选项组合或有消息时的默认保存响应，也不扩大模态窗口处理能力。


## 单线车削特征的目录策略（受限活体验证）

`solidworks_cam_configure_turn_feature_attribute` 提供 inspect、prepare、apply；
参数为已绑定 PID、准确的 saved-part 路径、feature_setup_index、正数
expected_feature_native_id、expected_turn_feature_type、qualification_only=true 和
message_policy=vendor_default。inspect 可带 attribute_name，以及仅检查时允许的
read_techdb_path=true。prepare/apply 必须给出完整原生 attribute_name，不去空格、
拆分或忽略大小写；apply 另需 prepare 的 expected_state_sha256 和新独占 receipt_path。

ICWTurnFeature.IGetAllAttributes（DISPID8）返回 VARIANT；保留转换后的形状，只接受
有界、无重复的完整 BSTR 名称列表。GetTdbIdForAttribute（DISPID9）从实际目录名称
解析 LONG ID，不硬编码 Thread 的 ID。该方法没有成功 BOOL；非正 ID 的语义尚未
资格化，只可诊断，不可写入。Attribute（DISPID4）为 LONG propget/propput，写入
没有 BOOL 返回值。apply 只写一次，并先立即读回 Attribute 与 GetAttributeName，
再在事件订阅有效时检查完整后快照；不猜测 Update/Rebuild 调用。

prepare/apply 要求 clean saved-part、目标恰为一条非退化直线、没有任何操作关联
目标 feature；绑定文件 SHA、模型实体/特征、全部有界 CAM profile、操作 ID/关联与
刀路记录数。只允许目标策略 ID/名称及文档 dirty flag 改变。这里不读取刀路坐标，
不会把计数/关联不变描述为完整刀路几何证明。快照之间及写入前核对文档，getter
之间只做本地 CAM 消息检查，包括 context 和 profile 内嵌的 Count/Item；集合先核对
剩余预算，再读取 Item。最后完整 CAM 快照在取消订阅前取得，取消订阅后只检查
事件清理状态、SW 文档状态及磁盘哈希，不再访问 CAM；不把它描述为清理后完整 CAM
证明。消息/回调/清理异常立即停止，无重试或自动回滚。

可选 ICWApp4.IGetTechDBPath（DISPID62）是无入参 METHOD，返回 BSTR；仅报告
原生路径，不读取数据库内容、不启动/切换数据库、不进行 SQL 写入。接口 ABI 来自
已安装 25.0 typelib；2026 SP4 单一工作副本上已只读验证返回实际活动 TechDB 路径。
这不验证数据库切换/写入或所需螺纹条件的存在。离线测试覆盖目录、严格 schema、路由、
单次属性写入、事件停止、部分诊断和全部允许变化的边界。

策略设为 Thread 不等于 Thread Condition 已选定。螺距、螺纹深度、大小径、单位、
刀具及生产资格均不因此确认。工具不运行 GOP/THREAD 插入/GTP，不保存；保存与
重开持久化检查是单独的明确步骤。apply 成功读回仍返回 review_required 和
may_continue=false，保留这些未完成的资格限制。

此 attribute 工具只对 solids.mass_properties_native 的 SHA 规范化使用 11 位有效
数字，最大相对量化步长为 1e-10；原始浮点数据完整保留，独立语义比较继续采用
相对容差 1e-10、绝对容差 0。文件、包围盒、profile、操作和关联均精确比较。
实测约 4.24e-12 的惯量相对漂移在旧 12 位指纹中跨格，新规范化能稳定识别该组
输入；这不是容差相近必然同哈希的承诺，舍入边界仍可安全拒绝。规则改变后必须
重新 prepare，不自动重试 apply。既有单线创建工具的默认 12 位规则不变。

2026 SP4 活体案例：在一个 clean 工作副本上，目录实际返回 Thread，动态解析的
策略 ID 为 18（该数据库的观测值，绝不是固定映射）。对无关联操作的已验证单线
feature 完成 prepare 和一次 apply，立即 ID/名称回读及订阅内完整后快照通过；
消息数为零、Unadvise 确认。随后用独立生命周期工具保存、关闭、重开，Thread
策略仍在，文件 SHA 与保存后的文件一致。9 features、15 operations、零 THREAD
operations，以及旧操作 ID/关联/刀路记录数保持不变；未比较刀路坐标。未运行 GOP
或 GTP，未配置 M60 Thread Condition、螺距或深度，不代表完整螺纹加工或生产放行。
这个持久化证明属于已实测副本；attribute apply 本身仍不保存、不声明持久化。


### 单特征 Thread 操作计划（离线验证，原生试运行待验证）

`solidworks_cam_qualify_feature_operation_plan` 提供 `inspect`、`prepare`、`apply`。
输入精确已保存零件、现有绑定进程、特征 setup/正原生 ID/类型，以及预期特征数、操作数和操作 setup 数。
本阶段只接受实际目录名 `Thread`；动态解析其 ID，不把 TechDB 表 ID 当作 CAM 属性 ID。
`prepare` 要求干净零件、唯一非退化单线特征、现有策略与目录匹配、该特征没有关联操作。
`apply` 绑定准备快照 SHA 和全新 JSON 回执，在事件订阅内只调用一次
`ICWFeature.GenerateOpPlan(CW_GOP_RETAIN=1)`（IID `{682686E4-3685-11D6-A9AA-00062999E55F}`、DISPID 3、LONG 输入、无 OUT）。
方法返回只记录调用已返回；验证必须发现恰好一个新的正 ID、类型 12、只关联目标特征且无刀路。
其他特征、文件、模型、旧操作顺序/关联和刀路记录数必须保持；完整刀路坐标不在本验证范围内。
原始质量属性保留，只有质量哈希采用 11 位有效数字及独立 1e-10 相对比较；其他字段精确比较。

结果始终需要人工/上层复核，不证明 Thread Condition、完整深度、工具、单位、M60 参数或持久化。
不自动保存、GTP、重试或回退。事件、异常或非预期增量之后停止；`inspect` 允许在脏模型和已有关联操作上读取当前状态，
使用当前准确计数，不重放 GOP。回执不可覆盖；最后完整 CAM 快照在退订前，退订后仅检查 SW 文档与文件哈希。
独立保存/关闭/重开及参数资格检查必须另行执行。安装版 CHM `ICWFeature/GenerateOpPlan.htm` 与 CAMWorksLib25.0 TLB 是 ABI 依据。
官方 Turn Tutorial 要求选择匹配的 Thread Condition；仅设置 Thread 策略不能证明已满足该条件。


单特征 GOP 的一次 SOLIDWORKS CAM 2026 SP4 原生资格验证已完成：已保存独立零件上的单线 Thread 特征，
RETAIN GOP 新增恰好一项 type 12，旧操作 ID/顺序/关联/记录数保持；通过独立原生保存、关闭、重开和有界标量读取确认新增操作持久化。
这只确认该生成与持久化路线，不代表默认线程条件、默认 Pitch、工具或完整深度正确。

### 已存在 THREAD 的单字段 Pitch（离线验证，原生试运行待验证）

`solidworks_cam_configure_thread_pitch` 复用单线特征快照，增加明确的 operation setup/index/正原生 ID。
`inspect` 只读既有 16 项已验证标量，允许脏模型；不探测 Z 限制、工具或其他未验证属性。
`prepare/apply` 必须给出不同的 `expected_old_pitch` 与 `new_pitch` 原生数值、精确数量、当前 `Thread` 目录策略，
且模型干净、目标操作没有已生成刀路。`apply` 绑定状态 SHA 和新回执，只调用一次
`ICWTurnThreadOp.SetPitchValue(DOUBLE)`（DISPID 2、HRESULT、无 OUT）。
立即检查 GetPitchValue 后再完整回读；仅允许目标 Pitch、其派生 ActualPitch 和 SW dirty 标志变化。
其他参数、特征、模型、文件、旧操作关联及刀路记录数必须保持；退订后不再读取 CAM。

不设置 60°、方向、工具、完整深度、TechDB ID，不保存或 GTP，不自动重试。
60° 螺纹形状属于 Thread insert 的 IncludedAngle；EntryAngle/WithdrawAngle 不能替代它。
文档把完整螺纹深度作为 feature/ThreadCondition 的独立参数，不能因 Pitch 写入成功就断言深度自动正确。
实际生成路径的直径、范围和材料去除仍需要后续独立验证，原生数值不自动解释为全局毫米/度。


Pitch 的一次原生资格验证已完成（SOLIDWORKS CAM 2026 SP4，独立工作副本）：单次写入后立即读回目标值，
其余 15 项既有标量保持；独立原生保存、关闭、重开后仍读回目标 Pitch。
该结果不证明 ActualPitch、完整深度、方向或刀具参数的物理含义。

### 精确 THREAD 的只读刀具与 CL 记录（原生试运行待验证）

`solidworks_cam_inspect_thread_tool` 要求明确 `process_id`、保存零件路径、setup/index、正操作 ID 以及唯一关联 feature ID。
仅接受原生 type12；先验证通用 tool type15 再读取既有车削刀具尺寸，可用 `holder_profile=operation` 读取原生 holder 曲线，
或显式 `none` 跳过曲线。复用已有 profile/tool readers；缺失工具与读取异常严格区分，首个异常保留部分结果并停止。

`solidworks_cam_inspect_thread_records` 要求同样的精确进程/文档/操作身份和已经生成的 THREAD 刀路。
`max_records` 默认 10000、最大 100000，计数超界在读取记录前拒绝。
只解码 type36 THREAD（EndX/Y/Z、Pitch、Height）、type7 GOTO（rapid flag、point）及 type8 SPINDL（七个原生 OUT）；
其他记录类型保留顺序与类型号，明确标记 payload 未解码。记录序列有 SHA256，保留原始数值。
Height 不解释为完整径向深度，原生点不自动解释为世界/FCS 或半径/直径；必须结合模型和材料去除验证。
这两个工具在必需的 app/notifier 引导后，对全部 CAM getter 保持事件订阅，包含 Count/Item；退订后仅检查 SW 身份与文件。
不保存、不重建、不生成、不修改任何 CL 记录。

### 材料与切削条件（离线验证，原生试运行待验证）

`solidworks_cam_configure_cutting_conditions` 提供 inspect/prepare/apply，单独设置 Material 或一个原生切削字段：
SMM、MAXRPM、SpindleSpeed、FPR、FPM、IsSMM、IsFPR、IsAssociateWithStockMaterial。
以所有文档操作作为保守影响范围，拒绝已有生成刀路；不把不同 IUnknown wrapper 当作无共享参数的证据。
Material 在 zero-ops 阶段可使用空 affected list，须有 exact native name 与已核验材料映射的 hash-bound JSON；
工具的 GetAllStockMaterialsList 仅作为工具相关诊断，不宣称它是全局 Workpiece 材料目录。
数值写入须有针对该字段、文档和原生 unit record 的独立校准 JSON；全局 TechDB Units 表不能代替 API 单位证据。
所有写入要求新回执、准备状态 SHA、保存文件哈希、活动事件保护及单字段回读；不保存、GTP、克隆工具或修改数据库。
当前 Workpiece.Material 对材料组或具体 MES 名称的接受语义仍须原生资格验证。


2026-10-26 资格检查补充：精确 THREAD 工具读取已在单独副本返回 native tool 565、车削刀具类型15、螺纹角60和鼻圆角0.1；所选 THREAD 的 GTP 返回34条 CL记录。此事实不证明完整螺纹深度或物理工装。首次 `GetRecordAtIndex(0)` 返回 native HRESULT -2147220991，未重试其他索引。读器改用文档化 `GetEnumRecords` 和既有 `ICWDispatchCollection.Count/Item` 规则，集合长度必须与 `RecordCount` 完全一致；新访问路径仍待 live 资格确认。

只读 CL 白名单增加 `UNITS=24` 的 `ICWUnitRecord.GetUnitParams`（一个 BSTR OUT）与 `FEEDRATE=29` 的 `ICWFeedrateRecord.GetFeedrateParams`（DOUBLE、LONG OUT）。字符串和 `bIsMatric` LONG 原样报告，不把它们自动扩展成所有 CAM 参数单位的保证；`FEED=14` 是不同记录，不混用接口。

`solidworks_cam_inspect_material_catalogue` 只读 `ICWApp4.GetWorkpieceMaterials`（DISPID65，四个 VARIANT 数组和一个计数 retval）及 `GetUseDocumentUnit`，要求当前明确绑定进程、精确干净已保存零件和一致文件哈希。目录读取两次并比较，CAM getter 均在事件订阅期间执行。它不更换数据库、不写材料，也不将目录名称视为合金等价或 Workpiece.Material setter 映射已验证；新原生路径目前仅有离线测试。


2026-10-26 后续原生结果：`GetEnumRecords()` 同样返回 HRESULT `0x80040201`，无 CAM 事件、无崩溃；34条路径计数在独立保存/关闭/重开后保留。安装版主要示例明确使用该集合链路，尚未找到厂商对该 HRESULT 的 CL 语义解释。不要通过猜索引、重放 GTP 或调用未证实接口声称已读到记录。

`solidworks_cam_qualify_thread_postprocess` 提供 inspect/prepare/apply：要求显式 PID、精确干净 SLDPRT、磁盘 SHA、正 native THREAD ID、setup/op 和记录总数。读取 `ICWMachine5.GetController2()` 的 isAPT/name/success 并绑定 prepare hash；apply 仅调用一次 `ICWTurnOperation.PostProcess(BSTR)`，不修改 controller，不 GTP、不保存、不发送给 CNC。输出必须位于新建专用目录，先写独占 intent receipt，之后确认非空文件/hash、原文件及 inventory/controller 不变；额外输出或任何不确定性保留证据并拒绝重放。始终 `productionNC=false`；内容须按实际 post 单独解释，存在 NC/APT 文件不证明螺纹深度、螺距、方向或可安全上机。此路径目前仅离线测试，尚未原生资格确认。

`solidworks_cam_configure_mill_qualification` 仅在空白已保存副本选择原生 MILL 目录项，或通过 `InsertMillSetup` 插入一个零原点、±X/±Y/±Z 的空设置；检查精确新增 ID、方向、原点及无非预期 inventory 变化。`solidworks_cam_configure_mill_stock` 仅在无特征/操作的 MILL 副本将审核过的加工余料 STL 定义为 stock；要求 STL/目标/包含性证据文件的哈希，使用声明的 mm 枚举0、默认CS、非bounding-box替代，检查type4、路径、单位与零offset回读。STL属于制造毛坯，不替代产品 BRep。两工具均不 AFR/GOP/GTP、不保存，也不宣称物理工艺或模型坐标系已资格确认。

MILL及cutting_conditions的首次、inspect、prepare快照已纳入同一 active CamMessageSession；除取得 app/notifier 的必要bootstrap外，CAM getter不在订阅外执行。Unadvise之后仅检查SOLIDWORKS文档与磁盘哈希。除下述受限目录 inspect 外，MILL 写入路线仍需原生资格确认；后续必须独立保存/重开和几何核验。

`solidworks_cam_configure_mill_qualification` preserves bounded partial document/file/current-machine and ordered catalogue diagnostics. `MachId` is not documented as globally unique: repeated IDs are reported without deduplication. Machine prepare/apply requires a unique selected full descriptor (type, ID, name, description); its index, the ordered catalogue, operation and setup direction are bound to the prepare hash and checked again before dispatch. Inspect/setup do not require global ID uniqueness. One SOLIDWORKS CAM 2026 native inspect returned three distinct Metric/4-axis/5-axis descriptions sharing `Milling Machine Metric`, with existing `Mill - Metric` already assigned, no setups/features/operations, no mutation or CAM events, and verified event disconnect. The file SHA matched the saved source while `needs_save=true`; inspection did not save that initialized state or require reassignment. This qualifies only the observed catalogue-read route, not machine/setup writes, material, MILL depth/feed units or production suitability. Evidence: `02_mill_machine_inspect_diagnostic_result.json`.



2026-10-26 安全限制更新：在 Material prepare 的 `GetUnitRecordParam` 阶段观察到 RPC 失败和自身 SOLIDWORKS 进程消失；Windows WER 为 heap corruption `c0000374`。这不证明该 getter 是唯一损坏来源，早先 CL 失败调用的影响也未排除。全部 TURN/MILL 快照已移除该 getter；报告 `unit_record_raw=null`，不猜单位、不 catch/retry，也不因材料 BSTR 写入去读单位。需要单位的数字写入明确拒绝未知单位，未来独立单位证据路线需另行资格确认。

`solidworks_cam_inspect_thread_records` 当前在原生访问之前返回 blocked；`GetRecordAtIndex` / `GetEnumRecords` 均不得重试，没有请求参数可解除。离线解码测试保留，但不代表这些读取器在当前版本安全可用。独立 PostProcess 与 WIP 属于另行资格阶段，不能从该限制推出它们已经成功。


### 独立 EXE 启动（离线验证，待原生资格）

当 `DispatchEx` 返回已存在的实例时，连接器仍在任何属性写入之前拒绝。新增显式
`solidworks_connect({launch_new_instance:true, launch_mode:"executable", startup_receipt_path:"<new absolute .json>", wait_seconds:60, visible:true})`
使用现有安装定位器选取 `SLDWORKS.exe`，不接受任意命令或启动参数。原有 `launch_mode:"com"` 默认行为不变。
EXE 模式在启动前独占写入 intent，随后仅启动一次主程序；不使用 shell、不继承 MCP 标准流、不创建终端窗口。
它验证进程不在启动前 PID 集中，并重复核对创建时间、可执行映像路径和存活状态。公开
[QueryFullProcessImageNameW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew)
以 PROCESS_QUERY_LIMITED_INFORMATION 读取映像，不是窗口控制。
只有 ROT 对象的实际 PID 等于该已验证新 PID 时才设置并回读 UserControl/Visible；标准应用别名可用于
此精确 PID 核对，但不能把别名返回的其它进程作为 fallback。不会调用 Dispatch/DispatchEx 激活第二次。

启动失败、身份未知、注册等待结束或日志落盘失败均保留 receipt，并报告 uncertain；不终止或关闭任何实例，
不自动重试，已有 receipt 路径禁止覆盖。超时后先读取日志及新进程身份，再决定显式连接，不能重放启动。
新模式已经过模拟回归；OS 元数据读取已仅在测试 Python 自身进程验证。尚未宣称 SOLIDWORKS 原生启动、
客户端退出后的进程寿命或该模式的 ROT 注册在当前机器成功。


`solidworks_cam_status` 与 `solidworks_cam_load_addin` 新增显式应用级空会话作用域：
`expected_no_documents:true, process_id:<already pinned PID>, addin_clsid:<registered CLSID>`，
不能同时传文档路径或标题。仅这两个工具接受该字段；其余 CAM 工具继续要求精确文档目标。
连接前核对固定 PID，核对已登记插件的 SOLIDWORKS 年份，原生调用前后通过 `GetDocuments`
和 `ActiveDoc` 验证包括隐藏文档在内的空会话，并复核 PID。枚举错误不是空会话。
若加载后范围改变或不可读，保留原生返回结果并报告错误，不关闭文档、不重试加载、不保存。
这允许在打开工作副本之前显式加载 CAM，避免为了加载插件而触碰已打开的副本；不承诺插件没有其它应用级副作用。
新增分支已通过模拟测试，原生资格由单独的调用回执记录。


### APT 选择与纯轮廓草图：离线测试阶段

`solidworks_cam_configure_apt_controller` 提供 `inspect/prepare/apply`。它读取当前机床的
`ICWMachine5.GetPostProcessorList(True)`、`GetController2()`，可按实际目录名称读取
`GetControllerParameters(True, name)`；仅在明确确认的已保存隔离 TURN 副本中调用一次
`SetController2(True, name, directory_with_trailing_separator)`。输入绑定进程、文档与保存文件
SHA、候选 `.aptctl` 文件 SHA、prepare 状态和独占 receipt。所有 CAM 读取都在消息订阅内；
任何消息、额外状态变化、错误返回或不匹配读回都会停止，不重试、不保存、不后处理或发送机床。

目录参数的具体语义尚未原生验证；调用者必须明确确认这是资格实验。官方帮助说明保存的路径
不可用时可能搜索默认目录，甚至选择第一个 post。精确 APT/名称读回排除不同名称的回退，
却不能证明加载的是给定 SHA 文件：`GetController2` 不返回实际路径。成功读回仍返回
`review_required`、`actual_loaded_file_verified=false`、`productionNC=false`。后处理属于
另一个显式动作；不能把此工具的 mock 测试当作原生 APT 输出验证。

`solidworks_cam_create_profile_sketch` 只在精确 PID/已保存资格副本中创建一个二维草图，
必要时创建一个轴向偏置参考面。`spec` 包含 `plane_axis=X|Y|Z`、`plane_offset_mm`、
互不相同的新 `sketch_name/plane_name`，以及 `circle(center_model_mm,radius_mm)` 或
`closed_polyline(points_model_mm)`；后者限3至32个不同顶点。prepare 返回状态 SHA；
apply 必须带相同 SHA 和新 receipt。使用公共 SOLIDWORKS API，按米读回实际模型坐标、
闭合轮廓及刚体变换，同时核对旧实体与特征。无 CAM 调用、实体操作、自动保存或重试。
这只确认 SW 草图使用的米/毫米转换，不证明 CAM 长度、深度或进给单位；MILL 特征写入
仍等待独立的几何单位资格验证。当前两个新入口均仅有离线测试，不宣称原生资格完成。


### 单个 MILL 特征的局部几何单位实验

`solidworks_cam_qualify_mill_feature_units` 提供 `inspect/prepare/apply`，仅接受明确声明的
隔离已保存副本、精确 PID/文件 SHA、一个实际 MILL setup ID、无操作和无 CAM 特征，
以及已保存并按模型米坐标读回的非对称四直线矩形草图。prepare 固定完整状态；apply
需要新 receipt，只调用一次 `ICWSetup.CreateMillFeature2`，类型 OPEN_POCKET=5。
`depth_native` 限1至100整数，但原生 `dDepth` 是 DOUBLE；此限制不把输入默认解释为毫米。

读回要求正 native ID、恰好一个 VolumeType=6 特征、原有 SW 特征与实体不变，
以及 `ICWMillFeature.IGetTopSegChain/IGetBottomSegChain` 返回各一个四直线轮廓。
`GetCurveAtIndex` 使用已核对的零基 `INT*` ABI，不尝试不同索引。两个不同边长和
对角线分别与真实 SW 草图比较；上下平面的距离直接来自真实端点，不能用 Depth 元数据代替。
绝对 CAM 坐标系、深度轴独立标定、全局单位、SMM/FPR/FPM 和工艺均不由此自动确认。

所有 CAM 读取在消息订阅内；退出后只核对 SW 文档/文件。无 AFR/GOP/GTP、保存、
库存修改、草图修改或 native 重试。未知创建结果只能检查现状；已有特征必须指定精确 ID
才能读取轮廓。没有 ID 的检查只暴露观察到的 ID 并停止，不重新创建。该实验不会放宽
现有生产 MILL/切削数值单位门禁；原生资格结果需单独审核。当前仅有离线测试及协议验证。


APT 原生目录已观察到 `GetPostProcessorList(True)` 返回 `E_FAIL`，发生在返回 VARIANT
之前、无消息或写入。已安装 TLB 的 BOOL 输入与该调用一致；目录依赖/失败原因尚未确定，
不能据此猜测其他参数或重试。新增显式 `catalogue_source="installed_files_qualification"`
模式：只读取当前 SW 年份对应的 `ProgramData/SOLIDWORKS/SOLIDWORKS CAM <year>/Posts/Turn`
直接 `.aptctl` 文件，限制目录项/文件数与大小，记录文件 SHA。候选名称来自文件 stem，
明确不是原生目录结果；不调用 `GetPostProcessorList` 或 `GetControllerParameters`。
此模式必须由调用者新请求明确选择，绝不在 native 目录失败后自动切换。prepare/apply
仅允许该目录中的精确候选文件与 SHA。单次 setter 后仍必须读回 strict true、APT=true
和精确名称；目录参数与实际加载路径继续 unverified，不自动开放后处理或生产 NC。


### Bounded operation variable-allowance inspection (offline tested, native qualification pending)

`solidworks_cam_inspect_turn_variable_allowance` reads one exact current ROUGH (type 1) or FINISH (type 2) operation. Required selectors are `process_id`, `addin_clsid`, `expected_document_path`, `setup_index`, `operation_index`, `expected_operation_type`, `expected_operation_native_id`, `expected_linked_feature_ids`, and `expected_source_sha256`. `message_policy` accepts only `vendor_default` (the default). The process must already be explicitly connected; the saved part SHA and all linked feature IDs are checked before the new getters. Existing unsaved memory is allowed for this read-only route only, reported, and must remain unchanged.

The typed calls are `ICWTurnRoughOp/ICWTurnFinishOp.GetAllowanceMethodVariable()` (raw LONG) and `ICWTurnOperation.GetAllVariableAllowances()` (four VARIANT outputs plus BOOL retval). The result preserves raw segment names, X/Z values, count and mode. Two bounded captures run under one active CAM message session; after disconnect only document/file checks run. Partial geometry and completed metadata remain available on the first failure. The tool never reads cutting tools, `GetUnitRecordParam`, CL records, or writes/generates/saves.

Native method availability, allowance-name mapping to profile segments, mode meaning, unit scaling and radius-versus-diameter scaling remain unqualified until separate native evidence. Array order is not a geometry mapping; no allowance write or production machining approval follows from this read.


The same tool supports explicit `action="identify"` when current linked IDs are unknown.
It requires the exact PID/document/SHA, setup and operation indices, and expected operation
type 1 or 2. `expected_operation_native_id` is optional but enforced when supplied;
`expected_linked_feature_ids` must be omitted/null. Two equal bounded captures return
`before.selected_operation.native_id` and `linked_feature_ids`, with identity checks under
the same event subscription. This mode does not read full inventory, profiles, tools,
variable mode or allowances. Empty linked IDs are reported as observed, not treated as
allowance qualification. The default `action="read"` still requires both exact ID inputs;
identify does not automatically invoke it. IDs are scoped to the current CAM document,
not guaranteed reusable after reopening. Both modes remain read-only; native identify
qualification is pending, distinct from the mocked branch/guard and MCP protocol tests.


### Bounded positive variable-allowance qualification

`solidworks_cam_qualify_turn_variable_allowance` offers `prepare/apply` in a distinct,
byte-identical copy of a protected saved CAM checkpoint. It requires explicit PID,
document/source SHA, exact operation type 1/2 and native ID, linked feature IDs,
`baseline_checkpoint_path`, and `qualification_only=true` plus
`acknowledge_unqualified_mapping_mode_units=true`. `changes` contains one or two unique
observed names, each with expected and desired raw X/Z values in 0..1; values may only
increase, with at least one increase per name. Names are exact BSTRs, never indices.
`expected_mode_native` is 0 or 1; `candidate_mode_native=1` is an acknowledged experiment,
not a documented enum mapping. The selected operation must have no generated path.

Prepare binds state and recipe. Apply requires that SHA and a new absolute JSON receipt.
It performs at most one mode setter and two per-name setters, with durable intent and
all-name/mode readback after each. Mode setter has no BOOL retval; per-name setter must
return native true. First error stops; partial completion remains recorded, without retry
or rollback. All CAM reads/writes remain within the event subscription. The final capture
checks linked profiles and inventory; after disconnect only SW document/file checks run.
There is no automatic GOP/GTP/save/post or product geometry editing call.

Native identify/read has been observed successfully on one SW CAM 2026 SP4 saved turning
copy (one FINISH operation, seven names and raw mode 0). The new writer is offline-tested
only. Even successful scalar qualification returns `review_required`, `may_continue=false`:
name-to-geometry mapping, mode meaning, numeric units/radial scaling, persistence and actual
remaining stock remain unverified. Inventory invariance does not prove every other operation
parameter unchanged, and linked profiles/saved bytes do not prove complete RAM BRep
invariance. A separately reviewed actual WIP/nominal-target containment result is required
before claiming a protected local feature is preserved.


### Existing axial TURN line: bounded crop qualification

`solidworks_cam_qualify_turn_feature` keeps its existing whole-line behavior when
`crop_z_native` is omitted. The optional crop takes `[startZ,endZ]` in the already
observed native coordinates. Both endpoints must lie within the exact source domain,
with positive length and the same direction as the source; no endpoint expansion or
implicit reversal is performed. The source must be a confirmed native straight line
parallel to its Z axis, within a fixed 1e-10 model-metre XY numerical check. This is
not a manufacturing tolerance. Endpoint XY values are interpolated from that line;
there is no independent endpoint/radius input.

Crop additionally requires `process_id`, `expected_source_operation_native_id`,
`expected_source_feature_native_id`, `expected_source_line_sha256` and
`expected_source_sha256`. The line SHA is the digest of the complete original raw
segment dictionary using UTF-8 JSON with `sort_keys=True`, `ensure_ascii=False`,
`separators=(",",":")`, `allow_nan=False`. Preserve the exact observed dictionary;
rounded display coordinates are not the hash input. Candidate feature type still must
match the actual source type. Fresh prepare pins the source line, IDs, file, cropped
geometry and native-to-model scale. Readback retains the full source and compares the
single newly added feature against `creation_line`, not the original whole segment.
Old CAM features, operations, saved bytes and bodies remain guarded. This does not
configure Thread, depth, pitch, tools, GOP or GTP.

Crop actions are `inspect/prepare/apply`; saving uses the separate existing native
lifecycle tool. Cropped snapshots begin after event subscription and finish before
Unadvise. After cleanup only PID/SW document/file checks run. The old whole-line event
coverage is preserved, not silently broadened or newly qualified by these tests.
Apply keeps single-use receipt/state gates and no automatic replay on unknown results.

Feature receipts now persist `capture_progress` before and after each full snapshot:
phase, start UTC, completion/error and elapsed seconds. A started preflight capture
with mutation=false does not mean geometry was attempted. This is progress evidence,
not an automatic heartbeat, completion guarantee or authority to retry.

The CLI `--timeout-seconds` limits the entire request batch, including startup,
connection and every capture. Cropped `apply` performs four full snapshots: initial,
before mutation, after sketch and after feature. Choose an explicit batch budget from
saved capture durations, allowing for native creation and cleanup; no fixed duration
is valid for every model or session. Saving remains a separate lifecycle action.
A client timeout does not prove the native call was cancelled or authorize replay.
Preserve its receipt and inspect the actual exact document/state before deciding how
to continue; an unfinished capture record is not a current live-session status.

One bounded crop has since been live-qualified on SOLIDWORKS CAM 2026 SP4:
the native call returned no object, but the exact one-feature delta and its line
geometry were verified, with the existing feature profiles and operation inventory
preserved. Native endpoint order was reversed and recorded; cutting direction was
not inferred or silently corrected. Solid-body boxes were exact, and mass values
were compared within the existing 1e-10 relative bound, not as bit-identical BRep.
Separate CAM save/readback succeeded; the newly cropped feature has not yet been
reopened. This qualifies this reference-profile case only, not a full thread,
physical tool, complete toolpath coordinates or general persistence.

The sketch crop follows the source endpoint order. As in the existing geometry verifier,
native feature readback may enumerate the same line in reverse; accepting that geometry
does not qualify thread handedness, feed direction or entry/exit. Those remain operation
and generated-output checks, independent of the bounded line domain.

`created_feature_orientation` reports requested and returned native endpoints,
`endpoint_order` (same/reversed/ambiguous) and the numerical comparison tolerance.
It uses the already captured new feature geometry; no extra CAM calls or automatic
Reverse setting occurs. `thread_direction_verified` remains false.

### Bounded THREAD feature attribute probe (offline-tested pilot)

`solidworks_cam_inspect_thread_feature_attributes` binds an explicit process, saved SLDPRT SHA, THREAD operation native ID and its sole linked feature native ID. It reads typed `ICWFeature.GetFeatureAttributes` once, between two bounded inventory/identity captures under one active CAM event subscription. A new JSON receipt records identity and the read intent before that getter. The part may contain unchanged unsaved CAM state; this read never saves it.

The result preserves exact Python marshalled scalar/list/tuple/bytes types within fixed size/depth limits. Unknown objects, including returned COM objects or pointer wrappers, are rejected without introspection, conversion, QueryInterface or fallback. Native VARIANT VARTYPE metadata is not preserved. A successful bounded read is `review_required`, `may_continue=false`: it does not establish that any field represents total thread depth, a complete ThreadCondition, units or physical machining capability.

No tool, holder, raw CL, prohibited unit getter, attribute setter, GOP, GTP, post or save is invoked. After event disconnect only SOLIDWORKS document/PID and saved-file SHA are checked. Inventory equality covers operation types, generated flags and path record counts, not all toolpath coordinates or every operation parameter. On a native error/message/unknown payload, retain the receipt and stop; the tool does not replay the getter. One bounded SOLIDWORKS CAM 2026 read has since been live-qualified: the exact OD feature linked to the selected THREAD operation returned 23 floating-point values, with unchanged identity/inventory/saved file and no CAM events. This qualifies only that read route for the observed case. No documented array index map was found; the observed profile-length match and sentinel-like values do not establish total depth or ThreadCondition semantics.

Required fields: `process_id`, `addin_clsid`, `expected_document_path`, `setup_index`, `operation_index`, `expected_operation_native_id`, `expected_feature_native_id`, `expected_source_sha256`, `receipt_path`. `message_policy` defaults to `vendor_default`; `response_format` defaults to JSON. The receipt must be a new absolute `.json` path in an existing directory. Operation and feature IDs are current document-scoped IDs, not IDs copied from historical qualification parts.

### TURN full thread depth: confirmed API coverage limit

The 2026-10-25 primary-help finding remains applicable: full thread depth is half the difference between the thread major and minor diameters and is distinct from depth per cut. A later installed CAMWorksLib 25.0 audit found no documented direct full-depth or ThreadCondition accessor on `ICWTurnFeature` / `ICWTurnThreadOp`. This is a limit of the inspected installed interfaces and help, not a claim that no vendor version or supported extension can provide it. Successful Thread strategy assignment, GOP persistence, Pitch write/readback or generic CL export does not close this limit.

`ICWTurnFeature` exposes profile diameter/endpoints/segments, a writable strategy `Attribute`, strategy catalogues and operation insertion. `ICWFeature.GetFeatureAttributes` is read-only VARIANT; no corresponding `SetFeatureAttributes` is declared. `SetDefaultStrategyFromTechDB` takes a strategy attribute ID and has no documented ThreadCondition/depth assignment contract. Do not write a guessed array index, reuse an unrelated database ID, or interpret profile D1/D2 as the independent thread-condition diameters M1/M2 without an explicit mapping.

`ICWTurnThreadOp.SetDepthPerCutValue` and `SetLastDepthPerCutValue` control per-pass values; neither is a total-depth setter. Pitch, canned-cycle flags and pass-count settings are also not substitutes for full-depth verification. The current generic CL output and existing profile/tool/16-scalar receipts should be reused for independent analysis; do not rerun unsafe raw CL or Z-limit getters to seek the missing contract.

`ICWFeatureFactory.CreateThread` and `ICWThread.SetParameters` do declare depth, tap form/designation, metric flag and tap/thread types. The inspected native `GetThread` bindings lead from MILL hole feature interfaces, not from the existing TURN feature or operation. Their existence does not justify speculative QueryInterface or parameter writes on a TURN OD/ID feature. `ICWThreadToolpathParams` is likewise not a documented total-depth setter or a qualified binding to this TURN feature.

The real tool is a separate contract: `ICWTurnOperation.SetTool(IDispatch*)` exists, and the holder declares `PrimaryDrivingPointAutomatic` (BOOL) and `PrimaryDrivingPoint` (LONG). These signatures do not establish an actual supplier insert/holder assembly or the LONG-to-tip/nose-centre reference mapping. Existing bounded insert dimension edits qualify CAM definitions only; changing a generic V insert is not proof of equivalence to a physical full-profile threading insert.

Before adding a full-depth writer, require one primary contract connecting the current TURN feature to editable total depth / ThreadCondition, or a documented structured read route that exposes those quantities. Bind any later extension to exact feature/operation/file identity and verify its independent generated result. Until then, full thread depth, tool reference and production suitability remain unverified; do not silently substitute pass depth, a MILL-hole object, direct TechDB writes or a guessed parameter index.

Primary declaration anchors in the installed generated typelib: `ICWTurnFeature` lines 64457–64573; `ICWFeature.GetFeatureAttributes` 11166–11171 and strategy methods 11234–11247; `ICWTurnThreadOp` 12277–12612; `ICWThread.SetParameters` 50315–50327 with MILL-hole `GetThread` bindings; `ICWTurnOperation.SetTool` 59253–59258; holder driving-point properties 68252–68275. These anchors are tied to generated-file SHA256 `359e2d39a970d2362fa1b44750963b9a64e1fa819d2d046e38174affa37eb3c4`, not to arbitrary future wrapper versions. Preserved audit artifacts: `depth_binding_primary.json`, `mcp_depth_binding_plan.json`, the 2026-10-25 `thread_feature_contract_20261025/contract.json`, and the bounded attribute read qualification receipt. No native calls were made for this knowledge update.

### Selected TURN rough/finish APT export (offline-tested pilot)

`solidworks_cam_qualify_turn_apt_postprocess` inspects/prepares/exports one generated, unsuppressed TURN ROUGH1 or FINISH2 operation. It requires exact process/document/source SHA, operation ID/type, linked feature IDs, total path record count and current APT controller name. Prepare binds that state and a new `.apt` output path; apply consumes a new JSON receipt and creates an exclusive output directory before exactly one native `ICWTurnOperation.PostProcess(BSTR)` call. This is a void HRESULT method, not a Boolean success return. Nonempty output/file hashes and unchanged inventory/source/controller are verified separately, including directory contents after event cleanup.

It does not change controllers, generate toolpaths, read raw CL/tool getters, save the model or send CNC data. Existing THREAD postprocess behavior is unchanged. An unexpected native return, CAM message, state change, output/cleanup or receipt failure stops without retry; any files remain evidence. Successful apply is `review_required`, `productionNC=false`. Exact APT/name readback does not prove the loaded postprocessor file/path. Output still needs offline unit, frame, radius/diameter and tool-reference analysis; no machining or geometry proof is inferred. Native TURN1/2 export has not yet been live-qualified.

### Explicit APT path argument qualification

`solidworks_cam_configure_apt_controller` accepts `path_argument_kind`: `directory_with_trailing_separator` (existing default) or `exact_aptctl_file_path`. The latter is permitted only with `catalogue_source="installed_files_qualification"` and the exact observed installed `.aptctl` file/SHA. The caller-selected controller name is unchanged. The selected kind and actual path argument are bound into the prepare state; changing either requires a fresh prepare and new apply receipt. No automatic fallback, filename-name substitution or native setter retry occurs.

Both argument meanings remain explicit qualification hypotheses; the installed TLB only declares BSTR. A strict native `false` may have partially changed the APT flag/name. If event transport remains clean, the wrapper reads the known controller and bounded inventory/operation IDs into `immediate_controller_readback` and `after_false`, retains partial diagnostics if a later getter fails, then performs normal cleanup and SW/file checks. The outcome remains `uncertain`, `readback_verified=false`, `controller_assignment_verified=false`, `apply_eligible=false`, and no postprocess is run. Native exceptions, non-Boolean returns or CAM events do not trigger diagnostic CAM reads. A matching name after `false` is not promoted to success. The existing true-return path still cannot prove the actual loaded controller file/path or downstream output.

### Explicit installed APT controller name qualification

`name_mode` is `stem` by default or explicitly `filename_with_extension`. Filename mode is restricted to `catalogue_source="installed_files_qualification"`; displayed candidate names are derived from the exact observed installed file name, retaining its extension. The caller still supplies the exact controller_name; the module does not silently convert or try another name. Source path/SHA checks remain mandatory. Name mode and selected name are included in prepared state, so changing either requires a fresh prepare and receipt.

The one next proposed diagnostic candidate is controller_name `turn.aptctl` with `name_mode="filename_with_extension"` and the unchanged `path_argument_kind="directory_with_trailing_separator"`. This is based on observed TechDB controller names containing an extension, not an explicit vendor SetController2 name/path mapping. The alternate full-file path argument remains available but has not been tried natively and is not the next selected candidate. No automatic traversal, fallback, postprocess or native retry is performed. Strict-false diagnostics remain unchanged and cannot promote a partial APT flag/name change to success.


### Generic CL machine-scope qualification

`solidworks_cam_export_generic_cl` provides `inspect` / `prepare` / `apply` for an exact clean saved TURN copy. It calls `ICWMachine4.SaveCLFile(BSTR)` once into a new dedicated local directory. This is vendor generic CL, not enhanced APT or an external-postprocessing input. It does not assign a controller or invoke AFR/GOP/GTP/model save; an unavailable current controller is captured and must remain unchanged.

Inputs bind the PID, document path/SHA, total operation count, generated-operation count and total record count. All operation IDs/types/generated flags/counts are compared before/after under one CAM event subscription; linked-feature topology and full motion coordinates are outside this snapshot. `qualification_only` and `acknowledge_machine_scope` must both be true. Apply additionally requires the prepared state SHA and a new one-use JSON receipt. Unknown/failed calls are never retried automatically.

The installed ABI is `ICWMachine4` `{95D0F478-6AA0-4AE9-BADD-2FAC078B1E5B}`, DISPID14, HRESULT with one input BSTR and no retval. A real in-memory COM regression confirms the typed Python result is integer S_OK=0; Boolean/None are rejected. File existence/hash and unchanged snapshots prove only that bounded output was obtained. Format, units, frame, thread depth/direction and machining correctness remain unverified; the native qualification below is limited to one saved TURN copy. No manufacturing release follows from software tests.


The first 2026 SP4 generic-CL qualification stopped before `SaveCLFile`: querying the separate `ICWMachine4` IID returned `E_NOINTERFACE`, while the current machine supports `ICWMachine5`. The installed typelib declares `ICWMachine5(ICWMachine4)` and inherits the same `SaveCLFile` vtable method. The exporter therefore now obtains Machine5 during inspect/prepare/capture and calls the inherited method on that pointer, with no separate Machine4 query or fallback. Receipt consumption and output-directory creation occur only after successful interface/state preflight. This correction is covered by an inherited-interface in-memory COM test; at that checkpoint actual SaveCLFile was still unqualified; the subsequent one-shot check is recorded below. The failed receipt and empty first output directory are retained, never replayed.


#### Qualified generic CL result and bounded APT return handling

A subsequent SOLIDWORKS CAM 2026 SP4 qualification successfully called inherited `SaveCLFile` through `ICWMachine5` on one clean saved TURN copy. The native result was integer S_OK=0 and the output was 4,157 bytes (SHA-256 `cfa71ecfc871e5070e71417a35433b2a2eed6ccaff61c3cfd5129b21c674ff46`). The complete captured before/after states matched: 9 features, 16 operation IDs/types/flags/counts, one generated operation with 40 records, and 15 ungenerated operations remained unchanged. Controller readback, source-file SHA and document dirty state also matched; zero CAM messages and confirmed event disconnection were recorded. This qualifies obtaining generic CL output for that case. It does not qualify its interpretation, units/frame, thread depth/direction, full machining geometry or production use.

The selected TURN1/2 APT exporter now also records `native_hresult` and requires exact integer S_OK=0 for its no-retval `PostProcess` method; the former None-only check incorrectly rejected that typed success result. Mock and actual in-memory COM tests cover the correction, including rejection of Boolean/None/non-S_OK returns. No native APT PostProcess qualification or controller-assignment success is claimed. The separate THREAD exporter is unchanged by this correction.
