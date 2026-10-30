"""从已验证的保存检查点导出 CL/WIP；不生成轨迹、不保存模型。"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import importlib
import json
import re
import os
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require

SCOPE = 'SAVED_GROUP_CHECKPOINT_EXPORT_V1'
EXPORT_ACTIONS = frozenset({'export_cl', 'export_wip'})
ACTIONS = EXPORT_ACTIONS | {'reconcile_saved_group'}
RECOVERY_SCOPE = 'READONLY_SAVED_GROUP_RECONCILIATION_V1'
ORDER = [143, 144, 195, 196, 267, 247, 248]
UNGENERATED = [143, 144, 195, 196]


def _group():
    return importlib.import_module('scripts.sw_cam_grouped_face_recipe')


def _key(path):
    return str(Path(path).resolve()).casefold()


def _pin(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=_file_hash(path))


def _check(pins):
    for pin in pins:
        require(_file_hash(pin['path']) == pin['sha256'], 'Export dependency changed')


def _merge(*groups):
    result = {}
    for group in groups:
        for raw in group:
            require(type(raw) is dict and type(raw.get('path')) is str
                and Path(raw['path']).is_absolute() and type(raw.get('sha256')) is str
                and re.fullmatch('[0-9a-f]{64}', raw['sha256']), 'Exact file pin required')
            key = _key(raw['path'])
            if key in result:
                require(result[key]['sha256'] == raw['sha256'], 'Conflicting export pin')
            else:
                result[key] = deepcopy(raw)
    return list(result.values())


def operation_contract(loaded):
    from scripts.sw_cam_cl_inventory import verify_export_operation_inventory
    state = loaded['state']
    require(len(state['features']) == 21 and state['operation_count'] == 7
        and [row['native_id'] for row in state['operations']] == ORDER
        and state['document']['needs_save'] is False, 'Exact clean saved21/7 required')
    count = loaded['toolpath_record_counts']
    require(type(count) is list and len(count) == 1 and type(count[0]) is int
        and 0 < count[0] <= 100000 and loaded['generated_face_operation_id'] == 267,
        'Actual single positive FACE count required')
    contract = [dict(operation_native_id=267, toolpath_record_counts=deepcopy(count)),
        dict(operation_native_id=247, toolpath_record_counts=[191]),
        dict(operation_native_id=248, toolpath_record_counts=[74])]
    verify_export_operation_inventory(state['operations'], 267, count, UNGENERATED, contract)
    face = next(row for row in state['operations'] if row['native_id'] == 267)
    require(face['linked_feature_ids'] == [265] and face['setup_native_id'] == 93
        and face['mill_operation_type'] == 20 and face['assigned_tool']['native_id'] == 249,
        'Saved FACE/tool/setup identity differs')
    return contract


def local_evidence_root():
    """固定用户本地状态目录；请求、输出名和配方不能改变一次性标记位置。"""
    value = os.environ.get('LOCALAPPDATA')
    require(type(value) is str and Path(value).is_absolute(), 'LOCALAPPDATA must be an absolute local directory')
    base = Path(value)
    require(base.is_dir() and not base.is_symlink() and not base.resolve().drive.startswith('\\\\'),
            'Persistent local user state directory required')
    root = base / 'SolidWorksAutomation' / 'cam-checkpoint-exports'
    require(not root.is_symlink() and not root.parent.is_symlink(), 'Local state root cannot be a symlink')
    root.mkdir(parents=True, exist_ok=True)
    require(root.resolve().is_relative_to(base.resolve()) and not root.resolve().drive.startswith('\\\\'),
            'Local state root escaped user state directory')
    return root.resolve()


def export_marker(action, source, source_sha256):
    require(action in ACTIONS, 'Unknown export action')
    digest = _digest(dict(scope=SCOPE, action=action, source=_key(source),
                          source_sha256=source_sha256, operation_native_id=267))
    return local_evidence_root() / ('checkpoint_' + action + '_' + digest + '.json')


def export_runtime_pins(action):
    names = ['sw_cam_cl_inventory', 'sw_cam_sandvik_phase1']
    if action == 'export_cl':
        names += ['sw_cam_mill_generic_cl', 'sw_cam_thread_postprocess', 'sw_cam_operation_profile']
    else:
        names += ['sw_cam_completed_gtp_wip']
    return [_pin(__file__)] + [_pin(importlib.import_module('scripts.' + name).__file__) for name in names]


def _phase_retirements(loaded, action):
    """完整父检查后，仅移走本能力不执行的辅助代码和已解析证据。"""
    root = Path(_group().__file__).resolve().parent
    names = ['sw_cam_mill_stock_export_evidence.py', 'sw_cam_installation.py']
    if loaded.get('authority_kind') != 'reconciled_saved_group':
        names += ['sw_cam_ud14_save.py', 'sw_cam_existing_sandvik.py']
    if action == 'export_cl':
        names += ['sw_cam_shared_holder_geometry.py']
    wanted = {_key(root / name) for name in names}
    if action == 'export_cl':
        recipes = [p for p in loaded['holder_recipe']['pins'] if Path(p['path']).suffix.casefold() == '.json']
        require(len(recipes) == 1, 'Exact parsed nominal holder recipe required')
        wanted.add(_key(recipes[0]['path']))
    retired = [p for p in loaded['pins'] if _key(p['path']) in wanted]
    require(len(retired) == len(wanted), 'Offline-only dependency role missing')
    return retired


def load_export_checkpoint(path, digest, *, action, process_id, expected_document_path,
                           expected_source_sha256):
    require(action in EXPORT_ACTIONS, 'Only export capability allowed')
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    header, _ = read_pin(path, digest)
    if header.get('scope') == RECOVERY_SCOPE:
        loaded = load_completed_reconciliation(path, digest, process_id=process_id,
            expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256)
    else:
        loaded = _group().load_completed_group(path, digest, process_id=process_id,
            expected_document_path=expected_document_path, expected_source_sha256=expected_source_sha256,
            check_current_source=True)
    operation_contract(loaded)
    require(loaded['source_sha256'] == loaded['state']['saved_file_sha256'] == expected_source_sha256
        and _file_hash(expected_document_path) == expected_source_sha256
        and _key(loaded['parent_pin']['path']) == _key(path) and loaded['parent_pin']['sha256'] == digest,
        'Current saved group authority differs')
    _check(loaded['pins'])
    retired = _phase_retirements(loaded, action)
    keys = {_key(p['path']) for p in retired}
    pins = _merge([p for p in loaded['pins'] if _key(p['path']) not in keys], export_runtime_pins(action))
    require(len(pins) <= 64, 'Export live dependency limit exceeded')
    require(all(_key(p['path']) not in keys for p in
        [loaded['parent_pin'], loaded['group_marker_pin']] +
        [p for p in loaded['pins'] if Path(p['path']).suffix.casefold() in ('.mt', '.mh', '.stl')]),
        'Current authority or native asset cannot retire')
    _check(pins)
    bootstrap = [p for p in retired if Path(p['path']).name == 'sw_cam_installation.py']
    require(len(bootstrap) == 1, 'Exact installation bootstrap phase pin required')
    result = dict(loaded, pins=pins, export_action=action,
        export_parent_pins=deepcopy(loaded['pins']), bootstrap_export_pins=deepcopy(bootstrap),
        offline_export_proof_pins=deepcopy([p for p in retired if p not in bootstrap]))
    require(_digest(_group().current_projection(result)) == loaded['current_context_sha256'],
        'Export cutover changed immutable current context')
    return result


def fresh_paths(loaded, args, action):
    source = args['expected_document_path']
    marker = export_marker(action, source, args['expected_source_sha256'])
    receipt = Path(args['receipt_path'])
    observation = receipt.with_suffix('.observations.json')
    protected = {_key(p['path']) for p in loaded['pins'] + loaded['offline_export_proof_pins'] + loaded['bootstrap_export_pins']}
    protected.add(_key(source))
    for path in (receipt, observation, marker):
        require(path.is_absolute() and path.suffix.casefold() == '.json' and path.parent.is_dir()
            and not path.exists() and not path.is_symlink(), 'Fresh export evidence and once marker required')
    require(len({_key(p) for p in (receipt, observation, marker)}) == 3
        and not protected.intersection({_key(p) for p in (receipt, observation, marker)}), 'Export evidence alias')
    return marker, observation


def verify_observed(loaded, observed, backend):
    """保留原始观察后比较；仅复用已批准的 mass_raw 相对误差规则。"""
    backend.verify_final(observed)
    backend.capture.cone.require_state_equivalent(loaded['state'], observed['state'])
    require(_group().exact(observed['settings'], loaded['settings']), 'Saved FACE/NC settings changed')
    require(_group().exact(observed['payload'], dict(rough=loaded['payload'], finish=loaded['finish_payload']))
        and _group().exact(observed['cone_observation'], loaded['cone_observation'])
        and _group().exact(observed['face_observation'], loaded['face_observation']), 'Saved protected payload/geometry changed')
    require(_group().exact(observed['units'], loaded['finish_payload']['unit_record']), 'Current units changed')
    operation_contract(dict(loaded, state=observed['state']))
    return deepcopy(loaded['state'])


class ExportEvidence:
    def __init__(self, loaded, args, action):
        self.loaded, self.args, self.action = loaded, dict(args), action
        self.marker, self.observation = fresh_paths(loaded, args, action)
        self.created = self.claimed = False
        self.marker_signature = None
        self.details = dict(scope=SCOPE, action=action, authoritative_checkpoint=False,
            parent_pin=deepcopy(loaded['parent_pin']), group_marker_pin=deepcopy(loaded['group_marker_pin']),
            source_sha256=args['expected_source_sha256'], live_pins=deepcopy(loaded['pins']),
            offline_export_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
            bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),
            bootstrap_validation=deepcopy(loaded.get('bootstrap_validation')), observations=[])

    def persist_observations(self):
        _write_receipt(self.observation, self.details, create=not self.created)
        self.created = True

    def marker_state(self, report):
        return dict(scope=SCOPE, action=self.action, source=self.args['expected_document_path'],
            source_sha256=self.args['expected_source_sha256'], parent_pin=deepcopy(self.loaded['parent_pin']),
            receipt_path=self.args['receipt_path'], observation_path=str(self.observation),
            status=report.get('status'), phase=report.get('phase'),
            native_call_attempted=report.get('native_call_attempted', False),
            native_call_returned=report.get('native_call_returned', False),
            native_dispatch_pending=report.get('native_dispatch_pending', False),
            readback_verified=report.get('readback_verified', False), automatic_replay=False)

    def claim(self, report):
        _check(self.loaded['pins'])
        _write_receipt(self.marker, self.marker_state(report), create=True)
        self.claimed = True
        self.marker_signature = None

    def persist_marker(self, report):
        if self.claimed:
            state = self.marker_state(report)
            signature = _digest({k:v for k,v in state.items() if k != 'phase'})
            if signature != self.marker_signature:
                _write_receipt(self.marker, state)
                self.marker_signature = signature

    def fields(self):
        return dict(scope=SCOPE, checkpoint_export_scope=SCOPE, checkpoint_export_action=self.action,
            saved_checkpoint_pin=deepcopy(self.loaded['parent_pin']), marker_path=str(self.marker),
            observations_path=str(self.observation), evidence_pins=deepcopy(self.loaded['pins']),
            offline_export_proof_pins=deepcopy(self.loaded['offline_export_proof_pins']),
            bootstrap_export_pins=deepcopy(self.loaded['bootstrap_export_pins']),
            bootstrap_validation=deepcopy(self.loaded.get('bootstrap_validation')),
            GTP_attempted=False, GOP_attempted=False, model_saved=False,
            assignment_attempted=False, setter_attempted=False, automatic_replay=False)


def make_backend(loaded, args, sw, clsid, typelib_path, evidence, external_events=None):
    group = _group()
    if external_events is None:
        backend_type = group.NativeBackend
    else:
        class ReadBackend(group.NativeBackend):
            def events(self, active=True):
                external_events(active)
        backend_type = ReadBackend
    return backend_type(loaded, args, sw, clsid, typelib_path, evidence.details,
                        evidence.persist_observations)


class CLContext:
    def __init__(self, loaded, args, sw, clsid, typelib_path):
        self.loaded, self.args = loaded, dict(args)
        self.evidence = ExportEvidence(loaded, args, 'export_cl')
        self.check = None
        self.backend = make_backend(loaded, args, sw, clsid, typelib_path, self.evidence,
            external_events=lambda active: self.check(active=active))

    def identity(self, sw):
        self.backend.ctx.files()
        return self.backend.ctx.identity()

    def report_fields(self):
        return self.evidence.fields()

    def validate(self, **request):
        from scripts.sw_cam_mill_generic_cl import validate_mill_cl_request
        require(request['action'] == 'apply' and request['acknowledge_machine_scope'] is True,
                'Only explicit machine export allowed')
        prepared = dict(request, action='prepare', expected_state_sha256=None, receipt_path=None)
        prepared['expected_generated_operations'] = operation_contract(self.loaded)
        validate_mill_cl_request(**prepared)

    def selected(self, state, feature_id, operation_id, operation_type):
        require((feature_id, operation_id, operation_type) == (265, 267, 20), 'Selected FACE identity changed')
        operation_contract(dict(self.loaded, state=state))
        return next(row for row in state['operations'] if row['native_id'] == 267)

    def verify_before(self, snapshot):
        require(snapshot['mill_state'] == self.loaded['state'], 'Export snapshot differs from saved checkpoint')

    def capture(self, sw, clsid, typelib_path, app, check, diagnostic):
        self.check = check
        self.backend.ctx.app = app
        observed = self.backend.capture_full(diagnostic['phase'])
        diagnostic['raw_observation'] = deepcopy(observed)
        self.evidence.details['observations'].append(deepcopy(observed))
        self.evidence.persist_observations()
        state = verify_observed(self.loaded, observed, self.backend)
        diagnostic['saved_checkpoint_match_verified'] = True
        return state, self.backend.native

    def claim(self, report):
        self.backend.boundary()
        self.evidence.claim(report)

    def persist(self, report):
        self.evidence.persist_marker(report)


def export_cl(sw, clsid, typelib_path, *, loaded, args, output_path):
    from scripts.sw_cam_mill_generic_cl import export_mill_generic_cl
    context = CLContext(loaded, args, sw, clsid, typelib_path)
    contract = operation_contract(loaded)
    report = export_mill_generic_cl(sw, clsid, typelib_path,
        **{k:args[k] for k in ('process_id','expected_document_path','expected_source_sha256',
            'qualification_only','acknowledge_disposable_copy','message_policy','receipt_path')},
        expected_feature_native_id=265, expected_operation_native_id=267, expected_mill_operation_type=20,
        expected_toolpath_record_counts=loaded['toolpath_record_counts'],
        expected_ungenerated_operation_ids=UNGENERATED, expected_generated_operations=contract,
        acknowledge_machine_scope=True, action='apply', output_path=output_path, _context_adapter=context)
    # 原核心可能无法序列化意外的非有限返回；辅助证据保留有界事实，不改写失败主收据。
    if context.evidence.created:
        encoded_return = _group().return_observation(report.get('native_hresult'))
        context.evidence.details['core_return_observation'] = encoded_return
        report['bounded_native_hresult'] = deepcopy(encoded_return)
        if not encoded_return['value_recorded']:
            report['native_hresult'] = None
        context.evidence.details['core_return_flags'] = {k:report.get(k) for k in
            ('status','phase','native_call_attempted','native_call_returned','native_dispatch_pending','readback_verified','receipt_write_error')}
        context.evidence.persist_observations()
    if report.get('phase') == 'finished' and report.get('readback_verified') is True and report.get('output_verified') is True:
        require(context.evidence.claimed, 'Successful core must own its attempt marker')
        try:
            context.backend.ctx.files()
            require(context.backend.ctx.identity() == loaded['state']['document'], 'CL cleanup changed document')
            report['checkpoint_export_readback_verified'] = True
        except Exception as exc:
            report.update(status='uncertain', failed_phase='export_finalize', issue=_error(exc), readback_verified=False)
        context.persist(report)
        _write_receipt(args['receipt_path'], report)
    return report


def export_wip(sw, clsid, typelib_path, *, loaded, args, project_root, output_dir):
    from scripts.sw_cam_completed_gtp_wip import run_one_wip_export, output_plan, collect_wip_files
    evidence = ExportEvidence(loaded, args, 'export_wip')
    directory, canonical = output_plan(output_dir, project_root, args['receipt_path'],
        args['expected_document_path'], loaded['pins'], evidence.marker)
    report = dict(evidence.fields(), schema_version=1, status='error', phase='preflight',
        process_id=args['process_id'], expected_document_path=args['expected_document_path'],
        source_sha256=args['expected_source_sha256'], native_scope='all_wip_parts_all_setups',
        single_operation_scope_claimed=False, native_dispatch_pending=False, mutation_attempted=False,
        native_call_attempted=False, native_call_returned=False, native_call_count=0,
        readback_verified=False, export_files_verified=False, files=[], capture_diagnostics=[],
        production_qualified=False, geometry_verified=False, manufacturing_tolerance_qualified=False)
    started = monotonic()
    created = False
    backend = None
    def persist():
        report['elapsed_seconds'] = monotonic() - started
        if created:
            if 'native_return_type' in report and 'bounded_native_return' not in report:
                value = report.get('native_return_value')
                observation = _group().return_observation(value)
                if report['native_return_type'] != type(value).__name__:
                    observation = dict(python_type=report['native_return_type'], value_recorded=False,
                                       value=None, limit_reason='nonprimitive_core_return')
                report['bounded_native_return'] = observation
                report['native_return_value'] = observation['value']
            _write_receipt(args['receipt_path'], report)
            evidence.persist_marker(report)
    def capture(label):
        observed = backend.capture_full(label)
        report['capture_diagnostics'].append(dict(phase=label, raw_observation=deepcopy(observed)))
        persist()
        state = verify_observed(loaded, observed, backend)
        return state, backend.native
    def claim():
        require(directory.resolve(strict=True) == canonical and not any(directory.iterdir()), 'WIP output changed')
        evidence.claim(report)
    def invoke(machine):
        value = _member(machine, 'CreateSTLOfWIPs2', *report['native_parameters'])
        report['immediate_native_return_observation'] = _group().return_observation(value)
        persist()
        return value
    try:
        _write_receipt(args['receipt_path'], report, create=True)
        created = True
        backend = make_backend(loaded, args, sw, clsid, typelib_path, evidence)
        backend.start()
        directory.mkdir()
        require(directory.resolve(strict=True) == canonical, 'WIP directory identity changed')
        parameters = [str(directory) + '\\', 'wip.stl', '', 0, 0]
        report['native_parameters'] = parameters
        run_one_wip_export(report, capture=capture, guard_factory=backend.ctx.guard,
            persist=persist, claim=claim, invoke=invoke,
            collect=lambda:collect_wip_files(directory, canonical))
        backend.finish()
        require(backend.ctx.identity() == loaded['state']['document'], 'WIP cleanup changed document')
        require(collect_wip_files(directory, canonical) == report['files'], 'WIP bytes changed after cleanup')
        report.update(status='review_required', phase='finished', checkpoint_export_readback_verified=True)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'], phase='finished', issue=_error(exc), readback_verified=False,
            export_files_verified=False)
    finally:
        if backend is not None:
            try: backend.close()
            except Exception as exc:
                report.update(status='uncertain', cleanup_error=_error(exc), readback_verified=False)
            report['messages'] = deepcopy(evidence.details.get('messages'))
        try: persist()
        except Exception as exc:
            report.update(status='uncertain', receipt_write_error=_error(exc), readback_verified=False)
    return report


def verify_failed_saved_group(data, marker, *, process_id, expected_document_path, expected_source_sha256):
    """仅接受已返回 Save0、但最终只读验证未发表的固定阶段前缀。"""
    group = _group()
    require(data.get('scope') == group.SCOPE and data.get('status') == 'error'
        and data.get('phase') == 'SaveActiveDocument' and data.get('current_action') == 'SaveActiveDocument'
        and data.get('model_saved') is False and data.get('readback_verified') is False
        and data.get('native_dispatch_pending') is False and data.get('full_capture_count') == 1,
        'Only the saved, unpublished final-read prefix is recoverable')
    require(type(process_id) is int and data['process_id'] == process_id
        and _key(data['source_path']) == _key(expected_document_path), 'Failed group PID/source differs')
    require(all(data.get(k) is False for k in ('automatic_retry','automatic_replay','automatic_rollback',
        'physical_geometry_verified','cutting_conditions_qualified','production_qualified')),
        'Unexpected failed-group policy')
    require(data['module_pin'] == group._self_pin(), 'Original grouped runtime changed')
    names = ['SetTool'] + [v[0] for v in group.CHANGES] + ['GenerateToolpath','SaveActiveDocument']
    require(set(data['actions']) == set(names), 'Exact original group actions required')
    for name in names:
        row = data['actions'][name]
        require(row.get('attempted') is True and row.get('returned') is True
            and row.get('native_dispatch_pending') is False, 'Original action is pending or unobserved')
        final = name == 'SaveActiveDocument'
        require(row['status'] == ('returned' if final else 'verified')
            and row['readback_verified'] is (not final), 'Unexpected action-prefix boundary')
        ret = row['native_return']
        require(ret.get('value_recorded') is True, 'Native return was not recorded')
        property_put = name in {v[0] for v in group.CHANGES if v[1] == 'property'}
        require((ret['python_type'] == 'NoneType' and ret['value'] is None) if property_put else
            (ret['python_type'] == 'int' and type(ret['value']) is int and ret['value'] == 0),
            'Strict original native return required')
    expected_marker = group.GroupJournal(data, data['receipt_path'], group.group_marker(data['source_path'],data['source_sha256']))._marker_state()
    require(group.exact(marker, expected_marker), 'Original once marker differs from durable main prefix')
    save = data['save_stage']; transition = data['source_transition']
    require(save.get('phase') == 'after_capture' and save.get('save_attempted') is True
        and save.get('native_call_attempted') is True and save.get('native_call_returned') is True
        and save.get('save_pending') is False and save.get('native_return_type') == 'int'
        and type(save.get('native_return_value')) is int and save['native_return_value'] == 0
        and save['saved_file_sha256'] == transition['source_after_sha256'] == expected_source_sha256
        and transition['source_before_sha256'] == data['source_sha256']
        and type(transition['strict_save_return']) is int and transition['strict_save_return'] == 0,
        'Exact successful native Save/source transition required')
    current = deepcopy(data['current_before'])
    require(set(current) == set(group.CURRENT_KEYS) and _digest(current) == data['current_before_sha256'],
            'Immutable original current context differs')
    group._require_current(current)
    from scripts.sw_cam_upper_cone_feature import require_state_equivalent
    require_state_equivalent(current['state'], data['baseline']['state'])
    require(data['baseline']['payload'] == dict(rough=current['payload'],finish=current['finish_payload'])
        and data['baseline']['cone_observation'] == current['cone_observation']
        and data['baseline']['face_observation'] == current['face_observation'], 'Original baseline differs')
    number = data['automatic_count_observation']
    require(number['before'] == 1 and number['physical_pass_count_verified'] is False, 'Unexpected derived-count proof')
    group.verify_settings(data['baseline']['settings'])
    group.verify_settings(data['configured']['settings'], configured=True)
    for label in ('generated','before_save'):
        group.verify_settings(data[label]['settings'],configured=True,generated_count=number['after'])
    expected_tool = next(v['assigned_tool'] for v in current['state']['operations'] if v['native_id'] == 248)
    group.verify_route_delta(current['state'], data['generated']['state'], expected_tool, generated=True)
    require(group.exact(group.NativeBackend.save_projection(None,data['generated']),
                        group.NativeBackend.save_projection(None,data['before_save'])), 'Generated preSave projection changed')
    require(group.exact(save['before'],group.NativeBackend.save_projection(None,data['before_save'])), 'Saved before projection differs')
    finals = [row for row in data['full_diagnostics'] if row.get('phase') == 'final']
    require(len(finals) == 1 and finals[0].get('capture_complete') is True, 'Complete persisted postSave header required')
    final = finals[0]; state = final['state']
    group.verify_route_delta(current['state'],state,expected_tool,generated=True,saved_sha=expected_source_sha256)
    require(state['document'] == transition['document'] and state['document']['needs_save'] is False
        and final['payload'] == dict(rough=current['payload'],finish=current['finish_payload'])
        and final['cone'] == current['cone_observation'], 'Persisted postSave payload/cone differs')
    require(group.exact(state['operations'],data['generated']['state']['operations']), 'Saved generated inventory changed')
    messages = data['messages']
    require(messages.get('subscribed') is True and messages.get('active') is True
        and not any(messages.get(k) for k in ('event_count','overflow','callback_errors','callback_error_count','subscription_error','disconnect_errors')),
        'Original event snapshot contains a failure')
    current.update(state=deepcopy(state),source_sha256=expected_source_sha256)
    face = next(v for v in state['operations'] if v['native_id'] == 267)
    return dict(current, settings=deepcopy(data['before_save']['settings']),generated_face_operation_id=267,
                toolpath_record_counts=deepcopy(face['toolpath_record_counts']),current_context_sha256=_digest(current))


def load_failed_saved_group(path, digest, *, marker_path, marker_sha256, process_id,
                            expected_document_path, expected_source_sha256):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    data, failed_pin = read_pin(path,digest); marker, marker_pin = read_pin(marker_path,marker_sha256)
    loaded = verify_failed_saved_group(data,marker,process_id=process_id,
        expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    require(_key(data['receipt_path']) == _key(path)
        and _key(marker_path) == _key(_group().group_marker(data['source_path'],data['source_sha256'])), 'Original publication paths differ')
    require(_file_hash(expected_document_path) == expected_source_sha256, 'Current saved source changed')
    parent, parent_pin = read_pin(data['parent_pin']['path'],data['parent_pin']['sha256'])
    require(parent.get('order_verified') is True and parent.get('readback_verified') is True
        and parent['current_after'] == data['current_before']
        and parent['current_after_sha256'] == data['current_before_sha256'], 'Original current authority differs')
    recipe, _ = read_pin(data['recipe_pin']['path'],data['recipe_pin']['sha256'])
    require(data['recipe_sha256'] == data['recipe_pin']['sha256'], 'Original recipe digest differs')
    _group().validate_plan(recipe)
    original = data['live_pins']; require(len(original) == 63, 'Exact original63 dependencies required')
    _check(original); _check([v['pin'] for v in data['retired_offline']])
    root = Path(_group().__file__).resolve().parent
    retired_keys = {_key(parent_pin['path']), _key(root/'sw_cam_ud14_save.py'), _key(root/'sw_cam_existing_sandvik.py')}
    retired = [p for p in original if _key(p['path']) in retired_keys]
    require(len(retired) == 3, 'Exact completed-parent/read-unused retirement required')
    phase1 = _pin(importlib.import_module('scripts.sw_cam_sandvik_phase1').__file__)
    live = _merge([p for p in original if _key(p['path']) not in retired_keys],
                  [_pin(__file__),phase1,failed_pin,marker_pin])
    require(len(live) == 64, 'Recovery current capture must retain64 pins')
    historical = data['historical_move_marker_pin']
    require(any(_key(p['path']) == _key(historical['path']) and p['sha256'] == historical['sha256'] for p in live),
            'Original uncertain Move marker must remain live')
    generated = [p for p in live if Path(p['path']).name.startswith('_FE488661_')]
    bootstrap = [p for p in live if Path(p['path']).name == 'sw_cam_installation.py']
    require(len(generated) == len(bootstrap) == 1, 'Native library/bootstrap binding missing')
    loaded.update(pins=live,parent_pin=failed_pin,failed_group_pin=failed_pin,group_marker_pin=marker_pin,
        generated_pin=generated[0],historical_move_marker_pin=historical,
        recovery_retired_pins=retired,bootstrap_export_pins=bootstrap,offline_export_proof_pins=[],
        authority_kind='expected_saved_group_reconciliation',failed_prefix_source_sha256=data['source_sha256'])
    operation_contract(loaded); _check(live)
    return loaded


def _local_receipt(path):
    p = Path(path)
    require(p.is_absolute() and p.suffix.casefold() == '.json' and p.parent.is_dir()
        and not p.exists() and not p.is_symlink() and not p.resolve().drive.startswith('\\\\'),
        'Fresh local-drive JSON receipt required')
    return p


def _recovery_marker_state(report):
    return {k:deepcopy(report[k]) for k in ('scope','status','phase','source_path','source_sha256',
        'failed_group_pin','receipt_path','read_pending','readback_verified','read_only','native_mutation_calls')}


def _run_reconciliation(sw, clsid, typelib_path, *, loaded, args):
    receipt = _local_receipt(args['receipt_path'])
    marker = export_marker('reconcile_saved_group',args['expected_document_path'],args['expected_source_sha256'])
    require(_key(receipt) != _key(marker) and not marker.exists() and not marker.is_symlink(),
            'Fresh separate reconciliation receipt and local marker required')
    report = dict(schema_version=1,scope=RECOVERY_SCOPE,status='reading',phase='preflight',read_only=True,
        native_mutation_calls=0,GTP_attempted=False,model_saved=False,setter_attempted=False,automatic_replay=False,
        process_id=args['process_id'],source_path=args['expected_document_path'],source_sha256=args['expected_source_sha256'],
        receipt_path=str(receipt),module_pin=_pin(__file__),failed_group_pin=deepcopy(loaded['failed_group_pin']),
        original_group_marker_pin=deepcopy(loaded['group_marker_pin']),live_pins=deepcopy(loaded['pins']),
        recovery_retired_pins=deepcopy(loaded['recovery_retired_pins']),local_state_root=str(local_evidence_root()),
        read_pending=False,readback_verified=False,full_capture_count=0)
    created = claimed = False; backend = None
    def persist():
        if created: _write_receipt(receipt,report)
    try:
        _write_receipt(receipt,report,create=True); created=True
        evidence=SimpleEvidence(report,persist)
        backend=make_backend(loaded,args,sw,clsid,typelib_path,evidence)
        backend.start()
        report.update(phase='capture_saved_group',read_pending=True)
        _write_receipt(marker,_recovery_marker_state(report),create=True);claimed=True;persist()
        observed=backend.capture_full('readonly_saved_group')
        report['observed']=deepcopy(observed);report['full_capture_count']=1;persist()
        verify_observed(loaded,observed,backend)
        backend.finish()
        require(backend.ctx.identity()==loaded['state']['document'],'Recovery cleanup changed document')
        current=_group().current_projection(loaded);current['state']=deepcopy(observed['state'])
        report['checkpoint']=dict(current=current,settings=deepcopy(observed['settings']),
            generated_face_operation_id=267,toolpath_record_counts=deepcopy(loaded['toolpath_record_counts']))
        report['checkpoint_sha256']=_digest(report['checkpoint'])
        report.update(status='observed',phase='finished',read_pending=False,readback_verified=True,
            state_reconciled=True,original_group_completion_claimed=False)
    except Exception as exc:
        report.update(status='error',failed_phase=report['phase'],phase='finished',issue=_error(exc),
                      read_pending=False,readback_verified=False)
    finally:
        if backend is not None:
            try:backend.close()
            except Exception as exc:report.update(status='error',cleanup_issue=_error(exc),readback_verified=False)
        try:
            if claimed:
                _write_receipt(marker,_recovery_marker_state(report))
                report['recovery_marker_pin']=_pin(marker)
            persist()
        except Exception as exc:report.update(status='error',receipt_write_error=_error(exc),readback_verified=False)
    return report


class SimpleEvidence:
    def __init__(self, report, persist):
        self.details=report
        self.persist_observations=persist


def load_completed_reconciliation(path, digest, *, process_id, expected_document_path, expected_source_sha256):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
    data,pin=read_pin(path,digest)
    require(data.get('scope')==RECOVERY_SCOPE and data.get('status')=='observed' and data.get('phase')=='finished'
        and data.get('read_only') is True and data.get('readback_verified') is True and data.get('state_reconciled') is True
        and data.get('read_pending') is False and data.get('full_capture_count')==1
        and data.get('native_mutation_calls')==0 and type(data.get('native_mutation_calls')) is int
        and data.get('original_group_completion_claimed') is False
        and all(data.get(k) is False for k in ('GTP_attempted','model_saved','setter_attempted','automatic_replay'))
        and not any(k in data for k in ('issue','failed_phase','cleanup_issue','receipt_write_error')),
        'Completed read-only saved-group reconciliation required')
    require(data['module_pin']==_pin(__file__) and data['process_id']==process_id
        and _key(data['source_path'])==_key(expected_document_path) and data['source_sha256']==expected_source_sha256
        and _key(data['local_state_root'])==_key(local_evidence_root())
        and _key(data['receipt_path'])==_key(path),'Reconciliation runtime/PID/source/local-policy differs')
    clean_events(data)
    loaded=load_failed_saved_group(data['failed_group_pin']['path'],data['failed_group_pin']['sha256'],
        marker_path=data['original_group_marker_pin']['path'],marker_sha256=data['original_group_marker_pin']['sha256'],
        process_id=process_id,expected_document_path=expected_document_path,expected_source_sha256=expected_source_sha256)
    require(data['live_pins']==loaded['pins'] and data['recovery_retired_pins']==loaded['recovery_retired_pins'], 'Recovery dependency roles differ')
    observed=data['observed'];backend=object.__new__(_group().NativeBackend)
    backend.loaded=loaded;backend.expected_tool=next(v['assigned_tool'] for v in loaded['state']['operations'] if v['native_id']==248)
    backend.args={'expected_source_sha256':expected_source_sha256}
    backend.ctx=type('SavedContext',(),{'args':backend.args})()
    from scripts import sw_cam_raw_mill_face_operation as capture
    backend.capture=capture
    verify_observed(loaded,observed,backend)
    current=_group().current_projection(loaded);current['state']=deepcopy(observed['state'])
    cp=dict(current=current,settings=deepcopy(observed['settings']),generated_face_operation_id=267,toolpath_record_counts=deepcopy(loaded['toolpath_record_counts']))
    require(data['checkpoint']==cp and data['checkpoint_sha256']==_digest(cp),'Reconciled current checkpoint differs')
    marker=export_marker('reconcile_saved_group',expected_document_path,expected_source_sha256)
    mark,markpin=read_pin(str(marker),data['recovery_marker_pin']['sha256'])
    require(mark==_recovery_marker_state(data) and _key(data['recovery_marker_pin']['path'])==_key(marker), 'Local completed reconciliation marker differs')
    live=_merge([p for p in loaded['pins'] if _key(p['path'])!=_key(loaded['failed_group_pin']['path'])],[pin])
    require(len(live)==64,'Completed reconciliation must preserve64 live paths')
    loaded.update(current,pins=live,parent_pin=pin,settings=cp['settings'],current_context_sha256=_digest(current),
        authority_kind='reconciled_saved_group',recovery_receipt_pin=pin,recovery_marker_pin=markpin)
    _check(live);return loaded


COMMON = {'checkpoint_receipt_path','checkpoint_receipt_sha256','process_id','expected_document_path',
    'expected_source_sha256','receipt_path','qualification_only','acknowledge_disposable_copy',
    'acknowledge_machine_scope','message_policy','module_sha256','addin_clsid'}


def validate_request(request):
    require(type(request) is dict and set(request) == {'action','params'} and request['action'] in ACTIONS,
            'Only CL/WIP exports allowed')
    action, params = request['action'], request['params']
    wanted = COMMON | ({'output_path'} if action == 'export_cl' else {'output_dir','project_root'} if action == 'export_wip' else {'group_marker_path','group_marker_sha256'})
    require(type(params) is dict and set(params) == wanted, 'Exact export request fields required')
    require(type(params['process_id']) is int and 0 < params['process_id'] < 2**32, 'Exact owned PID required')
    for key, value in params.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value), 'Strict SHA256 required')
        if key.endswith('path') or key in ('output_dir','project_root'):
            require(type(value) is str and Path(value).is_absolute(), 'Absolute path required')
    require(params['module_sha256'] == _file_hash(__file__) and params['qualification_only'] is True
        and params['acknowledge_disposable_copy'] is True and params['acknowledge_machine_scope'] is True
        and params['message_policy'] == 'vendor_default', 'Explicit software-only qualification required')
    require(type(params['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',params['addin_clsid']), 'Exact CAM CLSID required')
    return action, dict(params)



def discover_export_registration(loaded, addin_clsid):
    """注册表发现只在连接前执行；阶段前后检查真实实现文件。"""
    from scripts import sw_cam_installation as installation
    from scripts.sw_cam import select_registration
    pins = loaded['bootstrap_export_pins']
    require(len(pins) == 1 and _key(pins[0]['path']) == _key(installation.__file__),
            'Exact installation implementation binding required')
    _check(pins)
    inventory = installation.discover_cam_installations()
    _check(pins)
    require(not inventory['errors'], 'Installation discovery errors')
    loaded['bootstrap_validation'] = dict(role='bootstrap_checked', pins=deepcopy(pins),
        checked_before=True, checked_after=True, executes_during_native_capture=False)
    return select_registration(inventory, addin_clsid)


def dispatch_request(request):
    action, params = validate_request(request)
    args = {k:params[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy')}
    identity = {k:args[k] for k in ('process_id','expected_document_path','expected_source_sha256')}
    if action == 'reconcile_saved_group':
        loaded = load_failed_saved_group(params['checkpoint_receipt_path'],params['checkpoint_receipt_sha256'],
            marker_path=params['group_marker_path'],marker_sha256=params['group_marker_sha256'],**identity)
        _local_receipt(args['receipt_path'])
        require(not export_marker(action,args['expected_document_path'],args['expected_source_sha256']).exists(), 'Existing readonly attempt')
    else:
        loaded = load_export_checkpoint(params['checkpoint_receipt_path'],params['checkpoint_receipt_sha256'],action=action,**identity)
        fresh_paths(loaded,args,action)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=args['process_id']):
        _check(loaded['pins'])
        registration = discover_export_registration(loaded, params['addin_clsid'])
        sw, _ = connect_solidworks(process_id=args['process_id'],launch_new_instance=False,wait_seconds=1)
        typelib = str(Path(registration['addin_path']).parent/'camworks.tlb')
        if action == 'reconcile_saved_group':
            return _run_reconciliation(sw,registration['clsid'],typelib,loaded=loaded,args=args)
        if action == 'export_cl':
            return export_cl(sw,registration['clsid'],typelib,loaded=loaded,args=args,output_path=params['output_path'])
        return export_wip(sw,registration['clsid'],typelib,loaded=loaded,args=args,
            project_root=params['project_root'],output_dir=params['output_dir'])


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    options=parser.parse_args(argv)
    result=dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')))
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','marker_path')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
