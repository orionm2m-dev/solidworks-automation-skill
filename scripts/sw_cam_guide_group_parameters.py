"""Read actual parameters of four verified guide definitions in one bounded batch.

Existing MILL readers own all parameter semantics. No insert, setter,
generation, save, physical-tool qualification or manufacturing-unit inference.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_guide_group_definitions as definitions
from scripts import sw_cam_guide_group_reader as guide
from scripts import sw_cam_pocket_pair_read as pocket
from scripts import sw_cam_fresh_finish_field_batch as fields
from scripts import sw_cam_fresh_finish_protected_read as protected
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin, clean_events
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require

common, group = guide.common, guide.group
SCOPE = 'VERIFIED_GUIDE_FOUR_ACTUAL_PARAMETERS_READ_V1'
MAX_CALLS = 1900
PARAMS = guide.PARAMS | guide.REBIND_PARAMS | {'definitions_receipt_path', 'definitions_receipt_sha256'}
GETTERS = guide.GETTERS | pocket.CAM_GETTERS | fields.GETTERS | protected.MEMBERS | set(
    pocket.finish.MILL_TOOL_FIELDS + pocket.finish.HOLDER_FIELDS) | {'IGetMillToolHolder'}
INTERFACES = guide.INTERFACES | pocket.CAM_INTERFACES | fields.INTERFACES | protected.INTERFACES | {
    'ICWMillTool', 'ICWMillToolHolder'}
# Results stay pinned before/after; none of these functions runs in this reader.
OFFLINE_ONLY = {'sw_cam_chamfer_catalogue_preflight.py', 'sw_cam_checkpoint_exports.py',
    'sw_cam_chamfer_exports.py', 'sw_cam_cl_inventory.py', 'sw_cam_ud14_qualification.py',
    'sw_cam_sandvik_phase1.py', 'sw_cam_taper_tool_candidate.py'}


def completed_definitions(r):
    require(r.get('scope') == definitions.SCOPE and r.get('status') == 'observed'
        and r.get('phase') == 'finished' and r.get('readback_verified') is True,
        'Four completed definitions required')
    require(not any(k in r for k in ('issue', 'failed_phase', 'cleanup_issue', 'receipt_write_error')),
        'Partial definition receipt cannot authorize reading')
    for k in ('save_attempted', 'model_saved', 'GTP_attempted', 'tool_assignment_attempted',
              'parameter_setter_attempted', 'automatic_retry', 'native_dispatch_pending'):
        require(r.get(k) is False, 'Unexpected definition side effect: ' + k)
    clean_events(r)
    ids, rows = r['actual_new_ids'], r['plan']['rows']
    require(type(ids) is list and len(ids) == 4 and len(set(ids)) == 4
        and all(type(v) is int and 0 < v < 2**31 for v in ids), 'Four actual unique IDs required')
    require(len(rows) == 4 and [(v['feature_native_id'], v['operation_type']) for v in rows]
        == [(82, 0), (82, 1), (83, 0), (83, 1)], 'Exact guide pairs required')
    require(set(r['actions']) == {v['key'] for v in rows}, 'Exactly four action results required')
    captures = r['captures']
    require(len(captures) == 5 and captures[0]['label'] == 'before'
        and group.exact(captures[0]['binding'], r['before'])
        and group.exact(r['before'], r['plan']['baseline']), 'Exact initial capture required')
    current, anchor, targets = r['before'], 320, []
    for index, (row, oid) in enumerate(zip(rows, ids)):
        action, capture = r['actions'][row['key']], captures[index + 1]
        require(action.get('status') == 'verified' and action.get('attempted') is True
            and action.get('returned') is True and action.get('readback_verified') is True
            and action.get('native_dispatch_pending') is False and action.get('actual_native_id') == oid,
            'Each definition requires verified native return')
        require(capture['label'] == 'after_' + row['key'] and capture['new_operation_native_id'] == oid,
            'Exact capture order required')
        observed = definitions.verify_one_addition(current, capture['binding'], row, oid, anchor)
        require(group.exact(action['observed']['operation'], observed)
            and group.exact(action['observed']['nc'], capture['nc'])
            and capture['nc'].get('read_complete') is True, 'Own NC evidence differs')
        current, anchor = capture['binding'], oid
        targets.append(dict(row, operation_native_id=oid, assigned_tool=deepcopy(observed['assigned_tool'])))
    require(group.exact(current, r['after']), 'Final route differs from four additions')
    doc = r['current_document']
    require(type(doc) is dict and type(doc.get('needs_save')) is bool, 'Exact post-insert document required')
    guide.configuration_binding.require_binding(r['plan']['configuration'])
    return dict(targets=targets, baseline=deepcopy(current), document=deepcopy(doc),
        configuration=deepcopy(r['plan']['configuration']))


def read_tool_dimensions(tool, generic, batch):
    out = dict(generic=deepcopy(generic), mill={}, holder={}, full_profiles_read=False,
        physical_tool_identity_verified=False, holder_clearance_verified=False, native_units_verified=False)
    mill = batch.typed(tool, 'ICWMillTool')
    for name in pocket.finish.MILL_TOOL_FIELDS:
        out['mill'][name] = pocket.rough.bounded_raw_observation(batch.read(mill, name))
    holder = batch.typed(batch.read(tool, 'IGetMillToolHolder'), 'ICWMillToolHolder')
    for name in pocket.finish.HOLDER_FIELDS:
        out['holder'][name] = pocket.rough.bounded_raw_observation(batch.read(holder, name))
    out['dimension_read_complete'] = True
    return out


def read_parameters(doc, handles, targets, batch, report, persist):
    machine = batch.typed(batch.read(batch.typed(doc, 'ICWPartDoc'), 'IGetMachine'), 'ICWMachine')
    setups = _items(batch.read(machine, 'IGetEnumOpSetups'), batch.typed, batch.read, 3)
    selected = [s for s in setups if _object_id(doc, s, batch.read) == 93]
    require(len(selected) == 1, 'Exact operation setup93 required')
    setup, tool_cache = selected[0], {}
    for row in targets:
        oid, fid = row['operation_native_id'], row['feature_native_id']
        report['phase'] = 'parameters_' + str(oid)
        out = dict(operation_native_id=oid, feature_native_id=fid, read_complete=False)
        report.setdefault('parameters', []).append(out); persist()
        found = batch.read(doc, 'GetCWObjectFromID', 1, fid)
        require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
            'Exact retained guide feature lookup required')
        feature, operation = batch.feature_dispatch(found[0]), handles[oid]
        require(_object_id(doc, feature, batch.read) == fid, 'Resolved guide identity differs')
        out['levels'] = pocket.read_levels(operation, feature, read=batch.read,
            typed=batch.typed, feature_dispatch=batch.feature_dispatch)
        if row['operation_type'] == 0:
            out['rough'] = pocket.rough.read_rough_entry_parameters(operation, feature,
                read=batch.read, typed=batch.typed, diagnostic=out.setdefault('rough_diagnostic', {}))
            out['startpoints'] = guide.start.read_startpoints(operation, feature, read=batch.read,
                typed=batch.typed, metadata=batch.metadata, diagnostic=out.setdefault('startpoint_diagnostic', {}))
        else:
            out['finish'] = pocket.read_finish_parameters(operation, feature, read=batch.read, typed=batch.typed)
            out['finish_fields'] = fields.read_cached_fields(batch, operation, feature,
                out.setdefault('finish_field_diagnostic', {}))
            out['protected_finish'] = protected.read_protected(operation, feature, read=batch.read,
                typed=batch.typed, record=lambda key, value: out.setdefault('protected_raw', {}).update(
                    {key: pocket.rough.bounded_raw_observation(value)}))
            out['leads'] = pocket.leads.read_lead_details(operation, feature, read=batch.read,
                typed=batch.typed, lead_typed=lambda raw: batch.typed(raw, 'ICWLeadInOut'))
        out['nc'] = pocket.read_nc_settings(operation, setup, read=batch.read, typed=batch.typed,
            pointer_read=batch.plane, diagnostic=out.setdefault('nc_diagnostic', {}), persist=persist)
        generic, tool = read_generic_tool(operation, doc, batch.read, batch.typed)
        require(group.exact(generic, row['assigned_tool']), 'Assigned tool changed')
        tid = generic['native_id']; reused = tid in tool_cache
        if not reused: tool_cache[tid] = read_tool_dimensions(tool, generic, batch)
        require(group.exact(tool_cache[tid]['generic'], generic), 'Shared tool identity differs')
        out.update(tool=deepcopy(tool_cache[tid]), tool_dimensions_reused=reused, read_complete=True)
        persist()
    require(len(report['parameters']) == 4 and all(r['read_complete'] for r in report['parameters']),
        'Four complete actual parameter groups required')
    report['unique_tool_dimension_reads'] = len(tool_cache)


class ParameterReadBatch(guide.GroupReadBatch):
    def read(self, obj, name, *args):
        self.reject(name in GETTERS, 'Getter outside fixed guide parameter scope')
        for arg in args:
            self.reject(type(arg) is int or id(arg) in self._known_objects, 'Argument outside retained graph')
        return self.observed(obj, 'getter', name, lambda: _member(obj, name, *args))

    def typed(self, obj, name):
        self.reject(name in INTERFACES, 'Interface outside fixed guide parameter scope')
        if name in guide.start.INTERFACES:
            cls = guide.start.interface_class(name, self.typelib_path, self.generated_pin)
        elif name in pocket.CAM_INTERFACES:
            cls = pocket.cam_class(name, self.typelib_path, self.generated_pin)
        else:
            from scripts.sw_cam_comtypes import _interface_class, _INTERFACES
            cls = pocket._verify_generated_class(_interface_class(name, str(self.typelib_path)),
                _INTERFACES[name], self.generated_pin)
        def query():
            value = obj.QueryInterface(cls)
            require(value is not None and bool(value) and isinstance(value, cls), 'Exact typed CAM pointer required')
            return value
        return self.observed(obj, 'qi', name, query)


def make_batch(backend, doc, progress, state, binding):
    return ParameterReadBatch(backend.sw, backend.typelib_path, generated_pin=backend.loaded['generated_pin'],
        process_id=backend.args['process_id'], expected_document=backend.ctx.identity(),
        source_sha256=backend.args['expected_source_sha256'], evidence_pins=backend.loaded['pins'],
        verify_evidence=backend.ctx.files, verify_owned_process=backend.ctx.owned,
        check_events=backend.events, retained_objects=(doc,), verify_retained_binding=binding,
        max_native_calls=MAX_CALLS, progress=progress, progress_state=state)


class NativeBackend(guide.NativeBackend):
    def __init__(self, loaded, args, sw, clsid, typelib_path, report, persist):
        super().__init__(loaded, args, sw, clsid, typelib_path, report, persist)
        # Only the verified receipt authorizes the new RAM dirty state.
        self.ctx.expected_document = deepcopy(loaded['guide_parameters']['document'])

    def observe(self):
        r, selected = self.report, self.loaded['guide_parameters']
        with self.ctx.guard() as g:
            doc = g.typed(g.read(self.ctx.app, 'IGetActiveDoc'), 'ICWDoc3')
        r['configuration_before'] = self.configuration(doc)
        require(group.exact(r['configuration_before'], selected['configuration']), 'Definition configuration differs')
        def binding():
            require(group.exact(self.configuration(doc), selected['configuration']), 'Configuration changed')
        state = dict(member='', returned=False, read_index=0)
        paths = [self.args['expected_document_path'], self.args['receipt_path']] + [v['path'] for v in self.loaded['pins']]
        with pocket.journal.ReadProgressJournal(full_persist=self.persist, progress_path=self.args['progress_path'],
                describe=lambda: dict(state, phase=r['phase']), max_updates=4096, protected_paths=paths) as journal:
            batch = make_batch(self, doc, journal.read, state, binding)
            try:
                with batch:
                    r['before'], handles = definitions.read_current_binding(doc, read=batch.read, typed=batch.typed)
                    require(group.exact(r['before'], selected['baseline']), 'Completed baseline changed')
                    read_parameters(doc, handles, selected['targets'], batch, r, journal.read)
                    r['phase'] = 'after_binding'
                    r['after'], _ = definitions.read_current_binding(doc, read=batch.read, typed=batch.typed)
                    require(group.exact(r['before'], r['after']), 'Protected route changed during reading')
                batch.require_complete(); journal.complete()
            finally: r['read_batch'] = batch.summary(); self.persist()
        r['configuration_after'] = self.configuration(doc)
        require(group.exact(r['configuration_before'], r['configuration_after']), 'Configuration changed after reading')


def run_backend(backend, report, persist):
    report.update(read_only=True, status='reading', phase='starting', mutation_attempted=False,
        save_attempted=False, GTP_attempted=False, automatic_retry=False, readback_verified=False,
        parameter_read_complete=False, production_qualified=False, full_tool_profiles_read=False)
    try:
        backend.start(); report['before_document'] = backend.ctx.identity()
        backend.observe(); backend.finish(); report['after_document'] = backend.ctx.identity()
        require(group.exact(report['before_document'], report['after_document']), 'Document identity changed')
        report.update(status='observed', phase='finished', readback_verified=True, parameter_read_complete=True)
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished', issue=_error(exc),
            readback_verified=False, parameter_read_complete=False)
    finally:
        try: backend.close()
        except Exception as exc: report.update(status='error', cleanup_issue=_error(exc),
            readback_verified=False, parameter_read_complete=False)
        persist()
    return report


def validate_request(request):
    require(type(request) is dict and set(request) == {'action', 'params'}
        and request['action'] == 'read_guide_actual_parameters', 'Exact read-only action required')
    p = deepcopy(request['params'])
    require(type(p) is dict and set(p) == PARAMS, 'Exact read-only request keys required')
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**31, 'Strict owned PID required')
    for key, value in p.items():
        if key.endswith('_path'): require(type(value) is str and Path(value).is_absolute(), 'Absolute path required')
        if key.endswith('_sha256'): require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Exact SHA required')
    require(p['module_sha256'] == _file_hash(__file__), 'Reader source changed')
    return p


def prepare_request(request):
    p = validate_request(request)
    observed, pin = read_pin(p['definitions_receipt_path'], p['definitions_receipt_sha256'])
    selection = completed_definitions(observed)
    require(observed['module_pin'] == common._pin(definitions.__file__), 'Executed definition writer changed')
    for key in ('process_id', 'expected_source_sha256', 'expected_configuration', 'addin_clsid',
                'checkpoint_receipt_sha256', 'session_rebind_receipt_sha256'):
        require(group.exact(observed['request'][key], p[key]), 'Definition lineage differs: ' + key)
    for key in ('expected_document_path', 'checkpoint_receipt_path', 'session_rebind_receipt_path'):
        require(common._key(observed['request'][key]) == common._key(p[key]), 'Definition path differs: ' + key)
    loaded = definitions.rebind.load_verified_rebind(p['session_rebind_receipt_path'], p['session_rebind_receipt_sha256'], p)
    expected_doc = deepcopy(loaded['state']['document']); expected_doc['needs_save'] = selection['document']['needs_save']
    require(group.exact(expected_doc, selection['document']), 'Post-insert identity differs beyond dirty flag')
    require(group.exact(loaded['ownership'], observed['ownership']), 'Owned session changed')
    loaded['guide_parameters'] = selection
    retired = [v for v in loaded['pins'] if Path(v['path']).name in OFFLINE_ONLY]
    loaded['offline_export_proof_pins'] = common._merge(loaded['offline_export_proof_pins'], retired)
    loaded['pins'] = common._merge([v for v in loaded['pins'] if v not in retired], [pin] + [
        common._pin(v) for v in (__file__, definitions.__file__, fields.__file__, protected.__file__, protected.details.__file__, guide.checkpoint.__file__)])
    registration = common.discover_export_registration(loaded, p['addin_clsid'])
    typelib = str(Path(registration['addin_path']).parent / 'camworks.tlb')
    audit = pocket.audit_interfaces(typelib, loaded['generated_pin'])
    audit['protected_finish'] = protected.audit(typelib, loaded['generated_pin'])
    loaded['pins'] = common._merge(loaded['pins'], [common._pin(typelib)])
    require(len(loaded['pins']) <= 64, 'Existing 64-file live guard bound exceeded')
    for name in ('pins', 'offline_export_proof_pins', 'bootstrap_export_pins'): common._check(loaded[name])
    receipt, progress = common._local_receipt(p['receipt_path']), Path(p['progress_path'])
    keys = {common._key(v['path']) for name in ('pins', 'offline_export_proof_pins', 'bootstrap_export_pins')
        for v in loaded[name]} | {common._key(p['expected_document_path'])}
    for path in (receipt, progress):
        require(not path.exists() and not path.is_symlink() and path.parent.is_dir()
            and common._key(path) not in keys, 'Fresh nonaliased output required')
    require(common._key(receipt) != common._key(progress), 'Separate report/progress paths required')
    return p, loaded, registration, typelib, audit, receipt


def dispatch_request(request, *, validate_only=False):
    p, loaded, registration, typelib, audit, receipt = prepare_request(request)
    if validate_only:
        return dict(status='validated_offline', native_called=False, selected=loaded['guide_parameters'],
            live_pin_count=len(loaded['pins']), interface_audit=audit)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=p['process_id']):
        for name in ('pins', 'offline_export_proof_pins', 'bootstrap_export_pins'): common._check(loaded[name])
        sw, _ = connect_solidworks(process_id=p['process_id'], launch_new_instance=False, wait_seconds=1)
        report = dict(scope=SCOPE, request=p, module_pin=common._pin(__file__),
            definitions_pin=common._pin(p['definitions_receipt_path']), ownership=loaded['ownership'],
            live_pins=loaded['pins'], interface_audit=audit)
        _write_receipt(receipt, report, create=True)
        persist = lambda: _write_receipt(receipt, report)
        backend = NativeBackend(loaded, p, sw, registration['clsid'], typelib, report, persist)
        run_backend(backend, report, persist)
        try:
            for name in ('pins', 'offline_export_proof_pins', 'bootstrap_export_pins'): common._check(loaded[name])
        except Exception as exc:
            report.update(status='error', pin_issue=_error(exc), readback_verified=False, parameter_read_complete=False)
        persist(); return report



