"""CAM 安装清单的隔离注册表与文件系统回归测试。"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.sw_cam_installation as cam


CLSID = "{11111111-2222-3333-4444-555555555555}"
LIBID = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"


class FakeKey:
    def __init__(self, hive, path, view):
        self.hive, self.path, self.view = hive, path.lower(), view

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeRegistry:
    """只实现只读接口；任何未知字段读取会使测试失败。"""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_WOW64_64KEY = 256
    KEY_WOW64_32KEY = 512
    allowed_values = {"", "DisplayName", "DisplayVersion", "Publisher", "InstallLocation",
                      "Title", "Description", "CodeBase"}

    def __init__(self):
        self.data = {}
        self.denied = set()
        self.queries = []

    def add(self, path, values, *, hive="HKLM", view="64"):
        self.data[(hive, view, path.lower())] = values

    def OpenKey(self, hive, path, _reserved=0, access=0):
        view = "32" if access & self.KEY_WOW64_32KEY else "64"
        assert access == self.KEY_READ | (self.KEY_WOW64_32KEY if view == "32" else self.KEY_WOW64_64KEY)
        path = path.lower()
        if (hive, view, path) in self.denied:
            raise PermissionError(path)
        if not any(h == hive and v == view and (p == path or p.startswith(path + "\\"))
                   for h, v, p in self.data):
            raise FileNotFoundError(path)
        return FakeKey(hive, path, view)

    def QueryValueEx(self, key, name):
        assert name in self.allowed_values, "禁止读取许可证、序列号或其它未授权字段"
        self.queries.append((key.path, name))
        values = self.data.get((key.hive, key.view, key.path), {})
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], 1

    def _children(self, key):
        prefix = key.path + "\\"
        return sorted({p[len(prefix):].split("\\")[0] for h, v, p in self.data
                       if h == key.hive and v == key.view and p.startswith(prefix)})

    def QueryInfoKey(self, key):
        return len(self._children(key)), 0, 0

    def EnumKey(self, key, index):
        return self._children(key)[index]


def add_install(registry, root, *, year="2031", view="64", clsid=CLSID):
    registry.add(cam._UNINSTALL + "\\cam" + year,
                 {"DisplayName": "SOLIDWORKS CAM " + year, "DisplayVersion": year + ".1",
                  "InstallLocation": str(root), "Publisher": "Vendor",
                  "SerialNumber": "DO_NOT_READ", "LicenseKey": "DO_NOT_READ"}, view=view)
    registry.add(r"SOFTWARE\SOLIDWORKS\SOLIDWORKS " + year + "\\Addins\\" + clsid,
                 {"Title": "SOLIDWORKS CAM " + year, "Description": "Powered by CAMWorks"}, view=view)
    key = cam._CLASSES + "\\CLSID\\" + clsid
    registry.add(key, {"": "CAMWorks Add-in"}, view=view)
    registry.add(key + "\\ProgID", {"": "ActualVendor.ExactAddin.7"}, view=view)
    registry.add(key + "\\InprocServer32", {"": str(root / "CAMWorksAddin.dll")}, view=view)
    return key


def test_exact_registration_and_artifact_paths(tmp_path):
    """真实注册关联决定 ProgID；类型库和帮助路径仅来自存在的文件。"""
    registry = FakeRegistry()
    root = tmp_path / "custom-install"
    root.mkdir()
    (root / "CAMWorksAddin.dll").write_bytes(b"MZ")
    (root / "camworks.tlb").write_bytes(b"MSFT")
    help_dir = root / "Lang" / "English"
    help_dir.mkdir(parents=True)
    (help_dir / "swcamapihelp.chm").write_bytes(b"ITSF")
    key = add_install(registry, root)
    registry.add(key + "\\TypeLib", {"": LIBID})
    registry.add(cam._CLASSES + "\\TypeLib\\" + LIBID + "\\2.0", {"": "CAM API"})
    registry.add(cam._CLASSES + "\\TypeLib\\" + LIBID + "\\2.0\\0\\win64", {"": str(root / "camworks.tlb")})

    result = cam.discover_cam_installations(registry=registry)

    assert result["installed"] is True
    assert result["licensed"] is None and result["license_status"] == "not_checked"
    assert result["com_activated"] is False
    assert result["com_registrations"][0]["progid"] == "ActualVendor.ExactAddin.7"
    library = result["com_registrations"][0]["type_libraries"][0]
    assert library["libid"] == LIBID and library["paths"][0]["exists"]
    artifacts = result["installation_candidates"][0]["artifacts"]
    assert artifacts["type_libraries"] == [str(root / "camworks.tlb")]
    assert artifacts["help_files"] == [str(help_dir / "swcamapihelp.chm")]
    assert result["errors"] == [] and result["complete"]
    assert "DO_NOT_READ" not in json.dumps(result)


def test_multiple_versions_are_not_silently_selected(tmp_path):
    """两个安装和注册表视图必须分别保留，不能默认选最新版本。"""
    registry = FakeRegistry()
    for year, view, clsid in [("2028", "32", CLSID), ("2031", "64", LIBID)]:
        root = tmp_path / year
        root.mkdir()
        (root / "CAMWorksAddin.dll").write_bytes(b"MZ")
        add_install(registry, root, year=year, view=view, clsid=clsid)

    result = cam.discover_cam_installations(registry=registry)

    assert len(result["installation_candidates"]) == 2
    assert result["requires_selection"] and result["selected_installation"] is None
    assert {x["view"] for x in result["addin_registrations"]} == {"32", "64"}


def test_override_scans_only_explicit_directory(tmp_path, monkeypatch):
    """目录覆盖不触发其它版本的文件树扫描，也不伪造 COM 注册。"""
    registry = FakeRegistry()
    other = tmp_path / "other"
    other.mkdir()
    add_install(registry, other)
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    (chosen / "camworks.tlb").write_bytes(b"MSFT")
    original = cam._file_inventory
    scanned = []

    def record(root, errors):
        scanned.append(root)
        return original(root, errors)

    monkeypatch.setattr(cam, "_file_inventory", record)
    result = cam.discover_cam_installations(chosen, registry=registry)

    assert scanned == [chosen]
    assert len(result["installation_candidates"]) == 2
    assert not result["requires_selection"]
    assert result["selected_installation"] is None
    assert result["install_path_override"] == str(chosen)


def test_stale_registration_does_not_mean_installed_or_licensed(tmp_path):
    """只有注册表残留不等于存在可用安装，更不等于有授权。"""
    registry = FakeRegistry()
    add_install(registry, tmp_path / "missing")
    result = cam.discover_cam_installations(registry=registry)
    assert result["installation_registered"]
    assert result["installed"] is False and result["licensed"] is None
    assert result["installation_candidates"][0]["directory_exists"] is False


def test_access_denied_is_reported_without_hiding_other_evidence(tmp_path):
    """无权访问的注册表视图必须报告，并保留其它成功读取结果。"""
    registry = FakeRegistry()
    root = tmp_path / "CAM"
    root.mkdir()
    (root / "camworks.tlb").write_bytes(b"MSFT")
    registry.denied.add(("HKLM", "64", cam._UNINSTALL.lower()))
    result = cam.discover_cam_installations(root, registry=registry)
    assert result["installed"]
    assert not result["complete"]
    assert result["errors"][0]["code"] == "REGISTRY_READ_FAILED"
    assert result["errors"][0]["error_type"] == "PermissionError"


def test_empty_directory_and_unrelated_product_are_not_cam(tmp_path):
    """空目录、无关程序及许可证管理器不能证明 CAM 已安装。"""
    registry = FakeRegistry()
    registry.add(cam._UNINSTALL + r"\unrelated", {"DisplayName": "Other CAD", "InstallLocation": str(tmp_path)})
    registry.add(cam._UNINSTALL + r"\license", {"DisplayName": "CAMWorks License Manager", "SerialNumber": "DO_NOT_READ"})
    result = cam.discover_cam_installations(tmp_path, registry=registry)
    assert not result["installed"] and not result["installation_registered"]
    assert result["uninstall_entries"] == []


def test_progid_only_is_discovered_and_unregistered_coclass_is_not_invented(tmp_path):
    """缺少 Addins 时仍可读取真实 ProgID 注册；不得从 TLB 猜 CLSID。"""
    registry = FakeRegistry()
    registry.add(cam._CLASSES + r"\CAMWorksAddin.MWAddin.1\CLSID", {"": CLSID})
    registry.add(cam._CLASSES + "\\CLSID\\" + CLSID, {"": "CAMWorks Addin"})
    registry.add(cam._CLASSES + "\\CLSID\\" + CLSID + "\\ProgID", {"": "CAMWorksAddin.MWAddin.1"})
    result = cam.discover_cam_installations(registry=registry)
    assert len(result["com_registrations"]) == 1
    assert result["com_registrations"][0]["clsid"] == CLSID
    assert result["addin_registrations"] == []
    assert not result["installed"]


def test_file_limit_and_missing_progid_are_explicit(tmp_path, monkeypatch):
    """扫描上限必须可见，缺失的 ProgID 必须保持空值。"""
    registry = FakeRegistry()
    add_install(registry, tmp_path)
    del registry.data[("HKLM", "64", (cam._CLASSES + "\\CLSID\\" + CLSID + "\\ProgID").lower())]
    (tmp_path / "camworks.tlb").write_bytes(b"MSFT")
    (tmp_path / "z.txt").write_text("data")
    monkeypatch.setattr(cam, "_MAX_FILES", 1)
    result = cam.discover_cam_installations(tmp_path, registry=registry)
    assert result["com_registrations"][0]["progid"] is None
    assert result["complete"] is False
    assert any(x["code"] == "FILE_SCAN_TRUNCATED" for x in result["errors"])
