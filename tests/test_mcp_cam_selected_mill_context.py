"""Selected-feature MCP context inheritance and explicit downstream routing."""
import json,sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context,CLSID,server

CASES=[
 ("SolidWorksCamMillFeaturePlanInput","solidworks_cam_qualify_mill_feature_operation_plan","sw_cam_mill_feature_process","qualify_mill_feature_operation_plan"),
 ("SolidWorksCamMillOperationToolpathInput","solidworks_cam_qualify_mill_operation_toolpath","sw_cam_mill_toolpath","qualify_mill_operation_toolpath"),
 ("SolidWorksCamMillToolDiameterInput","solidworks_cam_qualify_mill_tool_diameter","sw_cam_mill_tool_diameter","qualify_mill_tool_diameter"),
 ("SolidWorksCamMillOperationLevelsInput","solidworks_cam_inspect_mill_operation_levels","sw_cam_mill_levels","inspect_mill_operation_levels"),
 ("SolidWorksCamMillRoughBoundaryInput","solidworks_cam_inspect_mill_rough_boundary","sw_cam_mill_rough_boundary","inspect_mill_rough_boundary"),
 ("SolidWorksCamMillRoughBoundarySetInput","solidworks_cam_configure_mill_rough_boundary","sw_cam_mill_rough_boundary_set","configure_mill_rough_boundary"),
 ("SolidWorksCamMillGenericCLExportInput","solidworks_cam_export_mill_generic_cl","sw_cam_mill_generic_cl","export_mill_generic_cl"),
 ("SolidWorksCamMillFeatureGeometryInput","solidworks_cam_export_mill_feature_geometry","sw_cam_mill_geometry","export_mill_feature_geometry")]

def params(context,case,**changes):
    cls=getattr(server,case[0])
    source=dict(addin_clsid=CLSID,process_id=731,expected_document_path=context.document,
        expected_source_sha256="b"*64,expected_feature_native_id=111,expected_operation_native_id=114,
        expected_mill_operation_type=0,expected_operation_native_ids=[114,115],
        expected_tool_native_id=116,expected_tool_type_raw=1,expected_cut_diameter_native=6.,new_cut_diameter_native=2.,
        expected_toolpath_record_counts=[68],expected_ungenerated_operation_ids=[115],
        expected_generated_operation_native_ids=[114],export_kind="target",output_dir=str(context.dll.parent/"fresh"),output_path=str(context.dll.parent/"fresh"/"output.cl"),
        qualification_only=True,acknowledge_disposable_copy=True,acknowledge_document_wide_export=True,acknowledge_machine_scope=True,
        action="prepare",receipt_path=str(context.dll.parent/"new_receipt.json"),
        expected_tool_diameter_percent=75.,new_tool_diameter_percent=0.,
        message_policy="vendor_default",feature_kind="circular_pocket",
        circle_creation_receipt_path=str(context.dll.parent/"creator.json"),circle_creation_receipt_sha256="c"*64)
    data={k:v for k,v in source.items() if k in cls.model_fields}
    if case[0] in ("SolidWorksCamMillFeaturePlanInput","SolidWorksCamMillOperationToolpathInput",
                   "SolidWorksCamMillToolDiameterInput","SolidWorksCamMillGenericCLExportInput",
                   "SolidWorksCamMillFeatureGeometryInput"):data.pop("receipt_path",None)
    if case[0]=="SolidWorksCamMillOperationToolpathInput":
        data.pop("expected_toolpath_record_counts",None);data.pop("expected_tool_diameter_percent",None)
    return cls(**(data|changes))

@pytest.mark.parametrize("case",CASES)
def test_explicit_circle_fields_reach_same_locked_route(context,monkeypatch,case):
    model=params(context,case);call=Mock(return_value={"status":"review_required"})
    monkeypatch.setitem(sys.modules,"scripts."+case[2],N(**{case[3]:call}))
    result=json.loads(getattr(server,case[1])(model))
    assert result==call.return_value
    kwargs=call.call_args.kwargs
    assert kwargs["feature_kind"]=="circular_pocket"
    assert kwargs["circle_creation_receipt_path"]==model.circle_creation_receipt_path
    assert kwargs["circle_creation_receipt_sha256"]=="c"*64
    assert kwargs["expected_source_sha256"]=="b"*64
    assert context.runners==[{"format":server.ResponseFormat.JSON,"automation":True}]

@pytest.mark.parametrize("case",CASES)
@pytest.mark.parametrize("field,value",[
 ("feature_kind","circle"),("feature_kind",None),
 ("circle_creation_receipt_path",None),("circle_creation_receipt_path","relative.json"),
 ("circle_creation_receipt_sha256",None),("circle_creation_receipt_sha256","A"*64)])
def test_partial_or_malformed_pins_fail_before_connect(context,case,field,value):
    with pytest.raises(ValueError):params(context,case,**{field:value})
    context.connect.assert_not_called()

@pytest.mark.parametrize("case",CASES)
def test_default_mode_rejects_even_explicit_null_provenance(context,case):
    with pytest.raises(ValueError):
        params(context,case,feature_kind="open_pocket",circle_creation_receipt_path=None,circle_creation_receipt_sha256=None)
    context.connect.assert_not_called()

@pytest.mark.parametrize("name",["SolidWorksCamDocumentLifecycleInput"]+[x[0] for x in CASES])
def test_one_inherited_context_contract(name):
    cls=getattr(server,name)
    assert server.SolidWorksCamSelectedFeatureContextInput in cls.__mro__
    assert len([x for x in cls.__mro__ if x.__name__=="SolidWorksCamSelectedFeatureContextInput"])==1
