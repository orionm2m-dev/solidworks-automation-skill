"""独立副本中单个 MILL 轮廓/深度的几何资格实验；无保存或加工生成。"""
from __future__ import annotations
from copy import deepcopy
from ctypes import byref, c_int
import math
from pathlib import Path
import re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _items
from scripts.sw_cam_mill_qualification import _bootstrap, _snapshot as _mill_snapshot, _vector
from scripts.sw_cam_profile_sketch import (_input as _sketch_input, _read_sketch,
    _features, _bodies, _same_bodies, _state_digest, call)
from scripts.sw_cam_mill_units_geometry import prove_mill_units_geometry, _rectangle
from scripts.sw_cam_mill_circle_geometry import prove_mill_circle_geometry
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('Exact lower-case SHA256 required')
    return value


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Finite native number required')
    return float(value)


def _same(a,b):
    if not _same_bodies(a['solids'],b['solids']):return False
    left=deepcopy(a);right=deepcopy(b);left.pop('solids');right.pop('solids')
    return left==right


def _ordered_sketch_points(data,spec):
    """将真实端点按已核对的 SW 轮廓顺序排列，而不是用请求值伪造回读。"""
    expected=[[v/1000 for v in p] for p in spec['profile']['points_model_mm']]
    rows=data['entities'];result=[]
    if len(rows)!=4 or any(row.get('type')!='line' for row in rows):raise ValueError('Exactly four actual SW line segments required')
    available=list(rows)
    for i,a in enumerate(expected):
        b=expected[(i+1)%4];matches=[]
        for n,row in enumerate(available):
            for pair in (row['points_model_m'],row['points_model_m'][::-1]):
                if math.dist(a,pair[0])<=1e-8 and math.dist(b,pair[1])<=1e-8:matches.append((n,pair[0]))
        if len(matches)!=1:raise ValueError('Actual sketch endpoints do not uniquely match requested rectangle')
        n,point=matches[0];result.append(point);available.pop(n)
    return result


def _contour(feature,method,typelib_path,read):
    """复用已核对的零基 INT* 曲线索引；只接受单链四条直线。"""
    raw=read(feature,method)
    if raw is None or not bool(raw):raise ValueError('Actual native contour is unavailable: '+method)
    chain=_typed(raw,'ICWSegChain',typelib_path)
    n=read(chain,'IGetNumChains');count=read(chain,'GetNumOfCurves')
    if type(n) is not int or n!=1 or type(count) is not int or count!=4:raise ValueError('Unit pilot requires one native four-curve chain')
    rows=[]
    for index in range(4):
        native_index=c_int(index)
        curve=_typed(read(chain,'GetCurveAtIndex',byref(native_index)),'ICWCurve',typelib_path)
        kind=read(curve,'GetTypeOfCurve')
        if type(kind) is not int or kind!=0:raise ValueError('Native contour must contain actual LINE curves only')
        pair=[]
        for getter in ('GetStart','GetEnd'):
            position=_typed(read(curve,getter),'ICWPosition',typelib_path)
            pair.append(_vector(read(position,'GetCoordinates')))
        rows.append(pair)
    return rows


def _feature(raw,doc,typelib_path,read):
    base=_typed(raw,'ICWFeature',typelib_path);feature=_typed(raw,'ICWMillFeature',typelib_path)
    kind=read(feature,'VolumeType');suppressed=read(base,'Suppressed')
    if type(kind) is not int or kind!=6 or suppressed is not False:raise ValueError('Only an unsuppressed OPEN_POCKET feature can be inspected')
    row=dict(native_id=_object_id(doc,base,read),volume_type=kind,suppressed=suppressed,
        name=read(base,'FeatureName'),axis_native=_vector(read(base,'Axis')),
        depth_native=_number(read(feature,'Depth')),bounds_native=_vector(read(feature,'GetBoundParams')),
        start_native=_vector(read(feature,'GetStartPosition')),
        top_segments_native=_contour(feature,'IGetTopSegChain',typelib_path,read),
        bottom_segments_native=_contour(feature,'IGetBottomSegChain',typelib_path,read))
    if type(row['name']) is not str or len(row['name'])>1024:raise ValueError('Bounded native feature name required')
    return row



def _nonnull(value, label):
    if value is None or type(value) in (bool,int,float,str,list,tuple,dict) or not bool(value):
        raise ValueError('Non-null native interface required: ' + label)
    return value


def _strict_integer(value, label):
    if type(value) is not int:
        raise ValueError('Strict native integer required: ' + label)
    return value


def _circle_sketch(data, spec):
    """Use the measured SW circle and rigid model-to-sketch normal."""
    rows = data['entities']
    if len(rows) != 1 or rows[0].get('type') != 'circle':
        raise ValueError('Exactly one actual saved SW circle required')
    row = rows[0]
    center = _vector(row['center_model_m'])
    radius = _number(row['radius_m'])
    expected = spec['profile']
    if radius <= 0 or math.dist(center, [v/1000 for v in expected['center_model_mm']]) > 1e-8 or abs(radius-expected['radius_mm']/1000) > 1e-8:
        raise ValueError('Actual SW circle differs from pinned sketch specification')
    transform = data['model_to_sketch_transform']
    if not isinstance(transform, (list, tuple)) or len(transform) != 16:
        raise ValueError('Measured rigid SW sketch transform required')
    transform = [_number(x) for x in transform]
    # SW uses row vectors; local Z in model is column three of model-to-sketch rotation.
    normal = [transform[2], transform[5], transform[8]]
    if abs(math.sqrt(sum(v*v for v in normal))-1.) > 1e-8 or abs(transform[12]-1.) > 1e-8:
        raise ValueError('Measured unit sketch normal and rigid scale required')
    return dict(center_model_m=center, radius_m=radius, normal_model=normal)


def _circle_contour(feature, method, typelib_path, read, typed):
    """Read a full native CIRCLE or an ARC chain; never reinterpret curve types."""
    chain = typed(read(feature, method), 'ICWSegChain')
    n = _strict_integer(read(chain, 'IGetNumChains'), 'IGetNumChains')
    count = _strict_integer(read(chain, 'GetNumOfCurves'), 'GetNumOfCurves')
    if n != 1 or not 1 <= count <= 64:
        raise ValueError('One bounded circular contour chain required')
    rows = []
    def position(raw):
        return _vector(read(typed(raw, 'ICWPosition'), 'GetCoordinates'))
    def normal(raw):
        return _vector(read(typed(raw, 'ICWUnitVector'), 'GetCoordinates'))
    for index in range(count):
        native_index = c_int(index)
        curve = typed(read(chain, 'GetCurveAtIndex', byref(native_index)), 'ICWCurve')
        kind = _strict_integer(read(curve, 'GetTypeOfCurve'), 'GetTypeOfCurve')
        if kind == 2:
            circle = typed(curve, 'ICWCircle')
            row = dict(curve_type=kind, centre_native=position(read(circle, 'CenterPoint')),
                       radius_native=_number(read(circle, 'GetRadius')),
                       normal_native=normal(read(circle, 'IGetNormal')),
                       direction_raw=_strict_integer(read(circle, 'GetDirection'), 'GetDirection'))
        elif kind == 1:
            arc = typed(curve, 'ICWArc')
            row = dict(curve_type=kind, start_native=position(read(curve, 'GetStart')),
                       end_native=position(read(curve, 'GetEnd')), mid_native=position(read(curve, 'GetMid')),
                       centre_native=position(read(arc, 'CenterPoint')),
                       radius_native=_number(read(arc, 'IGetRadius')),
                       normal_native=normal(read(arc, 'IGetNormal')),
                       sense_raw=_strict_integer(read(arc, 'IGetSense'), 'IGetSense'))
        else:
            raise ValueError('Circular pocket accepts only documented CIRCLE or ARC curve types')
        if row['radius_native'] <= 0:
            raise ValueError('Positive measured native radius required')
        rows.append(row)
    return rows


def _circle_feature(raw, doc, typelib_path, read, typed):
    base = typed(raw, 'ICWFeature')
    feature = typed(raw, 'ICWMillFeature')
    kind = _strict_integer(read(feature, 'VolumeType'), 'VolumeType')
    suppressed = read(base, 'Suppressed')
    if kind != 2 or suppressed is not False:
        raise ValueError('Only an unsuppressed POCKET volume can be inspected')
    row = dict(native_id=_object_id(doc, base, read), volume_type=kind, suppressed=suppressed,
        name=read(base, 'FeatureName'), axis_native=_vector(read(base, 'Axis')),
        depth_native=_number(read(feature, 'Depth')), bounds_native=_vector(read(feature, 'GetBoundParams')),
        start_native=_vector(read(feature, 'GetStartPosition')),
        top_curves_native=_circle_contour(feature, 'IGetTopSegChain', typelib_path, read, typed),
        bottom_curves_native=_circle_contour(feature, 'IGetBottomSegChain', typelib_path, read, typed))
    if type(row['name']) is not str or len(row['name']) > 1024:
        raise ValueError('Bounded native feature name required')
    return row


def qualify_mill_feature_units(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,action,expected_setup_native_id,sketch_spec,depth_native,
        qualification_only,acknowledge_disposable_copy,message_policy='vendor_default',
        expected_state_sha256=None,expected_feature_native_id=None,receipt_path=None,reverse_direction=False,feature_kind="open_pocket"):
    """在空白 MILL 副本创建一次盲 OPEN_POCKET，读取真实上下轮廓证明局部尺寸一致性。

    dDepth 的原生 ABI 是 DOUBLE；只允许1..100整数是资格实验的明确输入限制。
    无单位默认值，无进给/速度推断，结果必须单独审核，不更改现有数值单位门禁。
    """
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status='error',phase='preflight',action=action,may_continue=False,mutation_attempted=False,
        native_call_returned=False,readback_verified=False,model_saved=False,AFR_attempted=False,
        GOP_attempted=False,GTP_attempted=False,sketch_edit_attempted=False,stock_edit_attempted=False,
        global_native_units_verified=False,feed_units_verified=False,production_qualified=False,
        post_cleanup_CAM_getters=False,unsupported_unit_getter_called=False,
        geometry_scope='single_open_pocket_actual_top_bottom_contours',
        requested_reverse_direction=reverse_direction,reverse_direction_native_readback_verified=False,
        creation_delta_verified=False,native_feature_readback_complete=False,
        orientation_semantics_verified=False)
    receipt=session=None;created=False
    try:
        if type(process_id) is not int or not 0<process_id<2**32:raise ValueError('Exact positive PID required')
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold()!='.sldprt'):raise ValueError('Absolute saved qualification part required')
        _sha(expected_source_sha256)
        if qualification_only is not True or acknowledge_disposable_copy is not True or message_policy!='vendor_default':raise ValueError('Explicit disposable qualification required')
        if action not in ('inspect','prepare','apply'):raise ValueError('Unsupported action')
        if type(expected_setup_native_id) is not int or not 0<expected_setup_native_id<2**32:raise ValueError('Exact setup ID required')
        if feature_kind not in ('open_pocket', 'circular_pocket') or type(feature_kind) is not str:
            raise ValueError('Explicit supported feature_kind required')
        circular = feature_kind == 'circular_pocket'
        if circular:
            if not 0 < _number(depth_native) <= 100:raise ValueError('Positive finite circular-pocket depth <=100 required')
            report.update(geometry_scope='single_closed_circular_pocket_actual_top_bottom_contours',
                          feature_kind=feature_kind, process_id=process_id, physical_depth_verified=False)
        elif type(depth_native) is not int or not 1<=depth_native<=100:
            raise ValueError('Integer pilot depth1..100 required; native ABI DOUBLE')
        if type(reverse_direction) is not bool:raise ValueError('reverse_direction must be a strict Boolean')
        spec=_sketch_input(sketch_spec)
        if circular:
            if spec['profile']['kind'] != 'circle':raise ValueError('Known saved full circle required')
        elif spec['profile']['kind']!='closed_polyline' or len(spec['profile']['points_model_mm'])!=4:
            raise ValueError('Known asymmetric four-line rectangle required')
        if expected_feature_native_id is not None and (action!='inspect' or type(expected_feature_native_id) is not int or not 0<expected_feature_native_id<2**32):raise ValueError('Existing feature ID is inspect-only')
        if action=='apply':
            _sha(expected_state_sha256)
            receipt=Path(receipt_path) if type(receipt_path) is str else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold()!='.json' or not receipt.parent.is_dir():raise ValueError('New absolute JSON receipt required')
            _write_receipt(receipt,report,create=True);created=True
        elif expected_state_sha256 is not None or receipt_path is not None:raise ValueError('Read action rejects mutation inputs')
        def identity():
            pid=call(sw,'GetProcessID')
            if type(pid) is not int or pid!=process_id:raise ValueError('Exact PID changed')
            if circular:
                model = _nonnull(sw.ActiveDoc, 'ActiveDoc')
                value = dict(path=call(model,'GetPathName'), title=call(model,'GetTitle'),
                             type=call(model,'GetType'), needs_save=call(model,'GetSaveFlag'))
                if type(value['type']) is not int or type(value['needs_save']) is not bool:
                    raise ValueError('Strict raw document type and save flag required')
            else:value=document_snapshot(sw)
            if value is None or value['type']!=1:raise ValueError('Active part required')
            check_document_target(value['path'],value['title'],expected_path=expected_document_path,required=True)
            if _file_hash(expected_document_path)!=expected_source_sha256:raise ValueError('Source file SHA changed')
            return value
        initial=identity()
        session=CamMessageSession(_bootstrap(sw,clsid,typelib_path,expected_document_path),typelib_path)
        def check():
            value=session.summary();report['messages']=value
            if not value.get('active') or not value.get('subscribed') or any(value.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):raise ValueError('CAM events/transport require review')
        def persist():
            if created:_write_receipt(receipt,report)
        def context_guard():
            value=identity()
            if any(value[key] != initial[key] for key in ('path','title','type')):
                raise ValueError('Active document identity changed')
        def read(obj,name,*args):
            report['phase']=name
            if circular:
                context_guard()
                report['last_native_read'] = dict(method=name, attempted=True, returned=False, validated=False)
                persist()
            check();value=_member(obj,name,*args)
            if circular:
                record=report['last_native_read'];record['returned']=True
                if type(value) in (str,int,float,bool,type(None)):
                    record['value']=value
                elif isinstance(value,(tuple,list)) and all(type(x) in (str,int,float,bool,type(None)) for x in value):
                    record['value']=list(value)
                else:record['interface_present']=value is not None and bool(value)
                persist()
            check()
            if circular:
                context_guard();report['last_native_read']['validated']=True;persist()
            return value
        def typed(raw,name):
            context_guard();check();_nonnull(raw,name+' raw')
            report['phase']='QI '+name
            report['last_native_read']=dict(method='QI '+name,attempted=True,returned=False,validated=False)
            persist()
            value=_typed(raw,name,typelib_path)
            report['last_native_read'].update(returned=True,interface_present=value is not None and bool(value))
            persist();_nonnull(value,name);check();context_guard()
            report['last_native_read']['validated']=True;persist()
            return value
        def capture():
            check();begin=identity()
            state,native=_mill_snapshot(sw,clsid,typelib_path,expected_document_path,check=check)
            if state['current_machine']['machine_type']!=1 or len(state['feature_setups'])!=1 or state['feature_setups'][0]['native_id']!=expected_setup_native_id:raise ValueError('One exact MILL setup required')
            if any(state['operation_counts']) or state['feature_setups'][0]['feature_count']>1:raise ValueError('Pilot has at most one feature and no operations')
            if state['feature_setups'][0]['feature_count'] and not report['mutation_attempted'] and action!='inspect':raise ValueError('Existing feature cannot be prepared or replayed')
            model=read(sw,'ActiveDoc')
            if call(model,'IsOpenedReadOnly') is not False:raise ValueError('Writable owned qualification copy required')
            configs=call(model,'GetConfigurationNames')
            if not isinstance(configs,(list,tuple)) or len(configs)!=1 or call(model,'GetActiveSketch2') is not None:raise ValueError('Single configuration outside sketch edit required')
            feature=call(model,'FeatureByName',spec['sketch_name'])
            if feature is None or call(feature,'GetTypeName2')!='ProfileFeature' or call(feature,'IsSuppressed') is not False:raise ValueError('Exact unsuppressed saved 2D sketch required')
            sketch=_read_sketch(sw,call(feature,'GetSpecificFeature2'),spec)
            if circular:circle=_circle_sketch(sketch,spec)
            else:
                points=_ordered_sketch_points(sketch,spec)
                _rectangle(points,1e-10,1e-6,1e-7,'observed_SW_sketch')
            tree,_=_features(model);bodies=_bodies(model)
            units=call(model,'GetUnits')
            if not isinstance(units,(tuple,list)) or len(units)!=5 or any(type(x) is not int for x in units):raise ValueError('Document unit record must be exact five integers')
            use=read(native['app'],'GetUseDocumentUnit')
            if type(use) is not bool:raise ValueError('Strict native document-unit flag required')
            setup=typed(native['setups'][0],'ICWBaseSetup') if circular else _typed(native['setups'][0],'ICWBaseSetup',typelib_path)
            raw=_items(read(setup,'IGetEnumFeatures'),typelib_path,read,limit=1)
            rows=[]
            for value in raw:
                observed_id=_object_id(native['doc'],value,read)
                report['observed_feature_native_id']=observed_id
                wanted_id=report.get('new_feature_native_id') if report['mutation_attempted'] else expected_feature_native_id
                if wanted_id!=observed_id:raise ValueError('Exact feature ID required before contour getters; no replay')
                rows.append(_circle_feature(value,native['doc'],typelib_path,read,typed) if circular else _feature(value,native['doc'],typelib_path,read))
            if len(rows)!=state['feature_setups'][0]['feature_count']:raise ValueError('Feature count differs during capture')
            state.update(features=rows,sketch=sketch,sketch_spec=spec,
                SW_feature_tree=tree,solids=bodies,SW_document_units_raw=list(units),CAM_use_document_units_raw=use,
                requested_depth_native=depth_native,requested_reverse_direction=reverse_direction,
                depth_ABI='DOUBLE_integer_input_is_pilot_policy')
            if circular:
                state.update(sketch_circle_m=circle,feature_kind=feature_kind,process_id=process_id,depth_ABI='DOUBLE_positive_finite_circle_policy')
            else:state['sketch_model_points_m']=points
            if begin!=identity() or state['document']!=begin:raise ValueError('Document changed during capture')
            check();return state,native
        with session:
            before,native=capture();report.update(before=before,state_sha256=_state_digest(before))
            count=len(before['features'])
            if count:
                if action!='inspect' or expected_feature_native_id!=before['features'][0]['native_id']:raise ValueError('Existing feature requires exact inspect ID; no replay')
            elif expected_feature_native_id is not None:raise ValueError('Expected existing feature is absent')
            eligible=not before['document']['needs_save'] and count==0 and not any(before['operation_counts'])
            report['apply_eligible']=eligible
            if action=='prepare' and not eligible:raise ValueError('Prepare requires clean saved empty qualification copy')
            if action=='apply':
                if not eligible or report['state_sha256']!=expected_state_sha256:raise ValueError('Clean prepared empty state changed')
                current,native=capture()
                if not _same(before,current) or identity()!=initial:raise ValueError('State changed before feature creation')
                setup=typed(native['setups'][0],'ICWSetup') if circular else _typed(native['setups'][0],'ICWSetup',typelib_path)
                report.update(phase='CreateMillFeature2',mutation_attempted=True);_write_receipt(receipt,report);check()
                value=_member(setup,'CreateMillFeature2',0 if circular else 5,spec['sketch_name'],False,float(depth_native),reverse_direction,False,False,False,0.,-1,False,0,0)
                report.update(native_call_returned=True,native_result_present=value is not None and bool(value),phase='CreateMillFeature2_returned')
                _write_receipt(receipt,report);check()
                if value is None or not bool(value):raise ValueError('Native return null: inspect existing state explicitly; never replay')
                if circular:_nonnull(value,'CreateMillFeature2 return')
                new_id=_object_id(native['doc'],value,read);report['new_feature_native_id']=new_id
                final,_=capture();report['after']=final
                if len(final['features'])!=1 or final['features'][0]['native_id']!=new_id:raise ValueError('Exactly one new feature required')
                wanted=deepcopy(before);wanted['document']['needs_save']=final['document']['needs_save']
                wanted['feature_setups'][0]['feature_count']=1;wanted['features']=final['features']
                if not _same(wanted,final):raise ValueError('Unexpected state change beyond one CAM feature')
                report['creation_delta_verified']=True
                _write_receipt(receipt,report)
            else:final=before
            if final['features']:
                row=final['features'][0]
                report['native_feature_readback_complete']=True
                report['observed_feature']=deepcopy(row)
                if created:_write_receipt(receipt,report)
                if row['depth_native']!=depth_native:raise ValueError('Feature depth scalar differs')
                if circular:
                    proof=prove_mill_circle_geometry(final['sketch_circle_m'],row['top_curves_native'],
                        row['bottom_curves_native'],depth_native,row['axis_native'])
                    report['dimensional_evidence']=proof
                    report.update(contour_readback_verified=proof['contour_verified'],
                        geometric_readback_verified=proof['depth_matches_requested_native'],
                        depth_axis_metric_independently_verified=False,absolute_native_frame_verified=False,
                        physical_depth_verified=False,observed_native_units_per_mm=proof['native_units_per_mm'],
                        interpreted_contour_separation_mm=proof['measured_separation_native']/proof['native_units_per_mm'])
                else:
                    proof=prove_mill_units_geometry(final['sketch_model_points_m'],row['top_segments_native'],row['bottom_segments_native'],depth_native)
                    report['dimensional_evidence']=proof
                    report.update(native_curve_line_types_verified=True,geometric_readback_verified=True,
                        depth_axis_metric_independently_verified=False,absolute_native_frame_verified=False,
                        observed_native_units_per_mm=proof['native_units_per_mm'],
                        interpreted_depth_mm=proof['measured_separation_mm_using_in_plane_scale'])
            report['final_subscribed']=final;check()
        summary=session.summary();report['messages']=summary
        if summary.get('disconnected') is not True or summary.get('active') or any(summary.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):raise ValueError('Event cleanup unconfirmed')
        if identity()!=final['document']:raise ValueError('Document/file changed after cleanup')
        report.update(status='review_required' if final['features'] else 'ok',phase='finished',
            readback_verified=bool(final['features']),reason=('CIRCULAR_CONTOUR_READBACK_REQUIRES_SEPARATE_FRAME_DEPTH_AND_TOOLPATH_QUALIFICATION'
                if circular else 'LOCAL_CONTOUR_SCALE_AND_DEPTH_EVIDENCE_REQUIRES_REVIEW_NOT_GLOBAL_UNITS'))
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],phase='finished',
            issue=_error(exc),readback_verified=False,geometric_readback_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False,geometric_readback_verified=False)
    return report
