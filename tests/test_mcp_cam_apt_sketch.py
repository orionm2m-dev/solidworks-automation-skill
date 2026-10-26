"""APT 资格选择和纯草图的 MCP schema/路由测试；没有 CAD。"""
import json,sys
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from test_mcp_cam_operation_diagnostics import context, CLSID, server
from scripts import sw_cam_profile_sketch as sketch

SPEC=dict(plane_axis="Z",plane_offset_mm=2,sketch_name="PocketProbe",plane_name="ProbePlane",
          profile=dict(kind="closed_polyline",points_model_mm=[[1,1,2],[4,1,2],[4,6,2],[1,6,2]]))

@pytest.fixture
def cores(context,monkeypatch):
    apt=Mock(return_value=dict(status="ok",may_continue=False));sketch_core=Mock(return_value=dict(status="ok",may_continue=False))
    monkeypatch.setitem(sys.modules,"scripts.sw_cam_apt_controller",N(configure_apt_controller=apt))
    monkeypatch.setattr(sketch,"create_cam_profile_sketch",sketch_core)
    return N(apt=apt,sketch=sketch_core)

def inputs(context,kind,action="inspect",**changes):
    common=dict(process_id=731,expected_document_path=context.document,action=action,qualification_only=True)
    if kind=="apt":
        cls=server.SolidWorksCamAptControllerInput
        common.update(addin_clsid=CLSID,expected_source_sha256="a"*64,acknowledge_disposable_copy=True)
        if action!="inspect":
            path=context.dll.parent/"turn.aptctl";path.write_bytes(b"fixture")
            common.update(controller_name="turn",controller_file_path=str(path),controller_file_sha256="b"*64,acknowledge_path_argument_qualification=True)
    else:
        cls=server.SolidWorksCamProfileSketchInput;common["spec"]=deepcopy(SPEC)
    if action=="apply":common.update(expected_state_sha256="c"*64,receipt_path=str(context.dll.parent/"new.json"))
    return cls(**(common|changes))

def invoke(kind,p):
    return getattr(server,"solidworks_cam_"+("configure_apt_controller" if kind=="apt" else "create_profile_sketch"))(p)

@pytest.mark.parametrize("kind",["apt","sketch"])
@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_exact_routes(context,cores,kind,action):
    p=inputs(context,kind,action);assert json.loads(invoke(kind,p))["status"]=="ok"
    if kind=="apt":
        cores.apt.assert_called_once_with(context.sw,CLSID,typelib_path=str(context.dll.parent/"camworks.tlb"),
            **p.model_dump(exclude={"addin_clsid","expected_document_title","response_format"}))
    else:
        cores.sketch.assert_called_once_with(context.sw,expected_process_id=731,expected_document_path=context.document,
            action=action,spec=SPEC,expected_state_sha256=p.expected_state_sha256,receipt_path=p.receipt_path,qualification_only=True)
        context.discover.assert_not_called()

@pytest.mark.parametrize("kind",["apt","sketch"])
@pytest.mark.parametrize("change",[{"process_id":True},{"process_id":0},{"qualification_only":1},{"qualification_only":False},
    {"action":"retry"},{"expected_document_path":"relative.sldprt"},{"expected_document_path":"C:/other.sldasm"},{"save":True}])
def test_common_strict_schema(context,cores,kind,change):
    with pytest.raises(ValueError):inputs(context,kind,**change)
    cores.apt.assert_not_called();cores.sketch.assert_not_called()

@pytest.mark.parametrize("kind,guard",[("apt","pinned"),("apt","path"),("sketch","pinned"),("sketch","path"),("sketch","type")])
def test_exact_target_refusal_before_core(context,cores,monkeypatch,kind,guard):
    if guard=="pinned":monkeypatch.setattr(server,"_selected_process_id",732)
    elif guard=="path":context.model.GetPathName=str(context.dll.parent/"other.sldprt")
    else:context.model.GetType=2
    assert json.loads(invoke(kind,inputs(context,kind)))["status"]=="error"
    cores.apt.assert_not_called();cores.sketch.assert_not_called()
    if guard=="pinned":context.connect.assert_not_called()

@pytest.mark.parametrize("change",[{"acknowledge_disposable_copy":False},{"acknowledge_disposable_copy":1},
    {"acknowledge_path_argument_qualification":True},{"controller_file_sha256":"a"*64},{"message_policy":"accept"}])
def test_apt_read_scope(context,cores,change):
    with pytest.raises(ValueError):inputs(context,"apt",**change)

@pytest.mark.parametrize("field",["controller_name","controller_file_path","controller_file_sha256","expected_state_sha256","receipt_path"])
def test_apt_apply_requires_bound_inputs(context,cores,field):
    with pytest.raises(ValueError):inputs(context,"apt","apply",**{field:None})

@pytest.mark.parametrize("kind",["apt","sketch"])
def test_unique_receipt_and_no_read_mutation_fields(context,cores,kind):
    p=context.dll.parent/"new.json";p.write_text("old")
    with pytest.raises(ValueError):inputs(context,kind,"apply")
    assert p.read_text()=="old"
    with pytest.raises(ValueError):inputs(context,kind,"prepare",expected_state_sha256="f"*64)

@pytest.mark.parametrize("bad",[
    dict(plane_axis="Q"),dict(plane_offset_mm=True),dict(plane_offset_mm="2"),dict(sketch_name="Edge1; run"),
    dict(profile=dict(kind="closed_polyline",points_model_mm=[[1,1,2],[4,1,2],[1,1,2]])),
    dict(profile=dict(kind="circle",center_model_mm=[1,1,2],radius_mm=True)),
    dict(profile=dict(kind="circle",center_model_mm=[1,1,3],radius_mm=1)),dict(extra=1)])
def test_sketch_spec_strict_numeric_and_geometry(context,cores,bad):
    with pytest.raises(ValueError):inputs(context,"sketch",spec=deepcopy(SPEC)|bad)
    cores.sketch.assert_not_called()

def test_sketch_circle_route_no_cam_registration(context,cores):
    spec=deepcopy(SPEC);spec["profile"]=dict(kind="circle",center_model_mm=[1,1,2],radius_mm=.5)
    invoke("sketch",inputs(context,"sketch","prepare",spec=spec))
    assert cores.sketch.call_args.kwargs["spec"]==spec
    context.discover.assert_not_called()

def test_annotations_nonreplay():
    for name in ("solidworks_cam_configure_apt_controller","solidworks_cam_create_profile_sketch"):
        a=server.mcp._tool_manager._tools[name].annotations
        assert not a.idempotentHint and not a.readOnlyHint


@pytest.mark.parametrize("action",["inspect","prepare","apply"])
def test_explicit_installed_APT_mode_routes_without_implicit_fallback(context,cores,action):
    p=inputs(context,"apt",action,catalogue_source="installed_files_qualification")
    invoke("apt",p)
    assert cores.apt.call_args.kwargs["catalogue_source"]=="installed_files_qualification"
    assert inputs(context,"apt").catalogue_source=="native"


def test_unsupported_catalogue_mode_rejected(context,cores):
    with pytest.raises(ValueError):inputs(context,"apt",catalogue_source="automatic_fallback")
    cores.apt.assert_not_called()


@pytest.mark.parametrize("kind",["directory_with_trailing_separator","exact_aptctl_file_path"])
def test_explicit_APT_path_argument_kind_routes_exactly(context,cores,kind):
    p=inputs(context,"apt","prepare",catalogue_source="installed_files_qualification",path_argument_kind=kind)
    invoke("apt",p)
    assert cores.apt.call_args.kwargs["path_argument_kind"]==kind
    assert inputs(context,"apt").path_argument_kind=="directory_with_trailing_separator"


@pytest.mark.parametrize("change",[{"path_argument_kind":True},{"path_argument_kind":"auto"},
    {"path_argument_kind":"full_file_path"},{"path_argument_kind":"exact_aptctl_file_path"}])
def test_invalid_path_argument_kind_or_source_rejected(context,cores,change):
    with pytest.raises(ValueError):inputs(context,"apt","prepare",**change)
    cores.apt.assert_not_called()


def test_inspect_does_not_accept_unapplied_path_experiment(context,cores):
    with pytest.raises(ValueError):inputs(context,"apt",catalogue_source="installed_files_qualification",path_argument_kind="exact_aptctl_file_path")
    cores.apt.assert_not_called()


@pytest.mark.parametrize("mode,name",[("stem","turn"),("filename_with_extension","turn.aptctl")])
def test_name_mode_schema_route_exactly_preserves_candidate(context,cores,mode,name):
    p=inputs(context,"apt","prepare",catalogue_source="installed_files_qualification",name_mode=mode,controller_name=name)
    invoke("apt",p)
    assert cores.apt.call_args.kwargs["name_mode"]==mode and cores.apt.call_args.kwargs["controller_name"]==name
    assert inputs(context,"apt").name_mode=="stem"


@pytest.mark.parametrize("change",[{"name_mode":True},{"name_mode":"filename"},{"name_mode":"auto"},
    {"name_mode":"filename_with_extension"}])
def test_name_mode_schema_rejects_unknown_or_unbound_source(context,cores,change):
    with pytest.raises(ValueError):inputs(context,"apt","prepare",**change)
    cores.apt.assert_not_called()
