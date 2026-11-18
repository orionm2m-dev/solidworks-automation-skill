"""单视角展示渲染：透视、自定义视向、隐藏参考几何、纯色背景，导出高分辨率位图。

只改视图与显示首选项，导出后逐项恢复；不重建、不保存文档。
"""
import math
from itertools import product
from pathlib import Path

# 本机 swconst.tlb 核对过的枚举值。
TOGGLE_HIDE_ALL_TYPES = 198          # swViewDisplayHideAllTypes（文档级）
TOGGLE_REALVIEW = 814                # swDisplayRealViewGraphics（应用级，只读回）
TOGGLE_AMBIENT_OCCLUSION = 485       # swDisplayAmbientOcclusionShadows（应用级）
TOGGLE_SHADOWS = 131                 # swDisplayShadowsInShadedMode（应用级）
INT_ANTIALIASING = 445               # swSystemOptionDisplayAntiAliasing
INT_BACKGROUND_APPEARANCE = 305      # swColorsBackgroundAppearance
INT_VIEWPORT_BACKGROUND = 99         # swSystemColorsViewportBackground
ANTIALIASING_FULL_SCENE = 3
BACKGROUND_PLAIN = 0
COMMAND_REALVIEW = 499               # swCommands_RealviewGraphics
DISPLAY_MODES = {"shaded": 4, "shaded_with_edges": 5}


def view_rotation_data(yaw_deg, pitch_deg):
    """返回 MathTransform 的 16 元数组：相机右偏 yaw、俯视 pitch（度）。"""
    for value in (yaw_deg, pitch_deg):
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 180:
            raise ValueError("Finite yaw/pitch within ±180 degrees required")
    t, p = math.radians(yaw_deg), math.radians(pitch_deg)
    ry = [[math.cos(t), 0.0, -math.sin(t)], [0.0, 1.0, 0.0], [math.sin(t), 0.0, math.cos(t)]]
    rx = [[1.0, 0.0, 0.0], [0.0, math.cos(p), -math.sin(p)], [0.0, math.sin(p), math.cos(p)]]
    m = [[sum(rx[i][k] * ry[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    # SOLIDWORKS 按行存放各模型轴在视图坐标中的像，即模型→视图矩阵的转置。
    return [m[j][i] for i in range(3) for j in range(3)] + [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def _validate(output_path, width, height, zoom_box_mm, background_rgb, display_mode):
    path = Path(output_path)
    if not path.is_absolute() or path.suffix.lower() not in (".png", ".bmp"):
        raise ValueError("Absolute .png or .bmp output path required")
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("Output file must be new with an existing parent directory")
    for value in (width, height):
        if type(value) is not int or not 320 <= value <= 8000:
            raise ValueError("Integer width/height within 320..8000 required")
    box = None
    if zoom_box_mm is not None:
        if (not isinstance(zoom_box_mm, (list, tuple)) or len(zoom_box_mm) != 6
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in zoom_box_mm)
                or any(zoom_box_mm[i] >= zoom_box_mm[i + 3] for i in range(3))):
            raise ValueError("Finite nondegenerate model XYZ box required")
        box = [float(v) for v in zoom_box_mm]
    if (not isinstance(background_rgb, (list, tuple)) or len(background_rgb) != 3
            or any(type(v) is not int or not 0 <= v <= 255 for v in background_rgb)):
        raise ValueError("background_rgb requires three integers within 0..255")
    if display_mode not in DISPLAY_MODES:
        raise ValueError("display_mode must be shaded or shaded_with_edges")
    return path, box


def run_render_view(sw, model, *, process_id, expected_document_path, output_path,
                    width=3200, height=2000, yaw_deg=20.0, pitch_deg=12.0, zoom_box_mm=None,
                    perspective=True, display_mode="shaded", background_rgb=(255, 255, 255),
                    hide_reference_types=True, shadows=True, ambient_occlusion=True, realview=True):
    """导出一张展示位图并恢复全部视图状态；返回逐项回读的报告。"""
    from scripts.sw_cam_feature_sketch import _call_method as call, _double_array, _point
    from scripts.sw_cam_thread import _file_hash
    from scripts.sw_operation_guard import absolute_document_path, _path_identity

    if type(process_id) is not int or process_id <= 0:
        raise ValueError("Exact positive process_id required")
    if not absolute_document_path(expected_document_path) or not Path(expected_document_path).is_file():
        raise ValueError("Exact existing saved document required")
    path, box = _validate(output_path, width, height, zoom_box_mm, background_rgb, display_mode)
    rotation = view_rotation_data(yaw_deg, pitch_deg)

    def guard():
        if call(sw, "GetProcessID") != process_id:
            raise ValueError("SOLIDWORKS process changed")
        active = sw.ActiveDoc
        if (active is None or call(sw, "IsSame", active, model) != 1
                or _path_identity(call(model, "GetPathName")) != _path_identity(expected_document_path)
                or call(model, "GetType") not in (1, 2)):
            raise ValueError("Active saved part/assembly identity changed")
        return {"needs_save": bool(call(model, "GetSaveFlag")), "file_sha256": _file_hash(expected_document_path)}

    before = guard()
    extension = model.Extension
    view = model.ActiveView
    if view is None:
        raise ValueError("Active model view required")
    app_toggles = (TOGGLE_AMBIENT_OCCLUSION, TOGGLE_SHADOWS)
    app_integers = (INT_ANTIALIASING, INT_BACKGROUND_APPEARANCE, INT_VIEWPORT_BACKGROUND)
    saved = {
        "hide_all": bool(call(extension, "GetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0)),
        "toggles": {i: bool(call(sw, "GetUserPreferenceToggle", i)) for i in app_toggles},
        "integers": {i: int(call(sw, "GetUserPreferenceIntegerValue", i)) for i in app_integers},
        "realview": bool(call(sw, "GetUserPreferenceToggle", TOGGLE_REALVIEW)),
        "display_mode": int(view.DisplayMode), "perspective": bool(call(view, "HasPerspective")),
        "orientation": view.Orientation3, "scale": float(view.Scale2), "translation": view.Translation3,
    }
    report = {"status": "error", "output_path": str(path), "width": width, "height": height,
              "yaw_deg": float(yaw_deg), "pitch_deg": float(pitch_deg), "zoom_box_mm": box,
              "display_mode": display_mode, "background_rgb": list(background_rgb),
              "before": before, "model_saved": False, "model_rebuilt": False, "manual_review_required": True}
    realview_toggled = False
    bitmap = path.with_suffix(".bmp")
    if bitmap.exists():
        raise ValueError("Intermediate bitmap path already exists")
    try:
        call(model, "ClearSelection2", True)
        if hide_reference_types:
            call(extension, "SetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0, True)
        call(sw, "SetUserPreferenceToggle", TOGGLE_SHADOWS, bool(shadows))
        call(sw, "SetUserPreferenceToggle", TOGGLE_AMBIENT_OCCLUSION, bool(ambient_occlusion))
        call(sw, "SetUserPreferenceIntegerValue", INT_ANTIALIASING, ANTIALIASING_FULL_SCENE)
        call(sw, "SetUserPreferenceIntegerValue", INT_BACKGROUND_APPEARANCE, BACKGROUND_PLAIN)
        red, green, blue = background_rgb
        call(sw, "SetUserPreferenceIntegerValue", INT_VIEWPORT_BACKGROUND, red | (green << 8) | (blue << 16))
        if bool(realview) != saved["realview"]:
            # 该开关只能经命令切换；显卡不支持时回读保持原值，如实报告。
            call(sw, "RunCommand", COMMAND_REALVIEW, "")
            realview_toggled = bool(call(sw, "GetUserPreferenceToggle", TOGGLE_REALVIEW)) != saved["realview"]
        view.DisplayMode = DISPLAY_MODES[display_mode]
        if perspective and not saved["perspective"]:
            call(view, "AddPerspective")
        elif not perspective and saved["perspective"]:
            call(view, "RemovePerspective")
        utility = call(sw, "GetMathUtility")
        transform = call(utility, "CreateTransform", _double_array(rotation))
        if transform is None:
            raise ValueError("CreateTransform returned null")
        view.Orientation3 = transform
        if box is None:
            call(model, "ViewZoomtofit2")
        else:
            orientation = view.Orientation3
            points = [_point(utility, [v / 1000.0 for v in corner], orientation)
                      for corner in product(*[(box[i], box[i + 3]) for i in range(3)])]
            region = [min(p[i] for p in points) for i in range(3)] + [max(p[i] for p in points) for i in range(3)]
            if any(region[i] >= region[i + 3] for i in (0, 1)):
                raise ValueError("Degenerate projected zoom region")
            call(model, "ViewZoomTo2", *region)
        call(model, "ClearSelection2", True)
        call(model, "GraphicsRedraw2")
        guard()
        report["applied"] = {
            "hide_all_types": bool(call(extension, "GetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0)),
            "shadows": bool(call(sw, "GetUserPreferenceToggle", TOGGLE_SHADOWS)),
            "ambient_occlusion": bool(call(sw, "GetUserPreferenceToggle", TOGGLE_AMBIENT_OCCLUSION)),
            "realview": bool(call(sw, "GetUserPreferenceToggle", TOGGLE_REALVIEW)),
            "perspective": bool(call(view, "HasPerspective")), "display_mode": int(view.DisplayMode)}
        result = call(model, "SaveBMP", str(bitmap), width, height)
        if result is not True or not bitmap.is_file() or bitmap.stat().st_size == 0:
            raise RuntimeError("SaveBMP did not produce a nonempty image")
        if path.suffix.lower() == ".png":
            from PIL import Image
            with Image.open(bitmap) as image:
                image.convert("RGB").save(path)
            bitmap.unlink()
        report["bytes"] = path.stat().st_size
        report["status"] = "ok"
    finally:
        # 逐项恢复；恢复失败单独记录，不能掩盖原始异常。
        restore_errors = []
        steps = [
            lambda: setattr(view, "Orientation3", saved["orientation"]),
            lambda: (call(view, "AddPerspective") if saved["perspective"] and not call(view, "HasPerspective")
                     else call(view, "RemovePerspective") if not saved["perspective"] and call(view, "HasPerspective") else None),
            lambda: setattr(view, "Scale2", saved["scale"]),
            lambda: setattr(view, "Translation3", saved["translation"]),
            lambda: setattr(view, "DisplayMode", saved["display_mode"]),
            lambda: call(extension, "SetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0, saved["hide_all"]),
            lambda: call(sw, "RunCommand", COMMAND_REALVIEW, "") if realview_toggled else None,
        ]
        steps += [lambda i=i, v=v: call(sw, "SetUserPreferenceToggle", i, v) for i, v in saved["toggles"].items()]
        steps += [lambda i=i, v=v: call(sw, "SetUserPreferenceIntegerValue", i, v) for i, v in saved["integers"].items()]
        steps.append(lambda: call(model, "GraphicsRedraw2"))
        for step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - 恢复必须继续执行其余步骤
                restore_errors.append(f"{type(exc).__name__}: {exc}")
        report["restore_errors"] = restore_errors
        try:
            after = guard()
            report["after"] = after
            report["saved_file_unchanged"] = after["file_sha256"] == before["file_sha256"]
        except Exception as exc:  # noqa: BLE001
            report["after_error"] = f"{type(exc).__name__}: {exc}"
    if report["restore_errors"] or report.get("saved_file_unchanged") is not True:
        report["status"] = "warn"
    return report
