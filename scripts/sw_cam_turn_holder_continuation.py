"""已完成单次长度探测后，仅允许一次新 LeadAngle 设置；旧标记永不修改。"""
from pathlib import Path
from copy import deepcopy
import hashlib,json,os
from scripts import sw_cam_turn_feature_regenerate as guard
from scripts import sw_cam_turn_tool as single
from scripts import sw_cam_operation_profile as profile
from scripts.sw_operation_guard import absolute_document_path

SCOPE="TURN_HOLDER_COMPLETED_LENGTH_TO_LEAD_ONCE_V1"
_KEYS={"marker_path","marker_sha256","receipt_path","receipt_sha256"}
_REASONS={
 "CONTINUATION_INPUT_INVALID":"Continuation requires exact absolute JSON marker/receipt paths and SHA-256 pins.",
 "CONTINUATION_LEAD_ONLY":"This continuation permits only LeadAngle after a completed ShankLength probe; it is not general repeated editing.",
 "CONTINUATION_EVIDENCE_CHANGED":"Pinned prior marker or receipt is missing, aliased, changed, or exceeds the bounded JSON size.",
 "CONTINUATION_PROOF_INVALID":"Prior evidence does not prove one completed, verified ShankLength write for this same file and holder tool.",
 "CONTINUATION_CURRENT_LENGTH_CHANGED":"Fresh own-holder or crib ShankLength no longer matches the completed prior probe.",
 "CONTINUATION_PRIOR_OWNER_CHANGED":"A prior operation owner is missing or no longer has the same native tool binding.",
 "HOLDER_PRIOR_ATTEMPT_EXISTS":"A prior holder attempt exists. No setter was called; explicit completed-probe continuation evidence is required for a new LeadAngle setting.",
 "HOLDER_LEAD_ALREADY_CLAIMED":"The one-time LeadAngle continuation has already been claimed. A new receipt or saved-source hash cannot replay it.",
}
class ContinuationGuardError(ValueError):
    """仅公开固定诊断文本，避免回传任意异常内容。"""
    def __init__(self,code):self.code=code;super().__init__(_REASONS[code])

def require_known(condition,code):
    if not condition:raise ContinuationGuardError(code)

def known_reason(error):
    if isinstance(error,ContinuationGuardError):return dict(reason_code=error.code,reason=_REASONS[error.code])
    known={"Initially clean saved qualification copy required":("HOLDER_CLEAN_COPY_REQUIRED","Save the intended current changes first; holder preparation requires a clean saved qualification copy."),
        "Prepared holder state/recipe changed":("HOLDER_PREPARED_STATE_CHANGED","The prepared state or recipe changed. No new setter may use that stale digest."),
        "Generated sharing or no-op recipe forbids holder writes":("HOLDER_WRITE_NOT_ELIGIBLE","Generated sharing operations or a no-change recipe block holder writes.")}
    if type(error) is ValueError and str(error) in known:
        code,reason=known[str(error)];return dict(reason_code=code,reason=reason)
    return {}

def validate_completed_length_probe(value,values):
    """只校验公开输入格式；不读取文件或调用 CAD。"""
    if value is None:return None
    require_known(type(value) is dict and set(value)==_KEYS,"CONTINUATION_INPUT_INVALID")
    require_known(set(values)=={"LeadAngle"},"CONTINUATION_LEAD_ONLY")
    for prefix in ("marker","receipt"):
        p=value[prefix+"_path"];h=value[prefix+"_sha256"]
        require_known(type(p) is str and len(p)<=4096 and absolute_document_path(p) and Path(p).suffix.casefold()==".json" and guard.sha(h),"CONTINUATION_INPUT_INVALID")
    require_known(guard.key(value["marker_path"])!=guard.key(value["receipt_path"]),"CONTINUATION_INPUT_INVALID")
    return deepcopy(value)

def continuation_marker_path(legacy,identity,tool_id):
    return legacy.parent/("turn_holder_lead_after_length_"+single._digest(dict(scope=SCOPE,copy_file_identity=identity,tool_native_id=tool_id,field="LeadAngle"))+".json")

def _read_pin(path,digest):
    try:
        p=Path(path);before=p.stat()
        require_known(p.is_file() and not p.is_symlink() and 0<before.st_size<=16*1024*1024 and before.st_ino!=0,"CONTINUATION_EVIDENCE_CHANGED")
        with p.open("rb") as stream:
            opened=os.fstat(stream.fileno());raw=stream.read(16*1024*1024+1);closed=os.fstat(stream.fileno())
        after=p.stat();sig=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns)
        require_known(sig(before)==sig(opened)==sig(closed)==sig(after) and len(raw)==before.st_size and hashlib.sha256(raw).hexdigest()==digest,"CONTINUATION_EVIDENCE_CHANGED")
        return json.loads(raw)
    except ContinuationGuardError:raise
    except Exception:raise ContinuationGuardError("CONTINUATION_EVIDENCE_CHANGED") from None

def verify_evidence_pins(pins):
    for prefix in ("marker","receipt"):_read_pin(pins[prefix+"_path"],pins[prefix+"_sha256"])

def load_completed_length_probe(pins,legacy,identity,config):
    """验证历史成功证明及同文件/刀具关系；不把历史状态当作当前 CAM 快照。"""
    from scripts import sw_cam_turn_holder_dimensions as holder
    require_known(guard.key(pins["marker_path"])==guard.key(legacy),"CONTINUATION_PROOF_INVALID")
    marker=_read_pin(pins["marker_path"],pins["marker_sha256"]);receipt=_read_pin(pins["receipt_path"],pins["receipt_sha256"])
    try:
        require_known(type(marker) is dict and type(receipt) is dict,"CONTINUATION_PROOF_INVALID")
        request=receipt["request"];tid=config["expected_tool_native_id"]
        ok=marker["scope"]==receipt["scope"]==holder.PROBE_SCOPE and marker["status"]=="claimed_no_replay"
        ok=ok and marker["copy_file_identity"]==identity and type(marker["tool_native_id"]) is int and marker["tool_native_id"]==tid
        ok=ok and guard.key(marker["receipt_path"])==guard.key(pins["receipt_path"]) and guard.key(receipt["marker_path"])==guard.key(legacy)
        ok=ok and request["action"]=="probe" and guard.key(request["expected_document_path"])==guard.key(config["expected_document_path"])
        ok=ok and request["expected_tool_native_id"]==tid and request["expected_holder_id"]==config["expected_holder_id"]
        ok=ok and marker["source_sha256"]==request["expected_source_sha256"] and marker["state_sha256"]==receipt["state_sha256"]
        ok=ok and receipt["status"]=="review_required" and receipt["phase"]=="finished"
        ok=ok and all(receipt[k] is True for k in ("mutation_attempted","readback_verified","owner_write_through_verified"))
        ok=ok and receipt["native_dispatch_pending"] is False and type(receipt["native_calls_returned_count"]) is int and receipt["native_calls_returned_count"]==1
        ok=ok and receipt["write_through_outcome"]=="observed_in_fresh_owner_and_crib" and len(receipt["setters"])==1
        ok=ok and not any(receipt.get(k) for k in ("issue","receipt_write_error","runtime_error","terminal_issue","cleanup_issue"))
        messages=receipt["messages"]
        ok=ok and messages.get("subscribed") is True and messages.get("disconnected") is True and messages.get("active") is False and not any(messages.get(k) for k in guard.EVENT_ERRORS)
        require_known(ok,"CONTINUATION_PROOF_INVALID")
        item=receipt["setters"][0];old=profile._number(request["expected_shank_length_native"]);value=profile._number(request["shank_length_native"])
        require_known(old>0 and value>0 and old!=value and item["field"]=="ShankLength" and item["old_value_native"]==old and item["value_native"]==value and all(item[k] is True for k in ("attempted","returned","readback_verified")),"CONTINUATION_PROOF_INVALID")
        require_known(receipt["length_readback_native"]==dict(retained_holder=value,fresh_own_holder=value,current_crib_holder=value) and item["retained_value_native"]==value,"CONTINUATION_PROOF_INVALID")
        require_known(receipt["after"]==receipt["final_state"]==item["after"] and single._digest(receipt["final_state"])==receipt["final_state_sha256"],"CONTINUATION_PROOF_INVALID")
        digest=single._digest(dict(scope=holder.PROBE_SCOPE,request=request|{"action":"prepared_recipe"},copy_file_identity=identity,state=holder._probe_comparable(receipt["before"]),retained_holders=receipt["retained_holders_before"]))
        require_known(digest==receipt["state_sha256"],"CONTINUATION_PROOF_INVALID")
        holder._verify_probe_delta(receipt["before"],receipt["after"],value,tid)
        holder._verify_retained_probe_delta(receipt["retained_holders_before"],receipt["retained_holders_after"],value,tid)
        prior=[{k:deepcopy(x[k]) for k in ("operation","operation_native_id","tool_native_id")} for x in receipt["after"]["operation_tools"] if x["tool_native_id"]==tid]
        require_known(bool(prior) and any(x["operation_native_id"]==request["expected_operation_native_id"] for x in prior),"CONTINUATION_PROOF_INVALID")
        return dict(scope=SCOPE,pins=deepcopy(pins),prior_field="ShankLength",prior_value_native=value,prior_owners=prior,legacy_marker_preserved=True,allowed_new_field="LeadAngle")
    except ContinuationGuardError:raise
    except Exception:raise ContinuationGuardError("CONTINUATION_PROOF_INVALID") from None

def verify_current_completed_length(state,evidence,tool_id):
    """在当前独立快照中确认历史长度及原有 owner 仍存在；新增 owner 由完整 usage 门禁控制。"""
    value=evidence["prior_value_native"]
    rows=[r for r in state["observed_operation_tools"] if r["tool_native_id"]==tool_id]
    crib=[r for r in state["toolcrib"] if r["native_id"]==tool_id]
    require_known(len(crib)==1 and bool(rows) and state["selected_tool"]["holder"]["dimensions_native"]["ShankLength"]==value and crib[0]["holder_dimensions_native"]["ShankLength"]==value and all(r["observed_tool"]["holder"]["dimensions_native"]["ShankLength"]==value for r in rows),"CONTINUATION_CURRENT_LENGTH_CHANGED")
    for prior in evidence["prior_owners"]:
        require_known(sum(all(row[k]==prior[k] for k in prior) for row in rows)==1,"CONTINUATION_PRIOR_OWNER_CHANGED")
