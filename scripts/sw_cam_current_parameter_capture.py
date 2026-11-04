"""Bounded own-operation and existing tool observations for a current saved batch.

No authority loading, connections, setters or persistence. Caller owns source,
lifetime, runtime and event guards around every supplied read/typed callback.
"""
from copy import deepcopy
import math
from scripts import sw_cam_mill_current_parameters as parameters
from scripts.sw_cam_mill_append_delta import _inventory
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_route_context import integer,read_generic_tool
from scripts.sw_cam_guide_group_parameters import read_tool_dimensions
from scripts.sw_cam_chamfer_nc_planes import scalar

PREFLIGHT_INTERFACES=('ICWPartDoc','ICWMachine','ICWToolcrib4','ICWTool','ICWNCParam','ICWNCParam2')
NC_FIELDS=(('GetSpndlSpeed','ICWNCParam','double'),('XYFeed','ICWNCParam2','double'),('GetCNCComp','ICWNCParam','long'),('GetTlpComp','ICWNCParam','long'))

def require(ok,message):
    if not ok:raise ValueError(message)

def tool_generic(raw,doc,read,typed):
    tool=typed(raw,'ICWTool')
    out=dict(native_id=integer(_object_id(doc,tool,read),'tool identity',1),is_mill_tool=read(tool,'IsMillTool'),native_read_complete=False,units_verified=False,holder_geometry_verified=False)
    require(out['is_mill_tool'] is True,'Explicit MILL crib tool required')
    out['tool_type_raw']=integer(read(tool,'ToolType'),'ToolType')
    for key,name in (('cut_diameter_native','CutDiameter'),('protrusion_native','Protrusion')):
        value=read(tool,name)
        require(type(value) in (int,float) and math.isfinite(value) and value>=0,'Finite nonnegative crib tool scalar required')
        out[key]=value
    require(out['cut_diameter_native']>0,'Positive crib tool diameter required')
    out['native_read_complete']=True
    return out,tool

def own_operation(row,native,read,typed):
    doc=native['doc'];oid=row['native_id'];raw=native['operations'][oid]
    found=read(doc,'GetCWObjectFromID',3,oid)
    require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact consumer operation lookup required')
    for candidate in (raw,found[0]):
        operation=typed(candidate,'ICWOperation');mill=typed(candidate,'ICWMillOperation')
        kind=read(mill,'OpernType')
        require(_object_id(doc,operation,read)==oid and type(kind) is int,'Strict consumer operation identity required')
        require(kind==row['mill_operation_type'] and read(operation,'Suppressed') is row['suppressed'] and read(operation,'GetIsToolpathGenerated') is row['toolpath_generated'],'Consumer operation flags differ')
        links=[_object_id(doc,x,read) for x in _items(read(operation,'IGetAllFeatures'),typed,read,64)]
        require(links==row['linked_feature_ids'],'Consumer feature links differ')
        generic,_=read_generic_tool(operation,doc,read,typed)
        require(generic==row['assigned_tool'],'Consumer own assigned tool differs')
    return raw

def read_own_nc(raw,out,*,read,typed,boundary):
    out.update(read_complete=False,feeds_compensation={},physical_units_qualified=False,cutting_conditions_qualified=False,tool_defaults_read=False,full_parameters_read=False)
    boundary();owner=read(typed(raw,'ICWMillOperation'),'IGetNCParam')
    require(owner is not None and bool(owner),'Non-null own NC object required')
    interfaces={}
    for name,interface,kind in NC_FIELDS:
        if interface not in interfaces:interfaces[interface]=typed(owner,interface)
        value=read(interfaces[interface],name)
        out['feeds_compensation'][name]=scalar(kind,value)
        boundary()
    out['read_complete']=True
    return out

def capture_parameter_batch(state,native,targets,*,feature_id,candidate_tool_native_id,expected_candidate_consumer_ids,read,typed,boundary):
    """Append actual parameters, toolcrib witnesses and operation-owned NC rows.

    Candidate consumers are ALL route consumers, in route order. Their NC values
    are operation observations, never tool defaults or recommended cutting data.
    """
    integer(feature_id,'feature ID',1);integer(candidate_tool_native_id,'candidate tool ID',1)
    rows,_=_inventory(state);ids=[r['native_id'] for r in rows]
    require(state.get('capture_complete') is True and set(native['operations'])==set(ids),'Complete current route handles required')
    require(type(targets) is list and len(targets)==2,'Explicit rough/finish pair required')
    require(type(expected_candidate_consumer_ids) is list and all(type(i) is int and 0<i<2**32 for i in expected_candidate_consumer_ids) and len(set(expected_candidate_consumer_ids))==len(expected_candidate_consumer_ids),'Strict ordered candidate usage IDs required')
    selected=[]
    for kind,row in enumerate(targets):
        matches=[r for r in rows if r['native_id']==row['native_id']]
        require(len(matches)==1 and matches[0]==row and type(row['mill_operation_type']) is int and row['mill_operation_type']==kind and row['linked_feature_ids']==[feature_id] and row['suppressed'] is False and row['toolpath_generated'] is False and row['toolpath_record_counts']==[],'Exact ungenerated current own rough/finish targets required')
        selected.append(deepcopy(row))
    require(selected[0]['native_id']!=selected[1]['native_id'] and selected[0]['setup_native_id']==selected[1]['setup_native_id'],'Distinct targets in one setup required')
    consumers=[r for r in rows if r['assigned_tool']['native_id']==candidate_tool_native_id]
    require([r['native_id'] for r in consumers]==expected_candidate_consumer_ids,'Candidate tool usage differs from pinned current route')
    out=dict(read_complete=False,candidate_tool=None,toolcrib_catalogue=[],source_tools={},target_nc={},candidate_consumers={},candidate_consumer_ids=list(expected_candidate_consumer_ids),full_tool_profiles_read=False,physical_tool_qualified=False,native_units_verified=False)
    state['parameter_batch']=out
    boundary();require(_object_id(native['doc'],native['selected_feature'],read)==feature_id,'Exact native parameter feature required')
    parameters.capture_rows(state,native,selected,feature_id=feature_id,read=read,typed=typed,boundary=boundary)
    class Batch:
        def read(self,*a):return read(*a)
        def typed(self,*a):return typed(*a)
    batch=Batch();doc=native['doc'];boundary()
    machine=typed(read(typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    crib=typed(read(machine,'IGetToolcrib'),'ICWToolcrib4')
    all_tools=_items(read(crib,'GetAllTools'),typed,read,64)
    tool_cache={};seen=set();wanted={r['assigned_tool']['native_id'] for r in selected}|{candidate_tool_native_id}
    for raw in all_tools:
        boundary();generic,tool=tool_generic(raw,doc,read,typed);tid=generic['native_id']
        require(tid not in seen,'Duplicate native toolcrib identity');seen.add(tid);out['toolcrib_catalogue'].append(generic)
        if tid in wanted:tool_cache[tid]=read_tool_dimensions(tool,generic,batch)
    require(wanted<=set(tool_cache),'Candidate and source tools must exist in the same bounded document toolcrib')
    for row,observed in zip(selected,state['operation_parameters']):
        tid=row['assigned_tool']['native_id'];value=tool_cache[tid]
        require(value==observed['tool'],'Crib/source own full dimensions differ')
        out['source_tools'][str(tid)]=deepcopy(value)
        oid=row['native_id'];nc=dict(operation_native_id=oid);out['target_nc'][str(oid)]=nc
        read_own_nc(own_operation(row,native,read,typed),nc,read=read,typed=typed,boundary=boundary)
    out['candidate_tool']=deepcopy(tool_cache[candidate_tool_native_id])
    for row in consumers:
        boundary();oid=row['native_id'];raw=own_operation(row,native,read,typed)
        generic,tool=read_generic_tool(raw,doc,read,typed)
        require(read_tool_dimensions(tool,generic,batch)==out['candidate_tool'],'Candidate consumer tool dimensions differ from crib')
        observed=dict(operation_native_id=oid,assigned_tool_native_id=candidate_tool_native_id);out['candidate_consumers'][str(oid)]=observed
        read_own_nc(raw,observed,read=read,typed=typed,boundary=boundary)
    boundary();out['read_complete']=True
    return out
