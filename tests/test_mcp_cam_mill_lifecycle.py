"""MILL lifecycle MCP schema/route tests; all CAD calls mocked."""
from test_mcp_cam_lifecycle import *

def mill_params(context, action="prepare", **changes):
    return params(context, action, **(dict(machine_kind="mill_qualification", process_id=731,
        acknowledge_qualification_copy=True) | changes))


@pytest.mark.parametrize("action", ["prepare", "save", "close"])
def test_mill_exact_new_route(context, core, action):
    p = mill_params(context, action)
    result = json.loads(server.solidworks_cam_document_lifecycle(p))
    assert result == core.return_value
    core.assert_called_once_with(context.sw, CLSID,
        typelib_path=str(context.dll.parent / "camworks.tlb"), expected_document_path=context.document,
        action=action, message_policy="vendor_default", expected_state_sha256=p.expected_state_sha256,
        receipt_path=p.receipt_path, machine_kind="mill_qualification", process_id=731,
        acknowledge_qualification_copy=True)
    assert context.runners == [{"format": server.ResponseFormat.JSON, "automation": True}]


@pytest.mark.parametrize("field,value", [("process_id", x) for x in [None, 0, -1, 4294967296, True, 731.0, "731"]]
    + [("acknowledge_qualification_copy", x) for x in [False, None, 0, 1, "true"]]
    + [("machine_kind", x) for x in [None, True, "mill", "Mill_qualification"]])
def test_mill_invalid_scope_rejected_before_target(context, core, field, value):
    with pytest.raises(ValueError):
        mill_params(context, **{field: value})
    core.assert_not_called()
    context.connect.assert_not_called()


@pytest.mark.parametrize("missing", ["process_id", "acknowledge_qualification_copy"])
def test_mill_scope_fields_mandatory(context, core, missing):
    data=dict(addin_clsid=CLSID, expected_document_path=context.document, action="prepare",
        message_policy="vendor_default", machine_kind="mill_qualification", process_id=731,
        acknowledge_qualification_copy=True)
    del data[missing]
    with pytest.raises(ValueError):server.SolidWorksCamDocumentLifecycleInput(**data)
    core.assert_not_called()


@pytest.mark.parametrize("extra", [{"process_id":731}, {"process_id":None},
    {"acknowledge_qualification_copy":True}, {"acknowledge_qualification_copy":False}])
def test_turn_rejects_explicit_mill_fields(context, core, extra):
    with pytest.raises(ValueError):params(context, **extra)
    core.assert_not_called()
    context.connect.assert_not_called()


def test_explicit_turn_keeps_old_core_call(context, core):
    p=params(context, machine_kind="turn")
    server.solidworks_cam_document_lifecycle(p)
    assert "machine_kind" not in core.call_args.kwargs
    assert "process_id" not in core.call_args.kwargs
    assert "acknowledge_qualification_copy" not in core.call_args.kwargs


@pytest.mark.parametrize("pinned", [None, 999])
def test_mill_pinned_pid_checked_before_cam_target(context, core, monkeypatch, pinned):
    monkeypatch.setattr(server, "_selected_process_id", pinned)
    target=Mock(side_effect=AssertionError("must not reach _cam_target"))
    monkeypatch.setattr(server, "_cam_target", target)
    result=json.loads(server.solidworks_cam_document_lifecycle(mill_params(context)))
    assert result["status"] == "error"
    target.assert_not_called()
    context.connect.assert_not_called()
    context.discover.assert_not_called()
    core.assert_not_called()


@pytest.mark.parametrize("failure", ["wrong_document", "wrong_version", "discovery_error"])
def test_mill_preserves_existing_target_guards(context, core, failure):
    if failure == "wrong_document":context.model.GetPathName=str(context.dll.parent / "foreign.sldprt")
    elif failure == "wrong_version":context.sw.RevisionNumber="33.1.0"
    else:context.inventory["errors"]=[{"stage":"registry"}]
    result=json.loads(server.solidworks_cam_document_lifecycle(mill_params(context)))
    assert result["status"] == "error"
    core.assert_not_called()


@pytest.mark.parametrize("action", ["save", "close"])
def test_mill_receipt_and_digest_guards_preserved(context, core, action):
    with pytest.raises(ValueError):mill_params(context, action, expected_state_sha256=None)
    with pytest.raises(ValueError):mill_params(context, action, receipt_path=None)
    receipt=context.dll.parent / "occupied.json";receipt.write_text("original",encoding="utf-8")
    with pytest.raises(ValueError):mill_params(context, action, receipt_path=str(receipt))
    assert receipt.read_text(encoding="utf-8") == "original"
    core.assert_not_called()


def test_mill_prepare_rejects_receipt(context, core):
    with pytest.raises(ValueError):mill_params(context, receipt_path=str(context.dll.parent / "fresh.json"))
    core.assert_not_called()
