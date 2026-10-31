"""One read-only WIP export from a saved generated rough-pocket route.

The FINE export choice is the existing native setting, not a geometric error
bound. Mesh resolution, cut geometry and manufacturing readiness remain unproven.
"""
from copy import deepcopy
from pathlib import Path
from time import monotonic
import json
import re
from scripts import sw_cam_pocket_rough_exports as rough
cl = rough.cl
from scripts import sw_cam_completed_gtp_wip as core
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require

common, group = cl.common, cl.group
SCOPE = 'SAVED_ROUGH_POCKET_WIP_EXPORT_V1'


def marker_path(source, source_sha256, operation_id):
    key = _digest(dict(scope=SCOPE, source=common._key(source), source_sha256=source_sha256,
                      operation_native_id=operation_id))
    return common.local_evidence_root() / ('pocket_rough_wip_' + key + '.json')


def fresh_paths(loaded, args):
    marker = marker_path(args['expected_document_path'], args['expected_source_sha256'],
                         loaded['generated_pocket']['native_id'])
    receipt = Path(args['receipt_path']); observation = receipt.with_suffix('.observations.json')
    protected = {common._key(p['path']) for p in loaded['pins'] + loaded['offline_export_proof_pins']
                 + loaded['bootstrap_export_pins']}
    protected.add(common._key(args['expected_document_path']))
    paths = (receipt, observation, marker)
    for path in paths:
        require(path.is_absolute() and path.suffix.casefold() == '.json' and path.parent.is_dir()
            and not path.exists() and not path.is_symlink(), 'Fresh WIP evidence and once marker required')
    require(len({common._key(p) for p in paths}) == 3
        and not protected.intersection({common._key(p) for p in paths}), 'WIP evidence alias')
    return marker, observation


def load_checkpoint(path, digest, **identity):
    loaded = rough.load_checkpoint(path, digest, **identity)
    inactive = {'sw_cam_mill_generic_cl.py', 'sw_cam_thread_postprocess.py', 'sw_cam_operation_profile.py'}
    retired = [p for p in loaded['pins'] if Path(p['path']).name in inactive]
    require({Path(p['path']).name for p in retired} == inactive, 'Exact inactive CL phase roles required')
    live = common._merge([p for p in loaded['pins'] if p not in retired],
                         [common._pin(__file__), common._pin(core.__file__)])
    offline = common._merge(loaded['offline_export_proof_pins'], retired)
    require(len(live) <= 64, 'WIP dependency bound exceeded')
    common._check(live); common._check(offline)
    return dict(loaded, pins=live, offline_export_proof_pins=offline,
                wip_phase_retired_pins=retired)


class Evidence(cl.Evidence):
    def __init__(self, loaded, args):
        self.loaded, self.args = loaded, dict(args)
        self.marker, self.observation = fresh_paths(loaded, args)
        self.created = self.claimed = False
        self.marker_signature = None
        self.details = dict(scope=SCOPE, parent_pin=deepcopy(loaded['parent_pin']),
            generated_marker_pin=deepcopy(loaded['group_marker_pin']),
            source_sha256=args['expected_source_sha256'], live_pins=deepcopy(loaded['pins']),
            offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
            fresh_fields=cl.FRESH_SCOPE, reused_fields=cl.REUSED_SCOPE + ['saved_rough143_parameters_and_startpoints'], observations=[])
    def marker_state(self, report):
        result = super().marker_state(report); result.update(scope=SCOPE, operation_native_id=143)
        return result
    def fields(self):
        result = super().fields()
        result.update(scope=SCOPE, checkpoint_export_scope=SCOPE, checkpoint_export_action='export_wip',
            wip_phase_retired_pins=deepcopy(self.loaded['wip_phase_retired_pins']),
            reused_fields=deepcopy(self.details['reused_fields']),
            expected_generated_operations=rough.operation_contract(self.loaded),
            expected_ungenerated_operation_ids=deepcopy(rough.UNGENERATED))
        return result


class ReadBackend(cl.ReadBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, external_events=None, **kwargs)
    def events(self, active=True):
        return group.NativeBackend.events(self, active)


def export_wip(sw, clsid, typelib_path, *, loaded, args, project_root, output_dir):
    evidence = Evidence(loaded, args)
    directory, canonical = core.output_plan(output_dir, project_root, args['receipt_path'],
        args['expected_document_path'], loaded['pins'], evidence.marker)
    report = dict(evidence.fields(), schema_version=1, status='error', phase='preflight',
        process_id=args['process_id'], expected_document_path=args['expected_document_path'],
        source_sha256=args['expected_source_sha256'], native_scope='all_wip_parts_all_setups',
        single_operation_scope_claimed=False, native_dispatch_pending=False, mutation_attempted=False,
        native_call_attempted=False, native_call_returned=False, native_call_count=0,
        readback_verified=False, export_files_verified=False, files=[], capture_diagnostics=[],
        production_qualified=False, geometry_verified=False, manufacturing_tolerance_qualified=False,
        mesh_error_bound_qualified=False, export_quality_raw=0, export_quality_label='FINE',
        phase_proofs_verified_after_export=False, checkpoint_export_readback_verified=False)
    started = monotonic(); created = False; backend = None
    def persist():
        report['elapsed_seconds'] = monotonic() - started
        if created:
            if 'native_return_type' in report and 'bounded_native_return' not in report:
                value = report.get('native_return_value'); observation = group.return_observation(value)
                if report['native_return_type'] != type(value).__name__:
                    observation = dict(python_type=report['native_return_type'], value_recorded=False,
                                       value=None, limit_reason='nonprimitive_core_return')
                report['bounded_native_return'] = observation
                report['native_return_value'] = observation['value']
            _write_receipt(args['receipt_path'], report); evidence.persist(report)
    def capture(label):
        observed = backend.capture_export(label)
        evidence.details['observations'].append(deepcopy(observed)); evidence.persist_observations()
        state, comparison = rough.verify_observed(loaded, observed)
        report['capture_diagnostics'].append(dict(phase=label, comparison=comparison,
                                                saved_checkpoint_match_verified=True))
        persist(); return state, backend.native
    def claim():
        require(directory.resolve(strict=True) == canonical and not any(directory.iterdir()), 'WIP output changed')
        evidence.claim(report)
    def invoke(machine):
        value = _member(machine, 'CreateSTLOfWIPs2', *report['native_parameters'])
        report['immediate_native_return_observation'] = group.return_observation(value)
        persist(); return value
    try:
        _write_receipt(args['receipt_path'], report, create=True); created = True
        reader_args = dict(args, feature_native_id=loaded['configured_contour']['feature_native_id'])
        backend = ReadBackend(loaded, reader_args, sw, clsid, typelib_path, evidence.details,
                              evidence.persist_observations)
        backend.start()
        directory.mkdir()
        require(directory.resolve(strict=True) == canonical, 'WIP directory identity changed')
        report['native_parameters'] = [str(directory) + '\\', 'wip.stl', '', 0, 0]
        core.run_one_wip_export(report, capture=capture, guard_factory=backend.ctx.guard,
            persist=persist, claim=claim, invoke=invoke,
            collect=lambda:core.collect_wip_files(directory, canonical))
        backend.finish()
        require(backend.ctx.identity() == loaded['state']['document'], 'WIP cleanup changed document')
        require(core.collect_wip_files(directory, canonical) == report['files'], 'WIP changed after cleanup')
        common._check(loaded['offline_export_proof_pins']); common._check(loaded['bootstrap_export_pins'])
        backend.ctx.files()
        report.update(status='review_required', phase='finished', checkpoint_export_readback_verified=True,
                      phase_proofs_verified_after_export=True)
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
            failed_phase=report['phase'], phase='finished', issue=_error(exc), readback_verified=False,
            export_files_verified=False, checkpoint_export_readback_verified=False)
    finally:
        if backend is not None:
            try: backend.close()
            except Exception as exc:
                report.update(status='uncertain', cleanup_error=_error(exc), readback_verified=False,
                    export_files_verified=False, checkpoint_export_readback_verified=False)
            report['messages'] = deepcopy(evidence.details.get('messages'))
        try: persist()
        except Exception as exc:
            report.update(status='uncertain', receipt_write_error=_error(exc), readback_verified=False,
                export_files_verified=False, checkpoint_export_readback_verified=False)
    return report


PARAMS = common.COMMON | {'output_dir','project_root','protected_cl_receipt_path',
                          'protected_cl_receipt_sha256','protected_cl_path'}


def validate_request(request):
    require(type(request) is dict and set(request) == {'action','params'} and request['action'] == 'export_wip',
            'Only saved-route WIP export allowed')
    p = request['params']
    require(type(p) is dict and set(p) == PARAMS, 'Exact WIP request fields required')
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**32, 'Positive owned PID required')
    for key, value in p.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Strict SHA256 required')
        if key.endswith('path') or key in ('project_root','output_dir'):
            require(type(value) is str and Path(value).is_absolute(), 'Absolute path required')
    require(p['module_sha256'] == _file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy'] == 'vendor_default', 'Explicit qualified read-only WIP export required')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', p['addin_clsid']), 'Exact CAM CLSID required')
    return deepcopy(p)


def dispatch_request(request, *, validate_only=False):
    p = validate_request(request)
    identity = {k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'protected_cl_receipt_path','protected_cl_receipt_sha256','protected_cl_path')}
    loaded = load_checkpoint(p['checkpoint_receipt_path'], p['checkpoint_receipt_sha256'], **identity)
    args = {k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256',
        'receipt_path','qualification_only','acknowledge_disposable_copy','message_policy')}
    common._local_receipt(args['receipt_path']); marker, _ = fresh_paths(loaded, args)
    core.output_plan(p['output_dir'], p['project_root'], p['receipt_path'], p['expected_document_path'], loaded['pins'], marker)
    if validate_only:
        return dict(status='validated_offline', native_called=False, live_pin_count=len(loaded['pins']),
                    generated_operation_contract=rough.operation_contract(loaded), export_quality_raw=0)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=args['process_id']):
        common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
        registration = common.discover_export_registration(loaded, p['addin_clsid'])
        sw, _ = connect_solidworks(process_id=args['process_id'], launch_new_instance=False, wait_seconds=1)
        typelib = str(Path(registration['addin_path']).parent/'camworks.tlb')
        return export_wip(sw, registration['clsid'], typelib, loaded=loaded, args=args,
                          project_root=p['project_root'], output_dir=p['output_dir'])


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True); parser.add_argument('--validate-only', action='store_true')
    options = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(options.request).read_text(encoding='utf-8-sig')),
                              validate_only=options.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified','issue','marker_path','native_called')}, ensure_ascii=False))
    return 0 if result.get('readback_verified') is True or result.get('status') == 'validated_offline' else 1


if __name__ == '__main__':
    raise SystemExit(main())
