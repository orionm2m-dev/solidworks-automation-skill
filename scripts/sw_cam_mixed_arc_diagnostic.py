"""Read the existing mixed sketch after a bounded creation-readback failure.

This diagnostic records raw curve interval and arc direction independently. It
never creates, edits, selects, saves, closes, or regenerates a document or sketch.
"""
from copy import deepcopy
from pathlib import Path
import math
from scripts import sw_cam_mixed_root_pockets as parent
from scripts import sw_cam_profile_sketch as core
from scripts import sw_cam_long_cut_reconciliation as bounded
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam import _error
from scripts.sw_cam_upper_cone_feature import _process_identity

common = parent.common
SCOPE = 'EXISTING_MIXED_SKETCH_RAW_ARC_DIAGNOSTIC_V1'
PARAMS = {'process_id', 'expected_document_path', 'expected_source_sha256',
          'failed_receipt_path', 'failed_receipt_sha256', 'module_sha256', 'receipt_path'}


def failed_contract(receipt):
    require(receipt.get('scope') == parent.SCOPE and receipt.get('module_pin') == common._pin(parent.__file__),
            'Exact original mixed-pocket producer required')
    require(receipt.get('status') == 'uncertain' and receipt.get('phase') == 'finished', 'Exact terminated failure required')
    require(receipt.get('cleanup_session_active') is False and receipt.get('new_feature_ids') == [], 'No native pocket was created')
    require(list(receipt['actions']) == ['CreateSketch:0'], 'Only the first sketch may have been attempted')
    action = receipt['actions']['CreateSketch:0']
    require(action == dict(status='pending', attempted=True, returned=False, readback_verified=False, native_dispatch_pending=True),
            'Original uncertain sketch boundary changed')
    require(all(receipt.get(k) is False for k in ('save_attempted','model_saved','readback_verified','continuation_ready',
            'GOP_attempted','GTP_attempted','SetTool_attempted','operation_creation_attempted','tool_creation_attempted')),
            'No later native mutation or save allowed')
    require(receipt['issue']['type'] == 'ValueError' and receipt['issue']['locations'][-1] ==
            dict(file='sw_cam_mixed_profile.py', function='curve_interval', line=150), 'Exact interval failure required')
    require(len(receipt['sketch_creations']) == 1 and receipt['sketch_creations'][0].get('sketch_edit_exited') is True,
            'Owned first sketch must already be closed')
    require(receipt['profile_specs'][0]['sketch_name'] == 'RootRestProfile1' and
            receipt['profile_specs'][0]['plane_name'] == 'RootRestPlane1', 'Exact existing first sketch required')
    return receipt


def finite(value):
    require(type(value) in (int,float) and math.isfinite(value), 'Finite native numeric value required')
    return float(value)


def raw_end_params(curve, call=core.call):
    import pythoncom
    from win32com.client import VARIANT
    low = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R8, 0.)
    high = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R8, 0.)
    closed = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    periodic = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    returned = call(curve, 'GetEndParams', low, high, closed, periodic)
    return dict(returned=returned, returned_type=type(returned).__name__, low=low.value, high=high.value,
                closed=closed.value, closed_type=type(closed.value).__name__,
                periodic=periodic.value, periodic_type=type(periodic.value).__name__)


def read_rows(sw, sketch, *, check, persist, report):
    require(core.call(sketch, 'Is3D') is False, 'Existing two-dimensional sketch required')
    raw = core.call(sketch, 'GetSketchSegments')
    require(type(raw) in (list,tuple) and len(raw) == 13, 'Existing thirteen sketch entities required')
    mu = core.call(sw, 'GetMathUtility')
    transform = sketch.ModelToSketchTransform
    core._rigid_transform(transform)
    inverse = core.call(transform, 'Inverse');core._rigid_transform(inverse)
    report['model_to_sketch_transform'] = [finite(v) for v in transform.ArrayData]
    rows = report.setdefault('native_entities', [])
    for index, segment in enumerate(raw):
        check()
        kind = core.call(segment, 'GetType')
        require(type(kind) is int and kind in (0,1), 'Only native line and arc segments allowed')
        require(segment.ConstructionGeometry is False, 'Construction entity unexpected')
        native = core._typed_segment(segment, kind)
        local = [core._point_values(core.call(native,key)) for key in ('GetStartPoint2','GetEndPoint2')]
        row = dict(index=index, type='arc' if kind else 'line', endpoints_sketch_m=local,
                   endpoints_model_m=[core._point(mu,p,inverse) for p in local],
                   length_m=finite(core.call(segment,'GetLength')))
        rows.append(row);persist()
        if kind:
            row['is_circle_raw'] = core.call(native,'IsCircle')
            row['rotation_direction_raw'] = core.call(native,'GetRotationDir')
            normal=core.call(native,'GetNormalVector')
            require(type(normal) in (tuple,list) and len(normal)==3,'Three-component native arc normal required')
            row['normal_vector_raw']=[finite(v) for v in normal]
            center = core._point_values(core.call(native,'GetCenterPoint2'))
            row.update(center_sketch_m=center, center_model_m=core._point(mu,center,inverse),
                       radius_m=finite(core.call(native,'GetRadius')))
            curve = core.call(segment,'GetCurve')
            row['underlying_curve_end_params_raw'] = raw_end_params(curve)
            persist()  # Preserve raw closed/periodic values before any interval use.
            row['underlying_curve_closest_endpoints_raw'] = []
            for endpoint in local:
                value = core.call(curve,'GetClosestPointOn',*endpoint)
                require(type(value) in (tuple,list) and 3 <= len(value) <= 16, 'Bounded closest-point return required')
                row['underlying_curve_closest_endpoints_raw'].append([finite(v) for v in value])
            interval = row['underlying_curve_end_params_raw']
            low, high = finite(interval['low']), finite(interval['high'])
            if interval['returned'] is True and high > low:
                samples=[]
                for u in (low,(3*low+high)/4,(low+high)/2,(low+3*high)/4,high):
                    value = core.call(curve,'Evaluate2',u,0)
                    require(type(value) in (tuple,list) and 3 <= len(value) <= 16, 'Bounded curve evaluation required')
                    samples.append(dict(parameter=u, raw=[finite(v) for v in value]))
                row['underlying_curve_samples_raw'] = samples
        check();persist()
    return rows


def prepare(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='read_existing_mixed_arc',
            'Exact read-only diagnostic action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact diagnostic fields required')
    require(type(p['process_id']) is int and p['process_id']>0,'Positive owned process required')
    require(p['module_sha256']==parent._file_hash(__file__),'Exact diagnostic implementation required')
    receipt,pin=bounded.read_pin(p['failed_receipt_path'],p['failed_receipt_sha256']);failed_contract(receipt)
    require(p['process_id']==receipt['request']['process_id']==receipt['ownership']['process_id'],'Owned process differs')
    require(common._key(p['expected_document_path'])==common._key(receipt['source_path']),'Exact document required')
    require(p['expected_source_sha256']==receipt['source_sha256']==parent._file_hash(p['expected_document_path']),
            'Saved source must remain the failed packet baseline')
    output=Path(p['receipt_path']);common._local_receipt(output)
    require(output.is_absolute() and output.suffix.casefold()=='.json' and output.parent.is_dir() and not output.exists(),
            'Fresh diagnostic output required')
    pins=common._merge(receipt['initial_context']['checkpoint_pins'],receipt['initial_context']['pins'],
        [pin,common._pin(__file__),common._pin(core.__file__)])
    require(common._key(output) not in {common._key(v['path']) for v in pins},'Output aliases immutable proof')
    common._check(pins)
    return p,receipt,pin,pins


def execute(sw,p,failed,pin,pins):
    report=dict(scope=SCOPE,phase='reading',status='running',request=deepcopy(p),failed_receipt_pin=pin,
        module_pin=common._pin(__file__),source_sha256=p['expected_source_sha256'],
        model_modified=False,save_attempted=False,GTP_attempted=False,creation_attempted=False,
        arc_direction_interpreted=False,native_curve_frame_qualified=False,native_read_complete=False)
    persist=lambda:_write_receipt(p['receipt_path'],report)
    def check():
        actual=_process_identity(p['process_id']);owned=failed['ownership']
        require(actual.get('alive') is True and actual.get('process_id')==p['process_id']
                and actual.get('create_time')==owned['create_time']
                and common._key(actual.get('executable',''))==common._key(owned['executable']),
                'Owned PID lifetime changed')
        model=core._identity(sw,p['process_id'],p['expected_document_path'])
        require(parent._file_hash(p['expected_document_path'])==p['expected_source_sha256'],'Saved source changed')
        require(core.call(model,'GetSaveFlag') is True,'Expected existing unsaved first sketch')
        return model
    persist()
    try:
        common._check(pins);check();spec=failed['profile_specs'][0]
        before,model,refs=core._snapshot(sw,p['process_id'],p['expected_document_path'],spec)
        added=[row for row in before['features'] if row not in failed['before_cad']['features']]
        require(added==[dict(name='RootRestPlane1',type='RefPlane'),dict(name='RootRestProfile1',type='ProfileFeature')],
                'Only the existing first plane/sketch addition is permitted')
        parent.verify_cad(failed['before_cad'],before,added)
        plane=next(value for value in refs if str(value.Name)=='RootRestPlane1')
        report['native_plane']=core._plane(sw,plane);persist()
        feature=next(value for value in refs if str(value.Name)=='RootRestProfile1')
        sketch=core.call(feature,'GetSpecificFeature2')
        read_rows(sw,sketch,check=check,persist=persist,report=report)
        after,_,_=core._snapshot(sw,p['process_id'],p['expected_document_path'],spec)
        require(before==after,'Read-only diagnostic changed native CAD state')
        common._check(pins);check()
        report.update(status='read_only_raw_arc_observation',phase='finished',native_read_complete=True,
                      before_cad=before,after_cad=after)
    except Exception as exc:report.update(status='error',phase='finished',issue=_error(exc))
    persist();return report


def dispatch_request(request,*,validate_only=False):
    p,receipt,pin,pins=prepare(request)
    if validate_only:return dict(status='validated_offline',native_called=False,scope=SCOPE)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        return execute(sw,p,receipt,pin,pins)



