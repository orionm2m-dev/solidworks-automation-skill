"""SOLIDWORKS CAM 安装清单：只读注册表与文件元数据，不激活 COM 或检查许可证。"""
from __future__ import annotations

import ntpath
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


_CAM_NAME = re.compile(r"\b(?:solid\s*works\s+cam|camworks)\b", re.IGNORECASE)
_GUID = re.compile(r"^\{[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\}$", re.IGNORECASE)
_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_CLASSES = r"SOFTWARE\Classes"
_MAX_KEYS = 20000
_MAX_FILES = 12000
_MAX_DEPTH = 6


def _path_key(path: str | Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))


def _inside(path: str, root: str) -> bool:
    try:
        return ntpath.commonpath([_path_key(path), _path_key(root)]) == _path_key(root)
    except ValueError:
        return False


def _file_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = os.path.expandvars(value.strip())
    if value.lower().startswith("file:"):
        parsed = urlparse(value)
        value = unquote(parsed.path)
        if parsed.netloc:
            value = "//" + parsed.netloc + value
        elif re.match(r"^/[A-Za-z]:", value):
            value = value[1:]
    elif value.startswith('"'):
        match = re.match(r'^"([^"]+)"', value)
        return match.group(1) if match else None
    else:
        match = re.match(r"^(.+?\.(?:dll|exe|ocx))(?=\s|$)", value, re.IGNORECASE)
        if match:
            value = match.group(1)
    return value


class _RegistryReader:
    """只查询固定白名单值，不枚举许可证或序列号字段。"""

    def __init__(self, registry: Any, errors: list[dict[str, Any]]) -> None:
        self.registry = registry
        self.errors = errors
        self.hives = {
            "HKLM": registry.HKEY_LOCAL_MACHINE,
            "HKCU": registry.HKEY_CURRENT_USER,
        }
        self.views = [("64", registry.KEY_WOW64_64KEY), ("32", registry.KEY_WOW64_32KEY)]

    def _error(self, exc: OSError, hive: str, key: str, view: str, operation: str) -> None:
        if isinstance(exc, FileNotFoundError) or getattr(exc, "winerror", None) in (2, 3):
            return
        self.errors.append({"code": "REGISTRY_READ_FAILED", "operation": operation,
                            "hive": hive, "key": key, "view": view,
                            "error_type": type(exc).__name__, "winerror": getattr(exc, "winerror", None)})

    def values(self, hive: str, key: str, view: str, names: tuple[str, ...]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        flag = dict(self.views)[view]
        try:
            with self.registry.OpenKey(self.hives[hive], key, 0, self.registry.KEY_READ | flag) as handle:
                for name in names:
                    try:
                        value = self.registry.QueryValueEx(handle, name)[0]
                        if isinstance(value, (str, int)):
                            result[name] = value
                    except OSError as exc:
                        self._error(exc, hive, key, view, "query_value")
        except OSError as exc:
            self._error(exc, hive, key, view, "open_key")
        return result

    def children(self, hive: str, key: str, view: str) -> list[str]:
        result: list[str] = []
        flag = dict(self.views)[view]
        try:
            with self.registry.OpenKey(self.hives[hive], key, 0, self.registry.KEY_READ | flag) as handle:
                count = self.registry.QueryInfoKey(handle)[0]
                if count > _MAX_KEYS:
                    self.errors.append({"code": "REGISTRY_SCAN_TRUNCATED", "hive": hive,
                                        "key": key, "view": view, "limit": _MAX_KEYS})
                for index in range(min(count, _MAX_KEYS)):
                    try:
                        result.append(self.registry.EnumKey(handle, index))
                    except OSError as exc:
                        self._error(exc, hive, key, view, "enum_key")
                        break
        except OSError as exc:
            self._error(exc, hive, key, view, "open_key")
        return sorted(result, key=str.casefold)


def _typelib_registration(reader: _RegistryReader, hive: str, view: str, libid: str) -> list[dict[str, Any]]:
    result = []
    root = _CLASSES + "\\TypeLib\\" + libid
    for version in reader.children(hive, root, view):
        key = root + "\\" + version
        name = reader.values(hive, key, view, ("",)).get("")
        help_dir = reader.values(hive, key + "\\HELPDIR", view, ("",)).get("")
        paths = []
        for locale in reader.children(hive, key, view):
            if not re.fullmatch(r"[0-9a-f]+", locale, re.IGNORECASE):
                continue
            for architecture in ("win32", "win64"):
                value = reader.values(hive, key + "\\" + locale + "\\" + architecture, view, ("",)).get("")
                if value:
                    path = _file_path(value)
                    paths.append({"locale": locale, "architecture": architecture,
                                  "registered_value": value, "path": path,
                                  "exists": bool(path and Path(path).is_file())})
        result.append({"libid": libid, "version": version, "name": name,
                       "help_directory": help_dir, "hive": hive, "view": view,
                       "registry_key": key, "paths": paths})
    return result


def _com_registrations(reader: _RegistryReader, clsid: str, view: str) -> list[dict[str, Any]]:
    result = []
    key = _CLASSES + "\\CLSID\\" + clsid
    for hive in reader.hives:
        name = reader.values(hive, key, view, ("",)).get("")
        children = reader.children(hive, key, view)
        if name is None and not children:
            continue
        progid = reader.values(hive, key + "\\ProgID", view, ("",)).get("")
        version_independent = reader.values(hive, key + "\\VersionIndependentProgID", view, ("",)).get("")
        inproc = reader.values(hive, key + "\\InprocServer32", view, ("", "CodeBase"))
        local = reader.values(hive, key + "\\LocalServer32", view, ("",)).get("")
        libid = reader.values(hive, key + "\\TypeLib", view, ("",)).get("")
        servers = []
        for kind, value in (("inproc", inproc.get("")), ("codebase", inproc.get("CodeBase")), ("local", local)):
            if value:
                path = _file_path(value)
                servers.append({"kind": kind, "registered_value": value, "path": path,
                                "exists": bool(path and Path(path).is_file())})
        libraries = []
        if isinstance(libid, str) and _GUID.fullmatch(libid):
            # 类型库可能由机器或用户级安装注册；保留每一条来源，禁止混为一个版本。
            for lib_hive in reader.hives:
                libraries.extend(_typelib_registration(reader, lib_hive, view, libid))
        result.append({"clsid": clsid, "name": name, "progid": progid,
                       "version_independent_progid": version_independent,
                       "hive": hive, "view": view, "registry_key": key,
                       "servers": servers, "typelib_id": libid, "type_libraries": libraries})
    return result


def _registry_inventory(reader: _RegistryReader) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    installs, addins, com = [], [], []
    seeds: set[tuple[str, str]] = set()
    for view, _flag in reader.views:
        for hive in reader.hives:
            for child in reader.children(hive, _UNINSTALL, view):
                key = _UNINSTALL + "\\" + child
                name = reader.values(hive, key, view, ("DisplayName",)).get("DisplayName", "")
                if not _CAM_NAME.search(str(name)) or re.search(r"licen[cs]", str(name), re.IGNORECASE):
                    continue
                values = reader.values(hive, key, view, ("DisplayVersion", "Publisher", "InstallLocation"))
                installs.append({"display_name": name, "display_version": values.get("DisplayVersion"),
                                 "publisher": values.get("Publisher"),
                                 "install_path": _file_path(values.get("InstallLocation")),
                                 "hive": hive, "view": view, "registry_key": key})
            sw_root = r"SOFTWARE\SOLIDWORKS"
            addin_roots = [sw_root + r"\Addins"]
            for child in reader.children(hive, sw_root, view):
                if re.match(r"^SOLIDWORKS(?:\s|$)", child, re.IGNORECASE):
                    addin_roots.append(sw_root + "\\" + child + "\\Addins")
            for root in addin_roots:
                for child in reader.children(hive, root, view):
                    if not _GUID.fullmatch(child):
                        continue
                    key = root + "\\" + child
                    values = reader.values(hive, key, view, ("Title", "Description"))
                    if not _CAM_NAME.search(" ".join(str(x) for x in values.values())):
                        continue
                    addins.append({"clsid": child, "title": values.get("Title"),
                                   "description": values.get("Description"), "hive": hive,
                                   "view": view, "registry_key": key})
                    seeds.add((child.upper(), view))
            # 只用真实 ProgID -> CLSID 注册关系补充候选，绝不从文件名猜类标识。
            for child in reader.children(hive, _CLASSES, view):
                if not re.match(r"^(?:CAMWorks|SWCAM)[A-Za-z0-9_.]*$", child, re.IGNORECASE):
                    continue
                clsid = reader.values(hive, _CLASSES + "\\" + child + "\\CLSID", view, ("",)).get("")
                if isinstance(clsid, str) and _GUID.fullmatch(clsid):
                    seeds.add((clsid.upper(), view))
    for clsid, view in sorted(seeds):
        com.extend(_com_registrations(reader, clsid, view))
    for addin in addins:
        addin["com_registrations"] = [entry for entry in com
                                      if entry["clsid"].upper() == addin["clsid"].upper()
                                      and entry["view"] == addin["view"]]
    return installs, addins, com


def _file_inventory(root: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    artifacts: dict[str, Any] = {"type_libraries": [], "help_files": [], "api_binaries": [], "scan_complete": True}
    if not root.is_dir():
        return artifacts
    seen = 0

    def on_error(exc: OSError) -> None:
        artifacts["scan_complete"] = False
        errors.append({"code": "FILE_SCAN_FAILED", "path": str(getattr(exc, "filename", root)),
                       "error_type": type(exc).__name__})

    for current, dirs, files in os.walk(root, followlinks=False, onerror=on_error):
        depth = len(Path(current).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if not Path(current, d).is_symlink()
                         and not (hasattr(Path, "is_junction") and Path(current, d).is_junction()))
        if depth >= _MAX_DEPTH and dirs:
            dirs[:] = []
            artifacts["scan_complete"] = False
        for name in sorted(files):
            seen += 1
            if seen > _MAX_FILES:
                artifacts["scan_complete"] = False
                errors.append({"code": "FILE_SCAN_TRUNCATED", "path": str(root), "limit": _MAX_FILES})
                return artifacts
            lower = name.lower()
            path = str(Path(current, name))
            if lower.endswith((".tlb", ".olb")):
                artifacts["type_libraries"].append(path)
            elif (lower.endswith((".chm", ".hxs")) and ("cam" in lower or "api" in lower)) or ("api" in lower and lower.endswith((".pdf", ".html", ".htm"))):
                artifacts["help_files"].append(path)
            elif lower.startswith(("cwapi", "cwaddin", "camworks", "swcam")) and lower.endswith(".dll"):
                if not re.search(r"licen[cs]", lower):
                    artifacts["api_binaries"].append(path)
    return artifacts


def discover_cam_installations(install_path: str | os.PathLike[str] | None = None, *, registry: Any | None = None) -> dict[str, Any]:
    """只读发现 CAM 安装、插件注册及帮助文件；不连接 SOLIDWORKS、不判断授权。

    参数:
        install_path: 可选的显式安装目录，仅对此目录做文件扫描，不隐式选择其它版本。
        registry: 可选的 winreg 兼容对象，供隔离测试注入；默认使用 Windows 注册表。
    返回:
        JSON 可序列化清单。多版本全部保留；installed 仅表示找到 CAM 安装文件，
        licensed 始终为 None。注册表错误与截断独立报告，不宣称完整或已获许可证。
    """
    errors: list[dict[str, Any]] = []
    if registry is None:
        try:
            import winreg as registry
        except ImportError:
            errors.append({"code": "WINDOWS_REGISTRY_UNAVAILABLE"})
    installs, addins, registrations = _registry_inventory(_RegistryReader(registry, errors)) if registry is not None else ([], [], [])
    roots: dict[str, dict[str, Any]] = {}

    def add_root(path: str, source: str) -> None:
        key = _path_key(path)
        roots.setdefault(key, {"install_path": path, "sources": []})
        if source not in roots[key]["sources"]:
            roots[key]["sources"].append(source)

    for entry in installs:
        if entry["install_path"]:
            add_root(entry["install_path"], "uninstall_registry")
    for entry in registrations:
        for server in entry["servers"]:
            path = server["path"]
            if not path or any(_inside(path, value["install_path"]) for value in roots.values()):
                continue
            name = ntpath.basename(path).lower()
            if server["kind"] == "codebase" or name not in {"mscoree.dll", "mscoreei.dll", "combase.dll", "ole32.dll", "rundll32.exe"}:
                add_root(str(Path(path).parent), "com_server_registry")
    override = os.fspath(install_path) if install_path is not None else None
    if override is not None:
        if not override.strip():
            raise ValueError("install_path must not be empty")
        add_root(override, "explicit_install_path")
    candidates = []
    for key, candidate in sorted(roots.items()):
        path = candidate["install_path"]
        candidate["directory_exists"] = Path(path).is_dir()
        candidate["uninstall_entries"] = [x for x in installs if x["install_path"] and _path_key(x["install_path"]) == key]
        candidate["com_registrations"] = [x for x in registrations if any(s["path"] and _inside(s["path"], path) for s in x["servers"])]
        candidate["file_scan_performed"] = override is None or _path_key(override) == key
        candidate["artifacts"] = _file_inventory(Path(path), errors) if candidate["file_scan_performed"] else None
        artifacts = candidate["artifacts"] or {}
        evidence = list(artifacts.get("api_binaries", []))
        evidence.extend(p for p in artifacts.get("type_libraries", []) if ntpath.basename(p).lower() == "camworks.tlb")
        evidence.extend(s["path"] for c in candidate["com_registrations"] for s in c["servers"] if s["exists"] and _inside(s["path"], path))
        candidate["installed_evidence"] = sorted(set(evidence))
        candidate["installed"] = bool(evidence)
        candidates.append(candidate)
    return {"schema_version": 1, "read_only": True, "com_activated": False,
            "artifact_interpretation": "File candidates only; no type library or executable loaded.",
            "installed": any(c["installed"] for c in candidates),
            "installation_registered": bool(installs or addins or registrations),
            "licensed": None, "license_status": "not_checked",
            "install_path_override": override, "selected_installation": None,
            "requires_selection": len(candidates) > 1 and override is None,
            "installation_candidates": candidates, "uninstall_entries": installs,
            "addin_registrations": addins, "com_registrations": registrations,
            "complete": not errors and all(c["artifacts"] is None or c["artifacts"]["scan_complete"] for c in candidates),
            "errors": errors}
