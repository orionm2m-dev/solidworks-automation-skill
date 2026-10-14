# 原生圆截面路径与机械导入（pilot）

这些工具使用本机 SOLIDWORKS PIA，不执行调用方代码。每次操作都要求保存的目标文档完整路径和宿主 MCP 选定的 PID；通过宿主操作锁串行化。不运行新的 SOLIDWORKS 实例。

- `solidworks_inspect_native_geometry`：读取实体名称、体积、包围盒和组件变换。
- `solidworks_build_round_sweeps`：在空的已保存零件中建立圆截面原生扫描。路径是 2 点直线或 3–6 点 Bezier；JSON 数值经验证后转换为方程，不接受任意表达式。可建立独立矩形拉伸。先 `dry_run=true`。要求毫米单位，检查路径实测长度、矩形包围盒和重建。不会自动保存。
- `solidworks_import_step_part`：导入到新的多实体 SLDPRT；恢复全局导入选项，拒绝覆盖，返回每个实体供审查。原始目标文档不保存。
- `solidworks_replace_component_preserving_transform`：只支持唯一的固定实例；保持变换和其他组件引用，不保存。
- `solidworks_exclude_reviewed_bodies`：按已审查的精确实体名称建立 DeleteBody 特征，保留原始导入历史，不保存。

## 规格

```json
{"sweeps":[{"name":"Wire1","control_points_mm":[[0,0,0],[0,3,0],[3,5,0],[5,5,0]],"diameter_mm":0.9,"color":[1,0,0]}],"boxes":[]}
```

失败可能留下未保存的部分特征，必须审查，不能盲目重试。不会覆盖或删除既有特征。模型仅提供几何，不证明线束工艺、压接适配、绝缘性能、拉脱力或原生 SOLIDWORKS Routing 许可证。

验证：输入拒绝测试不启动 CAD；真实 SOLIDWORKS 版本和操作证据应单独记录。当前能力为 pilot，发布前需几何与视觉复核。