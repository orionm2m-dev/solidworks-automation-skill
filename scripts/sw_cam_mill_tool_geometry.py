"""Callback-only full MILL tool and holder observation; no assignment or setters.

Caller supplies an already typed ICWTool and its unchanged generic snapshot.
All values remain raw native scalars. Profiles use the existing bounded decoder;
no QI fallback, geometric reconstruction, unit inference, or physical qualification.
"""
from copy import deepcopy
import math
from scripts.sw_cam_mill_inventory_geometry import read_segment_chains, _available
from scripts.sw_cam_mill_units_qualification import _nonnull


def _integer(value,label,low=-0x80000000,high=0x7FFFFFFF):
    if type(value) is not int or not low<=value<=high:
        raise ValueError('Strict bounded native integer required: '+label)
    return value


def _scalar(value,label):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise ValueError('Finite nonnegative raw native scalar required: '+label)
    return value


def _text(value,label):
    if type(value) is not str or len(value)>4096:
        raise ValueError('Bounded native BSTR required: '+label)
    return value


def read_full_mill_tool(tool, *, generic, read, typed, diagnostic):
    """Extend an existing generic snapshot without rereading its native getters.

    read(obj, member, *args) and typed(raw, interface_name) are guarded callbacks.
    geometry_read_complete means all requested observations completed; null
    profiles remain explicit and leave profile_complete false. Neither flag
    establishes actual physical tool/holder identity, units or clearance.
    """
    if type(diagnostic) is not dict or type(generic) is not dict:
        raise ValueError('Generic snapshot and diagnostic dictionaries required')
    row=dict(geometry_read_complete=False,profile_complete=False,mill_tool={},holder={},profiles={},
        geometry_origin='native_observed_unqualified',units_verified=False,
        physical_tool_identity_verified=False,holder_geometry_verified=False,
        holder_clearance_verified=False,closed_loops_verified=False,production_qualified=False)
    diagnostic.update(capture_complete=False,state=row,stage='begin')
    def get(obj,name,*args):
        diagnostic['stage']=name
        return read(obj,name,*args)
    def qi(raw,name):
        diagnostic['stage']='QI '+name
        _nonnull(raw,name+' raw')
        return _nonnull(typed(raw,name),name)
    try:
        if not _available(tool,'already typed ICWTool'):
            raise ValueError('Existing typed ICWTool required')
        if generic.get('is_mill_tool') is not True or generic.get('native_read_complete') is not True:
            raise ValueError('Completed generic MILL tool observation required')
        row['tool_native_id']=_integer(generic.get('native_id'),'tool native ID',1,0xFFFFFFFF)
        row['tool_type_raw']=_integer(generic.get('tool_type_raw'),'ToolType')
        row['cut_diameter_native']=_scalar(generic.get('cut_diameter_native'),'CutDiameter')
        if row['cut_diameter_native']<=0:raise ValueError('Positive native cutting diameter required')
        row['tool_protrusion_native']=_scalar(generic.get('protrusion_native'),'tool Protrusion')
        mill=qi(tool,'ICWMillTool')
        for key,name,kind in (
            ('type_raw','MillToolType','enum'),('subtype_raw','MillToolSubType','enum'),
            ('effective_cutting_length_native','EffCutlength','scalar'),('shank_diameter_native','ShankDia','scalar'),
            ('overall_length_native','OverallLen','scalar'),('end_radius_native','EndRadius','scalar'),
            ('flute_count_raw','NoOfFlutes','flutes'),('shoulder_length_native','ShoulderLength','scalar'),
            ('shank_type_raw','MillToolShankType','enum'),('shoulder_diameter_native','ShoulderDia','scalar'),
            ('shank_length_native','ShankLength','scalar')):
            value=get(mill,name)
            row['mill_tool'][key]=(_integer(value,name,0,1024) if kind=='flutes' else
                _integer(value,name) if kind=='enum' else _scalar(value,name))
        holder=qi(get(tool,'IGetMillToolHolder'),'ICWMillToolHolder')
        row['holder']['holder_id_raw']=_integer(get(holder,'GetHolderId'),'GetHolderId')
        for key,name in (('number','GetHolderNumber'),('shape','GetHolderShape'),('type','GetHolderType'),
                ('specification','GetHolderSpec'),('name','GetName')):
            row['holder'][key]=_text(get(holder,name),name)
        for key,name in (('top_diameter_native','GetHolderTopDia'),('bottom_diameter_native','GetHolderBottomDia'),
                ('overall_length_native','GetHolderOverallLength'),('bottom_length_native','GetHolderBottomLength'),
                ('holder_protrusion_native','GetProtrusion')):
            row['holder'][key]=_scalar(get(holder,name),name)
        budget=dict(curves=0,chains=0,islands=0)
        row['profile_budget']=budget
        for key,owner,method in (('tool',tool,'GetToolProfile'),('shank',tool,'GetShankProfile'),
                ('holder',holder,'GetHolderProfile')):
            out={};row['profiles'][key]=out
            read_segment_chains(owner,method,read=get,typed=qi,diagnostic={'state':out},budget=budget)
        row['profile_complete']=all(p['status']=='observed' for p in row['profiles'].values())
        row['geometry_read_complete']=True
        diagnostic.update(capture_complete=True,stage='complete')
        return deepcopy(row)
    except Exception as exc:
        diagnostic.update(capture_complete=False,issue=dict(type=type(exc).__name__,message=str(exc)[:2048]))
        raise
