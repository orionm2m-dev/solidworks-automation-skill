"""THREAD 资格文件与空白 MILL 定义的 MCP schema/路由门禁；不连接 CAD。"""
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server
from scripts import sw_cam_comtypes as bridge

@pytest.fixture
def cores(context,monkeypatch):
    result={}
    for mod,fn in [("thread_postprocess","qualify_thread_postprocess"),("mill_qualification","configure_mill_qualification"),("mill_stock","configure_mill_stock")]:
        mock=Mock(return_value={"status":"ok","may_continue":False});result[mod]=mock
        monkeypatch.setitem(sys.modules,"scripts.sw_cam_"+mod,N(**{fn:mock}))
    return result

def args(context,kind,action="inspect",**changes):
    values=dict(addin_clsid=CLSID,expected_document_path=context.document,action=action,qualification_only=True)
    if kind=="thread_postprocess":
        cls=server.SolidWorksCamThreadPostprocessInput
        values.update(process_id=731,setup_index=0,operation_index=13,expected_operation_native_id=474,expected_record_count=34,expected_source_sha256="a"*64)
        if action!="inspect":values["output_path"]=str(context.dll.parent/"new-post"/"thread.nc")
    elif kind=="mill_qualification":
        cls=server.SolidWorksCamMillQualificationInput;values["operation"]="machine"
        if action!="inspect":values["machine_index"]=0
    else:
        cls=server.SolidWorksCamMillStockInput
        if action=="apply":
            source=context.dll.parent/"stock.stl";source.write_bytes(b"fixture")
            evidence=context.dll.parent/"review.json";evidence.write_text("{}")
            values.update(stl_path=str(source),stl_sha256="b"*64,stock_evidence=dict(path=str(evidence),sha256="c"*64))
    if action=="apply":values.update(expected_state_sha256="d"*64,receipt_path=str(context.dll.parent/"receipt.json"))
    return cls(**(values|changes))

def tool(kind):return getattr(server,"solidworks_cam_"+{"thread_postprocess":"qualify_thread_postprocess","mill_qualification":"configure_mill_qualification","mill_stock":"configure_mill_stock"}[kind])

@pytest.mark.parametrize("kind",["thread_postprocess","mill_qualification","mill_stock"])
@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_routes_exact_registered_target_and_fields(context,cores,kind,action):
    p=args(context,kind,action);assert json.loads(tool(kind)(p))==cores[kind].return_value
    cores[kind].assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))

@pytest.mark.parametrize("kind",["thread_postprocess","mill_qualification","mill_stock"])
@pytest.mark.parametrize("changes",[{"qualification_only":False},{"qualification_only":1},{"message_policy":"accept"},{"action":"replay"},
    {"expected_document_path":"relative.sldprt"},{"save":True}])
def test_strict_common_schema(context,cores,kind,changes):
    with pytest.raises(ValueError):args(context,kind,**changes)
    cores[kind].assert_not_called()

@pytest.mark.parametrize("kind",["thread_postprocess","mill_qualification","mill_stock"])
@pytest.mark.parametrize("guard",["pid","doc","version"])
def test_target_guard_prevents_core(context,cores,monkeypatch,kind,guard):
    if guard=="pid":monkeypatch.setattr(server,"_selected_process_id",None)
    elif guard=="doc":context.model.GetPathName=str(context.dll.parent/"other.sldprt")
    else:context.sw.RevisionNumber="33.1.0"
    assert json.loads(tool(kind)(args(context,kind)))["status"]=="error";cores[kind].assert_not_called()

@pytest.mark.parametrize("changes",[{"process_id":True},{"process_id":732},{"expected_record_count":0},{"expected_record_count":True},
    {"expected_source_sha256":"bad"},{"expected_operation_native_id":0},{"output_path":"C:/unrelated.nc"}])
def test_thread_scope_and_pid(context,cores,changes):
    if changes.get("process_id")==732:
        assert json.loads(tool("thread_postprocess")(args(context,"thread_postprocess",**changes)))["status"]=="error"
        context.connect.assert_not_called()
    else:
        with pytest.raises(ValueError):args(context,"thread_postprocess",**changes)
    cores["thread_postprocess"].assert_not_called()

@pytest.mark.parametrize("path",["relative.nc","C:/root.sldprt"])
def test_post_output_path_contract(context,cores,path):
    with pytest.raises(ValueError):args(context,"thread_postprocess","prepare",output_path=path)

def test_post_new_directory_and_receipt_no_overwrite(context,cores):
    out=context.dll.parent/"exists";out.mkdir()
    with pytest.raises(ValueError):args(context,"thread_postprocess","prepare",output_path=str(out/"thread.nc"))
    receipt=context.dll.parent/"receipt.json";receipt.write_text("old")
    with pytest.raises(ValueError):args(context,"thread_postprocess","apply")
    assert receipt.read_text()=="old"

@pytest.mark.parametrize("direction",[[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]])
def test_setup_cardinal_route(context,cores,direction):
    p=args(context,"mill_qualification","prepare",operation="setup",machine_index=None,direction=direction)
    tool("mill_qualification")(p)
    assert cores["mill_qualification"].call_args.kwargs["direction"]==direction

@pytest.mark.parametrize("direction",[[True,0,0],["1",0,0],[1,1,0],[0,0,0],[.5,0,0],[1,0],None])
def test_setup_ambiguous_axes_rejected(context,cores,direction):
    with pytest.raises(ValueError):args(context,"mill_qualification","prepare",operation="setup",machine_index=None,direction=direction)

@pytest.mark.parametrize("value",[True,1.0,"0",-1,128,None])
def test_machine_index_strict(context,cores,value):
    with pytest.raises(ValueError):args(context,"mill_qualification","prepare",machine_index=value)

@pytest.mark.parametrize("field",["stl_path","stl_sha256","stock_evidence","expected_state_sha256","receipt_path"])
def test_stock_apply_requires_all_bound_inputs(context,cores,field):
    with pytest.raises(ValueError):args(context,"mill_stock","apply",**{field:None})

@pytest.mark.parametrize("kind",["thread_postprocess","mill_qualification","mill_stock"])
def test_read_actions_reject_mutation_hash(context,cores,kind):
    with pytest.raises(ValueError):args(context,kind,"prepare",expected_state_sha256="d"*64)

def test_exact_interface_ids_and_non_replay_annotations():
    expected={"ICWMillMachine":"{FB4CC0D2-2AA4-11D6-A99F-00062999E55F}","ICWTurnMachine":"{FB4CC0D3-2AA4-11D6-A99F-00062999E55F}",
        "ICWSetup":"{FB4CC0D9-2AA4-11D6-A99F-00062999E55F}","ICWMillWorkpiece":"{C39E5BE7-A82A-4B02-B4DF-A23AD6C9162A}"}
    for name,iid in expected.items():assert bridge._INTERFACES[name]==iid
    for name in ["solidworks_cam_qualify_thread_postprocess","solidworks_cam_configure_mill_qualification","solidworks_cam_configure_mill_stock"]:
        annotations=server.mcp._tool_manager._tools[name].annotations
        assert not annotations.readOnlyHint and not annotations.idempotentHint
