"""只在已证明的新空会话卸载 Plastics；不更改注册表、文档或其它加载项。"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
from scripts.sw_cam import _error, _member
from scripts.sw_cam_feature_sketch import _call_method
from scripts.sw_executable_launch import _process_identity
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_checkpoint_exports import local_evidence_root

CLSID = '{B4D933F9-F4A9-4555-B4C7-8A06D0115CDC}'
SCOPE = 'PLASTICS_EMPTY_OWNED_SESSION_UNLOAD_V1'


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(path):
    return os.path.normcase(str(Path(path).resolve()))


def registry_tree(hive, key):
    """严格只读；不存在与无法读取分别处理，保留值类型。"""
    import winreg
    try:
        handle = winreg.OpenKey(hive, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return dict(exists=False, key=key)
    with handle:
        subcount, valcount, _ = winreg.QueryInfoKey(handle)
        require(subcount <= 256 and valcount <= 256, 'Unexpected registry tree size')
        values = []
        for i in range(valcount):
            name, value, kind = winreg.EnumValue(handle, i)
            if isinstance(value, bytes):
                value = {'hex': value.hex()}
            values.append(dict(name=name, value=value, kind=kind))
        children = [winreg.EnumKey(handle, i) for i in range(subcount)]
    return dict(exists=True, key=key, values=sorted(values, key=lambda r:r['name']),
                children=[registry_tree(hive, key+'\\'+name) for name in sorted(children)])


def value_of(tree, name=''):
    values = [r['value'] for r in tree.get('values', []) if r['name'] == name]
    require(len(values) == 1, 'Required registry value absent or ambiguous')
    return values[0]


def inspect_registration(year):
    """从当前版本的系统注册和有效 COM 注册绑定唯一 Plastics DLL。"""
    import winreg
    require(type(year) is int and 2020 <= year <= 2100, 'Explicit installed year required')
    addin = registry_tree(winreg.HKEY_LOCAL_MACHINE, f'SOFTWARE\\SolidWorks\\SOLIDWORKS {year}\\Addins\\{CLSID}')
    require(value_of(addin, 'Title').casefold() == 'solidworks plastics', 'Registered add-in is not Plastics')
    server = registry_tree(winreg.HKEY_CLASSES_ROOT, 'CLSID\\'+CLSID+'\\InprocServer32')
    progid = registry_tree(winreg.HKEY_CLASSES_ROOT, 'CLSID\\'+CLSID+'\\ProgID')
    user = registry_tree(winreg.HKEY_CURRENT_USER, 'Software\\Classes\\CLSID\\'+CLSID)
    require(not user['exists'], 'User COM override requires independent qualification')
    dll = Path(value_of(server))
    require(dll.is_absolute() and dll.is_file() and not dll.is_symlink()
            and dll.name.casefold() == 'simpoeworks.dll', 'Exact registered Plastics DLL required')
    module = dll.parent/'SimpoeMV'/'SimpoeMoldWorks.DLL'
    require(module.is_file() and not module.is_symlink(), 'Plastics model module missing')
    return dict(clsid=CLSID, year=year, addin_path=str(dll), addin_sha256=file_sha(dll),
                crash_module_path=str(module), crash_module_sha256=file_sha(module),
                progid=value_of(progid), registration=dict(addin=addin, server=server, progid=progid, user_override=user))


def startup_registry(year):
    """只读快照用户启动项；绝不写入自动加载设置。"""
    import winreg
    return {key:registry_tree(winreg.HKEY_CURRENT_USER, key) for key in
            ('Software\\SolidWorks\\AddInsStartup', f'Software\\SolidWorks\\SOLIDWORKS {year}\\AddInsStartup')}


def process_modules(pid):
    """通过 OS 模块列表观察，不调用可能创建加载项的 getter。"""
    import win32api
    import win32process
    handle = win32api.OpenProcess(0x410, False, pid)
    try:
        modules = win32process.EnumProcessModulesEx(handle, 3)
        require(0 < len(modules) <= 4096, 'Module enumeration empty or oversized')
        paths = sorted({str(win32process.GetModuleFileNameEx(handle, h)) for h in modules}, key=str.casefold)
        require(all(Path(p).is_absolute() for p in paths), 'Nonabsolute module path')
        return paths
    finally:
        handle.Close()


def once_path(pid, created):
    return local_evidence_root()/('plastics_unload_'+digest(dict(scope=SCOPE, process_id=pid, create_time=created, clsid=CLSID))+'.json')


def _json_path(path, fresh=False):
    p = Path(path)
    require(p.is_absolute() and p.suffix.lower() == '.json' and not p.is_symlink(), 'Absolute JSON path required')
    require(p.parent.is_dir(), 'Existing receipt directory required')
    require(not p.exists() if fresh else p.is_file(), 'Receipt existence differs from contract')
    return p


def late_attach_evidence(path, expected_sha, pid):
    """只读验证延迟连接的独立回执；绝不改写原启动结果。"""
    p = _json_path(path)
    require(p.stat().st_size <= 4*1024*1024 and file_sha(p) == expected_sha, 'Late-attach receipt hash or size differs')
    report = json.loads(p.read_text(encoding='utf-8-sig'))
    require(report.get('status') == 'success' and report.get('request_count') == 2
            and len(report.get('results', [])) == 2, 'Completed two-step late-attach evidence required')
    parsed = []
    for index, name in enumerate(('solidworks_connect', 'solidworks_inspect_open_documents')):
        row = report['results'][index]
        require(row.get('index') == index and row.get('name') == name
                and row.get('outcome') == {'status':'success', 'may_continue':True}, 'Late-attach tool sequence differs')
        result = row.get('result', {})
        require(result.get('isError') is False, 'Late-attach tool failed')
        text = [r for r in result.get('content', []) if r.get('type') == 'text']
        require(len(text) == 1, 'Single late-attach result required')
        value = json.loads(text[0]['text'])
        require(value == text[0].get('parsed_json')
                and value == json.loads(result.get('structuredContent', {}).get('result', 'null')),
                'Contradictory late-attach result representations')
        require(value.get('status') == 'ok' and type(value.get('process_id')) is int
                and value['process_id'] == pid and value.get('active_document', 'missing') is None,
                'Late-attach process or active document differs')
        parsed.append(value)
    connection, inventory = parsed
    require(connection.get('session_target') == {'process_id':pid, 'scope':'mcp_server', 'strict':True},
            'Late-attach must explicitly pin the exact PID')
    require(inventory.get('documents') == [] and type(inventory.get('document_count')) is int
            and inventory['document_count'] == 0 and inventory.get('user_control') is True
            and inventory.get('mutation_attempted') is False, 'Late-attach empty controlled session not verified')
    return p


def unload_plastics(sw, *, action, process_id, expected_process_create_time, expected_no_documents,
                    year, addin_path, expected_addin_sha256, crash_module_path, expected_crash_module_sha256,
                    startup_receipt_path, startup_receipt_sha256, receipt_path,
                    prepare_receipt_path=None, prepare_receipt_sha256=None,
                    late_attach_receipt_path=None, late_attach_receipt_sha256=None):
    """prepare 只读；apply 最多一次 UnloadAddIn，仍映射的 DLL 不判成功。"""
    require(action in ('prepare', 'apply'), 'Unknown action')
    require(type(process_id) is int and 0 < process_id < 2**32, 'Exact PID required')
    require(type(expected_process_create_time) in (int,float) and math.isfinite(expected_process_create_time)
            and expected_process_create_time > 0, 'Exact finite process lifetime required')
    require(expected_no_documents is True, 'Explicit empty session required')
    for value in (addin_path, crash_module_path):
        require(type(value) is str and Path(value).is_absolute() and Path(value).is_file()
                and Path(value).suffix.casefold() == '.dll' and not Path(value).is_symlink(),
                'Existing absolute nonsymlink DLL path required')
    out = _json_path(receipt_path, fresh=True)
    launch_path = _json_path(startup_receipt_path)
    require(file_sha(launch_path) == startup_receipt_sha256, 'Startup receipt hash changed')
    launch = json.loads(launch_path.read_text(encoding='utf8'))
    require(launch.get('launch_mode') == 'executable' and launch.get('new_process_verified') is True
            and launch.get('process_id') == process_id and type(launch.get('known_process_ids_before')) is list
            and process_id not in launch['known_process_ids_before'], 'Verified new owned executable session receipt required')
    late_path = None
    if late_attach_receipt_path is not None or late_attach_receipt_sha256 is not None:
        require(late_attach_receipt_path is not None and late_attach_receipt_sha256 is not None,
                'Late-attach path and SHA must be supplied together')
        require(launch.get('status') == 'uncertain' and launch.get('phase') == 'waiting_for_exact_pid_rot'
                and launch.get('launch_attempted') is True, 'Late attach only qualifies an owned startup waiting for ROT')
        late_path = late_attach_evidence(late_attach_receipt_path, late_attach_receipt_sha256, process_id)
        require(identity(late_path) != identity(launch_path), 'Late-attach evidence must be separate from startup receipt')
    else:
        require(launch.get('status') == 'ok' and launch.get('phase') == 'connected',
                'Verified connected startup receipt or separately pinned late attach required')
    expected_owner = launch.get('process_identity', {})
    require(expected_owner.get('process_id') == process_id and expected_owner.get('alive') is True
            and expected_owner.get('create_time') == expected_process_create_time, 'Startup lifetime differs')
    config = dict(scope=SCOPE, process_id=process_id, expected_process_create_time=expected_process_create_time,
                  expected_no_documents=True, year=year, addin_path=identity(addin_path), expected_addin_sha256=expected_addin_sha256,
                  crash_module_path=identity(crash_module_path), expected_crash_module_sha256=expected_crash_module_sha256,
                  startup_receipt_path=identity(launch_path), startup_receipt_sha256=startup_receipt_sha256,
                  late_attach_receipt_path=identity(late_path) if late_path is not None else None,
                  late_attach_receipt_sha256=late_attach_receipt_sha256,
                  startup_qualification='separate_late_attach' if late_path is not None else 'connected_at_startup',
                  implementation_sha256=file_sha(Path(__file__)))
    prior = None
    if action == 'apply':
        p = _json_path(prepare_receipt_path or '')
        require(file_sha(p) == prepare_receipt_sha256, 'Prepare receipt hash changed')
        prior = json.loads(p.read_text(encoding='utf8'))
        require(prior.get('status') == 'prepared' and prior.get('apply_eligible') is True
                and prior.get('config') == config, 'Prepared operation differs')
    else:
        require(prepare_receipt_path is None and prepare_receipt_sha256 is None, 'Prepare rejects continuation arguments')
    marker = once_path(process_id, float(expected_process_create_time))
    require(identity(out) != identity(marker), 'Output aliases durable attempt marker')
    require(not marker.exists() and not marker.is_symlink(), 'Attempt already claimed; never replay')
    report = dict(schema_version=1, scope=SCOPE, status='pending', phase='preflight', action=action, config=config,
                  unload_attempted=False, unload_calls=0, native_dispatch_pending=False, may_continue=False,
                  unloaded_verified=False, registry_write_attempted=False, model_change_requested=False,
                  process_restart_attempted=False, getter_used=False, automatic_retry=False, production_release=False)
    created = False
    def guard():
        owner = _process_identity(process_id)
        require(owner == expected_owner and Path(owner.get('executable','')).name.casefold() == 'sldworks.exe', 'Owned process changed')
        require(_call_method(sw, 'GetProcessID') == process_id, 'Connected PID differs')
        require(int(str(_member(sw, 'RevisionNumber')).split('.')[0])+1992 == year, 'Application major version differs')
        docs = _call_method(sw, 'GetDocuments')
        require(docs is None or type(docs) in (tuple,list) and not docs, 'Hidden or visible document is open')
        require(_member(sw, 'ActiveDoc') is None, 'Active document present')
        if late_path is not None:
            require(file_sha(late_path) == late_attach_receipt_sha256, 'Late-attach evidence changed')
            require(_member(sw, 'UserControl') is True, 'Late-attached session is no longer user controlled')
        registration = inspect_registration(year)
        require(identity(registration['addin_path']) == config['addin_path']
                and registration['addin_sha256'] == expected_addin_sha256
                and identity(registration['crash_module_path']) == config['crash_module_path']
                and registration['crash_module_sha256'] == expected_crash_module_sha256, 'Registration or DLL bytes differ')
        startup = startup_registry(year)
        modules = process_modules(process_id)
        wanted = {config['addin_path'], config['crash_module_path']}
        target_names = {'simpoeworks.dll', 'simpoemoldworks.dll'}
        require(not any(Path(p).name.casefold() in target_names and identity(p) not in wanted for p in modules),
                'A same-name Plastics DLL is mapped from another path')
        targets = sorted({identity(p) for p in modules if identity(p) in wanted})
        require(_process_identity(process_id) == owner and file_sha(launch_path) == startup_receipt_sha256, 'Owner or startup evidence changed')
        return dict(owner=owner, registration=registration, startup_registry=startup, startup_registry_sha256=digest(startup),
                    mapped_target_modules=targets, module_inventory_sha256=digest(modules), module_count=len(modules),
                    open_documents=[], active_document=None)
    def comparable(state):
        return {k:v for k,v in state.items() if k not in ('module_inventory_sha256', 'module_count')}
    try:
        before = guard();report['before'] = before
        if prior is not None:
            require(comparable(before) == comparable(prior['before']), 'Prepared process/add-in state changed')
        if action == 'prepare':
            mapped = before['mapped_target_modules']
            require(not mapped or config['addin_path'] in mapped, 'Orphan Plastics module mapped without registered add-in')
            report.update(status='prepared', phase='finished', apply_eligible=bool(mapped), already_unmapped=not mapped,
                          module_absence_verified=not mapped, may_continue=not mapped)
            _write_receipt(out, report, create=True)
            return report
        require(config['addin_path'] in before['mapped_target_modules'], 'Registered add-in is no longer mapped')
        _write_receipt(out, report, create=True);created=True
        _write_receipt(marker, dict(scope=SCOPE, status='claimed_no_replay', config=config, receipt_path=str(out)), create=True)
        require(comparable(guard()) == comparable(before), 'Scope changed before unload')
        report.update(phase='UnloadAddIn', unload_attempted=True, unload_calls=1, native_dispatch_pending=True)
        _write_receipt(out, report)
        returned = _call_method(sw, 'UnloadAddIn', str(Path(addin_path)))
        report.update(phase='UnloadAddIn_returned', unload_result=returned, native_dispatch_pending=False)
        _write_receipt(out, report)
        after = guard();report['after'] = after
        report['startup_registry_unchanged'] = after['startup_registry'] == before['startup_registry']
        require(report['startup_registry_unchanged'], 'Startup registry changed; no automatic restoration')
        require(after['registration'] == before['registration'], 'Registration changed')
        require(type(returned) is int and returned == 0, 'UnloadAddIn did not return integer zero')
        require(not after['mapped_target_modules'], 'Native returned zero but Plastics modules remain mapped')
        report.update(status='ok', phase='finished', unloaded_verified=True, module_absence_verified=True, may_continue=True)
    except Exception as exc:
        report.update(status='uncertain' if report['unload_attempted'] else 'error', failed_phase=report['phase'],
                      phase='finished', issue=_error(exc), unloaded_verified=False, may_continue=False)
    try:
        _write_receipt(out, report, create=not created)
    except Exception as exc:
        report.update(status='uncertain', receipt_write_issue=_error(exc), unloaded_verified=False, may_continue=False)
    return report