"""Guarded CAM workpiece material and turning cutting conditions; no save/GTP/DB write.

Values are raw native scalars, never inferred from the CAD display unit. Numeric
writes require a file-backed, hash-bound calibration declaration. That declaration
is caller evidence, not automatic proof of physical process qualification.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from scripts.sw_cam import _error, _member, document_snapshot
from scripts.sw_cam_generation import _typed, _write_receipt
from scripts.sw_cam_turn_feature_attribute import _context, _inventory, _items
from scripts.sw_cam_turn_tool import CamToolStateError, _digest, _identity, _reference, _ref_key
from scripts.sw_operation_guard import absolute_document_path, check_document_target

NUMERIC_FIELDS = frozenset({'SMM', 'MAXRPM', 'SpindleSpeed', 'FPR', 'FPM'})
BOOLEAN_FIELDS = frozenset({'IsSMM', 'IsFPR', 'IsAssociateWithStockMaterial'})
FIELDS = NUMERIC_FIELDS | BOOLEAN_FIELDS | {'Material'}


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('A finite native numeric value is required; bool/string are not numbers')
    return float(value)


def _boolean(value):
    if type(value) is not bool:
        raise ValueError('Native Boolean must be a strict bool')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or '\x00' in value:
        raise ValueError('A nonempty native BSTR of at most 512 characters is required')
    return value


def _read_bstr(value):
    if not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
        raise ValueError('Expected bounded native BSTR')
    return value


def _safe_variant(value, depth=0):
    if depth > 6:
        raise ValueError('Catalogue nesting exceeds bound')
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return _finite(value)
    if isinstance(value, (tuple, list)) and len(value) <= 4096:
        return [_safe_variant(v, depth + 1) for v in value]
    raise ValueError('Unexpected catalogue VARIANT shape')


def _strings(value):
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_strings(x) for x in value)) if value else set()
    return set()


def _bootstrap(sw,clsid,typelib_path,expected_path):
    before=document_snapshot(sw)
    if before is None or before.get('type')!=1 or not before.get('path'):raise ValueError('Active saved part required')
    check_document_target(before['path'],before['title'],expected_path=expected_path,required=True)
    addin=_member(sw,'GetAddInObject',clsid)
    if addin is None:raise ValueError('CAM add-in must already be loaded')
    return _typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)


def _snapshot(sw, clsid, typelib_path, selected, *, check=lambda: None, diagnostics=None):
    diagnostic = {} if diagnostics is None else diagnostics
    def read(obj, name, *args):
        diagnostic['stage'] = name
        check()
        result = _member(obj, name, *args)
        check()
        return result
    before, raw_doc, _part, machine, app = _context(sw, clsid, typelib_path, read)
    file_sha = _file_sha(before['path'])
    check()
    doc = _typed(raw_doc, 'ICWDoc3', typelib_path)
    if read(machine, 'MachType') != 3:
        raise ValueError('This bounded writer requires a native TURN machine (type3)')
    # RPC failure/process loss was observed at this getter; causality is unproven. Never retry.
    unit_record = None
    workpiece = _typed(read(machine, 'IGetWorkpiece'), 'ICWWorkpiece', typelib_path)
    material = _read_bstr(read(workpiece, 'Material'))
    inventory = _inventory(machine, typelib_path, read)
    check()
    groups, handles, identities, uses = [], [], [], []
    operation_ids, tool_ids = [], {}
    catalogue = None
    def native_id(obj):
        raw = read(doc, 'GetCWObjectID', obj)
        if not isinstance(raw, (tuple, list)) or len(raw) != 2:
            raise ValueError('GetCWObjectID must return (ULONG, BOOL)')
        number, success = raw
        if type(number) is not int or not 0 < number <= 4294967295 or success is not True:
            raise ValueError('Positive successful native object identity is required')
        return number
    setups = _items(read(machine, 'IGetEnumOpSetups'), typelib_path, read, limit=512)
    for si, raw_setup in enumerate(setups):
        setup = _typed(raw_setup, 'ICWBaseOpSetup', typelib_path)
        for oi, raw_op in enumerate(_items(read(setup, 'IGetEnumOperations'), typelib_path, read, limit=512 - len(uses))):
            if len(uses) >= 512:
                raise ValueError('Operation count exceeds512')
            op = _typed(raw_op, 'ICWOperation', typelib_path)
            turn_op = _typed(raw_op, 'ICWTurnOperation', typelib_path)
            ref = _reference(dict(setup_index=si, operation_index=oi,
                                  expected_operation_type=read(turn_op, 'OpernType')))
            oid = native_id(op)
            if oid in operation_ids:
                raise ValueError('Duplicate native operation identity')
            operation_ids.append(oid)
            raw_tool = read(op, 'IGetTool')
            if raw_tool is None or not bool(raw_tool):
                raise ValueError('Every operation needs a readable tool for complete material scope')
            tool = _typed(raw_tool, 'ICWTool', typelib_path)
            tid = native_id(tool)
            kind = read(tool, 'ToolType')
            if type(kind) is not int:
                raise ValueError('Tool type must be a strict integer')
            if kind == 15:
                turning = _typed(raw_tool, 'ICWTurnTool', typelib_path)
                subtype = read(turning, 'ToolType')
                if type(subtype) is not int or subtype != 1:
                    diagnostic['unavailable_tool_parameters'] = dict(operation=ref,
                        operation_native_id=oid, tool_native_id=tid, tool_type_raw=kind,
                        turn_tool_type_raw=subtype if type(subtype) in (int, bool, str) else None,
                        status='unavailable', reason='unsupported_turn_tool_subtype')
                    raise CamToolStateError('CAM_CUTTING_TOOL_SUBTYPE_UNAVAILABLE',
                        'Unsupported turning-tool subtype; no subtype-specific cutting getters called')
                param = _typed(read(turning, 'IGetActiveTurnCuttingParam'), 'ICWTurnCuttingParam', typelib_path)
                values = {n: _finite(read(param, 'Get' + n)) for n in sorted(NUMERIC_FIELDS)}
                values.update({n: _boolean(read(param, 'Get' + n)) for n in sorted(BOOLEAN_FIELDS)})
                stock_material = _read_bstr(read(param, 'GetCurrentTurnStockMaterial'))
                if catalogue is None:
                    catalogue = _safe_variant(read(param, 'GetAllStockMaterialsList'))
                group_kind = 'turning'
            else:
                # Generic cutting parameters are inspected so material changes cannot
                # silently alter a drilling tool sharing the same TURN document.
                param = _typed(read(tool, 'IGetActiveCuttingParam'), 'ICWToolCutParam', typelib_path)
                values = {'IsAssociateWithStockMaterial': _boolean(read(tool, 'GetAssociateCuttingParamsToStockMaterial')),
                          'SpindleSpeedRawFalse': _finite(read(param, 'GetSpindleSpeed', False)),
                          'SpindleSpeedRawTrue': _finite(read(param, 'GetSpindleSpeed', True)),
                          'FeedPerTooth': _finite(read(param, 'GetFeedPerTooth')),
                          'ZFeedrate': _finite(read(param, 'GetZFeedrate'))}
                stock_material = _read_bstr(read(param, 'GetMaterialGroupName'))
                group_kind = 'generic_read_only'
            identity = _identity(param)
            gi = next((i for i, ident in enumerate(identities) if identity == ident), None)
            data = {'kind': group_kind, 'values_native': values, 'stock_material_raw': stock_material}
            if gi is None:
                gi = len(groups)
                identities.append(identity)
                groups.append(data)
                handles.append(param)
            elif groups[gi] != data:
                raise ValueError('Shared cutting-param aliases returned inconsistent values')
            prior = tool_ids.get(tid)
            tool_data = (kind, gi)
            if prior is not None and prior != tool_data:
                raise ValueError('Shared tool identity maps to inconsistent type/cutting-param')
            tool_ids[tid] = tool_data
            uses.append({'operation': ref, 'operation_native_id': oid, 'tool_native_id': tid,
                         'tool_type_raw': kind, 'cutting_group': gi})
    target = None
    if selected is not None:
        found = [u for u in uses if u['operation'] == selected]
        if len(found) != 1 or groups[found[0]['cutting_group']]['kind'] != 'turning':
            raise ValueError('Selected operation must reference a verified turning cutting-param')
        target = found[0]['cutting_group']
    after_inventory = _inventory(machine, typelib_path, read)
    check()
    after = document_snapshot(sw)
    check()
    if file_sha != _file_sha(before['path']):
        raise ValueError('Saved file changed during native snapshot')
    if before != after or inventory != after_inventory or read(workpiece, 'Material') != material:
        raise ValueError('Document/inventory/material changed during read')
    state = {'document': before, 'saved_file_sha256': file_sha, 'inventory': inventory, 'unit_record_raw': unit_record, 'unit_record_status': 'unavailable_native_getter_disabled_after_RPC_failure',
             'material_raw': material, 'material_catalogue_raw': catalogue,
             'operation_uses': uses, 'cutting_groups': groups, 'selected_group': target,
             'identity_scope': 'native_ID_and_IUnknown_grouping_current_document_not_persistent_across_reopen'}
    diagnostic['stage'] = 'complete'
    return state, {'app': app, 'workpiece': workpiece, 'parameter': handles[target] if target is not None else None}


def _affected(state, field):
    # IUnknown equality confirms wrapper identity, but different wrappers do not
    # prove distinct vendor storage. Conservatively authorize every document op.
    return [u['operation'] for u in state['operation_uses']]


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def _material_evidence(value, target, expected_path):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('Material apply requires hash-bound catalogue/mapping evidence')
    p = Path(value['path']) if isinstance(value['path'], str) else None
    if p is None or not p.is_absolute() or not p.is_file() or p.suffix.lower() != '.json' or p.stat().st_size > 1048576:
        raise ValueError('Material evidence must be an absolute bounded JSON file')
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != value['sha256']:
        raise ValueError('Material evidence hash differs')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('status') != 'qualified_mapping' or data.get('native_material_name') != target:
        raise ValueError('Exact qualified native material mapping required')
    check_document_target(expected_path, Path(expected_path).name, expected_path=data.get('document_path'), required=True)
    for key in ('required_alloy', 'material_condition', 'mapping_basis'):
        _text(data.get(key))
    source = Path(data['catalogue_source_path']) if isinstance(data.get('catalogue_source_path'), str) else None
    if source is None or not source.is_absolute() or not source.is_file() or _file_sha(source) != data.get('catalogue_source_sha256'):
        raise ValueError('Actual material catalogue source must exist with matching hash')
    names = data.get('verified_native_material_names')
    if not isinstance(names, list) or not 1 <= len(names) <= 4096 or not all(isinstance(x, str) for x in names) or target not in names:
        raise ValueError('Mapping must list the exact observed native material name')
    return {'path': str(p), 'sha256': value['sha256'], 'native_material_name': target,
            'required_alloy': data['required_alloy'], 'material_condition': data['material_condition'],
            'catalogue_source_sha256': data['catalogue_source_sha256'],
            'verification_scope': 'caller_verified_mapping_bound_not_independent_metallurgy_or_TechDB_validation'}


def _unit_evidence(value, field, state, expected_path):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('Numeric writes require exact unit_evidence={path,sha256}')
    p = Path(value['path']) if isinstance(value['path'], str) else None
    digest = value['sha256']
    if p is None or not p.is_absolute() or not p.is_file() or p.suffix.lower() != '.json':
        raise ValueError('Unit evidence must be an existing absolute JSON file')
    if p.stat().st_size > 1048576:
        raise ValueError('Unit evidence exceeds1MiB')
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Unit evidence hash mismatch')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('status') != 'qualified':
        raise ValueError('Unit evidence must explicitly declare qualified status')
    if data.get('interface') != 'ICWTurnCuttingParam' or data.get('field') != field:
        raise ValueError('Unit evidence is for a different interface/field')
    if type(state.get('unit_record_raw')) is not str or not state['unit_record_raw'].strip() or data.get('unit_record_raw') != state['unit_record_raw']:
        raise ValueError('Unit record differs from calibrated evidence')
    check_document_target(expected_path, state['document']['title'], expected_path=data.get('document_path'), required=True)
    _text(data.get('native_unit'))
    _text(data.get('method'))
    # Evidence file must name the actual observed before/after pairs; a Boolean
    # claim alone is deliberately insufficient. Evaluating its physics remains review.
    pairs = data.get('observations')
    if not isinstance(pairs, list) or not 2 <= len(pairs) <= 32:
        raise ValueError('At least2 calibration observations are required')
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {'native', 'interpreted'}:
            raise ValueError('Each observation requires native and interpreted scalars')
        _finite(pair['native']); _finite(pair['interpreted'])
    if len({p['native'] for p in pairs}) < 2:
        raise ValueError('Calibration requires distinct native observations')
    return {'path': str(p), 'sha256': digest, 'native_unit': data['native_unit'],
            'verification_scope': 'caller_calibration_bound_not_independently_certified_by_writer'}


def _verify(before, after, field, value):
    expected = deepcopy(before)
    expected['document']['needs_save'] = after['document']['needs_save']
    if field == 'Material':
        expected['material_raw'] = value
    else:
        expected['cutting_groups'][before['selected_group']]['values_native'][field] = value
    if expected != after:
        raise ValueError('Readback changed beyond the single authorized field; derived changes need explicit review')


def configure_cutting_conditions(sw, clsid, typelib_path, *, expected_document_path,
        action, field, selected_operation=None, value_native=None,
        expected_state_sha256=None, allowed_affected_operations=None,
        unit_evidence=None, material_evidence=None, receipt_path=None, qualification_only, message_policy):
    """Inspect/prepare or apply exactly1 raw cutting scalar / workpiece Material.

    No save, regeneration, machine switch, tool cloning, or TechDB write. Caller
    must save/reopen through existing lifecycle and qualify units before numeric put.
    Material writes require a file-backed native catalogue mapping and no automatic material
    link on any operation tool; all document operations are explicit affected scope.
    """
    from scripts.sw_cam_events import CamMessageSession
    if action not in {'inspect', 'prepare', 'apply'} or field not in FIELDS:
        raise ValueError('Unsupported action/field')
    if qualification_only is not True or message_policy != 'vendor_default':
        raise ValueError('Explicit qualification_only/vendor_default policy required')
    if not isinstance(expected_document_path, str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.lower() != '.sldprt':
        raise ValueError('Exact absolute working SLDPRT path required')
    selected = _reference(selected_operation) if field != 'Material' else None
    if field == 'Material' and selected_operation is not None:
        raise ValueError('Material is whole-workpiece scope, not a selected operation')
    receipt = None
    if action != 'apply':
        if any(x is not None for x in (value_native, expected_state_sha256, allowed_affected_operations, unit_evidence, material_evidence, receipt_path)):
            raise ValueError('Read actions reject mutation inputs')
    else:
        if field != 'Material' and material_evidence is not None:
            raise ValueError('Only Material accepts material_evidence')
        if field in NUMERIC_FIELDS:
            value_native = _finite(value_native)
            if value_native <= 0:
                raise ValueError('Speed/feed must be positive; no automatic zero/off mode')
            if unit_evidence is None:
                raise ValueError('Numeric scalar requires calibration evidence')
        elif field in BOOLEAN_FIELDS:
            value_native = _boolean(value_native)
            if unit_evidence is not None:
                raise ValueError('Boolean field does not accept unit evidence')
        else:
            value_native = _text(value_native)
            if unit_evidence is not None:
                raise ValueError('Material field does not accept unit evidence')
        if not isinstance(expected_state_sha256, str) or len(expected_state_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_state_sha256):
            raise ValueError('Exact prepare fingerprint required')
        if not isinstance(allowed_affected_operations, list) or not (0 if field == 'Material' else 1) <= len(allowed_affected_operations) <= 512:
            raise ValueError('Explicit complete affected-operation list required')
        allowed_affected_operations = [_reference(x) for x in allowed_affected_operations]
        if len({(x['setup_index'], x['operation_index']) for x in allowed_affected_operations}) != len(allowed_affected_operations):
            raise ValueError('Duplicate affected operation')
        receipt = Path(receipt_path) if isinstance(receipt_path, str) else None
        if receipt is None or not receipt.is_absolute() or receipt.suffix.lower() != '.json' or not receipt.parent.is_dir() or receipt.exists() or receipt.is_symlink():
            raise ValueError('New absolute JSON receipt with existing parent required')
    report = {'status': 'started', 'action': action, 'field': field, 'value_native': value_native,
              'mutation_attempted': False, 'native_call_returned': False, 'readback_verified': False,
              'model_saved': False, 'generation_attempted': False, 'database_write_attempted': False,
              'physical_cutting_conditions_qualified': False, 'native_units_independently_verified': False,
              'may_continue': False, 'phase': 'preflight', 'snapshot_diagnostics': [],
              'affected_scope_policy': 'all_document_operations_conservative_vendor_storage_aliases_unproven',
              'post_cleanup_CAM_getters': False}
    if receipt:
        _write_receipt(receipt, report, create=True)
    session = None
    def capture(phase, check=lambda: None):
        diag = {'phase': phase}; report['snapshot_diagnostics'].append(diag)
        return _snapshot(sw, clsid, typelib_path, selected, check=check, diagnostics=diag)
    try:
        session = CamMessageSession(_bootstrap(sw,clsid,typelib_path,expected_document_path), typelib_path)
        def check():
            s = session.summary(); report['messages'] = s
            if not s.get('subscribed') or not s.get('active') or s.get('event_count') or s.get('overflow') or s.get('callback_errors') or s.get('callback_error_count') or s.get('subscription_error') or s.get('disconnect_errors'):
                raise ValueError('Native CAM message or event-transport issue: stop without another native call')
        with session:
            check()
            initial, native = capture('initial', check)
            report['before'] = initial
            file_before = _file_sha(expected_document_path)
            report['saved_file_sha256_before'] = file_before
            check_document_target(initial['document']['path'], initial['document']['title'], expected_path=expected_document_path, required=True)
            if initial['document']['needs_save']:
                raise ValueError('Clean saved working copy required')
            report['state_sha256'] = _digest(initial)
            affected = _affected(initial, field)
            report['affected_operations'] = affected
            generated = [o for o in initial['inventory']['operations'] if o['toolpath_generated'] and
                         any(o['setup_index'] == x['setup_index'] and o['operation_index'] == x['operation_index'] for x in affected)]
            report['affected_generated_operations'] = generated
            links = [i for i, g in enumerate(initial['cutting_groups']) if g['values_native']['IsAssociateWithStockMaterial']]
            report['material_linked_groups'] = links
            report['apply_eligible'] = (bool(affected) or field == 'Material') and not generated and not (field == 'Material' and links)
            if action == 'apply':
                if not report['apply_eligible']:
                    raise ValueError('Generated affected paths, empty scope or automatic material links block this write')
                if report['state_sha256'] != expected_state_sha256:
                    raise ValueError('Prepare fingerprint changed')
                if sorted(allowed_affected_operations, key=_ref_key) != sorted(affected, key=_ref_key):
                    raise ValueError('Affected refs must include exactly all current native parameter aliases')
                if field == 'Material':
                    report['material_evidence'] = _material_evidence(material_evidence, value_native, expected_document_path)
                    old = initial['material_raw']
                else:
                    values = initial['cutting_groups'][initial['selected_group']]['values_native']
                    old = values[field]
                    if field != 'IsAssociateWithStockMaterial' and values['IsAssociateWithStockMaterial']:
                        raise ValueError('Disable automatic stock-material association explicitly before a scalar write')
                if old == value_native:
                    raise ValueError('No-op is already satisfied; no write')
                if field in NUMERIC_FIELDS:
                    report['unit_evidence'] = _unit_evidence(unit_evidence, field, initial, expected_document_path)
                check()
                current, native = capture('pre_write', check)
                if current != initial:
                    raise ValueError('Native state changed immediately before write')
                if field in NUMERIC_FIELDS:
                    if _unit_evidence(unit_evidence, field, initial, expected_document_path) != report['unit_evidence']:
                        raise ValueError('Unit evidence changed before write')
                if field == 'Material' and _material_evidence(material_evidence, value_native, expected_document_path) != report['material_evidence']:
                    raise ValueError('Material evidence changed before write')
                if _file_sha(expected_document_path) != file_before:
                    raise ValueError('Saved file changed before write')
                report.update(phase='native_write', mutation_attempted=True)
                _write_receipt(receipt, report)
                if document_snapshot(sw) != initial['document']:
                    raise ValueError('Active document changed before write')
                check()
                if field == 'Material':
                    setattr(native['workpiece'], 'Material', value_native)
                else:
                    _member(native['parameter'], 'Set' + field, value_native)
                report.update(native_call_returned=True, phase='native_return')
                _write_receipt(receipt, report)
                check()
                after, _ = capture('after_write', check)
                report['after'] = after
                _verify(initial, after, field, value_native)
                report['readback_before_cleanup_verified'] = True
                _write_receipt(receipt, report)
                final, _ = capture('final_subscribed_readback', check)
                report['final_subscribed'] = final
                _verify(initial, final, field, value_native)
                check()
            else:
                final = initial
                report['final_subscribed'] = final
            check()
        summary = session.summary()
        report['messages'] = summary
        if (not summary.get('disconnected') or summary.get('active') or summary.get('event_count')
                or summary.get('overflow') or summary.get('callback_errors') or summary.get('callback_error_count')
                or summary.get('disconnect_errors') or summary.get('subscription_error')):
            raise ValueError('Event cleanup/message state unconfirmed')
        report['phase'] = 'post_cleanup_document_file_check'
        final_doc = document_snapshot(sw)
        file_after = _file_sha(expected_document_path)
        report['document_after_cleanup'] = final_doc
        report['saved_file_sha256_after'] = file_after
        if final_doc != final['document'] or file_after != file_before:
            raise ValueError('Document or saved file changed during cleanup')
        report.update(status='review_required' if action=='apply' else 'ok', phase='finished', readback_verified=action=='apply',
                      reason='CAM_DEFINITION_ONLY_SAVE_REOPEN_AND_PROCESS_QUALIFICATION_REQUIRED')
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                      reason=getattr(exc, 'reason', 'CAM_CUTTING_CONDITION_CHANGE_NOT_CONFIRMED'), issue=_error(exc),
                      failed_phase=report['phase'], phase='finished')
    finally:
        if session is not None:
            report['messages'] = session.summary()
        if receipt:
            try:
                _write_receipt(receipt, report)
            except Exception as exc:
                report.update(status='uncertain', receipt_write_error=_error(exc), readback_verified=False)
    return report
