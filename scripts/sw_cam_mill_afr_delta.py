"""Pure bounded empty-baseline MILL AFR delta validation; no application calls."""
from copy import deepcopy
import json
import math
import re
from scripts.sw_cam_profile_sketch import _same_bodies

MAX_SETUPS = 8
MAX_FEATURES = 64
_SETUP_KEYS = {'native_id', 'name', 'feature_count', 'axis_native', 'origin_native', 'origin_type_raw'}
_FEATURE_KEYS = {'setup_index', 'feature_index', 'setup_native_id', 'geometry'}
_OP_SETUP_KEYS = {'index', 'native_id', 'operation_count'}


def _int(value, label, low=0, high=0xFFFFFFFF):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Bounded strict integer required: ' + label)
    return value


def _list(value, label, cap):
    if type(value) is not list or len(value) > cap:
        raise ValueError('Bounded native list required: ' + label)
    return value


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('Finite serializable complete snapshot required') from exc


def _vector(value, label, length):
    if type(value) is not list or len(value) != length or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('Finite numeric vector required: ' + label)


def _validate(state):
    if type(state) is not dict:
        raise ValueError('Complete inventory snapshot required')
    _json(state)
    doc = state.get('document')
    if (type(doc) is not dict or type(doc.get('type')) is not int or doc['type'] != 1 or
            type(doc.get('needs_save')) is not bool or type(doc.get('path')) is not str or not doc['path'] or
            type(doc.get('title')) is not str):
        raise ValueError('Strict saved-part document identity required')
    source = state.get('saved_file_sha256')
    if type(source) is not str or re.fullmatch('[0-9a-f]{64}', source) is None:
        raise ValueError('Exact source SHA required')
    machine = state.get('current_machine')
    if type(machine) is not dict or type(machine.get('machine_type')) is not int or machine['machine_type'] != 1:
        raise ValueError('MILL machine snapshot required')
    for key in ('material_raw', 'stock', 'recognition_options', 'recognition_method', 'mill_catalogue'):
        if key not in state:
            raise ValueError('Required captured context absent: ' + key)
    setups = _list(state.get('feature_setups'), 'feature setups', MAX_SETUPS)
    setup_ids = []
    for row in setups:
        if type(row) is not dict or set(row) != _SETUP_KEYS:
            raise ValueError('Exact captured feature setup fields required')
        setup_ids.append(_int(row['native_id'], 'setup ID', 1))
        _int(row['feature_count'], 'feature count', high=MAX_FEATURES)
        _int(row['origin_type_raw'], 'origin type')
        if type(row['name']) is not str or len(row['name']) > 1024:
            raise ValueError('Bounded setup name required')
        _vector(row['axis_native'], 'setup axis', 3)
        _vector(row['origin_native'], 'setup origin', 3)
    if len(set(setup_ids)) != len(setup_ids):
        raise ValueError('Duplicate feature setup ID')
    features = _list(state.get('features'), 'features', MAX_FEATURES)
    feature_ids = []
    position = 0
    for si, setup in enumerate(setups):
        for fi in range(setup['feature_count']):
            if position >= len(features):
                raise ValueError('Feature inventory shorter than declared setup counts')
            row = features[position]
            if type(row) is not dict or set(row) != _FEATURE_KEYS or type(row.get('geometry')) is not dict:
                raise ValueError('Exact captured feature membership fields required')
            if (_int(row['setup_index'], 'setup index', high=MAX_SETUPS-1) != si or
                    _int(row['feature_index'], 'feature index', high=MAX_FEATURES-1) != fi or
                    _int(row['setup_native_id'], 'feature setup ID', 1) != setup['native_id']):
                raise ValueError('Feature order or setup membership mismatch')
            feature_ids.append(_int(row['geometry'].get('native_id'), 'feature native ID', 1))
            position += 1
    if position != len(features):
        raise ValueError('Feature inventory exceeds declared setup counts')
    if len(set(feature_ids)) != len(feature_ids):
        raise ValueError('Duplicate feature native ID')
    counts = _list(state.get('operation_counts'), 'operation counts', MAX_SETUPS)
    if any(_int(n, 'operation count', high=0) for n in counts):
        raise ValueError('Exactly zero operations required')
    _int(state.get('operation_count'), 'total operation count', high=0)
    if 'operations' in state and state['operations'] != []:
        raise ValueError('Unexpected operation rows')
    op_setups = _list(state.get('operation_setups'), 'operation setups', MAX_SETUPS)
    if len(op_setups) != len(counts):
        raise ValueError('Operation setup/count mismatch')
    op_ids = []
    for index, row in enumerate(op_setups):
        if type(row) is not dict or set(row) != _OP_SETUP_KEYS:
            raise ValueError('Exact empty operation setup fields required')
        if _int(row['index'], 'operation setup index', high=MAX_SETUPS-1) != index:
            raise ValueError('Operation setup order/index mismatch')
        _int(row['operation_count'], 'setup operation count', high=0)
        op_ids.append(_int(row['native_id'], 'operation setup ID', 1))
    all_ids = setup_ids + feature_ids + op_ids
    if len(set(all_ids)) != len(all_ids):
        raise ValueError('Duplicate or cross-kind native identity')
    reference = state.get('sw_reference')
    if type(reference) is not dict or type(reference.get('feature_tree')) is not list:
        raise ValueError('SW feature tree reference required')
    solids = _list(reference.get('solids'), 'solid references', 64)
    if not solids:
        raise ValueError('At least one solid reference required')
    for body in solids:
        if type(body) is not dict or set(body) != {'box_m', 'mass_raw'}:
            raise ValueError('Exact solid fingerprint fields required')
        _vector(body['box_m'], 'body box', 6)
        mass = _list(body['mass_raw'], 'body mass values', 64)
        if len(mass) < 4:
            raise ValueError('Complete native mass fingerprint required')
        _vector(mass, 'body mass values', len(mass))
    visible = _int(state.get('visible_solid_body_count'), 'visible body count', 1, 64)
    total = _int(state.get('all_solid_body_count'), 'all body count', 1, 64)
    if visible != total or total != len(solids):
        raise ValueError('AFR requires all captured solid bodies visible')
    return dict(setup_ids=setup_ids, feature_ids=feature_ids, operation_setup_ids=op_ids)


def validate_empty_afr_baseline(state):
    """Require a clean, completely enumerated empty MILL feature/operation state."""
    summary = _validate(state)
    if state['document']['needs_save'] is not False:
        raise ValueError('AFR baseline must be clean and saved')
    if summary['feature_ids'] or any(row['feature_count'] for row in state['feature_setups']):
        raise ValueError('AFR baseline must contain exactly zero features')
    return summary


def verify_afr_delta(before, after, native_return):
    """Accept only new features/setups with unchanged captured source/context.

    The raw before/after snapshots are never changed. Body mass roundoff is
    compared with the existing _same_bodies rel=1e-10, abs=0 and exact boxes;
    no rolling canonical anchor or broader tolerance is introduced.
    """
    baseline = validate_empty_afr_baseline(before)
    result = _validate(after)
    returned = _int(native_return, 'AFR returned feature count', 1, MAX_FEATURES)
    if returned != len(result['feature_ids']):
        raise ValueError('AFR return differs from actual new feature count')
    old_ids = set(baseline['setup_ids'])
    if [n for n in result['setup_ids'] if n in old_ids] != baseline['setup_ids']:
        raise ValueError('Existing feature setups removed or reordered')
    old_rows = {r['native_id']: r for r in before['feature_setups']}
    for row in after['feature_setups']:
        if row['native_id'] in old_rows:
            expected = deepcopy(old_rows[row['native_id']])
            expected['feature_count'] = row['feature_count']
            if _json(expected) != _json(row):
                raise ValueError('Existing feature setup fields changed')
    old_ops = set(baseline['operation_setup_ids'])
    if [n for n in result['operation_setup_ids'] if n in old_ops] != baseline['operation_setup_ids']:
        raise ValueError('Existing empty operation setups removed or reordered')
    old_op_rows = {r['native_id']: r for r in before['operation_setups']}
    for row in after['operation_setups']:
        if row['native_id'] in old_op_rows:
            expected = deepcopy(old_op_rows[row['native_id']]); expected['index'] = row['index']
            if _json(expected) != _json(row):
                raise ValueError('Existing empty operation setup fields changed')
    if not _same_bodies(before['sw_reference']['solids'], after['sw_reference']['solids']):
        raise ValueError('SW solid fingerprint changed beyond existing mass tolerance')
    expected = deepcopy(before)
    for key in ('features', 'feature_setups', 'operation_setups', 'operation_counts'):
        expected[key] = deepcopy(after[key])
    expected['document']['needs_save'] = after['document']['needs_save']
    expected['sw_reference']['solids'] = deepcopy(after['sw_reference']['solids'])
    if _json(expected) != _json(after):
        raise ValueError('AFR changed captured fields outside permitted feature/setup delta')
    return dict(new_feature_native_ids=list(result['feature_ids']),
        new_setup_native_ids=[n for n in result['setup_ids'] if n not in old_ids],
        new_operation_setup_native_ids=[n for n in result['operation_setup_ids'] if n not in old_ops],
        native_return_feature_count=returned)
