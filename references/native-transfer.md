# 受限原生副本迁移与装配回读

当前为 qualification/pilot：本模块已通过离线 guards、schema、原生 dispatch 回归；
本工具的实际导入、布尔运算、重开及动画尚需调用方逐步活体验证。成功 BOOL、文件
落盘和文件复制均不单独证明拓扑引用、动画或生产资格。没有项目路径/修订号/实例数硬编码。

`solidworks_inspect_open_documents(process_id)` 只读列出指定已连接 PID 的有界文档
path/title/type/dirty/visible 和活动文档，允许无活动文档；不启动、关闭或激活任何文档。
STEP 导入先把实际返回文档的类型、标题、路径写入 transfer 回执，再验证预期 part 类型。
意外导入为 assembly 时仍拒绝实体迁移；这些元数据不授权装配实体导入。

## 零件副本

`solidworks_qualify_part_transfer` 的 action 为 prepare 或 apply。必填：process_id、
expected_document_path（当前唯一可见且 clean 的已保存锚点）、source_path/source_sha256、
output_path、donor_step_path/donor_sha256、roundtrip_step_path、mode、qualification_only=true。
可选 frozen_files 为最多512项 {path,sha256}。prepare 只读，返回 state_sha256；apply
必须携带该 expected_state_sha256 及新的 receipt_path。原文件、donor 和目标都必须关闭，
当前会话的所有已有文档必须 clean，UserControl 必须已经为 true；不隐式启动或接管会话。

- replace_body：完整 donor 只能为一个 solid。在原 SLDPRT 的独占字节副本中插入新体，
  只选择原体并 InsertDeleteBody2(False)。这保留文件来源与原特征历史，不保证旧拓扑 ID。
- add_delta：只允许明确批准的增量 donor，acknowledge_delta_only=true。最多8个 donor
  solids 逐体插入后，用 InsertCombineFeature(SWBODYADD=15903, empty, allBodies)。
- subtract_delta：同样要求显式 delta-only acknowledgement，使用 SWBODYCUT=15902，
  MainBody 严格为原体，ToolVar 严格为插入 donor bodies；不把原体当作工具体。

插入为 IBody2.Copy → IPartDoc.CreateFeatureFromBody3(body,False,1)，1为 body-check
选项。用 ISldWorks.IsSame（same=1, different=0）确认唯一原体；未知比较结果拒绝。
每个输入/最终结果要求有效 solid，零 sheet，Check3.Count=0。最终必须恰好一个 solid。
本地 ADD/CUT 的体积差还须符合 donor 总体积（相对1e-7，绝对0）；这只是门禁，
不能代替完整 STEP/B-Rep 差集。delta_volume_policy 默认 strict，仍按上述阈值拒绝不符。
显式 diagnostic 仅用于 qualification：记录 before/donor/after/expected/relative_error，
不符时 local_volume_delta_verified=false；允许保存和回导以进行独立完整差集检查，
不提高容差、不以体积替代几何证明、不自动放行下一步。GetBodyBox 仅作诊断，不作为精确全局包络证明。

导入前将 donor 按 SHA 复制到 output 旁的短名称；原始长路径只用于文件读取，
传给原生 importer/exporter 的输出路径限定小于240字符，保留调用者的显式路径形式。
STEP 导入使用已有有效 part template；限定的导入选项逐项保存、设置、回读，并在退出
恢复。保存/关闭/重开及回导 STEP 都有持久 intent/returned 记录。原生失败不重放，
不删除失败副本，不自动保存其它文档，不使用 Windows UI。已有源 SHA 在后检查保持不变。

继续修改同一新副本时，仅 local delta 模式允许 prior_transfer_receipt_path 和
prior_transfer_receipt_sha256。前次回执必须证明本工具已创建/保存/重开该副本，且
原始 source、当前 output SHA 均一致；不是任意 existing-output overwrite 开关。
每次仍需新的 donor staging 文件、roundtrip STEP、prepare SHA 和 receipt。外部修改
（包括更改元数据后保存）会使前次 output SHA 失效，不能悄悄继续。

## 已保存副本的受限完成

`solidworks_finalize_part_transfer` 只接受已经 Save3、关闭、重开返回的 transfer 回执。
必填 process_id、expected_document_path（当前活动的 output 或原 anchor）、
transfer_receipt_path/transfer_receipt_sha256、expected_output_sha256、
expected_anchor_sha256 和新的 receipt_path。原 uncertain 回执不修改。
重新核对保存文件 SHA、单一有效实体的体积和特征历史，仅导出原回执尚未尝试的 STEP，
关闭本次 output/donor，然后恢复原 anchor；不重放插入、布尔、重建或 Save3。
只要回执已有 STEP attempt，或目标 STEP 已存在，就拒绝自动重试。

CloseDoc/OpenDoc 后始终按完整路径重新获取 output、anchor 和 donor；不继续使用
跨生命周期的旧 COM proxy。anchor 若已消失，只能按原路径及显式 SHA 重开，且必须 clean。
新 transfer prepare 记录 anchor SHA；旧回执恢复则要求调用者提供已验证 SHA。
这不构成任意失败事务恢复，也不证明独立 STEP 等价或装配轴引用保持。

`solidworks_cleanup_part_transfer` 只接收 process_id、transfer_receipt_path/
transfer_receipt_sha256、expected_output_current_sha256 和新 receipt_path。
允许无活动文档；要求原回执证明本工具创建的独占副本、原 anchor SHA 及导入 donor 身份。
输出必须已由调用方单独保存且 clean；只关闭该 output 和回执唯一对应的 donor，恢复
原 anchor。已关闭的 output/donor 不重新打开。不保存、不导出、不重建、不声明几何合格；
原 uncertain receipt 保留，独立 STEP 等价报告与显式保存仍是另外的证据。

意外多实体 STEP 导入为装配时，可明确 acknowledge_discard_unexpected_import=true。
只允许一次已记录导入且未开始实体编辑/保存、output 仍为原始字节副本；装配必须是
staged donor 同 basename 的无路径 SLDASM。通过 GetComponents(False)/GetModelDoc2
确认最多8个实际 child parts；其路径/标题不能在导入前会话中，不能属于 frozen sources，
且磁盘文件必须不存在。仅关闭该装配和仍加载的这些 child parts，不保存到其暂定路径。
这不是通用关闭命令，也不增加装配实体导入能力。

## 关闭文件引用替换

`solidworks_qualify_reference_copy` 同样使用 prepare/apply、PID/anchor/source SHA/
new output/frozen_files。source/output 是 SLDASM；replacements 为1..8项
{old_path,old_sha256,new_path,new_sha256}，禁止重复、链式、循环和类型不一致。
源装配、目标和全部替换引用必须关闭。只字节复制源装配，然后逐项调用
ISldWorks.ReplaceReferencedDocument(newClosedAssembly,oldPath,newPath)，遇到任何
失败立即停止。每次原生调用之前和返回后都写回执。

native_reference_calls_returned 只确认全部返回 true；reference_replacements_verified、
assembly_identity_verified 和 animation_verified 仍为 false。厂商明确警告不同
internal file ID 的新引用可能在打开装配时产生错误消息，mates/references 也可能失效。
因此不将独立新导入 SLDPRT 的成功引用替换当作身份保持证明；必须另行打开/回读。
文件 byte-copy 可保留来源，但局部布尔也必须实际验证被引用 faces/axes。

原始自定义属性、Revision/ChangeScope 和文件名关联表达式随副本保留。最终几何通过
独立 STEP 检查后，用已有 set_custom_properties 和明确 save 更新元数据；重新记录
最终 SHA，再建立装配引用。工具不自动编造修订号或制造放行状态。

## 装配与动画单独检查

`solidworks_inspect_native_assembly` 必填 process_id、expected_document_path（SLDASM）、
expected_file_sha256、新 receipt_path。读取全部有界实例的 Name2/reference/path/
configuration/native ID/状态/16项矩阵、配置名、活动配置的全部 explode steps、每步
GetExplodeDirection/GetRotationAxis 的所属组件和可用 CylinderParams、study名与时长。
最多1024实例、512步骤；null/non-face 轴明确保留 unavailable，不调用猜测的 surface API。
可传 expected_snapshot_path/expected_snapshot_sha256 和最多32项 path_replacements
字典 old→new 进行精确基线比较；只有明确路径字段允许映射。不切换配置、不修复、不保存。

`solidworks_audit_native_animation` 是独立显式操作：除上述 PID/file/receipt 外，提供
study_name、explode_view_name、baseline_samples_path/baseline_samples_sha256、
tracked_components=[{key,reference,path}]（1..16项）及 matrix_tolerance（默认1e-8，
最大1e-6）。基线包含 sampled_transforms，最多1001个递增时间，必须从0开始。
只 collapse 指定既有 explode 展示、activate 既有 study、逐帧 SetTime/GetTime 回读并
对比实际矩阵；不 Calculate、Play、创建 study 或保存。有限时间就绪重试只针对既有
幂等游标；COM异常或未确认请求后不在 finally 再次重放。完整原生矩阵保存供离线复核。
最终确认 time0，并重读全部实例身份/配置/状态；只有基线 initial_closed_poses
覆盖所有实际 Name2 时，才声明全部最终闭合姿态验证。抽样匹配不证明连续路径无碰撞。

所有成功资格结果仍是 review_required/may_continue=false。关闭文件替换、结构/轴
回读、保存后重开、动画样本及独立几何比较是不同证据，不以其中一个替代其它步骤。

## 原生合同来源

- [InsertDeleteBody2 示例](https://help.solidworks.com/2018/english/api/sldworksapi/Insert_Delete_Body_Feature_Example_VB.htm)
- [CreateFeatureFromBody3 options](https://help.solidworks.com/2026/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCreateFeatureBodyOpts_e.html)
- [IBody2.Select2](https://help.solidworks.com/2017/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IBody2~Select2.html)
- [ReplaceReferencedDocument 限制](https://help.solidworks.com/2018/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~ReplaceReferencedDocument.html)

布尔枚举、精确方法参数及 IExplodeStep/IEntity/IFace2 接口也已与本机 SW34 的
sldworks.tlb、swconst.tlb、swmotionstudy.tlb 核对。类型库/离线测试不等于活体验证。


## 精确签名圆角：尚待目标拓扑活体验证

`solidworks_list_edges` 的返回增加 signature、box_basis、adjacent_faces 和读取 errors。
签名只使用原生几何，不使用 B-Rep 索引、CurveTag 或 COM 地址。IEdge 没有 GetLength/
GetBox；新 inspector 使用 GetCurveParams3 的端点/参数区间和 ICurve.GetLength3。
直线 box_mm 为精确端点包络；圆弧为支撑圆包络（不是裁剪弧的紧包围盒），另包含
CircleParams、裁剪参数与中点。其它曲线仅报告九点采样范围，不能用于 exact-mode 选边。
相邻面的 box/plane/cylinder 参数只作可用诊断，不虚构不可读的曲面数据。

`solidworks_fillet` 保留旧筛选模式。精确模式提供 process_id、expected_document_path、
axis="all"、radius_mm、edge_signatures、expected_edge_count 和 dry_run=true；禁止混入
旧轴向/长度/凸凹筛选。每个签名必须恰好匹配一条边，重复或歧义立即拒绝。
预检不选择、不重建、不保存，返回 selection_sha256；该哈希还绑定文件 SHA、所有边的几何裁剪端点/参数、精确选中边签名、体积、特征历史和 clean 状态。重新枚举顺序不影响哈希。

apply 令 dry_run=false，并提供 expected_selection_sha256、新 receipt_path；检查
全部状态后只选择这些对象，并从原生 SelectionManager 回读数量及 IsSame。
只调用一次 FeatureFillet，194=UniformRadius2+AttachEdges64+KeepFeatures128，
不设置 Propagate1；旧模式默认195不变。请求尺寸不降级，null/异常后不重试。
意图与 returned 分别持久记录；之后 ForceRebuild3、DefaultRadius/Type/IsMultipleRadius、
恰好新增一个 Fillet 特征及单一有效 solid/Check3=0 全部回读。失败保留当前文档和可用
只读状态，不自动撤销或保存。成功仍为 review_required，需调用方另行 STEP、保存和重开验证。

固定数值规范化：毫米9位小数、原生曲线参数12有效数字、体积11有效数字；没有用户
可增大的匹配容差。哈希边界附近的浮点差异可能导致安全拒绝，不能因此自动放宽。
此阶段仅通过离线 mocks/schema；具体 SW2026 SP4 与目标零件的原生结果尚未确认。

### Local edge performance qualification, 2026-10-25

The first full detailed live inventory of the threaded BASE exceeded 180 seconds; no geometry mutation was attempted. Use optional `endpoint_bounds_mm=[xmin,ymin,zmin,xmax,ymax,zmax]` in `solidworks_list_edges` for local inspection. Both trim endpoints must be inside. This is not a bound on the entire curved edge, and cannot be mixed with legacy filters. The operation enumerates GetCurveParams2 once per edge and reads detailed curve/surface geometry only for local candidates.

Exact fillet prepare and apply now require a clean saved working copy. The state hash retains file SHA, all edge trim endpoint/parameter data (excluding packed native curve tags), body validity/volume, feature history, and exact selected signatures. The complete STEP comparison after native execution remains mandatory; this fast state guard is not a substitute for full B-Rep equivalence. The existing 9-decimal mm signature precision is unchanged. Local regression: 101 tests passed. Native local-inspector and fillet qualification remain pending.
