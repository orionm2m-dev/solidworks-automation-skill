"""Pinned, explicitly indexed read-only PROFILE chain diagnostic."""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_mill_profile_headers as headers
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_thread import _object_id, _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_circle_lifecycle_evidence import raw_part_identity
from scripts.sw_cam_mill_qualification import _bootstrap
from scripts.sw_cam_mill_units_qualification import _nonnull
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains, _integer
from scripts.sw_cam_mill_feature_context import _CaptureReadFiles
from scripts.sw_cam_mill_stock_export_evidence import _receipt_bytes, _decode, _require
from scripts.sw_operation_guard import absolute_document_path, check_document_target

MAX_READS = 4096
GUARD_POLICY = 'read_only_events_files_per_getter_identity_per_chain_and_phase'


def validate_profile_indexed_request(*, profile_headers_receipt_path,
        profile_headers_receipt_sha256, index_mapping, **base):
    headers.validate_profile_headers_request(**base)
    if (type(profile_headers_receipt_path) is not str
        or not absolute_document_path(profile_headers_receipt_path)
        or Path(profile_headers_receipt_path).suffix.casefold() != '.json'
        or not Path(profile_headers_receipt_path).is_file()
        or Path(profile_headers_receipt_path).is_symlink()):
        raise ValueError('Pinned absolute headers receipt required')
    if (type(profile_headers_receipt_sha256) is not str or len(profile_headers_receipt_sha256) != 64
        or any(c not in '0123456789abcdef' for c in profile_headers_receipt_sha256)):
        raise ValueError('Strict lowercase header receipt SHA required')
    if Path(profile_headers_receipt_path).resolve() == Path(base['receipt_path']).resolve():
        raise ValueError('Output cannot replace pinned header receipt')
    if type(index_mapping) is not list or not 1 <= len(index_mapping) <= 64:
        raise ValueError('Explicit bounded index/name mapping required')
    for row in index_mapping:
        if (type(row) is not dict or set(row) != {'native_index', 'expected_sketch_name'}
            or type(row['native_index']) is not int or not 0 <= row['native_index'] <= 64
            or type(row['expected_sketch_name']) is not str
            or not 1 <= len(row['expected_sketch_name']) <= 1024):
            raise ValueError('Strict bounded index and exact name required')
    if len({row['native_index'] for row in index_mapping}) != len(index_mapping):
        raise ValueError('Explicit native indices must be unique')
    if len({row['expected_sketch_name'] for row in index_mapping}) != len(index_mapping):
        raise ValueError('Each requested sketch name must have one explicit candidate index')


def load_profile_headers_anchor(path, sha, *, process_id, expected_document_path,
        expected_source_sha256, selected, index_mapping):
    raw, pin = _receipt_bytes(path)
    _require(pin['sha256'] == sha, 'Headers receipt hash differs')
    data = _decode(raw)
    _require(data.get('status') == 'review_required' and data.get('phase') == 'finished',
             'Completed headers receipt required')
    for key in ('read_only', 'profile_read_complete', 'readback_verified',
                'profile_headers_read_complete', 'representation_readback_verified'):
        _require(data.get(key) is True, 'Missing header evidence: '+key)
    for key in ('mutation_attempted', 'AFR_attempted', 'GOP_attempted', 'GTP_attempted',
                'model_saved', 'TechDB_write_attempted', 'post_cleanup_CAM_getters',
                'include_contours', 'profile_geometry_complete'):
        _require(data.get(key) is False, 'Unexpected header state: '+key)
    _require(type(data.get('process_id')) is int and data['process_id'] == process_id,
             'Headers receipt requires the same exact process')
    _require(data.get('saved_file_sha256') == expected_source_sha256, 'Saved source differs')
    doc = data.get('document', {})
    check_document_target(doc.get('path'), doc.get('title'),
                          expected_path=expected_document_path, required=True)
    _require(doc.get('type') == 1 and doc.get('needs_save') is False, 'Clean saved part required')
    _require(data.get('selected') == selected, 'Selected feature context differs from header receipt')
    messages = data.get('messages', {})
    _require(messages.get('subscribed') is True and messages.get('disconnected') is True
             and messages.get('active') is False, 'Clean header event cleanup required')
    _require(not any(messages.get(k) for k in ('event_count', 'overflow', 'callback_errors',
        'callback_error_count', 'subscription_error', 'disconnect_errors')), 'Header event errors')
    before, after = data.get('before'), data.get('after')
    _require(type(before) is dict and before == after and data.get('state_sha256') == _digest(before),
             'Two equal pinned header snapshots required')
    count = _integer(before.get('sketch_count'), 'pinned sketch count', 1, 64)
    names = before.get('sketch_names', {}).get('value')
    _require(type(names) is list and len(names) == count
        and all(type(n) is str and len(n) <= 1024 for n in names), 'Flat observed name list required')
    _require(all(row['expected_sketch_name'] in names for row in index_mapping),
             'Every mapped name must be present in the pinned header list')
    _require(all(row['native_index'] <= count for row in index_mapping),
             'Explicit index exceeds bounded zero-or-one-based candidate range')
    return dict(pin=pin, headers=deepcopy(before), document=deepcopy(doc), names=deepcopy(names))


def check_anchor_files(anchor):
    _, current = _receipt_bytes(anchor['pin']['path'])
    _require(current == anchor['pin'], 'Pinned headers receipt changed')


def _indexed_name(value, expected):
    observed = headers._sketch_names(value, 1)
    matches = ((type(value) is str and value == expected) or
               (type(value) in (list, tuple) and len(value) == 1 and value[0] == expected))
    return observed, matches


def read_profile_indexed_chains(doc, *, selected, index_mapping, anchor, read, typed,
        boundary, diagnostic, progress=lambda: None):
    """Explicit index candidates qualify only this saved context and requested list."""
    out = dict(headers={}, indexed_chains=[], read_complete=False,
        geometric_role_mapping_verified=False, universal_index_base_verified=False,
        physical_geometry_verified=False, units_verified=False)
    diagnostic['state'] = out
    boundary('headers_before')
    out['headers'] = headers.read_profile_feature_headers(doc, selected=selected, read=read,
        typed=typed, diagnostic=diagnostic.setdefault('headers_before', {}), progress=progress)
    if out['headers'] != anchor['headers']:
        raise ValueError('Current PROFILE headers differ from pinned receipt')
    boundary('headers_before_complete')
    found = read(doc, 'GetCWObjectFromID', headers.CW_OBJ_FEAT, selected['feature_native_id'])
    if not isinstance(found, (list, tuple)) or len(found) != 2 or found[1] is not True:
        raise ValueError('Exact feature lookup failed')
    raw = _nonnull(found[0], 'exact feature')
    base = _nonnull(typed(raw, 'ICWFeature'), 'ICWFeature')
    if _object_id(doc, base, read) != selected['feature_native_id']:
        raise ValueError('Exact feature identity changed')
    profile = _nonnull(typed(raw, 'ICWProfileFeature'), 'ICWProfileFeature')
    budget = dict(curves=0, chains=0, islands=0)
    diagnostic['geometry_budget'] = budget
    for mapping in index_mapping:
        index = mapping['native_index']
        boundary('chain_before:'+str(index))
        entry = dict(native_index=index, expected_sketch_name=mapping['expected_sketch_name'], geometric_role='unknown',
            name_matches=False, segment_chain_read_attempted=False, read_complete=False, contour={})
        out['indexed_chains'].append(entry)
        diagnostic.update(index=index, stage='GetSketchNameListAt')
        progress()
        value = read(profile, 'GetSketchNameListAt', index)
        entry['name_return_python_type'] = type(value).__name__
        entry['name_observation'], entry['name_matches'] = _indexed_name(value, entry['expected_sketch_name'])
        progress()
        if not entry['name_matches']:
            raise ValueError('Indexed name differs from corresponding pinned name; no chain call')
        entry['segment_chain_read_attempted'] = True
        progress()
        consumed = False
        def chain_read(obj, method, *args):
            nonlocal consumed
            if obj is profile and method == 'GetSegmentChain':
                if consumed or args:
                    raise ValueError('Exactly one explicit indexed chain lookup required')
                consumed = True
                result = read(obj, method, index)
                entry['chain_return_python_type'] = type(result).__name__
                return _nonnull(result, 'GetSegmentChain result')
            result = read(obj, method, *args)
            if method == 'IGetNextChain':
                boundary('linked_chain_after:'+str(index))
            return result
        def chain_typed(raw, name):
            if name == 'ICWSegChain':
                boundary('linked_chain_before:'+str(index))
            return typed(raw, name)
        detail = dict(state=entry['contour'])
        diagnostic['contour_diagnostic'] = detail
        read_segment_chains(profile, 'GetSegmentChain', read=chain_read, typed=chain_typed,
                            diagnostic=detail, budget=budget)
        if not consumed or entry['contour'].get('status') != 'observed':
            raise ValueError('Complete observed linked segment-chain list required')
        boundary('chain_after:'+str(index))
        entry['read_complete'] = True
        progress()
    boundary('headers_after')
    final = headers.read_profile_feature_headers(doc, selected=selected, read=read, typed=typed,
        diagnostic=diagnostic.setdefault('headers_after', {}), progress=progress)
    if final != anchor['headers']:
        raise ValueError('PROFILE headers changed after indexed reads')
    boundary('headers_after_complete')
    out['read_complete'] = True
    return out


def capture_profile_indexed_chains(sw, app, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, baseline, selected, index_mapping, anchor, check, diagnostic, progress):
    diagnostic.update(native_read_count=0, identity_boundary_count=0, guard_policy=GUARD_POLICY)
    with _CaptureReadFiles(expected_document_path, anchor['pin']['path']) as files:
        def light():
            check()
            files.check()
            check()
        def boundary(label):
            light()
            pid = _member(sw, 'GetProcessID')
            if type(pid) is not int or pid != process_id or raw_part_identity(sw) != baseline:
                raise ValueError('Exact process/document identity changed at chain boundary')
            diagnostic['identity_boundary_count'] += 1
            diagnostic['identity_boundary'] = label
            light()
        def read(obj, name, *args):
            light()
            if diagnostic['native_read_count'] >= MAX_READS:
                raise ValueError('Indexed PROFILE read budget exceeded')
            diagnostic.update(stage=name, native_read_count=diagnostic['native_read_count']+1)
            result = _member(obj, name, *args)
            light()
            return result
        def typed(raw, name):
            light()
            if diagnostic['native_read_count'] >= MAX_READS:
                raise ValueError('Indexed PROFILE read budget exceeded')
            diagnostic.update(stage='QI '+name, native_read_count=diagnostic['native_read_count']+1)
            result = _typed(raw, name, typelib_path)
            light()
            return result
        boundary('capture_before')
        doc = typed(_nonnull(read(app, 'IGetActiveDoc'), 'active CAM document'), 'ICWDoc3')
        result = read_profile_indexed_chains(doc, selected=selected, index_mapping=index_mapping, anchor=anchor,
            read=read, typed=typed, boundary=boundary, diagnostic=diagnostic, progress=progress)
        boundary('capture_after')
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Saved source changed')
        check_anchor_files(anchor)
        return result


def inspect_mill_profile_indexed(sw, clsid, typelib_path, *, process_id, expected_document_path,
        expected_source_sha256, expected_feature_native_id, expected_owner_setup_native_id,
        expected_volume_type, expected_shape, expected_island_count, qualification_only,
        acknowledge_disposable_copy, receipt_path, profile_headers_receipt_path,
        profile_headers_receipt_sha256, index_mapping, message_policy='vendor_default'):
    from scripts.sw_cam_events import CamMessageSession
    report = dict(status='error', phase='preflight', process_id=process_id, read_only=True,
        guard_policy=GUARD_POLICY, identity_checks_batched_at_chain_boundaries=True,
        mutation_attempted=False, AFR_attempted=False, GOP_attempted=False, GTP_attempted=False,
        model_saved=False, TechDB_write_attempted=False, post_cleanup_CAM_getters=False,
        full_inventory_verified=False, selected_chains_read_complete=False, readback_verified=False,
        universal_index_base_verified=False, geometric_role_mapping_verified=False,
        physical_geometry_verified=False, production_qualified=False, may_continue=False,
        apply_eligible=False, units_verified=False, snapshots_diagnostics=[])
    receipt = None
    created = False
    session = None
    def persist():
        if created:
            _write_receipt(receipt, report)
    def identity():
        pid = _member(sw, 'GetProcessID')
        if type(pid) is not int or pid != process_id:
            raise ValueError('Exact process differs')
        doc = raw_part_identity(sw)
        check_document_target(doc['path'], doc['title'], expected_path=expected_document_path, required=True)
        if _file_hash(expected_document_path) != expected_source_sha256:
            raise ValueError('Saved source changed')
        check_anchor_files(anchor)
        return doc
    def check(active=True):
        value = session.summary()
        report['messages'] = value
        if (value.get('subscribed') is not True or (active and value.get('active') is not True)
            or (not active and (value.get('active') is not False or value.get('disconnected') is not True))
            or any(value.get(k) for k in ('event_count','overflow','callback_errors',
                'callback_error_count','subscription_error','disconnect_errors'))):
            raise ValueError('CAM event or cleanup requires stop')
    try:
        validate_profile_indexed_request(process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, expected_feature_native_id=expected_feature_native_id,
            expected_owner_setup_native_id=expected_owner_setup_native_id, expected_volume_type=expected_volume_type,
            expected_shape=expected_shape, expected_island_count=expected_island_count,
            qualification_only=qualification_only, acknowledge_disposable_copy=acknowledge_disposable_copy,
            receipt_path=receipt_path, message_policy=message_policy, index_mapping=index_mapping,
            profile_headers_receipt_path=profile_headers_receipt_path,
            profile_headers_receipt_sha256=profile_headers_receipt_sha256)
        selected = dict(feature_native_id=expected_feature_native_id, owner_setup_native_id=expected_owner_setup_native_id,
            volume_type=expected_volume_type, shape=expected_shape, island_count=expected_island_count, include_contours=False)
        anchor = load_profile_headers_anchor(profile_headers_receipt_path, profile_headers_receipt_sha256,
            process_id=process_id, expected_document_path=expected_document_path,
            expected_source_sha256=expected_source_sha256, selected=selected, index_mapping=index_mapping)
        receipt = Path(receipt_path)
        _write_receipt(receipt, report, create=True)
        created = True
        report.update(selected=selected, index_mapping=index_mapping, header_anchor=anchor['pin'])
        baseline = identity()
        if baseline != anchor['document']:
            raise ValueError('Current document differs from pinned clean headers')
        report.update(document=baseline, saved_file_sha256=expected_source_sha256)
        app = _bootstrap(sw, clsid, typelib_path, expected_document_path)
        if identity() != baseline:
            raise ValueError('Document changed acquiring event host')
        session = CamMessageSession(app, typelib_path)
        with session:
            for phase in ('before', 'after'):
                check()
                report['phase'] = phase
                diagnostic = dict(phase=phase)
                report['snapshots_diagnostics'].append(diagnostic)
                persist()
                report[phase] = capture_profile_indexed_chains(sw, app, typelib_path,
                    process_id=process_id, expected_document_path=expected_document_path,
                    expected_source_sha256=expected_source_sha256, baseline=baseline,
                    selected=selected, index_mapping=index_mapping, anchor=anchor,
                    check=check, diagnostic=diagnostic, progress=persist)
                persist()
                check()
            if report['before'] != report['after']:
                raise ValueError('Indexed PROFILE observations changed between snapshots')
        check(active=False)
        if identity() != baseline:
            raise ValueError('Document changed during cleanup')
        report.update(status='review_required', phase='finished', selected_chains_read_complete=True,
            readback_verified=True, selected_index_name_mapping_verified=True,
            state_sha256=_digest(report['before']),
            reason='REQUESTED_INDEX_NAMES_AND_RAW_CHAIN_READBACK_ONLY_NO_ROLE_OR_MANUFACTURING_QUALIFICATION')
    except Exception as exc:
        report.update(status='error', failed_phase=report['phase'], phase='finished', issue=_error(exc),
            selected_chains_read_complete=False, readback_verified=False, selected_index_name_mapping_verified=False)
    finally:
        if session is not None:
            report['messages'] = session.summary()
        try:
            persist()
        except Exception as exc:
            report.update(status='error', receipt_write_error=_error(exc), selected_chains_read_complete=False,
                          readback_verified=False, selected_index_name_mapping_verified=False)
    return report
