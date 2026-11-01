"""Bounded read-only baseline for two unplanned shallow guide features.

Reuses the saved fresh-finish checkpoint and existing typed MILL readers.
No definition creation, setters, generation, save, CAD traversal or CL export.
"""
from copy import deepcopy
from pathlib import Path
import re
from scripts import sw_cam_fresh_finish_recipe as checkpoint
from scripts import sw_cam_grouped_face_recipe as group
from scripts import sw_cam_rough_startpoint_read as start
from scripts import sw_cam_chamfer_catalogue_preflight as catalogue
from scripts import sw_cam_rough_entry_parameters as rough
from scripts import sw_cam_read_progress_journal as journal
from scripts import sw_cam_configuration_binding as configuration_binding
from scripts.sw_cam import _member, _error
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require

common = start.common
SCOPE = 'SAVED_SHALLOW_GUIDE_GROUP_READ_V1'
FEATURES = (82, 83)
ORDER = (195, 196, 267, 247, 248, 271, 143, 144, 320)
MAX_CALLS = 1900
PARAMS = {'process_id', 'expected_document_path', 'expected_source_sha256',
    'expected_configuration', 'addin_clsid', 'checkpoint_receipt_path',
    'checkpoint_receipt_sha256', 'module_sha256', 'receipt_path', 'progress_path'}
REBIND_PARAMS = {'session_rebind_receipt_path', 'session_rebind_receipt_sha256'}
GETTERS = start.GETTERS | {'IGetAllDefaultOperations', 'GetTdbIdForDefaultOperation',
    'IGetMachine', 'MachType', 'IGetEnumOpSetups', 'IGetEnumOperations', 'GetActiveConfigurationName'}
INTERFACES = start.INTERFACES | {'ICWDoc3', 'ICWPartDoc', 'ICWMachine', 'ICWBaseOpSetup'}


def expected(loaded):
    state = loaded['state']
    require(tuple(v['native_id'] for v in state['operations']) == ORDER,
        'Exact saved nine-operation order required')
    require(state['document']['needs_save'] is False, 'Saved clean source required')
    features = {}
    for fid in FEATURES:
        rows = [v for v in state['features'] if v['geometry']['native_id'] == fid]
        require(len(rows) == 1 and rows[0]['setup_native_id'] == 69, 'Unique owner69 guide required')
        require(rows[0]['geometry']['suppressed'] is False, 'Unsuppressed guide required')
        require(not any(fid in v['linked_feature_ids'] for v in state['operations']),
            'Guide already has operations; do not reuse an obsolete baseline')
        features[str(fid)] = deepcopy(rows[0]['geometry'])
    reference = next(v for v in state['operations'] if v['native_id'] == 143)
    require(reference['linked_feature_ids'] == [79] and reference['mill_operation_type'] == 0,
        'Exact rough143 reference required')
    return dict(features=features, operation_setups=deepcopy(state['operation_setups']),
        operations=deepcopy(state['operations']))


def read_binding(doc, loaded, *, read, typed):
    wanted = expected(loaded)
    doc_kind = read(doc, 'GetDocType')
    require(type(doc_kind) is int and doc_kind == 1, 'CAM part required')
    machine = typed(read(typed(doc, 'ICWPartDoc'), 'IGetMachine'), 'ICWMachine')
    kind = read(machine, 'MachType')
    require(type(kind) is int and kind == 1, 'MILL machine required')
    out = dict(features={}, operation_setups=[], operations=[])
    handles = {}
    for si, raw_setup in enumerate(_items(read(machine, 'IGetEnumOpSetups'), typed, read, 3)):
        setup = typed(raw_setup, 'ICWBaseOpSetup')
        sid = _object_id(doc, setup, read)
        operations = _items(read(setup, 'IGetEnumOperations'), typed, read, 9)
        out['operation_setups'].append(dict(index=si, native_id=sid, operation_count=len(operations)))
        for oi, raw in enumerate(operations):
            op = typed(raw, 'ICWOperation'); oid = _object_id(doc, op, read)
            require(oid not in handles, 'Duplicate operation identity')
            handles[oid] = raw
            mill = typed(raw, 'ICWMillOperation')
            tool, _ = read_generic_tool(raw, doc, read, typed)
            row = dict(setup_index=si, setup_native_id=sid, operation_index=oi, native_id=oid,
                mill_operation_type=read(mill, 'OpernType'), base_operation_type=read(op, 'OpernType'),
                suppressed=read(op, 'Suppressed'), toolpath_generated=read(op, 'GetIsToolpathGenerated'),
                linked_feature_ids=[_object_id(doc, v, read) for v in _items(read(op, 'IGetAllFeatures'), typed, read, 4)],
                toolpath_record_counts=[read(typed(v, 'ICWToolpath'), 'RecordCount')
                    for v in _items(read(op, 'IGetEnumToolpaths'), typed, read, 4)], assigned_tool=tool)
            out['operations'].append(row)
    for fid in (*FEATURES, 79):
        found = read(doc, 'GetCWObjectFromID', 1, fid)
        require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
            'Exact feature lookup failed')
        header, base = read_header(found[0], doc, read, typed, 69)
        require(header['native_id'] == fid, 'Feature lookup identity differs')
        handles['feature' + str(fid)] = base
        if fid in FEATURES: out['features'][str(fid)] = header
        else:
            reference = next(v['geometry'] for v in loaded['state']['features'] if v['geometry']['native_id'] == 79)
            require(group.exact(header, reference), 'Reference79 header changed')
    require(group.exact(out, wanted), 'Protected order, links, counts, tools or guide headers changed')
    return out, handles


def read_catalogues(feature, *, read, typed):
    mill = typed(feature, 'ICWMillFeature')
    result = []
    for kind in (0, 1):
        row = catalogue.decode_catalogue(read(mill, 'IGetAllDefaultOperations', kind),
            lambda name: read(mill, 'GetTdbIdForDefaultOperation', kind, name))
        row['operation_type'] = kind
        result.append(row)
    return result


def missing_defaults():
    return dict(code='GUIDE_OPERATION_PARAMETERS_NOT_CREATED',
        observed=False, getter_available=False, native_call_attempted=False,
        reason='IGetAllDefaultOperations/GetTdbIdForDefaultOperation return names and IDs only. '
            'The current saved features82/83 have no operations; no qualified default-parameter-object getter exists in the reused modules.',
        next_action='Create the selected definitions with a separately authorized group writer, then read their actual allowance, step, entry and NC values.')


class GroupReadBatch(start.StartPointReadBatch):
    def read(self, obj, name, *args):
        self.reject(name in GETTERS, 'Getter outside grouped read scope')
        limit = 1000 if name == 'GetTdbIdForDefaultOperation' else 128
        for arg in args:
            self.reject(type(arg) is int or (type(arg) is str and len(arg) <= limit and '\x00' not in arg)
                or id(arg) in self._known_objects, 'Argument outside retained graph')
        return self.observed(obj, 'getter', name, lambda: _member(obj, name, *args))

    def typed(self, obj, name):
        self.reject(name in INTERFACES, 'Interface outside grouped read scope')
        cls = (start.interface_class(name, self.typelib_path, self.generated_pin) if name in start.INTERFACES
            else start.pocket.cam_class(name, self.typelib_path, self.generated_pin))
        def query():
            value = obj.QueryInterface(cls)
            require(value is not None and bool(value) and isinstance(value, cls), 'Exact typed CAM pointer required')
            return value
        return self.observed(obj, 'qi', name, query)


def audit_interfaces(typelib, generated):
    from ctypes import HRESULT, POINTER, c_int
    from comtypes import BSTR
    from comtypes.automation import VARIANT
    result = start.audit_interfaces(typelib, generated)
    cls = start.interface_class('ICWMillFeature', typelib, generated)
    for name, dispid, types, flags in (
        ('IGetAllDefaultOperations', 42, (c_int, POINTER(VARIANT)), (1, 10)),
        ('GetTdbIdForDefaultOperation', 43, (c_int, BSTR, POINTER(c_int)), (1, 1, 10))):
        rows = [v for v in cls._methods_ if v.name == name]
        require(len(rows) == 1, 'Unique catalogue method required')
        method = rows[0]
        require(method.restype is HRESULT and int(method.idlflags[0]) == dispid
            and method.argtypes == types and tuple(v[0] for v in method.paramflags) == flags,
            'Exact catalogue ABI differs')
        result['getters'].append(dict(interface='ICWMillFeature', member=name, dispid=dispid,
            paramflags=list(flags), iid=str(cls._iid_).upper()))
    _, result['configuration_binding'] = configuration_binding.abi(typelib, generated)
    return result


class NativeBackend(group.NativeBackend):
    def configuration(self, cam_doc=None):
        self.boundary()
        with self.ctx.guard() as g:
            document = g.read(self.sw, 'ActiveDoc')
            manager = g.read(document, 'ConfigurationManager')
            configuration = g.read(manager, 'ActiveConfiguration')
            name = g.read(configuration, 'Name')
        require(type(name) is str and name == self.args['expected_configuration'], 'Exact SW configuration required')
        result = dict(sw_configuration_name=name)
        if cam_doc is not None:
            cls = configuration_binding._verify_generated_class(
                getattr(configuration_binding._load_type_library(self.typelib_path), 'ICWConfiguration'),
                configuration_binding.EXTRA_INTERFACES['ICWConfiguration'], self.loaded['generated_pin'])
            with self.ctx.guard() as g:
                def typed_config(obj, interface):
                    require(interface == 'ICWConfiguration', 'Only fixed configuration QI allowed')
                    value = g._observe(lambda: obj.QueryInterface(cls))
                    require(value is not None and bool(value) and isinstance(value, cls), 'Exact CAM configuration pointer required')
                    return value
                result = configuration_binding.config_binding(cam_doc, name, read=g.read, typed=typed_config)
                configuration_binding.require_binding(result)
        self.boundary()
        return result

    def observe(self):
        r = self.report; state = dict(member='', returned=False, read_index=0)
        self.configuration()
        with self.ctx.guard() as g:
            doc = g.typed(g.read(self.ctx.app, 'IGetActiveDoc'), 'ICWDoc3')
        r['configuration_before'] = self.configuration(doc)
        def binding():
            require(group.exact(self.configuration(doc), r['configuration_before']), 'CAM configuration binding changed')
            with self.ctx.guard() as g:
                require(g.read(doc, 'GetDocType') == 1, 'Retained CAM part required')
        protected = [self.args['expected_document_path'], self.args['receipt_path']] + [p['path'] for p in self.loaded['pins']]
        with journal.ReadProgressJournal(full_persist=self.persist, progress_path=self.args['progress_path'],
                describe=lambda: dict(state, phase=r['phase']), max_updates=4096, protected_paths=protected) as progress:
            batch = GroupReadBatch(self.sw, self.typelib_path, generated_pin=self.loaded['generated_pin'],
                process_id=self.args['process_id'], expected_document=self.ctx.identity(),
                source_sha256=self.args['expected_source_sha256'], evidence_pins=self.loaded['pins'],
                verify_evidence=self.ctx.files, verify_owned_process=self.ctx.owned, check_events=self.events,
                retained_objects=(doc,), verify_retained_binding=binding, max_native_calls=MAX_CALLS,
                progress=progress.read, progress_state=state)
            try:
                with batch:
                    r['phase'] = 'before_binding'
                    r['before'], handles = read_binding(doc, self.loaded, read=batch.read, typed=batch.typed)
                    r['guides'] = []
                    for fid in FEATURES:
                        r['phase'] = 'catalogue_' + str(fid)
                        r['guides'].append(dict(feature_native_id=fid, header=r['before']['features'][str(fid)],
                            feature_start_is_tool_entry=False, start_coordinate_frame_qualified=False,
                            defaults_catalogue=read_catalogues(handles['feature' + str(fid)], read=batch.read, typed=batch.typed),
                            actual_operation_defaults=missing_defaults()))
                    r['phase'] = 'reference143_parameters'
                    feature = batch.feature_dispatch(handles['feature79'])
                    reference = dict(operation_native_id=143, feature_native_id=79, is_guide_default=False,
                        safe_to_copy_automatically=False)
                    r['reference143'] = reference
                    reference['parameters'] = rough.read_rough_entry_parameters(handles[143], feature,
                        read=batch.read, typed=batch.typed, diagnostic=reference.setdefault('diagnostic', {}))
                    reference['startpoints'] = start.read_startpoints(handles[143], feature, read=batch.read,
                        typed=batch.typed, metadata=batch.metadata, diagnostic=reference.setdefault('startpoint_diagnostic', {}))
                    r['phase'] = 'after_binding'
                    r['after'], _ = read_binding(doc, self.loaded, read=batch.read, typed=batch.typed)
                    require(group.exact(r['before'], r['after']), 'Read baseline changed')
                batch.require_complete(); progress.complete()
            finally: r['read_batch'] = batch.summary()
        r['configuration_after'] = self.configuration(doc)
        require(group.exact(r['configuration_before'], r['configuration_after']), 'CAM/SW configuration changed')


def validate_request(request):
    require(type(request) is dict and set(request) == {'action', 'params'}
        and request['action'] == 'read_shallow_guide_group', 'Exact group read action required')
    p = request['params']
    require(type(p) is dict and set(p) in (PARAMS, PARAMS | REBIND_PARAMS), 'Exact reader parameters and complete optional rebind pair required')
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**31, 'Exact positive PID required')
    require(type(p['expected_configuration']) is str and 0 < len(p['expected_configuration']) <= 256
        and '\x00' not in p['expected_configuration'], 'Explicit current configuration required')
    for key, value in p.items():
        if key.endswith('sha256'): require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value), 'Full SHA256 required')
        if key.endswith('path'): require(type(value) is str and Path(value).is_absolute(), 'Absolute paths required')
    require(p['module_sha256'] == _file_hash(__file__), 'Reader source changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}', p['addin_clsid']),
        'Exact CAM add-in CLSID required')
    return deepcopy(p)


def load_inputs(p):
    if REBIND_PARAMS <= set(p):
        from scripts.sw_cam_fresh_finish_rebind import load_verified_rebind
        loaded = load_verified_rebind(p['session_rebind_receipt_path'], p['session_rebind_receipt_sha256'], p)
    else:
        loaded = checkpoint.load_completed(p['checkpoint_receipt_path'], p['checkpoint_receipt_sha256'],
            **{k: p[k] for k in ('process_id', 'expected_document_path', 'expected_source_sha256')})
    return prepare_loaded(loaded)


def prepare_loaded(loaded):
    """Pin only the existing reader's live closure; keep retired phase proofs."""
    expected(loaded)
    # Completed writer proofs stay checked before/after, outside the per-read live closure.
    retired_names = {'sw_cam_ud14_save.py', 'sw_cam_pocket_finish_apply.py', 'sw_cam_pocket_rough_apply.py',
        'sw_cam_pocket_wall_continue.py', 'sw_cam_wall_outcome.py', 'sw_cam_wall_perimeter_first.py',
        'sw_cam_wall_configuration_save.py', 'sw_cam_fresh_finish_field_batch.py', 'sw_cam_finish_defaults_progress.py',
        'sw_cam_fresh_finish_insert.py', 'sw_cam_chamfer_insert_defaults.py', 'sw_cam_fresh_finish_recipe.py',
        'sw_cam_shared_cutter_geometry.py', 'sw_cam_shared_holder_geometry.py'}
    retired = [v for v in loaded['pins'] if Path(v['path']).name in retired_names]
    loaded['offline_export_proof_pins'] = common._merge(loaded['offline_export_proof_pins'], retired)
    loaded['pins'] = common._merge([v for v in loaded['pins'] if v not in retired],
        [common._pin(v.__file__) for v in (start, start.pocket, start.nc, start.pocket.planes, catalogue, rough, journal, configuration_binding)]
        + [common._pin(__file__), common._pin(Path(checkpoint.__file__).parent / 'sw_cam_pocket_rough_apply.py')])
    require(len(loaded['pins']) <= 64, 'Bounded live dependency closure required')
    common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
    require(_digest(group.current_projection(loaded)) == loaded['current_context_sha256'], 'Saved context changed')
    return loaded


def run_backend(backend, report, persist):
    try:
        backend.start()
        report['before_document'] = backend.ctx.identity()
        backend.observe(); backend.finish()
        report['after_document'] = backend.ctx.identity()
        require(group.exact(report['before_document'], report['after_document']), 'Document changed')
        report.update(status='observed', phase='finished', readback_verified=True, group_baseline_read_complete=True,
            reference_parameter_reads_complete=True)
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], issue=_error(exc), readback_verified=False)
    finally:
        try: backend.close()
        except Exception as exc: report.update(status='error', cleanup_issue=_error(exc), readback_verified=False)
        persist()
    return report


def dispatch_request(request, *, validate_only=False):
    p = validate_request(request); loaded = load_inputs(p)
    registration = common.discover_export_registration(loaded, p['addin_clsid'])
    typelib = str(Path(registration['addin_path']).parent / 'camworks.tlb')
    audit = audit_interfaces(typelib, loaded['generated_pin'])
    loaded['pins'] = common._merge(loaded['pins'], [common._pin(typelib)])
    require(len(loaded['pins']) <= 64, 'Bounded audited dependency closure required')
    receipt = common._local_receipt(p['receipt_path']); progress = Path(p['progress_path'])
    protected = [p['expected_document_path']] + [v['path'] for v in loaded['pins'] + loaded['offline_export_proof_pins'] + loaded['bootstrap_export_pins']]
    keys = {common._key(v) for v in protected}
    require(not receipt.exists() and not receipt.is_symlink() and common._key(receipt) not in keys
        and common._key(progress) not in keys and common._key(receipt) != common._key(progress)
        and progress.suffix.lower() == '.json' and progress.parent.is_dir() and not progress.exists() and not progress.is_symlink(),
        'Fresh distinct output files outside protected inputs required')
    if validate_only:
        return dict(status='validated_offline', native_called=False, selected=expected(loaded), interface_audit=audit,
            live_pin_count=len(loaded['pins']), missing=missing_defaults())
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=p['process_id']):
        common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
        sw, _ = connect_solidworks(process_id=p['process_id'], launch_new_instance=False, wait_seconds=1)
        report = dict(schema_version=1, scope=SCOPE, status='reading', phase='prepared', read_only=True,
            request=deepcopy(p), interface_audit=audit, checkpoint_pin=loaded['parent_pin'],
            ownership=loaded['ownership'], live_pins=loaded['pins'],
            readback_verified=False, group_baseline_read_complete=False, reference_parameter_reads_complete=False,
            guide_operation_parameters_observed=False, mutation_attempted=False,
            save_attempted=False, GTP_attempted=False, production_qualified=False, automatic_retry=False,
            ready_for_mutation=False, full_geometry_reread=False)
        _write_receipt(receipt, report, create=True)
        persist = lambda: _write_receipt(receipt, report)
        backend = NativeBackend(loaded, p, sw, registration['clsid'], typelib, report, persist)
        run_backend(backend, report, persist)
        try:
            common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins']); common._check(loaded['bootstrap_export_pins'])
        except Exception as exc: report.update(status='error', issue=_error(exc), readback_verified=False)
        persist()
        return report
