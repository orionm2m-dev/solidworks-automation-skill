"""CAM native probe safety tests; all CAD interfaces are isolated fakes."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam as cam

CLSID = "{CCAC6208-0E19-6455-2022-2026CEB541FA}"
OTHER_CLSID = "{00000000-0000-0000-0000-000000000001}"
ADDIN_PATH = r"D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS CAM\cwaddinu.dll"


class Model:
    def __init__(self):
        self.path = r"C:\job\owned-part.sldprt"
        self.title = "owned-part.sldprt"
        self.dirty = False

    def GetPathName(self):
        return self.path

    def GetTitle(self):
        return self.title

    def GetType(self):
        return 1

    def GetSaveFlag(self):
        return self.dirty

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected model API: {name}")


class App:
    def __init__(self):
        self.GetVersion = Mock(return_value="2026")
        self.GetServicePack = Mock(return_value="4.1")
        self.GetBuildDate = Mock(return_value="2026-06-19")
        self.GetIsCAMWorksInDemoMode = Mock(return_value=False)
        self.forbidden = []

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"Unexpected CAM API: {name}")


class SolidWorks:
    def __init__(self, addin=None, model=None):
        self.ActiveDoc = model
        self.GetAddInObject = Mock(return_value=addin)
        self.LoadAddIn = Mock(side_effect=AssertionError("Unexpected add-in load"))
        self.forbidden = []

    def __getattr__(self, name):
        self.forbidden.append(name)
        raise AssertionError(f"Unexpected SOLIDWORKS API: {name}")


def installed_inventory(*, com_registrations=None):
    result = {
        "addin_registrations": [{"clsid": CLSID, "title": "SOLIDWORKS CAM 2026",
                                  "hive": "HKLM", "view": "64"}],
        "com_registrations": [{"clsid": CLSID, "hive": "HKLM", "view": "64",
                               "progid": "CAMWorksAddin.MWAddin.1",
                               "servers": [{"kind": "inproc", "path": ADDIN_PATH,
                                            "exists": True}]}],
    }
    if com_registrations is not None:
        result["com_registrations"] = com_registrations
    return result


def ready(model=None):
    app = App()
    addin = SimpleNamespace(GetCWApp=Mock(return_value=app))
    return SolidWorks(addin=addin, model=model), app


def test_unloaded_probe_does_not_load_create_or_activate_anything():
    sw = SolidWorks()
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] == "unavailable"
    assert result["reason"] == "CAM_ADDIN_NOT_LOADED"
    assert result["turning_entitlement"] == "unknown"
    assert result["document_before"] is None
    assert result["active_document_unchanged"] is True
    sw.GetAddInObject.assert_called_once_with(CLSID)
    sw.LoadAddIn.assert_not_called()
    assert sw.forbidden == []


def test_null_cam_bridge_is_not_reported_as_api_success():
    bridge = Mock(return_value=None)
    sw = SolidWorks(SimpleNamespace(GetCWApp=bridge))
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] == "unavailable"
    assert result["addin_available"] is True
    assert result["api_available"] is False
    assert result["reason"] == "CAM_API_OBJECT_UNAVAILABLE"
    bridge.assert_called_once_with()
    sw.LoadAddIn.assert_not_called()


def test_success_uses_only_documented_application_getters_and_owned_sw():
    model = Model()
    sw, app = ready(model)
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] == "ok"
    assert result["demo_mode"] is False
    assert result["turning_entitlement"] == "unknown"
    assert result["license_activation_attempted"] is False
    assert result["model_saved"] is False
    assert result["document_before"] == result["document_after"]
    assert app.forbidden == []  # No Module, GetLicenseEnabled, ICreateDocument, etc.
    assert sw.forbidden == []  # No alternate instance lookup, activation or save.
    for name in ("GetVersion", "GetServicePack", "GetBuildDate", "GetIsCAMWorksInDemoMode"):
        getattr(app, name).assert_called_once_with()


class SecretComError(Exception):
    hresult = -2147467259


def test_partial_getter_failure_preserves_other_evidence_and_redacts_error_text():
    sw, app = ready()
    app.GetServicePack.side_effect = SecretComError("SECRET_LICENSE_IDENTIFIER")
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] == "partial"
    assert result["service_pack"] is None
    assert result["version"] == "2026"
    assert result["demo_mode"] is False
    assert result["issues"][0]["stage"] == "GetServicePack"
    assert result["issues"][0]["hresult"] == SecretComError.hresult
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)


@pytest.mark.parametrize("stage", ["GetAddInObject", "GetCWApp"])
def test_failed_native_entrypoint_is_sanitized_without_fallback_creation(stage):
    sw, app = ready()
    if stage == "GetAddInObject":
        sw.GetAddInObject.side_effect = SecretComError("SECRET_LICENSE_IDENTIFIER")
    else:
        sw.GetAddInObject.return_value.GetCWApp.side_effect = SecretComError("SECRET_LICENSE_IDENTIFIER")
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] == "unavailable"
    assert result["issues"][0]["stage"] == stage
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)
    sw.LoadAddIn.assert_not_called()
    app.GetVersion.assert_not_called()


@pytest.mark.parametrize("change", ["dirty", "path", "active_document"])
def test_probe_detects_document_changes_even_when_all_app_getters_succeed(change):
    model = Model()
    sw, app = ready(model)

    def mutate_and_read():
        if change == "dirty":
            model.dirty = True
        elif change == "path":
            model.path = r"C:\other\foreign-part.sldprt"
        else:
            sw.ActiveDoc = None
        return "2026"

    app.GetVersion.side_effect = mutate_and_read
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] == "error"
    assert result["reason"] == "CAM_DOCUMENT_STATE_CHANGED"
    assert result["active_document_unchanged"] is False


@pytest.mark.parametrize("bad", [None, "", "CAMWorksAddin.MWAddin.1", ADDIN_PATH,
                                  CLSID.strip("{}"), OTHER_CLSID])
def test_registration_selector_rejects_non_guid_or_undiscovered_target(bad):
    with pytest.raises(ValueError):
        cam.select_registration(installed_inventory(), bad)


def test_registration_selector_accepts_case_insensitive_registered_clsid():
    selected = cam.select_registration(installed_inventory(), CLSID.lower())
    assert selected["clsid"].casefold() == CLSID.casefold()


def test_registration_selector_rejects_conflicting_hkcu_server_for_same_clsid():
    inventory = installed_inventory()
    inventory["com_registrations"].append({
        "clsid": CLSID, "hive": "HKCU", "view": "64",
        "progid": "CAMWorksAddin.MWAddin.1",
        "servers": [{"kind": "inproc", "path": r"C:\unexpected\cwaddinu.dll", "exists": True}],
    })
    with pytest.raises(ValueError):
        cam.select_registration(inventory, CLSID)


def test_registration_selector_allows_identical_discovery_duplicates():
    inventory = installed_inventory()
    inventory["addin_registrations"].append(dict(inventory["addin_registrations"][0]))
    selected = cam.select_registration(inventory, CLSID)
    assert selected["clsid"].casefold() == CLSID.casefold()


def test_explicit_load_is_idempotent_when_addin_is_already_loaded():
    sw, _app = ready()
    result = cam.load_cam_addin(sw, CLSID, addin_path=ADDIN_PATH)
    assert result["status"] == "ok"
    assert result["load_attempted"] is False
    sw.LoadAddIn.assert_not_called()


def test_explicit_load_uses_verified_dll_path_then_reads_same_clsid():
    app = App()
    bridge = SimpleNamespace(GetCWApp=Mock(return_value=app))
    sw = SolidWorks()
    sw.GetAddInObject.side_effect = [None, bridge]
    sw.LoadAddIn = Mock(return_value=0)
    result = cam.load_cam_addin(sw, CLSID, addin_path=ADDIN_PATH)
    sw.LoadAddIn.assert_called_once_with(ADDIN_PATH)
    assert all(call.args == (CLSID,) for call in sw.GetAddInObject.call_args_list)
    assert result["load_attempted"] is True
    assert result["api_available"] is True
    assert result["turning_entitlement"] == "unknown"


def test_load_return_code_alone_does_not_claim_api_or_license_success():
    sw = SolidWorks()
    sw.LoadAddIn = Mock(return_value=0)
    result = cam.load_cam_addin(sw, CLSID, addin_path=ADDIN_PATH)
    assert result["status"] == "unavailable"
    assert result["api_available"] is False
    assert result["turning_entitlement"] == "unknown"


def test_load_compares_document_state_from_before_loading_not_only_after():
    model = Model()
    app = App()
    sw = SolidWorks(model=model)
    sw.GetAddInObject.side_effect = [None, SimpleNamespace(GetCWApp=Mock(return_value=app))]

    def load(_path):
        model.dirty = True
        return 0

    sw.LoadAddIn = Mock(side_effect=load)
    result = cam.load_cam_addin(sw, CLSID, addin_path=ADDIN_PATH)
    assert result["status"] == "error"
    assert result["reason"] == "CAM_DOCUMENT_STATE_CHANGED"
    assert result["active_document_unchanged"] is False


def test_document_snapshot_failure_is_not_silently_claimed_unchanged():
    sw, app = ready(Model())
    sw.ActiveDoc.GetSaveFlag = Mock(side_effect=SecretComError("SECRET_LICENSE_IDENTIFIER"))
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] in {"error", "unavailable"}
    assert result.get("active_document_unchanged") is not True
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)
    app.GetVersion.assert_not_called()


def test_registration_selector_rejects_conflicting_progid_for_same_server():
    inventory = installed_inventory()
    row = dict(inventory["com_registrations"][0])
    row["hive"] = "HKCU"
    row["progid"] = "Unrelated.Server.1"
    inventory["com_registrations"].append(row)
    with pytest.raises(ValueError):
        cam.select_registration(inventory, CLSID)


def test_registration_selector_requires_existing_registered_inproc_server():
    inventory = installed_inventory()
    inventory["com_registrations"][0]["servers"][0]["exists"] = False
    with pytest.raises(ValueError):
        cam.select_registration(inventory, CLSID)


def test_after_snapshot_failure_is_sanitized_and_not_marked_unchanged():
    sw, _app = ready(Model())
    sw.ActiveDoc.GetSaveFlag = Mock(side_effect=[False, SecretComError("SECRET_LICENSE_IDENTIFIER")])
    result = cam.inspect_cam(sw, CLSID)
    assert result["status"] in {"error", "unavailable"}
    assert result.get("active_document_unchanged") is not True
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)


def test_load_exception_is_sanitized_without_retry_or_fallback():
    sw = SolidWorks()
    sw.LoadAddIn = Mock(side_effect=SecretComError("SECRET_LICENSE_IDENTIFIER"))
    result = cam.load_cam_addin(sw, CLSID, addin_path=ADDIN_PATH)
    assert result["status"] in {"error", "unavailable"}
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)
    sw.LoadAddIn.assert_called_once_with(ADDIN_PATH)
    assert sw.forbidden == []


class CallableDispatchModel(Model):
    """pywin32 dispatch values can look callable without being getter methods."""
    def __init__(self):
        super().__init__()
        self._oleobj_ = object()
        self.default_invocations = 0

    def __call__(self, *args):
        self.default_invocations += 1
        raise AssertionError("IDispatch default member must not be invoked")


def test_member_returns_callable_dispatch_property_without_default_invoke():
    model = CallableDispatchModel()
    sw = SolidWorks(model=model)
    assert cam._member(sw, "ActiveDoc") is model
    assert cam.document_snapshot(sw)["path"] == model.path
    assert model.default_invocations == 0


def test_member_still_calls_explicit_getter_and_indexed_method():
    item = object()
    getter = Mock(return_value=item)
    indexed = Mock(return_value=item)
    target = SimpleNamespace(GetCWApp=getter, Item=indexed)
    assert cam._member(target, "GetCWApp") is item
    assert cam._member(target, "Item", 2) is item
    getter.assert_called_once_with()
    indexed.assert_called_once_with(2)


def turning_fixture(monkeypatch, *, machine_type=1, count=2, setup_count=0, op_setup_count=0):
    model = Model()
    chosen = object()
    machine = SimpleNamespace(
        MachType=machine_type,
        IGetEnumSetups=Mock(return_value=SimpleNamespace(Count=setup_count)),
        IGetEnumOpSetups=Mock(return_value=SimpleNamespace(Count=op_setup_count)),
    )
    part = SimpleNamespace(IGetMachine=Mock(return_value=machine))
    candidates = SimpleNamespace(Count=count, Item=Mock(return_value=chosen))
    doc = SimpleNamespace(GetDocType=Mock(return_value=1), SetMachine2=Mock())
    app = SimpleNamespace(IGetActiveDoc=Mock(return_value=doc), GetMachines=Mock(return_value=candidates))
    sw = SolidWorks(SimpleNamespace(GetCWApp=Mock(return_value=app)), model=model)
    interfaces = []
    typelib_paths = []

    def interface(obj, name, typelib_path=None):
        interfaces.append(name)
        typelib_paths.append(typelib_path)
        if obj is None:
            raise ValueError("Null interface")
        return part if name == "part" else obj

    def assign(candidate):
        assert candidate is chosen
        machine.MachType = 3
        model.dirty = True

    doc.SetMachine2.side_effect = assign
    monkeypatch.setattr(cam, "_interface", interface)
    return SimpleNamespace(sw=sw, model=model, chosen=chosen, machine=machine,
                           part=part, candidates=candidates, doc=doc, app=app,
                           interfaces=interfaces, typelib_paths=typelib_paths)


def test_inspect_turning_reads_catalog_without_choosing_machine_or_claiming_license(monkeypatch):
    f = turning_fixture(monkeypatch)
    result = cam.inspect_turning(f.sw, CLSID)
    assert result["status"] == "ok"
    assert result["current_machine_type"] == 1
    assert result["turn_machine_count"] == 2
    assert result["turning_entitlement"] == "unknown"
    assert result["active_document_unchanged"] is True
    f.app.GetMachines.assert_called_once_with(3)
    f.candidates.Item.assert_not_called()
    f.doc.SetMachine2.assert_not_called()
    f.sw.LoadAddIn.assert_not_called()


@pytest.mark.parametrize("invalid", ["unsaved", "assembly", "missing_cam_doc", "wrong_cam_doc"])
def test_turning_inspection_requires_existing_saved_part_and_matching_cam_kind(monkeypatch, invalid):
    f = turning_fixture(monkeypatch)
    if invalid == "unsaved":
        f.model.path = ""
    elif invalid == "assembly":
        f.model.GetType = Mock(return_value=2)
    elif invalid == "missing_cam_doc":
        f.app.IGetActiveDoc.return_value = None
    else:
        f.doc.GetDocType.return_value = 2
    result = cam.inspect_turning(f.sw, CLSID)
    assert result["status"] == "unavailable"
    f.doc.SetMachine2.assert_not_called()
    f.candidates.Item.assert_not_called()


def test_turning_readonly_inspection_detects_state_change(monkeypatch):
    f = turning_fixture(monkeypatch)

    def get_machines(_machine_type):
        f.model.dirty = True
        return f.candidates

    f.app.GetMachines.side_effect = get_machines
    result = cam.inspect_turning(f.sw, CLSID)
    assert result["status"] == "error"
    assert result["active_document_unchanged"] is False
    f.doc.SetMachine2.assert_not_called()


@pytest.mark.parametrize("count", [-1, 10001])
def test_unreasonable_turning_catalog_count_is_rejected(monkeypatch, count):
    f = turning_fixture(monkeypatch, count=count)
    result = cam.inspect_turning(f.sw, CLSID)
    assert result["status"] == "unavailable"
    f.doc.SetMachine2.assert_not_called()


def test_set_turn_machine_passes_actual_selected_dispatch_and_verifies_readback(monkeypatch):
    f = turning_fixture(monkeypatch)
    result = cam.set_turn_machine(f.sw, CLSID, 1, 1, 2)
    assert result["status"] == "ok"
    assert result["machine_assignment_verified"] is True
    assert result["current_machine_type"] == 3
    assert result["document_before"]["needs_save"] is False
    assert result["document_after"]["needs_save"] is True
    assert result["model_saved"] is False
    assert result["turning_entitlement"] == "unknown"
    assert result["toolpath_verified"] is False
    f.candidates.Item.assert_called_once_with(1)
    f.doc.SetMachine2.assert_called_once_with(f.chosen)
    assert f.part.IGetMachine.call_count == 2
    assert f.interfaces.count("collection") == 3  # Machines, feature setups, operation setups.
    f.sw.LoadAddIn.assert_not_called()


@pytest.mark.parametrize("invalid", ["dirty", "machine_changed", "catalog_changed", "negative_index", "large_index"])
def test_set_turn_machine_stops_before_assignment_on_stale_or_invalid_preconditions(monkeypatch, invalid):
    f = turning_fixture(monkeypatch)
    index, old_type, catalog_count = 0, 1, 2
    if invalid == "dirty":
        f.model.dirty = True
    elif invalid == "machine_changed":
        old_type = 3
    elif invalid == "catalog_changed":
        catalog_count = 7
    elif invalid == "negative_index":
        index = -1
    else:
        index = 2
    result = cam.set_turn_machine(f.sw, CLSID, index, old_type, catalog_count)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    f.doc.SetMachine2.assert_not_called()
    f.candidates.Item.assert_not_called()


@pytest.mark.parametrize("existing", ["features", "operations"])
def test_set_turn_machine_refuses_existing_feature_or_operation_setups(monkeypatch, existing):
    f = turning_fixture(monkeypatch, setup_count=int(existing == "features"),
                        op_setup_count=int(existing == "operations"))
    result = cam.set_turn_machine(f.sw, CLSID, 0, 1, 2)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    f.doc.SetMachine2.assert_not_called()
    f.candidates.Item.assert_not_called()


def test_set_turn_machine_refuses_null_candidate(monkeypatch):
    f = turning_fixture(monkeypatch)
    f.candidates.Item.return_value = None
    result = cam.set_turn_machine(f.sw, CLSID, 0, 1, 2)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    f.doc.SetMachine2.assert_not_called()


def test_set_turn_machine_rechecks_active_document_after_candidate_lookup(monkeypatch):
    f = turning_fixture(monkeypatch)

    def choose(_index):
        f.model.path = r"C:\production\foreign-part.sldprt"
        return f.chosen

    f.candidates.Item.side_effect = choose
    result = cam.set_turn_machine(f.sw, CLSID, 0, 1, 2)
    assert result["status"] == "error"
    assert result["assignment_attempted"] is False
    f.doc.SetMachine2.assert_not_called()


@pytest.mark.parametrize("failed_readback", ["wrong_type", "wrong_document"])
def test_set_turn_machine_requires_type_and_document_readback(monkeypatch, failed_readback):
    f = turning_fixture(monkeypatch)

    def assign(_chosen):
        f.machine.MachType = 1 if failed_readback == "wrong_type" else 3
        if failed_readback == "wrong_document":
            f.sw.ActiveDoc = None

    f.doc.SetMachine2.side_effect = assign
    result = cam.set_turn_machine(f.sw, CLSID, 0, 1, 2)
    assert result["status"] == "error"
    assert result["machine_assignment_verified"] is False
    f.doc.SetMachine2.assert_called_once_with(f.chosen)


def test_machine_assignment_exception_is_sanitized_and_marks_attempted(monkeypatch):
    f = turning_fixture(monkeypatch)
    f.doc.SetMachine2.side_effect = SecretComError("SECRET_LICENSE_IDENTIFIER")
    result = cam.set_turn_machine(f.sw, CLSID, 0, 1, 2)
    assert result["status"] == "error"
    assert result["stage"] == "SetMachine2"
    assert result["assignment_attempted"] is True
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)
    f.doc.SetMachine2.assert_called_once_with(f.chosen)


def test_turning_query_interface_failure_does_not_try_alternate_factory(monkeypatch):
    f = turning_fixture(monkeypatch)
    monkeypatch.setattr(cam, "_interface", Mock(side_effect=SecretComError("SECRET_LICENSE_IDENTIFIER")))
    result = cam.inspect_turning(f.sw, CLSID)
    assert result["status"] == "unavailable"
    assert "SECRET_LICENSE_IDENTIFIER" not in json.dumps(result)
    f.doc.SetMachine2.assert_not_called()
    f.sw.LoadAddIn.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "assign"])
def test_turning_forwards_explicit_typelib_to_every_interface(monkeypatch, tmp_path, operation):
    """显式类型库路径必须传给初始接口、空配置检查和修改后的回读。"""
    f = turning_fixture(monkeypatch)
    typelib_path = str(tmp_path / "camworks.tlb")
    if operation == "inspect":
        result = cam.inspect_turning(f.sw, CLSID, typelib_path=typelib_path)
    else:
        result = cam.set_turn_machine(f.sw, CLSID, 1, 1, 2, typelib_path=typelib_path)
    assert result["status"] == "ok"
    assert f.typelib_paths
    assert set(f.typelib_paths) == {typelib_path}
    assert len(f.typelib_paths) == len(f.interfaces)
    if operation == "assign":
        assert f.interfaces.count("machine") == 2
        assert f.interfaces.count("collection") == 3


def test_member_preserves_callable_coclass_wrapper_without_default_invoke():
    """CoClassBaseClass 的 _dispobj_ 包装器必须作为对象返回，不能触发默认成员。"""
    model = CallableDispatchModel()
    model._dispobj_ = model.__dict__.pop("_oleobj_")
    app = SimpleNamespace(IGetActiveDoc=model)
    sw = SolidWorks(model=model)
    assert "_oleobj_" not in model.__dict__
    assert cam._member(app, "IGetActiveDoc") is model
    assert cam.document_snapshot(sw)["path"] == model.path
    assert model.default_invocations == 0
