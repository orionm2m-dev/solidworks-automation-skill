"""Optional tool observations for an already captured selected MILL plan.

The canonical operation state is never changed. Known detail-reader failures
remain structured partial observations; transport, event, identity and file
failures propagate. No operation generation, tool assignment, save or fallback.
"""
from copy import deepcopy
from types import CodeType
from scripts.sw_cam import _member, _error
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_route_context import integer, read_generic_tool, read_route_operations
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts import sw_cam_mill_tool_geometry as tool_geometry
from scripts import sw_cam_mill_inventory_geometry as contour_geometry

_OPERATION_KEYS = ('operations','operation_setups','operation_counts','operation_count',
                   'operation_setup_count','operation_inventory_scope')


def _codes(fn):
    result = set()
    def visit(code):
        result.add(code)
        for item in code.co_consts:
            if isinstance(item, CodeType):
                visit(item)
    visit(fn.__code__)
    return result


_VALIDATION_CODES = set().union(*(_codes(fn) for fn in (
    tool_geometry.read_full_mill_tool, tool_geometry._integer,
    tool_geometry._scalar, tool_geometry._text,
    contour_geometry.read_segment_chains, contour_geometry._integer,
    contour_geometry._available, tool_geometry._nonnull,
    contour_geometry._strict_integer, contour_geometry._number, contour_geometry._vector)))


def _native_origin(exc, function, obj, name):
    """Match the exact attempted native call, not a guard called around it."""
    frame = exc.__traceback__
    while frame is not None:
        if (frame.tb_frame.f_code is function.__code__
                and frame.tb_frame.f_locals.get('obj') is obj
                and frame.tb_frame.f_locals.get('name') == name):
            return True
        frame = frame.tb_next
    return False


def _partial_category(exc, attempt, callback_exception=None):
    info = _error(exc)
    if attempt is not None:
        kind,obj,name = attempt
        if (kind == 'read' and info.get('type') == 'COMError'
                and info.get('hresult') == -2147467259
                and _native_origin(exc, _member, obj, name)):
            return 'native_tool_getter_E_FAIL'
        if (kind == 'typed' and info.get('code') == 'CAM_COM_NATIVE_QI_FAILED'
                and info.get('bridge_stage') == 'native_query_interface'
                and info.get('error_type') == 'COMError'
                and info.get('hresult') == -2147467262
                and _native_origin(exc, _typed, obj, name)):
            return 'native_tool_interface_E_NOINTERFACE'
    if type(exc) is ValueError and exc is not callback_exception:
        last = exc.__traceback__
        while last is not None and last.tb_next is not None:
            last = last.tb_next
        if last is not None and last.tb_frame.f_code in _VALIDATION_CODES:
            return 'tool_reader_value_validation_failed'
    return None


def read_selected_operation_tool_details(state,native,read,typed,diagnostic,*,
                                         feature_native_id,boundary):
    """Optional capture hook; caller owns native session and guarded callbacks."""
    integer(feature_native_id,'selected feature ID',1)
    if type(diagnostic) is not dict or not callable(boundary):
        raise ValueError('Caller diagnostics and identity boundary required')
    report = dict(scope='selected_operation_tool_details_only',items=[],
        metadata_read_complete=False,profile_complete=False,readback_verified=False,
        generic_operation_context_unchanged=False,canonical_state_changed=False,
        units_verified=False,physical_tool_identity_verified=False,
        holder_clearance_verified=False,production_qualified=False)
    diagnostic['selected_tool_details'] = report
    canonical = deepcopy(state)
    operations = state['operations']
    if type(operations) is not list or len(operations)>32:
        raise ValueError('Bounded canonical operations required')
    selected = [row for row in operations if row['linked_feature_ids']==[feature_native_id]]
    if not operations:
        report.update(status='no_operations',metadata_read_complete=True,
                      generic_operation_context_unchanged=True)
        return report
    if not selected:
        raise ValueError('Selected plan has no exactly linked operation')
    ids=[integer(row['native_id'],'operation ID',1) for row in selected]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate selected operation identities')
    for row in selected:
        boundary()
        oid = row['native_id']
        entry = dict(operation_native_id=oid,mill_operation_type=row['mill_operation_type'],
                     tool_metadata_complete=False,full_tool=None)
        report['items'].append(entry)
        raw = native['operations'][oid]
        if _object_id(native['doc'],raw,read) != oid or row['suppressed'] is not False:
            raise ValueError('Selected operation identity or suppression differs')
        generic,tool = read_generic_tool(raw,native['doc'],read,typed)
        if generic != row['assigned_tool']:
            raise ValueError('Assigned tool changed before detail reading')
        detail = {}
        entry['diagnostic'] = detail
        attempt = None
        callback_exception = None
        def detail_read(obj,name,*args):
            nonlocal attempt, callback_exception
            attempt = ('read',obj,name)
            callback_exception = None
            try:
                return read(obj,name,*args)
            except Exception as exc:
                callback_exception = exc
                raise
        def detail_typed(obj,name):
            nonlocal attempt, callback_exception
            attempt = ('typed',obj,name)
            callback_exception = None
            try:
                return typed(obj,name)
            except Exception as exc:
                callback_exception = exc
                raise
        try:
            full = read_full_mill_tool(tool,generic=generic,read=detail_read,
                                      typed=detail_typed,diagnostic=detail)
            entry.update(status='observed',full_tool=full,
                         tool_metadata_complete=full['geometry_read_complete'])
        except Exception as exc:
            category = _partial_category(exc,attempt,callback_exception)
            if category is None:
                raise
            # The failed native call did not reach its normal post-call guard.
            # Revalidate identity, events and files before retaining a partial read.
            boundary()
            entry.update(status='partial',category=category,issue=_error(exc),
                         full_tool=deepcopy(detail.get('state')))
        boundary()
        repeated,_ = read_generic_tool(raw,native['doc'],read,typed)
        if repeated != generic:
            raise ValueError('Assigned tool changed during detail reading')
    boundary()
    repeated = deepcopy(canonical)
    repeat_native = dict(native)
    read_route_operations(repeated,repeat_native,read,typed,
                          diagnostic=diagnostic.setdefault('operation_details_context_recheck',{}))
    if any(repeated[key] != canonical[key] for key in _OPERATION_KEYS):
        raise ValueError('Sibling operation context changed during tool observations')
    if state != canonical:
        report['canonical_state_changed'] = True
        raise ValueError('Tool hook changed canonical state')
    boundary()
    report['generic_operation_context_unchanged'] = True
    report['metadata_read_complete'] = all(row['tool_metadata_complete'] for row in report['items'])
    report['profile_complete'] = all(row['full_tool'] and row['full_tool'].get('profile_complete') is True
                                     for row in report['items'])
    report['status'] = 'observed' if report['metadata_read_complete'] else 'partial'
    return report
