"""Diagnose one failed subtraction using temporary copies; never edit documents."""
from __future__ import annotations
import json
import math
from pathlib import Path
from scripts.sw_cam import _member
from scripts.sw_cam_feature_sketch import _call_method as call, _double_array
from scripts.sw_native_transfer import _path, _hash, _stats, _documents, _check_files, _features
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_operation_guard import _path_identity

ERRORS = {0:"NoError",1:"NonApiBody",2:"WrongType",3:"FailGeomCondition",4:"FailToCutBody",
 5:"DisjointBodies",6:"EmptyBody",7:"EmptyInputBody",8:"InvalidInputBody",96:"MissingGeom",
 543:"UniteSolidSheet",545:"SameToolAndTarget",547:"NonManifold",951:"OpposedSheets",
 972:"IntersectSolidWithSheets",1040:"PartialCoincidence",1058:"BooleanFail",1067:"NoIntersect",-1:"UnknownError"}

def _same_measurement(a,b):
    return (a.get("check3")==b.get("check3")==0
        and math.isclose(a["volume_m3"],b["volume_m3"],rel_tol=1e-10,abs_tol=1e-18)
        and len(a["box_model_m"])==len(b["box_model_m"])==6
        and all(math.isclose(x,y,rel_tol=0,abs_tol=1e-10) for x,y in zip(a["box_model_m"],b["box_model_m"])))

def _match_rows(current,expected):
    if len(current)!=len(expected) or not 2<=len(current)<=9:
        raise ValueError("Retained body count differs from failed receipt")
    indexes=[]
    for row in expected:
        matches=[i for i,other in enumerate(current) if _same_measurement(row,other)]
        if len(matches)!=1 or matches[0] in indexes:
            raise ValueError("Retained body measurements are not a unique bijection")
        indexes.append(matches[0])
    return indexes

class _TemporaryPart:
    def __init__(self,bodies): self.bodies=bodies
    def GetBodies2(self,kind,visible): return self.bodies if kind==0 else []

def _temporary_copy(sw,body,originals):
    copied=call(body,"Copy")
    if copied is None or call(copied,"IsTemporaryBody") is not True:
        raise ValueError("Copy did not return a temporary body")
    if any(call(sw,"IsSame",copied,original)==1 for original in originals):
        raise ValueError("Copy aliases a document body")
    _stats(_TemporaryPart([copied]))
    return copied

def _operations(target,tool,operation_type):
    if type(operation_type) is not int or operation_type not in {15902,15903}:
        raise ValueError("Only explicit temporary CUT or ADD is supported")
    import pythoncom
    # Installed IBody2 PIA: DISPID110 METHOD, I4 + IDispatch + OUT I4, VARIANT retval.
    # InvokeTypes returns (retval, out_error). Never retry on marshaling uncertainty.
    raw=target._oleobj_.InvokeTypes(110,0,pythoncom.DISPATCH_METHOD,
        (pythoncom.VT_VARIANT,0),((pythoncom.VT_I4,1),(pythoncom.VT_DISPATCH,1),(pythoncom.VT_BYREF | pythoncom.VT_I4,2)),
        operation_type,tool._oleobj_,pythoncom.Missing)
    if not isinstance(raw,tuple) or len(raw)!=2 or type(raw[1]) is not int:
        raise ValueError("Unexpected Operations2 retval/out-error binding")
    bodies,error=raw
    if bodies is None: return [],error
    if not isinstance(bodies,(tuple,list)) or len(bodies)>9:
        raise ValueError("Unexpected Operations2 body array")
    from win32com.client import Dispatch
    return [Dispatch(body) for body in bodies],error

def _operations_cut(target,tool):
    return _operations(target,tool,15902)

def diagnose_retained_subtraction(sw,*,process_id,transfer_receipt_path,transfer_receipt_sha256,receipt_path):
    prior_path=_path(transfer_receipt_path,{".json"})
    if _file_hash(prior_path)!=_hash(transfer_receipt_sha256): raise ValueError("Transfer receipt SHA changed")
    prior=json.loads(prior_path.read_text(encoding="utf-8-sig"))
    if (prior.get("status")!="uncertain" or prior.get("phase")!="finished"
            or prior.get("failed_phase")!="InsertCombineFeature_SUBTRACT_DELTA_returned"
            or prior.get("mode")!="subtract_delta"):
        raise ValueError("Expected exactly a finished null subtraction receipt")
    state=prior["before"]; config=state["config"]
    if type(process_id) is not int or process_id!=config["process_id"] or call(sw,"GetProcessID")!=process_id:
        raise ValueError("Exact owned process required")
    if _member(sw,"UserControl") is not True: raise ValueError("Owned UserControl required")
    _check_files(state["frozen_files"])
    output=_path(prior["output_path"],{".sldprt"})
    if _file_hash(output)!=prior["copied_source_sha256"]: raise ValueError("Retained output disk copy changed")
    model=_member(sw,"ActiveDoc")
    if model is None or _path_identity(call(model,"GetPathName"))!=_path_identity(output):
        raise ValueError("Retained output must already be active")
    documents=_documents(sw)
    allowed={_path_identity(output),_path_identity(config["expected_document_path"])}
    donor_title=prior["open_donor"]["title"]
    if len(documents)!=3 or any(not((row["path"] and _path_identity(row["path"]) in allowed)
            or (not row["path"] and row["title"]==donor_title and row["type"]==1)) for row in documents):
        raise ValueError("Unexpected retained document set")
    before,bodies=_stats(model)
    indexes=_match_rows(before["bodies"],prior["inserted_bodies"]["bodies"])
    source_matches=[i for i,row in enumerate(before["bodies"]) if _same_measurement(row,prior["body_before"]["bodies"][0])]
    if len(source_matches)!=1: raise ValueError("Cannot identify unique retained source")
    main_index=source_matches[0]
    tool_indexes=[i for i in indexes if i!=main_index]
    tool_index=tool_indexes[0]
    features=_features(model)
    report=dict(status="running",phase="preflight_complete",document_mutation_attempted=False,
        temporary_operations_attempted=0,process_id=process_id,transfer_receipt_path=str(prior_path),
        transfer_receipt_sha256=transfer_receipt_sha256,output_path=str(output),
        document_before=documents,active_visible=_member(model,"Visible"),
        active_model_view_count=call(model,"GetModelViewCount"),bodies_before=before,
        main_body_index=main_index,tool_body_index=tool_index,calls=[])
    receipt=_path(receipt_path,{".json"},new=True)
    _write_receipt(receipt,report,create=True)
    def save(phase):
        report["phase"]=phase; _write_receipt(receipt,report)
    def cut(label,target,tool):
        row=dict(label=label,attempted=True,returned=False)
        report["calls"].append(row); report["temporary_operations_attempted"]+=1
        save(label+"_pending")
        results,error=_operations_cut(target,tool)
        row.update(returned=True,error_code=error,error_name=ERRORS.get(error,"UnmappedError"),result_count=len(results))
        save(label+"_returned")
        if results:
            if any(call(body,"IsTemporaryBody") is not True for body in results):
                raise ValueError("Operations2 returned a non-temporary body")
            row["results"]=_stats(_TemporaryPart(results))[0]
        row["success"]=error==0 and bool(results)
        save(label+"_validated")
        return row
    try:
        target=_temporary_copy(sw,bodies[main_index],bodies)
        tool=_temporary_copy(sw,bodies[tool_index],bodies)
        actual=cut("source_first_tool_cut",target,tool)
        if not actual["success"]:
            # One explicit binding control; no original temp body is reused after Operations2.
            left=_temporary_copy(sw,bodies[tool_index],bodies)
            right=_temporary_copy(sw,bodies[tool_index],bodies)
            box=before["bodies"][tool_index]["box_model_m"]
            translation=(box[3]-box[0])/4
            matrix=[1.,0.,0.,0.,1.,0.,0.,0.,1.,translation,0.,0.,1.,0.,0.,0.]
            transform=call(call(sw,"GetMathUtility"),"CreateTransform",_double_array(matrix))
            if transform is None or call(right,"ApplyTransform",transform) is not True:
                raise ValueError("Temporary control translation failed")
            report["control_translation_m"]=[translation,0.,0.]
            control=cut("translated_tool_control",left,right)
            control["expected_partial_cut_observed"]=(control["success"] and
                0<sum(x["volume_m3"] for x in control["results"]["bodies"])<before["bodies"][tool_index]["volume_m3"])
        report["status"]="ok"
    except Exception as exc:
        report.update(status="uncertain",issue={"type":type(exc).__name__,"message":str(exc)})
    finally:
        try:
            after,current=_stats(model)
            _match_rows(after["bodies"],before["bodies"])
            if any(sum(call(sw,"IsSame",old,new)==1 for new in current)!=1 for old in bodies):
                raise ValueError("Original document body identity changed")
            if _documents(sw)!=documents or _features(model)!=features:
                raise ValueError("Document state or feature history changed")
            _check_files(state["frozen_files"])
            if _file_hash(output)!=prior["copied_source_sha256"]: raise ValueError("Output disk file changed")
            report.update(document_unchanged_verified=True,bodies_after=after,source_files_unchanged=True)
        except Exception as exc:
            report.update(status="uncertain",final_verification_issue={"type":type(exc).__name__,"message":str(exc)})
        save("finished")
    return report
