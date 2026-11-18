"""经官方 SOLIDWORKS Visualize Add-in API（2025 FCS 起）同步渲染活动文档的当前视图。

视向、透视与参考几何显示在渲染前设置、渲染后恢复；不重建、不保存文档。
接口为 .NET 双接口，跨进程后期绑定返回 E_NOINTERFACE，必须用类型库早期绑定。
"""
import ctypes
import math
import re
import time
from itertools import product
from pathlib import Path

from scripts.sw_render_view import TOGGLE_HIDE_ALL_TYPES, view_rotation_data

ADDIN_PROGID = "SolidWorks.Visualize.Implementation.VisualizeAddin"
INTERFACES_TLB = "SolidWorks.Visualize.Interfaces.tlb"
IMAGE_FORMATS = {"jpeg": 0, "bmp": 1, "tiff": 2, "png": 3}       # ImageFormat_e
IMAGE_SUFFIXES = {"jpeg": (".jpeg", ".jpg"), "bmp": (".bmp",), "tiff": (".tiff", ".tif"), "png": (".png",)}
TERMINATION_TIME_LIMIT, TERMINATION_QUALITY = 0, 1                 # TerminationMode_e


def validate_render_request(output_dir, job_name, width, height, frame_count, image_format, zoom_box_mm):
    """校验输出位置与渲染参数；返回 (作业目录, 规范化包围盒)。"""
    directory = Path(output_dir)
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("Absolute existing output directory required")
    if type(job_name) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", job_name) is None or job_name in (".", ".."):
        raise ValueError("Safe job name required")
    job_dir = directory / job_name
    if job_dir.exists() or job_dir.is_symlink():
        raise ValueError("Job output folder already exists")
    for value in (width, height):
        if type(value) is not int or not 320 <= value <= 4000:
            raise ValueError("Integer width/height within 320..4000 required")
    if type(frame_count) is not int or not 1 <= frame_count <= 5000:
        raise ValueError("Integer frame_count within 1..5000 required")
    if image_format not in IMAGE_FORMATS:
        raise ValueError("image_format must be png, jpeg, tiff or bmp")
    box = None
    if zoom_box_mm is not None:
        if (not isinstance(zoom_box_mm, (list, tuple)) or len(zoom_box_mm) != 6
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in zoom_box_mm)
                or any(zoom_box_mm[i] >= zoom_box_mm[i + 3] for i in range(3))):
            raise ValueError("Finite nondegenerate model XYZ box required")
        box = [float(v) for v in zoom_box_mm]
    return job_dir, box


def find_interfaces_tlb():
    """从注册表中的类型库登记定位接口类型库；找不到时报错，不猜测路径。"""
    import winreg
    key = r"TypeLib\{2615126C-0ACD-4C09-A4ED-A31DC6A93B14}\1.0\0\win64"
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key) as handle:
            path = Path(winreg.QueryValueEx(handle, None)[0])
    except OSError as exc:
        raise RuntimeError("SOLIDWORKS Visualize interfaces type library is not registered") from exc
    if path.name != INTERFACES_TLB or not path.is_file():
        raise RuntimeError("Registered SOLIDWORKS Visualize type library file is missing")
    return path


def _addin_manager(sw, call):
    """取得早期绑定的 IVisualizeAddinManager；附加模块未启用时明确报错。"""
    import comtypes
    import comtypes.client
    tlb = find_interfaces_tlb()
    addin = call(sw, "GetAddInObject", ADDIN_PROGID)
    if addin is None:
        # 新启动的实例默认不加载；按安装目录中的实现 DLL 完整路径加载（GUID 方式返回 swFileNotFound）。
        dll = tlb.with_name("SolidWorks.Visualize.Implementation.dll")
        if not dll.is_file():
            raise RuntimeError("SOLIDWORKS Visualize add-in DLL is missing")
        call(sw, "LoadAddIn", str(dll))
        addin = call(sw, "GetAddInObject", ADDIN_PROGID)
    if addin is None:
        raise RuntimeError("SOLIDWORKS Visualize add-in is not loaded (Tools > Add-ins)")
    module = comtypes.client.GetModule(str(tlb))
    match = re.search(r"obj at (0x[0-9A-Fa-f]+)", repr(addin._oleobj_))
    if match is None:
        raise RuntimeError("Cannot read the add-in COM pointer")
    unknown = ctypes.cast(int(match.group(1), 16), ctypes.POINTER(comtypes.IUnknown))
    unknown.AddRef()  # 指针由 pywin32 持有；comtypes 释放前须自增引用。
    return unknown.QueryInterface(module.IVisualizeAddin).GetAddinManager()


def run_visualize_render(sw, model, *, process_id, expected_document_path, output_dir, job_name,
                         width=1200, height=1200, frame_count=200, image_format="png",
                         include_alpha=False, denoiser=False, yaw_deg=20.0, pitch_deg=12.0,
                         zoom_box_mm=None, perspective=True, hide_reference_types=True):
    """阻塞渲染一帧并恢复视图状态；返回含耗时与输出文件的报告。"""
    from scripts.sw_cam_feature_sketch import _call_method as call, _double_array, _point
    from scripts.sw_cam_thread import _file_hash
    from scripts.sw_operation_guard import absolute_document_path, _path_identity

    if type(process_id) is not int or process_id <= 0:
        raise ValueError("Exact positive process_id required")
    if not absolute_document_path(expected_document_path) or not Path(expected_document_path).is_file():
        raise ValueError("Exact existing saved document required")
    job_dir, box = validate_render_request(output_dir, job_name, width, height, frame_count, image_format, zoom_box_mm)
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
    manager = _addin_manager(sw, call)
    options = manager.RenderOptions
    extension = model.Extension
    view = model.ActiveView
    if view is None:
        raise ValueError("Active model view required")
    saved = {"hide_all": bool(call(extension, "GetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0)),
             "perspective": bool(call(view, "HasPerspective")), "orientation": view.Orientation3,
             "scale": float(view.Scale2), "translation": view.Translation3}
    saved_options = {name: getattr(options, name) for name in (
        "JobName", "OutputFolder", "ImageFormat", "IncludeAlpha", "Width", "Height",
        "DenoiserEnabled", "TerminationMode", "FrameCount")}
    report = {"status": "error", "job_folder": str(job_dir), "width": width, "height": height,
              "frame_count": frame_count, "image_format": image_format, "include_alpha": bool(include_alpha),
              "denoiser": bool(denoiser), "yaw_deg": float(yaw_deg), "pitch_deg": float(pitch_deg),
              "zoom_box_mm": box, "before": before, "model_saved": False, "model_rebuilt": False,
              "manual_review_required": True}
    try:
        call(model, "ClearSelection2", True)
        if hide_reference_types:
            call(extension, "SetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0, True)
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
        options.JobName = job_name
        options.OutputFolder = str(job_dir.parent)
        options.ImageFormat = IMAGE_FORMATS[image_format]
        options.IncludeAlpha = bool(include_alpha)
        options.Width, options.Height = width, height
        options.DenoiserEnabled = bool(denoiser)
        options.TerminationMode = TERMINATION_QUALITY
        options.FrameCount = frame_count
        started = time.monotonic()
        result = manager.Render()
        report["render_seconds"] = round(time.monotonic() - started, 2)
        report["render_returned"] = bool(result)
        files = sorted(p for p in job_dir.glob("*") if p.is_file()) if job_dir.is_dir() else []
        images = [p for p in files if p.suffix.lower() in IMAGE_SUFFIXES[image_format] and p.stat().st_size > 0]
        report["files"] = [{"path": str(p), "bytes": p.stat().st_size} for p in files]
        if result is not True or len(images) != 1:
            raise RuntimeError("Visualize render did not produce exactly one nonempty image")
        report["image_path"] = str(images[0])
        report["status"] = "ok"
    finally:
        restore_errors = []
        steps = [
            lambda: setattr(view, "Orientation3", saved["orientation"]),
            lambda: (call(view, "AddPerspective") if saved["perspective"] and not call(view, "HasPerspective")
                     else call(view, "RemovePerspective") if not saved["perspective"] and call(view, "HasPerspective") else None),
            lambda: setattr(view, "Scale2", saved["scale"]),
            lambda: setattr(view, "Translation3", saved["translation"]),
            lambda: call(extension, "SetUserPreferenceToggle", TOGGLE_HIDE_ALL_TYPES, 0, saved["hide_all"]),
        ]
        steps += [lambda n=n, v=v: setattr(options, n, v) for n, v in saved_options.items()]
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
