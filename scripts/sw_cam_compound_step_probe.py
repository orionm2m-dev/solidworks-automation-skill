"""Bounded interior step observation; indexing convention remains unqualified."""
import math

def finite(value):
    if type(value) not in (float, int) or not math.isfinite(value) or abs(value)>=1e6:
        raise ValueError('Finite bounded native dimension required')
    return value

def _read_step(obj, *, count, read, typed, index=1):
    if type(count) is not int or not 3<=count<=64:
        raise ValueError('Interior index1 probe requires at least three steps')
    if type(index) is not int or index not in (0,1,2):raise ValueError('Explicit three-step probe index required')
    kind=read(obj,'GetTypeAtStep',index)
    if type(kind) is not int or kind not in (1,2):
        raise ValueError('Only observed cylinder or cone step is supported; no fallback')
    method='GetCylParams' if kind==1 else 'GetConeParams'
    raw=read(obj,method,index)
    if not isinstance(raw,(list,tuple)) or len(raw)!=(3 if kind==1 else 7):
        raise ValueError('Unexpected typed step parameter return shape')
    pos_index=2 if kind==1 else 4
    if raw[pos_index] is None:raise ValueError('Missing native step start position')
    pos=typed(raw[pos_index],'ICWPosition')
    xyz=read(pos,'GetCoordinates')
    if not isinstance(xyz,(list,tuple)) or len(xyz)!=3:raise ValueError('Position must have three values')
    out=dict(index=index,type_raw=kind,method=method,start_native=[finite(v) for v in xyz])
    if kind==1:
        out.update(diameter_native=finite(raw[0]),depth_native=finite(raw[1]))
    else:
        if type(raw[5]) is not bool:raise ValueError('Strict native cone apex flag required')
        out.update(bottom_diameter_native=finite(raw[0]),top_diameter_native=finite(raw[1]),
            cone_depth_native=finite(raw[2]),depth_native=finite(raw[3]),
            cone_at_apex=raw[5],taper_angle_native=finite(raw[6]))
    after=read(obj,'GetTypeAtStep',index)
    if type(after) is not int or after!=kind:raise ValueError('Step type changed during read')
    return dict(observed_steps=[out],step_dimensions_read=True,
        complete_step_coverage=False,index_base_verified=False,
        index_policy='EXPLICIT_INTERIOR_INDEX1_PROBE_NO_ENDPOINT_OR_FALLBACK',
        units_verified=False,coordinate_frame_verified=False,
        physical_geometry_verified=False,production_qualified=False)

def read_interior_step(obj, *, count, read, typed):
    return _read_step(obj,count=count,read=read,typed=typed,index=1)

def read_three_step_profile(obj, *, count, read, typed):
    if type(count) is not int or count!=3:
        raise ValueError('Exact three-step qualification required')
    values=[]
    for index in (0,1,2):
        result=_read_step(obj,count=count,read=read,typed=typed,index=index)
        values.extend(result['observed_steps'])
    starts=[tuple(row['start_native']) for row in values]
    if len(set(starts))!=3:raise ValueError('Step starts must be distinct')
    return dict(observed_steps=values,step_dimensions_read=True,complete_step_coverage=True,
        index_base_verified=True,index_base_observed=0,
        index_contract_scope='Observed valid indices0..2 for this exact three-step feature only',
        index_policy='EXPLICIT_THREE_STEP_PROFILE_NO_FALLBACK',
        units_verified=False,coordinate_frame_verified=False,physical_geometry_verified=False,
        production_qualified=False)
