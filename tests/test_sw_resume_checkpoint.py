"""Pure filesystem continuation evidence; no CAD or COM dependencies."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
import pytest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import sw_resume_checkpoint as core


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path):
    artifact=tmp_path/"part.sldprt";artifact.write_bytes(b"saved native bytes")
    receipt=tmp_path/"receipt.json";receipt.write_text(json.dumps({"saved":True,"generated":True,"count":40,"a/b":{"~field":[True]}}))
    failure=tmp_path/"failed.json";failure.write_text(json.dumps({"returned":False}))
    status=tmp_path/"STATUS.json"
    manifest={"schema_version":1,"current_artifacts":[{"id":"part","path":str(artifact),"sha256":digest(artifact),"role":"current saved part"}],
        "milestones":[{"id":"saved","label":"One part saved","state":"saved","evidence_checks":[{"path":str(receipt),"sha256":digest(receipt),"json_pointer":"/saved","expected":True}],"limitations":["No live RAM or manufacturing approval"]},
            {"id":"later","label":"Unfinished milling","state":"planned","evidence_checks":[],"limitations":["Not done"]}],
        "failed_attempts":[{"id":"old_candidate","hypothesis":"unchanged old candidate","evidence_refs":[{"path":str(failure),"sha256":digest(failure),"json_pointer":"/returned","expected":False}],"disposition":"Do not repeat unchanged"}],
        "next_action":{"id":"next","label":"Single next candidate","preconditions":[{"kind":"artifact","id":"part"},{"kind":"milestone","id":"saved","required_state":"saved"}],"human_preconditions":["Root checks live PID/document"],"success_criteria":["Specific readback"],"do_not_repeat":["Old candidate"]}}
    def write():status.write_text(json.dumps({"other_status_fields":"preserved","resume_checkpoint":manifest},ensure_ascii=False),encoding="utf-8")
    def run():write();return core.read_resume_checkpoint(str(status))
    return type("Case",(),dict(tmp_path=tmp_path,artifact=artifact,receipt=receipt,failure=failure,status=status,manifest=manifest,write=staticmethod(write),run=staticmethod(run)))()


def test_valid_static_checkpoint_is_ready_without_live_or_approval_claim(case):
    result=case.run()
    assert result["status"]=="ok" and result["continuation_ready_by_saved_evidence"]
    assert result["next_action"]["status"]=="continuation_ready_by_saved_evidence"
    assert not result["live_state_verified"] and not result["native_mutation_authorized"]
    assert not result["next_action"]["human_preconditions_verified"]
    assert result["evidence_passed"][0]["declared_state"]=="saved"
    assert result["summary"]["counts_by_declared_state"]["verified"]==0
    assert result["pending"][0]["declared_state"]=="planned" and result["findings"]==[]
    assert result["status_sha256"]==result["status_sha256_after"]==digest(case.status)


def test_artifact_tamper_is_stale_and_blocks_only_static_ready(case):
    case.artifact.write_bytes(b"tampered")
    result=case.run()
    assert not result["continuation_ready_by_saved_evidence"]
    assert result["findings"][0]["code"]=="sha256_mismatch"
    assert result["findings"][0]["actual_sha256"]==digest(case.artifact)


@pytest.mark.parametrize("actual",[1,0,"true",None,False])
def test_receipt_boolean_is_type_strict_even_after_new_hash(case,actual):
    case.receipt.write_text(json.dumps({"saved":actual}))
    case.manifest["milestones"][0]["evidence_checks"][0]["sha256"]=digest(case.receipt)
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    issue=next(x for x in result["findings"] if x["code"]=="receipt_value_mismatch")
    assert issue["expected"] is True and issue["actual_python_type"]==type(actual).__name__


@pytest.mark.parametrize("which",["artifact","receipt","failure"])
def test_any_missing_referenced_file_blocks_readiness(case,which):
    getattr(case,which).unlink()
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert any(x["code"]=="missing_file" for x in result["findings"])


def test_generated_is_not_saved_even_when_receipt_boolean_true(case):
    case.manifest["milestones"][0]["state"]="generated"
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert result["evidence_passed"][0]["declared_state"]=="generated"
    assert result["summary"]["counts_by_declared_state"]["saved"]==0
    assert any(x["code"]=="declared_state_mismatch" for x in result["findings"])


def test_reopened_not_implicitly_promoted_to_verified(case):
    case.manifest["milestones"][0]["state"]="reopened"
    case.manifest["next_action"]["preconditions"][1]["required_state"]="verified"
    assert not case.run()["continuation_ready_by_saved_evidence"]


def test_planned_without_checks_pending_and_only_blocks_if_required(case):
    assert case.run()["continuation_ready_by_saved_evidence"]
    case.manifest["next_action"]["preconditions"].append({"kind":"milestone","id":"later","required_state":"planned"})
    assert not case.run()["continuation_ready_by_saved_evidence"]


def test_verified_without_checks_is_invalid_manifest(case):
    case.manifest["milestones"][1]["state"]="verified"
    result=case.run();assert result["status"]=="error" and not result["continuation_ready_by_saved_evidence"]


@pytest.mark.parametrize("pointer",["/a~1b/~0field/0","/generated",""])
def test_RFC6901_escape_array_and_root_pointer(case,pointer):
    expected=True if pointer else json.loads(case.receipt.read_text())
    case.manifest["milestones"][0]["evidence_checks"][0].update(json_pointer=pointer,expected=expected)
    assert case.run()["continuation_ready_by_saved_evidence"]


@pytest.mark.parametrize("pointer",["/missing","/a~1b/~0field/01","/saved/child"])
def test_missing_or_noncanonical_array_pointer_blocks(case,pointer):
    case.manifest["milestones"][0]["evidence_checks"][0]["json_pointer"]=pointer
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert any(x["code"]=="json_pointer_missing" for x in result["findings"])


@pytest.mark.parametrize("change",["schema_bool","relative","badsha","unknownfield","badtilde","duplicateid","expected_too_large","unknowncondition"])
def test_manifest_schema_refuses_ambiguous_inputs(case,change):
    if change=="schema_bool":case.manifest["schema_version"]=True
    elif change=="relative":case.manifest["current_artifacts"][0]["path"]="relative.sldprt"
    elif change=="badsha":case.manifest["current_artifacts"][0]["sha256"]="AB"*32
    elif change=="unknownfield":case.manifest["next_action"]["execute"]="never"
    elif change=="badtilde":case.manifest["milestones"][0]["evidence_checks"][0]["json_pointer"]="/a~2b"
    elif change=="duplicateid":case.manifest["milestones"].append(deepcopy(case.manifest["milestones"][0]))
    elif change=="expected_too_large":case.manifest["milestones"][0]["evidence_checks"][0]["expected"]="x"*5000
    else:case.manifest["next_action"]["preconditions"][0]["kind"]="execute"
    assert case.run()["status"]=="error"


def test_receipt_hash_tamper_blocks_before_trusting_boolean(case):
    case.receipt.write_text('{"saved":true,"added":1}')
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert any(x["code"]=="sha256_mismatch" and x["scope"]=="milestone:saved" for x in result["findings"])


def test_failed_attempt_hash_only_reference_still_checks_bytes(case):
    ref=case.manifest["failed_attempts"][0]["evidence_refs"][0]
    ref.pop("json_pointer");ref.pop("expected")
    assert case.run()["continuation_ready_by_saved_evidence"]
    case.failure.write_bytes(b"changed")
    assert not case.run()["continuation_ready_by_saved_evidence"]


def test_unknown_precondition_id_is_not_silently_skipped(case):
    case.manifest["next_action"]["preconditions"][0]["id"]="absent"
    result=case.run();assert any(x["code"]=="unknown_artifact_id" for x in result["findings"])
    assert not result["continuation_ready_by_saved_evidence"]


def test_status_edit_during_evidence_scan_is_never_accepted(case,monkeypatch):
    original=core._Reader.read;changed=[False]
    def read(self,path,*args,**kwargs):
        result=original(self,path,*args,**kwargs)
        if Path(path)==case.artifact and not changed[0]:
            changed[0]=True;case.status.write_text(case.status.read_text()+" ")
        return result
    monkeypatch.setattr(core._Reader,"read",read)
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert any(x["code"]=="stale_during_read" for x in result["findings"])


def test_file_modification_after_hash_is_caught_by_final_stability(case,monkeypatch):
    original=core._Reader.read
    def read(self,path,*args,**kwargs):
        result=original(self,path,*args,**kwargs)
        if Path(path)==case.failure:case.artifact.write_bytes(b"changed later")
        return result
    monkeypatch.setattr(core._Reader,"read",read)
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert any(x["scope"]=="file_stability" for x in result["findings"])


@pytest.mark.parametrize("constant",["MAX_ARTIFACT_BYTES","MAX_TOTAL_BYTES","MAX_EVIDENCE_BYTES","MAX_STATUS_BYTES"])
def test_stream_byte_limits_fail_closed(case,monkeypatch,constant):
    monkeypatch.setattr(core,constant,1)
    result=case.run();assert not result["continuation_ready_by_saved_evidence"]
    assert any("bound" in x["code"] for x in result["findings"])


def test_symlink_file_refused(case,monkeypatch):
    original=Path.is_symlink
    monkeypatch.setattr(Path,"is_symlink",lambda p:p==case.artifact or original(p))
    result=case.run();assert any(x["code"]=="symlink_rejected" for x in result["findings"])


def test_duplicate_receipt_keys_not_interpreted(case):
    case.receipt.write_text('{"saved":false,"saved":true}')
    case.manifest["milestones"][0]["evidence_checks"][0]["sha256"]=digest(case.receipt)
    result=case.run();assert any(x["code"]=="invalid_evidence_json" for x in result["findings"])


def test_no_time_expiry_or_code_execution_from_labels(case):
    case.manifest["next_action"]["label"]="__import__('os').system('never execute')"
    result=case.run();assert result["continuation_ready_by_saved_evidence"]
    assert result["next_action"]["label"]==case.manifest["next_action"]["label"]
