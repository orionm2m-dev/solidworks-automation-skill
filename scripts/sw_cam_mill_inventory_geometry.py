"""Bounded callback-only MILL contour/island observations, with no mutation owner.

Reuses the established strict numeric/vector/interface validators and the exact
LINE/ARC/CIRCLE getters used by the existing MILL qualification reader. Spline3
adds bounded typed metadata and native facet observations of unknown tolerance;
no unmanaged control-point/knot pointers or geometry reconstruction. Islands
are a candidate ICWDispatchCollection representation, not natively qualified:
there is one QI attempt, no alternative representation or unsafe face-array read.
Limits: 64 islands per feature, 32 chains per contour, 256 curves per chain,
8192 curves across the caller's capture. Shared budget counters never roll back.
"""
from ctypes import byref, c_int
from scripts.sw_cam_mill_units_qualification import _number, _strict_integer, _nonnull
from scripts.sw_cam_mill_qualification import _vector

MAX_ISLANDS = 64
MAX_CHAINS = 32
MAX_CURVES_PER_CHAIN = 256
MAX_TOTAL_CURVES = 8192
MAX_SPLINE_FACETS = 256
MAX_SPLINE_CONTROL_POINTS = 4096
MAX_SPLINE_DEGREE = 32
_CONTOURS = (('top', 'IGetTopSegChain'), ('bottom', 'IGetBottomSegChain'),
             ('wall', 'IGetWallSegChain'))


def _integer(value, label, low=0, high=0xFFFFFFFF):
    value = _strict_integer(value, label)
    if not low <= value <= high:
        raise ValueError('Bounded native integer required: ' + label)
    return value


def _available(value, label):
    # An actual null interface is an observation, not an invented empty contour.
    if value is None:
        return False
    if type(value) in (bool, int, float, str, bytes, list, tuple, dict):
        raise ValueError('Native interface or null required: ' + label)
    return bool(value)


def read_segment_chains(owner, method, *, read, typed, diagnostic, budget):
    """Observe one native chain list; preserve partial state and shared budgets.

    Return the established contour dictionary. A pre-attached diagnostic['state']
    dictionary is reused so owning feature/tool diagnostics retain partial reads.
    Null is observed_not_available; unsupported types/counts/QI stop immediately.
    """
    if type(diagnostic) is not dict or type(budget) is not dict:
        raise ValueError('Caller diagnostic and shared budget dictionaries required')
    for key in ('curves', 'chains', 'islands'):
        _integer(budget.get(key), 'budget.' + key, high=0x7FFFFFFF)
    if budget['curves'] > MAX_TOTAL_CURVES:
        raise ValueError('Global curve budget already exhausted')
    if type(method) is not str or not method:
        raise ValueError('Exact native chain getter name required')
    out = diagnostic.setdefault('state', {})
    if type(out) is not dict:
        raise ValueError('Contour diagnostic state dictionary required')
    diagnostic.update(capture_complete=False, stage='begin')

    def get(obj, member, *args):
        diagnostic['stage'] = member
        return read(obj, member, *args)

    def qi(value, interface):
        diagnostic['stage'] = 'QI ' + interface
        _nonnull(value, interface + ' raw')
        # No catch/retry/fallback: an unsupported collection is a hard stop.
        return _nonnull(typed(value, interface), interface)

    def position(value):
        return _vector(get(qi(value, 'ICWPosition'), 'GetCoordinates'))

    def normal(value):
        return _vector(get(qi(value, 'ICWUnitVector'), 'GetCoordinates'))

    def curve(raw_curve, out, *, facet=False):
        native = qi(raw_curve, 'ICWCurve')
        kind = _integer(get(native, 'GetTypeOfCurve'), 'GetTypeOfCurve')
        out['curve_type'] = kind
        if facet and kind not in (0, 1, 2):
            raise ValueError('Spline facets require one analytic LINE/ARC/CIRCLE; no recursive spline')
        if kind == 0:
            out['start_native'] = position(get(native, 'GetStart'))
            out['end_native'] = position(get(native, 'GetEnd'))
        elif kind == 1:
            arc = qi(native, 'ICWArc')
            out['start_native'] = position(get(native, 'GetStart'))
            out['end_native'] = position(get(native, 'GetEnd'))
            out['mid_native'] = position(get(native, 'GetMid'))
            out['centre_native'] = position(get(arc, 'CenterPoint'))
            out['radius_native'] = _number(get(arc, 'IGetRadius'))
            out['normal_native'] = normal(get(arc, 'IGetNormal'))
            out['sense_raw'] = _integer(get(arc, 'IGetSense'), 'IGetSense', -0x80000000, 0x7FFFFFFF)
        elif kind == 2:
            circle = qi(native, 'ICWCircle')
            out['centre_native'] = position(get(circle, 'CenterPoint'))
            out['radius_native'] = _number(get(circle, 'GetRadius'))
            out['normal_native'] = normal(get(circle, 'IGetNormal'))
            out['direction_raw'] = _integer(get(circle, 'GetDirection'), 'GetDirection', -0x80000000, 0x7FFFFFFF)
        elif kind == 3:
            spline = qi(native, 'ICWSpline')
            out.update(representation='native_spline_metadata_and_facets',
                geometry_exact=False, approximation_tolerance_native=None,
                approximation_tolerance_status='native_facet_tolerance_not_exposed',
                exact_control_points_read=False, exact_knots_read=False,
                facets=[], facets_status='reading')
            count = _integer(get(spline, 'GetNumOfFacet'), 'GetNumOfFacet', 0, MAX_SPLINE_FACETS)
            out['declared_facet_count'] = count
            # Indexed spline observations share the same total curve budget.
            if budget['curves'] + count > MAX_TOTAL_CURVES:
                raise ValueError('Global curve/facet budget exceeded before facet reads')
            out['control_point_count_raw'] = _integer(get(spline, 'IGetNumControlPoints'),
                'IGetNumControlPoints', 1, MAX_SPLINE_CONTROL_POINTS)
            out['degree_raw'] = _integer(get(spline, 'GetDegree'), 'GetDegree', 1, MAX_SPLINE_DEGREE)
            out['order_raw'] = _integer(get(spline, 'GetOrder'), 'GetOrder', 2, MAX_SPLINE_DEGREE + 1)
            out['dimension_raw'] = _integer(get(spline, 'IGetDimension'), 'IGetDimension', 1, 4)
            # Declared INT flags are retained as raw signed scalars, not coerced bools.
            out['periodic_raw'] = _integer(get(spline, 'GetIsPeriodic'), 'GetIsPeriodic', -0x80000000, 0x7FFFFFFF)
            out['rational_raw'] = _integer(get(spline, 'IGetIsRational'), 'IGetIsRational', -0x80000000, 0x7FFFFFFF)
            out['start_parameter_raw'] = _number(get(spline, 'IGetStartParam'))
            out['end_parameter_raw'] = _number(get(spline, 'IGetEndParam'))
            out['start_native'] = position(get(native, 'GetStart'))
            out['end_native'] = position(get(native, 'GetEnd'))
            for facet_index in range(count):
                item = dict(index=facet_index, read_complete=False)
                out['facets'].append(item)
                budget['curves'] += 1
                native_index = c_int(facet_index)
                curve(get(spline, 'GetFacetAtIndex', byref(native_index)), item, facet=True)
            if _integer(get(spline, 'GetNumOfFacet'), 'GetNumOfFacet', 0, MAX_SPLINE_FACETS) != count:
                raise ValueError('Native spline facet count changed during read')
            if _integer(get(spline, 'IGetNumControlPoints'), 'IGetNumControlPoints', 1, MAX_SPLINE_CONTROL_POINTS) != out['control_point_count_raw']:
                raise ValueError('Native spline control-point count changed during read')
            out['facets_status'] = 'observed_unknown_tolerance' if count else 'observed_no_facets'
        else:
            raise ValueError('Unsupported native curve type: ' + str(kind))
        if kind in (1, 2) and out['radius_native'] <= 0:
            raise ValueError('Positive measured native radius required')
        out['read_complete'] = True

    def contour(owner, method, out):
        out.update(status='reading', declared_chain_count=None, chains=[])
        first_raw = get(owner, method)
        if not _available(first_raw, method):
            out['status'] = 'observed_not_available'
            return
        first = qi(first_raw, 'ICWSegChain')
        count = _integer(get(first, 'IGetNumChains'), 'IGetNumChains', 1, MAX_CHAINS)
        out['declared_chain_count'] = count
        current_raw, current = first_raw, first
        seen = []
        for index in range(count):
            if any(current_raw is previous for previous in seen):
                raise ValueError('Repeated contour-chain object before declared end')
            seen.append(current_raw)
            if index:
                current = qi(current_raw, 'ICWSegChain')
            chain = dict(index=index, curves=[], read_complete=False)
            out['chains'].append(chain)
            budget['chains'] += 1
            ncurves = _integer(get(current, 'GetNumOfCurves'), 'GetNumOfCurves', 1, MAX_CURVES_PER_CHAIN)
            chain['declared_curve_count'] = ncurves
            if budget['curves'] + ncurves > MAX_TOTAL_CURVES:
                raise ValueError('Global curve budget exceeded before curve reads')
            for curve_index in range(ncurves):
                if budget['curves'] >= MAX_TOTAL_CURVES:
                    raise ValueError('Global curve/facet budget exhausted before next curve')
                entry = dict(index=curve_index, read_complete=False)
                chain['curves'].append(entry)
                budget['curves'] += 1
                native_index = c_int(curve_index)
                curve(get(current, 'GetCurveAtIndex', byref(native_index)), entry)
            if _integer(get(current, 'GetNumOfCurves'), 'GetNumOfCurves', 1, MAX_CURVES_PER_CHAIN) != ncurves:
                raise ValueError('Native curve count changed during read')
            chain['read_complete'] = True
            following = get(current, 'IGetNextChain')
            present = _available(following, 'IGetNextChain')
            if index + 1 < count:
                if not present:
                    raise ValueError('Contour ended before declared chain count')
                current_raw = following
            elif present:
                raise ValueError('Contour contains undeclared extra chain')
        if _integer(get(first, 'IGetNumChains'), 'IGetNumChains', 1, MAX_CHAINS) != count:
            raise ValueError('Native chain count changed during read')
        out['status'] = 'observed'

    try:
        contour(owner, method, out)
        diagnostic.update(capture_complete=True, stage='complete')
        return out
    except Exception as exc:
        diagnostic.update(capture_complete=False, issue=dict(type=type(exc).__name__, message=str(exc)))
        raise


def read_mill_feature(raw, *, read, typed, object_id, diagnostic, budget):
    """Read one feature. Caller owns identity, event guard, persistence and reads.

    Callback signatures: read(obj, member, *args), typed(raw, interface_name),
    object_id(raw). The diagnostic receives serializable partial state before
    each read; exceptions propagate so a partial capture cannot authorize work.
    Null contour pointers are explicitly unavailable. Successful reading does
    not prove closed loops, nesting, physical depth, units, or manufacturing use.
    """
    if type(diagnostic) is not dict or type(budget) is not dict:
        raise ValueError('Caller diagnostic and shared budget dictionaries required')
    for key in ('curves', 'chains', 'islands'):
        _integer(budget.get(key), 'budget.' + key, high=0x7FFFFFFF)
    if budget['curves'] > MAX_TOTAL_CURVES:
        raise ValueError('Global curve budget already exhausted')
    row = dict(contours={}, islands={}, geometry_origin='native_observed_unqualified',
               physical_depth_verified=False, closed_loops_verified=False,
               island_nesting_verified=False)
    diagnostic.update(capture_complete=False, state=row, stage='begin')

    def get(obj, member, *args):
        diagnostic['stage'] = member
        return read(obj, member, *args)

    def qi(value, interface):
        diagnostic['stage'] = 'QI ' + interface
        _nonnull(value, interface + ' raw')
        # No catch/retry/fallback: an unsupported collection is a hard stop.
        return _nonnull(typed(value, interface), interface)

    def position(value):
        return _vector(get(qi(value, 'ICWPosition'), 'GetCoordinates'))

    def contours(owner, out):
        for name, method in _CONTOURS:
            out[name] = {}
            read_segment_chains(owner, method, read=get, typed=qi,
                diagnostic={'state': out[name]}, budget=budget)

    def islands(feature, out):
        out.update(status='reading', items=[], collection_representation_qualified=False)
        count = _integer(get(feature, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS)
        out['declared_count'] = count
        raw_collection = get(feature, 'IGetIslands')
        if not _available(raw_collection, 'IGetIslands'):
            out.update(collection_representation_observed='null', collection_count=None)
            if count:
                raise ValueError('Positive island count returned a null collection')
            if _integer(get(feature, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS) != count:
                raise ValueError('Native island count changed during read')
            out['status'] = 'observed_no_islands'
            return
        out['collection_representation_attempted'] = 'ICWDispatchCollection'
        collection = qi(raw_collection, 'ICWDispatchCollection')
        observed = _integer(get(collection, 'Count'), 'island collection Count', 0, MAX_ISLANDS)
        out.update(collection_count=observed, collection_representation_observed='ICWDispatchCollection')
        if observed != count:
            raise ValueError('Island collection count differs from feature declaration')
        for index in range(count):
            entry = dict(index=index, contours={}, read_complete=False)
            out['items'].append(entry)
            budget['islands'] += 1
            island = qi(get(collection, 'Item', index), 'ICWIslandInfo')
            entry['start_native'] = position(get(island, 'GetStartPosition'))
            entry['depth_native'] = _number(get(island, 'GetDepth'))
            contours(island, entry['contours'])
            entry['read_complete'] = True
        if (_integer(get(collection, 'Count'), 'island collection Count', 0, MAX_ISLANDS) != count or
                _integer(get(feature, 'IGetIslandCount'), 'IGetIslandCount', 0, MAX_ISLANDS) != count):
            raise ValueError('Native island count changed during read')
        out['status'] = 'observed'

    try:
        base = qi(raw, 'ICWFeature')
        feature = qi(raw, 'ICWMillFeature')
        diagnostic['stage'] = 'feature native ID'
        row['native_id'] = _integer(object_id(base), 'feature native ID', 1)
        row['volume_type'] = _integer(get(feature, 'VolumeType'), 'VolumeType')
        row['subtype_raw'] = _integer(get(feature, 'SubType'), 'SubType')
        row['shape_raw'] = _integer(get(feature, 'Shape'), 'Shape')
        suppressed = get(base, 'Suppressed')
        if type(suppressed) is not bool:
            raise ValueError('Strict native feature suppression flag required')
        row['suppressed'] = suppressed
        name = get(base, 'FeatureName')
        if type(name) is not str or len(name) > 1024:
            raise ValueError('Bounded native feature name required')
        row['name'] = name
        row['axis_native'] = _vector(get(base, 'Axis'))
        row['depth_native'] = _number(get(feature, 'Depth'))
        row['bounds_native'] = _vector(get(feature, 'GetBoundParams'))
        row['start_native'] = _vector(get(feature, 'GetStartPosition'))
        contours(feature, row['contours'])
        islands(feature, row['islands'])
        diagnostic.update(capture_complete=True, stage='complete')
        return row
    except Exception as exc:
        diagnostic.update(capture_complete=False, issue=dict(type=type(exc).__name__, message=str(exc)))
        raise
