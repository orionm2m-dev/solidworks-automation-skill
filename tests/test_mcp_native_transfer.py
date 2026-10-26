"""原生副本传递 MCP 的严格契约与 PID/锚点门禁；不调用 CAD。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"mcp-server") not in sys.path: sys.path.insert(0,str(ROOT/"mcp-server"))
import server

TOOLS={"part":"solidworks_qualify_part_transfer", "copy":"solidworks_qualify_reference_copy"}
SCHEMAS={"part":server.SolidWorksPartTransferInput,"copy":server.SolidWorksReferenceCopyInput}


@pytest.fixture
def transfer(tmp_path,monkeypatch):
    files={}
    for name in ["anchor.sldasm","source.sldprt","source.sldasm","donor.step","old.sldprt","new.sldprt"]:
        path=tmp_path/name;path.write_bytes(b"offline fixture");files[name]=str(path)
    model=N(GetPathName=files["anchor.sldasm"],GetTitle="anchor.sldasm",GetType=2)
    sw=N(ActiveDoc=model)
    part=Mock(return_value={"status":"review_required","qualified":False})
    copy=Mock(return_value={"status":"review_required","animation_verified":False})
    finalize=Mock(return_value={"status":"review_required","geometry_replayed":False})
    cleanup=Mock(return_value={"status":"review_required","cleanup_verified":True})
    inventory=Mock(return_value={"status":"ok","documents":[]})
    monkeypatch.setitem(sys.modules,"scripts.sw_native_transfer",N(qualify_part_transfer=part,qualify_reference_copy=copy,finalize_part_transfer=finalize,cleanup_part_transfer=cleanup,inspect_open_documents=inventory))
    connect=Mock(return_value=(sw,model));runners=[]
    def locked(op,response_format,load_automation=True,**kwargs):
        runners.append((response_format,load_automation))
        try:return server._result(op(),response_format)
        except Exception as exc:return server._tool_error(exc,response_format)
    monkeypatch.setattr(server,"_run_locked",locked)
    monkeypatch.setattr(server,"_selected_process_id",731)
    monkeypatch.setattr(server,"connect_solidworks",connect)
    monkeypatch.setattr(server,"get_com_member",lambda obj,name:getattr(obj,name),raising=False)
    cam_target=Mock(side_effect=AssertionError("No CAM target/add-in calls"))
    monkeypatch.setattr(server,"_cam_target",cam_target)
    active=Mock(wraps=server._active_model_required)
    monkeypatch.setattr(server,"_active_model_required",active)
    return N(**locals())


def values(p,kind="part",action="prepare"):
    result=dict(process_id=731,expected_document_path=p.files["anchor.sldasm"],action=action,
        source_path=p.files["source.sldprt" if kind=="part" else "source.sldasm"],source_sha256="a"*64,
        output_path=str(p.tmp_path/("copy.sldprt" if kind=="part" else "copy.sldasm")),qualification_only=True)
    if kind=="part":result.update(mode="replace_body",donor_step_path=p.files["donor.step"],
        donor_sha256="b"*64,roundtrip_step_path=str(p.tmp_path/"roundtrip.step"))
    else:result["replacements"]=[dict(old_path=p.files["old.sldprt"],old_sha256="c"*64,
        new_path=p.files["new.sldprt"],new_sha256="d"*64)]
    if action=="apply":result.update(expected_state_sha256="e"*64,receipt_path=str(p.tmp_path/"receipt.json"))
    return result


def params(p,kind="part",action="prepare",**changes):
    return SCHEMAS[kind](**(values(p,kind,action)|changes))


def call(kind,p):return json.loads(getattr(server,TOOLS[kind])(p))


@pytest.mark.parametrize("kind",["part","copy"])
@pytest.mark.parametrize("action",["prepare","apply"])
def test_exact_core_route_after_real_document_guard(transfer,kind,action):
    p=params(transfer,kind,action,frozen_files=[{"path":transfer.files["anchor.sldasm"],"sha256":"f"*64}])
    native=getattr(transfer,kind)
    assert call(kind,p)==native.return_value
    native.assert_called_once_with(transfer.sw,**p.model_dump(exclude={"response_format","expected_document_title"}))
    transfer.active.assert_called_once_with(p)
    transfer.connect.assert_called_once_with(wait_seconds=1)
    transfer.cam_target.assert_not_called()
    assert transfer.runners==[(server.ResponseFormat.JSON,True)]


@pytest.mark.parametrize("mode",["add_delta","subtract_delta"])
def test_delta_mode_requires_explicit_ack_and_exact_donor_hash(transfer,mode):
    p=params(transfer,mode=mode,acknowledge_delta_only=True,donor_sha256="1"*64)
    call("part",p)
    assert transfer.part.call_args.kwargs["mode"]==mode
    assert transfer.part.call_args.kwargs["acknowledge_delta_only"] is True
    assert transfer.part.call_args.kwargs["donor_sha256"]=="1"*64


@pytest.mark.parametrize("kind",["part","copy"])
@pytest.mark.parametrize("selected",[None,999,"731",True])
def test_pid_guard_precedes_connection_and_active_document_read(transfer,monkeypatch,kind,selected):
    monkeypatch.setattr(server,"_selected_process_id",selected)
    assert call(kind,params(transfer,kind))["status"]=="error"
    transfer.active.assert_not_called();transfer.connect.assert_not_called()
    transfer.part.assert_not_called();transfer.copy.assert_not_called()


@pytest.mark.parametrize("kind",["part","copy"])
def test_wrong_anchor_blocks_native_core(transfer,kind):
    transfer.model.GetPathName=str(transfer.tmp_path/"foreign.sldasm")
    assert call(kind,params(transfer,kind))["status"]=="error"
    getattr(transfer,kind).assert_not_called();transfer.cam_target.assert_not_called()


@pytest.mark.parametrize("kind",["part","copy"])
@pytest.mark.parametrize("value",[True,False,0,-1,731.0,"731",None])
def test_process_id_is_required_strict_positive_integer(transfer,kind,value):
    with pytest.raises(ValueError):params(transfer,kind,process_id=value)
    transfer.connect.assert_not_called()


@pytest.mark.parametrize("field",["process_id","expected_document_path","source_path","source_sha256","output_path","qualification_only","action"])
def test_common_required_fields_cannot_be_omitted(transfer,field):
    data=values(transfer);data.pop(field)
    with pytest.raises(ValueError):server.SolidWorksPartTransferInput(**data)


@pytest.mark.parametrize("value",[False,1,0,"true",None])
def test_qualification_is_literal_json_true(transfer,value):
    with pytest.raises(ValueError):params(transfer,qualification_only=value)


@pytest.mark.parametrize("value",[1,0,"true","false",None])
def test_delta_ack_is_strict_boolean(transfer,value):
    with pytest.raises(ValueError):params(transfer,acknowledge_delta_only=value)


@pytest.mark.parametrize("mode,ack",[("add_delta",False),("subtract_delta",False),("replace_body",True)])
def test_wrong_mode_acknowledgement_is_rejected(transfer,mode,ack):
    with pytest.raises(ValueError):params(transfer,mode=mode,acknowledge_delta_only=ack)
    transfer.part.assert_not_called()


@pytest.mark.parametrize("field",["source_sha256","donor_sha256","expected_state_sha256"])
@pytest.mark.parametrize("bad",["A"*64,"a"*63,"g"*64,True])
def test_hashes_are_strict_lowercase_sha256(transfer,field,bad):
    with pytest.raises(ValueError):params(transfer,action="apply",**{field:bad})


@pytest.mark.parametrize("kind",["part","copy"])
@pytest.mark.parametrize("extra",[{"receipt_path":"unused.json"},{"expected_state_sha256":"a"*64}])
def test_prepare_rejects_apply_only_fields(transfer,kind,extra):
    with pytest.raises(ValueError):params(transfer,kind,**extra)


@pytest.mark.parametrize("kind",["part","copy"])
@pytest.mark.parametrize("field",["receipt_path","expected_state_sha256"])
def test_apply_requires_receipt_and_state_hash(transfer,kind,field):
    with pytest.raises(ValueError):params(transfer,kind,"apply",**{field:None})


@pytest.mark.parametrize("field",["output_path","roundtrip_step_path","receipt_path"])
def test_existing_outputs_and_receipts_are_immutable(transfer,field):
    suffix={"output_path":".sldprt","roundtrip_step_path":".step","receipt_path":".json"}[field]
    existing=transfer.tmp_path/("existing"+suffix);existing.write_bytes(b"immutable")
    with pytest.raises(ValueError):params(transfer,action="apply",**{field:str(existing)})
    assert existing.read_bytes()==b"immutable"
    transfer.part.assert_not_called()


@pytest.mark.parametrize("field",["expected_document_path","source_path","output_path","donor_step_path","roundtrip_step_path","receipt_path"])
def test_relative_paths_are_rejected(transfer,field):
    with pytest.raises(ValueError):params(transfer,action="apply",**{field:"relative.sldprt"})


@pytest.mark.parametrize("field",["source_path","donor_step_path"])
def test_source_files_must_exist(transfer,field):
    suffix=".step" if field=="donor_step_path" else ".sldprt"
    with pytest.raises(ValueError):params(transfer,**{field:str(transfer.tmp_path/("missing"+suffix))})


@pytest.mark.parametrize("kind,field",[("part","source_path"),("part","output_path"),("copy","source_path"),("copy","output_path")])
def test_source_output_document_types_are_fixed(transfer,kind,field):
    suffix="sldasm" if kind=="part" else "sldprt"
    path=transfer.files["source."+suffix] if field=="source_path" else str(transfer.tmp_path/("wrong."+suffix))
    with pytest.raises(ValueError):params(transfer,kind,**{field:path})


@pytest.mark.parametrize("bad",[None,(),"files",False])
def test_frozen_files_requires_a_json_list(transfer,bad):
    with pytest.raises(ValueError):params(transfer,frozen_files=bad)


def test_frozen_files_bound_and_nested_contract(transfer):
    good={"path":transfer.files["anchor.sldasm"],"sha256":"a"*64}
    assert params(transfer).frozen_files==[]
    with pytest.raises(ValueError):params(transfer,frozen_files=[good]*513)
    with pytest.raises(ValueError):params(transfer,frozen_files=[good|{"path":"relative.sldasm"}])
    with pytest.raises(ValueError):params(transfer,frozen_files=[good|{"sha256":"A"*64}])
    with pytest.raises(ValueError):params(transfer,frozen_files=[good|{"delete":True}])


@pytest.mark.parametrize("bad",[None,(),"replace",False,[]])
def test_replacements_requires_nonempty_json_list(transfer,bad):
    with pytest.raises(ValueError):params(transfer,"copy",replacements=bad)


def test_replacement_limits_duplicate_old_and_same_native_type(transfer):
    row=values(transfer,"copy")["replacements"][0]
    for rows in ([row]*9,[row,row], [row|{"old_path":"relative.sldprt"}],
                 [row|{"new_path":transfer.files["source.sldasm"]}],
                 [row|{"new_path":transfer.files["donor.step"]}],
                 [row|{"old_sha256":"A"*64}], [row|{"new_sha256":True}]):
        with pytest.raises(ValueError):params(transfer,"copy",replacements=rows)
    transfer.copy.assert_not_called()


def test_replacement_order_and_nested_hashes_are_forwarded(transfer):
    first=values(transfer,"copy")["replacements"][0]
    second=dict(old_path=transfer.files["source.sldasm"],old_sha256="1"*64,
                new_path=str(transfer.tmp_path/"replacement.sldasm"),new_sha256="2"*64)
    call("copy",params(transfer,"copy",replacements=[second,first]))
    assert transfer.copy.call_args.kwargs["replacements"]==[second,first]


@pytest.mark.parametrize("kind",["part","copy"])
def test_registration_response_format_and_core_errors(transfer,kind):
    annotation=server.mcp._tool_manager._tools[TOOLS[kind]].annotations
    assert not annotation.readOnlyHint and not annotation.idempotentHint and annotation.destructiveHint
    native=getattr(transfer,kind)
    output=getattr(server,TOOLS[kind])(params(transfer,kind,response_format="markdown"))
    assert output.startswith("# review_required")
    native.side_effect=RuntimeError("native transfer failed")
    assert call(kind,params(transfer,kind))["status"]=="error"


@pytest.mark.parametrize("field",["launch_new_instance","addin_clsid","save_all","generate_toolpath"])
def test_unrelated_mutators_and_cam_inputs_are_forbidden(transfer,field):
    with pytest.raises(ValueError):params(transfer,**{field:True})
    transfer.part.assert_not_called();transfer.cam_target.assert_not_called()


def test_continuation_schema_requires_existing_copy_and_paired_receipt(transfer):
    output=transfer.tmp_path/'copy.sldprt';output.write_bytes(b'owned copied part')
    prior=transfer.tmp_path/'prior.json';prior.write_text('{}')
    p=params(transfer,mode='subtract_delta',acknowledge_delta_only=True,
        prior_transfer_receipt_path=str(prior),prior_transfer_receipt_sha256='f'*64)
    call('part',p)
    assert transfer.part.call_args.kwargs['prior_transfer_receipt_path']==str(prior)
    with pytest.raises(ValueError):params(transfer,mode='add_delta',acknowledge_delta_only=True,
        prior_transfer_receipt_path=str(prior))
    with pytest.raises(ValueError):params(transfer,prior_transfer_receipt_path=str(prior),prior_transfer_receipt_sha256='f'*64)


@pytest.fixture
def finalization(transfer):
    prior=transfer.tmp_path/"completed_transfer.json";prior.write_text('{"saved":true}',encoding="utf8")
    transfer.model.GetPathName=transfer.files["source.sldprt"]
    transfer.model.GetTitle="source.sldprt";transfer.model.GetType=1
    transfer.finalize_values=dict(process_id=731,expected_document_path=transfer.files["source.sldprt"],
        transfer_receipt_path=str(prior),transfer_receipt_sha256="a"*64,expected_output_sha256="b"*64,expected_anchor_sha256="c"*64,
        receipt_path=str(transfer.tmp_path/"finalized.json"))
    return transfer


def finalize_params(p,**changes):
    return server.SolidWorksFinalizePartTransferInput(**(p.finalize_values|changes))


def finalize_call(p):
    return json.loads(server.solidworks_finalize_part_transfer(p))


def test_finalize_routes_only_existing_transfer_recovery_with_exact_guards(finalization):
    p=finalize_params(finalization)
    assert finalize_call(p)==finalization.finalize.return_value
    finalization.finalize.assert_called_once_with(finalization.sw,
        **p.model_dump(exclude={"response_format","expected_document_title"}))
    finalization.active.assert_called_once_with(p)
    finalization.connect.assert_called_once_with(wait_seconds=1)
    finalization.part.assert_not_called();finalization.copy.assert_not_called();finalization.cam_target.assert_not_called()
    assert finalization.runners==[(server.ResponseFormat.JSON,True)]


@pytest.mark.parametrize("selected",[None,999,"731",True])
def test_finalize_selected_pid_rejects_before_connection(finalization,monkeypatch,selected):
    monkeypatch.setattr(server,"_selected_process_id",selected)
    assert finalize_call(finalize_params(finalization))["status"]=="error"
    finalization.active.assert_not_called();finalization.connect.assert_not_called();finalization.finalize.assert_not_called()


def test_finalize_wrong_current_document_blocks_core(finalization):
    finalization.model.GetPathName=finalization.files["old.sldprt"]
    assert finalize_call(finalize_params(finalization))["status"]=="error"
    finalization.finalize.assert_not_called();finalization.part.assert_not_called();finalization.cam_target.assert_not_called()


@pytest.mark.parametrize("value",[True,False,0,-1,731.0,"731",None])
def test_finalize_pid_is_strict_positive(finalization,value):
    with pytest.raises(ValueError):finalize_params(finalization,process_id=value)
    finalization.connect.assert_not_called()


@pytest.mark.parametrize("field",["process_id","expected_document_path","transfer_receipt_path","transfer_receipt_sha256","expected_output_sha256","expected_anchor_sha256","receipt_path"])
def test_finalize_requires_all_recovery_identity_fields(finalization,field):
    values=finalization.finalize_values.copy();values.pop(field)
    with pytest.raises(ValueError):server.SolidWorksFinalizePartTransferInput(**values)


@pytest.mark.parametrize("field",["transfer_receipt_sha256","expected_output_sha256","expected_anchor_sha256"])
@pytest.mark.parametrize("bad",["A"*64,"a"*63,"g"*64,True,None])
def test_finalize_requires_exact_lowercase_hashes(finalization,field,bad):
    with pytest.raises(ValueError):finalize_params(finalization,**{field:bad})


@pytest.mark.parametrize("field",["expected_document_path","transfer_receipt_path","receipt_path"])
def test_finalize_paths_absolute_and_strict(finalization,field):
    for value in ("relative.json",True,None):
        with pytest.raises(ValueError):finalize_params(finalization,**{field:value})


@pytest.mark.parametrize("field",["expected_document_path","transfer_receipt_path"])
def test_finalize_source_evidence_must_exist_with_exact_types(finalization,field):
    missing=finalization.tmp_path/("absent.sldprt" if field=="expected_document_path" else "absent.json")
    with pytest.raises(ValueError):finalize_params(finalization,**{field:str(missing)})
    with pytest.raises(ValueError):finalize_params(finalization,**{field:finalization.files["anchor.sldasm"]})


def test_finalize_existing_receipt_immutable_and_parent_required(finalization):
    prior=Path(finalization.finalize_values["transfer_receipt_path"])
    original=prior.read_bytes()
    with pytest.raises(ValueError):finalize_params(finalization,receipt_path=str(prior))
    assert prior.read_bytes()==original
    with pytest.raises(ValueError):finalize_params(finalization,receipt_path=str(finalization.tmp_path/"absent"/"receipt.json"))
    with pytest.raises(ValueError):finalize_params(finalization,receipt_path=str(finalization.tmp_path/"receipt.txt"))


@pytest.mark.parametrize("field",["mode","action","donor_step_path","output_path","roundtrip_step_path","save_all","launch_new_instance","addin_clsid"])
def test_finalize_rejects_mutation_inputs_or_alternate_outputs(finalization,field):
    with pytest.raises(ValueError):finalize_params(finalization,**{field:"forbidden"})
    finalization.finalize.assert_not_called()


def test_finalize_tool_annotations_and_core_failure(finalization):
    annotation=server.mcp._tool_manager._tools["solidworks_finalize_part_transfer"].annotations
    assert not annotation.readOnlyHint and not annotation.idempotentHint and annotation.destructiveHint
    output=server.solidworks_finalize_part_transfer(finalize_params(finalization,response_format="markdown"))
    assert output.startswith("# review_required")
    finalization.finalize.side_effect=RuntimeError("Receipt does not authorize an unattempted export")
    assert finalize_call(finalize_params(finalization))["status"]=="error"
    finalization.part.assert_not_called();finalization.copy.assert_not_called()


@pytest.mark.parametrize("policy",["strict","diagnostic"])
def test_delta_volume_policy_routes_explicitly(transfer,policy):
    p=params(transfer,mode="add_delta",acknowledge_delta_only=True,delta_volume_policy=policy)
    assert p.delta_volume_policy==policy
    call("part",p)
    assert transfer.part.call_args.kwargs["delta_volume_policy"]==policy


def test_delta_volume_policy_defaults_to_strict(transfer):
    p=params(transfer)
    assert p.delta_volume_policy=="strict"
    call("part",p)
    assert transfer.part.call_args.kwargs["delta_volume_policy"]=="strict"


@pytest.mark.parametrize("value",[True,False,None,1,"STRICT","other",["diagnostic"]])
def test_delta_volume_policy_rejects_other_types_and_values(transfer,value):
    with pytest.raises(ValueError):params(transfer,delta_volume_policy=value)
    transfer.part.assert_not_called()


@pytest.fixture
def cleanup_request(transfer):
    prior=transfer.tmp_path/"cleanup_prior.json";prior.write_text('{}',encoding="utf8")
    transfer.cleanup_values=dict(process_id=731,transfer_receipt_path=str(prior),
        transfer_receipt_sha256="a"*64,expected_output_current_sha256="b"*64,
        receipt_path=str(transfer.tmp_path/"cleanup.json"))
    return transfer


def cleanup_params(p,**changes):
    return server.SolidWorksCleanupPartTransferInput(**(p.cleanup_values|changes))


def cleanup_call(p):return json.loads(server.solidworks_cleanup_part_transfer(p))


def test_cleanup_connects_without_active_document_and_never_routes_to_geometry(cleanup_request):
    p=cleanup_params(cleanup_request)
    cleanup_request.sw.ActiveDoc=None
    cleanup_request.connect.return_value=(cleanup_request.sw,None)
    assert cleanup_call(p)==cleanup_request.cleanup.return_value
    cleanup_request.connect.assert_called_once_with(wait_seconds=1)
    cleanup_request.cleanup.assert_called_once_with(cleanup_request.sw,**p.model_dump(exclude={"response_format"}))
    cleanup_request.active.assert_not_called();cleanup_request.cam_target.assert_not_called()
    cleanup_request.part.assert_not_called();cleanup_request.copy.assert_not_called();cleanup_request.finalize.assert_not_called()
    assert cleanup_request.runners==[(server.ResponseFormat.JSON,True)]


@pytest.mark.parametrize("selected",[None,999,"731",True])
def test_cleanup_selected_pid_fails_before_connection(cleanup_request,monkeypatch,selected):
    monkeypatch.setattr(server,"_selected_process_id",selected)
    assert cleanup_call(cleanup_params(cleanup_request))["status"]=="error"
    cleanup_request.connect.assert_not_called();cleanup_request.cleanup.assert_not_called();cleanup_request.active.assert_not_called()


@pytest.mark.parametrize("value",[True,False,0,-1,731.0,"731",None])
def test_cleanup_requires_strict_positive_pid(cleanup_request,value):
    with pytest.raises(ValueError):cleanup_params(cleanup_request,process_id=value)


@pytest.mark.parametrize("field",["process_id","transfer_receipt_path","transfer_receipt_sha256","expected_output_current_sha256","receipt_path"])
def test_cleanup_fields_all_required(cleanup_request,field):
    values=cleanup_request.cleanup_values.copy();values.pop(field)
    with pytest.raises(ValueError):server.SolidWorksCleanupPartTransferInput(**values)


@pytest.mark.parametrize("field",["transfer_receipt_sha256","expected_output_current_sha256"])
@pytest.mark.parametrize("value",[True,None,"A"*64,"f"*63,"g"*64])
def test_cleanup_hashes_strict_lowercase(cleanup_request,field,value):
    with pytest.raises(ValueError):cleanup_params(cleanup_request,**{field:value})


@pytest.mark.parametrize("field",["transfer_receipt_path","receipt_path"])
@pytest.mark.parametrize("value",[True,None,"relative.json"])
def test_cleanup_paths_strict_absolute(cleanup_request,field,value):
    with pytest.raises(ValueError):cleanup_params(cleanup_request,**{field:value})


def test_cleanup_evidence_exists_and_new_receipt_is_immutable(cleanup_request):
    prior=Path(cleanup_request.cleanup_values["transfer_receipt_path"])
    with pytest.raises(ValueError):cleanup_params(cleanup_request,transfer_receipt_path=str(cleanup_request.tmp_path/"missing.json"))
    with pytest.raises(ValueError):cleanup_params(cleanup_request,transfer_receipt_path=cleanup_request.files["source.sldprt"])
    with pytest.raises(ValueError):cleanup_params(cleanup_request,receipt_path=str(prior))
    with pytest.raises(ValueError):cleanup_params(cleanup_request,receipt_path=str(cleanup_request.tmp_path/"absent"/"result.json"))
    assert prior.read_text()=="{}"


@pytest.mark.parametrize("field",["expected_document_path","expected_document_title","action","mode","donor_step_path","output_path","save_all","launch_new_instance"])
def test_cleanup_extra_inputs_forbidden(cleanup_request,field):
    with pytest.raises(ValueError):cleanup_params(cleanup_request,**{field:"unexpected"})
    cleanup_request.cleanup.assert_not_called()


def test_cleanup_annotation_format_and_error_propagation(cleanup_request):
    annotation=server.mcp._tool_manager._tools["solidworks_cleanup_part_transfer"].annotations
    assert not annotation.readOnlyHint and annotation.destructiveHint and not annotation.idempotentHint
    result=server.solidworks_cleanup_part_transfer(cleanup_params(cleanup_request,response_format="markdown"))
    assert result.startswith("# review_required")
    cleanup_request.cleanup.side_effect=RuntimeError("Receipt does not identify the anchor")
    assert cleanup_call(cleanup_params(cleanup_request))["status"]=="error"
    cleanup_request.active.assert_not_called()



def test_open_document_inventory_needs_only_pid_and_no_active_document(transfer):
    transfer.sw.ActiveDoc=None;transfer.connect.return_value=(transfer.sw,None)
    p=server.SolidWorksOpenDocumentsInput(process_id=731)
    result=json.loads(server.solidworks_inspect_open_documents(p))
    assert result==transfer.inventory.return_value
    transfer.inventory.assert_called_once_with(transfer.sw,process_id=731)
    transfer.connect.assert_called_once_with(wait_seconds=1)
    transfer.active.assert_not_called();transfer.cam_target.assert_not_called()
    transfer.cleanup.assert_not_called();transfer.finalize.assert_not_called();transfer.part.assert_not_called()
    assert transfer.runners==[(server.ResponseFormat.JSON,True)]


@pytest.mark.parametrize("selected",[None,999,"731",True])
def test_open_document_inventory_checks_pid_before_connection(transfer,monkeypatch,selected):
    monkeypatch.setattr(server,"_selected_process_id",selected)
    result=json.loads(server.solidworks_inspect_open_documents(server.SolidWorksOpenDocumentsInput(process_id=731)))
    assert result["status"]=="error"
    transfer.connect.assert_not_called();transfer.inventory.assert_not_called();transfer.active.assert_not_called()


@pytest.mark.parametrize("value",[True,False,0,-1,731.0,"731",None])
def test_open_document_inventory_strict_pid(value):
    with pytest.raises(ValueError):server.SolidWorksOpenDocumentsInput(process_id=value)


def test_open_document_inventory_pid_required_and_extra_document_controls_forbidden():
    with pytest.raises(ValueError):server.SolidWorksOpenDocumentsInput()
    for field in ("expected_document_path","expected_document_title","action","save_all","close_all","receipt_path"):
        with pytest.raises(ValueError):server.SolidWorksOpenDocumentsInput(process_id=731,**{field:"unexpected"})


def test_open_document_inventory_readonly_annotations_and_native_error(transfer):
    annotation=server.mcp._tool_manager._tools["solidworks_inspect_open_documents"].annotations
    assert annotation.readOnlyHint and annotation.idempotentHint and not annotation.destructiveHint
    output=server.solidworks_inspect_open_documents(server.SolidWorksOpenDocumentsInput(process_id=731,response_format="markdown"))
    assert output.startswith("# ok")
    transfer.inventory.side_effect=RuntimeError("Native enumeration failed")
    result=json.loads(server.solidworks_inspect_open_documents(server.SolidWorksOpenDocumentsInput(process_id=731)))
    assert result["status"]=="error"
    transfer.active.assert_not_called()



@pytest.mark.parametrize("acknowledge",[False,True])
def test_cleanup_unexpected_import_acknowledgement_routes_explicitly(cleanup_request,acknowledge):
    p=cleanup_params(cleanup_request,acknowledge_discard_unexpected_import=acknowledge)
    assert cleanup_call(p)==cleanup_request.cleanup.return_value
    assert cleanup_request.cleanup.call_args.kwargs["acknowledge_discard_unexpected_import"] is acknowledge
    cleanup_request.active.assert_not_called();cleanup_request.part.assert_not_called()


def test_cleanup_unexpected_import_discard_is_disabled_by_default(cleanup_request):
    p=cleanup_params(cleanup_request)
    assert p.acknowledge_discard_unexpected_import is False
    cleanup_call(p)
    assert cleanup_request.cleanup.call_args.kwargs["acknowledge_discard_unexpected_import"] is False


@pytest.mark.parametrize("value",[1,0,"true","false",None])
def test_cleanup_unexpected_import_acknowledgement_requires_json_boolean(cleanup_request,value):
    with pytest.raises(ValueError):cleanup_params(cleanup_request,acknowledge_discard_unexpected_import=value)
    cleanup_request.connect.assert_not_called();cleanup_request.cleanup.assert_not_called()
