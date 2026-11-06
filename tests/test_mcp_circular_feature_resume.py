"""Real Pydantic/wrapper continuation admission; no application calls."""
import ast,json
from pathlib import Path
from unittest.mock import Mock
import pytest
from test_mcp_current_circular_pocket import context,fake,params as ordinary_params,server,CLSID,core

SOURCE=Path(__file__).resolve().parents[1]/"server_nodes.py"
if SOURCE.is_file():
    tree=ast.parse(SOURCE.read_text(encoding="utf-8"))
    assert len(tree.body)==2
    server.mcp._tool_manager._tools.pop("solidworks_cam_add_circular_pocket_plan",None)
    exec(compile(tree,str(SOURCE),"exec"),server.__dict__)

PREFIXES=("partial_receipt","old_marker","original_apply_request","original_prepare_receipt")
def history(context):
    root=Path(context.document).parent
    return {prefix+suffix:(str(root/(prefix+".json")) if suffix=="_path" else "c"*64)
        for prefix in PREFIXES for suffix in ("_path","_sha256")}

def resume(context,**changes):
    values=dict(continuation_mode="after_feature",**history(context));values.update(changes)
    return ordinary_params(context,**values)

def test_actual_schema_and_wrapper_forward_all_history_without_outer_MCP_keys(context,fake):
    p=resume(context)
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(p))
    assert result["readback_verified"] and fake.fn.call_count==1
    values=p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    core.validate.assert_called_once_with(values,CLSID)
    args,kw=fake.fn.call_args
    assert args[1]==CLSID and kw["continuation_mode"]=="after_feature"
    for key,value in history(context).items():assert kw[key]==value
    assert not {"addin_clsid","expected_document_title","response_format"}&set(kw)
    assert all(key in json.dumps(server.mcp._tool_manager._tools["solidworks_cam_add_circular_pocket_plan"].parameters) for key in history(context))

@pytest.mark.parametrize("field",[p+s for p in PREFIXES for s in ("_path","_sha256")])
def test_each_missing_history_pin_rejected_before_target(context,fake,field):
    with pytest.raises(ValueError):resume(context,**{field:None})
    fake.fn.assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("field",[p+s for p in PREFIXES for s in ("_path","_sha256")])
def test_ordinary_creation_rejects_any_history_pin(context,fake,field):
    with pytest.raises(ValueError):ordinary_params(context,**{field:history(context)[field]})
    fake.fn.assert_not_called();context.connect.assert_not_called()

def test_normal_default_binding_stays_legacy_shape(context):
    p=ordinary_params(context)
    values=p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"})
    old={k:v for k,v in values.items() if k!="continuation_mode" and not any(k.startswith(x+"_") for x in PREFIXES)}
    assert core.binding(values)==core.binding(old)
    assert not set(history(context))&set(core.binding(values))

@pytest.mark.parametrize("changes",[
    {"action":"apply"},
    {"action":"prepare","prepare_receipt_path":"fresh.json","prepare_receipt_sha256":"d"*64},
    {"continuation_mode":"unknown"},
    {"partial_receipt_path":""},
    {"old_marker_sha256":"bad"},
    {"original_apply_request_path":False},
    {"action":"resume_after_feature"},
])
def test_explicit_prepare_apply_and_history_types(context,fake,changes):
    with pytest.raises(ValueError):resume(context,**changes)
    fake.fn.assert_not_called();context.connect.assert_not_called()

def test_apply_forwards_original_verified_prepare_pair_without_new_native_prepare(context,fake):
    h=history(context)
    p=resume(context,action="apply",prepare_receipt_path=h["original_prepare_receipt_path"],prepare_receipt_sha256=h["original_prepare_receipt_sha256"])
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(p))
    assert result["readback_verified"] and fake.fn.call_count==1
    kw=fake.fn.call_args.kwargs
    assert kw["prepare_receipt_sha256"]==kw["original_prepare_receipt_sha256"]=="c"*64
    assert kw["prepare_receipt_path"]==kw["original_prepare_receipt_path"]

def test_failed_history_validation_precedes_application_target(context,fake,monkeypatch):
    core.validate.side_effect=ValueError("invalid immutable history")
    target=Mock();monkeypatch.setattr(server,"_cam_target",target)
    result=json.loads(server.solidworks_cam_add_circular_pocket_plan(resume(context)))
    assert result["status"]=="error"
    target.assert_not_called();context.connect.assert_not_called();fake.fn.assert_not_called()

def test_wrapper_ast_is_unchanged(context):
    if not SOURCE.is_file():pytest.skip("Staging-only wrapper AST compare")
    old=ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    new=ast.parse(SOURCE.read_text(encoding="utf-8"))
    def node(tree):return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="solidworks_cam_add_circular_pocket_plan")
    assert ast.dump(node(old),include_attributes=False)==ast.dump(node(new),include_attributes=False)
