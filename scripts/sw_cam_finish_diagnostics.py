"""Bounded finish-operation diagnostics using caller-owned read/QI callbacks.

No application lookup, COM import, mutation, generation, export or save occurs
here. The caller owns document/process guards and before/after inventories.
GetText is raw operation text, not a documented error message.
"""
import math
from ctypes import _Pointer

IIDS = {'ICWFeature': '{682686E4-3685-11D6-A9AA-00062999E55F}', 'ICWOperation': '{4EDDCA73-325A-11D6-A9A7-00062999E55F}', 'ICWMillOperation': '{4EDDCA74-325A-11D6-A9A7-00062999E55F}', 'ICWNCParam': '{7532C780-3BC4-11D6-A9AF-00062999E55F}', 'ICWFinishMillOp': '{4EDDCA7E-325A-11D6-A9A7-00062999E55F}', 'ICWFinishMillOp3': '{86B3CEBB-97D6-461C-9A0D-E1047D826FBC}', 'ICWDispatchCollection': '{670DD771-2C33-11D6-A9A1-00062999E55F}', 'ICWDoc3': '{EF023226-D383-42DA-84FC-FC9243897FA7}'}
TARGETS = {144: 79, 248: 244}
MAX_AREAS = 16
MAX_READS = 100
FIELDS = {
    'ICWFinishMillOp3': (
        ('ContourMillRestMachMethod', 'long'),
        ('ContourMillRestMachToolType', 'long'),
        ('ContourMillRestMachCutDiameter', 'double'),
        ('ContourMillRestMachEndRadius', 'double'),
        ('ContourMillRestMachPrevAllowance', 'double'),
        ('ContourMillRestMachOverridePrev', 'bool'),
        ('GougeCheck', 'bool'), ('GetToolRadiusLeadInLeadOut', 'bool'),
        ('LeadInOutApplyToAll', 'bool'),
        ('GetIsSingleCutDepth', 'bool'),
        ('GetFirstDepthCut', 'double_bool'), ('GetMaxDepthCut', 'double_bool'),
        ('GetSideCutAmt', 'double_bool'),
    ),
    'ICWFinishMillOp': (('IgnoreAirSegOpt', 'bool'), ('CornerMachOpt', 'bool'),
                        ('DepthProcessOpt', 'long')),
    'ICWNCParam': (('GetTlpComp', 'long'), ('GetCNCComp', 'long')),
}
AREA_MEMBERS = ('IGetAllContainAreas', 'IGetAllAvoidAreas')
ALLOWED_MEMBERS = frozenset(name for fields in FIELDS.values() for name, _ in fields) | frozenset({
    'GetCWObjectID', 'GetText', 'GetRebuildOk', 'IGetNCParam', 'Count', 'Item', *AREA_MEMBERS,
})


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _scalar(value, kind):
    if kind == 'bool':
        _require(type(value) is bool, 'Strict native Boolean required')
    elif kind == 'long':
        _require(type(value) is int and -(2**31) <= value < 2**31, 'Strict native LONG required')
    elif kind == 'double':
        _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e9,
                 'Finite bounded native scalar required')
    elif kind == 'double_bool':
        _require(type(value) in (tuple, list) and len(value) == 2,
                 'Exact DOUBLE then VARIANT_BOOL output pair required')
        return [_scalar(value[0], 'double'), _scalar(value[1], 'bool')]
    elif kind == 'text':
        _require(type(value) is str and len(value) <= 16384, 'Bounded native text required')
    else:
        raise ValueError('Unknown scalar contract')
    return value


def _object_id(doc, value, read, *, required):
    raw = read(doc, 'GetCWObjectID', value)
    _require(type(raw) in (tuple, list) and len(raw) == 2, 'Exact object ID output pair required')
    object_id, supported = raw
    _require(type(supported) is bool, 'Object ID status must be Boolean')
    _require(type(object_id) is int and 0 <= object_id < 2**32, 'Object ID must be ULONG')
    if supported:
        _require(object_id > 0, 'A supported object ID must be positive')
    elif required:
        raise ValueError('Target object ID is unsupported')
    return {'supported': supported, 'native_id': object_id if supported else None}


def _null_pointer(value):
    return value is None or (isinstance(value, _Pointer) and not bool(value))


def _areas(owner, member, doc, read, typed):
    raw = read(owner, member)
    _require(type(raw) in (tuple, list) and len(raw) == 2, 'Exact area OUT-dispatch/retval-BOOL pair required')
    collection, defined = raw
    _require(type(defined) is bool, 'Area-defined status must be Boolean')
    if _null_pointer(collection):
        _require(defined is False, 'Defined areas cannot have a null collection')
        return {'defined': False, 'collection_present': False, 'count': 0, 'items': []}
    owner = typed(collection, 'ICWDispatchCollection')
    count = read(owner, 'Count')
    _require(type(count) is int and 0 <= count <= MAX_AREAS, 'Area collection count outside bound')
    _require(defined or count == 0, 'Undefined area collection contains items')
    items = []
    for index in range(count):
        item = read(owner, 'Item', index)
        _require(not _null_pointer(item), 'Null area collection item')
        items.append({'index': index, **_object_id(doc, item, read, required=False)})
    return {'defined': defined, 'collection_present': True, 'count': count, 'items': items}


def read_finish_diagnostics(operation, feature, doc, *, read, typed):
    """Read only fixed diagnostic fields for144/79 or248/244.

    read(obj, member, *args) and typed(obj, interface_name) must be guarded by
    the caller. Exceptions are propagated; no retry, fallback or mutation.
    """
    calls = 0
    def bounded_read(obj, member, *args):
        nonlocal calls
        _require(member in ALLOWED_MEMBERS, 'Member outside diagnostic whitelist')
        _require(calls < MAX_READS, 'Native read budget exceeded')
        calls += 1
        return read(obj, member, *args)
    def bounded_typed(obj, interface):
        _require(interface in IIDS, 'Interface outside diagnostic whitelist')
        _require(obj is not None, 'Null interface source')
        return typed(obj, interface)
    doc_owner = bounded_typed(doc, 'ICWDoc3')
    op_id = _object_id(doc_owner, operation, bounded_read, required=True)['native_id']
    feat_id = _object_id(doc_owner, feature, bounded_read, required=True)['native_id']
    _require(type(op_id) is int and TARGETS.get(op_id) == feat_id, 'Exact144/79 or248/244 target pair required')
    op = bounded_typed(operation, 'ICWOperation')
    result = {
        'operation_native_id': op_id, 'feature_native_id': feat_id,
        'read_only': True, 'read_complete': False, 'supported_fields_read_complete': False,
        'unobserved_fields': [{'interface': 'ICWObject', 'member': 'GetLock',
            'status': 'not_observed_unsupported_interface',
            'observed_hresult': -2147352568,
            'reason': 'Native QI failed with DISP_E_BADVARTYPE; this interface is excluded without retry.'}],
        'raw_operation_text':
            _scalar(bounded_read(op, 'GetText'), 'text'),
        'text_is_documented_error_message': False,
        'feature_rebuild_ok': _scalar(bounded_read(bounded_typed(feature, 'ICWFeature'), 'GetRebuildOk'), 'bool'),
        'values': {}, 'areas': {}, 'enum_values_decoded': False,
        'geometry_accepted': False, 'production_qualified': False,
    }
    for interface, fields in FIELDS.items():
        source = operation
        if interface == 'ICWNCParam':
            source = bounded_read(bounded_typed(operation, 'ICWMillOperation'), 'IGetNCParam')
        owner = bounded_typed(source, interface)
        result['values'][interface] = {name: _scalar(bounded_read(owner, name), kind) for name, kind in fields}
    for member in AREA_MEMBERS:
        result['areas'][member] = _areas(op, member, doc_owner, bounded_read, bounded_typed)
    result.update(supported_fields_read_complete=True, native_read_count=calls)
    return result


ABI_SPECS = ({'interface': 'ICWFeature', 'member': 'GetRebuildOk', 'native_name': 'GetRebuildOk', 'dispid': 15, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp', 'member': 'IgnoreAirSegOpt', 'native_name': '_get_IgnoreAirSegOpt', 'dispid': 6, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp', 'member': 'CornerMachOpt', 'native_name': '_get_CornerMachOpt', 'dispid': 16, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'GetToolRadiusLeadInLeadOut', 'native_name': 'GetToolRadiusLeadInLeadOut', 'dispid': 125, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'LeadInOutApplyToAll', 'native_name': '_get_LeadInOutApplyToAll', 'dispid': 129, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'GougeCheck', 'native_name': '_get_GougeCheck', 'dispid': 130, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'ContourMillRestMachMethod', 'native_name': '_get_ContourMillRestMachMethod', 'dispid': 141, 'args': ['POINTER(c_int)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'ContourMillRestMachToolType', 'native_name': '_get_ContourMillRestMachToolType', 'dispid': 142, 'args': ['POINTER(c_int)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'ContourMillRestMachCutDiameter', 'native_name': '_get_ContourMillRestMachCutDiameter', 'dispid': 143, 'args': ['POINTER(c_double)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'ContourMillRestMachEndRadius', 'native_name': '_get_ContourMillRestMachEndRadius', 'dispid': 144, 'args': ['POINTER(c_double)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'ContourMillRestMachPrevAllowance', 'native_name': '_get_ContourMillRestMachPrevAllowance', 'dispid': 145, 'args': ['POINTER(c_double)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'ContourMillRestMachOverridePrev', 'native_name': '_get_ContourMillRestMachOverridePrev', 'dispid': 146, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [10]}, {'interface': 'ICWMillOperation', 'member': 'IGetNCParam', 'native_name': 'IGetNCParam', 'dispid': 7, 'args': ['POINTER(POINTER(IDispatch))'], 'paramflags': [10]}, {'interface': 'ICWOperation', 'member': 'IGetAllContainAreas', 'native_name': 'IGetAllContainAreas', 'dispid': 37, 'args': ['POINTER(POINTER(IDispatch))', 'POINTER(VARIANT_BOOL)'], 'paramflags': [2, 10]}, {'interface': 'ICWOperation', 'member': 'IGetAllAvoidAreas', 'native_name': 'IGetAllAvoidAreas', 'dispid': 38, 'args': ['POINTER(POINTER(IDispatch))', 'POINTER(VARIANT_BOOL)'], 'paramflags': [2, 10]}, {'interface': 'ICWOperation', 'member': 'GetText', 'native_name': 'GetText', 'dispid': 73, 'args': ['POINTER(BSTR)'], 'paramflags': [10]}, {'interface': 'ICWNCParam', 'member': 'GetTlpComp', 'native_name': 'GetTlpComp', 'dispid': 17, 'args': ['POINTER(c_int)'], 'paramflags': [10]}, {'interface': 'ICWNCParam', 'member': 'GetCNCComp', 'native_name': 'GetCNCComp', 'dispid': 19, 'args': ['POINTER(c_int)'], 'paramflags': [10]}, {'interface': 'ICWDispatchCollection', 'member': 'Item', 'native_name': 'Item', 'dispid': 0, 'args': ['c_int', 'POINTER(POINTER(IDispatch))'], 'paramflags': [1, 10]}, {'interface': 'ICWDispatchCollection', 'member': 'Count', 'native_name': '_get_Count', 'dispid': 1, 'args': ['POINTER(c_int)'], 'paramflags': [10]}, {'interface': 'ICWDoc3', 'member': 'GetCWObjectID', 'native_name': 'GetCWObjectID', 'dispid': 33, 'args': ['POINTER(IDispatch)', 'POINTER(c_ulong)', 'POINTER(VARIANT_BOOL)'], 'paramflags': [1, 2, 10]}, {'interface': 'ICWFinishMillOp', 'member': 'DepthProcessOpt', 'native_name': '_get_DepthProcessOpt', 'dispid': 19, 'args': ['POINTER(c_int)'], 'paramflags': [10]}, {'interface': 'ICWFinishMillOp3', 'member': 'GetSideCutAmt', 'native_name': 'GetSideCutAmt', 'dispid': 80, 'args': ['POINTER(c_double)', 'POINTER(VARIANT_BOOL)'], 'paramflags': [2, 2]}, {'interface': 'ICWFinishMillOp3', 'member': 'GetFirstDepthCut', 'native_name': 'GetFirstDepthCut', 'dispid': 94, 'args': ['POINTER(c_double)', 'POINTER(VARIANT_BOOL)'], 'paramflags': [2, 2]}, {'interface': 'ICWFinishMillOp3', 'member': 'GetMaxDepthCut', 'native_name': 'GetMaxDepthCut', 'dispid': 96, 'args': ['POINTER(c_double)', 'POINTER(VARIANT_BOOL)'], 'paramflags': [2, 2]}, {'interface': 'ICWFinishMillOp3', 'member': 'GetIsSingleCutDepth', 'native_name': 'GetIsSingleCutDepth', 'dispid': 104, 'args': ['POINTER(VARIANT_BOOL)'], 'paramflags': [2]})


def _check_abi_members(classes, specs, verifier, resolve_type):
    rows = []
    for spec in specs:
        owner = classes[spec['interface']]
        matches = [member for member in owner._methods_ if member.name == spec['native_name']]
        _require(len(matches) == 1, 'Unique native getter required: ' + spec['member'])
        args = tuple(resolve_type(token) for token in spec['args'])
        verifier(matches[0], spec['dispid'], args, tuple(spec['paramflags']))
        rows.append(dict(spec))
    return rows


def audit(typelib_path, generated_pin):
    """Validate installed declarations only; no application connection or QI."""
    from ctypes import POINTER, c_int, c_ulong, c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch, BSTR
    from scripts.sw_cam_comtypes import _load_type_library
    from scripts.sw_cam_face_interfaces import _verify_generated_class
    from scripts.sw_cam_pocket_rough_apply import require_abi
    library = _load_type_library(str(typelib_path))
    classes = {name: _verify_generated_class(getattr(library, name), iid, generated_pin)
               for name, iid in IIDS.items()}
    types = {
        'c_int': c_int,
        'POINTER(c_int)': POINTER(c_int),
        'POINTER(c_ulong)': POINTER(c_ulong),
        'POINTER(c_double)': POINTER(c_double),
        'POINTER(VARIANT_BOOL)': POINTER(VARIANT_BOOL),
        'POINTER(BSTR)': POINTER(BSTR),
        'POINTER(IDispatch)': POINTER(IDispatch),
        'POINTER(POINTER(IDispatch))': POINTER(POINTER(IDispatch)),
    }
    rows = _check_abi_members(classes, ABI_SPECS, require_abi, types.__getitem__)
    return {'scope': 'FINISH_DIAGNOSTIC_GETTER_ABI_V1', 'abi_verified': True,
            'interfaces': dict(IIDS), 'getters': rows, 'application_connections': 0,
            'native_calls': 0, 'native_behavior_qualified': False}
