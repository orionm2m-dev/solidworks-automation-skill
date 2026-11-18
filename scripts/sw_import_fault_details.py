"""Read fault entities from an owned imported donor after one failed repair; no edits."""
from __future__ import annotations
import json
import math
from scripts.sw_cam import _member
from scripts.sw_cam_feature_sketch import _call_method as call
from scripts.sw_native_transfer import _path, _hash, _check_files, _documents, _owned_donor, _find_document, _fault_indexed_property
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generation import _write_receipt

ENTITY_IID="{83A33D65-27C5-11CE-BFD4-00400513BB57}"
FACE_IID="{4A8BA4D8-DA25-4B75-8E2D-4922B74D81ED}"

def _interface(entity,iid):
    import pythoncom
    from win32com.client import Dispatch
    ole=getattr(entity,"_oleobj_",entity)
    from scripts.sw_native_assembly_audit import _native_interface
    native = Dispatch(ole.QueryInterface(pythoncom.MakeIID(iid),pythoncom.IID_IDispatch))
    return _native_interface(native, "IEntity" if iid == ENTITY_IID else "IFace2")

def _error(exc):return {"type":type(exc).__name__,"message":str(exc),"hresult":getattr(exc,"hresult",None)}

def _numbers(value,count):
    if not isinstance(value,(list,tuple)) or len(value)!=count or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):
        raise ValueError("Unexpected finite geometry coordinate array")
    return list(value)

def _entity_details(entity):
    result={"present":entity is not None}
    if entity is None:return result
    try:result["entity_type"]=call(_interface(entity,ENTITY_IID),"GetType")
    except Exception as exc:result["entity_type_issue"]=_error(exc)
    try:face=_interface(entity,FACE_IID)
    except Exception as exc:
        result.update(face_interface_confirmed=False,face_query_issue=_error(exc));return result
    result["face_interface_confirmed"]=True
    for key,reader in (("bounds_m",lambda:_numbers(call(face,"GetBox"),6)),
            ("area_m2",lambda:call(face,"GetArea")),
            ("surface_identity",lambda:call(call(face,"GetSurface"),"Identity")),
            ("edge_count",lambda:call(face,"GetEdgeCount"))):
        try:
            value=reader()
            if key != "bounds_m" and (type(value) not in (int,float) or not math.isfinite(value)):
                raise ValueError("Nonfinite native face measurement")
            result[key]=value
        except Exception as exc:result[key+"_issue"]=_error(exc)
    try:
        edges=list(call(face,"GetEdges") or [])
        if len(edges)>64:raise ValueError("Face edge count exceeds bounded inspection")
        result["edges"]=[]
        for index,edge in enumerate(edges):
            row={"index":index};result["edges"].append(row)
            for field,method in (("start_m","GetStartVertex"),("end_m","GetEndVertex")):
                try:
                    vertex=call(edge,method)
                    row[field]=None if vertex is None else _numbers(call(vertex,"GetPoint"),3)
                except Exception as exc:row[field+"_issue"]=_error(exc)
    except Exception as exc:result["edges_issue"]=_error(exc)
    return result

def _read_faults(sw,donor,report,save):
    solids=list(call(donor,"GetBodies2",0,False) or [])
    sheets=list(call(donor,"GetBodies2",1,False) or [])
    if len(solids)+len(sheets)>9:raise ValueError("Donor body count exceeds bounded inspection")
    report.update(solid_count=len(solids),sheet_count=len(sheets),bodies=[],unique_fault_entities=[])
    entities=[];total=0
    for kind,values in (("solid",solids),("sheet",sheets)):
        for index,body in enumerate(values):
            faults=_member(body,"Check3");count=_member(faults,"Count")
            if type(count) is not int or not 0<=count<=32 or total+count>64:raise ValueError("Fault count exceeds bound")
            total+=count;row=dict(kind=kind,body_index=index,fault_count=count,faults=[]);report['bodies'].append(row);save("fault_count_read")
            for fault_index in range(count):
                code=_fault_indexed_property(faults,"ErrorCode",fault_index)
                if type(code) is not int:raise ValueError("Fault code is not int")
                fault=dict(index=fault_index,error_code=code);row['faults'].append(fault);save("fault_code_read")
                raw=_fault_indexed_property(faults,"Entity2",fault_index)
                fault["entity_present"]=raw is not None
                if raw is None:continue
                from win32com.client import Dispatch
                entity=Dispatch(raw)
                matches=[j for j,previous in enumerate(entities) if call(sw,"IsSame",entity,previous)==1]
                if len(matches)>1:raise ValueError("Fault entity identity is ambiguous")
                if matches:fault["unique_entity_index"]=matches[0]
                else:
                    fault["unique_entity_index"]=len(entities);entities.append(entity)
                    report['unique_fault_entities'].append(_entity_details(entity))
                save("fault_entity_read")
    report.update(total_fault_count=total,unique_fault_entity_count=len(entities))

def inspect_failed_import_faults(sw,*,process_id,transfer_receipt_path,transfer_receipt_sha256,
        repair_receipt_path,repair_receipt_sha256,receipt_path):
    transfer_path=_path(transfer_receipt_path,{".json"});repair_path=_path(repair_receipt_path,{".json"})
    if _file_hash(transfer_path)!=_hash(transfer_receipt_sha256) or _file_hash(repair_path)!=_hash(repair_receipt_sha256):
        raise ValueError("Failed receipt pin changed")
    transfer=json.loads(transfer_path.read_text('utf-8-sig'));repair=json.loads(repair_path.read_text('utf-8-sig'))
    attempts=[x for x in repair.get('native_calls',[]) if x.get('name')=='ImportDiagnosis' and x.get('attempted') is True]
    if repair.get('status')!='uncertain' or repair.get('phase')!='finished' or len(attempts)!=1:
        raise ValueError("Expected one finished uncertain repair attempt")
    if repair['before']['transfer_receipt_sha256']!=transfer_receipt_sha256:
        raise ValueError("Repair does not bind the failed transfer")
    config=transfer['before']['config'];output=_path(transfer['output_path'],{'.sldprt'})
    marker=_path(repair['repair_marker_path'],{'.json'});marker_hash=_file_hash(marker)
    marker_data=json.loads(marker.read_text('utf-8-sig'))
    from scripts.sw_operation_guard import _path_identity
    if (marker_data['transfer_receipt_sha256']!=transfer_receipt_sha256 or marker_data['process_id']!=process_id
            or _path_identity(marker_data['receipt_path']) != _path_identity(repair_path)):
        raise ValueError("One-shot marker differs")
    staged=_path(transfer['donor_stage_path'],{'.step','.stp'})
    donor=_owned_donor(sw,staged,transfer['open_donor'])
    anchor=_find_document(sw,config['expected_document_path']);copy=_find_document(sw,output)
    if donor is None or anchor is None or copy is None:raise ValueError("Owned donor, copy and anchor must remain open")
    allowed={(str(call(x,'GetPathName') or ''),str(call(x,'GetTitle'))) for x in (donor,anchor,copy)}
    def guard():
        if type(process_id) is not int or process_id!=config['process_id'] or call(sw,'GetProcessID')!=process_id or _member(sw,'UserControl') is not True:
            raise ValueError("Exact owned process required")
        if _file_hash(output)!=config['source_sha256'] or _file_hash(staged)!=config['donor_sha256'] or _file_hash(marker)!=marker_hash:
            raise ValueError("Source copy, donor stage or marker changed")
        _check_files(transfer['before']['frozen_files'])
        if call(anchor,'GetSaveFlag') or call(copy,'GetSaveFlag'):raise ValueError("Source copy and anchor must stay clean")
        if any((x['path'],x['title']) not in allowed for x in _documents(sw)):raise ValueError("Unexpected document in session")
    guard();before=_documents(sw);active=_member(sw,'ActiveDoc')
    report=dict(status='running',phase='preflight_complete',mutation_attempted=False,
        process_id=process_id,transfer_receipt_sha256=transfer_receipt_sha256,repair_receipt_sha256=repair_receipt_sha256,
        transfer_receipt_path=str(transfer_path),repair_receipt_path=str(repair_path),donor=transfer['open_donor'],documents_before=before,
        units={'bounds':'m','area':'m2'},repair_retry=False)
    receipt=_path(receipt_path,{'.json'},new=True);_write_receipt(receipt,report,create=True)
    def save(phase):report['phase']=phase;_write_receipt(receipt,report)
    try:
        _read_faults(sw,donor,report,save);report['status']='ok'
    except Exception as exc:report.update(status='uncertain',issue=_error(exc))
    finally:
        try:
            guard()
            if _documents(sw)!=before or call(sw,'IsSame',active,_member(sw,'ActiveDoc'))!=1:
                raise ValueError("Document state changed during read-only inspection")
            if _file_hash(transfer_path)!=transfer_receipt_sha256 or _file_hash(repair_path)!=repair_receipt_sha256:
                raise ValueError("Input receipt changed")
            report.update(document_state_unchanged=True,source_files_unchanged=True,marker_unchanged=True)
        except Exception as exc:report.update(status='uncertain',final_guard_issue=_error(exc))
        save('finished')
    return report
