"""只读 THREAD 及材料/切削条件的 MCP 严格输入与目标门禁。"""
import json
import sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server
from scripts import sw_cam_comtypes as bridge
from scripts.sw_cam_thread_records import REQUIRED_INTERFACES

@pytest.fixture
def cores(context,monkeypatch):
    result={}
    for suffix,func in [("thread_records","inspect_thread_records"),("thread_tool","inspect_thread_tool"),
            ("cutting_conditions","configure_cutting_conditions"),("material_catalogue","inspect_material_catalogue")]:
        mock=Mock(return_value={"status":"ok","may_continue":False})
        monkeypatch.setitem(sys.modules,"scripts.sw_cam_"+suffix,N(**{func:mock}));result[suffix]=mock
    return result


def reader(context,kind="thread_tool",**changes):
    args=dict(addin_clsid=CLSID,process_id=731,expected_document_path=context.document,
        setup_index=0,operation_index=13,expected_operation_native_id=474)
    cls=server.SolidWorksCamThreadToolInput if kind=="thread_tool" else server.SolidWorksCamThreadRecordsInput
    if kind=="thread_tool":args["expected_feature_native_id"]=382
    return cls(**(args|changes))

@pytest.mark.parametrize("kind",["thread_records","thread_tool"])
def test_reader_routes_exact_process_id_and_registered_typelib(context,cores,kind):
    p=reader(context,kind)
    tool=getattr(server,"solidworks_cam_inspect_"+kind)
    assert json.loads(tool(p))==cores[kind].return_value
    cores[kind].assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
        **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]

@pytest.mark.parametrize("kind",["thread_records","thread_tool"])
@pytest.mark.parametrize("field,value",[("process_id",True),("setup_index",1.0),("operation_index","13"),
    ("expected_operation_native_id",0),("message_policy","yes"),("expected_document_path","relative.sldprt"),("generate_toolpath",True)])
def test_reader_strict_schema(context,cores,kind,field,value):
    with pytest.raises(ValueError):reader(context,kind,**{field:value})
    cores[kind].assert_not_called()

@pytest.mark.parametrize("kind",["thread_records","thread_tool"])
def test_foreign_pid_rejected_before_connect(context,cores,kind):
    result=getattr(server,"solidworks_cam_inspect_"+kind)(reader(context,kind,process_id=732))
    assert json.loads(result)["status"]=="error"
    cores[kind].assert_not_called();context.connect.assert_not_called()

@pytest.mark.parametrize("kind",["thread_records","thread_tool"])
def test_reader_native_document_guard(context,cores,kind):
    context.model.GetPathName=str(context.dll.parent/"other.sldprt")
    assert json.loads(getattr(server,"solidworks_cam_inspect_"+kind)(reader(context,kind)))["status"]=="error"
    cores[kind].assert_not_called()


def cutting(context,action="inspect",field="Material",**changes):
    args=dict(addin_clsid=CLSID,expected_document_path=context.document,action=action,field=field,
        qualification_only=True,message_policy="vendor_default")
    if field!="Material":args["selected_operation"]=dict(setup_index=0,operation_index=13,expected_operation_type=12)
    return server.SolidWorksCamCuttingConditionsInput(**(args|changes))

@pytest.mark.parametrize("field",["Material","SMM","MAXRPM","SpindleSpeed","FPR","FPM","IsSMM","IsFPR","IsAssociateWithStockMaterial"])
def test_cutting_read_route_preserves_exact_scope(context,cores,field):
    p=cutting(context,"prepare",field)
    assert json.loads(server.solidworks_cam_configure_cutting_conditions(p))==cores["cutting_conditions"].return_value
    cores["cutting_conditions"].assert_called_once_with(context.sw,CLSID,
        typelib_path=str(context.dll.parent/"camworks.tlb"),**p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))


def apply_args(context,field):
    evidence=context.dll.parent/"evidence.json";evidence.write_text("{}")
    args=dict(expected_state_sha256="a"*64,receipt_path=str(context.dll.parent/"new.json"),
        allowed_affected_operations=[] if field=="Material" else [dict(setup_index=0,operation_index=13,expected_operation_type=12)])
    if field=="Material":args.update(value_native="Exact material",material_evidence=dict(path=str(evidence),sha256="b"*64))
    elif field.startswith("Is"):args["value_native"]=False
    else:args.update(value_native=1.5,unit_evidence=dict(path=str(evidence),sha256="b"*64))
    return args

@pytest.mark.parametrize("field",["Material","FPR","IsFPR"])
def test_cutting_apply_nested_evidence_and_empty_material_scope(context,cores,field):
    p=cutting(context,"apply",field,**apply_args(context,field))
    server.solidworks_cam_configure_cutting_conditions(p)
    assert cores["cutting_conditions"].call_args.kwargs["value_native"]==p.value_native
    if field=="Material":assert cores["cutting_conditions"].call_args.kwargs["allowed_affected_operations"]==[]

@pytest.mark.parametrize("field,value",[("FPR",True),("FPR","1.5"),("FPR",0),("FPR",float("nan")),
    ("IsSMM",0),("IsSMM","false"),("Material",1),("Material"," ")])
def test_cutting_values_not_coerced(context,cores,field,value):
    with pytest.raises(ValueError):cutting(context,"apply",field,**(apply_args(context,field)|dict(value_native=value)))
    cores["cutting_conditions"].assert_not_called()

@pytest.mark.parametrize("field",["expected_state_sha256","receipt_path","allowed_affected_operations","material_evidence"])
def test_material_apply_requires_bound_inputs(context,cores,field):
    with pytest.raises(ValueError):cutting(context,"apply","Material",**(apply_args(context,"Material")|{field:None}))
    cores["cutting_conditions"].assert_not_called()

@pytest.mark.parametrize("changes",[{"value_native":1},{"qualification_only":1},{"field":"ThreadDepth"},
    {"selected_operation":{"setup_index":0,"operation_index":0,"expected_operation_type":1}},
    {"save":True}])
def test_cutting_read_contract_rejects_unrelated_or_mutating_inputs(context,cores,changes):
    with pytest.raises(ValueError):cutting(context,**changes)
    cores["cutting_conditions"].assert_not_called()


def test_new_interfaces_match_primary_iids_and_tool_annotations():
    for name,iid in REQUIRED_INTERFACES.items():assert bridge._INTERFACES[name]==iid
    assert bridge._INTERFACES["ICWWorkpiece"]=="{31EB50B8-4306-4A84-BFC8-2C92B8E9996E}"
    assert bridge._INTERFACES["ICWTurnCuttingParam"]=="{32FB48CB-70D3-46B2-B3A2-35DC96F2AE9B}"
    assert bridge._INTERFACES["ICWToolCutParam"]=="{09C4ADAD-7772-4110-B936-802ABFBF86AF}"
    for name in ["solidworks_cam_inspect_thread_tool","solidworks_cam_inspect_thread_records"]:
        annotations=server.mcp._tool_manager._tools[name].annotations
        assert annotations.readOnlyHint and annotations.idempotentHint and not annotations.destructiveHint
    assert not server.mcp._tool_manager._tools["solidworks_cam_configure_cutting_conditions"].annotations.idempotentHint



def catalogue(context,**changes):
    return server.SolidWorksCamMaterialCatalogueInput(**(dict(addin_clsid=CLSID,expected_document_path=context.document)|changes))


def test_material_catalogue_routes_registered_typelib(context,cores):
    result=json.loads(server.solidworks_cam_inspect_material_catalogue(catalogue(context)))
    assert result==cores["material_catalogue"].return_value
    cores["material_catalogue"].assert_called_once_with(context.sw,CLSID,
        typelib_path=str(context.dll.parent/"camworks.tlb"),expected_document_path=context.document)
    a=server.mcp._tool_manager._tools["solidworks_cam_inspect_material_catalogue"].annotations
    assert a.readOnlyHint and a.idempotentHint and not a.destructiveHint


@pytest.mark.parametrize("changes",[{"expected_document_path":"relative.sldprt"},
    {"expected_document_path":"C:/fixture.step"},{"expected_document_path":None},{"material":"304L"}])
def test_material_catalogue_schema_rejects_non_target_inputs(context,cores,changes):
    with pytest.raises(ValueError):catalogue(context,**changes)
    cores["material_catalogue"].assert_not_called()


@pytest.mark.parametrize("guard",["document","pid","version"])
def test_material_catalogue_target_guards_prevent_core(context,cores,monkeypatch,guard):
    if guard=="document":context.model.GetPathName=str(context.dll.parent/"other.sldprt")
    elif guard=="pid":monkeypatch.setattr(server,"_selected_process_id",None)
    else:context.sw.RevisionNumber="33.1.0"
    assert json.loads(server.solidworks_cam_inspect_material_catalogue(catalogue(context)))["status"]=="error"
    cores["material_catalogue"].assert_not_called()
