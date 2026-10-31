"""Bounded callback-only Contour defaults reader; never accesses tool profiles."""
from copy import deepcopy
import math
from scripts.sw_cam_finish_observation import FINISH_BASE_FIELDS, FINISH_V3_FIELDS
from scripts.sw_cam_mill_levels import read_mill_level_values

CHAMFER_FIELDS = ('GetChamferClearance', 'GetChamferType', 'GetChamferAngle')
INTERFACES = frozenset({'ICWFinishMillOp', 'ICWFinishMillOp2', 'ICWFinishMillOp3',
    'ICWMillOperation', 'ICWMillOperation3', 'ICWToolpathParam', 'ICWPosition', 'ICWUnitVector'})
GETTERS = frozenset(FINISH_BASE_FIELDS + FINISH_V3_FIELDS + CHAMFER_FIELDS + (
    'GetPreviousAllowance', 'GetMachiningDepth', 'GetOverrideMachiningDepth',
    'GetMachiningDepthValue', 'GetToolpathParam', 'GetToolpathParameters',
    'GetSetupParameters', 'GetCoordinates'))
BOOL_FIELDS = frozenset({'CleanUpPassOpt', 'BottomFinOpt', 'OverridePrevAllow', 'GetIsChamferMachining'})
INT_FIELDS = frozenset({'SpringPass', 'DepthMethod', 'Ramp', 'CutMethod',
    'PerimeterPassType', 'BottomFinMethod', 'GetContainType', 'GetTypeOfFirstCutZ', 'GetChamferType'})
MAX_NATIVE_CALLS = 45


def require(value, message):
    if not value: raise ValueError(message)


def scalar(name, value):
    if name in BOOL_FIELDS:
        require(type(value) is bool, 'Strict native Boolean required: '+name)
    elif name in INT_FIELDS:
        require(type(value) is int and -(2**31) <= value < 2**31, 'Strict native LONG required: '+name)
    else:
        require(type(value) is float and math.isfinite(value), 'Finite native double required: '+name)
    return value


def validate_defaults(value):
    """Validate saved defaults using the same scalar contract, without callbacks."""
    require(type(value) is dict and set(value) == {'finish','level_state','complete','tool_profile_read',
        'units_verified','enum_meaning_verified','production_qualified'}, 'Exact defaults result shape required')
    require(value['complete'] is True and all(value[k] is False for k in
        ('tool_profile_read','units_verified','enum_meaning_verified','production_qualified')), 'Exact observation flags required')
    expected = set(FINISH_BASE_FIELDS + FINISH_V3_FIELDS + CHAMFER_FIELDS + ('GetPreviousAllowance',))
    require(type(value['finish']) is dict and set(value['finish']) == expected, 'Complete finish fields required')
    for name, raw in value['finish'].items(): scalar(name, raw)
    state = value['level_state']; require(set(state) == {'levels','setup'}, 'Exact level/setup shape required')
    levels = state['levels']
    require(set(levels) == {'machining_depth_native','override_machining_depth','toolpath_parameters',
                          'machining_depth_value_native'}, 'Exact level fields required')
    from scripts.sw_cam_mill_levels import _number, _boolean, _coordinates, _toolpath_parameters
    _number(levels['machining_depth_native']); _boolean(levels['override_machining_depth'])
    scalar('GetMachiningDepthValue', levels['machining_depth_value_native'])
    params = levels['toolpath_parameters']
    keys = ('use_setup_definition_for_top_Z','use_minimum_Z','adjust_feature_height','first_cut_Z_type_raw',
            'use_setup_definition_for_bottom_Z','minimum_Z_native','start_Z_native')
    require(set(params) == set(keys), 'Exact toolpath level parameters required')
    _toolpath_parameters([params[k] for k in keys])
    setup = state['setup']
    require(set(setup) == {'transform_present','transform_matrix_decoded','origin_native','axis_native',
        'axis_magnitude','axis_normalized_for_report_only','native_axis_modified'}, 'Exact setup fields required')
    require(setup['transform_present'] is True and setup['transform_matrix_decoded'] is False
        and setup['native_axis_modified'] is False, 'Setup observation flags differ')
    _coordinates(setup['origin_native']); axis = _coordinates(setup['axis_native'])
    magnitude = math.hypot(*axis)
    require(magnitude > 0 and _number(setup['axis_magnitude']) == magnitude
        and _coordinates(setup['axis_normalized_for_report_only']) == [v/magnitude for v in axis],
        'Saved setup direction proof differs')
    return deepcopy(value)


def read_defaults(operation, feature, *, read, typed, persist, diagnostic):
    """Caller guards every callback, including typed(feature, 'IDispatch').

    IDispatch is standard COM, not a CAM interface-registry entry. The supplied
    typed callback must handle it through a guarded standard QI. No callback
    from read_mill_level_values is executed outside these supplied boundaries.
    """
    require(type(diagnostic) is dict and not diagnostic, 'Fresh defaults diagnostic required')
    result = dict(finish={}, level_state={}, complete=False, tool_profile_read=False,
                  units_verified=False, enum_meaning_verified=False, production_qualified=False)
    diagnostic.update(partial_values=result, calls=[], native_call_count=0, max_native_calls=MAX_NATIVE_CALLS)
    persist()

    def invoke(kind, name, call, decoder=None, interface=False, validator=None):
        require(diagnostic['native_call_count'] < MAX_NATIVE_CALLS, 'Defaults native read budget exhausted')
        row = dict(kind=kind, name=name, attempted=True, returned=False, validated=False)
        diagnostic['calls'].append(row); diagnostic['native_call_count'] += 1; persist()
        try:
            value = call(); row.update(returned=True, return_type=type(value).__name__)
            if interface: require(value is not None and bool(value), 'Non-null defaults interface required')
            if validator: validator(value)
            value = decoder(value) if decoder else value
            row['validated'] = True; persist(); return value
        except Exception as exc:
            row['issue_type'] = type(exc).__name__; persist(); raise

    def as_type(obj, name):
        require(name in INTERFACES or name == 'IDispatch', 'Unexpected defaults interface')
        return invoke('query_interface', name, lambda: typed(obj, name), interface=True)

    def getter(obj, interface_name, name, *args, decoder=None, interface=False, validator=None):
        require(name in GETTERS, 'Unexpected defaults getter')
        return invoke('getter', name, lambda: read(obj, name, *args), decoder, interface, validator)

    dispatch = as_type(feature, 'IDispatch')
    for interface_name, fields in (('ICWFinishMillOp', FINISH_BASE_FIELDS),
                                   ('ICWFinishMillOp2', ('GetPreviousAllowance',)),
                                   ('ICWFinishMillOp3', FINISH_V3_FIELDS + CHAMFER_FIELDS)):
        obj = as_type(operation, interface_name)
        for name in fields:
            args = (dispatch,) if name == 'GetPreviousAllowance' else ()
            result['finish'][name] = getter(obj, interface_name, name, *args,
                decoder=lambda value, name=name: scalar(name, value))
            persist()

    def native_read(label, ignored_call, decoder=None, interface=False, validator=None):
        require(label == 'QueryInterface.IDispatch.feature' and interface is True,
                'Unexpected level-reader native dispatch')
        return dispatch

    read_mill_level_values(feature, operation, native_read=native_read,
                          typed=as_type, getter=getter, report=result['level_state'])
    op3 = as_type(operation, 'ICWMillOperation3')
    result['level_state']['levels']['machining_depth_value_native'] = getter(
        op3, 'ICWMillOperation3', 'GetMachiningDepthValue', dispatch,
        decoder=lambda value: scalar('GetMachiningDepthValue', value))
    require(diagnostic['native_call_count'] == MAX_NATIVE_CALLS, 'Fixed defaults sequence changed')
    result['complete'] = True
    validated = validate_defaults(result)
    diagnostic['read_complete'] = True; persist()
    return validated
