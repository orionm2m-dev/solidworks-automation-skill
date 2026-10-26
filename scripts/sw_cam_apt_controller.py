"""隔离的已保存 TURN 副本中进行 APT 选择资格验证。
只调用一次 SetController2，不后处理、保存、生成、发送或重试。
目录参数属于明确的资格实验；同名读回不能证明实际载入文件路径。
"""
from __future__ import annotations
from copy import deepcopy
import math
import os
from pathlib import Path
import re
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread_postprocess import _controller, _digest
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_feature_attribute import _context, _items, _inventory
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _sha(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}',value) is None:
        raise ValueError('Exact lower-case SHA256 required')
    return value


def _name(value):
    if type(value) is not str or not value.strip() or len(value)>256 or any(c in value for c in '\x00\r\n'):
        raise ValueError('Exact bounded native controller name required')
    return value


def _catalogue(raw):
    if raw is None:return []
    if not isinstance(raw,(tuple,list)) or len(raw)>256:
        raise ValueError('APT native catalogue must be a bounded array; no variant-shape guessing')
    names=[_name(x) for x in raw]
    if len(set(names))!=len(names):raise ValueError('Duplicate APT catalogue names')
    return names


def _parameters(raw):
    if not isinstance(raw,(tuple,list)) or len(raw)!=3 or type(raw[2]) is not bool:
        raise ValueError('Controller parameters require two VARIANT outputs and BOOL status')
    keys,values,success=raw
    if not success:
        return dict(success=False,entries=[],reason='native_parameter_lookup_unavailable')
    if (not isinstance(keys,(tuple,list)) or not isinstance(values,(tuple,list))
            or len(keys)!=len(values) or len(keys)>256):
        raise ValueError('Controller parameter arrays differ or exceed bounds')
    rows=[]
    for key,value in zip(keys,values):
        _name(key)
        if value is not None and type(value) not in (str,bool,int,float):
            raise ValueError('Unsupported nested controller parameter shape')
        if type(value) is str and (len(value)>4096 or '\x00' in value):raise ValueError('Controller parameter string too large')
        if type(value) is float and not math.isfinite(value):raise ValueError('Nonfinite controller parameter')
        rows.append(dict(key=key,value=value,python_type=type(value).__name__))
    return dict(success=True,entries=rows,actual_loaded_path_verified=False)


def _candidate(path_value,digest,name,path_argument_kind='directory_with_trailing_separator'):
    path=Path(path_value) if type(path_value) is str else None
    if (path is None or not path.is_absolute() or path.suffix.casefold()!='.aptctl'
            or not path.is_file() or path.is_symlink() or not 0<path.stat().st_size<=4*1024*1024):
        raise ValueError('Existing bounded absolute .aptctl candidate required')
    _sha(digest)
    if _file_hash(path)!=digest:raise ValueError('APT candidate file SHA differs')
    if name.casefold() not in {path.stem.casefold(),path.name.casefold(),str(path).casefold()}:
        raise ValueError('Exact native name must identify the supplied APT file, not a guessed mapping')
    return dict(path=str(path),sha256=digest,bytes=path.stat().st_size,
        native_path_argument=(str(path) if path_argument_kind=='exact_aptctl_file_path' else str(path.parent)+os.sep),
        path_argument_kind=path_argument_kind,
        actual_loaded_file_verified=False)


def _installed_candidates(sw,read,name_mode='stem'):
    """仅枚举当前 SW 年份的已安装 Turn APT 文件；不冒充原生目录结果。"""
    revision=read(sw,'RevisionNumber')
    if type(revision) is not str or re.fullmatch(r"[0-9]+(?:\.[0-9]+)+",revision) is None:
        raise ValueError('Exact SOLIDWORKS revision required for installed post directory')
    year=int(revision.split('.')[0])+1992
    base=Path(os.environ.get('PROGRAMDATA',''))
    if not 2000<=year<=2100 or not base.is_absolute():raise ValueError('Absolute installed ProgramData/year required')
    root=base/'SOLIDWORKS'/f'SOLIDWORKS CAM {year}'/'Posts'/'Turn'
    if not root.is_dir() or root.is_symlink():raise ValueError('Installed current-year Turn post directory not found')
    rows=[]
    for count,path in enumerate(root.iterdir()):
        if count>=512:raise ValueError('Installed post directory entry bound exceeded')
        if path.suffix.casefold()!='.aptctl':continue
        if len(rows)>=64 or not path.is_file() or path.is_symlink() or path.resolve().parent!=root.resolve():raise ValueError('Bounded direct installed APT files required')
        size=path.stat().st_size
        if not 0<size<=4*1024*1024:raise ValueError('Installed APT file size outside bound')
        rows.append(dict(name=_name(path.name if name_mode=='filename_with_extension' else path.stem),path=str(path),sha256=_file_hash(path),bytes=size))
    rows.sort(key=lambda x:x['name'].casefold())
    if not rows or len({r['name'].casefold() for r in rows})!=len(rows):raise ValueError('Missing or ambiguous installed APT names')
    return dict(directory=str(root),solidworks_year=year,source='installed_files_not_native_catalogue',
        name_mode=name_mode,name_source='derived_from_exact_installed_file_not_native_catalogue',entries=rows)


def configure_apt_controller(sw,clsid,typelib_path,*,process_id,expected_document_path,
        expected_source_sha256,action,qualification_only,acknowledge_disposable_copy,
        message_policy='vendor_default',controller_name=None,controller_file_path=None,
        controller_file_sha256=None,acknowledge_path_argument_qualification=False,
        expected_state_sha256=None,receipt_path=None,catalogue_source='native',
        path_argument_kind='directory_with_trailing_separator',name_mode='stem'):
    """读取实际 APT 目录，或在精确隔离副本中选择一个已观察到的条目。"""
    from scripts.sw_cam_events import CamMessageSession
    report=dict(status='error',phase='preflight',action=action,may_continue=False,
        mutation_attempted=False,native_call_returned=False,readback_verified=False,
        productionNC=False,postprocess_attempted=False,cnc_send_attempted=False,
        model_saved=False,GOP_attempted=False,GTP_attempted=False,
        actual_loaded_file_verified=False,path_argument_semantics_qualified=False,
        post_cleanup_CAM_getters=False,controller_scope='document_machine_APT_only',
        catalogue_source=catalogue_source,catalogue_names_native_verified=False,
        path_argument_kind=path_argument_kind,name_mode=name_mode,false_return_diagnostic_attempted=False,
        false_return_diagnostic_complete=False,controller_assignment_verified=False)
    receipt=session=None;created=False
    try:
        if type(process_id) is not int or not 0<process_id<2**32:raise ValueError('Explicit strict PID required')
        if (type(expected_document_path) is not str or not absolute_document_path(expected_document_path)
                or Path(expected_document_path).suffix.casefold()!='.sldprt'):raise ValueError('Exact absolute saved part required')
        _sha(expected_source_sha256)
        if (qualification_only is not True or acknowledge_disposable_copy is not True
                or message_policy!='vendor_default' or action not in ('inspect','prepare','apply')):
            raise ValueError('Explicit disposable-copy qualification action/policy required')
        if catalogue_source not in ('native','installed_files_qualification'):raise ValueError('Explicit supported catalogue source required')
        if name_mode not in ('stem','filename_with_extension'):
            raise ValueError('Explicit supported controller name mode required')
        if name_mode=='filename_with_extension' and catalogue_source!='installed_files_qualification':
            raise ValueError('Filename name experiment requires the observed installed file source')
        if path_argument_kind not in ('directory_with_trailing_separator','exact_aptctl_file_path'):
            raise ValueError('Explicit supported path argument kind required')
        if path_argument_kind=='exact_aptctl_file_path' and catalogue_source!='installed_files_qualification':
            raise ValueError('Exact file path experiment requires the observed installed file source')
        if type(acknowledge_path_argument_qualification) is not bool:raise ValueError('Strict path acknowledgement required')
        if controller_name is not None:_name(controller_name)
        if action=='inspect':
            if (any(x is not None for x in (controller_file_path,controller_file_sha256,expected_state_sha256,receipt_path))
                    or acknowledge_path_argument_qualification or path_argument_kind!='directory_with_trailing_separator'):
                raise ValueError('Inspect rejects file/assignment/receipt inputs')
            candidate=None
        else:
            _name(controller_name)
            if acknowledge_path_argument_qualification is not True:raise ValueError('Path argument requires explicit qualification acknowledgement')
            candidate=_candidate(controller_file_path,controller_file_sha256,controller_name,path_argument_kind)
            if action=='prepare' and (expected_state_sha256 is not None or receipt_path is not None):
                raise ValueError('Prepare rejects mutation receipt/hash')
        if action=='apply':
            _sha(expected_state_sha256)
            receipt=Path(receipt_path) if type(receipt_path) is str else None
            if receipt is None or not receipt.is_absolute() or receipt.suffix.lower()!='.json' or not receipt.parent.is_dir():raise ValueError('New absolute JSON receipt required')
            _write_receipt(receipt,report,create=True);created=True
        def identity(clean=False):
            pid=_member(sw,'GetProcessID')
            if type(pid) is not int or pid!=process_id:raise ValueError('Exact PID mismatch')
            state=document_snapshot(sw)
            if state is None or state['type']!=1 or (clean and state['needs_save']):raise ValueError('Exact clean saved part required')
            check_document_target(state['path'],state['title'],expected_path=expected_document_path,required=True)
            if _file_hash(state['path'])!=expected_source_sha256:raise ValueError('Saved file SHA changed')
            return state
        initial=identity(clean=True)
        addin=_member(sw,'GetAddInObject',clsid)
        if addin is None:raise ValueError('CAM must already be loaded')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
        session=CamMessageSession(app,typelib_path)
        def check():
            state=session.summary();report['messages']=state
            if not state.get('active') or not state.get('subscribed') or any(state.get(k) for k in
                    ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
                raise ValueError('CAM message/event transport requires review')
        def read(obj,name,*args):
            report['phase']=name;check();value=_member(obj,name,*args);check();return value
        def capture(diagnostic=None):
            if diagnostic is not None:diagnostic['capture_complete']=False
            check();before_doc=identity()
            if diagnostic is not None:diagnostic['document']=before_doc
            _,doc,_,machine,_=_context(sw,clsid,typelib_path,read)
            if read(machine,'MachType')!=3:raise ValueError('APT qualification limited to a TURN copy')
            inventory=_inventory(machine,typelib_path,read)
            if diagnostic is not None:diagnostic['inventory']=inventory
            identities=[]
            if diagnostic is not None:diagnostic['operation_identities']=identities
            for si,setup in enumerate(_items(read(machine,'IGetEnumOpSetups'),typelib_path,read,limit=512)):
                base=_typed(setup,'ICWBaseOpSetup',typelib_path)
                for oi,raw in enumerate(_items(read(base,'IGetEnumOperations'),typelib_path,read,limit=512-len(identities))):
                    identities.append(dict(setup_index=si,operation_index=oi,native_id=_object_id(doc,_typed(raw,'ICWOperation',typelib_path),read)))
            if len({row['native_id'] for row in identities})!=len(identities):raise ValueError('Duplicate operation IDs')
            target=_typed(machine,'ICWMachine5',typelib_path)
            installed=None
            if catalogue_source=='native':
                names=_catalogue(read(target,'GetPostProcessorList',True))
                report['catalogue_names_native_verified']=True
            else:
                installed=_installed_candidates(sw,read,name_mode)
                names=[row['name'] for row in installed['entries']]
            current=_controller(read(target,'GetController2'))
            if diagnostic is not None:diagnostic['current_controller']=current
            params=None
            if controller_name is not None:
                if controller_name not in names:raise ValueError('Selected name is absent from the explicit candidate source')
                if catalogue_source=='native':
                    params=_parameters(read(target,'GetControllerParameters',True,controller_name))
                else:
                    params=dict(success=None,entries=[],reason='not_queried_in_installed_file_qualification')
                    selected=next(row for row in installed['entries'] if row['name']==controller_name)
                    if candidate and (Path(candidate['path']).resolve()!=Path(selected['path']).resolve() or candidate['sha256']!=selected['sha256']):
                        raise ValueError('Candidate is not the exact installed current-year APT file')
            if before_doc!=identity():raise ValueError('Document changed during capture')
            file=_candidate(controller_file_path,controller_file_sha256,controller_name,path_argument_kind) if candidate else None
            result=dict(document=before_doc,saved_file_sha256=expected_source_sha256,
                inventory=inventory,operation_identities=identities,apt_names=names,current_controller=current,
                selected_name=controller_name,selected_parameters=params,candidate_file=file,
                catalogue_source=catalogue_source,installed_candidates=installed,name_mode=name_mode)
            if diagnostic is not None:diagnostic.update(result,capture_complete=True)
            return result,target
        with session:
            before,target=capture();report.update(before=before,state_sha256=_digest(before))
            report['apply_eligible']=action!='inspect' and before['current_controller']!=dict(is_apt=True,name=controller_name,success=True)
            if action=='apply':
                if not report['apply_eligible']:raise ValueError('Requested APT already selected; no replay')
                if report['state_sha256']!=expected_state_sha256:raise ValueError('Prepared state changed')
                current,target=capture()
                if current!=before:raise ValueError('State changed before controller assignment')
                if identity(clean=True)!=initial:raise ValueError('Document changed before assignment')
                report.update(phase='SetController2',mutation_attempted=True)
                _write_receipt(receipt,report);check()
                result=_member(target,'SetController2',True,controller_name,candidate['native_path_argument'])
                report.update(native_call_returned=True,native_result_raw=result,phase='SetController2_returned')
                _write_receipt(receipt,report);check()
                if result is False:
                    # false 可能仍改变 APT 标志；只读已知状态，不重试 setter，不宣称成功。
                    report.update(false_return_diagnostic_attempted=True,apply_eligible=False)
                    scalar=_controller(read(target,'GetController2'));report['immediate_controller_readback']=scalar
                    report['after_false']={}
                    after,_=capture(report['after_false'])
                    report.update(false_return_diagnostic_complete=True,
                        after_false_inventory_unchanged=(after['inventory']==before['inventory'] and
                            after['operation_identities']==before['operation_identities']))
                    final=after
                else:
                    if result is not True:raise ValueError('APT assignment did not return strict Boolean true; no retry or diagnostic replay')
                    scalar=_controller(read(target,'GetController2'));report['immediate_controller_readback']=scalar
                    wanted=dict(is_apt=True,name=controller_name,success=True)
                    if scalar!=wanted:raise ValueError('Exact APT/name readback failed; fallback selection is not accepted')
                    after,_=capture();report['after']=after
                    expected=deepcopy(before);expected['document']['needs_save']=after['document']['needs_save'];expected['current_controller']=wanted
                    if after!=expected:raise ValueError('State changed beyond requested controller and document dirty flag')
                    report['readback_verified']=True;report['controller_assignment_verified']=True;final=after
            else:final=before
            report['final_subscribed']=final;check()
        summary=session.summary();report['messages']=summary
        if summary.get('disconnected') is not True or summary.get('active') or any(summary.get(k) for k in
                ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')):
            raise ValueError('Event cleanup not confirmed')
        if identity()!=final['document']:raise ValueError('Document/file changed after cleanup')
        if candidate and _candidate(controller_file_path,controller_file_sha256,controller_name,path_argument_kind)!=candidate:
            raise ValueError('APT candidate file changed after cleanup')
        report['post_cleanup_document_file_verified']=True
        if report['false_return_diagnostic_attempted']:
            report.update(status='uncertain',phase='finished',readback_verified=False,controller_assignment_verified=False,
                reason='APT_SETTER_RETURNED_FALSE_DIAGNOSTIC_ONLY_NO_RETRY_OR_POSTPROCESS')
        else:
            report.update(status='review_required' if action=='apply' else 'ok',phase='finished',
                reason='APT_NAME_READBACK_ONLY_ACTUAL_LOADED_PATH_AND_OUTPUT_UNQUALIFIED' if action=='apply' else None)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'],phase='finished',issue=_error(exc),readback_verified=False,controller_assignment_verified=False)
    finally:
        if session is not None:report['messages']=session.summary()
        if created:
            try:_write_receipt(receipt,report)
            except Exception as exc:report.update(status='uncertain',receipt_write_error=_error(exc),readback_verified=False,controller_assignment_verified=False)
    return report
