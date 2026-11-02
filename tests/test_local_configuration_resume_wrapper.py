import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

HELPER = "_cam_local_configuration_resume_sealed_payload"
TOOL = "solidworks_cam_resume_local_group_configuration"

@pytest.fixture
def wrapper(tmp_path):
    from cam_public_test_support import add_runtime
    root = add_runtime()
    source = root / "mcp-server/server.py"
    tree = ast.parse(source.read_text("utf-8-sig"))
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in (HELPER, TOOL)]
    if len(found) != 2:
        raise RuntimeError("Required complete installed wrapper is missing")
    for node in found:
        node.decorator_list = []
    scope = dict(SCRIPTS_DIR=str(tmp_path), SolidWorksCamLocalConfigurationResumeInput=object,
        _selected_process_id=123, _run_locked=lambda fn, *a, **kw: fn())
    exec(compile(ast.Module(body=found, type_ignores=[]), "<sealed-wrapper>", "exec"), scope)
    module = tmp_path / "sw_cam_local_configuration_resume.py"
    module.write_bytes(b"tested packet")
    value = dict(action="resume_local_group_configuration", params=dict(process_id=123,
        module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),
        receipt_path=str(tmp_path / "result.json"), progress_path=str(tmp_path / "progress.json"),
        saved_cl_path=str(tmp_path / "saved.cl"),
        expected_document_path=str(tmp_path / "owned.sldprt"),
        partial_receipt_path=str(tmp_path / "failed.json"), partial_marker_path=str(tmp_path / "pending.json"),
        writer_stop_receipt_path=str(tmp_path / "writer_stopped.json"),
        acknowledgement="adopt30_verified_actions_configure_remaining_save1_export14_no_insert_no_settool_no_gtp"))
    path = tmp_path / "request.json"
    def seal(value=value, raw=None):
        path.write_bytes(raw if raw is not None else json.dumps(value).encode())
        return SimpleNamespace(process_id=123, request_path=str(path),
            request_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), response_format="json")
    def invoke(value=value, raw=None, pid=123):
        p = seal(value, raw)
        return scope[HELPER](p.request_path, p.request_sha256, pid)
    return scope, value, module, path, seal, invoke


def test_exact_packet(wrapper):
    *_, invoke = wrapper
    assert invoke() == wrapper[1]

@pytest.mark.parametrize("fault", ["extra", "action", "pid", "bool_pid", "module", "relative", "alias_request", "alias_module", "alias_outputs", "missing_output"])
def test_invalid_packet_rejected(wrapper, fault):
    scope, value, module, path, seal, invoke = wrapper
    if fault == "extra": value["authority"] = {}
    if fault == "action": value["action"] = "other"
    if fault == "pid": value["params"]["process_id"] = 124
    if fault == "bool_pid": value["params"]["process_id"] = True
    if fault == "module": module.write_bytes(b"changed")
    if fault == "relative": value["params"]["receipt_path"] = "relative.json"
    if fault == "alias_request": value["params"]["receipt_path"] = str(path)
    if fault == "alias_module": value["params"]["progress_path"] = str(module)
    if fault == "alias_outputs": value["params"]["progress_path"] = value["params"]["receipt_path"]
    if fault == "missing_output": del value["params"]["saved_cl_path"]
    with pytest.raises(ValueError): invoke()

@pytest.mark.parametrize("raw", [b'{"action":"a","action":"b","params":{}}', b'{"action":"a","params":{"x":NaN}}', b'{"action":"a","params":{"x":Infinity}}'])
def test_duplicate_and_nonfinite_rejected(wrapper, raw):
    with pytest.raises(ValueError): wrapper[-1](raw=raw)


def test_oversize_request_rejected(wrapper):
    with pytest.raises(ValueError): wrapper[-1](raw=b" " * 1048577)


def test_bad_digest_rejected(wrapper):
    scope, value, module, path, seal, invoke = wrapper
    p = seal()
    with pytest.raises(ValueError): scope[HELPER](p.request_path, "0" * 64, 123)


def test_selected_pid_checked_before_dispatch(wrapper, monkeypatch):
    scope, value, module, path, seal, invoke = wrapper
    scope["_selected_process_id"] = 124
    calls = []
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_local_configuration_resume", SimpleNamespace(dispatch_request=lambda p: calls.append(p)))
    with pytest.raises(ValueError): scope[TOOL](seal())
    assert calls == []


def test_dispatch_gets_copy_and_original_is_rechecked(wrapper, monkeypatch):
    scope, value, module, path, seal, invoke = wrapper
    p = seal(); before = path.read_bytes()
    def dispatch(payload):
        payload["params"]["acknowledgement"] = "modified only in dispatch copy"
        return {"result": "fake"}
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_local_configuration_resume", SimpleNamespace(dispatch_request=dispatch))
    assert scope[TOOL](p) == {"result": "fake"}
    assert path.read_bytes() == before


def test_changed_seal_after_dispatch_rejected(wrapper, monkeypatch):
    scope, value, module, path, seal, invoke = wrapper
    def dispatch(payload):
        path.write_text("{}")
        return {"result": "fake"}
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_local_configuration_resume", SimpleNamespace(dispatch_request=dispatch))
    with pytest.raises(ValueError): scope[TOOL](seal())


@pytest.mark.parametrize("field", ["expected_document_path", "partial_receipt_path", "partial_marker_path", "writer_stop_receipt_path"])
def test_continuation_inputs_cannot_be_overwritten(wrapper, field):
    wrapper[1]["params"]["receipt_path"] = wrapper[1]["params"][field]
    with pytest.raises(ValueError): wrapper[-1]()


@pytest.mark.parametrize("field", ["expected_document_path", "partial_receipt_path", "partial_marker_path", "writer_stop_receipt_path"])
def test_relative_continuation_inputs_rejected(wrapper, field):
    wrapper[1]["params"][field] = "relative.json"
    with pytest.raises(ValueError): wrapper[-1]()
