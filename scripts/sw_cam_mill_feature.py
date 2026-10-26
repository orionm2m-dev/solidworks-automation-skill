"""One guarded blind MILL feature from a saved, named two-dimensional sketch.
No sketch creation, AFR, operation generation, save, through/stock extension,
profile offset, taper or islands. Geometry/process qualification stays external.
"""
from __future__ import annotations
from copy import deepcopy
import json
import math
from pathlib import Path
from scripts.sw_cam import _error,_member,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_mill_stock import _snapshot as _stock_snapshot
from scripts.sw_cam_mill_qualification import _bootstrap,_vector,_int,_text
from scripts.sw_cam_turn_feature_attribute import _items
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_operation_guard import absolute_document_path

KINDS={'hole':(4,1),'open_pocket':(5,6)} # CWInteractiveFeatType / CWVolumeType


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Finite native numeric required')
    return float(value)


def _spec(value):
    keys={'kind','sketch_name','depth_native','expected_start_native','expected_bounds_native'}
    if not isinstance(value,dict) or value.get('kind') not in KINDS:raise ValueError('Exact bounded feature specification required')
    if value['kind']=='hole':keys.add('expected_tip_angle_native')
    if set(value)!=keys:raise ValueError('Hole requires exact expected tip angle; pocket must omit it')
    name=value['sketch_name']
    if not isinstance(name,str) or not name.strip() or len(name)>128 or any(x in name for x in '\x00\r\n'):raise ValueError('Exact saved sketch name required')
    depth=_number(value['depth_native'])
    bounds=_vector(value['expected_bounds_native'])
    if depth<=0 or any(x<=0 for x in bounds) or bounds[2]!=depth:raise ValueError('Positive depth/bounds with equal depth required')
    out=dict(kind=value['kind'],sketch_name=name,depth_native=depth,
                expected_start_native=_vector(value['expected_start_native']),expected_bounds_native=bounds)
    if value['kind']=='hole':out['expected_tip_angle_native']=_number(value['expected_tip_angle_native'])
    return out


def _raw_numbers(raw,max_length):
    if raw is None:return []
    if not isinstance(raw,(tuple,list)) or len(raw)>max_length:raise ValueError('Bounded numeric sketch array required')
    return [_number(x) for x in raw]


def _sketch(sw,name,read):
    model=read(sw,'ActiveDoc')
    if read(model,'GetActiveSketch2') is not None:raise ValueError('Exit any sketch edit before CAM feature creation')
    feature=read(model,'FeatureByName',name)
    if feature is None or read(feature,'GetTypeName2')!='ProfileFeature':raise ValueError('Exact existing 2D sketch required')
    if read(feature,'IsSuppressed') is not False:raise ValueError('Sketch must be unsuppressed')
    sketch=read(feature,'GetSpecificFeature2')
    if read(sketch,'Is3D') is not False:raise ValueError('Only 2D sketches supported')
    segments=read(sketch,'GetSketchSegments')
    if not isinstance(segments,(tuple,list)) or not 1<=len(segments)<=32:raise ValueError('Sketch segment bound is1..32')
    kinds=[]
    for segment in segments:
        kind=_int(read(segment,'GetType'))
        if kind not in (0,1) or read(segment,'ConstructionGeometry') is not False:raise ValueError('Only nonconstruction lines/arcs supported')
        kinds.append(kind)
    transform=_raw_numbers(read(read(sketch,'ModelToSketchTransform'),'ArrayData'),16)
    if len(transform)!=16:raise ValueError('Complete model-to-sketch transform required')
    return dict(name=name,segment_types=kinds,lines_raw_m=_raw_numbers(read(sketch,'GetLines2',0),4096),
                arcs_raw_m=_raw_numbers(read(sketch,'GetArcs2'),4096),model_to_sketch_transform=transform)


def _feature(raw,doc,typelib_path,read):
    base=_typed(raw,'ICWFeature',typelib_path);mill=_typed(raw,'ICWMillFeature',typelib_path)
    suppressed=read(base,'Suppressed')
    if type(suppressed) is not bool:raise ValueError('Strict suppressed flag required')
    volume_type=_int(read(mill,'VolumeType'))
    tip_angle=None
    if volume_type==1:
        # Installed TLB + local CHM: ICWMSHoleFeat, DISPID 8, DOUBLE retval.
        # Raw exact value only: docs do not define degrees/radians or flat-tip convention.
        hole=_typed(raw,'ICWMSHoleFeat',typelib_path)
        tip_angle=_number(read(hole,'GetTipAngle'))
    return dict(native_id=_object_id(doc,base,read),name=_text(read(base,'FeatureName')),
                axis_native=_vector(read(base,'Axis')),suppressed=suppressed,
                volume_type=volume_type,tip_angle_native=tip_angle,subtype=_int(read(mill,'SubType')),
                depth_native=_number(read(mill,'Depth')),bounds_native=_vector(read(mill,'GetBoundParams')),
                start_native=_vector(read(mill,'GetStartPosition')),taper_angle_native=_number(read(mill,'IGetTaperAngle')))


def _snapshot(sw,clsid,typelib_path,path,spec,*,check=lambda:None):
    base,native=_stock_snapshot(sw,clsid,typelib_path,path,check=check)
    def read(obj,name,*args):check();v=_member(obj,name,*args);check();return v
    sketch=_sketch(sw,spec['sketch_name'],read)
    rows=[];handles=[]
    for si,raw in enumerate(_items(read(native['machine'],'IGetEnumSetups'),typelib_path,read,limit=8)):
        setup=_typed(raw,'ICWBaseSetup',typelib_path)
        for value in _items(read(setup,'IGetEnumFeatures'),typelib_path,read,limit=64-len(rows)):
            row=_feature(value,native['doc'],typelib_path,read);row['setup_index']=si;rows.append(row)
        handles.append(raw)
    if len({x['native_id'] for x in rows})!=len(rows):raise ValueError('Duplicate native feature identity')
    final,_=_stock_snapshot(sw,clsid,typelib_path,path,check=check)
    if final!=base or _sketch(sw,spec['sketch_name'],read)!=sketch:raise ValueError('Native definitions/sketch changed while reading')
    base.update(features=rows,sketch=sketch,sketch_sha256=_digest(sketch));native['setup_handles']=handles
    return base,native


def _units(value,state,path):
    if not isinstance(value,dict) or set(value)!={'path','sha256'}:raise ValueError('Unit calibration evidence required')
    p=Path(value['path']) if isinstance(value.get('path'),str) else None
    if p is None or not p.is_absolute() or not p.is_file() or p.stat().st_size>1048576 or _file_hash(p)!=value['sha256']:raise ValueError('Unit evidence path/hash invalid')
    data=json.loads(p.read_text(encoding='utf-8-sig'))
    if (data.get('status')!='qualified' or data.get('interface')!='ICWSetup.CreateMillFeature2'
            or type(state.get('unit_record_raw')) is not str or data.get('unit_record_raw')!=state['unit_record_raw'] or not state['unit_record_raw'].strip()
            or Path(data.get('document_path','')).resolve()!=Path(path).resolve()
            or not isinstance(data.get('native_length_unit'),str) or not data['native_length_unit'].strip()
            or not isinstance(data.get('method'),str) or not data['method'].strip()):raise ValueError('Exact feature length-unit calibration required')
    pairs=data.get('observations')
    if not isinstance(pairs,list) or not 2<=len(pairs)<=32:raise ValueError('Two distinct unit observations required')
    for pair in pairs:
        if not isinstance(pair,dict) or set(pair)!={'native','interpreted_mm'}:raise ValueError('Explicit observed native/mm pairs required')
        _number(pair['native']);_number(pair['interpreted_mm'])
    if len({p['native'] for p in pairs})<2:raise ValueError('Distinct unit observations required')
    return dict(path=str(p),sha256=value['sha256'],scope='caller_calibration_not_independent_physical_qualification')


def _verify(before,after,setup_index,spec,new_id):
    oldids={x['native_id'] for x in before['features']};added=[x for x in after['features'] if x['native_id'] not in oldids]
    if len(added)!=1 or added[0]['native_id']!=new_id:raise ValueError('Exactly one new feature identity required')
    row=added[0];axis=before['feature_setups'][setup_index]['axis_native']
    expected_values=dict(setup_index=setup_index,axis_native=axis,suppressed=False,volume_type=KINDS[spec['kind']][1],subtype=0,
                         depth_native=spec['depth_native'],bounds_native=spec['expected_bounds_native'],start_native=spec['expected_start_native'],taper_angle_native=0.)
    expected_values['tip_angle_native']=spec.get('expected_tip_angle_native')
    for key,value in expected_values.items():
        if row.get(key)!=value:raise ValueError('Feature readback differs: '+key)
    expected=deepcopy(before);expected['document']['needs_save']=after['document']['needs_save']
    expected['feature_setups'][setup_index]['feature_count']+=1
    # Feature ordering is native; all previous identities and fields must survive.
    expected['features'].append(row)
    if sorted(expected['features'],key=lambda x:x['native_id'])!=sorted(after['features'],key=lambda x:x['native_id']):raise ValueError('Prior features changed')
    expected['features']=after['features']
    if expected!=after:raise ValueError('Unrequested state changes after feature creation')


def create_mill_feature(sw,clsid,typelib_path,*,expected_document_path,action,setup_index,expected_setup_native_id,
        feature_spec,expected_state_sha256=None,unit_evidence=None,receipt_path=None,qualification_only,message_policy):
    from scripts.sw_cam_events import CamMessageSession
    if qualification_only is not True or message_policy!='vendor_default' or action not in ('inspect','prepare','apply'):raise ValueError('Explicit bounded action/policy required')
    if not isinstance(expected_document_path,str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.lower()!='.sldprt':raise ValueError('Absolute saved part path required')
    if type(setup_index) is not int or not 0<=setup_index<8 or type(expected_setup_native_id) is not int or expected_setup_native_id<=0:raise ValueError('Exact setup reference required')
    spec=_spec(feature_spec);receipt=None
    if action=='apply':
        if not isinstance(expected_state_sha256,str) or len(expected_state_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_state_sha256):raise ValueError('Exact prepare SHA required')
        receipt=Path(receipt_path) if isinstance(receipt_path,str) else None
        if receipt is None or not receipt.is_absolute() or receipt.suffix.lower()!='.json' or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink():raise ValueError('Unique absolute receipt required')
    elif any(x is not None for x in (expected_state_sha256,unit_evidence,receipt_path)):raise ValueError('Read action rejects mutation inputs')
    report=dict(status='started',phase='initial',action=action,feature_spec=spec,mutation_attempted=False,native_call_returned=False,
                readback_verified=False,model_saved=False,sketch_edit_attempted=False,AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,
                geometry_match_independently_qualified=False,tip_angle_units_verified=False,
                tip_angle_basis='exact_raw_readback_not_flat_or_drill_angle_calibration',
                post_cleanup_CAM_getters=False,may_continue=False)
    if receipt:_write_receipt(receipt,report,create=True)
    session=None
    try:
        session=CamMessageSession(_bootstrap(sw,clsid,typelib_path,expected_document_path),typelib_path)
        def check():
            s=session.summary();report['messages']=s
            if (not s.get('subscribed') or not s.get('active') or s.get('event_count') or s.get('overflow') or s.get('callback_errors') or s.get('callback_error_count') or s.get('subscription_error') or s.get('disconnect_errors')):raise ValueError('Native message/event transport: stop')
        def read(obj,name,*args):check();v=_member(obj,name,*args);check();return v
        with session:
            check()
            before,native=_snapshot(sw,clsid,typelib_path,expected_document_path,spec,check=check)
            if setup_index>=len(before['feature_setups']) or before['feature_setups'][setup_index]['native_id']!=expected_setup_native_id:raise ValueError('Setup reference changed')
            eligible=(not before['document']['needs_save'] and not before['operation_counts'] and not before['extend_holes_to_stock'] and before['stock']['type_raw']==4 and len(before['features'])<64)
            report.update(before=before,state_sha256=_digest(before),apply_eligible=eligible)
            if action=='apply':
                if not eligible:raise ValueError('Saved MILL/STL stock, no operations and ExtendHolesToStock=false required')
                if report['state_sha256']!=expected_state_sha256:raise ValueError('Prepare fingerprint changed')
                if any(x['setup_index']==setup_index and x['volume_type']==KINDS[spec['kind']][1] and x['depth_native']==spec['depth_native'] and x['start_native']==spec['expected_start_native'] and x['bounds_native']==spec['expected_bounds_native'] for x in before['features']):raise ValueError('Equivalent feature already exists; no duplicate')
                evidence=_units(unit_evidence,before,expected_document_path);report['unit_evidence']=evidence
                check();current,native=_snapshot(sw,clsid,typelib_path,expected_document_path,spec,check=check)
                if current!=before or _units(unit_evidence,before,expected_document_path)!=evidence:raise ValueError('State/evidence changed before feature creation')
                setup=_typed(native['setup_handles'][setup_index],'ICWSetup',typelib_path)
                report.update(phase='native_write',mutation_attempted=True);_write_receipt(receipt,report)
                if document_snapshot(sw)!=before['document'] or _file_hash(expected_document_path)!=before['saved_file_sha256']:raise ValueError('Document/file changed before feature creation')
                check()
                added=_member(setup,'CreateMillFeature2',KINDS[spec['kind']][0],spec['sketch_name'],False,spec['depth_native'],False,False,False,False,0.,-1,False,0,0)
                report.update(native_call_returned=True,phase='native_return');_write_receipt(receipt,report);check()
                if added is None or not bool(added):raise ValueError('Native feature creation returned null')
                new_id=_object_id(native['doc'],added,read);report['new_feature_native_id']=new_id
                after,_=_snapshot(sw,clsid,typelib_path,expected_document_path,spec,check=check);_verify(before,after,setup_index,spec,new_id);report['after']=after
                final,_=_snapshot(sw,clsid,typelib_path,expected_document_path,spec,check=check);_verify(before,final,setup_index,spec,new_id);report['final_subscribed']=final;check()
            else:
                report.update(status='ok',phase='prepared' if action=='prepare' else 'inspected')
                final=before
                report['final_subscribed']=final
            check()
        s=session.summary();report['messages']=s
        if (not s.get('disconnected') or s.get('active') or s.get('event_count') or s.get('overflow') or s.get('callback_errors') or s.get('callback_error_count') or s.get('subscription_error') or s.get('disconnect_errors')):raise ValueError('Event cleanup unconfirmed')
        if document_snapshot(sw)!=final['document'] or _file_hash(expected_document_path)!=before['saved_file_sha256']:raise ValueError('Document/file changed during cleanup')
        report.update(status='review_required' if action=='apply' else 'ok',phase='finished',readback_verified=action=='apply',reason='FEATURE_ONLY_SAVE_REOPEN_AND_GEOMETRY_CHECK_REQUIRED')
    except Exception as exc:report.update(status='uncertain' if report['mutation_attempted'] else 'error',issue=_error(exc),failed_phase=report['phase'],phase='finished')
    finally:
        if session is not None:report['messages']=session.summary()
        if receipt:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status='uncertain',readback_verified=False,receipt_write_error=_error(exc))
    return report
