"""只核验持久化续作清单及文件证据；不连接 CAD、不执行清单内容。"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re

MAX_STATUS_BYTES=4*1024*1024
MAX_EVIDENCE_BYTES=8*1024*1024
MAX_JSON_TOTAL_BYTES=32*1024*1024
MAX_ARTIFACT_BYTES=4*1024**3
MAX_TOTAL_BYTES=8*1024**3
STATES={"planned","defined","generated","saved","reopened","verified"}


class FileProblem(Exception):
    def __init__(self,code,path,detail):
        super().__init__(detail);self.code=code;self.path=str(path)


def _text(v,label,limit=2000):
    if type(v) is not str or not v or len(v)>limit or "\x00" in v:raise ValueError("Invalid bounded string: "+label)
    return v


def _path(v):
    _text(v,"absolute path",4096)
    if not Path(v).is_absolute():raise ValueError("Exact absolute paths required")
    return Path(v)


def _sha(v):
    if type(v) is not str or re.fullmatch(r"[0-9a-f]{64}",v) is None:raise ValueError("Exact lower-case SHA256 required")


def _id(v):
    if type(v) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}",v) is None:raise ValueError("Invalid bounded checkpoint ID")


def _keys(v,required,optional=()):
    if type(v) is not dict or not set(required)<=set(v) or set(v)-set(required)-set(optional):raise ValueError("Unexpected or missing checkpoint fields")


def _list(v,limit):
    if type(v) is not list or len(v)>limit:raise ValueError("Checkpoint array exceeds bound or has wrong type")
    return v


def _strings(v):
    for item in _list(v,64):_text(item,"label/limitation")


def _expected(v,depth=0):
    if depth>8:raise ValueError("Expected JSON value too deeply nested")
    if type(v) is dict:
        for k,item in v.items():_text(k,"expected key",1000);_expected(item,depth+1)
    elif type(v) is list:
        for item in v:_expected(item,depth+1)
    elif v is not None and type(v) not in (str,bool,int,float):raise ValueError("Expected value must be JSON")
    if depth==0 and len(json.dumps(v,ensure_ascii=False,allow_nan=False).encode("utf-8"))>4096:raise ValueError("Expected JSON value exceeds bound")


def _tokens(pointer):
    if type(pointer) is not str or len(pointer)>4096 or (pointer and not pointer.startswith("/")) or re.search(r"~(?![01])",pointer):
        raise ValueError("Exact RFC6901 JSON pointer required")
    return [] if not pointer else [x.replace("~1","/").replace("~0","~") for x in pointer[1:].split("/")]


def _reference(ref,check=False):
    _keys(ref,("path","sha256","json_pointer","expected") if check else ("path","sha256"),() if check else ("json_pointer","expected"))
    _path(ref["path"]);_sha(ref["sha256"])
    if ("json_pointer" in ref)!=("expected" in ref):raise ValueError("Pointer and expected must appear together")
    if "json_pointer" in ref:_tokens(ref["json_pointer"]);_expected(ref["expected"])


def _validate(c):
    _keys(c,("schema_version","current_artifacts","milestones","failed_attempts","next_action"))
    if type(c["schema_version"]) is not int or c["schema_version"]!=1:raise ValueError("Only strict schema_version=1 supported")
    total=0
    for group,limit in (("current_artifacts",256),("milestones",512),("failed_attempts",128)):
        seen=set()
        for row in _list(c[group],limit):
            if type(row) is not dict:raise ValueError("Checkpoint row must be object")
            _id(row.get("id"))
            if row["id"] in seen:raise ValueError("Duplicate checkpoint ID in "+group)
            seen.add(row["id"])
            if group=="current_artifacts":
                _keys(row,("id","path","sha256","role"));_path(row["path"]);_sha(row["sha256"]);_text(row["role"],"role")
            elif group=="milestones":
                _keys(row,("id","label","state","evidence_checks","limitations"));_text(row["label"],"label")
                if type(row["state"]) is not str or row["state"] not in STATES:raise ValueError("Unknown declared milestone state")
                refs=_list(row["evidence_checks"],64)
                if row["state"]=="verified" and not refs:raise ValueError("Declared verified milestone requires explicit evidence checks")
                for ref in refs:_reference(ref,check=True)
                total+=len(refs);_strings(row["limitations"])
            else:
                _keys(row,("id","hypothesis","evidence_refs","disposition"));_text(row["hypothesis"],"hypothesis");_text(row["disposition"],"disposition")
                refs=_list(row["evidence_refs"],64)
                if not refs:raise ValueError("Failed attempt requires evidence refs")
                for ref in refs:_reference(ref)
                total+=len(refs)
    if total>512:raise ValueError("Total evidence reference bound exceeded")
    action=c["next_action"]
    _keys(action,("id","label","preconditions","success_criteria","do_not_repeat"),("human_preconditions",))
    _id(action["id"]);_text(action["label"],"next action label")
    for ref in _list(action["preconditions"],256):
        if type(ref) is not dict or ref.get("kind") not in ("artifact","milestone"):raise ValueError("Machine preconditions require explicit kind")
        _keys(ref,("kind","id","required_state") if ref["kind"]=="milestone" else ("kind","id"));_id(ref["id"])
        if ref["kind"]=="milestone" and (type(ref["required_state"]) is not str or ref["required_state"] not in STATES):raise ValueError("Exact required milestone state needed")
    for field in ("success_criteria","do_not_repeat","human_preconditions"):_strings(action.get(field,[]))


def _json(data):
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result:raise ValueError("Duplicate JSON object key")
            result[key]=value
        return result
    def invalid(_):raise ValueError("Nonfinite JSON value")
    return json.loads(data.decode("utf-8-sig"),object_pairs_hook=pairs,parse_constant=invalid)


def _signature(st):return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)


class _Reader:
    def __init__(self):self.seen={};self.bytes_read=0;self.json_bytes=0
    def read(self,value,limit,keep=False,force=False):
        path=_path(value);key=str(path.absolute())
        try:
            if path.is_symlink():raise FileProblem("symlink_rejected",path,"Named files cannot be symlinks")
            before=path.stat()
            if not path.is_file():raise FileProblem("not_a_file",path,"Named path is not a regular file")
            if before.st_size>limit:raise FileProblem("file_bound_exceeded",path,"File exceeds explicit byte limit")
            cached=self.seen.get(key)
            if cached and cached["signature"]!=_signature(before):raise FileProblem("stale_during_read",path,"File metadata changed during checkpoint inspection")
            if cached and not force and (not keep or cached.get("data") is not None):return cached
            if self.bytes_read+before.st_size>MAX_TOTAL_BYTES:raise FileProblem("total_bound_exceeded",path,"Total streamed byte bound exceeded")
            if keep and self.json_bytes+before.st_size>MAX_JSON_TOTAL_BYTES:raise FileProblem("json_total_bound_exceeded",path,"Aggregate JSON read bound exceeded")
            digest=hashlib.sha256();parts=[];size=0
            with path.open("rb") as stream:
                opened=_signature(os.fstat(stream.fileno()))
                if opened!=_signature(before):raise FileProblem("stale_during_read",path,"File changed before open")
                while True:
                    block=stream.read(1024*1024)
                    if not block:break
                    size+=len(block);self.bytes_read+=len(block)
                    if size>limit or self.bytes_read>MAX_TOTAL_BYTES:raise FileProblem("file_bound_exceeded",path,"File grew beyond the read bound")
                    digest.update(block)
                    if keep:parts.append(block)
                after=_signature(os.fstat(stream.fileno()))
            if path.is_symlink() or after!=opened or _signature(path.stat())!=opened or size!=before.st_size:
                raise FileProblem("stale_during_read",path,"File changed while hashing")
            item=dict(path=str(path),sha256=digest.hexdigest(),bytes=size,signature=opened,data=b"".join(parts) if keep else None)
            if cached and cached["sha256"]!=item["sha256"]:raise FileProblem("stale_during_read",path,"File content changed during checkpoint inspection")
            if keep:self.json_bytes+=size
            self.seen[key]=item;return item
        except FileProblem:raise
        except FileNotFoundError as exc:raise FileProblem("missing_file",path,"Named file is missing") from exc
        except OSError as exc:raise FileProblem("file_read_error",path,str(exc)) from exc
    def stability(self):
        result=[]
        for value in self.seen.values():
            path=Path(value["path"])
            try:
                if path.is_symlink() or _signature(path.stat())!=value["signature"]:
                    result.append(dict(code="stale_during_read",path=str(path),detail="File changed after its hash was observed"))
            except OSError:result.append(dict(code="missing_file",path=str(path),detail="File disappeared after hashing"))
        return result


def _pointer(value,pointer):
    for token in _tokens(pointer):
        if type(value) is dict:
            if token not in value:raise KeyError("Object member missing")
            value=value[token]
        elif type(value) is list:
            if re.fullmatch(r"0|[1-9][0-9]*",token) is None or int(token)>=len(value):raise KeyError("Array index missing/invalid")
            value=value[int(token)]
        else:raise KeyError("Pointer traverses a scalar")
    return value


def _equal(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return a.keys()==b.keys() and all(_equal(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(_equal(x,y) for x,y in zip(a,b))
    return a==b


def _value_evidence(value):
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False)
    return dict(actual=value,actual_truncated=False) if len(raw)<=2048 else dict(actual_preview=raw[:2048],actual_truncated=True,actual_json_characters=len(raw))


def read_resume_checkpoint(status_path):
    """校验静态 STATUS 文件引用；不会授权原生修改或断言当前 CAD 内存状态。"""
    report=dict(status="error",live_state_verified=False,native_mutation_authorized=False,
        authorization_scope="This reader does not evaluate or grant native mutation authorization",
        continuation_ready_by_saved_evidence=False,findings=[],current_artifacts=[],evidence_passed=[],pending=[],failed_attempts=[],
        evidence_scope="Bounded saved-file hashes and exact typed receipt fields; no CAD or manufacturing approval")
    reader=_Reader();parsed={}
    def issue(scope,code,**details):report["findings"].append(dict(scope=scope,code=code,**details))
    def reference(ref,scope):
        try:
            pointer="json_pointer" in ref
            item=reader.read(ref["path"],MAX_EVIDENCE_BYTES if pointer else MAX_ARTIFACT_BYTES,keep=pointer)
            if item["sha256"]!=ref["sha256"]:
                issue(scope,"sha256_mismatch",path=ref["path"],expected_sha256=ref["sha256"],actual_sha256=item["sha256"]);return False
            if pointer:
                key=(item["path"],item["sha256"])
                if key not in parsed:parsed[key]=_json(item["data"])
                try:actual=_pointer(parsed[key],ref["json_pointer"])
                except KeyError as exc:
                    issue(scope,"json_pointer_missing",path=ref["path"],json_pointer=ref["json_pointer"],detail=str(exc));return False
                if not _equal(actual,ref["expected"]):
                    issue(scope,"receipt_value_mismatch",path=ref["path"],json_pointer=ref["json_pointer"],expected=ref["expected"],expected_python_type=type(ref["expected"]).__name__,actual_python_type=type(actual).__name__,**_value_evidence(actual));return False
            return True
        except FileProblem as exc:issue(scope,exc.code,path=exc.path,detail=str(exc));return False
        except (ValueError,RecursionError) as exc:issue(scope,"invalid_evidence_json",path=ref["path"],detail=str(exc));return False
    try:
        path=_path(status_path)
        if path.suffix.casefold()!=".json":raise ValueError("STATUS input must be an absolute JSON path")
        initial=reader.read(str(path),MAX_STATUS_BYTES,keep=True)
        report.update(status_path=str(path),status_sha256=initial["sha256"])
        root=_json(initial["data"])
        if type(root) is not dict or "resume_checkpoint" not in root:raise ValueError("Existing STATUS requires resume_checkpoint section")
        c=root["resume_checkpoint"];_validate(c)
        report["next_action"]=dict(c["next_action"],status="not_yet_checked",continuation_ready_by_saved_evidence=False,human_preconditions_verified=False,native_mutation_authorized=False)
        artifacts={};milestones={}
        for row in c["current_artifacts"]:
            valid=reference(row,"artifact:"+row["id"]);artifacts[row["id"]]=valid
            report["current_artifacts"].append(dict(row,sha256_verified=valid))
        for row in c["milestones"]:
            results=[reference(ref,"milestone:"+row["id"]) for ref in row["evidence_checks"]]
            valid=bool(results) and all(results);milestones[row["id"]]=(row["state"],valid)
            entry=dict(id=row["id"],label=row["label"],declared_state=row["state"],evidence_checks_verified=valid,
                evidence_check_count=len(results),limitations=row["limitations"])
            (report["evidence_passed"] if valid else report["pending"]).append(entry)
        for row in c["failed_attempts"]:
            results=[reference(ref,"failed_attempt:"+row["id"]) for ref in row["evidence_refs"]]
            report["failed_attempts"].append(dict(id=row["id"],hypothesis=row["hypothesis"],disposition=row["disposition"],evidence_refs_verified=all(results)))
        action=c["next_action"];ready=True
        for ref in action["preconditions"]:
            if ref["kind"]=="artifact":
                if ref["id"] not in artifacts:issue("next_action","unknown_artifact_id",id=ref["id"]);ready=False
                elif not artifacts[ref["id"]]:ready=False
            else:
                found=milestones.get(ref["id"])
                if found is None:issue("next_action","unknown_milestone_id",id=ref["id"]);ready=False
                elif found[0]!=ref["required_state"]:
                    issue("next_action","declared_state_mismatch",id=ref["id"],required_state=ref["required_state"],declared_state=found[0]);ready=False
                elif not found[1]:ready=False
        # 重读 STATUS 内容指纹，不能把正在编辑的清单当作一致快照。
        final=reader.read(str(path),MAX_STATUS_BYTES,keep=True,force=True)
        report["status_sha256_after"]=final["sha256"]
        for finding in reader.stability():issue("file_stability",**finding)
        ready=ready and not report["findings"] and all(artifacts.values())
        report.update(status="ok",continuation_ready_by_saved_evidence=ready,status_file_unchanged=True,
            next_action=dict(action,status="continuation_ready_by_saved_evidence" if ready else "pending_or_mismatch",
                continuation_ready_by_saved_evidence=ready,human_preconditions_verified=False,native_mutation_authorized=False),
            summary=dict(evidence_verified_milestones=len(report["evidence_passed"]),pending_milestones=len(report["pending"]),
                artifacts=len(artifacts),findings=len(report["findings"]),bytes_hashed=reader.bytes_read,
                counts_by_declared_state={state:sum(row["state"]==state for row in c["milestones"]) for state in sorted(STATES)}))
    except FileProblem as exc:issue("status",exc.code,path=exc.path,detail=str(exc))
    except (ValueError,TypeError,RecursionError) as exc:issue("status","invalid_checkpoint",detail=str(exc))
    if not report["continuation_ready_by_saved_evidence"] and "next_action" in report:
        report["next_action"]["status"]="pending_or_mismatch"
    return report
