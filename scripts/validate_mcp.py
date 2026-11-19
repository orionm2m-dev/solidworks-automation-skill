"""
验证 SolidWorks MCP Server 的协议层可用性。

该脚本不调用 SolidWorks COM 工具，只启动本地 stdio MCP server 检查三种表面：
- `default`：不设置 `SW_MCP_DISCOVERY` / `SW_MCP_APPROVAL`，不安装网关，原生命名工具全部可见；
- `full`：安装网关的完整模式，原生命名工具全部可见，不暴露发现入口；
- `search`：安装网关的发现模式，只暴露三个发现入口，且每个必需工具都能按名称检索并读到 Schema。

另外检查打包注册表（`bundle`）：在不设置网关变量的环境中，`build_smithery_mcpb.py`
读到的 search 工具卡恰好是三个发现入口，full 工具卡包含全部必需工具；以及服务端输入
校验用的螺纹库类型与 `scripts/sw_thread_feature.py` 一致（只解析源码，不导入 COM 模块）。

适合在提交前或 CI 中发现 schema/注册错误。
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "mcp-server" / "server.py"
THREAD_FEATURE_PATH = ROOT / "scripts" / "sw_thread_feature.py"
DISCOVERY_TOOLS = {"sw_search_tools", "sw_describe_tool", "sw_call_tool"}

REQUIRED_TOOLS = {
    "solidworks_read_resume_checkpoint",
    "solidworks_inspect_open_documents",
    "solidworks_cleanup_part_transfer",
    "solidworks_finalize_part_transfer",
    "solidworks_qualify_part_transfer",
    "solidworks_qualify_reference_copy",
    "solidworks_inspect_native_assembly",
    "solidworks_audit_native_animation",
    "solidworks_cam_installation",
    "solidworks_cam_status",
    "solidworks_cam_load_addin",
    "solidworks_cam_inspect_turning",
    "solidworks_cam_inspect_turn_stock",
    "solidworks_cam_define_turn_stock",
    "solidworks_cam_set_turn_machine",
    "solidworks_cam_inspect_machining",
    "solidworks_cam_run_qualification_step",
    "solidworks_cam_prepare_toolpath_job",
    "solidworks_cam_job_status",
    "solidworks_cam_stop_observation",
    "solidworks_cam_inspect_operation",
    "solidworks_cam_inspect_operation_profile",
    "solidworks_cam_inspect_turn_variable_allowance",
    "solidworks_cam_qualify_turn_variable_allowance",
    "solidworks_cam_configure_turn_tool",
    "solidworks_cam_configure_turn_tool_dimensions",
    "solidworks_cam_configure_turn_holder_dimensions",
    "solidworks_cam_qualify_turn_holder_stl",
    "solidworks_cam_qualify_turn_holder_write_through",
    "solidworks_recover_owned_process",
    "solidworks_cam_inspect_qualification_context",
    "solidworks_cam_qualify_thread_operation",
    "solidworks_cam_qualify_turn_feature",
    "solidworks_cam_configure_turn_feature_attribute",
    "solidworks_cam_inspect_turn_feature_recipe",
    "solidworks_cam_qualify_turn_feature_recipe",
    "solidworks_cam_reconcile_turn_feature_recipe",
    "solidworks_cam_reorder_turn_operations",
    "solidworks_cam_inspect_turn_bore_options",
    "solidworks_cam_inspect_turn_cutoff_options",
    "solidworks_cam_probe_turn_post_parameter",
    "solidworks_cam_inspect_turn_tool_contours",
    "solidworks_cam_inspect_turn_setup_context",
    "solidworks_cam_qualify_turn_reverse_setup",
    "solidworks_cam_qualify_turn_feature_copy",
    "solidworks_cam_qualify_turn_feature_plan_append",
    "solidworks_reconcile_owned_startup",
    "solidworks_cam_qualify_feature_operation_plan",
    "solidworks_cam_configure_thread_pitch",
    "solidworks_cam_inspect_material_catalogue",
    "solidworks_cam_configure_apt_controller",
    "solidworks_cam_qualify_mill_feature_units",
    "solidworks_cam_create_profile_sketch",
    "solidworks_cam_qualify_thread_postprocess",
    "solidworks_cam_qualify_turn_apt_postprocess",
    "solidworks_cam_export_generic_cl",
    "solidworks_cam_export_mill_generic_cl",
    "solidworks_cam_configure_mill_qualification",
    "solidworks_cam_inspect_current_saved_compound",
    "solidworks_cam_inspect_operation_geometry",
    "solidworks_cam_configure_mill_stock",
    "solidworks_cam_inspect_thread_records",
    "solidworks_cam_inspect_thread_tool",
    "solidworks_cam_inspect_thread_feature_attributes",
    "solidworks_cam_configure_cutting_conditions",
    "solidworks_cam_document_lifecycle",
    "solidworks_cam_inspect_thread_operation",
    "solidworks_cam_save_prompt",
    "solidworks_cam_run_simulation",
    "solidworks_cam_preview_simulation",
    "solidworks_cam_export_geometry",
    "solidworks_inspect_reference_planes",
    "solidworks_inspect_native_geometry",
    "solidworks_build_round_sweeps",
    "solidworks_import_step_part",
    "solidworks_replace_component_preserving_transform",
    "solidworks_exclude_reviewed_bodies",
    "solidworks_set_face_appearance",
    "solidworks_add_face_decal",
    "solidworks_clear_decals",
    "cadstudio_read_artifact",
    "cadstudio_resolve_backend",
    "cadstudio_write_open_format",
    "cadstudio_build_dxf_preview_scene",
    "cadstudio_check_dfm",
    "cadstudio_check_drc",
    "cadstudio_list_drc_rules",
    "cadstudio_check_routing",
    "cadstudio_routing_preflight",
    "solidworks_addin_host_status",
    "cadstudio_fea_preflight",
    "cadstudio_prepare_fea",
    "cadstudio_run_fea",
    "cadstudio_run_fea_convergence",
    "cadstudio_review_advanced_geometry",
    "cadstudio_create_ocp_loft",
    "cadstudio_create_ocp_surface",
    "solidworks_health_check",
    "solidworks_lookup_api",
    "solidworks_recover",
    "solidworks_cancel_featureworks_prompt",
    "solidworks_connect",
    "solidworks_new_document",
    "solidworks_create_basic_part",
    "solidworks_open_document",
    # 建模工具：这些是机械工程师实际画零件用的入口，回归保护必须覆盖。
    "solidworks_sketch_and_extrude",
    "solidworks_revolve",
    "solidworks_fillet",
    "solidworks_chamfer",
    "solidworks_shell",
    "solidworks_pattern",
    "solidworks_mirror_feature",
    "solidworks_list_edges",
    # 几何自检工具：机械设计必须能回读实测尺寸和质量。
    "solidworks_mass_properties",
    "solidworks_bounding_box",
    "solidworks_interference_check",
    "solidworks_document_units",
    # 规格驱动建模：可版本控制、幂等、自带验证。
    "design_spec_validate",
    "design_spec_build",
    "solidworks_add_component",
    "solidworks_set_component_fixed",
    "solidworks_list_component_transforms",
    "solidworks_set_component_transform",
    "solidworks_set_component_visibility",
    "solidworks_save_component_copy",
    "solidworks_set_component_suppression",
    "solidworks_reorganize_components",
    "solidworks_delete_components",
    "solidworks_list_circular_edges",
    "solidworks_add_thread_feature",
    "solidworks_save_document",
    "solidworks_close_documents",
    "solidworks_add_coincident_mate",
    "solidworks_add_distance_mate",
    "solidworks_add_concentric_mate",
    "solidworks_set_appearance",
    "solidworks_export_active",
    "solidworks_inspect_configurations",
    "solidworks_create_configuration",
    "solidworks_activate_configuration",
    "solidworks_update_dimension",
    "solidworks_inspect_capsule_sketch",
    "solidworks_resize_capsule_sketch",
    "solidworks_set_custom_properties",
    "solidworks_batch_export_files",
    "solidworks_export_assembly_bom",
    "solidworks_pack_and_go",
    "solidworks_review_active",
    "solidworks_create_hole_feature",
    "solidworks_inspect_hole_features",
    "solidworks_add_rotary_motor",
    "solidworks_inspect_motion_studies",
    "solidworks_validate_motion_study",
    "solidworks_generate_drawing",
    "solidworks_review_drawing",
    "solidworks_inspect_drawing",
}


def _configure_stdio_utf8() -> None:
    """在 Windows 旧代码页下尽量使用 UTF-8 输出中文提示。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _server_env(mode: str) -> dict[str, str]:
    if mode == "default":
        # 默认表面：去掉网关变量，按客户端未做任何配置时的状态启动。
        return {key: value for key, value in os.environ.items()
                if key not in {"SW_MCP_DISCOVERY", "SW_MCP_APPROVAL"}}
    return {
        **os.environ,
        "SW_MCP_DISCOVERY": mode,
        "SW_MCP_APPROVAL": "auto",
        "SW_MCP_APPROVAL_DIR": os.path.join(tempfile.gettempdir(), "sw-mcp-validate-approvals"),
    }


async def _with_session(mode: str, check) -> str:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(ROOT),
        env=_server_env(mode),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await check(session)


async def _check_named_tools(session: ClientSession, label: str) -> str:
    names = {tool.name for tool in (await session.list_tools()).tools}
    if names & DISCOVERY_TOOLS:
        raise AssertionError(f"{label}不应暴露发现入口: {sorted(names & DISCOVERY_TOOLS)}")
    missing = sorted(REQUIRED_TOOLS - names)
    if missing:
        raise AssertionError(f"{label}缺少工具: " + ", ".join(missing))
    return f"{label} {len(names)} 个工具可见。"


async def _check_default(session: ClientSession) -> str:
    return await _check_named_tools(session, "默认模式")


async def _check_full(session: ClientSession) -> str:
    return await _check_named_tools(session, "完整模式")


async def _check_search(session: ClientSession) -> str:
    listed = {tool.name for tool in (await session.list_tools()).tools}
    if listed != DISCOVERY_TOOLS:
        raise AssertionError(f"发现模式应只暴露 {sorted(DISCOVERY_TOOLS)}，实际 {sorted(listed)}")

    for name in sorted(REQUIRED_TOOLS):
        found = await session.call_tool("sw_search_tools", {"query": name, "limit": 5})
        if found.isError:
            raise AssertionError(f"检索 {name} 失败: {found.content[0].text}")
        payload = json.loads(found.content[0].text)
        hits = [item["name"] for item in payload["results"]]
        if name not in hits:
            raise AssertionError(f"按名称检索不到 {name}，实际候选: {hits}")

        described = await session.call_tool("sw_describe_tool", {"name": name})
        if described.isError:
            raise AssertionError(f"读取 {name} 的 Schema 失败: {described.content[0].text}")
        detail = json.loads(described.content[0].text)
        if detail.get("name") != name or not detail.get("inputSchema"):
            raise AssertionError(f"{name} 的 describe 结果不完整: {detail}")

    return f"发现模式 3 个入口，{len(REQUIRED_TOOLS)} 个必需工具均可按名称检索并读取 Schema。"


# 打包脚本在独立进程中导入 server；只输出最后一行 JSON，避免导入期日志干扰解析。
_BUNDLE_PROBE = """
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from scripts.build_smithery_mcpb import collect_tool_cards
print(json.dumps({mode: [card["name"] for card in collect_tool_cards(root, mode)] for mode in ("search", "full")}))
"""


def _check_bundle() -> str:
    """@brief 打包注册表不能随运行时网关变量变化，否则发布包缺少工具卡。"""
    completed = subprocess.run(
        [sys.executable, "-c", _BUNDLE_PROBE, str(ROOT)],
        cwd=str(ROOT), env=_server_env("default"), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    if completed.returncode != 0:
        raise AssertionError("读取打包注册表失败: " + completed.stderr.strip()[-2000:])
    lines = completed.stdout.strip().splitlines()
    if not lines:
        raise AssertionError("读取打包注册表没有输出")
    cards = json.loads(lines[-1])
    search, full = set(cards["search"]), set(cards["full"])
    if search != DISCOVERY_TOOLS:
        raise AssertionError(f"打包 search 工具卡应为 {sorted(DISCOVERY_TOOLS)}，实际 {sorted(search)}")
    if full & DISCOVERY_TOOLS:
        raise AssertionError(f"打包 full 工具卡不应包含发现入口: {sorted(full & DISCOVERY_TOOLS)}")
    missing = sorted(REQUIRED_TOOLS - full)
    if missing:
        raise AssertionError("打包 full 工具卡缺少工具: " + ", ".join(missing))
    return f"打包注册表 search {len(search)} 张、full {len(full)} 张工具卡。"


def _module_constant(path: Path, name: str) -> object:
    """@brief 从源码读取顶层字面量常量，不导入模块（螺纹模块导入时会加载 COM 依赖）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} 中找不到常量 {name}")


def _check_thread_types() -> str:
    """@brief 服务端输入校验的螺纹库类型副本必须与后端模块一致。"""
    backend = tuple(_module_constant(THREAD_FEATURE_PATH, "THREAD_TYPES"))
    server = tuple(_module_constant(SERVER_PATH, "_THREAD_TYPES"))
    if backend != server:
        raise AssertionError(f"server.py 的 _THREAD_TYPES {server} 与 sw_thread_feature.THREAD_TYPES {backend} 不一致")
    return f"螺纹库类型与后端一致（{len(backend)} 种）。"


async def _main(mode: str) -> int:
    """执行 MCP 工具清单检查。"""
    if not SERVER_PATH.exists():
        raise FileNotFoundError(f"找不到 MCP Server: {SERVER_PATH}")
    print("MCP 验证通过: " + _check_thread_types())
    if mode in ("all", "bundle"):
        print("MCP 验证通过: " + _check_bundle())
    if mode in ("all", "default"):
        print("MCP 验证通过: " + await _with_session("default", _check_default))
    if mode in ("all", "both", "full"):
        print("MCP 验证通过: " + await _with_session("full", _check_full))
    if mode in ("all", "both", "search"):
        print("MCP 验证通过: " + await _with_session("search", _check_search))
    return 0


if __name__ == "__main__":
    _configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="校验 SolidWorks MCP 的 tools/list 表面")
    parser.add_argument("--mode", choices=("all", "both", "bundle", "default", "full", "search"), default="all",
                        help="校验哪种模式（默认 all：bundle、default、full、search；both：full 和 search；"
                             "bundle：打包注册表）")
    options = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_main(options.mode)))
    except Exception as exc:
        print(f"MCP 验证失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
