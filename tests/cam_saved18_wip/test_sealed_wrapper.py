import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

HELPER = "_cam_saved_optimized_wip_sealed_payload"
TOOL = "solidworks_cam_export_saved_optimized_eighteen_wip"

@pytest.fixture
def wrapper(tmp_path):
    root = Path(os.environ.get("SOLIDWORKS_SKILL_ROOT", Path(__file__).resolve().parents[2]))
    source = root / "mcp-server/server.py"
    text = source.read_text("utf-8-sig") if source.exists() else ""
    tree = ast.parse(text)
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in (HELPER, TOOL)]
    assert len(found) == 2, "Test the installed wrapper when present; incomplete installed wrapper is an error"
    for node in found:
        node.decorator_list = []
    scope = dict(SCRIPTS_DIR=str(tmp_path), SolidWorksCamSavedOptimizedWipInput=object,
        _selected_process_id=123, _run_locked=lambda fn, *a, **kw: fn())
    exec(compile(ast.Module(body=found, type_ignores=[]), "<sealed-wrapper>", "exec"), scope)
    module = tmp_path / "sw_cam_saved18_optimized_wip.py"
    module.write_bytes(b"tested packet")
    value = dict(action="export_saved_optimized_eighteen_wip", params=dict(process_id=123,
        module_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),
        receipt_path=str(tmp_path / "result.json"), output_dir=str(tmp_path / "progress.json"),
        expected_document_path=str(tmp_path / "owned.sldprt"),
        saved_receipt_path=str(tmp_path / "qualified.json"),
        acknowledgement="export_saved18_whole_machine_wip1_no_generation_no_save_no_settings"))
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
    if fault == "alias_module": value["params"]["output_dir"] = str(module)
    if fault == "alias_outputs": value["params"]["output_dir"] = value["params"]["receipt_path"]
    if fault == "missing_output": del value["params"]["output_dir"]
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
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_saved18_optimized_wip", SimpleNamespace(dispatch_request=lambda p: calls.append(p)))
    with pytest.raises(ValueError): scope[TOOL](seal())
    assert calls == []


def test_dispatch_gets_copy_and_original_is_rechecked(wrapper, monkeypatch):
    scope, value, module, path, seal, invoke = wrapper
    p = seal(); before = path.read_bytes()
    def dispatch(payload):
        payload["params"]["acknowledgement"] = "modified only in dispatch copy"
        return {"result": "fake"}
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_saved18_optimized_wip", SimpleNamespace(dispatch_request=dispatch))
    assert scope[TOOL](p) == {"result": "fake"}
    assert path.read_bytes() == before


def test_changed_seal_after_dispatch_rejected(wrapper, monkeypatch):
    scope, value, module, path, seal, invoke = wrapper
    def dispatch(payload):
        path.write_text("{}")
        return {"result": "fake"}
    monkeypatch.setitem(sys.modules, "scripts.sw_cam_saved18_optimized_wip", SimpleNamespace(dispatch_request=dispatch))
    with pytest.raises(ValueError): scope[TOOL](seal())


@pytest.mark.parametrize("field", ["expected_document_path", "saved_receipt_path"])
def test_continuation_inputs_cannot_be_overwritten(wrapper, field):
    wrapper[1]["params"]["receipt_path"] = wrapper[1]["params"][field]
    with pytest.raises(ValueError): wrapper[-1]()


@pytest.mark.parametrize("field", ["expected_document_path", "saved_receipt_path"])
def test_relative_continuation_inputs_rejected(wrapper, field):
    wrapper[1]["params"][field] = "relative.json"
    with pytest.raises(ValueError): wrapper[-1]()
