"""One-operation positive variable-allowance experiment in a saved CAM copy.
Raw names/mode/units remain unqualified; no GOP, GTP, save, post or rollback.
"""
from __future__ import annotations
from copy import deepcopy
import math
from pathlib import Path
import re
from scripts.sw_cam import _member,_error,document_snapshot
from scripts.sw_cam_generation import _typed,_write_receipt
from scripts.sw_cam_events import CamMessageSession
from scripts.sw_cam_operation_profile import _integer
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_feature_attribute import _context,_items
from scripts.sw_cam_turn_variable_allowance import _snapshot,_digest,_allowances,_MODE_INTERFACES
from scripts.sw_operation_guard import absolute_document_path,check_document_target,solidworks_operation_lock


def _changes(values):
    keys={'name','expected_radial_x_native','expected_axial_z_native','radial_x_native','axial_z_native'}
    if not isinstance(values,list) or not 1<=len(values)<=2: raise ValueError('Exactly one or two explicit allowance-name changes required')
    result=[];names=set()
    for row in values:
        if not isinstance(row,dict) or set(row)!=keys: raise ValueError('Exact change fields required')
        name=row['name']
        if type(name) is not str or not name.strip() or len(name)>1000 or any(c in name for c in '\x00\r\n') or name in names:
            raise ValueError('Unique exact bounded BSTR names required; no index coercion')
        names.add(name); item={'name':name}
        for key in keys-{'name'}:
            v=row[key]
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:
                raise ValueError('Qualification amounts must be finite raw numbers 0..1, not inferred mm')
            item[key]=float(v)
        old=(item['expected_radial_x_native'],item['expected_axial_z_native'])
        new=(item['radial_x_native'],item['axial_z_native'])
        if any(b<a for a,b in zip(old,new)) or new==old: raise ValueError('Each explicit change must only increase a nonnegative allowance')
        result.append(item)
    return result


def _validate_plan(before,changes,expected_mode):
    if before['document']['needs_save']: raise ValueError('Qualification copy must begin clean and saved')
    if before['variable_mode_native']!=expected_mode: raise ValueError('Expected raw mode changed')
    selected=before['selected_operation']
    if selected['suppressed']: raise ValueError('Selected operation is suppressed')
    row=next((x for x in before['inventory']['operations'] if x['setup_index']==selected['setup_index'] and x['operation_index']==selected['operation_index']),None)
    if row is None or row['toolpath_generated'] or row['toolpath_record_counts']:
        raise ValueError('Selected operation must have no generated toolpath before qualification')
    actual={v['name']:v for v in before['allowances']['entries']}
    for change in changes:
        name=change['name']
        if name not in actual: raise ValueError('Requested exact native name absent')
        if any(actual[name][field]!=change['expected_'+field] for field in ('radial_x_native','axial_z_native')):
            raise ValueError('Expected per-name raw allowance changed')


def _verify(before,after,mode,completed):
    expected=deepcopy(before)
    expected['variable_mode_native']=mode
    for item in expected['allowances']['entries']:
        if item['name'] in completed:
            item.update(completed[item['name']])
    expected['document']['needs_save']=after['document']['needs_save']
    if type(after['document']['needs_save']) is not bool: raise ValueError('Document dirty flag not Boolean')
    if expected!=after: raise ValueError('Unexpected operation/profile/inventory/allowance change')


def _locate(sw,clsid,tlb,config,read):
    _,doc,_,machine,_=_context(sw,clsid,tlb,read)
    setups=_items(read(machine,'IGetEnumOpSetups'),tlb,read)
    si=config['setup_index'];oi=config['operation_index']
    if si>=len(setups): raise ValueError('Exact operation setup absent')
    ops=_items(read(_typed(setups[si],'ICWBaseOpSetup',tlb),'IGetEnumOperations'),tlb,read)
    if oi>=len(ops): raise ValueError('Exact operation absent')
    raw=ops[oi]; op=_typed(raw,'ICWOperation',tlb);turn=_typed(raw,'ICWTurnOperation',tlb)
    if _object_id(doc,op,read)!=config['expected_operation_native_id'] or _integer(read(turn,'OpernType'))!=config['expected_operation_type']:
        raise ValueError('Exact operation ID/type changed before setter')
    ids=[_object_id(doc,f,read) for f in _items(read(op,'IGetAllFeatures'),tlb,read,limit=64)]
    if len(set(ids))!=len(ids) or sorted(ids)!=config['expected_linked_feature_ids']:
        raise ValueError('Exact operation feature links changed before setter')
    return turn,_typed(raw,_MODE_INTERFACES[config['expected_operation_type']],tlb)


def qualify_turn_variable_allowance(sw,clsid,typelib_path,*,process_id,expected_document_path,
        setup_index,operation_index,expected_operation_native_id,expected_operation_type,
        expected_linked_feature_ids,expected_source_sha256,baseline_checkpoint_path,
        action,changes,expected_mode_native,candidate_mode_native,qualification_only,
        acknowledge_unqualified_mapping_mode_units,message_policy='vendor_default',
        expected_state_sha256=None,receipt_path=None):
    report={'status':'error','phase':'validation','action':action,'may_continue':False,
       'mutation_attempted':False,'setters_attempted':0,'setters_returned':0,'completed_changes':[],
       'GOP_attempted':False,'GTP_attempted':False,'model_saved':False,'post_attempted':False,
       'automatic_rollback':False,'retry_attempted':False,'productionNC':False,
       'units_verified':False,'radius_vs_diameter_scaling_verified':False,'mode_meaning_verified':False,
       'name_to_geometry_mapping_verified':False,'persistence_verified':False,'WIP_validation_required':True,
       'other_operations_scope':'Inventory/types/generated flags/counts only, not all machining parameters',
       'product_geometry_scope':'Linked CAM profiles and unchanged saved CAD bytes; not complete RAM BRep proof',
       'post_cleanup_cam_read_performed':False,'full_cam_snapshot_scope':'before_event_disconnect'}
    session=None;receipt=None;created=False
    try:
        for name,v,lo,hi in [('process_id',process_id,1,2**32-1),('setup_index',setup_index,0,511),
                ('operation_index',operation_index,0,511),('expected_operation_native_id',expected_operation_native_id,1,2**32-1)]:
            if type(v) is not int or not lo<=v<=hi: raise ValueError('Invalid strict selector '+name)
        if type(expected_operation_type) is not int or expected_operation_type not in _MODE_INTERFACES: raise ValueError('Only OD ROUGH1/FINISH2 allowed')
        if (not isinstance(expected_linked_feature_ids,list) or not 1<=len(expected_linked_feature_ids)<=64
                or any(type(v) is not int or not 0<v<2**32 for v in expected_linked_feature_ids)
                or len(set(expected_linked_feature_ids))!=len(expected_linked_feature_ids)):
            raise ValueError('Unique exact linked native feature IDs required')
        if type(expected_source_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_source_sha256): raise ValueError('Exact source SHA required')
        for value in (expected_document_path,baseline_checkpoint_path):
            if type(value) is not str or not absolute_document_path(value) or Path(value).suffix.casefold()!='.sldprt' or not Path(value).is_file():
                raise ValueError('Existing absolute saved part paths required')
        if Path(expected_document_path).samefile(baseline_checkpoint_path): raise ValueError('Qualification must use a distinct copied CAM file')
        if action not in ('prepare','apply') or qualification_only is not True or acknowledge_unqualified_mapping_mode_units is not True or message_policy!='vendor_default':
            raise ValueError('Explicit qualification and unqualified mapping/mode/units acknowledgement required')
        if type(expected_mode_native) is not int or expected_mode_native not in (0,1) or type(candidate_mode_native) is not int or candidate_mode_native!=1:
            raise ValueError('Only explicit raw mode0/1 -> candidate1 experiment allowed; not an enum mapping claim')
        changes=_changes(changes)
        if action=='prepare' and (expected_state_sha256 is not None or receipt_path is not None): raise ValueError('Prepare cannot write a receipt')
        if action=='apply':
            if type(expected_state_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}',expected_state_sha256): raise ValueError('Prepared state SHA required')
            receipt=Path(receipt_path) if type(receipt_path) is str else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.casefold()!='.json' or not receipt.parent.is_dir(): raise ValueError('New absolute JSON receipt required')
            _write_receipt(receipt,report,create=True);created=True
        config=dict(action='read',process_id=process_id,expected_document_path=expected_document_path,
           setup_index=setup_index,operation_index=operation_index,expected_operation_native_id=expected_operation_native_id,
           expected_operation_type=expected_operation_type,expected_linked_feature_ids=sorted(expected_linked_feature_ids),
           expected_source_sha256=expected_source_sha256,baseline_checkpoint_path=baseline_checkpoint_path)
        report['request']=dict(config,changes=changes,expected_mode_native=expected_mode_native,candidate_mode_native=candidate_mode_native,
             qualification_only=True,acknowledge_unqualified_mapping_mode_units=True)
        def identity():
            if _integer(_member(sw,'GetProcessID'))!=process_id: raise ValueError('Exact PID mismatch')
            doc=document_snapshot(sw)
            if doc is None or doc['type']!=1 or not doc['path']: raise ValueError('Saved active part required')
            check_document_target(doc['path'],doc['title'],expected_path=expected_document_path,required=True)
            if _file_hash(doc['path'])!=expected_source_sha256 or _file_hash(baseline_checkpoint_path)!=expected_source_sha256:
                raise ValueError('Current copy or baseline checkpoint SHA changed')
            return doc
        with solidworks_operation_lock(timeout_seconds=1,process_id=process_id):
            initial_doc=identity()
            if initial_doc['needs_save']: raise ValueError('Clean saved qualification copy required')
            addin=_member(sw,'GetAddInObject',clsid)
            if addin is None: raise ValueError('CAM must already be loaded')
            app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
            session=CamMessageSession(app,typelib_path)
            def check():
                summary=session.summary();report['messages']=summary
                if not summary.get('active') or not summary.get('subscribed') or any(summary.get(k) for k in
                      ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                    raise ValueError('CAM event transport requires review; stop without retry')
            def read(obj,name,*args):
                report['phase']=name;check();value=_member(obj,name,*args);check();return value
            def capture(key):
                report[key]={}
                return _snapshot(sw,clsid,typelib_path,config,read,check,identity,report[key])
            with session:
                before=capture('before');_validate_plan(before,changes,expected_mode_native)
                state=_digest({'snapshot':before,'request':report['request']});report['state_sha256']=state
                if action=='apply' and state!=expected_state_sha256: raise ValueError('Prepared exact state/plan changed')
                fresh=capture('pre_apply' if action=='apply' else 'after')
                if fresh!=before: raise ValueError('State changed during preparation')
                report['apply_eligible']=True
                if action=='apply':
                    mode=expected_mode_native; completed={}
                    def scalar_check():
                        turn,typed_mode=_locate(sw,clsid,typelib_path,config,read)
                        value=read(typed_mode,'GetAllowanceMethodVariable')
                        if type(value) is not int or value!=mode: raise ValueError('Mode readback changed unexpectedly')
                        actual=_allowances(read(turn,'GetAllVariableAllowances'))
                        desired=deepcopy(before['allowances'])
                        for row in desired['entries']:
                            if row['name'] in completed: row.update(completed[row['name']])
                        if actual!=desired: raise ValueError('Per-name or untouched allowance readback mismatch')
                        return turn,typed_mode
                    def call_setter(obj,name,args):
                        check();identity();check()
                        report.update(phase='before_'+name,setter_intent={'method':name,'arguments':list(args)},mutation_attempted=True)
                        _write_receipt(receipt,report)
                        check();identity();check()
                        report['setters_attempted']+=1
                        value=_member(obj,name,*args)
                        report['setters_returned']+=1
                        report['phase']=name+'_returned'
                        _write_receipt(receipt,report)
                        check();identity();check()
                        return value
                    if mode!=candidate_mode_native:
                        turn,typed_mode=scalar_check()
                        # Setter is HRESULT/VOID. No Boolean retval is required or invented.
                        call_setter(typed_mode,'SetAllowanceMethodVariable',(candidate_mode_native,))
                        mode=candidate_mode_native
                        scalar_check()
                        report['mode_scalar_readback_verified']=True
                    for change in changes:
                        turn,_=scalar_check()
                        value=call_setter(turn,'SetVariableAllowance',(change['name'],change['radial_x_native'],change['axial_z_native']))
                        if type(value) is not bool or value is not True: raise ValueError('SetVariableAllowance did not return native True')
                        completed[change['name']]={f:change[f] for f in ('radial_x_native','axial_z_native')}
                        scalar_check()
                        report['completed_changes'].append(deepcopy(change))
                        _write_receipt(receipt,report)
                    after=capture('after');_verify(before,after,mode,completed)
                    report['scalar_readback_verified']=True
                    report['linked_profile_unchanged']=before['linked_features']==after['linked_features']
                    report['inventory_unchanged']=before['inventory']==after['inventory']
                check()
                post_doc=identity()
            summary=session.summary();report['messages']=summary
            if summary.get('disconnected') is not True or summary.get('active') or any(summary.get(k) for k in
                  ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                raise ValueError('Event disconnect not cleanly confirmed')
            if identity()!=post_doc: raise ValueError('SW document changed after event cleanup')
            report.update(status='review_required' if action=='apply' else 'ok',phase='finished',
                 post_cleanup_document_file_verified=True,
                 reason='SCALAR_QUALIFICATION_ONLY_REQUIRES_WIP_MAPPING_UNITS_AND_CONTAINMENT' if action=='apply' else None)
    except Exception as error:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],
                      phase='finished',issue=_error(error),scalar_readback_verified=False,apply_eligible=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as error:report.update(status='uncertain',receipt_finalize_error=_error(error),scalar_readback_verified=False)
    return report
