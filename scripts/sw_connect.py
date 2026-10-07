"""
SolidWorks 连接工具
提供连接到 SolidWorks 实例的各种方法
"""
import glob
import os
import re
import tempfile
import time
from pathlib import Path

try:
    from .sw_preflight import ensure_solidworks_installed, import_com_dependencies
except ImportError:
    from sw_preflight import ensure_solidworks_installed, import_com_dependencies

pythoncom, win32com_client, VARIANT = import_com_dependencies()
import pywintypes


DOC_TYPE_MAP = {
    "part": 1,
    "prt": 1,
    "sldprt": 1,
    "assembly": 2,
    "asm": 2,
    "sldasm": 2,
    "drawing": 3,
    "drw": 3,
    "slddrw": 3,
}

DOC_TYPE_LABELS = {
    "part": "零件",
    "assembly": "装配体",
    "drawing": "工程图",
}

DEFAULT_TEMPLATE_PREFS = {
    "part": 8,       # swUserPreferenceStringValue_e.swDefaultTemplatePart
    "assembly": 9,   # swUserPreferenceStringValue_e.swDefaultTemplateAssembly
    "drawing": 10,   # swUserPreferenceStringValue_e.swDefaultTemplateDrawing
}

SW_ALWAYS_USE_DEFAULT_TEMPLATES = 111


class SolidWorksConnectionError(RuntimeError):
    """带阶段和错误码的 SolidWorks 连接错误。"""

    def __init__(self, code, stage, message):
        self.code = code
        self.stage = stage
        super().__init__(f"[{code}] {stage}: {message}")


class _LaunchGuard:
    """跨进程启动互斥；Windows 使用命名 Mutex，其它平台使用独占锁文件。"""

    def __init__(self, name="CADStudio.SolidWorks.Launch"):
        self.name = name
        self.handle = None
        self.path = Path(tempfile.gettempdir()) / "cad-studio-solidworks-launch.lock"
        self._owns_file = False

    def __enter__(self):
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            self.handle = kernel32.CreateMutexW(None, False, self.name)
            if not self.handle:
                raise SolidWorksConnectionError("SW_MUTEX", "locking", "无法创建 SolidWorks 启动互斥锁")
            wait_result = kernel32.WaitForSingleObject(self.handle, 15000)
            if wait_result not in (0, 0x80):
                kernel32.CloseHandle(self.handle)
                self.handle = None
                raise SolidWorksConnectionError("SW_MUTEX_TIMEOUT", "locking", "等待其它启动任务超时")
            return self

        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            self._owns_file = True
        except FileExistsError as exc:
            try:
                stale_pid = int(self.path.read_text(encoding="ascii").strip())
                os.kill(stale_pid, 0)
            except (ProcessLookupError, ValueError):
                self.path.unlink(missing_ok=True)
                return self.__enter__()
            raise SolidWorksConnectionError("SW_MUTEX_BUSY", "locking", "已有 SolidWorks 启动任务") from exc
        return self

    def __exit__(self, *_):
        if os.name == "nt" and self.handle:
            import ctypes

            ctypes.windll.kernel32.ReleaseMutex(self.handle)
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None
        elif self._owns_file:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._owns_file = False


def get_com_member(obj, attr_name, *args):
    """
    兼容 pywin32 中“同一成员在不同环境下可能是属性也可能是方法”的情况。

    参数:
        obj: COM 对象
        attr_name: 成员名称
        *args: 当成员可调用时传入的参数

    返回:
        成员值或调用结果
    """
    member = getattr(obj, attr_name)
    if args:
        return member(*args)
    try:
        return member() if callable(member) else member
    except Exception as exc:
        message = str(exc)
        if "-2147352573" in message or "找不到成员" in message or "Member not found" in message:
            return member
        raise


def safe_get_com_member(obj, attr_name, *args):
    """
    读取 COM 成员，兼容 pywin32 中伪可调用属性。

    保留该别名便于其它模块表达“安全读取”的意图；核心逻辑统一在 get_com_member。
    """
    return get_com_member(obj, attr_name, *args)


def create_empty_dispatch_variant():
    """创建可传给 COM 接口的空 Dispatch 参数。"""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def normalize_doc_type(doc_type):
    """
    规范化文档类型名称。

    参数:
        doc_type: "part"、"assembly"、"drawing" 或常见缩写/扩展名

    返回:
        (name, enum_value) 元组
    """
    key = str(doc_type).strip().lower().lstrip(".")
    enum_value = DOC_TYPE_MAP.get(key)
    if enum_value is None:
        raise ValueError(f"未知文档类型: {doc_type}")

    name_map = {1: "part", 2: "assembly", 3: "drawing"}
    return name_map[enum_value], enum_value


def _expand_path(file_path):
    """展开用户目录和环境变量，并返回绝对路径。"""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(file_path)))


def _ensure_parent_dir(file_path):
    """确保输出文件的父目录存在。"""
    parent = os.path.dirname(_expand_path(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _prog_id_for_version(version):
    """返回 SolidWorks 年份对应的 ProgID。"""
    if version is None:
        return "SldWorks.Application"
    try:
        year = int(version)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SolidWorks 版本必须是年份，例如 2024: {version}") from exc
    if year < 2010 or year > 2035:
        raise ValueError(f"不支持的 SolidWorks 版本年份: {year}")
    return f"SldWorks.Application.{(year - 2000) + 8}"


def _read_active_document(sw):
    """读取活动文档，兼容 COM 属性/方法差异。"""
    try:
        return get_com_member(sw, "ActiveDoc")
    except Exception:
        return None


def _wait_until_ready(sw, timeout_seconds):
    """等待 COM 服务器可读，避免固定 sleep 导致 UI 假死。"""
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    last_error = None
    while time.monotonic() < deadline:
        try:
            get_com_member(sw, "RevisionNumber")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise SolidWorksConnectionError(
        "SW_START_TIMEOUT", "ready", f"SolidWorks 启动超时（{timeout_seconds:.1f}s）: {last_error or 'COM 未就绪'}"
    )


def close_owned_solidworks(sw, started_by_cad_studio):
    """只退出由当前 CAD Studio 会话启动的 SolidWorks 实例。"""
    if not started_by_cad_studio:
        return False
    for member_name in ("ExitApp", "Quit"):
        try:
            member = getattr(sw, member_name)
            member() if callable(member) else None
            return True
        except Exception:
            continue
    return False


def _selected_process_id(process_id):
    """验证显式 PID；未传参时继承当前 MCP 进程的绑定。"""
    if process_id is None:
        value = os.environ.get("SOLIDWORKS_MCP_PROCESS_ID")
        if value is None:
            return None
        if re.fullmatch(r"[1-9][0-9]*", value) is None:
            raise ValueError("SOLIDWORKS_MCP_PROCESS_ID must be a positive decimal integer")
        process_id = int(value)
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
        raise ValueError("process_id must be a positive integer")
    return process_id


def _read_process_id(sw):
    """回读应用进程号，不能把无法验证的代理视为选定实例。"""
    value = get_com_member(sw, "GetProcessID")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("SOLIDWORKS returned an invalid process ID")
    return value


def _application_class_monikers(version=None):
    """从已注册 ProgID 解析应用类 moniker，不硬编码某个安装版本的 CLSID。"""
    names = set()
    prog_ids = ["SldWorks.Application"]
    if version is not None:
        prog_ids.append(_prog_id_for_version(version))
    for prog_id in prog_ids:
        try:
            clsid = str(pywintypes.IID(prog_id)).casefold()
            names.update((clsid, "!" + clsid))
        except pywintypes.com_error:
            # 未注册的版本可以跳过；API 拼写或其它编程错误必须显式报错。
            continue
    return names


def _rot_application_candidates(process_id=None, version=None):
    """仅枚举 SOLIDWORKS 应用 moniker；不绑定文件或其它应用对象。"""
    try:
        rot = pythoncom.GetRunningObjectTable()
        context = pythoncom.CreateBindCtx(0)
        enumerator = rot.EnumRunning()
        exact, aliases = [], []
        class_monikers = _application_class_monikers(version)
        while True:
            batch = enumerator.Next(1)
            if not batch:
                break
            moniker = batch[0]
            try:
                name = str(moniker.GetDisplayName(context, None))
            except Exception:
                continue
            match = re.fullmatch(r"!?(?:SolidWorks|SldWorks)_PID_([1-9][0-9]*)", name, re.IGNORECASE)
            if match:
                advertised_pid = int(match.group(1))
                if process_id is None or advertised_pid == process_id:
                    exact.append((rot, moniker, name, advertised_pid))
            elif (name.casefold() in class_monikers
                  or re.fullmatch(r"!?SldWorks[.]Application(?:[.][0-9]+)?", name, re.IGNORECASE)):
                aliases.append((rot, moniker, name, None))
        return exact + aliases
    except Exception as exc:
        raise SolidWorksConnectionError("SW_ROT_UNAVAILABLE", "attach", f"无法读取运行对象表: {exc}") from exc


def _dispatch_rot_application(rot, moniker):
    """将 ROT 的 IUnknown 明确转换为 IDispatch 后再创建 Python 代理。"""
    unknown = rot.GetObject(moniker)
    dispatch = unknown.QueryInterface(pythoncom.IID_IDispatch)
    return win32com_client.Dispatch(dispatch)


def _connect_process(process_id, version=None):
    """按 PID 只附着现有应用；失败时禁止回退默认实例或启动新进程。"""
    errors = []
    for rot, moniker, name, advertised_pid in _rot_application_candidates(process_id, version):
        try:
            # Dispatch 接收已有 ROT 对象，不传 ProgID，因此不会激活类工厂。
            sw = _dispatch_rot_application(rot, moniker)
            actual_pid = _read_process_id(sw)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if actual_pid != process_id:
            if advertised_pid is not None:
                raise SolidWorksConnectionError(
                    "SW_PROCESS_MISMATCH", "attach",
                    f"ROT 标记 PID {process_id}，应用却返回 PID {actual_pid}；未执行操作",
                )
            continue
        if version is not None:
            try:
                actual_version = get_sw_version(sw)["year"]
            except Exception as exc:
                raise SolidWorksConnectionError("SW_VERSION_UNVERIFIED", "attach", str(exc)) from exc
            if actual_version != int(version):
                raise SolidWorksConnectionError(
                    "SW_VERSION_MISMATCH", "attach",
                    f"PID {process_id} 为 SOLIDWORKS {actual_version}，请求版本为 {version}",
                )
        return sw, name
    detail = "; ".join(errors) or "未找到匹配的应用 moniker"
    raise SolidWorksConnectionError(
        "SW_PROCESS_NOT_FOUND", "attach",
        f"不能附着 SOLIDWORKS PID {process_id}；不会启动或选择其它实例: {detail}",
    )


def list_solidworks_instances():
    """
    只读列出 ROT 中可验证的 SOLIDWORKS 实例，不启动或激活窗口。

    返回:
        字典列表，含 process_id、revision、moniker 和 active_document；
        不包含尚未注册 ROT、无法响应或进程号不符的实例。
    """
    instances = {}
    for rot, moniker, name, advertised_pid in _rot_application_candidates():
        try:
            sw = _dispatch_rot_application(rot, moniker)
            process_id = _read_process_id(sw)
            if advertised_pid is not None and process_id != advertised_pid:
                continue
            if process_id in instances:
                continue
            revision = str(get_com_member(sw, "RevisionNumber"))
            model = _read_active_document(sw)
            document = None
            if model is not None:
                document = {
                    "path": str(get_com_member(model, "GetPathName") or ""),
                    "title": str(get_com_member(model, "GetTitle") or ""),
                    "type": int(get_com_member(model, "GetType")),
                }
            instances[process_id] = {
                "process_id": process_id, "revision": revision,
                "moniker": name, "active_document": document,
            }
        except Exception:
            # 枚举期间退出或尚未就绪的实例不应阻止其它实例的诊断。
            continue
    return [instances[pid] for pid in sorted(instances)]


def connect_solidworks(version=None, wait_seconds=5, visible=True, return_metadata=False, process_id=None):
    """
    连接到 SolidWorks 实例。

    参数:
        version: SolidWorks 版本年份（如 2024），None 则自动检测
        wait_seconds: 默认模式启动新实例后等待秒数
        visible: 仅控制默认模式新启动实例的窗口
        return_metadata: True 时另返回连接来源与进程信息
        process_id: 可选正整数 PID；只附着此现有进程，不启动或回退。
            未传参时继承 SOLIDWORKS_MCP_PROCESS_ID，均未设置则保留默认连接行为。

    返回:
        (sw, model) 元组，model 可能为 None（无打开的文档时）；
        return_metadata=True 时返回 (sw, model, metadata)。
    """
    process_id = _selected_process_id(process_id)
    ensure_solidworks_installed()
    prog_id = _prog_id_for_version(version)
    sw = None
    launched_here = False
    moniker = None

    if process_id is not None:
        sw, moniker = _connect_process(process_id, version)
        print(f"已连接到指定 SolidWorks 实例（PID: {process_id}）")
    else:
        # 默认连接保持原行为；启动和附着共享锁，避免同时拉起实例。
        with _LaunchGuard():
            try:
                sw = win32com_client.GetActiveObject(prog_id)
                print(f"已连接到运行中的 SolidWorks 实例（ProgID: {prog_id}）")
            except Exception as attach_error:
                try:
                    sw = win32com_client.Dispatch(prog_id)
                    launched_here = True
                    try:
                        sw.Visible = visible
                    except Exception:
                        pass
                    print(f"启动了新的 SolidWorks 实例（ProgID: {prog_id}）")
                    _wait_until_ready(sw, wait_seconds)
                except SolidWorksConnectionError:
                    close_owned_solidworks(sw, launched_here)
                    raise
                except Exception as launch_error:
                    close_owned_solidworks(sw, launched_here)
                    raise SolidWorksConnectionError(
                        "SW_LAUNCH_FAILED", "launch", f"无法启动 {prog_id}: {launch_error}; attach={attach_error}"
                    ) from launch_error

    if sw is None:
        raise SolidWorksConnectionError("SW_NO_INSTANCE", "connect", "未获得 SolidWorks COM 实例")

    model = _read_active_document(sw)
    if model:
        doc_types = {1: "零件", 2: "装配体", 3: "工程图"}
        doc_type = get_com_member(model, "GetType")
        title = get_com_member(model, "GetTitle")
        print(f"当前文档: {title} (类型: {doc_types.get(doc_type, '未知')})")
    else:
        print("当前没有打开的文档")

    try:
        actual_process_id = _read_process_id(sw)
    except Exception as exc:
        if process_id is not None:
            raise SolidWorksConnectionError("SW_PROCESS_UNVERIFIED", "connect", str(exc)) from exc
        actual_process_id = None
    if process_id is not None and actual_process_id != process_id:
        raise SolidWorksConnectionError("SW_PROCESS_MISMATCH", "connect", "连接进程号在验证后发生变化")
    metadata = {
        "prog_id": prog_id,
        "requested_version": int(version) if version is not None else None,
        "started_by_cad_studio": launched_here,
        "process_id": actual_process_id,
        "requested_process_id": process_id,
        "moniker": moniker,
    }
    return (sw, model, metadata) if return_metadata else (sw, model)


def get_sw_version(sw):
    """获取 SolidWorks 版本信息。"""
    rev = get_com_member(sw, "RevisionNumber")
    major = int(rev.split(".")[0])
    year = major - 8 + 2000
    return {"revision": rev, "year": year, "major": major}


def find_template(sw, doc_type="part"):
    """
    自动查找 SolidWorks 文档模板。

    参数:
        sw: SolidWorks 应用对象
        doc_type: "part" | "assembly" | "drawing"

    返回:
        模板文件路径字符串
    """
    doc_type, _ = normalize_doc_type(doc_type)

    type_map = {
        "part": (sw.GetUserPreferenceStringValue(DEFAULT_TEMPLATE_PREFS["part"]), "*.prtdot"),
        "assembly": (sw.GetUserPreferenceStringValue(DEFAULT_TEMPLATE_PREFS["assembly"]), "*.asmdot"),
        "drawing": (sw.GetUserPreferenceStringValue(DEFAULT_TEMPLATE_PREFS["drawing"]), "*.drwdot"),
    }

    default_path, pattern = type_map.get(doc_type, type_map["part"])
    if default_path:
        for candidate_root in str(default_path).split(";"):
            candidate_root = _expand_path(candidate_root.strip().strip('"'))
            if not candidate_root:
                continue

            if os.path.isfile(candidate_root):
                return candidate_root

            if os.path.isdir(candidate_root):
                matches = glob.glob(os.path.join(candidate_root, pattern))
                if matches:
                    return matches[0]

    search_dirs = [
        r"C:\ProgramData\SolidWorks\SOLIDWORKS *\templates",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\chinese-simplified",
        r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english",
    ]
    for search_dir in search_dirs:
        matches = glob.glob(os.path.join(os.path.expandvars(search_dir), pattern))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"无法找到 {doc_type} 模板文件，请手动指定路径")


def ensure_default_templates(sw):
    """
    @brief 配置默认模板并关闭新建文件模板选择提示。
    @param sw SolidWorks 应用对象。
    @return 字典，包含已确认的默认模板路径。
    """
    templates = {}
    for doc_type, preference in DEFAULT_TEMPLATE_PREFS.items():
        template_path = find_template(sw, doc_type)
        templates[doc_type] = template_path
        current_path = str(sw.GetUserPreferenceStringValue(preference) or "")
        if _expand_path(current_path) != _expand_path(template_path):
            sw.SetUserPreferenceStringValue(preference, template_path)
    try:
        sw.SetUserPreferenceToggle(SW_ALWAYS_USE_DEFAULT_TEMPLATES, True)
    except Exception as exc:
        print(f"提示: 无法设置始终使用默认模板: {exc}")
    return templates


def snapshot_open_documents(sw):
    """
    快照当前已打开的文档标题集合。

    ISldWorks.GetDocuments 返回当前会话全部打开文档；部分版本在无文档时返回
    None 而非空数组。标题是判定"新建结果"的稳定标识，因为 NewDocument 成功后
    新文档尚未保存，GetPathName 为空字符串，无法用路径区分。
    """
    titles = set()
    try:
        documents = get_com_member(sw, "GetDocuments")
    except Exception:
        return titles
    for document in documents or ():
        try:
            titles.add(str(get_com_member(document, "GetTitle")))
        except Exception:
            continue
    return titles


def _find_new_document(sw, preexisting_titles):
    """
    在新建文档后定位真正的新文档。

    只返回标题不在 preexisting_titles 中的文档。绝不回退到裸 ActiveDoc：
    当 NewDocument 失败或返回 None 时，ActiveDoc 可能是用户先前打开的另一个
    文档，把它当作新建结果会让后续所有特征静默画到错误的文档上。
    """
    try:
        documents = get_com_member(sw, "GetDocuments")
    except Exception:
        return None
    for document in documents or ():
        try:
            title = str(get_com_member(document, "GetTitle"))
        except Exception:
            continue
        if title and title not in preexisting_titles:
            return document
    return None


def new_document(sw, doc_type="part", template_path=None):
    """
    创建新文档。

    参数:
        sw: SolidWorks 应用对象
        doc_type: "part" | "assembly" | "drawing"
        template_path: 模板路径，None 则自动查找

    返回:
        新建的 IModelDoc2 对象

    异常:
        RuntimeError: 无法创建文档。此前的实现会在 NewDocument 返回 None 时
            盲取 sw.ActiveDoc，可能把用户已打开的文档误判为新建结果；现在改为
            按文档标题差集定位，定位不到就显式报错。
    """
    doc_type, _ = normalize_doc_type(doc_type)
    if not template_path:
        template_path = find_template(sw, doc_type)
    else:
        template_path = _expand_path(template_path)

    preexisting_titles = snapshot_open_documents(sw)

    model = sw.NewDocument(template_path, 0, 0, 0)
    if model is not None:
        # 正常路径：NewDocument 直接返回文档。仍需确认它确实是新文档，
        # 避免个别版本返回陈旧引用。
        try:
            if str(get_com_member(model, "GetTitle")) in preexisting_titles:
                model = None
        except Exception:
            pass

    if model is None:
        # 退化路径：NewDocument 返回 None 时，按标题差集轮询新文档。
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            model = _find_new_document(sw, preexisting_titles)
            if model is not None:
                break
            time.sleep(0.25)

    if model is None:
        raise RuntimeError(
            f"创建{DOC_TYPE_LABELS.get(doc_type, doc_type)}文档失败：SolidWorks 未返回新文档。"
            f"请确认模板可用（{template_path}）且未弹出模态对话框阻塞自动化。"
        )

    print(f"已创建新{DOC_TYPE_LABELS.get(doc_type, doc_type)}文档")
    return model


def open_document(sw, file_path, read_only=False, silent=False, raise_on_error=False):
    """
    打开已有文档。

    参数:
        sw: SolidWorks 应用对象
        file_path: 文件完整路径
        read_only: 是否以只读模式打开
        silent: 是否静默打开
        raise_on_error: 打开失败时是否抛出异常

    返回:
        IModelDoc2 对象
    """
    file_path = _expand_path(file_path)
    if not os.path.exists(file_path):
        message = f"文件不存在: {file_path}"
        if raise_on_error:
            raise FileNotFoundError(message)
        print(message)
        return None

    # 装配体会把组件文档加载到当前会话；再次 OpenDoc6 可能返回
    # swFileWithSameTitleAlreadyOpen。复用同一路径对象也能保留文档所有权。
    try:
        existing_model = sw.GetOpenDocumentByName(file_path)
    except Exception:
        existing_model = None
    if existing_model is not None:
        print(f"已复用打开文档: {file_path}")
        return existing_model

    ext = os.path.splitext(file_path)[1].lower()
    foreign_exts = {".step", ".stp", ".igs", ".iges"}
    type_map = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}

    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    options = 2 if read_only else 0  # swOpenDocOptions_ReadOnly = 2
    if silent:
        options |= 1  # swOpenDocOptions_Silent = 1

    if ext in foreign_exts:
        if read_only:
            print("提示: LoadFile4 导入外来 CAD 文件时不支持 read_only，已忽略该参数")
        if silent:
            print("提示: LoadFile4 导入外来 CAD 文件时不支持 OpenDoc6 silent 选项，已忽略该参数")
        ensure_default_templates(sw)
        import_data = sw.GetImportFileData(file_path)
        if import_data is None:
            message = f"获取导入数据失败: {file_path}"
            if raise_on_error:
                raise RuntimeError(message)
            print(message)
            return None
        # 非 DXF/DWG、非 Pro/E 外来文件应传 "r"，表示导入为新的 SolidWorks 文档；
        # 空字符串会在部分 SW2024 环境中弹出模板选择对话框并阻塞自动化。
        try:
            model = sw.LoadFile4(file_path, "r", import_data, errors)
        except TypeError:
            # SW2026 的 makepy 强类型代理会对 LoadFile4 的 [out] long
            # 再执行 int(VARIANT)，与 OpenDoc6 的已知问题相同。动态代理
            # 可以正确保留 by-ref 错误码，同时继续复用已取得的导入选项。
            ole_object = getattr(sw, "_oleobj_", None)
            if ole_object is None:
                raise
            dynamic_sw = win32com_client.dynamic.DumbDispatch(ole_object, "SldWorks.Application")
            model = dynamic_sw.LoadFile4(file_path, "r", import_data, errors)
        warnings.value = 0
    else:
        doc_type = type_map.get(ext, 1)
        try:
            model = sw.OpenDoc6(file_path, doc_type, options, "", errors, warnings)
        except TypeError:
            # SW2024 的 makepy 强类型代理可能对 [out] long 再做 int(VARIANT)，
            # 动态代理会把显式 by-ref VARIANT 正确传给原生 OpenDoc6。
            ole_object = getattr(sw, "_oleobj_", None)
            if ole_object is None:
                raise
            dynamic_sw = win32com_client.dynamic.DumbDispatch(ole_object, "SldWorks.Application")
            model = dynamic_sw.OpenDoc6(file_path, doc_type, options, "", errors, warnings)
        if isinstance(model, (tuple, list)):
            values = list(model)
            model = values[0] if values else None
            if len(values) > 1 and values[1] is not None:
                errors.value = int(values[1])
            if len(values) > 2 and values[2] is not None:
                warnings.value = int(values[2])
    if model:
        print(f"已打开: {file_path}")
    else:
        message = f"打开失败, 错误码: {errors.value}, 警告码: {warnings.value}"
        if raise_on_error:
            raise RuntimeError(message)
        print(message)
    return model


def save_document(model, file_path=None):
    """
    保存文档。

    参数:
        model: IModelDoc2 对象
        file_path: 另存为路径，None 则保存到当前位置

    返回:
        bool 成功/失败
    """
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

    if file_path:
        file_path = _expand_path(file_path)
        _ensure_parent_dir(file_path)
        success = model.Extension.SaveAs(
            file_path, 0, 1, create_empty_dispatch_variant(), errors, warnings
        )
    else:
        success = model.Save3(1, errors, warnings)

    if success:
        print(f"保存成功: {file_path or get_com_member(model, 'GetPathName')}")
    else:
        print(f"保存失败, 错误码: {errors.value}, 警告码: {warnings.value}")
    return bool(success)


def mm(value):
    """毫米转米（SolidWorks API 单位）。"""
    return value / 1000.0


def deg(value):
    """角度转弧度。"""
    import math
    return value * math.pi / 180.0
