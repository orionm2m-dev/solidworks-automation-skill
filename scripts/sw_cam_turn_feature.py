"""从已读直线段验证一个新车削特征；类型映射是假设，不生成 THREAD 或刀路。"""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
import math
from pathlib import Path
import re
import time
from datetime import datetime, timezone

from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _collection, _inventory, _typed, _write_receipt
from scripts.sw_cam_operation_profile import _number, _integer, _read_profile
from scripts.sw_cam_thread import _capture, _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest, _reference
from scripts.sw_operation_guard import absolute_document_path



# 仅质量属性容纳浮点积分噪声；文件、包围盒、特征和操作仍逐值精确比较。
_MASS_SIGNIFICANT_DIGITS = 12
_MASS_RELATIVE_TOLERANCE = 1e-10


def _state_digest(state, *, mass_significant_digits=_MASS_SIGNIFICANT_DIGITS):
    canonical = deepcopy(state)
    for body in canonical["solids"]:
        body["mass_properties_native"] = [
            0.0 if _number(value) == 0 else float(format(_number(value), f".{mass_significant_digits}g"))
            for value in body["mass_properties_native"]]
    return _digest(canonical)


def _states_equal(before, after):
    candidate = deepcopy(after)
    if len(before["solids"]) != len(candidate["solids"]):
        return False
    for old_body, new_body in zip(before["solids"], candidate["solids"]):
        old = old_body["mass_properties_native"]
        new = new_body["mass_properties_native"]
        if len(old) != len(new) or any(not math.isclose(_number(a), _number(b),
                rel_tol=_MASS_RELATIVE_TOLERANCE, abs_tol=0.0) for a, b in zip(old, new)):
            return False
        new_body["mass_properties_native"] = deepcopy(old)
    return before == candidate


def _body_state(model):
    bodies = list(_member(model, "GetBodies2", 0, False) or [])
    if not 1 <= len(bodies) <= 64:
        raise ValueError("Qualification requires a bounded solid part")
    return [{"box_model_m": list(map(_number, _member(body, "GetBodyBox"))),
             "mass_properties_native": list(map(_number, _member(body, "GetMassProperties", 1)))}
            for body in bodies]


def _model_features(model):
    rows = []
    feature = _member(model, "FirstFeature")
    while feature is not None:
        if len(rows) >= 512:
            raise ValueError("Model feature traversal exceeds qualification bound")
        rows.append({"name": str(_member(feature, "Name")), "type": str(_member(feature, "GetTypeName2"))})
        feature = _member(feature, "GetNextFeature")
    return rows


# 仅裁剪已确认的轴向直线；此数值容差不是制造公差，也不放宽 Z 域。
_CROP_AXIS_TOLERANCE_MODEL_M = 1e-10


def _crop_line(line, config, state):
    """从原线插值截取，禁止任意 XY、反向或越界；原始线与 ID/SHA 保留。"""
    if state['selected_operation_id'] != config['expected_source_operation_native_id']:
        raise ValueError('Exact source operation ID changed')
    if state['selected_feature_id'] != config['expected_source_feature_native_id']:
        raise ValueError('Exact source feature ID changed')
    if state['saved_file_sha256'] != config['expected_source_sha256']:
        raise ValueError('Exact source saved file SHA changed')
    if _digest(line) != config['expected_source_line_sha256']:
        raise ValueError('Exact source line fingerprint changed')
    if line.get('curve_type_raw') != 0 or line.get('curve_parameters_available') is not True:
        raise ValueError('Crop requires a confirmed straight source segment')
    a, b = [[_number(v) for v in line[key]] for key in ('start_native','end_native')]
    if len(a) != 3 or len(b) != 3:
        raise ValueError('Source endpoints require three coordinates')
    scale = config['native_to_model_scale']
    if (a[2] == b[2] or math.dist(a[:2],b[:2])*scale > _CROP_AXIS_TOLERANCE_MODEL_M):
        raise ValueError('Crop supports an axial native Z line only')
    z0, z1 = config['crop_z_native']
    lo, hi = sorted((a[2],b[2]))
    if not lo <= z0 <= hi or not lo <= z1 <= hi:
        raise ValueError('Crop endpoints must lie within the exact source Z domain')
    t0, t1 = (z0-a[2])/(b[2]-a[2]), (z1-a[2])/(b[2]-a[2])
    if not 0 <= t0 < t1 <= 1:
        raise ValueError('Crop must have positive length and preserve source direction')
    if t0 == 0 and t1 == 1:
        raise ValueError('A whole line needs no crop; use the unchanged whole-line mode')
    points = [[a[i]+f*(b[i]-a[i]) for i in range(3)] for f in (t0,t1)]
    points[0][2], points[1][2] = z0, z1
    result = deepcopy(line)
    result['start_native'], result['end_native'] = points
    native = result['line_native']; source = line['line_native']
    d0, d1 = _number(source['start_diameter']), _number(source['end_diameter'])
    native['start_diameter'], native['end_diameter'] = d0+t0*(d1-d0), d0+t1*(d1-d0)
    for key in ('length_along_axis','true_length'):
        native[key] = _number(source[key])*(t1-t0)
    return result


def _capture_crop(sw, clsid, typelib_path, selected, linked_feature_index, expected_document_path,
                  *, check, diagnostic):
    """裁剪专用快照：每个上下文/集合 getter 都经过同一事件检查。"""
    from scripts.sw_cam_turn_feature_attribute import _context as context, _inventory as inventory, _items as items
    from scripts.sw_operation_guard import check_document_target
    def read(obj, name, *args):
        diagnostic['stage']=name;check();value=_member(obj,name,*args);check();return value
    before, doc, part, machine, app = context(sw,clsid,typelib_path,read)
    diagnostic['document']=before
    check_document_target(before['path'],before['title'],expected_path=expected_document_path,required=True)
    initial=inventory(machine,typelib_path,read);diagnostic['inventory']=initial
    records=[];handles={};total_links=0;diagnostic['operations']=records
    for si, raw_setup in enumerate(items(read(machine,'IGetEnumOpSetups'),typelib_path,read)):
        setup=_typed(raw_setup,'ICWBaseOpSetup',typelib_path)
        for oi, raw in enumerate(items(read(setup,'IGetEnumOperations'),typelib_path,read,limit=512-len(records))):
            operation=_typed(raw,'ICWOperation',typelib_path);turn=_typed(raw,'ICWTurnOperation',typelib_path)
            oid=_object_id(doc,operation,read)
            if oid in handles: raise ValueError('Duplicate native operation ID')
            linked=items(read(operation,'IGetAllFeatures'),typelib_path,read,limit=min(64,1024-total_links))
            total_links+=len(linked)
            ids=[_object_id(doc,feature,read) for feature in linked]
            if len(set(ids))!=len(ids): raise ValueError('Duplicate linked native feature ID')
            records.append(dict(setup_index=si,operation_index=oi,native_id=oid,
                turn_operation_type=_integer(read(turn,'OpernType')),linked_feature_ids=ids))
            handles[oid]=dict(raw=raw,operation=operation,linked=linked)
    target=next((row for row in records if row['setup_index']==selected['setup_index'] and
        row['operation_index']==selected['operation_index'] and row['turn_operation_type']==selected['expected_operation_type']),None)
    if target is None: raise ValueError('Exact selected crop source operation is absent')
    handle=handles[target['native_id']]
    if not 0<=linked_feature_index<len(handle['linked']): raise ValueError('Linked crop source feature is absent')
    raw_feature=handle['linked'][linked_feature_index];profile={};diagnostic['selected_profile']=profile
    _read_profile(raw_feature,typelib_path,read,[0],profile,
        collection_reader=lambda value,limit:items(value,typelib_path,read,limit=limit))
    # 创建几何不需要 THREAD 目录；避免在新裁剪分支增加无关的原生读取。
    catalog={'read':False,'reason':'not_required_for_line_crop'}
    saved_hash=_file_hash(before['path']);check()
    final=inventory(machine,typelib_path,read)
    if document_snapshot(sw)!=before or final!=initial: raise ValueError('Crop document or inventory changed during capture')
    check()
    state=dict(document=before,saved_file_sha256=saved_hash,inventory=initial,operations=records,
        selected_operation=selected,selected_operation_id=target['native_id'],linked_feature_index=linked_feature_index,
        selected_feature_id=target['linked_feature_ids'][linked_feature_index],selected_profile=profile,
        thread_catalog=catalog,native_id_scope='current_document_requires_fresh_prepare_after_reopen')
    return state,dict(doc=doc,app=app,feature=raw_feature,after_operation=handle['operation'],operations=handles,machine=machine)


def _snapshot(sw, clsid, typelib_path, config, *, check=lambda: None, diagnostic=None):
    from scripts.sw_cam_feature_sketch import inspect_meridional_plane
    diagnostic = {} if diagnostic is None else diagnostic
    selected = {key: config[key] for key in ("setup_index", "operation_index", "expected_operation_type")}
    cropped = config.get('crop_z_native') is not None
    capture_source = _capture_crop if cropped else _capture
    state, native = capture_source(sw, clsid, typelib_path, selected, config["linked_feature_index"],
                            config["expected_document_path"], check=check, diagnostic=diagnostic)
    def read(obj, name, *args):
        diagnostic['stage']=name;check();value=_member(obj,name,*args);check();return value
    if cropped:
        from scripts.sw_cam_turn_feature_attribute import _items as guarded_items, _inventory as guarded_inventory
    profile = state["selected_profile"]
    if profile["turn_feature_type_raw"] != config["candidate_feature_type"]:
        raise ValueError("Candidate must equal the explicitly observed source turn-feature type")
    index = config["segment_index"]
    if index >= len(profile["segments"]):
        raise ValueError("Source segment is absent")
    line = profile["segments"][index]
    if line.get("curve_type_raw") != 0 or not line.get("curve_parameters_available"):
        raise ValueError("A confirmed native line segment is required")
    points = [line["start_native"], line["end_native"]]
    if math.dist(*points) <= 0:
        raise ValueError("Source line has zero length")
    creation_line = _crop_line(line, config, state) if config.get("crop_z_native") is not None else line
    if config.get("crop_z_native") is not None:
        points = [creation_line["start_native"], creation_line["end_native"]]
    model = _member(sw, "ActiveDoc")
    if _member(model, "GetActiveSketch2") is not None:
        raise ValueError("No existing sketch may be in edit mode")
    model_points = [[_number(v) * config["native_to_model_scale"] for v in point] for point in points]
    diagnostic["stage"] = "reference_plane"
    plane, _plane_feature = inspect_meridional_plane(sw, model, model_points)
    # IGetMachine 属于 ICWPartDoc，不能在 ICWDoc3 的重复 DISPID 上调用。
    if cropped:
        machine = _typed(native['machine'],'ICWMachine5',typelib_path)
        setups = guarded_items(read(machine,'IGetEnumSetups'),typelib_path,read)
    else:
        native_part = _typed(native["doc"], "ICWPartDoc", typelib_path)
        machine = _typed(_member(native_part, "IGetMachine"), "ICWMachine5", typelib_path)
        setups = _collection(_member(machine, "IGetEnumSetups"), typelib_path)
    if config["feature_setup_index"] >= len(setups):
        raise ValueError("Target feature setup is absent")
    features, budget = [], [0]
    for si, raw_setup in enumerate(setups):
        setup = _typed(raw_setup, "ICWBaseSetup", typelib_path)
        raw_features = read(setup,'IGetEnumFeatures')
        items = (guarded_items(raw_features,typelib_path,read,limit=64-len(features)) if cropped
                 else _collection(raw_features,typelib_path))
        for raw in items:
            if len(features) >= 64:
                raise ValueError("Too many existing CAM features")
            row = {"setup_index": si, "native_id": _object_id(native["doc"], raw, read), "profile": {}}
            features.append(row)
            if cropped:
                _read_profile(raw,typelib_path,read,budget,row['profile'],
                    collection_reader=lambda value,limit:guarded_items(value,typelib_path,read,limit=limit))
            else:
                _read_profile(raw, typelib_path, read, budget, row["profile"])
    if len({item["native_id"] for item in features}) != len(features):
        raise ValueError("Existing feature IDs must be unique")
    if not any(item["native_id"] == state["selected_feature_id"] and
               item["setup_index"] == config["feature_setup_index"] for item in features):
        raise ValueError("Source feature must belong to the explicitly selected target setup")
    state.update(config=deepcopy(config), source_line=deepcopy(line), endpoints_model_m=model_points,
                 plane=plane, features=features, solids=_body_state(model), model_features=_model_features(model))
    if config.get("crop_z_native") is not None:
        state["creation_line"] = deepcopy(creation_line)
        state["source_line_sha256"] = _digest(line)
    diagnostic["mass_properties_native_raw"] = [deepcopy(body["mass_properties_native"]) for body in state["solids"]]
    check()
    if document_snapshot(sw) != state['document']:
        raise ValueError('Document or inventory changed during feature snapshot')
    after_inventory = (guarded_inventory(machine,typelib_path,read) if cropped else _inventory(machine,typelib_path))
    if after_inventory != state['inventory']:
        raise ValueError('Document or inventory changed during feature snapshot')
    native.update(model=model, machine=machine, target_setup=setups[config["feature_setup_index"]])
    diagnostic["stage"] = "complete"
    return state, native


def _verify(before, after, *, sketch_added=False, new_id=None, saving=False):
    expected = deepcopy(before)
    expected["document"]["needs_save"] = after["document"]["needs_save"]
    if saving:
        expected["saved_file_sha256"] = after["saved_file_sha256"]
    if sketch_added:
        name = before["config"]["sketch_name"]
        added = [item for item in after["model_features"] if item["name"] == name]
        if len(added) != 1 or added[0]["type"] != "ProfileFeature":
            raise ValueError("Exactly one new 2D sketch is required")
        if [item for item in after["model_features"] if item["name"] != name] != before["model_features"]:
            raise ValueError("An existing model feature changed")
        expected["model_features"] = deepcopy(after["model_features"])
    if new_id is not None:
        rows = [item for item in after["features"] if item["native_id"] == new_id]
        if len(rows) != 1 or any(item["native_id"] == new_id for item in before["features"]):
            raise ValueError("Returned feature is not exactly one new positive native ID")
        row = rows[0]
        if row["setup_index"] != before["config"]["feature_setup_index"]:
            raise ValueError("New feature belongs to another setup")
        profile = row["profile"]
        if profile["turn_feature_type_raw"] != before["config"]["candidate_feature_type"] or profile["segment_count"] != 1:
            raise ValueError("Candidate mapping or single-segment feature readback did not match")
        line = profile["segments"][0]
        if line.get("curve_type_raw") != 0 or not line.get("curve_parameters_available"):
            raise ValueError("Created feature is not a confirmed line")
        points = [line["start_native"], line["end_native"]]
        reference_line = before.get("creation_line", before["source_line"])
        source = [reference_line["start_native"], reference_line["end_native"]]
        tolerance = 1e-8 / before["config"]["native_to_model_scale"]
        if not any(all(math.dist(a, b) <= tolerance for a, b in zip(points, order)) for order in (source, source[::-1])):
            raise ValueError("Created native feature endpoints differ from the qualified source line")
        for key in ("start_diameter", "end_diameter", "length_along_axis", "true_length"):
            actual = abs(_number(line["line_native"][key]))
            reference = abs(_number(reference_line["line_native"][key]))
            if abs(actual - reference) > tolerance:
                raise ValueError("Created native line dimensions differ from the source")
        if [item for item in after["features"] if item["native_id"] != new_id] != before["features"]:
            raise ValueError("An existing CAM feature changed")
        expected["features"] = deepcopy(after["features"])
        expected["inventory"]["feature_count"] += 1
        expected["inventory"]["feature_counts_by_setup"][row["setup_index"]] += 1
    if not _states_equal(expected, after):
        raise ValueError("Unexpected change to document, saved file, solids, old features or operation paths")


def _created_orientation(before, after, new_id):
    """只比较已读端点顺序；不把几何等价解释为进给方向或旋向。"""
    requested=before.get('creation_line',before['source_line'])
    actual=next(row['profile']['segments'][0] for row in after['features'] if row['native_id']==new_id)
    wanted=[requested['start_native'],requested['end_native']]
    observed=[actual['start_native'],actual['end_native']]
    tolerance=1e-8/before['config']['native_to_model_scale']
    forward=all(math.dist(a,b)<=tolerance for a,b in zip(wanted,observed))
    reverse=all(math.dist(a,b)<=tolerance for a,b in zip(wanted,observed[::-1]))
    order=('ambiguous_within_numeric_tolerance' if forward and reverse else
           'same_as_requested' if forward else 'reversed_by_native' if reverse else 'mismatch')
    return dict(requested_endpoints_native=deepcopy(wanted),returned_endpoints_native=deepcopy(observed),
        endpoint_order=order,same_order_verified=forward and not reverse,
        tolerance_native=tolerance,thread_direction_verified=False,automatic_reversal_performed=False)


def qualify_turn_feature(sw, clsid, typelib_path, *, expected_document_path, setup_index,
        operation_index, expected_operation_type, linked_feature_index, segment_index,
        feature_setup_index, candidate_feature_type, native_to_model_scale, sketch_name,
        action, qualification_only, acknowledge_unverified_type_mapping, message_policy,
        expected_state_sha256=None, receipt_path=None, expected_new_feature_native_id=None,
        crop_z_native=None, process_id=None, expected_source_operation_native_id=None,
        expected_source_feature_native_id=None, expected_source_line_sha256=None, expected_source_sha256=None):
    """准备/执行一次明确假设的直线车削特征创建，或单独试验 CAM 保存。

    必须绑定保存路径、源操作/段、原生到模型米的显式比例和新草图名。apply 需要
    prepare 的 SHA 与新回执；save_candidate 另需新特征 ID。返回始终要求人工复核，
    不创建 THREAD、不生成刀路；保存返回不等于关闭重开持久化已通过。
    """
    from scripts.sw_cam_events import CamMessageSession
    from scripts.sw_cam_feature_sketch import create_single_line_sketch
    config = dict(expected_document_path=expected_document_path, setup_index=setup_index,
        operation_index=operation_index, expected_operation_type=expected_operation_type,
        linked_feature_index=linked_feature_index, segment_index=segment_index,
        feature_setup_index=feature_setup_index, candidate_feature_type=candidate_feature_type,
        native_to_model_scale=native_to_model_scale, sketch_name=sketch_name)
    report = {"status": "error", "action": action, "phase": "preflight", "may_continue": False,
        "mutation_attempted": False, "feature_call_attempted": False, "native_call_returned": False,
        "generation_attempted": False, "thread_created": False, "model_saved": False,
        "persistence_verified": False, "mapping_verified": False, "snapshot_diagnostics": [],
        "mapping_basis": "explicit_observed_type_hypothesis_requires_exact_geometry_readback",
        "mass_comparison": {"raw_values_retained": True, "hash_significant_digits": _MASS_SIGNIFICANT_DIGITS,
            "relative_tolerance": _MASS_RELATIVE_TOLERANCE, "absolute_tolerance": 0.0,
            "scope": "solids.mass_properties_native_only", "other_state_fields": "exact"}}
    receipt = None
    receipt_created = False
    session = None
    crop_entered = False
    crop_post_document = None
    try:
        _reference({key: config[key] for key in ("setup_index", "operation_index", "expected_operation_type")})
        for key, upper in (("linked_feature_index",63),("segment_index",511),("feature_setup_index",511),("candidate_feature_type",2147483647)):
            if type(config[key]) is not int or not 0 <= config[key] <= upper:
                raise ValueError("Invalid strict selector: " + key)
        crop_guards = (process_id, expected_source_operation_native_id, expected_source_feature_native_id,
                       expected_source_line_sha256, expected_source_sha256)
        if crop_z_native is None:
            if any(v is not None for v in crop_guards): raise ValueError('Crop guards require explicit crop_z_native')
        else:
            if action == 'save_candidate': raise ValueError('Crop saving is a separate native lifecycle action')
            if (not isinstance(crop_z_native,list) or len(crop_z_native)!=2 or
                    any(type(v) not in (int,float) or not math.isfinite(v) for v in crop_z_native)):
                raise ValueError('Two finite exact native Z endpoints are required')
            if crop_z_native[0] == crop_z_native[1]: raise ValueError('Crop cannot have zero length')
            for v in crop_guards[:3]:
                if type(v) is not int or not 0 < v < 2**32: raise ValueError('Exact crop PID/operation/feature IDs are required')
            for v in crop_guards[3:]:
                if type(v) is not str or not re.fullmatch(r'[0-9a-f]{64}',v): raise ValueError('Exact crop source/line SHA required')
            config.update(crop_z_native=list(map(float,crop_z_native)), process_id=process_id,
                expected_source_operation_native_id=expected_source_operation_native_id,
                expected_source_feature_native_id=expected_source_feature_native_id,
                expected_source_line_sha256=expected_source_line_sha256,expected_source_sha256=expected_source_sha256)
            report.update(crop_scope='same_source_axial_line_strict_domain_no_reversal',
                full_cam_snapshot_scope='before_event_disconnect',post_cleanup_cam_read_performed=False,
                crop_axis_tolerance_model_m=_CROP_AXIS_TOLERANCE_MODEL_M)
        scale = _number(native_to_model_scale)
        if not 0 < scale <= 1 or not isinstance(sketch_name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", sketch_name):
            raise ValueError("Explicit positive scale and an exact simple unique sketch name are required")
        config["native_to_model_scale"] = scale
        if not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold() != ".sldprt":
            raise ValueError("An exact absolute saved part is required")
        if qualification_only is not True or acknowledge_unverified_type_mapping is not True or message_policy != "vendor_default":
            raise ValueError("Explicit qualification/type hypothesis and vendor_default are required")
        if action not in {"inspect", "prepare", "apply", "save_candidate"}:
            raise ValueError("Unknown action")
        if action in {"inspect", "prepare"}:
            if any(value is not None for value in (expected_state_sha256, receipt_path, expected_new_feature_native_id)):
                raise ValueError("Inspect/prepare cannot take mutation inputs")
        else:
            if not isinstance(expected_state_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_state_sha256):
                raise ValueError("Exact prepared/final state SHA-256 required")
            receipt = Path(receipt_path) if isinstance(receipt_path,str) else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold() != ".json" or not receipt.parent.is_dir():
                raise ValueError("New absolute JSON receipt with an existing parent required")
            if action == "save_candidate":
                if type(expected_new_feature_native_id) is not int or not 0 < expected_new_feature_native_id <= 4294967295:
                    raise ValueError("Save candidate requires the exact new native feature ID")
            elif expected_new_feature_native_id is not None:
                raise ValueError("Apply cannot accept a preexisting new feature ID")
            _write_receipt(receipt, report, create=True)
            receipt_created = True
        def crop_identity():
            if _integer(_member(sw,'GetProcessID')) != process_id: raise ValueError('Exact crop PID mismatch')
            doc = document_snapshot(sw)
            if doc is None or doc['type'] != 1 or not doc['path']: raise ValueError('Saved crop target part required')
            from scripts.sw_operation_guard import check_document_target
            check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
            if _file_hash(doc['path']) != expected_source_sha256: raise ValueError('Crop source file SHA changed')
            return doc
        def check_events():
            summary = session.summary();report['messages'] = summary
            if (not summary.get('subscribed') or (crop_z_native is not None and not summary.get('active'))
                    or any(summary.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
                raise ValueError('CAM event requires review; stop further calls')
        if crop_z_native is not None:
            crop_post_document = crop_identity()
            addin = _member(sw,'GetAddInObject',clsid)
            if addin is None: raise ValueError('CAM add-in must already be loaded')
            app = _typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
            session = CamMessageSession(app,typelib_path)
            crop_entered = True
            session.__enter__()
            check_events()
        def capture(phase, identity_check=lambda:None, read_check=None):
            nonlocal crop_post_document
            diagnostic = {'phase':phase};report['snapshot_diagnostics'].append(diagnostic)
            progress = {'phase':phase,'status':'started','started_at_utc':datetime.now(timezone.utc).isoformat(),
                        'elapsed_seconds':0.0}
            report.setdefault('capture_progress',[]).append(progress)
            report['phase'] = phase + '_capture'
            # 持久化只读阶段，超时不等于已进入几何写入；绝不自动重放。
            if receipt_created: _write_receipt(receipt,report)
            started = time.perf_counter()
            try:
                if crop_z_native is not None: crop_identity();check_events()
                identity_check()
                guard = read_check or (check_events if crop_z_native is not None else (lambda:None))
                value = _snapshot(sw,clsid,typelib_path,config,check=guard,diagnostic=diagnostic)
                identity_check()
                if crop_z_native is not None:
                    check_events();crop_post_document = crop_identity()
                    if crop_post_document != value[0]['document']: raise ValueError('Crop document changed during snapshot')
                progress['status'] = 'completed'
                return value
            except Exception as exc:
                progress.update(status='error',issue=_error(exc))
                raise
            finally:
                progress['elapsed_seconds'] = time.perf_counter()-started
                report['phase'] = phase + '_capture_' + progress['status']
                if receipt_created: _write_receipt(receipt,report)
        before, native = capture("initial")
        report.update(before=before, state_sha256=_state_digest(before))
        if action == "inspect":
            report.update(status="review_required", phase="inspected", prepared=False,
                apply_eligible=False, snapshot_readback_completed=True,
                reason="READ_ONLY_CURRENT_STATE_NOT_PREPARED")
            return report
        if action != "save_candidate":
            if before["document"]["needs_save"] or any(item["name"] == sketch_name for item in before["model_features"]):
                raise ValueError("Creation requires a clean saved copy and a new sketch name")
        elif not any(item["native_id"] == expected_new_feature_native_id for item in before["features"]):
            raise ValueError("Expected created feature ID is absent")
        if action == "prepare":
            report.update(status="ok",phase="prepared");return report
        if report["state_sha256"] != expected_state_sha256:
            raise ValueError("Prepared feature/document/file state changed")
        if crop_z_native is None:
            session = CamMessageSession(native['app'],typelib_path)
        def check():
            check_events()
            current = document_snapshot(sw)
            if current is None or any(current[key] != before["document"][key] for key in ("path","title","type")):
                raise ValueError("Active document identity changed")
            if crop_z_native is not None: crop_identity()
            check_events()
        with (nullcontext(session) if crop_z_native is not None else session):
            check()
            current, native = capture("before_mutation",check,check_events)
            if not _states_equal(before, current):raise ValueError("State changed before mutation")
            report.update(phase="native_save" if action == "save_candidate" else "create_sketch",mutation_attempted=True)
            _write_receipt(receipt,report)
            if action == "save_candidate":
                app = _typed(native["app"],"ICWApp",typelib_path)
                check();_member(app,"SaveActiveDocument")
                report.update(native_call_returned=True,native_save_call_returned=True,phase="native_save_returned")
                _write_receipt(receipt,report);check()
                after, _ = capture("after_save",check,check_events)
                report["after"] = after;_verify(before,after,saving=True)
            else:
                report["sketch"] = {}
                sketch = create_single_line_sketch(sw,native["model"],endpoints_model_m=before["endpoints_model_m"],
                    sketch_name=sketch_name,expected_plane=before["plane"],diagnostic=report["sketch"],check=check)
                report["sketch"].update(sketch)
                if sketch.get("verified") is not True:raise ValueError("Sketch geometry readback was not verified")
                report["phase"] = "sketch_verified";_write_receipt(receipt,report)
                after_sketch,native = capture("after_sketch",check,check_events)
                _verify(before,after_sketch,sketch_added=True)
                setup = _typed(native["target_setup"],"ICWTurnSetup",typelib_path)
                report.update(phase="CreateTurnFeature",feature_call_attempted=True);_write_receipt(receipt,report)
                check();raw = _member(setup,"CreateTurnFeature",candidate_feature_type,sketch_name)
                report.update(native_call_returned=True,phase="CreateTurnFeature_returned",native_result_present=raw is not None and bool(raw))
                _write_receipt(receipt,report);check()
                if report["native_result_present"]:
                    def created_read(obj,name,*args):
                        if crop_z_native is not None: check_events()
                        value=_member(obj,name,*args)
                        if crop_z_native is not None: check_events()
                        return value
                    new_id = _object_id(native["doc"],raw,created_read)
                    report["new_feature_identity_source"] = "returned_object"
                after,_ = capture("after_feature",check,check_events);report["after"] = after
                if not report["native_result_present"]:
                    # 已返回但空对象不等于未创建：只读一次精确增量，绝不重放创建。
                    old_ids = {item["native_id"] for item in before["features"]}
                    added = [item["native_id"] for item in after["features"] if item["native_id"] not in old_ids]
                    if len(added) != 1 or type(added[0]) is not int or not 0 < added[0] <= 4294967295:
                        raise ValueError("Null creator return requires exactly one new positive feature ID")
                    new_id = added[0]
                    report["new_feature_identity_source"] = "snapshot_delta_after_null_return"
                report["new_feature_native_id"] = new_id
                _verify(before,after,sketch_added=True,new_id=new_id)
                report["created_feature_orientation"] = _created_orientation(before,after,new_id)
                report["null_result_recovered_by_exact_delta"] = not report["native_result_present"]
        if crop_z_native is not None:
            check();final = after
            crop_post_document = crop_identity()
            if crop_post_document != after['document']: raise ValueError('Crop document changed before disconnect')
            report['final_state'] = deepcopy(after)
        else:
            check()
            if not session.summary().get('disconnected'):raise ValueError('Event cleanup was not verified')
            final,_ = capture('after_cleanup',check,check_events);report['final_state'] = final
            if not _states_equal(after, final):raise ValueError('State changed during cleanup')
        report.update(status="review_required",phase="finished",state_sha256=_state_digest(final),readback_verified=True,
            mapping_verified=action=="apply",model_saved=action=="save_candidate",
            reason="SAVE_RETURNED_PERSISTENCE_REQUIRES_REOPEN" if action=="save_candidate" else "ONE_LINE_FEATURE_MAPPING_QUALIFIED_NOT_THREAD_CONFIGURATION")
    except Exception as exc:
        report.update(status="uncertain" if report["mutation_attempted"] else "error",failed_phase=report["phase"],
            reason="CAM_TURN_FEATURE_QUALIFICATION_FAILED",issue=_error(exc),phase="finished")
    finally:
        if crop_entered:
            try:
                session.__exit__(None,None,None)
                summary=session.summary();report['messages']=summary
                if (not summary.get('disconnected') or summary.get('active') or any(summary.get(k) for k in
                        ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors'))):
                    raise ValueError('Crop event cleanup was not cleanly verified')
                current = crop_identity()
                if report['status'] not in ('error','uncertain') and current != crop_post_document:
                    raise ValueError('Crop document changed after event cleanup')
                report['post_cleanup_document_file_verified']=True
            except Exception as exc:
                report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                    cleanup_issue=_error(exc),readback_verified=False,prepared=False,apply_eligible=False)
        if session is not None:report["messages"] = session.summary()
        if receipt_created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status="uncertain",receipt_write_error=_error(exc),readback_verified=False)
    return report
