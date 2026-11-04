"""完成长度探测后一次新角度设置；保留旧证据，未知结果或同字段不能重放。"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from test_sw_cam_turn_holder_dimensions import probe,ref
from test_sw_cam_turn_holder_write_through import length_probe
from scripts import sw_cam_turn_holder_dimensions as cam
from scripts import sw_cam_turn_holder_continuation as c

@pytest.fixture
def continued(length_probe):
    q=length_probe;p=q.p;old=q.run();assert old["readback_verified"],old
    old_receipt=p.tmp_path/"completed_length.json";p.receipt.rename(old_receipt)
    marker=Path(old["marker_path"]);m=json.loads(marker.read_text());m["receipt_path"]=str(old_receipt);marker.write_text(json.dumps(m),encoding="utf-8")
    pins=dict(marker_path=str(marker),marker_sha256=cam._file_hash(marker),receipt_path=str(old_receipt),receipt_sha256=cam._file_hash(old_receipt))
    p.document["needs_save"]=False;p.copy.write_bytes(b"saved after completed probe")
    p.defaults.update(expected_source_sha256=cam._file_hash(p.copy),values_native={"LeadAngle":-32.},completed_length_probe=pins)
    p.state["extra_assignment"]=True;p.first.values["HolderShape"]=1
    p.state["holder_file_path"]=str(p.tmp_path/"holder.stl");Path(p.state["holder_file_path"]).write_bytes(b"custom holder")
    p.tool.dimensions.update(NoseRadius=.2,InscribedCircle=9.525,Thickness=3.96875)
    p.legacy_marker=marker;p.legacy_receipt=old_receipt;p.legacy_bytes=(marker.read_bytes(),old_receipt.read_bytes());p.pins=pins;p.old=old
    return p


def test_new_field_success_preserves_legacy_and_exact_custom_file(continued):
    p=continued;prepared=p.prepare();assert prepared["status"]=="prepared" and prepared["apply_eligible"],prepared
    assert not p.receipt.exists() and len(list(p.marker_root.iterdir()))==1
    result=p.apply(prepared);assert result["readback_verified"] and result["holder_file_fields_preserved"],result
    assert p.state["writes"]==[("ShankLength",200.),("LeadAngle",-32.)]
    assert result["before"]["selected_holder_file"]==result["after"]["selected_holder_file"]
    assert len(result["affected_operations"])==2 and result["after"]["selected_tool"]["holder"]["dimensions_native"]["ShankLength"]==200.
    assert (p.legacy_marker.read_bytes(),p.legacy_receipt.read_bytes())==p.legacy_bytes
    claim=json.loads(Path(result["marker_path"]).read_text());assert claim["scope"]==c.SCOPE and claim["field"]=="LeadAngle"
    assert len(list(p.marker_root.iterdir()))==2 and json.loads(p.receipt.read_text())==result

@pytest.mark.parametrize("values",[{"ShankLength":190.},{"BoringBarDiameter":19.},{"LeadAngle":-32.,"ShankLength":190.}])
def test_only_new_Lead_field_admitted(continued,values):
    r=continued.prepare(values_native=values);assert r["status"]=="error" and r["reason_code"]=="CONTINUATION_LEAD_ONLY"
    assert continued.state["writes"]==[("ShankLength",200.)]


def test_default_previous_marker_refusal_is_readable(continued):
    r=continued.prepare(completed_length_probe=None)
    assert r["status"]=="error" and r["reason_code"]=="HOLDER_PRIOR_ATTEMPT_EXISTS" and "No setter" in r["reason"]
    assert not r["mutation_attempted"]

@pytest.mark.parametrize("which",["marker_hash","receipt_hash","wrong_marker_path","file_identity","tool","unknown_outcome","pending","extra_setter","failed_setter","final_digest","quiet_events","wrong_scope"])
def test_reject_invalid_or_unknown_prior_proof_before_CAM(continued,which):
    p=continued;before=p.state["snapshots"];pins=deepcopy(p.pins)
    if which=="marker_hash":pins["marker_sha256"]="a"*64
    elif which=="receipt_hash":pins["receipt_sha256"]="a"*64
    elif which=="wrong_marker_path":pins["marker_path"]=str(p.tmp_path/"other.json")
    elif which in ("file_identity","tool"):
        data=json.loads(p.legacy_marker.read_text())
        if which=="file_identity":data["copy_file_identity"]["inode"]+=1
        else:data["tool_native_id"]+=1
        p.legacy_marker.write_text(json.dumps(data),encoding="utf-8");pins["marker_sha256"]=cam._file_hash(p.legacy_marker)
    else:
        data=json.loads(p.legacy_receipt.read_text())
        if which=="unknown_outcome":data["status"]="uncertain"
        elif which=="pending":data["native_dispatch_pending"]=True
        elif which=="extra_setter":data["setters"].append(deepcopy(data["setters"][0]))
        elif which=="failed_setter":data["setters"][0]["returned"]=False
        elif which=="final_digest":data["final_state_sha256"]="b"*64
        elif which=="quiet_events":data["messages"]["event_count"]=1
        else:data["scope"]=cam.SCOPE
        p.legacy_receipt.write_text(json.dumps(data),encoding="utf-8");pins["receipt_sha256"]=cam._file_hash(p.legacy_receipt)
    r=p.prepare(completed_length_probe=pins)
    assert r["status"]=="error" and r["reason_code"] in ("CONTINUATION_PROOF_INVALID","CONTINUATION_EVIDENCE_CHANGED"),r
    assert p.state["snapshots"]==before and len(p.state["writes"])==1


def test_current_old_value_must_match_in_fresh_views(continued):
    p=continued;p.first.values["ShankLength"]=199.
    r=p.prepare();assert r["status"]=="error" and r["reason_code"]=="CONTINUATION_CURRENT_LENGTH_CHANGED"
    assert r["captures"][0]["state"]["selected_tool"]["holder"]["dimensions_native"]["ShankLength"]==199.
    assert len(p.state["writes"])==1


def test_prior_owner_cannot_silently_disappear(continued):
    p=continued;old=p.old["after"]["operation_tools"][0];identity=cam.files(p.defaults,p.defaults["protected_part_pins"])
    evidence=c.load_completed_length_probe(p.pins,p.legacy_marker,identity,p.defaults)
    state=p.prepare()["before"];state["observed_operation_tools"][0]["operation_native_id"]=999
    with pytest.raises(c.ContinuationGuardError,match="prior operation owner"):c.verify_current_completed_length(state,evidence,101)


def test_proof_change_between_prepare_and_apply_no_put(continued):
    p=continued;prepared=p.prepare();p.legacy_receipt.write_bytes(p.legacy_receipt.read_bytes()+b" ")
    r=p.apply(prepared);assert r["status"]=="error" and r["reason_code"]=="CONTINUATION_EVIDENCE_CHANGED"
    assert len(p.state["writes"])==1


def test_partial_Lead_failure_keeps_actual_and_forbids_new_receipt_or_saved_hash(continued):
    p=continued
    def fail(*args):raise OSError("do not expose private error text")
    p.state["after_write"]=fail;r=p.apply();assert r["status"]=="uncertain" and not r["readback_verified"]
    assert r["after"]["selected_tool"]["holder"]["dimensions_native"]["LeadAngle"]==-32.
    assert json.loads(p.receipt.read_text())==r and len(p.state["writes"])==2
    p.copy.write_bytes(b"another saved hash");p.defaults["expected_source_sha256"]=cam._file_hash(p.copy);p.document["needs_save"]=False
    retry=p.prepare();assert retry["reason_code"]=="HOLDER_LEAD_ALREADY_CLAIMED"
    assert len(p.state["writes"])==2 and (p.legacy_marker.read_bytes(),p.legacy_receipt.read_bytes())==p.legacy_bytes


def test_field_marker_race_blocks_second_claim_before_setter(continued,monkeypatch):
    p=continued;prepared=p.prepare();original=cam._write_receipt
    def race(path,data,create=False):
        if create and Path(path).name.startswith("turn_holder_lead_after_length_"):
            original(path,{"claimed_by_another_request":True},create=True)
        return original(path,data,create=create)
    monkeypatch.setattr(cam,"_write_receipt",race)
    r=p.apply(prepared);assert r["status"]=="error" and not r["mutation_attempted"] and len(p.state["writes"])==1
    assert p.prepare()["reason_code"]=="HOLDER_LEAD_ALREADY_CLAIMED"


def test_unknown_exception_message_is_not_promoted():
    assert c.known_reason(ValueError("secret arbitrary text"))=={}
