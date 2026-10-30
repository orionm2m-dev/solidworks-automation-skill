"""Reusable raw rough-operation parameter reads for an already-bound caller.

The caller owns PID, document, feature/operation relationship, event subscription,
and file guards. feature_dispatch must be the selected feature's existing
IDispatch obtained under those guards (the existing rough-boundary reader uses
standard QueryInterface for this). This module never discovers another target.
All native access is through the supplied read/typed callbacks.
"""
from copy import deepcopy
from scripts.sw_cam_mill_rough_boundary import _number, _boolean, _tuple, _long, _nonnull

SCOPE = "ROUGH_ENTRY_DEPTH_ALLOWANCE_RAW_READER_V1"
MAX_GETTERS = 31
MAX_QUERIES = 3
MAX_RAW_NODES = 64
MAX_RAW_DEPTH = 4
MAX_RAW_SEQUENCE = 32
MAX_RAW_STRING = 4096
MAX_RAW_TEXT = 8192

# Unit and enum bindings are absent in these saved method contracts.
ENTRY_FIELDS = (
    ("GetEntryExitType", "enum_unbound"),
    ("GetEntryHoleAttr", "string"),
    ("GetRampAngle", "angle"),
    ("GetSpiralRadius", "length"),
    ("GetSpiralPitch", "length"),
    ("GetHoleCentreEntry", "boolean"),
    ("GetEntryLengthAngle", "boolean"),
    ("GetEntryLength", "length"),
    ("GetEntryAngle", "angle"),
    ("GetAutoCorrectEntryLengthAngle", "boolean"),
    ("GetEntryStartPtX", "coordinate_variant"),
    ("GetEntryStartPtY", "coordinate_variant"),
)
DEPTH_FIELDS = (
    ("DepthMethod", "enum_unbound"),
    ("DepthAllow", "length"),
    ("FirstDepthAmt", "length"),
    ("SbsqDepthAmt", "length"),
    ("FinCutAmt", "length"),
    ("GetStartDepth", "percent_pair"),
    ("GetSubsequentDepthAmount", "percent_pair"),
)
BOUNDARY_FIELDS = (
    ("PocketMethod", "enum_unbound"),
    ("SideAllow", "length"),
    ("GetStepOver", "percent_pair"),
    ("GetZAllowance", "length"),
    ("GetContainType", "enum_unbound"),
    ("GetContainAllowance", "length"),
    ("GetXYClearance", "length"),
    ("GetToolDiameterPercent", "percent_scalar"),
)
NC_FIELDS = (
    ("GetClrPlaneUseSetupStatus", "boolean"),
    ("GetRpdPlaneUseSetupStatus", "boolean"),
    ("GetRetractType", "enum_unbound"),
)


def bounded_raw_observation(value):
    """Copy only bounded built-in values; never inspect or stringify COM objects.

    Python shape is retained separately because JSON represents both tuples and
    lists as arrays. These are observation bounds, not coordinate semantics.
    """
    nodes = 0
    text_size = 0

    def visit(item, depth):
        nonlocal nodes, text_size
        nodes += 1
        if nodes > MAX_RAW_NODES or depth > MAX_RAW_DEPTH:
            raise ValueError("Raw observation tree exceeds bounds")
        item_type = type(item)
        shape = dict(python_type=item_type.__name__)
        if item is None or item_type is bool:
            return item, shape
        if item_type is int:
            if not -(2**63) <= item <= 2**64 - 1:
                raise ValueError("Raw observation integer exceeds VARIANT storage bounds")
            return item, shape
        if item_type is float:
            return _number(item), shape
        if item_type is str:
            text_size += len(item)
            if len(item) > MAX_RAW_STRING or text_size > MAX_RAW_TEXT:
                raise ValueError("Raw observation text exceeds bounds")
            return item, shape
        if item_type in (tuple, list):
            if len(item) > MAX_RAW_SEQUENCE:
                raise ValueError("Raw observation sequence exceeds bounds")
            children = [visit(child, depth + 1) for child in item]
            shape.update(length=len(item), items=[child[1] for child in children])
            return [child[0] for child in children], shape
        raise ValueError("Raw observation requires built-in primitive values")

    raw, shape = visit(value, 0)
    return dict(recorded=True, raw=raw, python_shape=shape,
                original_variant_tag_verified=False)


def decode_parameter(value, kind):
    """Validate the documented storage type without inventing engineering units."""
    if kind in ("length", "angle", "percent_scalar"):
        result = dict(raw=_number(value), quantity_from_member_name=kind,
            documented_unit=None, unit_binding_verified=False,
            unit_documentation="Unit/scale not stated in saved SDK method or TLB contract.",
            conversion_performed=False)
    elif kind == "enum_unbound":
        result = dict(raw=_long(value), storage_type="LONG",
            enum_binding_verified=False, confirmed_enum_name=None,
            reason="Method declares LONG; no named enum binding is documented.")
    elif kind == "boolean":
        result = dict(raw=_boolean(value), storage_type="VARIANT_BOOL",
            interpretation="Raw flag only; no additional mode semantics inferred.")
    elif kind == "string":
        if type(value) is not str or len(value)>4096:
            raise ValueError("Bounded native BSTR required")
        result = dict(raw=value, storage_type="BSTR")
    elif kind == "percent_pair":
        pair = _tuple(value,2)
        result = dict(raw=list(pair), is_percent=_boolean(pair[0]), value_native=_number(pair[1]),
            storage_types=["VARIANT_BOOL","DOUBLE"],
            value_mode="percent_flag_set" if pair[0] else "percent_flag_clear",
            documented_unit=None, unit_binding_verified=False,
            percent_reference_basis_verified=False, percent_scale_conversion_performed=False,
            reason="Keep the explicit native percent flag and value together; reference basis and unit conversion are not established.")
    elif kind == "coordinate_variant":
        observed = bounded_raw_observation(value)
        if value is None:
            variant_kind="empty_or_null"
        elif type(value) is bool:
            variant_kind="boolean"
        elif type(value) in (int,float):
            _number(value);variant_kind="numeric"
        elif type(value) is str and len(value)<=4096:
            variant_kind="string"
        elif type(value) is tuple:
            variant_kind="tuple_sequence"
        else:
            raise ValueError("Bounded primitive or tuple coordinate VARIANT required")
        result = dict(raw=observed["raw"], storage_type="VARIANT", observed_variant_kind=variant_kind,
            observed_python_shape=observed["python_shape"], original_variant_tag_verified=False,
            array_element_semantics_verified=False, multiple_out_interpretation=False,
            coordinate_frame_verified=False, coordinate_interpreted=False,
            documented_unit=None, unit_binding_verified=False,
            reason="One VARIANT retval is declared. comtypes may unpack its SAFEARRAY as tuples; exact native tag and element semantics are not observed. No tuple arity, frame/unit, expression or coordinate interpretation.")
    else:
        raise ValueError("Unknown fixed parameter decoder")
    return result


def read_rough_entry_parameters(operation_raw, feature_dispatch, *, read, typed, diagnostic=None):
    """Read bounded parameters only; caller must independently verify the target.

    Existing read/typed callbacks must enforce the caller's retained document,
    exact operation/feature association, and event/file boundaries. This helper
    neither resolves IDs nor grants Save, generation, or machining authorization.
    A supplied diagnostic dictionary retains the completed prefix if a getter
    or type check fails; the original exception is propagated, without retry.
    """
    if not callable(read) or not callable(typed):
        raise ValueError("Existing guarded read and typed callbacks required")
    _nonnull(operation_raw);_nonnull(feature_dispatch)
    if diagnostic is None:diagnostic={}
    if type(diagnostic) is not dict:raise ValueError("Diagnostic dictionary required")
    diagnostic.update(scope=SCOPE,read_complete=False,read_only=True,stage="before_interface",
        native_getter_calls=0,interface_queries=0,observations=[],
        mutation_attempted=False,units_verified=False,coordinate_frame_verified=False,
        enum_bindings_verified=False,rapid_clearance_values_read=False,
        physical_tool_qualified=False,production_qualified=False,may_continue=False)
    result=dict(scope=SCOPE,read_only=True,entry={},depth={},boundary={},nc_flags={},
        native_units_verified=False,coordinate_frame_verified=False,
        enum_bindings_verified=False,engineering_parameters_qualified=False,
        caller_target_binding_required=True,caller_guarded_readback_required=True,
        document_lookup_performed=False,mutation_attempted=False,rapid_clearance_values_read=False,
        production_qualified=False,may_continue=False)
    def query(obj,interface):
        if diagnostic["interface_queries"]>=MAX_QUERIES:raise ValueError("Interface budget exhausted")
        diagnostic.update(stage="interface:"+interface,interface_queries=diagnostic["interface_queries"]+1)
        return _nonnull(typed(obj,interface))
    def observe(obj,member,kind,*params):
        if diagnostic["native_getter_calls"]>=MAX_GETTERS:raise ValueError("Getter budget exhausted")
        row=dict(member=member,attempted=True,returned=False,validated=False)
        diagnostic["observations"].append(row)
        diagnostic.update(stage=member,native_getter_calls=diagnostic["native_getter_calls"]+1)
        value=read(obj,member,*params)
        row.update(returned=True,returned_type=type(value).__name__)
        try:
            row["raw_observation"] = bounded_raw_observation(value)
        except ValueError as exc:
            row["raw_observation"] = dict(recorded=False, reason=str(exc))
            raise
        value=decode_parameter(value,kind)
        row.update(validated=True,value=deepcopy(value))
        return value
    try:
        rough=query(operation_raw,"ICWRghMillOp")
        for member,kind in ENTRY_FIELDS:
            result["entry"][member]=observe(rough,member,kind,feature_dispatch)
        for member,kind in DEPTH_FIELDS:
            result["depth"][member]=observe(rough,member,kind)
        for member,kind in BOUNDARY_FIELDS:
            params=(feature_dispatch,) if member=="GetToolDiameterPercent" else ()
            result["boundary"][member]=observe(rough,member,kind,*params)
        mill=query(operation_raw,"ICWMillOperation")
        # This no-argument retval contract is separate from the pointer-only plane getters.
        diagnostic.update(stage="IGetNCParam",native_getter_calls=diagnostic["native_getter_calls"]+1)
        row=dict(member="IGetNCParam",attempted=True,returned=False,validated=False)
        diagnostic["observations"].append(row)
        nc_raw=read(mill,"IGetNCParam");row.update(returned=True)
        nc=query(nc_raw,"ICWNCParam");row["validated"]=True
        for member,kind in NC_FIELDS:
            result["nc_flags"][member]=observe(nc,member,kind)
        result["gaps"]=[
            dict(code="NC_PLANE_POINTER_BINDING_NOT_QUALIFIED",
                interface="ICWNCParam",members=["GetRpdPlnPrms","GetClrPlanePrms"],
                method_contract="HRESULT(DOUBLE*, LONG*); SDK flags [none], TLB flags [].",
                invocation_attempted=False,values_observed=False,
                reason="Explicit pointer ownership, initialization, output direction and HRESULT behavior are not established by an existing qualified reader. No guessed tuple or native invocation."),
            dict(code="ENUM_BINDINGS_UNDOCUMENTED",
                members=["GetEntryExitType","DepthMethod","PocketMethod","GetContainType","GetRetractType"],
                reason="Strict LONG values retained. Similar enum names do not prove method-to-enum correspondence."),
            dict(code="NUMERIC_UNITS_AND_COORDINATE_FRAME_UNDOCUMENTED",
                reason="Raw scalar/VARIANT values and percentage flags retained. No degree/radian, millimetre/inch, percent-basis or coordinate-frame conversion."),
        ]
        result.update(parameter_reads_complete=True,native_getter_calls=diagnostic["native_getter_calls"],
            interface_queries=diagnostic["interface_queries"])
        diagnostic.update(read_complete=True,stage="complete")
        return result
    except Exception as exc:
        diagnostic.update(read_complete=False,failure_type=type(exc).__name__,
            failed_stage=diagnostic["stage"],automatic_retry=False)
        raise

