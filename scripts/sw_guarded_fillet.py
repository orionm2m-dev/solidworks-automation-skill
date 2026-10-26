"""精确几何签名绑定的恒定半径圆角；单次原生调用，不保存、不降级、不重放。"""
from __future__ import annotations

import json
import math
from pathlib import Path

from scripts.sw_cam import _member, _error
from scripts.sw_cam_feature_sketch import _call_method as call
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_edge_select import iter_model_edges
from scripts.sw_native_transfer import _features, _stats
from scripts.sw_operation_guard import _path_identity, absolute_document_path
from scripts.sw_part import fillet


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Finite native number required")
    return float(value)


def _vector(value, size):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError("Native vector shape differs")
    return [_number(item) for item in value]


def _mm(point):
    return [round(value * 1000., 9) for value in _vector(point, 3)]


def _canonical_signature(value):
    keys = {"length_mm", "endpoints_mm", "box_mm", "curve_type", "curve_parameters_native"}
    if type(value) is not dict or set(value) != keys or value["curve_type"] not in {"line", "circle", "other"}:
        raise ValueError("Exact geometric signature fields required")
    endpoints = value["endpoints_mm"]
    if not isinstance(endpoints, (tuple, list)) or len(endpoints) != 2:
        raise ValueError("Two native trim endpoints required")
    params = value["curve_parameters_native"]
    if not isinstance(params, (tuple, list)) or not 1 <= len(params) <= 256:
        raise ValueError("Bounded native curve parameters required")
    length = _number(value["length_mm"])
    if length <= 0: raise ValueError("Positive trimmed edge length required")
    return dict(length_mm=round(length, 9),
        endpoints_mm=sorted([[round(v, 9) for v in _vector(p, 3)] for p in endpoints]),
        box_mm=[round(v, 9) for v in _vector(value["box_mm"], 6)],
        curve_type=value["curve_type"],
        curve_parameters_native=[float(format(_number(v), ".12g")) for v in params])


def inspect_edge(edge, *, adjacent=True):
    """读取原生裁剪曲线；直线包围盒精确，圆弧为支撑圆范围，其它曲线仅采样范围。"""
    result = dict(signature=None, adjacent_faces=[], errors=[])
    try:
        curve = call(edge, "GetCurve"); trim = call(edge, "GetCurveParams3")
        start = _vector(_member(trim, "StartPoint"), 3); end = _vector(_member(trim, "EndPoint"), 3)
        low = _number(_member(trim, "UMinValue")); high = _number(_member(trim, "UMaxValue"))
        length = _number(call(curve, "GetLength3", low, high))
        if call(curve, "IsLine"):
            kind = "line"; params = _vector(_member(curve, "LineParams"), 6)
            points = [start, end]; basis = "exact_line_endpoints"
        elif call(curve, "IsCircle"):
            kind = "circle"; params = _vector(_member(curve, "CircleParams"), 7)
            center, normal, radius = params[:3], params[3:6], params[6]
            norm = math.sqrt(sum(v*v for v in normal))
            if norm <= 0 or radius <= 0: raise ValueError("Invalid native supporting circle")
            extents = [radius*math.sqrt(max(0., 1.-(v/norm)**2)) for v in normal]
            points = [[center[i]-extents[i] for i in range(3)], [center[i]+extents[i] for i in range(3)]]
            params += [low, high] + _vector(call(curve, "Evaluate2", (low+high)/2., 0), 3)
            basis = "supporting_circle_not_trimmed_arc"
        else:
            kind = "other"
            samples = [_vector(call(curve,"Evaluate2",low+(high-low)*i/8.,0),3) for i in range(9)]
            params = [low,high] + [v for point in samples for v in point]
            points = samples; basis = "nine_parameter_samples_not_exact_bounds"
        box = [min(p[i] for p in points)*1000. for i in range(3)] + [max(p[i] for p in points)*1000. for i in range(3)]
        result["signature"] = _canonical_signature(dict(length_mm=length*1000., endpoints_mm=[_mm(start),_mm(end)],
            box_mm=box,curve_type=kind,curve_parameters_native=params))
        result["box_basis"] = basis
    except Exception as exc:
        result["errors"].append(dict(stage="curve_signature", issue=_error(exc)))
        return result
    if adjacent:
        try:
            faces = list(call(edge,"GetTwoAdjacentFaces2") or [])
            if len(faces)>2: raise ValueError("Unexpected adjacent-face count")
            for face in faces:
                if face is None: continue
                surface = call(face,"GetSurface")
                row = dict(box_mm=[round(v*1000.,9) for v in _vector(call(face,"GetBox"),6)])
                if call(surface,"IsPlane"): row.update(type="plane",parameters_native=_vector(_member(surface,"PlaneParams"),6))
                elif call(surface,"IsCylinder"): row.update(type="cylinder",parameters_native=_vector(_member(surface,"CylinderParams"),7))
                else: row.update(type="other",parameters_native=None)
                result["adjacent_faces"].append(row)
        except Exception as exc: result["errors"].append(dict(stage="adjacent_faces",issue=_error(exc)))
    return result


def _guard(sw, process_id, path):
    if type(process_id) is not int or process_id<=0 or call(sw,"GetProcessID") != process_id:
        raise ValueError("Exact owned PID required")
    model = _member(sw,"ActiveDoc")
    if model is None or call(model,"GetType") != 1 or _path_identity(call(model,"GetPathName")) != _path_identity(path):
        raise ValueError("Exact active saved part required")
    return model


def _fast_trim(edge):
    """One native call per edge; retain geometric trim data, not packed curve tags."""
    values = list(call(edge, "GetCurveParams2") or [])
    if len(values) < 8:
        raise ValueError("Native trimmed curve vector requires at least eight values")
    return dict(endpoints_mm=sorted([_mm(values[:3]), _mm(values[3:6])]),
        trim_parameters_native=[float(format(_number(v), ".12g")) for v in values[6:8]])


def inspect_local_edges(model, bounds_mm, limit=100):
    bounds = _vector(bounds_mm, 6)
    if any(bounds[i] > bounds[i+3] for i in range(3)):
        raise ValueError("Ordered endpoint bounds required")
    descriptors, errors = iter_model_edges(model, include_descriptions=False)
    if errors:
        raise ValueError("Complete edge inventory required")
    matches=[]
    for item in descriptors:
        trim = _fast_trim(item["edge"])
        if all(bounds[i] <= point[i] <= bounds[i+3]
                for point in trim["endpoints_mm"] for i in range(3)):
            matches.append(item)
    rows=[dict(index=item["index"],body_index=item["body_index"],
        **inspect_edge(item["edge"])) for item in matches[:limit]]
    return dict(status="ok",total_edge_count=len(descriptors),matched_count=len(matches),
        returned_count=len(rows),truncated=len(matches)>limit,edges=rows,
        endpoint_bounds_mm=bounds,filter_basis="both trim endpoints; not entire curved-edge bounds",
        errors=[])


def _state(sw, process_id, path, requested=None, require_clean=False):
    model = _guard(sw,process_id,path)
    dirty=bool(call(model,"GetSaveFlag"))
    if require_clean and dirty:
        raise ValueError("Exact fillet prepare/apply requires a clean saved working copy")
    bodies, solids = _stats(model)
    if len(solids)!=1: raise ValueError("Exactly one valid solid required")
    descriptors, errors = iter_model_edges(model, include_descriptions=False)
    if errors or not 1<=len(descriptors)<=4096: raise ValueError("Complete bounded edge inventory required")
    endpoint_keys={json.dumps(row["endpoints_mm"]) for row in (requested or [])}
    rows=[]; trims=[]
    for descriptor in descriptors:
        trim=_fast_trim(descriptor["edge"]);trims.append(trim)
        if json.dumps(trim["endpoints_mm"]) in endpoint_keys:
            detail=inspect_edge(descriptor["edge"],adjacent=False)
            if detail["signature"] is None: raise ValueError("A selected candidate edge signature could not be read")
            rows.append((detail["signature"],descriptor["edge"]))
    state=dict(document_path=str(path),file_sha256=_file_hash(path),needs_save=dirty,
        feature_tree=_features(model),solid_count=1,
        volume_m3=float(format(bodies["bodies"][0]["volume_m3"],".11g")),
        edge_trims=sorted(trims,key=lambda row:json.dumps(row,sort_keys=True)),
        selected_edge_signatures=sorted([row[0] for row in rows],key=lambda row:json.dumps(row,sort_keys=True)),
        geometry_guard_scope="saved file, clean precondition, history, valid body, volume, all edge trims and exact selected signatures; independent STEP audit still required")
    _guard(sw,process_id,path)
    return model,state,rows


def configure_fillet(sw, *, process_id, expected_document_path, radius_mm, edge_signatures,
        expected_edge_count, dry_run, expected_selection_sha256=None, receipt_path=None):
    """预检返回状态/选边哈希；apply 必须一致，单次创建精确半径并读取特征和有效实体。"""
    report=dict(status="error",phase="preflight",mutation_attempted=False,may_continue=False,
        native_call_attempted=False,native_call_returned=False,model_saved=False,production_release=False)
    receipt=None;created=False
    def record(phase):
        report["phase"]=phase
        if created:_write_receipt(receipt,report)
    try:
        path=Path(expected_document_path)
        if not absolute_document_path(expected_document_path) or path.suffix.lower()!='.sldprt' or not path.is_file():
            raise ValueError("Exact existing native part required")
        radius=_number(radius_mm)
        if not 0<radius<=2500 or type(dry_run) is not bool or type(expected_edge_count) is not int or not 1<=expected_edge_count<=64:
            raise ValueError("Invalid radius/count/dry-run contract")
        if type(edge_signatures) is not list or len(edge_signatures)!=expected_edge_count:
            raise ValueError("Signature count differs from explicit expected count")
        requested=[_canonical_signature(row) for row in edge_signatures]
        if any(row["curve_type"]=="other" for row in requested):
            raise ValueError("Only exact line/circle geometry is qualified for selection")
        if len({_digest(row) for row in requested})!=len(requested): raise ValueError("Duplicate requested signatures")
        model,before,rows=_state(sw,process_id,path,requested,require_clean=True)
        selected=[]
        for signature in requested:
            matches=[edge for actual,edge in rows if actual==signature]
            if len(matches)!=1: raise ValueError("Every signature must identify exactly one current edge")
            selected.append(matches[0])
        state=dict(geometry=before,radius_mm=radius,expected_edge_count=expected_edge_count,
            selected_signatures=sorted(requested,key=lambda row:json.dumps(row,sort_keys=True)),tangent_propagation=False)
        digest=_digest(state)
        report.update(before=before,selected_signatures=state["selected_signatures"],selection_sha256=digest,
            geometry_state_sha256=_digest(before),radius_mm=radius,feature_options=194,
            signature_precision=dict(mm_decimal_places=9,curve_native_significant_digits=12,volume_significant_digits=11))
        if dry_run:
            if expected_selection_sha256 is not None or receipt_path is not None: raise ValueError("Dry run forbids mutation inputs")
            report.update(status="ok",phase="prepared",apply_eligible=True);return report
        if expected_selection_sha256!=digest: raise ValueError("Prepared geometry or exact selection changed")
        from scripts.sw_native_transfer import _path
        receipt=_path(receipt_path,{'.json'},new=True)
        _write_receipt(receipt,report,create=True);created=True
        fresh_model,fresh,rows=_state(sw,process_id,path,requested,require_clean=True)
        if fresh!=before: raise ValueError("Geometry changed immediately before selection")
        model=fresh_model
        selected=[next(edge for actual,edge in rows if actual==signature) for signature in requested]
        call(model,"ClearSelection2",True)
        from scripts.sw_connect import create_empty_dispatch_variant
        for edge in selected:
            if call(edge,"Select4",True,create_empty_dispatch_variant()) is not True:
                raise ValueError("Exact edge selection was not confirmed; no fillet call")
        manager=_member(model,"SelectionManager")
        if call(manager,"GetSelectedObjectCount2",-1)!=expected_edge_count:
            raise ValueError("Native selected edge count differs")
        for index,edge in enumerate(selected,1):
            if call(sw,"IsSame",call(manager,"GetSelectedObject6",index,-1),edge)!=1:
                raise ValueError("Native selection identity differs")
        _guard(sw,process_id,path)
        if _file_hash(path)!=before["file_sha256"]: raise ValueError("Saved part changed immediately before fillet")
        report.update(mutation_attempted=True,native_call_attempted=True);record("FeatureFillet_intent")
        feature=fillet(model,radius/1000.,tangent_propagation=False)
        report["native_call_returned"]=True;record("FeatureFillet_returned")
        if feature is None: raise ValueError("Native fillet returned null; do not replay")
        report["feature_name"]=str(_member(feature,"Name"));report["feature_type"]=str(call(feature,"GetTypeName2"))
        report["rebuild_return"]=call(model,"ForceRebuild3",False)
        data=call(feature,"GetDefinition")
        actual_radius=_number(_member(data,"DefaultRadius"))*1000.
        report["actual_radius_mm"]=actual_radius
        if _member(data,"Type")!=0 or _member(data,"IsMultipleRadius") is not False or not math.isclose(actual_radius,radius,rel_tol=1e-10,abs_tol=0):
            raise ValueError("Native constant fillet radius/type readback differs")
        _,after,_=_state(sw,process_id,path);report["after"]=after
        if (after["file_sha256"]!=before["file_sha256"] or after["feature_tree"][:-1]!=before["feature_tree"]
                or len(after["feature_tree"])!=len(before["feature_tree"])+1
                or after["feature_tree"][-1]["name"]!=report["feature_name"]
                or report["feature_type"]!='Fillet'):
            raise ValueError("Exact one-fillet feature history or saved file changed")
        report.update(status="review_required",phase="complete",radius_verified=True,valid_single_solid=True,
            feature_tree_verified=True,reason="UNSAVED_NATIVE_FILLET_REQUIRES_GEOMETRY_AND_PERSISTENCE_REVIEW")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],issue=_error(exc))
        if report["mutation_attempted"]:
            try:
                current=_guard(sw,process_id,Path(expected_document_path))
                report["failure_document"]=dict(path=str(expected_document_path),needs_save=bool(call(current,"GetSaveFlag")),
                    feature_tree=_features(current),file_sha256=_file_hash(expected_document_path))
                _,report["failure_readback"],_=_state(sw,process_id,Path(expected_document_path))
            except Exception as read_exc: report["failure_readback_issue"]=_error(read_exc)
    finally:
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc))
    return report
