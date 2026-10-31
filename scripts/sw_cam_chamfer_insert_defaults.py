"""Insert one saved MILL contour definition, observe defaults, and save once.

No explicit tool assignment, parameter setter, toolpath generation or profile
qualification is performed. The caller supplies the feature and anchor IDs.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
from scripts import sw_cam_taper_tool_candidate as base
from scripts import sw_cam_taper_tool_resume as parent
from scripts import sw_cam_grouped_face_recipe as group
from scripts import sw_cam_checkpoint_exports as exports
from scripts import sw_cam_chamfer_catalogue_preflight as catalogue
from scripts import sw_cam_chamfer_defaults as defaults
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _file_hash, _object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_ud14_save import run_one_existing_save
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_read_batch_guard import ScopedCamReadBatch
from scripts.sw_cam_face_interfaces import audit_interfaces

SCOPE = 'SAVED_CONTOUR_DEFAULT_INSERT_V1'
TYPE = 1


def marker_path(source, source_sha256, feature_id, anchor_id):
    key = _digest(dict(scope=SCOPE, source=exports._key(source), source_sha256=source_sha256,
                       feature_native_id=feature_id, anchor_operation_native_id=anchor_id))
    return exports.local_evidence_root() / ('contour_insert_' + key + '.json')


def verify_before(loaded, observed):
    require(group.exact(observed['route'], base.expected_route(loaded)),
            'Current old route differs from saved authority')
    require(group.exact(observed['tools'], loaded['tool_checkpoint']['final_observation']['tools']),
            'Current saved tool catalogue differs')
    require(group.exact(observed['feature'], loaded['cone_observation']['feature']),
            'Current selected feature differs from saved contour')


def verify_added(before, observed, new_id, feature_id, anchor_id):
    require(type(new_id) is int and new_id > 0, 'Actual new positive operation identity required')
    a, b = before['route'], deepcopy(observed['route'])
    old = a['operations']
    require(new_id not in {r['native_id'] for r in old}, 'Returned operation already exists')
    anchors = [r for r in old if r['native_id'] == anchor_id]
    require(len(anchors) == 1, 'Unique anchor required')
    anchor = anchors[0]
    target = [r for r in b['operations'] if r['native_id'] == new_id]
    require(len(target) == 1 and len(b['operations']) == len(old) + 1, 'Exactly one operation addition required')
    row = target[0]
    require(row['setup_native_id'] == anchor['setup_native_id']
        and row['setup_index'] == anchor['setup_index']
        and row['operation_index'] == anchor['operation_index'] + 1
        and type(row['mill_operation_type']) is int and row['mill_operation_type'] == TYPE
        and row['linked_feature_ids'] == [feature_id]
        and row['suppressed'] is False and row['toolpath_generated'] is False
        and row['toolpath_record_counts'] == [], 'Exact ungenerated linked contour after anchor required')
    at = next(i for i, r in enumerate(b['operations']) if r['native_id'] == new_id)
    require(at > 0 and b['operations'][at-1]['native_id'] == anchor_id,
            'New operation must directly follow actual anchor')
    b['operations'].pop(at)
    require(group.exact(b['operations'], old), 'Protected operation rows changed')
    si = anchor['setup_index']
    require(type(b['operation_counts'][si]) is int and b['operation_counts'][si] == a['operation_counts'][si] + 1,
            'Only target setup count may grow')
    b['operation_counts'][si] -= 1
    b['operation_setups'][si]['operation_count'] -= 1
    require(group.exact(b, a), 'Protected settings, units, tool binding or setup changed')
    require(group.exact(observed['tools'], before['tools']), 'Insertion changed local tool catalogue')
    require(group.exact(observed['feature'], before['feature']), 'Insertion changed target feature geometry')
    return deepcopy(row)


class Journal(base.Journal):
    def marker_state(self):
        r = self.report
        return dict(scope=SCOPE, receipt_path=str(self.receipt), source_path=r['source_path'],
            initial_source_sha256=r['initial_source_sha256'], phase=r['phase'],
            feature_native_id=r['feature_native_id'], anchor_operation_native_id=r['anchor_operation_native_id'],
            new_operation_native_id=r.get('new_operation_native_id'), actions=deepcopy(r['actions']),
            readback_verified=r.get('readback_verified', False),
            saved_source_sha256=r.get('saved_source_sha256'), automatic_replay=False)


class DefaultsReadBatch(ScopedCamReadBatch):
    def read(self, obj, name, *args):
        try:
            require(name in defaults.GETTERS | {'QueryInterface'}, 'Getter outside defaults-only scope')
            if name == 'QueryInterface':
                from comtypes.automation import IDispatch
                require(len(args) == 1 and args[0] is IDispatch, 'Only native IDispatch conversion permitted')
            return self._observe_read(obj, 'getter', lambda: _member(obj, name, *args))
        except BaseException:
            self._invalid = True; self._completed = False
            raise

    def typed(self, obj, name):
        try:
            if name == 'IDispatch':
                from comtypes.automation import IDispatch
                return self.read(obj, 'QueryInterface', IDispatch)
            require(name in defaults.INTERFACES, 'Interface outside defaults-only scope')
            return self._observe_read(obj, 'qi', lambda: _typed(obj, name, self.typelib_path))
        except BaseException:
            self._invalid = True; self._completed = False
            raise


class NativeBackend(base.NativeBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inserted_id = None

    def start(self):
        self.report['interface_audit'] = audit_interfaces(
            defaults.INTERFACES | {'ICWMillFeature', 'ICWOperation'},
            self.typelib_path, generated_pin=self.loaded['generated_pin'])
        self.persist()
        require(self.report['interface_audit']['all_resolved'] is True,
                'Every interface must resolve before connection or insertion')
        super().start()

    def selected_feature(self):
        with self.ctx.guard() as g:
            fid = self.args['feature_native_id']
            found = g.read(self.native['doc'], 'GetCWObjectFromID', 1, fid)
            require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
                    'Exact current feature lookup required')
            feature = g.typed(found[0], 'ICWMillFeature')
            require(_object_id(self.native['doc'], feature, g.read) == fid, 'Feature identity changed')
            expected = self.loaded['cone_observation']['feature']
            saved_row = next(r for r in self.loaded['state']['features'] if r['geometry']['native_id'] == fid)
            row, _ = read_header(feature, self.native['doc'], g.read, g.typed, saved_row['setup_native_id'])
            require(group.exact(row, saved_row['geometry']), 'Selected full feature header changed')
            row.update(taper_enabled=g.read(feature, 'Taper'), taper_angle_readback=g.read(feature, 'IGetTaperAngle'))
            # The completed contour payload is reused; this step freshly verifies
            # its header and taper values, not all sketch segments or CAD BRep.
            saved = deepcopy(expected)
            for key, value in row.items():
                if key in saved:
                    require(group.exact(saved[key], value), 'Selected feature header changed: ' + key)
            return feature, saved

    def read_narrow(self, label):
        self.boundary()
        state = deepcopy(self.current_state)
        state['document'] = self.ctx.identity()
        state['saved_file_sha256'] = self.ctx.args['expected_source_sha256']
        diagnostic = dict(phase=label)
        self.report.setdefault('route_header_observations', []).append(diagnostic); self.persist()
        batch = self.capture.cone.ScopedUpperHeaderReadBatch(
            self.sw, self.typelib_path, native_context=self.native, reference_state=state,
            process_id=self.args['process_id'], expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'], evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files, verify_owned_process=self.ctx.owned, check_events=self.events)
        try:
            with batch:
                self.capture.read_route_operations(state, self.native, batch.read, batch.typed,
                    diagnostic=diagnostic, nullable_operation_id=self.inserted_id)
            batch.require_complete()
        finally:
            diagnostic.update(state=deepcopy(state), batch=batch.summary()); self.persist()
        self.current_state = deepcopy(state)
        return dict(state=state, **self.read_settings(label))

    def snapshot(self, label):
        route = self.read_narrow(label)
        _, feature = self.selected_feature()
        result = dict(route=group.NativeBackend.save_projection(self, route),
                      tools=self.catalogue(), feature=feature)
        self.report.setdefault('observations', []).append(dict(label=label, value=deepcopy(result)))
        self.persist()
        return result

    def operation_defaults(self, operation_id, label, feature_native_id=None):
        fid = self.args['feature_native_id'] if feature_native_id is None else feature_native_id
        if feature_native_id is None:
            feature, _ = self.selected_feature()
        else:
            with self.ctx.guard() as g:
                found = g.read(self.native['doc'], 'GetCWObjectFromID', 1, fid)
                require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
                        'Existing anchor feature lookup failed')
                feature = g.typed(found[0], 'ICWMillFeature')
                require(_object_id(self.native['doc'], feature, g.read) == fid, 'Anchor feature ID changed')
        with self.ctx.guard() as g:
            raw = self.native['operations'][operation_id]
            require(_object_id(self.native['doc'], raw, g.read) == operation_id, 'Defaults target identity changed')
        def binding():
            self.events()
            require(_object_id(self.native['doc'], raw, _member) == operation_id,
                    'Retained defaults operation identity changed')
            require(_object_id(self.native['doc'], feature, _member) == fid,
                    'Retained defaults feature identity changed')
            self.events()
        batch = DefaultsReadBatch(self.sw, self.typelib_path,
            process_id=self.args['process_id'], expected_document=self.ctx.identity(),
            source_sha256=self.ctx.args['expected_source_sha256'], evidence_pins=self.loaded['pins'],
            verify_evidence=self.ctx.files, verify_owned_process=self.ctx.owned, check_events=self.events,
            retained_objects=(self.native['doc'], raw, feature), verify_retained_binding=binding,
            max_native_calls=defaults.MAX_NATIVE_CALLS)
        diagnostic = dict(label=label, operation_native_id=operation_id, read={})
        self.report.setdefault('defaults_observations', []).append(diagnostic); self.persist()
        try:
            with batch:
                value = defaults.read_defaults(raw, feature, read=batch.read, typed=batch.typed,
                                               persist=self.persist, diagnostic=diagnostic['read'])
            batch.require_complete()
            return value
        finally:
            diagnostic['batch'] = batch.summary(); self.persist()

    def insert(self, pending):
        from scripts.sw_cam_comtypes import _is_comtypes_pointer
        from comtypes.automation import IDispatch
        feature, _ = self.selected_feature()
        with self.ctx.guard() as g:
            aid = self.args['anchor_operation_native_id']
            raw = self.native['operations'][aid]
            require(_object_id(self.native['doc'], raw, g.read) == aid, 'Insertion anchor identity changed')
            anchor = g.read(raw, 'QueryInterface', IDispatch)
            require(_object_id(self.native['doc'], anchor, g.read) == aid, 'Actual anchor dispatch differs')
            default_id = g.read(feature, 'GetTdbIdForDefaultOperation', TYPE, self.args['default_operation_name'])
            require(type(default_id) is int and default_id == self.args['default_operation_id'],
                    'Selected native TechDB default changed')
            result = g.dispatch_once(lambda: _member(feature, 'InsertOperation', TYPE, default_id, anchor),
                                     persist_pending=pending)
        valid = _is_comtypes_pointer(result) and bool(result)
        self.report['actions']['InsertOperation'].update(returned=True, pending=False,
            native_return_type=type(result).__name__, returned_interface_pointer=valid)
        self.persist()
        require(valid, 'One actual nonnull operation pointer required')
        return result

    def bind_inserted(self, raw):
        with self.ctx.guard() as g:
            oid = _object_id(self.native['doc'], raw, g.read)
        self.inserted_id = oid
        self.report['new_operation_native_id'] = oid; self.persist()
        before = self.loaded['state']
        forbidden = {r['native_id'] for r in before['operations']}
        forbidden |= {r['native_id'] for r in before['feature_setups'] + before['operation_setups']}
        forbidden |= {r['geometry']['native_id'] for r in before['features']}
        forbidden |= {r['native_id'] for r in self.loaded['tool_checkpoint']['final_observation']['tools']}
        require(type(oid) is int and oid > 0 and oid not in forbidden, 'New operation cross-kind identity collision')
        anchor = next(r for r in before['operations'] if r['native_id'] == self.args['anchor_operation_native_id'])
        self.current_state['operation_counts'][anchor['setup_index']] += 1
        return oid


def run_backend(backend, journal, loaded, params):
    r = journal.report
    persist = journal.persist
    try:
        backend.start()
        r['before'] = backend.snapshot('before')
        verify_before(loaded, r['before'])
        aid, fid = params['anchor_operation_native_id'], params['feature_native_id']
        anchor = next(x for x in loaded['state']['operations'] if x['native_id'] == aid)
        require(len(anchor['linked_feature_ids']) == 1, 'One actual anchor feature required for reader preflight')
        r['anchor_reader_preflight'] = backend.operation_defaults(
            aid, 'anchor_reader_preflight', anchor['linked_feature_ids'][0])
        defaults.validate_defaults(r['anchor_reader_preflight'])
        persist()
        raw = backend.insert(lambda: journal.pending('InsertOperation'))
        journal.returned('InsertOperation', raw, pointer=True)
        backend.refresh_dirty()
        new_id = backend.bind_inserted(raw)
        r['new_operation_native_id'] = new_id
        configured = backend.snapshot('inserted')
        r['inserted_observation'] = configured
        r['new_operation'] = verify_added(r['before'], configured, new_id, fid, aid)
        value = backend.operation_defaults(new_id, 'new_defaults')
        defaults.validate_defaults(value)
        r['new_defaults'] = value
        persist()
        expected = dict(observation=configured, defaults=value)
        def capture(label):
            if label == 'before':
                backend.boundary()
                return deepcopy(expected)
            observed = backend.snapshot('saved')
            verify_added(r['before'], observed, new_id, fid, aid)
            final_defaults = backend.operation_defaults(new_id, 'saved_defaults')
            defaults.validate_defaults(final_defaults)
            r.update(final_observation=observed, final_defaults=final_defaults,
                     final_state=deepcopy(backend.current_state))
            persist()
            return dict(observation=observed, defaults=final_defaults)
        def verify(observed):
            require(group.exact(expected, observed), 'Save changed inserted definition or protected observations')
        def save():
            result = backend.save()
            journal.returned('SaveActiveDocument', result)
            return result
        def saved_hash():
            value = backend.saved_hash(r['save_stage'])
            require(value != r['initial_source_sha256'], 'Changed CAM definition must change saved source bytes')
            r['saved_source_sha256'] = value
            persist()
            return value
        r['save_stage'] = {}
        run_one_existing_save(r['save_stage'], capture=capture, verify=verify, guard=backend.boundary,
            claim=lambda: journal.pending('SaveActiveDocument'), persist=persist, save=save, saved_hash=saved_hash)
        backend.finish()
        r.update(status='review_required', phase='finished', readback_verified=True, model_saved=True,
                 exactly_one_operation_inserted=True)
    except Exception as exc:
        r.update(status='uncertain' if r.get('mutation_attempted') else 'error',
                 failed_phase=r['phase'], readback_verified=False, issue=_error(exc))
    finally:
        try:
            backend.close()
        except Exception as exc:
            r.update(status='uncertain', readback_verified=False, cleanup_issue=_error(exc))
        persist()
    return r


def derive_closure(loaded):
    from scripts import sw_cam_chamfer_parent as history
    # The completed parent resume is validated before and after native work.
    # Its native writer is not called by this operation-only step.
    retired = [p for p in loaded['pins'] if Path(p['path']).name == 'sw_cam_taper_tool_resume.py']
    require(len(retired) == 1, 'One completed parent implementation proof required')
    live = exports._merge([p for p in loaded['pins'] if p != retired[0]],
                          [exports._pin(__file__), exports._pin(defaults.__file__)])
    offline = exports._merge(loaded['offline_export_proof_pins'], retired,
        [exports._pin(history.__file__), exports._pin(catalogue.__file__), loaded['tool_source_archive_pin']])
    require(len(live) <= 64, 'Complete live closure exceeds bounded guard')
    exports._check(live); exports._check(offline)
    return live, offline, retired


def load_inputs(params, *, check_current=True):
    from scripts import sw_cam_chamfer_parent as history
    identity = {k: params[k] for k in ('process_id', 'expected_document_path', 'expected_source_sha256')}
    loaded = history.load_historical_resume_parent(params['checkpoint_receipt_path'],
        params['checkpoint_receipt_sha256'], historical_source_path=params['tool_source_archive_path'], **identity)
    if check_current:
        require(_file_hash(params['expected_document_path']) == params['expected_source_sha256'],
                'Current source differs from saved tool checkpoint')
    binding = catalogue.expected_binding(loaded, params)
    old = loaded['tool_checkpoint']
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    cat, _ = read_pin(old['catalogue_pin']['path'], old['catalogue_pin']['sha256'])
    require(cat['readback_verified'] is True and cat['phase_proofs_verified_after_read'] is True
        and cat['before']['feature']['geometry']['native_id'] == params['feature_native_id']
        and cat['before']['anchor']['native_id'] == params['anchor_operation_native_id'],
        'Pinned actual feature/anchor catalogue differs')
    entries = cat['catalogue']['entries']
    require(sum(x['name'] == params['default_operation_name']
                and type(x['default_operation_id']) is int
                and x['default_operation_id'] == params['default_operation_id'] for x in entries) == 1,
            'Exact pinned operation default required')
    live, offline, retired = derive_closure(loaded)
    return dict(loaded, pins=live, offline_export_proof_pins=offline,
                insertion_phase_retired_pins=retired, insertion_binding=binding)


def prepare(params):
    loaded = load_inputs(params)
    marker = marker_path(params['expected_document_path'], params['expected_source_sha256'],
                         params['feature_native_id'], params['anchor_operation_native_id'])
    exports._local_receipt(params['receipt_path'])
    protected = {exports._key(x['path']) for x in loaded['pins'] + loaded['offline_export_proof_pins']}
    protected.add(exports._key(params['expected_document_path']))
    require(not Path(params['receipt_path']).exists() and not Path(params['receipt_path']).is_symlink()
        and not marker.exists() and not marker.is_symlink()
        and exports._key(params['receipt_path']) not in protected and exports._key(marker) not in protected
        and exports._key(params['receipt_path']) != exports._key(marker), 'Fresh distinct local receipt and once-marker required')
    report = dict(schema_version=1, scope=SCOPE, phase='prepared', status='running',
        process_id=params['process_id'], source_path=params['expected_document_path'],
        initial_source_sha256=params['expected_source_sha256'], receipt_path=params['receipt_path'],
        module_pin=exports._pin(__file__), parent_pin=deepcopy(loaded['parent_pin']),
        tool_source_archive_pin=deepcopy(loaded['tool_source_archive_pin']),
        feature_native_id=params['feature_native_id'], anchor_operation_native_id=params['anchor_operation_native_id'],
        default_operation_id=params['default_operation_id'], default_operation_name=params['default_operation_name'],
        current_before=group.current_projection(loaded), current_before_sha256=loaded['current_context_sha256'],
        settings_before=deepcopy(loaded['settings']), generated_face_operation_id=loaded['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(loaded['toolpath_record_counts']),
        local_tool_candidate=deepcopy(loaded['local_tool_candidate']),
        profile_contract=deepcopy(loaded['profile_contract']),
        candidate_qualification=deepcopy(loaded['candidate_qualification']),
        live_pins=deepcopy(loaded['pins']), offline_proof_pins=deepcopy(loaded['offline_export_proof_pins']),
        phase_retired_pins=deepcopy(loaded['insertion_phase_retired_pins']),
        actions={}, mutation_attempted=False, readback_verified=False, model_saved=False,
        assignment_attempted=False, GTP_attempted=False, GOP_attempted=False,
        tool_edit_attempted=False, parameter_edit_attempted=False, automatic_retry=False,
        automatic_replay=False, production_qualified=False, phase_proofs_verified_after_native=False,
        profiles_reused_from_parent=True, full_tool_profile_capture_count=0,
        feature_geometry_scope='saved_contour_plus_fresh_header_and_taper')
    return loaded, report, marker


def make_checkpoint(data):
    current = deepcopy(data['current_before'])
    current.update(state=deepcopy(data['final_state']), source_sha256=data['saved_source_sha256'])
    return dict(current=current, settings=deepcopy(data['settings_before']),
        generated_face_operation_id=data['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(data['toolpath_record_counts']),
        local_tool_candidate=deepcopy(data['local_tool_candidate']), profile_contract=deepcopy(data['profile_contract']),
        candidate_qualification=deepcopy(data['candidate_qualification']),
        inserted_contour=dict(native_id=data['new_operation_native_id'],
            feature_native_id=data['feature_native_id'], anchor_operation_native_id=data['anchor_operation_native_id'],
            operation_type=TYPE, default_operation_id=data['default_operation_id'],
            default_operation_name=data['default_operation_name'], defaults=deepcopy(data['final_defaults']),
            generated=False, explicit_tool_assignment=False, chamfer_recipe_applied=False))


def validate_terminal(data, loaded):
    from scripts.sw_cam_mill_selected_plan_evidence import clean_events
    require(data['scope'] == SCOPE and data['status'] == 'review_required' and data['phase'] == 'finished' and data['readback_verified'] is True
        and data['model_saved'] is True and data['phase_proofs_verified_after_native'] is True
        and data['exactly_one_operation_inserted'] is True, 'Completed saved insertion required')
    require(not any(k in data for k in ('issue','failed_phase','cleanup_issue','phase_proof_error','receipt_write_error')),
            'Uncertain insertion cannot become authority')
    for k in ('assignment_attempted','GTP_attempted','GOP_attempted','tool_edit_attempted',
              'parameter_edit_attempted','automatic_retry','automatic_replay','production_qualified'):
        require(data.get(k) is False, 'Forbidden insertion claim/action: ' + k)
    require(type(data['full_tool_profile_capture_count']) is int and data['full_tool_profile_capture_count'] == 0,
            'No repeated tool-profile qualification permitted in insertion')
    require(group.exact(group.current_projection(loaded),data['current_before'])
        and data['current_before_sha256'] == _digest(data['current_before'])
        and all(group.exact(loaded[k],data[k]) for k in (
            'generated_face_operation_id','toolpath_record_counts','local_tool_candidate',
            'profile_contract','candidate_qualification'))
        and group.exact(loaded['settings'],data['settings_before']), 'Exact saved tool authority required')
    audit = data['interface_audit']
    require(audit['all_resolved'] is True and type(audit['native_query_interface_calls']) is int
        and audit['native_query_interface_calls'] == 0, 'Completed offline interface resolution required')
    verify_before(loaded, data['before'])
    fid, aid, new_id = data['feature_native_id'], data['anchor_operation_native_id'], data['new_operation_native_id']
    for key in ('inserted_observation','final_observation'):
        row = verify_added(data['before'],data[key],new_id,fid,aid)
        require(group.exact(row,data['new_operation']), 'New operation row differs')
    defaults.validate_defaults(data['anchor_reader_preflight'])
    defaults.validate_defaults(data['new_defaults']); defaults.validate_defaults(data['final_defaults'])
    require(group.exact(data['new_defaults'],data['final_defaults']), 'Saved defaults changed')
    require(set(data['actions']) == {'InsertOperation','SaveActiveDocument'}, 'Exact native action inventory required')
    for name, action in data['actions'].items():
        require(action['attempted'] is True and action['returned'] is True and action['pending'] is False,
                'Incomplete native action')
        if name == 'InsertOperation':
            require(action['returned_interface_pointer'] is True, 'Actual operation pointer return required')
        else:
            require(action['native_return_type'] == 'int' and type(action['native_return_value']) is int
                and action['native_return_value'] == 0, 'Strict Save zero required')
    save, transition, sha = data['save_stage'], data['source_transition'], data['saved_source_sha256']
    require(save['save_readback_verified'] is True and save['native_call_returned'] is True
        and save['save_pending'] is False and save['native_return_type'] == 'int'
        and type(save['native_return_value']) is int and save['native_return_value'] == 0
        and type(transition['strict_save_return']) is int and transition['strict_save_return'] == 0
        and sha == save['saved_file_sha256'] == transition['source_after_sha256']
        and transition['source_before_sha256'] == data['initial_source_sha256'] == loaded['source_sha256']
        and sha != data['initial_source_sha256'], 'Changed-source strict Save transition required')
    expected = dict(observation=data['final_observation'],defaults=data['final_defaults'])
    require(group.exact(save['before'],expected) and group.exact(save['after'],expected), 'Save readback projection differs')
    final = data['final_state']
    ref = deepcopy(loaded['state'])
    ref['saved_file_sha256'] = sha; ref['document']['needs_save'] = False
    route = data['final_observation']['route']
    for name in ('operations','operation_counts','operation_setups'):
        ref[name] = deepcopy(route[name])
    ref['operation_count'] += 1
    require(group.exact(final,ref) and group.exact(transition['document'],final['document']),
            'Final current state differs from the one permitted operation addition')
    cp = make_checkpoint(data)
    require(group.exact(data['checkpoint'],cp) and data['checkpoint_sha256'] == _digest(cp), 'Flat checkpoint differs')
    clean_events(data)
    return cp


def execute(sw, clsid, typelib, *, params, loaded, report, marker):
    journal = Journal(report, params['receipt_path'], marker)
    _write_receipt(params['receipt_path'], report, create=True)
    backend = NativeBackend(loaded, params, sw, clsid, typelib, report, journal.persist)
    result = run_backend(backend, journal, loaded, params)
    try:
        exports._check(loaded['offline_export_proof_pins'])
        exports._check(loaded['bootstrap_export_pins'])
        result['phase_proofs_verified_after_native'] = True
        if result.get('readback_verified') is True:
            result['checkpoint'] = make_checkpoint(result)
            result['checkpoint_sha256'] = _digest(result['checkpoint'])
            validate_terminal(result, loaded)
            journal.persist()
            result['marker_pin'] = exports._pin(marker)
            journal.persist()
            require(result['marker_pin']['sha256'] == _file_hash(marker), 'Completed marker must remain stable')
    except Exception as exc:
        result.update(status='uncertain', readback_verified=False,
                      phase_proofs_verified_after_native=False, phase_proof_error=_error(exc))
    journal.persist()
    return result


def load_completed(path, digest, *, process_id, expected_document_path, expected_source_sha256):
    from scripts.sw_cam_mill_selected_plan_evidence import read_pin
    data, receiptpin = read_pin(path, digest)
    require(data['module_pin'] == exports._pin(__file__) and data['process_id'] == process_id
        and exports._key(data['source_path']) == exports._key(expected_document_path)
        and exports._key(data['receipt_path']) == exports._key(path)
        and data['saved_source_sha256'] == expected_source_sha256 == _file_hash(expected_document_path),
        'Current saved contour source/process/runtime differs')
    params = dict(process_id=process_id, expected_document_path=expected_document_path,
        expected_source_sha256=data['initial_source_sha256'],
        checkpoint_receipt_path=data['parent_pin']['path'], checkpoint_receipt_sha256=data['parent_pin']['sha256'],
        tool_source_archive_path=data['tool_source_archive_pin']['path'],
        feature_native_id=data['feature_native_id'], anchor_operation_native_id=data['anchor_operation_native_id'],
        default_operation_id=data['default_operation_id'], default_operation_name=data['default_operation_name'])
    loaded = load_inputs(params, check_current=False)
    require(all(group.exact(loaded[left],data[right]) for left,right in (
        ('pins','live_pins'),('offline_export_proof_pins','offline_proof_pins'),
        ('insertion_phase_retired_pins','phase_retired_pins'),('parent_pin','parent_pin'),
        ('tool_source_archive_pin','tool_source_archive_pin'))), 'Exact parent and phase-closure binding required')
    cp = validate_terminal(data, loaded)
    marker = marker_path(data['source_path'], data['initial_source_sha256'],
                         data['feature_native_id'], data['anchor_operation_native_id'])
    mark, markerpin = read_pin(str(marker), data['marker_pin']['sha256'])
    require(exports._key(marker) == exports._key(data['marker_pin']['path'])
        and group.exact(mark, Journal(data,path,marker).marker_state()), 'Completed insertion marker differs')
    live = exports._merge([p for p in loaded['pins']
        if exports._key(p['path']) != exports._key(data['parent_pin']['path'])], [receiptpin])
    offline = exports._merge(loaded['offline_export_proof_pins'], [data['parent_pin'], markerpin])
    result = dict(cp['current'], pins=live, parent_pin=receiptpin, group_marker_pin=markerpin,
        current_context_sha256=_digest(cp['current']), generated_pin=deepcopy(loaded['generated_pin']),
        settings=deepcopy(cp['settings']), generated_face_operation_id=cp['generated_face_operation_id'],
        toolpath_record_counts=deepcopy(cp['toolpath_record_counts']),
        local_tool_candidate=deepcopy(cp['local_tool_candidate']), profile_contract=deepcopy(cp['profile_contract']),
        candidate_qualification=deepcopy(cp['candidate_qualification']), inserted_contour=deepcopy(cp['inserted_contour']),
        tool_checkpoint=loaded['tool_checkpoint'], operation_checkpoint=data,
        offline_export_proof_pins=offline, bootstrap_export_pins=deepcopy(loaded['bootstrap_export_pins']),
        authority_kind='saved_ungenerated_contour_defaults')
    exports._check(live); exports._check(offline)
    # The existing seven-operation export contract intentionally is not called.
    # This checkpoint proves one extra ungenerated definition, not a new CL/WIP.
    return result


PARAMS = frozenset({
    'process_id','expected_document_path','expected_source_sha256','checkpoint_receipt_path',
    'checkpoint_receipt_sha256','tool_source_archive_path','module_sha256','addin_clsid',
    'feature_native_id','anchor_operation_native_id','default_operation_id','default_operation_name',
    'qualification_only','acknowledge_disposable_copy','acknowledge_machine_scope','message_policy','receipt_path',
})


def validate_request(request):
    require(type(request) is dict and set(request) == {'action','params'}
        and request['action'] == 'insert_contour_defaults', 'Exact bounded contour insertion action required')
    p = request['params']
    require(type(p) is dict and set(p) == PARAMS, 'Exact contour insertion request fields required')
    for key in ('process_id','feature_native_id','anchor_operation_native_id','default_operation_id'):
        require(type(p[key]) is int and 0 < p[key] < 2**31, 'Strict positive identity required')
    require(type(p['default_operation_name']) is str and 0 < len(p['default_operation_name']) <= 1000
        and '\x00' not in p['default_operation_name'], 'Exact bounded native default name required')
    for key, value in p.items():
        if key.endswith('sha256'):
            require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value), 'Strict SHA256 required')
        if key.endswith('path'):
            require(type(value) is str and Path(value).is_absolute(), 'Absolute request path required')
    require(p['module_sha256'] == _file_hash(__file__) and p['qualification_only'] is True
        and p['acknowledge_disposable_copy'] is True and p['acknowledge_machine_scope'] is True
        and p['message_policy'] == 'vendor_default', 'Explicit bounded qualification request required')
    require(type(p['addin_clsid']) is str and re.fullmatch(
        r'\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}',p['addin_clsid']), 'Exact CAM CLSID required')
    return deepcopy(p)


def dispatch_request(request, *, validate_only=False):
    params = validate_request(request)
    loaded, report, marker = prepare(params)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1, process_id=params['process_id']):
        exports._check(loaded['pins']); exports._check(loaded['offline_export_proof_pins'])
        registration = exports.discover_export_registration(loaded,params['addin_clsid'])
        typelib = str(Path(registration['addin_path']).parent / 'camworks.tlb')
        audit = audit_interfaces(defaults.INTERFACES | {'ICWMillFeature','ICWOperation'},typelib,
                                 generated_pin=loaded['generated_pin'])
        if validate_only:
            return dict(status='validated_offline', readback_verified=True, native_called=False,
                        interface_audit=audit, live_pin_count=len(loaded['pins']))
        sw, _ = connect_solidworks(process_id=params['process_id'], launch_new_instance=False, wait_seconds=1)
        report['bootstrap_validation'] = deepcopy(loaded['bootstrap_validation'])
        return execute(sw,registration['clsid'],typelib,params=params,loaded=loaded,report=report,marker=marker)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True)
    parser.add_argument('--validate-only',action='store_true')
    args = parser.parse_args(argv)
    result = dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),
                              validate_only=args.validate_only)
    print(json.dumps({k:result.get(k) for k in ('status','phase','readback_verified',
        'new_operation_native_id','saved_source_sha256','issue')},ensure_ascii=False))
    return 0 if result.get('readback_verified') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
