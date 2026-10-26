"""Bounded native MILL machine/setup qualification in separate saved copies.
No AFR/GOP/GTP, stock edit, save, material assignment or geometry edit. A successful
readback proves the requested native definition only, not a machining process.
"""
from __future__ import annotations
from array import array
from copy import deepcopy
import math
from pathlib import Path
from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_turn_feature_attribute import _items
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _int(v):
    if type(v) is not int:raise ValueError('Native integer required')
    return v


def _text(v):
    if not isinstance(v,str) or len(v)>2048 or '\x00' in v:raise ValueError('Bounded native BSTR required')
    return v


def _vector(v):
    if not isinstance(v,(tuple,list,array)) or len(v)!=3:raise ValueError('Three finite native vector values required')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in v):raise ValueError('Finite numeric vector required')
    return [float(x) for x in v]


def _direction(v):
    result=_vector(v)
    if sum(x!=0 for x in result)!=1 or any(x not in (-1.,0.,1.) for x in result):
        raise ValueError('Initial qualification accepts only six cardinal setup directions')
    return result


def _machine_info(machine,kind,typelib_path,read,*,result=None):
    # 逐字段保留已验证的标量；后续 getter 失败不丢失前面的只读证据。
    result={} if result is None else result
    result['machine_type']=kind
    if kind not in (1,3):return result
    obj=_typed(machine,'ICWMillMachine' if kind==1 else 'ICWTurnMachine',typelib_path)
    result['name']=_text(read(obj,'Name'))
    result['machine_id']=_text(read(obj,'MachId'))
    result['description']=_text(read(obj,'Description'))
    return result


def _bootstrap(sw,clsid,typelib_path,expected_path):
    before=document_snapshot(sw)
    if before is None or before.get('type')!=1 or not before.get('path'):raise ValueError('Active saved part required')
    check_document_target(before['path'],before['title'],expected_path=expected_path,required=True)
    addin=_member(sw,'GetAddInObject',clsid)
    if addin is None:raise ValueError('CAM add-in must already be loaded')
    # Only the connection-point host is acquired before subscription. All CAM
    # document, catalogue and inventory getters run inside the active subscription.
    return _typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)


def _snapshot(sw,clsid,typelib_path,expected_path,*,check=lambda:None,diagnostic=None,required_machine_type=None):
    diagnostic={} if diagnostic is None else diagnostic
    diagnostic.update(capture_complete=False,stage='document',catalogue_read_complete=False)
    def read(obj,name,*args):
        diagnostic['stage']=name
        check();value=_member(obj,name,*args);check();return value
    before=document_snapshot(sw)
    diagnostic['document']=deepcopy(before)
    if before is None or before.get('type')!=1 or not before.get('path'):
        raise ValueError('Active saved part required')
    check_document_target(before['path'],before['title'],expected_path=expected_path,required=True)
    file_before=_file_hash(expected_path)
    diagnostic['saved_file_sha256']=file_before
    addin=read(sw,'GetAddInObject',clsid)
    if addin is None:raise ValueError('CAM add-in must already be loaded')
    app=_typed(read(addin,'GetCWApp'),'ICWApp4',typelib_path)
    active=read(app,'IGetActiveDoc')
    doc=_typed(active,'ICWDoc3',typelib_path)
    if _int(read(doc,'GetDocType'))!=1:raise ValueError('Active CAM part required')
    part=_typed(active,'ICWPartDoc',typelib_path)
    machine=_typed(read(part,'IGetMachine'),'ICWMachine',typelib_path)
    kind=_int(read(machine,'MachType'))
    if required_machine_type is not None and kind!=required_machine_type:
        diagnostic['error_code']='MILL_REQUIRED_MACHINE_TYPE_MISMATCH'
        raise ValueError('Required machine type differs before subtype getters')
    if kind not in (0,1,3):raise ValueError('Only empty UNKNOWN/MILL/TURN copy can be inspected')
    diagnostic['current_machine']={}
    current=_machine_info(machine,kind,typelib_path,read,result=diagnostic['current_machine'])
    count=_int(read(app,'GetNumMachineOfType',1))
    diagnostic['catalogue_declared_count']=count
    candidates=_items(read(app,'GetMachines',1),typelib_path,read,limit=128)
    diagnostic['catalogue_collection_count']=len(candidates)
    if count!=len(candidates):
        diagnostic['error_code']='MILL_CATALOGUE_COUNT_MISMATCH'
        raise ValueError('MILL catalogue count differs from collection')
    catalogue=[];diagnostic['catalogue_entries']=[]
    for index,raw in enumerate(candidates):
        entry=dict(catalogue_index=index,read_complete=False,machine={})
        diagnostic['catalogue_entries'].append(entry)
        native=_typed(raw,'ICWMillMachine',typelib_path)
        entry['observed_machine_type']=_int(read(native,'MachType'))
        if entry['observed_machine_type']!=1:
            diagnostic['error_code']='MILL_CATALOGUE_NON_MILL_ENTRY'
            raise ValueError('Non-MILL candidate in native catalogue')
        info=_machine_info(native,1,typelib_path,read,result=entry['machine'])
        entry['read_complete']=True
        if not info['machine_id']:
            diagnostic['error_code']='MILL_CATALOGUE_EMPTY_MACHINE_ID'
            raise ValueError('Empty machine identity')
        catalogue.append(info)
    diagnostic['catalogue_read_complete']=True
    groups={}
    for index,info in enumerate(catalogue):groups.setdefault(info['machine_id'],[]).append(index)
    diagnostic['duplicate_machine_ids']=[dict(machine_id=key,catalogue_indices=indices)
        for key,indices in groups.items() if len(indices)>1]
    diagnostic['catalogue_identity_unique']=not diagnostic['duplicate_machine_ids']
    # MachId 的 BSTR 合同不保证全目录唯一；保留原顺序，不去重或按 ID 选首项。
    # 仅 machine prepare/apply 校验所选完整描述在目录中的唯一性。
    setups=_items(read(machine,'IGetEnumSetups'),typelib_path,read,limit=8)
    setup_rows=[]
    for raw in setups:
        setup=_typed(raw,'ICWBaseSetup',typelib_path)
        features=_items(read(setup,'IGetEnumFeatures'),typelib_path,read,limit=256)
        row=dict(native_id=_object_id(doc,setup,read),name=_text(read(setup,'SetupName')),feature_count=len(features))
        if kind==1:
            mill_setup=_typed(raw,'ICWSetup',typelib_path)
            row.update(axis_native=_vector(read(setup,'Axis')),origin_native=_vector(read(mill_setup,'GetReferencePosition')),
                       origin_type_raw=_int(read(mill_setup,'OriginType')))
        setup_rows.append(row)
    if len({x['native_id'] for x in setup_rows})!=len(setup_rows):raise ValueError('Duplicate native setup identity')
    op_setups=_items(read(machine,'IGetEnumOpSetups'),typelib_path,read,limit=8)
    operation_counts=[]
    for raw in op_setups:
        op_setup=_typed(raw,'ICWBaseOpSetup',typelib_path)
        operation_counts.append(len(_items(read(op_setup,'IGetEnumOperations'),typelib_path,read,limit=512)))
    wp_raw=read(machine,'IGetWorkpiece')
    material=None if wp_raw is None or not bool(wp_raw) else _text(read(_typed(wp_raw,'ICWWorkpiece',typelib_path),'Material'))
    extend=read(doc,'ExtendHolesToStock')
    if type(extend) is not bool:raise ValueError('Expected strict ExtendHolesToStock native bool')
    state=dict(document=before,saved_file_sha256=file_before,current_machine=current,mill_catalogue=catalogue,
               feature_setups=setup_rows,operation_counts=operation_counts,material_raw=material,
               extend_holes_to_stock=extend,unit_record_raw=None,
               unit_record_status='unavailable_native_getter_disabled_after_RPC_failure')
    if before!=document_snapshot(sw) or file_before!=_file_hash(expected_path):raise ValueError('Document/file changed during snapshot')
    check()
    diagnostic.update(capture_complete=True,stage='complete')
    return state,dict(app=app,doc=doc,machine=machine,candidates=candidates,setups=setups)


def _eligible(state,operation):
    if state['document']['needs_save']:return False
    if any(x['feature_count'] for x in state['feature_setups']) or any(state['operation_counts']):return False
    if operation=='machine':return not state['feature_setups'] and not state['operation_counts']
    return state['current_machine']['machine_type']==1 and len(state['feature_setups'])<8 and not state['operation_counts']


def _verify(before,after,operation,machine_index,direction,new_id):
    expected=deepcopy(before)
    expected['document']['needs_save']=after['document']['needs_save']
    if operation=='machine':
        expected['current_machine']=before['mill_catalogue'][machine_index]
        # Machine assignment may select a native default stock; report it, do not
        # pretend its geometry/material is qualified. Every other state is exact.
        expected['material_raw']=after['material_raw']
    else:
        if len(after['feature_setups'])!=len(before['feature_setups'])+1:raise ValueError('Expected exactly one new setup')
        new=after['feature_setups'][-1]
        if new['native_id']!=new_id or new['feature_count'] or new['axis_native']!=direction or new['origin_native']!=[0.,0.,0.]:
            raise ValueError('Setup axis/origin/identity/features readback differs')
        expected['feature_setups'].append(new)
        # InsertMillSetup can also create one corresponding empty operation setup.
        # This is a count-level delta, not a claim about operation-setup object IDs.
        counts=after['operation_counts']
        if (before['operation_counts']==[] and isinstance(counts,list) and
                len(counts)==1 and type(counts[0]) is int and counts[0]==0):
            expected['operation_counts']=[0]
    if expected!=after:raise ValueError('Unrequested state changes after native operation')


def configure_mill_qualification(sw,clsid,typelib_path,*,expected_document_path,action,operation,
        machine_index=None,direction=None,expected_state_sha256=None,receipt_path=None,
        qualification_only,message_policy):
    """Assign one catalogue MILL machine to empty copy or add one empty zero-origin setup.

    Direction is dimensionless cardinal API vector, not a claim about the physical
    feed sign; verify native setup axes against CAD before features. Native origin
    is fixed at zero, avoiding unqualified linear conversion. No stock qualification.
    """
    from scripts.sw_cam_events import CamMessageSession
    if qualification_only is not True or message_policy!='vendor_default':raise ValueError('Explicit qualification/vendor_default required')
    if action not in ('inspect','prepare','apply') or operation not in ('machine','setup'):raise ValueError('Unsupported action/operation')
    if not isinstance(expected_document_path,str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.lower()!='.sldprt':raise ValueError('Absolute saved SLDPRT path required')
    if operation=='machine':
        if direction is not None:raise ValueError('Machine action has no direction')
        if action!='inspect' and (type(machine_index) is not int or not 0<=machine_index<128):raise ValueError('Explicit native catalogue index required')
        if action=='inspect' and machine_index is not None:raise ValueError('Machine inspection has no selection')
    else:
        if machine_index is not None:raise ValueError('Setup action has no machine selection')
        direction=_direction(direction)
    receipt=None
    if action=='apply':
        if not isinstance(expected_state_sha256,str) or len(expected_state_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_state_sha256):raise ValueError('Exact prepare hash required')
        receipt=Path(receipt_path) if isinstance(receipt_path,str) else None
        if receipt is None or not receipt.is_absolute() or receipt.suffix.lower()!='.json' or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink():raise ValueError('Unique absolute JSON receipt required')
    elif expected_state_sha256 is not None or receipt_path is not None:raise ValueError('Read action rejects mutation evidence')
    report=dict(status='started',action=action,operation=operation,mutation_attempted=False,native_call_returned=False,
                readback_verified=False,model_saved=False,AFR_attempted=False,GOP_attempted=False,GTP_attempted=False,
                stock_qualified=False,stock_edit_attempted=False,geometry_independently_verified=False,
                post_cleanup_CAM_getters=False,may_continue=False,apply_eligible=False,phase='initial',snapshot_diagnostics=[])
    if receipt:_write_receipt(receipt,report,create=True)
    session=None
    try:
        session=CamMessageSession(_bootstrap(sw,clsid,typelib_path,expected_document_path),typelib_path)
        def check():
            state=session.summary();report['messages']=state
            if (not state.get('subscribed') or not state.get('active') or state.get('event_count') or state.get('overflow') or state.get('callback_errors')
                    or state.get('callback_error_count') or state.get('subscription_error') or state.get('disconnect_errors')):raise ValueError('Native message/event transport: stop')
        def read(obj,name,*args):
            check();value=_member(obj,name,*args);check();return value
        def capture(phase):
            diagnostic={'phase':phase,'capture_complete':False}
            report['snapshot_diagnostics'].append(diagnostic)
            return _snapshot(sw,clsid,typelib_path,expected_document_path,check=check,diagnostic=diagnostic)
        with session:
            check()
            initial,native=capture('initial')
            prepared_state=dict(snapshot=initial,operation=operation,machine_index=machine_index,direction=direction)
            report.update(before=initial,state_sha256=_digest(prepared_state),apply_eligible=_eligible(initial,operation))
            if operation=='machine' and machine_index is not None:
                if machine_index>=len(initial['mill_catalogue']):raise ValueError('Selected machine index absent')
                selected=initial['mill_catalogue'][machine_index]
                matches=[i for i,value in enumerate(initial['mill_catalogue']) if value==selected]
                report.update(selected_machine=selected,selected_machine_catalogue_index=machine_index,
                    selected_machine_matching_catalogue_indices=matches,selected_machine_unique=len(matches)==1)
                if len(matches)!=1:
                    report['error_code']='MILL_SELECTED_MACHINE_DESCRIPTOR_AMBIGUOUS'
                    raise ValueError('Selected full machine descriptor is ambiguous')
            if action=='apply':
                if not report['apply_eligible']:raise ValueError('Only clean empty qualification definitions may be changed')
                if report['state_sha256']!=expected_state_sha256:raise ValueError('Prepare fingerprint changed')
                if operation=='machine' and initial['current_machine']==initial['mill_catalogue'][machine_index]:raise ValueError('Requested machine already assigned; no write')
                if operation=='setup' and any(x.get('axis_native')==direction and x.get('origin_native')==[0.,0.,0.] for x in initial['feature_setups']):raise ValueError('Identical setup already exists; no duplicate')
                check()
                current,native=capture('before_mutation')
                if current!=initial:raise ValueError('State changed before mutation')
                report.update(phase='native_write',mutation_attempted=True)
                _write_receipt(receipt,report)
                if document_snapshot(sw)!=initial['document'] or _file_hash(expected_document_path)!=initial['saved_file_sha256']:raise ValueError('Document/file changed before native write')
                check()
                if operation=='machine':
                    _member(native['doc'],'SetMachine2',native['candidates'][machine_index]);new_id=None
                else:
                    mill=_typed(native['machine'],'ICWMillMachine',typelib_path)
                    added=_member(mill,'InsertMillSetup',array('d',direction),array('d',[0.,0.,0.]),False,native['setups'][-1] if native['setups'] else None)
                    new_id=None
                report.update(native_call_returned=True,phase='native_return');_write_receipt(receipt,report);check()
                if operation=='setup':
                    if added is None or not bool(added):raise ValueError('Native setup insertion returned null')
                    new_id=_object_id(native['doc'],added,read)
                    report['new_setup_native_id']=new_id
                after,_=capture('after_mutation')
                report.update(after=after,phase='after_mutation_validation')
                _write_receipt(receipt,report)
                _verify(initial,after,operation,machine_index,direction,new_id)
                final,_=capture('final_subscribed')
                report['final_subscribed']=final
                _verify(initial,final,operation,machine_index,direction,new_id);check()
            else:
                report.update(status='ok',phase='prepared' if action=='prepare' else 'inspected')
                final=initial
                report['final_subscribed']=final
            check()
        state=session.summary();report['messages']=state
        if (not state.get('disconnected') or state.get('active') or state.get('event_count') or state.get('overflow') or state.get('callback_errors')
                or state.get('callback_error_count') or state.get('subscription_error') or state.get('disconnect_errors')):raise ValueError('Event cleanup unconfirmed')
        if document_snapshot(sw)!=final['document'] or _file_hash(expected_document_path)!=initial['saved_file_sha256']:raise ValueError('Document/file changed during cleanup')
        report.update(status='review_required' if action=='apply' else 'ok',phase='finished',readback_verified=action=='apply',
                      reason='NATIVE_DEFINITION_ONLY_SAVE_REOPEN_STOCK_DIRECTION_AND_PROCESS_QUALIFICATION_REQUIRED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',issue=_error(exc),failed_phase=report['phase'],phase='finished',apply_eligible=False)
        if report['snapshot_diagnostics']:
            code=report['snapshot_diagnostics'][-1].get('error_code')
            if code:report['error_code']=code
    finally:
        if session is not None:report['messages']=session.summary()
        if receipt:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status='uncertain',readback_verified=False,receipt_write_error=_error(exc))
    return report
