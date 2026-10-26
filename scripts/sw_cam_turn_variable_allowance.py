"""Read-only operation-owned turning variable allowance inspection.
No setter, tool getter, CL read, GTP, GOP, save or inferred unit conversion.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_operation_profile import _integer, _read_profile
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target, solidworks_operation_lock

_MODE_INTERFACES={1:'ICWTurnRoughOp',2:'ICWTurnFinishOp'}


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _allowances(raw):
    """Installed TLB: four VARIANT OUT parameters plus BOOL retval; no shape guessing."""
    if not isinstance(raw,(tuple,list)) or len(raw)!=5 or type(raw[4]) is not bool:
        raise ValueError('GetAllVariableAllowances requires four OUT values and Boolean return')
    names,x,z,count,success=raw
    if not success: raise ValueError('GetAllVariableAllowances native returned false; OUT values not interpreted')
    if type(count) is not int or not 0<=count<=512: raise ValueError('Native segment count must be integer 0..512')
    if any(not isinstance(a,(tuple,list)) or len(a)!=count for a in (names,x,z)):
        raise ValueError('Native names/X/Z arrays must all match exact segment count')
    if any(type(n) is not str or not n.strip() or len(n)>1000 or any(c in n for c in '\x00\r\n') for n in names):
        raise ValueError('Exact bounded nonempty native names required')
    if len(set(names))!=count: raise ValueError('Native segment names must be unique')
    for value in (*x,*z):
        if type(value) not in (int,float) or not math.isfinite(value): raise ValueError('Allowances must be finite native numbers, not Boolean')
    return {'native_success':True,'segment_count':count,
            'entries':[{'name':n,'radial_x_native':float(a),'axial_z_native':float(b)} for n,a,b in zip(names,x,z)],
            'native_variant_metadata_preserved':False,
            'converted_arrays_type_checked':True,
            'units_verified':False,'radius_vs_diameter_scaling_verified':False,
            'name_to_profile_segment_mapping':'unqualified_do_not_infer_from_array_order'}


def _snapshot(sw,clsid,typelib_path,config,read,check,identity,diagnostic=None):
    result={} if diagnostic is None else diagnostic
    result['capture_complete']=False
    check(); current_doc=identity()
    result.update(document=current_doc,saved_file_sha256=config['expected_source_sha256'])
    _,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
    if config['action']=='read':
        result['inventory']=_inventory(machine,typelib_path,read)
    setups=_items(read(machine,'IGetEnumOpSetups'),typelib_path,read)
    si=config['setup_index']; oi=config['operation_index']
    if si>=len(setups): raise ValueError('Selected setup absent')
    setup=_typed(setups[si],'ICWBaseOpSetup',typelib_path)
    operations=_items(read(setup,'IGetEnumOperations'),typelib_path,read)
    if oi>=len(operations): raise ValueError('Selected operation absent')
    raw=operations[oi]; operation=_typed(raw,'ICWOperation',typelib_path)
    turn=_typed(raw,'ICWTurnOperation',typelib_path)
    native_id=_object_id(doc,operation,read)
    if config['expected_operation_native_id'] is not None and native_id!=config['expected_operation_native_id']:
        raise ValueError('Exact native operation ID mismatch')
    kind=_integer(read(turn,'OpernType'))
    if kind!=config['expected_operation_type']: raise ValueError('Exact TURN operation type mismatch')
    suppressed=read(operation,'Suppressed')
    if type(suppressed) is not bool: raise ValueError('Operation suppression state is not Boolean')
    linked=_items(read(operation,'IGetAllFeatures'),typelib_path,read,limit=64)
    ids=[]; profiles=[]; budget=[0]
    result['selected_operation']={'setup_index':si,'operation_index':oi,'native_id':native_id,
        'turn_operation_type':kind,'suppressed':suppressed,'linked_feature_ids':ids}
    result['linked_features']=profiles
    for value in linked:
        fid=_object_id(doc,value,read)
        if fid in ids: raise ValueError('Duplicate linked feature ID')
        ids.append(fid)
    if config['action']=='identify':
        # 身份发现仅使用已有对象的正原生 ID；不进入轮廓、模式或余量链。
        check()
        if identity()!=current_doc: raise ValueError('Document or saved file changed during capture')
        result['capture_complete']=True
        return result
    if not ids or sorted(ids)!=config['expected_linked_feature_ids']:
        raise ValueError('Exact linked feature IDs changed')
    for fid,value in zip(ids,linked):
        profile={}
        profiles.append({'native_id':fid,'profile':profile})
        _read_profile(value,typelib_path,read,budget,profile,
                      collection_reader=lambda v,limit:_items(v,typelib_path,read,limit=limit))
    if any(not p['profile'].get('segment_count') or any(not seg.get('curve_parameters_available')
           for seg in p['profile'].get('segments',[])) for p in profiles):
        raise ValueError('Complete line/arc profile geometry is required for this qualification')
    mode=read(_typed(raw,_MODE_INTERFACES[kind],typelib_path),'GetAllowanceMethodVariable')
    if type(mode) is not int or not -(2**31)<=mode<2**31: raise ValueError('Variable mode must be exact native LONG')
    result.update(variable_mode_native=mode,variable_mode_meaning_qualified=False)
    allowance=_allowances(read(turn,'GetAllVariableAllowances'))
    result['allowances']=allowance
    check()
    if identity()!=current_doc: raise ValueError('Document or saved file changed during capture')
    result['capture_complete']=True
    return result


def inspect_turn_variable_allowance(sw,clsid,typelib_path,*,process_id,expected_document_path,
        setup_index,operation_index,expected_operation_type,expected_source_sha256,
        expected_operation_native_id=None,expected_linked_feature_ids=None,
        action='read',message_policy='vendor_default'):
    """Exact current saved part (may contain unchanged unsaved RAM data), one operation.

    Bootstrap obtains add-in/app only so events can be subscribed. All subsequent
    CAM getters, Count and Item calls, including both snapshots, run under active
    CamMessageSession. After disconnect only SW identity and saved file hash read.
    """
    report={'action':action,'inspection_scope':'identity_only' if action=='identify' else 'profile_and_variable_allowance',
            'status':'error','phase':'validation','may_continue':False,'mutation_attempted':False,
            'GOP_attempted':False,'GTP_attempted':False,'model_saved':False,'tool_readers_used':False,
            'CL_read_attempted':False,'units_verified':False,'radius_vs_diameter_scaling_verified':False,
            'persistence_verified':False,'name_to_geometry_mapping_verified':False,
            'full_cam_snapshot_scope':'before_event_disconnect','post_cleanup_cam_read_performed':False,
            'bootstrap_scope':'GetAddInObject/GetCWApp only; required before message subscription'}
    session=None
    try:
        for name,value,lo,hi in [('process_id',process_id,1,2**32-1),('setup_index',setup_index,0,511),
               ('operation_index',operation_index,0,511)]:
            if type(value) is not int or not lo<=value<=hi: raise ValueError('Invalid strict selector '+name)
        if action not in ('read','identify'): raise ValueError('Only read or identify action allowed')
        if expected_operation_native_id is not None and (type(expected_operation_native_id) is not int or not 1<=expected_operation_native_id<2**32):
            raise ValueError('Invalid strict selector expected_operation_native_id')
        if action=='read' and expected_operation_native_id is None:
            raise ValueError('Allowance read requires exact expected operation native ID')
        if action=='identify' and expected_linked_feature_ids is not None:
            raise ValueError('Identify discovers linked IDs; expected linked IDs belong to strict read only')
        if type(expected_operation_type) is not int or expected_operation_type not in _MODE_INTERFACES:
            raise ValueError('Only exact OD ROUGH type1 or FINISH type2 mode interfaces supported')
        if type(expected_document_path) is not str or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.casefold()!='.sldprt':
            raise ValueError('Exact absolute saved part path required')
        if type(expected_source_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_source_sha256):
            raise ValueError('Exact saved source SHA required')
        if action=='read' and (not isinstance(expected_linked_feature_ids,list) or not 1<=len(expected_linked_feature_ids)<=64
                or any(type(i) is not int or not 1<=i<2**32 for i in expected_linked_feature_ids)
                or len(set(expected_linked_feature_ids))!=len(expected_linked_feature_ids)):
            raise ValueError('Unique exact linked feature IDs required')
        if message_policy!='vendor_default': raise ValueError('Only vendor_default message policy allowed')
        config=dict(action=action,setup_index=setup_index,operation_index=operation_index,
             expected_operation_native_id=expected_operation_native_id,expected_operation_type=expected_operation_type,
             expected_linked_feature_ids=sorted(expected_linked_feature_ids) if expected_linked_feature_ids is not None else None,
             expected_source_sha256=expected_source_sha256)
        def identity():
            if _integer(_member(sw,'GetProcessID'))!=process_id: raise ValueError('Exact PID mismatch')
            state=document_snapshot(sw)
            if state is None or state['type']!=1 or not state['path']: raise ValueError('Saved part required')
            check_document_target(state['path'],state['title'],expected_path=expected_document_path,required=True)
            if _file_hash(state['path'])!=expected_source_sha256: raise ValueError('Saved source SHA changed')
            return state
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial_doc=identity(); report['unsaved_memory_present']=initial_doc['needs_save']
            addin=_member(sw,'GetAddInObject',clsid)
            if addin is None: raise ValueError('CAM add-in must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
            session=CamMessageSession(app,typelib_path)
            def check():
                state=session.summary(); report['messages']=state
                if not state.get('active') or not state.get('subscribed') or any(state.get(k) for k in
                      ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                    raise ValueError('CAM event transport requires review; no further CAM getters')
            def read(obj,name,*args):
                report['phase']=name; check(); value=_member(obj,name,*args); check(); return value
            with session:
                report['before']={}
                before=_snapshot(sw,clsid,typelib_path,config,read,check,identity,report['before'])
                report['state_sha256']=_digest(before)
                report['after']={}
                after=_snapshot(sw,clsid,typelib_path,config,read,check,identity,report['after'])
                if before!=after or before['document']!=initial_doc: raise ValueError('Operation/profile/allowance/document changed during read')
                check()
            summary=session.summary(); report['messages']=summary
            if summary.get('disconnected') is not True or summary.get('active') or any(summary.get(k) for k in
                  ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                raise ValueError('CAM event cleanup not cleanly confirmed')
            if identity()!=initial_doc: raise ValueError('SW document changed after event cleanup')
            report.update(status='ok',phase='finished',readback_verified=True,post_cleanup_document_file_verified=True,
                          interpretation=('Current document-scoped IDs only; no profiles, tools, mode or allowances read' if action=='identify'
                            else 'Raw operation-owned values only; no safe allowance write or units/mode mapping claimed'))
    except Exception as error:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(error),readback_verified=False)
    finally:
        if session is not None: report['messages']=session.summary()
    return report
